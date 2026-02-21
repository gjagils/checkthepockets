"""
ABN AMRO CSV/TAB parser.

ABN AMRO exports transactions as tab-separated values with these columns
(no header row):
  0: Rekeningnummer (IBAN)
  1: Muntsoort (EUR)
  2: Transactiedatum (YYYYMMDD)
  3: Rentedatum (YYYYMMDD)
  4: Beginsaldo (signed, comma decimal)
  5: Eindsaldo (signed, comma decimal)
  6: Bedrag (signed, comma decimal)
  7: Omschrijving (free text)

Encoding is typically Windows-1252 (Latin-1).
"""

import csv
import io
from datetime import datetime
from decimal import Decimal

from app.parsers.base import ParsedTransaction, ParseError

EXPECTED_MIN_COLS = 8


def _parse_dutch_decimal(value: str) -> Decimal:
    """Parse a Dutch-style number like '1.234,56' or '-1234,56'."""
    cleaned = value.strip().replace(".", "").replace(",", ".")
    return Decimal(cleaned)


def _extract_counterparty(description: str) -> tuple[str | None, str | None]:
    """Try to extract counterparty name and IBAN from the description field."""
    counterparty = None
    counterparty_iban = None

    # ABN AMRO puts structured info in the description
    # Common patterns: /TRTP/... /NAME/... /IBAN/...
    parts = description.split("/")
    for i, part in enumerate(parts):
        if part.strip().upper() == "NAME" and i + 1 < len(parts):
            counterparty = parts[i + 1].strip()
        elif part.strip().upper() == "IBAN" and i + 1 < len(parts):
            counterparty_iban = parts[i + 1].strip()

    return counterparty, counterparty_iban


def parse(file_content: bytes) -> tuple[str | None, list[ParsedTransaction]]:
    """Parse ABN AMRO export file. Returns (iban, transactions)."""
    # Try UTF-8 first, fallback to Latin-1
    for encoding in ("utf-8", "latin-1"):
        try:
            text = file_content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ParseError("Kan bestand niet decoderen (niet UTF-8 of Latin-1)")

    transactions: list[ParsedTransaction] = []
    iban = None

    reader = csv.reader(io.StringIO(text), delimiter="\t")
    for line_num, row in enumerate(reader, 1):
        if not row or all(cell.strip() == "" for cell in row):
            continue

        if len(row) < EXPECTED_MIN_COLS:
            raise ParseError(
                f"Verwacht minimaal {EXPECTED_MIN_COLS} kolommen, maar {len(row)} gevonden",
                line=line_num,
            )

        try:
            account_nr = row[0].strip()
            if iban is None and account_nr:
                iban = account_nr

            tx_date = datetime.strptime(row[2].strip(), "%Y%m%d").date()
            end_balance = _parse_dutch_decimal(row[5])
            amount = _parse_dutch_decimal(row[6])
            description = row[7].strip()
            currency = row[1].strip() or "EUR"

            counterparty, counterparty_iban = _extract_counterparty(description)

            transactions.append(
                ParsedTransaction(
                    date=tx_date,
                    amount=amount,
                    currency=currency,
                    description=description,
                    counterparty=counterparty,
                    counterparty_iban=counterparty_iban,
                    balance_after=end_balance,
                )
            )
        except (ValueError, IndexError) as e:
            raise ParseError(f"Fout bij verwerken regel {line_num}: {e}", line=line_num)

    return iban, transactions
