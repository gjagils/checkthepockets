"""
Bunq CSV parser.

Bunq exports transactions as semicolon-separated CSV with a header row:
  "Date";"Amount";"Account";"Counterparty";"Name";"Description"

- Date format: YYYY-MM-DD
- Amount: decimal point, negative for debits
- Encoding: UTF-8
"""

import csv
import io
from datetime import datetime
from decimal import Decimal

from app.parsers.base import ParsedTransaction, ParseError

REQUIRED_HEADERS = {"date", "amount", "account"}


def _normalize_headers(headers: list[str]) -> dict[str, int]:
    """Map lowercase header names to column indices."""
    mapping = {}
    for i, h in enumerate(headers):
        mapping[h.strip().strip('"').lower()] = i
    return mapping


def parse(file_content: bytes) -> tuple[str | None, list[ParsedTransaction]]:
    """Parse Bunq CSV export. Returns (iban, transactions)."""
    text = file_content.decode("utf-8-sig")

    # Detect delimiter (Bunq uses semicolons, but some versions use commas)
    first_line = text.split("\n")[0]
    delimiter = ";" if ";" in first_line else ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header_row = next(reader, None)
    if header_row is None:
        raise ParseError("Leeg bestand")

    cols = _normalize_headers(header_row)

    missing = REQUIRED_HEADERS - set(cols.keys())
    if missing:
        raise ParseError(f"Ontbrekende kolommen: {', '.join(missing)}")

    date_col = cols["date"]
    amount_col = cols["amount"]
    account_col = cols["account"]
    counterparty_col = cols.get("counterparty")
    name_col = cols.get("name")
    description_col = cols.get("description")

    transactions: list[ParsedTransaction] = []
    iban = None

    for line_num, row in enumerate(reader, 2):
        if not row or all(cell.strip() == "" for cell in row):
            continue

        try:
            account = row[account_col].strip()
            if iban is None and account:
                iban = account

            # Handle multiple date formats
            date_str = row[date_col].strip()
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                try:
                    tx_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Onbekend datumformaat: {date_str}")

            amount_str = row[amount_col].strip().replace(",", ".")
            amount = Decimal(amount_str)

            counterparty_account = (
                row[counterparty_col].strip() if counterparty_col is not None else None
            )
            name = row[name_col].strip() if name_col is not None else None
            description = (
                row[description_col].strip() if description_col is not None else ""
            )

            transactions.append(
                ParsedTransaction(
                    date=tx_date,
                    amount=amount,
                    currency="EUR",
                    description=description,
                    counterparty=name,
                    counterparty_iban=counterparty_account or None,
                )
            )
        except (ValueError, IndexError) as e:
            raise ParseError(f"Fout bij verwerken regel {line_num}: {e}", line=line_num)

    return iban, transactions
