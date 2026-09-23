"""Savings plan calculations without database access."""
import datetime
from decimal import Decimal, InvalidOperation


FREQUENCY_LABELS = {
    "monthly": "Maandelijks",
    "quarterly": "Per kwartaal",
    "biannual": "Halfjaarlijks",
    "yearly": "Jaarlijks",
    "one-off": "Eenmalig",
    "custom": "Onregelmatig",
}


def months_for_frequency(frequency: str, target_month: int | None = None) -> list[int]:
    """Return the months (1..12) where this frequency 'fires', given an optional start month.
    Voor 'custom' is er geen vast schema — de maanden volgen uit per-maand ingevoerde bedragen."""
    if frequency == "monthly":
        return list(range(1, 13))
    if frequency == "quarterly":
        start = target_month or 3
        return sorted({((start - 1 + 3 * i) % 12) + 1 for i in range(4)})
    if frequency == "biannual":
        start = target_month or 6
        return sorted({((start - 1 + 6 * i) % 12) + 1 for i in range(2)})
    if frequency == "yearly":
        return [target_month or 12]
    if frequency == "one-off":
        return [target_month] if target_month else []
    if frequency == "custom":
        return []
    return list(range(1, 13))


def parse_custom_amounts(
    a1: str, a2: str, a3: str, a4: str, a5: str, a6: str,
    a7: str, a8: str, a9: str, a10: str, a11: str, a12: str,
) -> dict[int, Decimal | None]:
    """Parse 12 maandvelden naar een {1..12: Decimal|None} dict.
    Lege waarden → None (maand niet ingepland). Ongeldige waarden → None."""
    raw = [a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12]
    result: dict[int, Decimal | None] = {}
    for i, v in enumerate(raw, start=1):
        s = (v or "").strip().replace(",", ".")
        if s == "":
            result[i] = None
            continue
        try:
            result[i] = Decimal(s)
        except (InvalidOperation, ValueError):
            result[i] = None
    return result


def determine_color_status(
    actual: Decimal | None,
    expected: Decimal | None,
    is_income: bool,
    month: int,
    year: int,
    today: datetime.date,
    month_fully_categorized: bool = False,
) -> str:
    """Bepaal de kleurstatus voor een spaarcel.

    - 'forecast' (transparant): toekomstige maand of geen actual
    - 'current' (grijs): lopende maand
    - 'above' (groen): beter dan verwacht
    - 'match' (blauw): gelijk aan verwacht
    - 'below' (rood): slechter dan verwacht (incl. niet-gerealiseerd in een
      maand waarin alle transacties gecategoriseerd zijn)
    """
    # Toekomst
    if (year, month) > (today.year, today.month):
        return "forecast"
    # Lopende maand — altijd grijs ongeacht waarde
    if (year, month) == (today.year, today.month):
        return "current"
    # Verleden maand zonder actual: als de maand volledig gecategoriseerd is
    # weten we zeker dat 0 ontvangen/uitgegeven is voor deze categorie.
    if actual is None:
        if month_fully_categorized:
            actual = Decimal("0")
        else:
            return "forecast"

    actual_abs = abs(actual)
    expected_abs = abs(expected) if expected is not None else Decimal("0")

    if actual_abs == expected_abs:
        return "match"
    if is_income:
        return "above" if actual_abs > expected_abs else "below"
    return "above" if actual_abs < expected_abs else "below"
