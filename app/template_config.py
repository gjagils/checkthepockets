"""Shared Jinja2 templates instance with custom filters."""

from decimal import Decimal

from fastapi.templating import Jinja2Templates


def _euro_filter(value) -> str:
    """Format a number as Dutch euro: 1.234,56 (dot for thousands, comma for decimals)."""
    try:
        d = Decimal(str(value))
    except Exception:
        return str(value)

    negative = d < 0
    d = abs(d)

    # Format with 2 decimal places
    formatted = f"{d:.2f}"
    integer_part, decimal_part = formatted.split(".")

    # Add thousand separators (dots)
    digits = list(integer_part)
    result = []
    for i, digit in enumerate(reversed(digits)):
        if i > 0 and i % 3 == 0:
            result.append(".")
        result.append(digit)
    integer_part = "".join(reversed(result))

    # Combine with comma decimal separator
    formatted = f"{integer_part},{decimal_part}"
    if negative:
        formatted = f"-{formatted}"

    return formatted


def _euro0_filter(value) -> str:
    """Format a number as Dutch euro without decimals: 1.234 (dot for thousands)."""
    try:
        d = Decimal(str(value))
    except Exception:
        return str(value)

    negative = d < 0
    d = abs(d)

    # Format with 0 decimal places
    integer_part = str(int(d.quantize(Decimal("1"))))

    # Add thousand separators (dots)
    digits = list(integer_part)
    result = []
    for i, digit in enumerate(reversed(digits)):
        if i > 0 and i % 3 == 0:
            result.append(".")
        result.append(digit)
    integer_part = "".join(reversed(result))

    if negative:
        integer_part = f"-{integer_part}"

    return integer_part


def _euro_sign_filter(value) -> str:
    """"€ 1.234,56" met harde spatie; negatief als "€ -1.234,56"."""
    return "\u20ac\u00a0" + _euro_filter(value)


def _euro0_sign_filter(value) -> str:
    return "\u20ac\u00a0" + _euro0_filter(value)


def _date_filter(value) -> str:
    """dd-mm-jjjj; lege waarde geeft een lege string."""
    return value.strftime("%d-%m-%Y") if value else ""


def _datetime_filter(value) -> str:
    """dd-mm-jjjj hh:mm; lege waarde geeft een lege string."""
    return value.strftime("%d-%m-%Y %H:%M") if value else ""


templates = Jinja2Templates(directory="app/templates")
templates.env.filters["euro"] = _euro_filter
templates.env.filters["euro0"] = _euro0_filter
templates.env.filters["euro_sign"] = _euro_sign_filter
templates.env.filters["euro0_sign"] = _euro0_sign_filter
templates.env.filters["date"] = _date_filter
templates.env.filters["datetime"] = _datetime_filter
