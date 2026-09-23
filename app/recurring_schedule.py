"""Schedule rules for recurring items: periods, active and skipped months.

Pure functions without database access, shared by the recurring, budget and
transaction routes.
"""
import calendar
from datetime import date, timedelta
from typing import List

from app.models import RecurringTransaction


def get_period_range(frequency: str, ref_date: date) -> tuple[date, date]:
    """Get the start and end date for the current period based on frequency."""
    if frequency == "weekly":
        start = ref_date - timedelta(days=ref_date.weekday())
        end = start + timedelta(days=6)
    elif frequency == "monthly":
        start = ref_date.replace(day=1)
        last_day = calendar.monthrange(ref_date.year, ref_date.month)[1]
        end = ref_date.replace(day=last_day)
    elif frequency == "quarterly":
        q_month = ((ref_date.month - 1) // 3) * 3 + 1
        start = date(ref_date.year, q_month, 1)
        end_month = q_month + 2
        end_year = ref_date.year
        if end_month > 12:
            end_month -= 12
            end_year += 1
        last_day = calendar.monthrange(end_year, end_month)[1]
        end = date(end_year, end_month, last_day)
    elif frequency == "yearly":
        start = date(ref_date.year, 1, 1)
        end = date(ref_date.year, 12, 31)
    else:
        start = ref_date.replace(day=1)
        last_day = calendar.monthrange(ref_date.year, ref_date.month)[1]
        end = ref_date.replace(day=last_day)
    return start, end


def get_previous_period_range(frequency: str, ref_date: date) -> tuple[date, date]:
    """Get the start and end date of the period BEFORE the current one."""
    current_start, _ = get_period_range(frequency, ref_date)
    prev_date = current_start - timedelta(days=1)
    return get_period_range(frequency, prev_date)


def parse_active_months(values: List[str]) -> str | None:
    """Convert list of month number strings to stored comma-separated string, or None for all."""
    nums = sorted({int(v) for v in values if v.isdigit() and 1 <= int(v) <= 12})
    if len(nums) == 12:
        return None  # all months = no restriction
    return ",".join(str(m) for m in nums) if nums else None


def active_months_set(item: RecurringTransaction) -> set[int]:
    """Return the set of active month numbers for a recurring item (1-12). Empty = all."""
    if not item.active_months:
        return set(range(1, 13))
    try:
        return {int(m) for m in item.active_months.split(",") if m.strip()}
    except ValueError:
        return set(range(1, 13))


def is_in_active_period(item: RecurringTransaction, today: date) -> bool:
    """Check if a recurring item is within its configured active period."""
    if item.start_date and item.start_date > today:
        return False
    if item.end_date and item.end_date < today:
        return False
    months = active_months_set(item)
    if today.month not in months:
        return False
    return True


def is_active_in_month(item: RecurringTransaction, year: int, month: int) -> bool:
    """Check if a recurring item should be active in the given year/month."""
    ref = date(year, month, 1)
    if item.start_date and item.start_date > date(year, month, calendar.monthrange(year, month)[1]):
        return False
    if item.end_date and item.end_date < ref:
        return False
    months = active_months_set(item)
    if month not in months:
        return False
    if is_month_skipped(item, year, month):
        return False
    return True


def skipped_months_set(item: RecurringTransaction) -> set[str]:
    raw = (item.skipped_months or "").strip()
    if not raw:
        return set()
    return {p.strip() for p in raw.split(",") if p.strip()}


def is_month_skipped(item: RecurringTransaction, year: int, month: int) -> bool:
    return f"{year:04d}-{month:02d}" in skipped_months_set(item)


def add_skipped_month(item: RecurringTransaction, year: int, month: int) -> None:
    existing = skipped_months_set(item)
    existing.add(f"{year:04d}-{month:02d}")
    item.skipped_months = ",".join(sorted(existing))


def remove_skipped_month(item: RecurringTransaction, year: int, month: int) -> None:
    existing = skipped_months_set(item)
    existing.discard(f"{year:04d}-{month:02d}")
    item.skipped_months = ",".join(sorted(existing)) if existing else None


def projected_hash(item_id: int, year: int, month: int) -> str:
    """Canonical hash for a projected transaction. Always use this function."""
    return f"projected-{item_id}-{year}-{month:02d}"
