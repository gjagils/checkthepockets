"""Generic CSV import with a user-defined column mapping (moved out of the transactions router)."""
import csv
import io
from datetime import datetime as _datetime
from decimal import Decimal, InvalidOperation

from app.parsers.base import ParsedTransaction

# Fields available for custom CSV column mapping
CUSTOM_CSV_FIELDS = [
    ("date",              "Datum *"),
    ("amount",            "Bedrag *"),
    ("description",       "Omschrijving"),
    ("counterparty",      "Tegenpartij"),
    ("counterparty_iban", "IBAN tegenpartij"),
    ("balance_after",     "Saldo na"),
    ("category",          "Categorie (naam)"),
]

DATE_FORMATS = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y%m%d"]


def csv_headers_and_preview(content: bytes) -> tuple[list[str], list[list[str]]]:
    """Return (headers, first_5_data_rows) from raw CSV bytes."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration:
        return [], []
    preview = []
    for i, row in enumerate(reader):
        if i >= 5:
            break
        preview.append(row)
    return headers, preview


def _parse_amount(raw: str):
    """'1.234,56', '1,234.56', '12,5' or '12.5' -> Decimal, or None when it is not a number."""
    raw = raw.strip().replace("\xa0", "").replace(" ", "")
    if "," in raw and "." in raw:
        if raw.rindex(",") > raw.rindex("."):      # 1.234,56
            raw = raw.replace(".", "").replace(",", ".")
        else:                                       # 1,234.56
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def parse_custom_csv(content: bytes, col_mapping: dict) -> list[ParsedTransaction]:
    """Parse a generic CSV using a user-defined column mapping. Rows without a valid date or amount are skipped."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    date_col = col_mapping.get("date", "")
    amount_col = col_mapping.get("amount", "")
    desc_col = col_mapping.get("description", "")
    cp_col = col_mapping.get("counterparty", "")
    iban_col = col_mapping.get("counterparty_iban", "")
    bal_col = col_mapping.get("balance_after", "")
    cat_col = col_mapping.get("category", "")

    parsed = []
    for row in reader:
        date_str = row.get(date_col, "").strip() if date_col else ""
        parsed_date = None
        for fmt in DATE_FORMATS:
            try:
                parsed_date = _datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                pass
        if not parsed_date:
            continue

        amount = _parse_amount(row.get(amount_col, "")) if amount_col else _parse_amount("")
        if amount is None:
            continue

        description = row.get(desc_col, "").strip() if desc_col else ""
        counterparty = row.get(cp_col, "").strip() if cp_col else ""
        iban = row.get(iban_col, "").strip() if iban_col else ""
        category_name = row.get(cat_col, "").strip() if cat_col else ""

        balance = None
        if bal_col:
            bal_raw = row.get(bal_col, "").strip().replace(",", ".").replace(" ", "")
            try:
                balance = Decimal(bal_raw)
            except InvalidOperation:
                pass

        transaction = ParsedTransaction(
            date=parsed_date,
            amount=amount,
            currency="EUR",
            description=description or None,
            counterparty=counterparty or None,
            counterparty_iban=iban or None,
            balance_after=balance,
        )
        transaction._category_name = category_name  # type: ignore[attr-defined]
        parsed.append(transaction)
    return parsed
