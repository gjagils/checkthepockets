"""Overboekingen tussen eigen rekeningen in een overzicht (ACT-57).

Gekoppelde boekingen (``transfer_id``) tellen niet mee zodra hun tegenboeking óók in het overzicht zit:
in "alle rekeningen" vallen dus beide kanten weg, binnen één rekeninggroep een overboeking tussen de
rekeningen van die groep ook. Zit de tegenboeking buiten het overzicht (bijv. een bijdrage van de ene groep
aan de gezamenlijke rekening), dan telt de boeking wel mee: als inkomen voor de ontvanger en als uitgave voor de
afzender.
"""
from collections.abc import Iterable

from sqlalchemy import exists, or_
from sqlalchemy.orm import aliased

from app.models import Transaction


def not_internal_transfer(account_ids: Iterable[int] | None):
    """SQL-voorwaarde voor een overzicht van ``account_ids`` (``None`` of leeg = alle rekeningen)."""
    ids = list(account_ids or [])
    if not ids:
        return Transaction.transfer_id.is_(None)
    partner = aliased(Transaction)
    partner_in_view = exists().where(partner.id == Transaction.transfer_id, partner.account_id.in_(ids))
    return or_(Transaction.transfer_id.is_(None), ~partner_in_view)
