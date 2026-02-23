"""
ING (Netherlands) CSV parser.

ING exports transactions as semicolon-separated CSV with a header row.
Common columns:
  "Datum","Naam / Omschrijving","Rekening","Tegenrekening","Code",
  "Af Bij","Bedrag (EUR)","Mutatiesoort","Mededelingen"

- Date format: YYYYMMDD
- Amount: comma decimal, always positive; "Af" = debit, "Bij" = credit
- Encoding: Latin-1 or UTF-8
"""

import csv
import io
from datetime import datetime
from decimal import Decimal

from app.parsers.base import ParsedTransaction, ParseError

# Possible column name variations (lowercase, stripped)
DATE_COLS = {"datum", "date"}
NAME_COLS = {"naam / omschrijving", "naam/omschrijving", "name", "naam"}
ACCOUNT_COLS = {"rekening", "account"}
COUNTER_COLS = {"tegenrekening", "tegenrekening iban", "counter account"}
DIRECTION_COLS = {"af bij", "af/bij", "direction"}
AMOUNT_COLS = {"bedrag (eur)", "bedrag", "amount"}
DESCRIPTION_COLS = {"mededelingen", "mededeling", "description", "omschrijving"}


def _find_col(headers: dict[str, int], candidates: set[str]) -> int | None:
    for name in candidates:
        if name in headers:
            return headers[name]
    return None


def _parse_dutch_decimal(value: str) -> Decimal:
    """Parse a Dutch-style number like '1.234,56' or '1234,56'."""
    cleaned = value.strip().replace(".", "").replace(",", ".")
    return Decimal(cleaned)


def parse(file_content: bytes) -> tuple[str | None, list[ParsedTransaction]]:
    """Parse ING CSV export. Returns (iban, transactions)."""
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
    if ";" in first_line:
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

    date_col = _find_col(cols, DATE_COLS)
    name_col = _find_col(cols, NAME_COLS)
    account_col = _find_col(cols, ACCOUNT_COLS)
    counter_col = _find_col(cols, COUNTER_COLS)
    direction_col = _find_col(cols, DIRECTION_COLS)
    amount_col = _find_col(cols, AMOUNT_COLS)
    desc_col = _find_col(cols, DESCRIPTION_COLS)

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

            # Date: YYYYMMDD or DD-MM-YYYY
            date_str = row[date_col].strip()
            for fmt in ("%Y%m%d", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                try:
                    tx_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Onbekend datumformaat: {date_str}")

            # Amount
            amount = _parse_dutch_decimal(row[amount_col])

            # Direction: "Af" = debit (negative), "Bij" = credit (positive)
            if direction_col is not None:
                direction = row[direction_col].strip().lower()
                if direction == "af":
                    amount = -abs(amount)
                elif direction == "bij":
                    amount = abs(amount)

            # Counterparty
            counterparty = row[name_col].strip() if name_col is not None else None
            counterparty_iban = (
                row[counter_col].strip() if counter_col is not None else None
            ) or None

            # Description (mededelingen)
            description = row[desc_col].strip() if desc_col is not None else ""
            # If no separate description, use counterparty name
            if not description and counterparty:
                description = counterparty

            transactions.append(
                ParsedTransaction(
                    date=tx_date,
                    amount=amount,
                    currency="EUR",
                    description=description,
                    counterparty=counterparty or None,
                    counterparty_iban=counterparty_iban,
                )
            )
        except (ValueError, IndexError) as e:
            raise ParseError(f"Fout bij verwerken regel {line_num}: {e}", line=line_num)

    return iban, transactions
