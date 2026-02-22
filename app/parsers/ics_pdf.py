"""
ICS (International Card Services) PDF statement parser.

Parses the PDF credit card statement into individual transactions.
Skips "GEINCASSEERD VORIG SALDO" lines.

Typical line format:
  21 dec.    22 dec.    PLUGSURFING          BERLIN         DEU                  16,10    Af
  01 jan.    02 jan.    OPENAI *CHATGPT SUBSCR  SAN FRANCISCO  USA  24,20 USD  21,06    Af
                        Wisselkoers USD       1,149100

Continuation lines (Wisselkoers) are ignored.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pdfplumber

from app.parsers.base import ParseError


MONTH_MAP = {
    "jan": 1, "feb": 2, "mrt": 3, "mar": 3, "apr": 4,
    "mei": 5, "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dec": 12,
}

# Matches: "21 dec." or "01 jan." at the start of a line
DATE_PATTERN = re.compile(r"(\d{1,2})\s+(jan|feb|mrt|mar|apr|mei|may|jun|jul|aug|sep|okt|oct|nov|dec)\.?", re.IGNORECASE)

# Matches a full transaction line: two dates, description, amount, Af/Bij
TX_LINE_PATTERN = re.compile(
    r"(\d{1,2})\s+(jan|feb|mrt|mar|apr|mei|may|jun|jul|aug|sep|okt|oct|nov|dec)\.?\s+"
    r"(\d{1,2})\s+(jan|feb|mrt|mar|apr|mei|may|jun|jul|aug|sep|okt|oct|nov|dec)\.?\s+"
    r"(.+?)\s+"
    r"([\d.,]+)\s+"
    r"(Af|Bij)\s*$",
    re.IGNORECASE,
)

SKIP_PATTERNS = [
    "GEINCASSEERD",
    "VORIG SALDO",
    "NIEUW SALDO",
    "TOTAAL",
]


@dataclass
class ICSPdfTransaction:
    """A single transaction parsed from an ICS PDF statement."""
    transaction_date: date
    booking_date: date
    description: str
    amount_eur: Decimal
    is_debit: bool  # Af = debit (expense), Bij = credit (refund)


def _parse_date(day: int, month_str: str, statement_year: int, statement_month: int) -> date:
    """Parse a day + Dutch month abbreviation into a date, inferring the year."""
    month = MONTH_MAP.get(month_str.lower())
    if not month:
        raise ParseError(f"Onbekende maand: {month_str}")

    # If the transaction month is much later than the statement month,
    # it's probably from the previous year (e.g. dec transactions on a jan statement)
    year = statement_year
    if month > statement_month + 1:
        year -= 1

    try:
        return date(year, month, day)
    except ValueError:
        raise ParseError(f"Ongeldige datum: {day} {month_str} {year}")


def _extract_statement_date(text: str) -> tuple[int, int]:
    """Extract statement year and month from the PDF header text."""
    # Look for patterns like "22 januari 2026" or "Datum: 22-01-2026"
    full_months = {
        "januari": 1, "februari": 2, "maart": 3, "april": 4,
        "mei": 5, "juni": 6, "juli": 7, "augustus": 8,
        "september": 9, "oktober": 10, "november": 11, "december": 12,
    }

    for month_name, month_num in full_months.items():
        m = re.search(rf"\d{{1,2}}\s+{month_name}\s+(\d{{4}})", text, re.IGNORECASE)
        if m:
            return int(m.group(1)), month_num

    # Try DD-MM-YYYY pattern
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", text)
    if m:
        return int(m.group(3)), int(m.group(2))

    # Fallback: try to find any 4-digit year
    m = re.search(r"20\d{2}", text)
    if m:
        from datetime import date as d
        return int(m.group()), d.today().month

    raise ParseError("Kan geen afschriftdatum vinden in de PDF")


def parse_ics_pdf(file_content: bytes) -> list[ICSPdfTransaction]:
    """Parse an ICS PDF statement into individual transactions."""
    try:
        pdf = pdfplumber.open(file_content if hasattr(file_content, 'read') else __import__('io').BytesIO(file_content))
    except Exception as e:
        raise ParseError(f"Kan PDF niet openen: {e}")

    all_text = ""
    for page in pdf.pages:
        page_text = page.extract_text()
        if page_text:
            all_text += page_text + "\n"

    pdf.close()

    if not all_text.strip():
        raise ParseError("Geen tekst gevonden in de PDF")

    # Get statement date for year inference
    statement_year, statement_month = _extract_statement_date(all_text)

    transactions: list[ICSPdfTransaction] = []
    lines = all_text.split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip header/footer/summary lines
        if any(skip in line.upper() for skip in SKIP_PATTERNS):
            continue

        # Skip continuation lines (Wisselkoers, etc.)
        if line.startswith("Wisselkoers") or line.startswith("wisselkoers"):
            continue

        # Try to match a transaction line
        m = TX_LINE_PATTERN.match(line)
        if not m:
            continue

        tx_day = int(m.group(1))
        tx_month = m.group(2)
        book_day = int(m.group(3))
        book_month = m.group(4)
        description_raw = m.group(5).strip()
        amount_str = m.group(6)
        direction = m.group(7)

        tx_date = _parse_date(tx_day, tx_month, statement_year, statement_month)
        book_date = _parse_date(book_day, book_month, statement_year, statement_month)

        # Parse EUR amount (Dutch format: comma as decimal separator)
        amount = Decimal(amount_str.replace(".", "").replace(",", "."))

        # Clean up description: remove foreign currency amount if present
        # Pattern: "description  24,20 USD" -> "description"
        desc_cleaned = re.sub(r"\s+[\d.,]+\s+[A-Z]{3}\s*$", "", description_raw).strip()
        # Also clean up extra whitespace
        desc_cleaned = re.sub(r"\s{2,}", " ", desc_cleaned)

        transactions.append(ICSPdfTransaction(
            transaction_date=tx_date,
            booking_date=book_date,
            description=desc_cleaned,
            amount_eur=amount,
            is_debit=(direction.lower() == "af"),
        ))

    if not transactions:
        raise ParseError("Geen transacties gevonden in de PDF. Controleer of dit een ICS afschrift is.")

    return transactions
