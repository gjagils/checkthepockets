"""Dutch month names, defined once (they were copied into dashboard, budgets, analytics, recurring,
transactions and person_utils)."""

# Index 0 is empty so that MONTHS_NL_FULL[month] works with month numbers 1-12.
MONTHS_NL_FULL = [
    "", "Januari", "Februari", "Maart", "April", "Mei", "Juni",
    "Juli", "Augustus", "September", "Oktober", "November", "December",
]
MONTHS_NL_SHORT = [
    "", "Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec",
]


def month_names_by_number(whole_year_label: str | None = None) -> dict[int, str]:
    """{1: "Januari", ...}; with `whole_year_label` also {0: label} (the "all months" option)."""
    names = {number: name for number, name in enumerate(MONTHS_NL_FULL) if number}
    if whole_year_label is not None:
        names = {0: whole_year_label, **names}
    return names
