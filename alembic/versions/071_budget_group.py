"""Budget per rekeninggroep (ACT-55b).

Revision ID: 071
Revises: 070

budgets.group_id wordt gevuld met de groep van de rekening van de categorie (categorieën zonder
rekening houden NULL). De uniekheid gaat van (gebruiker, categorie, jaar, maand) naar dezelfde
sleutel met de groep; voor NULL-groepen bewaakt een partiële unieke index de oude regel.
"""
from alembic import op
import sqlalchemy as sa

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("budgets", sa.Column("group_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_budgets_group_id", "budgets", "account_groups", ["group_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_budgets_group_id", "budgets", ["group_id"])
    op.execute(
        """
        UPDATE budgets SET group_id = (
            SELECT accounts.group_id FROM categories
            JOIN accounts ON accounts.id = categories.account_id
            WHERE categories.id = budgets.category_id
        )
        """
    )
    op.drop_constraint("uq_budget_user_cat_year_month", "budgets", type_="unique")
    op.create_unique_constraint(
        "uq_budget_user_cat_group_year_month", "budgets", ["user_id", "category_id", "group_id", "year", "month"],
    )
    op.create_index(
        "uq_budget_user_cat_year_month_nogroup", "budgets", ["user_id", "category_id", "year", "month"],
        unique=True, postgresql_where=sa.text("group_id IS NULL"),
    )


def downgrade():
    op.drop_index("uq_budget_user_cat_year_month_nogroup", table_name="budgets")
    op.drop_constraint("uq_budget_user_cat_group_year_month", "budgets", type_="unique")
    # Meerdere groepen kunnen nu een budget voor dezelfde categorie hebben: houd per sleutel de hoogste id.
    op.execute(
        """
        DELETE FROM budgets WHERE id NOT IN (
            SELECT MAX(id) FROM budgets GROUP BY user_id, category_id, year, month
        )
        """
    )
    op.create_unique_constraint("uq_budget_user_cat_year_month", "budgets", ["user_id", "category_id", "year", "month"])
    op.drop_index("ix_budgets_group_id", table_name="budgets")
    op.drop_constraint("fk_budgets_group_id", "budgets", type_="foreignkey")
    op.drop_column("budgets", "group_id")
