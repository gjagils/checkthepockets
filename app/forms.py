"""Tolerant parsing of form input: invalid or blank values give None instead of a 500."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation


def parse_int(raw, default=None):
    """'12' -> 12; blank, 'abc' or '1,2,3' -> default."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def parse_amount(raw, default=None):
    """Dutch-friendly decimal: '12,50', '1.234,56', '€ 5', ' 7.5 ' -> Decimal; invalid -> default."""
    if raw is None:
        return default
    text = re.sub(r"[€\s]", "", str(raw))
    if not text:
        return default
    if "," in text:
        text = text.replace(".", "").replace(",", ".")   # 1.234,56 -> 1234.56
    try:
        value = Decimal(text)
    except InvalidOperation:
        return default
    return value if value.is_finite() else default


def parse_percent(raw, default=None):
    """'3,5' or '3.5%' -> Decimal('3.5')."""
    return parse_amount(str(raw).replace("%", "") if raw is not None else None, default)


def parse_iso_date(raw, default=None):
    """'2026-05-01' -> date; anything else -> default."""
    try:
        return date.fromisoformat(str(raw).strip())
    except (TypeError, ValueError):
        return default
