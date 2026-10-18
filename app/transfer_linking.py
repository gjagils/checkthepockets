"""Compatibiliteit: de koppellogica woont in ``app/transfer_service.py`` (ACT-57)."""
from app.transfer_service import MAX_DAYS_APART, link_transfers

__all__ = ["MAX_DAYS_APART", "link_transfers"]
