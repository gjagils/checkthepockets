"""
ICS (International Card Services) CSV parser.

ICS exports credit card transactions as comma-separated CSV.
The format typically has a header row with columns like:
  Datum, Omschrijving, Valuta, Bedrag, Mut.soort (or similar)

Variations exist, so this parser is flexible with column detection.

- Date format: DD-MM-YYYY or YYYYMMDD
- Amount: comma as decimal separator (Dutch locale)
  - Purchases are positive, payments/refunds are negative
  - Or amounts are always positive with a separate debit/credit column
- Encoding: Latin-1 or UTF-8
- May have header lines to skip before the actual CSV data
"""

import csv
import io
from datetime import datetime
from decimal import Decimal

from app.parsers.base import ParsedTransaction, ParseError

# Possible column name variations (lowercase)
DATE_COLS = {"datum", "date", "transactiedatum"}
DESC_COLS = {"omschrijving", "description", "naam / omschrijving"}
AMOUNT_COLS = {"bedrag", "amount", "bedrag (eur)", "bedrag in eur"}
CURRENCY_COLS = {"valuta", "currency", "muntsoort"}


def _find_col(headers: dict[str, int], candidates: set[str]) -> int | None:
    for name in candidates:
        if name in headers:
            return headers[name]
    return None


def _parse_dutch_decimal(value: str) -> Decimal:
    cleaned = value.strip().replace(".", "").replace(",", ".")
    return Decimal(cleaned)


def _find_header_row(lines: list[str]) -> int:
    """Find the row that looks like a CSV header (contains 'datum' or 'date')."""
    for i, line in enumerate(lines):
        lower = line.lower()
        if any(col in lower for col in DATE_COLS):
            return i
    return 0


def parse(file_content: bytes) -> tuple[str | None, list[ParsedTransaction]]:
    """Parse ICS CSV export. Returns (None, transactions) - ICS has no IBAN."""
    # Try UTF-8 first, fallback to Latin-1
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = file_content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ParseError("Kan bestand niet decoderen")

    lines = text.strip().split("\n")
    if not lines:
        raise ParseError("Leeg bestand")

    # Find actual header row (ICS may have informational lines at the top)
    header_idx = _find_header_row(lines)
    csv_text = "\n".join(lines[header_idx:])

    # Detect delimiter
    first_csv_line = lines[header_idx]
    if ";" in first_csv_line:
        delimiter = ";"
    elif "\t" in first_csv_line:
        delimiter = "\t"
    else:
        delimiter = ","

    reader = csv.reader(io.StringIO(csv_text), delimiter=delimiter)
    raw_headers = next(reader, None)
    if raw_headers is None:
        raise ParseError("Geen kolomkoppen gevonden")

    cols = {h.strip().strip('"').lower(): i for i, h in enumerate(raw_headers)}

    date_col = _find_col(cols, DATE_COLS)
    desc_col = _find_col(cols, DESC_COLS)
    amount_col = _find_col(cols, AMOUNT_COLS)

    if date_col is None:
        raise ParseError("Kan kolom 'Datum' niet vinden in de kolomkoppen")
    if amount_col is None:
        raise ParseError("Kan kolom 'Bedrag' niet vinden in de kolomkoppen")

    transactions: list[ParsedTransaction] = []

    for line_num, row in enumerate(reader, header_idx + 2):
        if not row or all(cell.strip() == "" for cell in row):
            continue

        try:
            date_str = row[date_col].strip()
            for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y%m%d", "%Y-%m-%d"):
                try:
                    tx_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Onbekend datumformaat: {date_str}")

            amount = _parse_dutch_decimal(row[amount_col])
            description = row[desc_col].strip() if desc_col is not None else ""

            transactions.append(
                ParsedTransaction(
                    date=tx_date,
                    amount=amount,
                    currency="EUR",
                    description=description,
                    counterparty=None,
                    counterparty_iban=None,
                )
            )
        except (ValueError, IndexError) as e:
            raise ParseError(f"Fout bij verwerken regel {line_num}: {e}", line=line_num)

    return None, transactions
