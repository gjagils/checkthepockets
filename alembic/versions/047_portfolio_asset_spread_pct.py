"""Spread % op PortfolioAsset zodat auto-gefetchte spot-prijzen kunnen worden
gecorrigeerd richting een werkelijke broker-prijs (bv. Goldrepublic).

Revision ID: 047
Revises: 046
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa


revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("portfolio_assets")}
    if "spread_pct" not in cols:
        op.add_column(
            "portfolio_assets",
            sa.Column(
                "spread_pct",
                sa.Numeric(6, 2),
                nullable=True,
                server_default="0",
            ),
        )

    # Backfill: Goud en Zilver (XAU/XAG) krijgen 0,6% standaard, zodat de
    # huidige Goldrepublic-achtige spread direct werkt zonder dat de gebruiker
    # de assets handmatig moet bewerken. Andere assets blijven op 0.
    op.execute(
        "UPDATE portfolio_assets SET spread_pct = 0.6 "
        "WHERE asset_class = 'metal' AND symbol IN ('XAU', 'XAG') "
        "AND (spread_pct IS NULL OR spread_pct = 0)"
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("portfolio_assets")}
    if "spread_pct" in cols:
        try:
            op.drop_column("portfolio_assets", "spread_pct")
        except Exception:
            pass
