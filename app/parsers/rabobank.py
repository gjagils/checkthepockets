"""
Rabobank CSV parser.

Rabobank exports transactions as comma-separated CSV with a header row.
Common columns:
  "IBAN/BBAN","Munt","BIC","Volgnr","Datum","Rentedatum","Bedrag",
  "Saldo na trn","Tegenrekening IBAN/BBAN","Naam tegenpartij",
  "Naam uiteindelijke partij","Naam initiërende partij","BIC tegenpartij",
  "Code","Batch ID","Transactiereferentie","Machtigingskenmerk",
  "Incassant ID","Betalingskenmerk","Omschrijving-1","Omschrijving-2",
  "Omschrijving-3","Reden retour","Oorspr bedrag","Oorspr munt","Koers"

- Date format: YYYY-MM-DD
- Amount: comma decimal, can be negative (debit) or positive (credit)
- Encoding: UTF-8
"""

import csv
import io
from datetime import datetime
from decimal import Decimal

from app.parsers.base import ParsedTransaction, ParseError

# Possible column name variations (lowercase, stripped)
ACCOUNT_COLS = {"iban/bban", "iban", "rekeningnummer"}
DATE_COLS = {"datum", "date"}
AMOUNT_COLS = {"bedrag", "amount"}
BALANCE_COLS = {"saldo na trn", "saldo na transactie", "balance"}
COUNTER_IBAN_COLS = {"tegenrekening iban/bban", "tegenrekening", "tegenrekening iban"}
COUNTER_NAME_COLS = {"naam tegenpartij", "naam / omschrijving", "naam"}
DESC_COLS_1 = {"omschrijving-1", "omschrijving 1", "omschrijving"}
DESC_COLS_2 = {"omschrijving-2", "omschrijving 2"}
DESC_COLS_3 = {"omschrijving-3", "omschrijving 3"}
CURRENCY_COLS = {"munt", "valuta", "currency"}


def _find_col(headers: dict[str, int], candidates: set[str]) -> int | None:
    for name in candidates:
        if name in headers:
            return headers[name]
    return None


def _parse_dutch_decimal(value: str) -> Decimal:
    """Parse a Dutch-style number like '+1.234,56' or '-1234,56'."""
    cleaned = value.strip().lstrip("+").replace(".", "").replace(",", ".")
    return Decimal(cleaned)


def parse(file_content: bytes) -> tuple[str | None, list[ParsedTransaction]]:
    """Parse Rabobank CSV export. Returns (iban, transactions)."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = file_content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ParseError("Kan bestand niet decoderen (niet UTF-8 of Latin-1)")

    # Detect delimiter
    first_line = text.split("\n")[0]
    if ";" in first_line and first_line.count(";") > first_line.count(","):
        delimiter = ";"
    elif "\t" in first_line:
        delimiter = "\t"
    else:
        delimiter = ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header_row = next(reader, None)
    if header_row is None:
        raise ParseError("Leeg bestand")

    cols = {h.strip().strip('"').lower(): i for i, h in enumerate(header_row)}

    account_col = _find_col(cols, ACCOUNT_COLS)
    date_col = _find_col(cols, DATE_COLS)
    amount_col = _find_col(cols, AMOUNT_COLS)
    balance_col = _find_col(cols, BALANCE_COLS)
    counter_iban_col = _find_col(cols, COUNTER_IBAN_COLS)
    counter_name_col = _find_col(cols, COUNTER_NAME_COLS)
    desc1_col = _find_col(cols, DESC_COLS_1)
    desc2_col = _find_col(cols, DESC_COLS_2)
    desc3_col = _find_col(cols, DESC_COLS_3)
    currency_col = _find_col(cols, CURRENCY_COLS)

    if date_col is None:
        raise ParseError("Kan kolom 'Datum' niet vinden in de kolomkoppen")
    if amount_col is None:
        raise ParseError("Kan kolom 'Bedrag' niet vinden in de kolomkoppen")

    transactions: list[ParsedTransaction] = []
    iban = None

    for line_num, row in enumerate(reader, 2):
        if not row or all(cell.strip() == "" for cell in row):
            continue

        try:
            # Account IBAN
            if account_col is not None:
                account = row[account_col].strip()
                if iban is None and account:
                    iban = account

            # Date: YYYY-MM-DD or DD-MM-YYYY
            date_str = row[date_col].strip().strip('"')
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y%m%d", "%d/%m/%Y"):
                try:
                    tx_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Onbekend datumformaat: {date_str}")

            # Amount (already includes sign for Rabobank)
            amount = _parse_dutch_decimal(row[amount_col])

            # Balance after transaction
            balance_after = None
            if balance_col is not None:
                bal_str = row[balance_col].strip()
                if bal_str:
                    balance_after = _parse_dutch_decimal(bal_str)

            # Counterparty
            counterparty = (
                row[counter_name_col].strip() if counter_name_col is not None else None
            ) or None
            counterparty_iban = (
                row[counter_iban_col].strip() if counter_iban_col is not None else None
            ) or None

            # Description: combine omschrijving 1, 2, 3
            desc_parts = []
            for col in (desc1_col, desc2_col, desc3_col):
                if col is not None and col < len(row):
                    part = row[col].strip()
                    if part:
                        desc_parts.append(part)
            description = " ".join(desc_parts)

            # If no description, fall back to counterparty
            if not description and counterparty:
                description = counterparty

            # Currency
            currency = "EUR"
            if currency_col is not None:
                cur = row[currency_col].strip()
                if cur:
                    currency = cur.upper()

            transactions.append(
                ParsedTransaction(
                    date=tx_date,
                    amount=amount,
                    currency=currency,
                    description=description,
                    counterparty=counterparty,
                    counterparty_iban=counterparty_iban,
                    balance_after=balance_after,
                )
            )
        except (ValueError, IndexError) as e:
            raise ParseError(f"Fout bij verwerken regel {line_num}: {e}", line=line_num)

    return iban, transactions
