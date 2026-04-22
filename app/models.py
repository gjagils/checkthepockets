import datetime
from decimal import Decimal

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Date,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    Table,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.crypto import EncryptedText


# Many-to-many: een Account heeft 0..N eigenaren (Persons); een Person kan
# eigenaar zijn van meerdere rekeningen. Composite PK.
account_owners = Table(
    "account_owners",
    Base.metadata,
    Column("account_id", Integer, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", Integer, ForeignKey("persons.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    is_verified = Column(Integer, default=1)   # 1 = verified, 0 = pending email verification
    is_admin = Column(Integer, default=0)       # 1 = admin
    is_active = Column(Integer, default=1)      # 0 = deactivated by admin
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Weekly digest voorkeuren — opt-in, jouw eigen ritme.
    weekly_digest_enabled = Column(Integer, default=0)        # 1 = abonneer, 0 = uit
    weekly_digest_weekday = Column(Integer, default=4)        # 0=ma ... 6=zo, default vrijdag
    weekly_digest_hour = Column(Integer, default=8)           # 0..23 in Europe/Amsterdam
    weekly_digest_last_sent_at = Column(DateTime, nullable=True)

    # Startpagina: de route die getoond wordt bij inloggen of bezoek aan "/".
    start_page = Column(String(100), default="/dashboard")

    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan")
    savings_plans = relationship("SavingsPlan", back_populates="user", cascade="all, delete-orphan")
    budgets = relationship("Budget", back_populates="user", cascade="all, delete-orphan")
    rules = relationship("Rule", back_populates="user", cascade="all, delete-orphan")
    recurring_transactions = relationship("RecurringTransaction", back_populates="user", cascade="all, delete-orphan")
    portfolio_assets = relationship("PortfolioAsset", back_populates="user", cascade="all, delete-orphan")
    persons = relationship("Person", back_populates="user", cascade="all, delete-orphan")
    portfolio_holdings = relationship("PortfolioHolding", back_populates="user", cascade="all, delete-orphan")
    networth_accounts = relationship("NetWorthAccount", back_populates="user", cascade="all, delete-orphan")
    networth_snapshots = relationship("NetWorthSnapshot", back_populates="user", cascade="all, delete-orphan")
    budget_presets = relationship("BudgetPreset", back_populates="user", cascade="all, delete-orphan")
    auth_tokens = relationship("AuthToken", back_populates="user", cascade="all, delete-orphan")


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    token = Column(String(128), unique=True, nullable=False)
    token_type = Column(String(20), nullable=False)  # verify_email | reset_password | invite
    email = Column(String(255), nullable=True)        # stored on invite tokens
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="auth_tokens")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    iban = Column(String(34), nullable=True)
    bank = Column(String(50), nullable=False)  # "abn_amro", "bunq", "ics"
    external_uid = Column(String(255), nullable=True, index=True)  # Enable Banking account_uid
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="accounts")
    transactions = relationship(
        "Transaction", back_populates="account", cascade="all, delete-orphan"
    )
    categories = relationship(
        "Category", back_populates="account", cascade="all, delete-orphan"
    )
    savings_plans = relationship(
        "SavingsPlan", back_populates="account", cascade="all, delete-orphan"
    )
    owners = relationship(
        "Person", secondary=account_owners, back_populates="accounts",
        order_by="Person.sort_order",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "iban", "bank", name="uq_user_account"),
    )


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    name = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    color = Column(String(7), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_income = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)
    exclude_from_budget = Column(Integer, default=0)
    exclude_from_totals = Column(Integer, default=0)
    is_archived = Column(Integer, default=0)

    user = relationship("User", back_populates="categories")
    account = relationship("Account", back_populates="categories")
    parent = relationship("Category", remote_side=[id], backref="children")
    transactions = relationship("Transaction", back_populates="category")
    savings_lines = relationship("SavingsLine", back_populates="category")
    budgets = relationship("Budget", back_populates="category")

    __table_args__ = (
        UniqueConstraint("user_id", "account_id", "name", name="uq_user_account_category"),
    )


class Rule(Base):
    __tablename__ = "rules"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    is_active = Column(Integer, default=1)  # 1=active, 0=inactive

    # IF conditions
    match_field = Column(String(20), nullable=False)  # "counterparty", "description", "counterparty_iban"
    match_type = Column(String(20), nullable=False)  # "contains", "exact", "starts_with"
    match_value = Column(String(255), nullable=False)
    amount_min = Column(Numeric(12, 2), nullable=True)
    amount_max = Column(Numeric(12, 2), nullable=True)
    condition_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)

    # THEN actions
    assign_category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    action_rename_counterparty = Column(String(255), nullable=True)
    action_set_reviewed = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="rules")
    assign_category = relationship("Category")
    condition_account = relationship("Account", foreign_keys=[condition_account_id])


class RecurringTransaction(Base):
    __tablename__ = "recurring_transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    name = Column(String(150), nullable=False)
    amount_expected = Column(Numeric(12, 2), nullable=False)
    frequency = Column(String(20), nullable=False)  # "monthly", "weekly", "yearly", "quarterly"
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    counterparty = Column(String(255), nullable=True)
    description_match = Column(String(255), nullable=True)  # for auto-detection
    is_active = Column(Integer, default=1)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    active_months = Column(String(50), nullable=True)  # comma-separated month numbers, NULL = all
    skipped_months = Column(String(2000), nullable=True)  # comma-separated "YYYY-MM" — maanden waarin deze verwachting NIET plaatsvindt
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="recurring_transactions")
    account = relationship("Account")
    category = relationship("Category")


class RuleSuggestion(Base):
    __tablename__ = "rule_suggestions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    match_value = Column(String(255), nullable=False)
    match_field = Column(String(20), nullable=False, default="description")
    counterparty_clean = Column(String(255), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    category_name = Column(String(100), nullable=True)
    reasoning = Column(Text, nullable=True)
    uncat_count = Column(Integer, default=0)
    cat_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")
    category = relationship("Category")


class RecurringSuggestion(Base):
    __tablename__ = "recurring_suggestions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(150), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    frequency = Column(String(20), nullable=False)
    counterparty_match = Column(String(255), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    category_name = Column(String(100), nullable=True)
    reasoning = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")
    category = relationship("Category")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    date = Column(Date, nullable=False)
    # Oorspronkelijke boekingsdatum door de bank; wordt gevuld zodra de
    # zichtbare datum verplaatst wordt bij koppelen aan een terugkerend item
    # waarvan de periode afwijkt (bv. hypotheek op 31-12 voor de januari-termijn).
    original_date = Column(Date, nullable=True)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="EUR")
    description = Column(EncryptedText, nullable=True)        # encrypted when FIELD_ENCRYPTION_KEY is set
    counterparty = Column(EncryptedText, nullable=True)        # encrypted when FIELD_ENCRYPTION_KEY is set
    counterparty_iban = Column(EncryptedText, nullable=True)   # encrypted when FIELD_ENCRYPTION_KEY is set
    balance_after = Column(Numeric(12, 2), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    parent_id = Column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True)
    import_hash = Column(String(64), unique=True, nullable=False)
    is_excluded = Column(Integer, default=0)
    is_reviewed = Column(Integer, default=0)
    is_projected = Column(Integer, default=0)
    recurring_id = Column(Integer, ForeignKey("recurring_transactions.id", ondelete="SET NULL"), nullable=True)
    transfer_id = Column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)
    assigned_by_rule_id = Column(Integer, ForeignKey("rules.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    account = relationship("Account", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    parent = relationship("Transaction", remote_side="Transaction.id", foreign_keys="[Transaction.parent_id]", backref="children")
    assigned_by_rule = relationship("Rule", foreign_keys=[assigned_by_rule_id])


class SavingsPlan(Base):
    __tablename__ = "savings_plans"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    year = Column(Integer, nullable=False)
    starting_balance = Column(Numeric(12, 2), default=0)
    source_plan_id = Column(
        Integer, ForeignKey("savings_plans.id", ondelete="SET NULL"), nullable=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="savings_plans")
    account = relationship("Account", back_populates="savings_plans")
    source_plan = relationship(
        "SavingsPlan", remote_side="SavingsPlan.id", foreign_keys=[source_plan_id],
    )
    lines = relationship(
        "SavingsLine", back_populates="plan", cascade="all, delete-orphan",
        order_by="SavingsLine.sort_order",
    )

    __table_args__ = (
        UniqueConstraint("account_id", "year", name="uq_savings_plan_account_year"),
    )


class SavingsLine(Base):
    __tablename__ = "savings_lines"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("savings_plans.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    is_income = Column(Integer, default=0)
    annual_budget = Column(Numeric(12, 2), default=0)
    frequency = Column(String(20), nullable=False, default="monthly")
    default_amount = Column(Numeric(12, 2), default=0)
    sort_order = Column(Integer, default=0)

    plan = relationship("SavingsPlan", back_populates="lines")
    category = relationship("Category", back_populates="savings_lines")
    entries = relationship(
        "SavingsEntry", back_populates="line", cascade="all, delete-orphan",
        order_by="SavingsEntry.month",
    )


class SavingsEntry(Base):
    __tablename__ = "savings_entries"

    id = Column(Integer, primary_key=True)
    line_id = Column(Integer, ForeignKey("savings_lines.id", ondelete="CASCADE"), nullable=False)
    month = Column(Integer, nullable=False)
    amount = Column(Numeric(12, 2), nullable=True)
    status = Column(String(20), default="forecast")  # forecast, pending, confirmed

    line = relationship("SavingsLine", back_populates="entries")

    __table_args__ = (
        UniqueConstraint("line_id", "month", name="uq_savings_entry_line_month"),
    )


class PortfolioAsset(Base):
    __tablename__ = "portfolio_assets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)       # "Goud", "Zilver", "Bitcoin", "ASML"
    symbol = Column(String(20), nullable=False)       # "XAU", "XAG", "bitcoin", "ASML.AS"
    asset_class = Column(String(20), nullable=False)  # "metal", "crypto", "stock"
    unit = Column(String(20), default="oz")           # "oz", "gram", "coin", "aandeel"
    ticker = Column(String(20), nullable=True)        # Optional stock ticker, e.g. "ASML.AS"
    exchange = Column(String(50), nullable=True)      # Optional exchange, e.g. "Euronext Amsterdam"
    current_price_eur = Column(Numeric(16, 4), default=0)
    price_updated_at = Column(DateTime, nullable=True)
    monthly_growth_pct = Column(Numeric(6, 2), default=0)
    cashout_fee_fixed_eur = Column(Numeric(12, 2), default=0)
    cashout_fee_pct = Column(Numeric(6, 2), default=0)
    # Spread (% lager dan spot) die op de gehaalde prijs wordt toegepast bij
    # auto-fetch. Voor edelmetalen via Goldrepublic-achtige bronnen ligt dit
    # rond 0,6% onder spot. 0 = geen aanpassing (raw spot price).
    spread_pct = Column(Numeric(6, 2), default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="portfolio_assets")
    holdings = relationship("PortfolioHolding", back_populates="asset", cascade="all, delete-orphan")


class Person(Base):
    __tablename__ = "persons"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    birthdate = Column(Date, nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="persons")
    holdings = relationship("PortfolioHolding", back_populates="person", cascade="all, delete-orphan")
    accounts = relationship(
        "Account", secondary=account_owners, back_populates="owners",
    )


class PortfolioHolding(Base):
    __tablename__ = "portfolio_holdings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    asset_id = Column(Integer, ForeignKey("portfolio_assets.id", ondelete="CASCADE"), nullable=False)
    person_id = Column(Integer, ForeignKey("persons.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Numeric(16, 8), default=0)
    monthly_contribution_eur = Column(Numeric(12, 2), default=0)

    user = relationship("User", back_populates="portfolio_holdings")
    asset = relationship("PortfolioAsset", back_populates="holdings")
    person = relationship("Person", back_populates="holdings")

    __table_args__ = (
        UniqueConstraint("user_id", "asset_id", "person_id", name="uq_holding_user_asset_person"),
    )


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=0)

    user = relationship("User", back_populates="budgets")
    category = relationship("Category", back_populates="budgets")

    __table_args__ = (
        UniqueConstraint("user_id", "category_id", "year", "month", name="uq_budget_user_cat_year_month"),
    )


class BudgetPreset(Base):
    __tablename__ = "budget_presets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="budget_presets")
    lines = relationship("BudgetPresetLine", back_populates="preset", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_budget_preset_user_name"),
    )


class BudgetPresetLine(Base):
    __tablename__ = "budget_preset_lines"

    id = Column(Integer, primary_key=True)
    preset_id = Column(Integer, ForeignKey("budget_presets.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=0)

    preset = relationship("BudgetPreset", back_populates="lines")
    category = relationship("Category")


class NetWorthAccount(Base):
    __tablename__ = "networth_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(150), nullable=False)
    account_type = Column(String(20), nullable=False)  # "asset" or "liability"
    category = Column(String(50), nullable=False)  # "savings", "investment", "property", "mortgage", "loan", "other"
    balance = Column(Numeric(14, 2), default=0)
    notes = Column(Text, nullable=True)
    is_active = Column(Integer, default=1)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="networth_accounts")
    snapshots = relationship("NetWorthSnapshot", back_populates="account", cascade="all, delete-orphan")


class NetWorthSnapshot(Base):
    __tablename__ = "networth_snapshots"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("networth_accounts.id", ondelete="CASCADE"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    balance = Column(Numeric(14, 2), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="networth_snapshots")
    account = relationship("NetWorthAccount", back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint("account_id", "year", "month", name="uq_networth_snapshot_account_year_month"),
    )


class BankConnection(Base):
    """PSD2 bank connection via Enable Banking."""
    __tablename__ = "bank_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    bank_name = Column(String(100), nullable=False)        # ASPSP name, e.g. "ING"
    display_name = Column(String(100), nullable=True)      # Custom user-facing name
    bank_country = Column(String(2), nullable=False, default="NL")
    session_id = Column(String(255), nullable=True)        # Enable Banking session ID
    accounts_json = Column(Text, nullable=True)             # JSON list of {uid, iban, name}
    valid_until = Column(DateTime, nullable=True)           # consent expiry
    status = Column(String(20), nullable=False, default="pending")  # pending, active, expired, revoked
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")


class HouseholdFinance(Base):
    """Stabiele huishoud-waardes die alle hypotheek-scenarios gebruiken."""
    __tablename__ = "household_finance"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    salary_primary = Column(Numeric(12, 2), default=0)
    salary_primary_name = Column(String(100), nullable=True)
    salary_secondary = Column(Numeric(12, 2), default=0)
    salary_secondary_name = Column(String(100), nullable=True)

    existing_mortgage_pim = Column(Numeric(12, 2), default=0)
    existing_mortgage_interest_only = Column(Numeric(12, 2), default=0)
    existing_mortgage_interest_only_monthly = Column(Numeric(12, 2), default=0)
    existing_mortgage_pim_rate = Column(Numeric(6, 4), default=0)
    existing_mortgage_pim_refund_rate = Column(Numeric(6, 4), default=0)

    current_home_debt = Column(Numeric(12, 2), default=0)
    tax_rate = Column(Numeric(6, 4), default=Decimal("0.3697"))
    notional_rent_value = Column(Numeric(12, 2), default=Decimal("3600"))
    purchase_costs_pct = Column(Numeric(6, 4), default=Decimal("0.025"))
    selling_costs_pct = Column(Numeric(6, 4), default=Decimal("0.015"))

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User")


class MortgageRateTable(Base):
    """Rente-tabel per user: rentevast × LTV-bucket → %."""
    __tablename__ = "mortgage_rate_table"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    fixed_years = Column(Integer, nullable=False)
    ltv_max_pct = Column(Numeric(6, 4), nullable=False)
    interest_rate = Column(Numeric(6, 4), nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", "fixed_years", "ltv_max_pct", name="uq_rate_user_fixed_ltv"),
    )


class MortgageScenario(Base):
    """Een hypotheek-scenario voor één potentieel huis."""
    __tablename__ = "mortgage_scenarios"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(150), nullable=False)
    valuation = Column(Numeric(12, 2), default=0)
    offer = Column(Numeric(12, 2), default=0)
    renovation_cost = Column(Numeric(12, 2), default=0)
    own_contribution = Column(Numeric(12, 2), default=0)
    sale_old_home = Column(Numeric(12, 2), default=0)
    # Per-scenario aan/verkoopkosten (LIN-44). Percentages, default 2,5 / 1,5.
    purchase_fee_pct = Column(Numeric(5, 2), nullable=False, default=Decimal("2.5"))
    sale_fee_pct = Column(Numeric(5, 2), nullable=False, default=Decimal("1.5"))
    energy_label = Column(String(2), default="A")
    notes = Column(Text, nullable=True)
    funda_url = Column(String(500), nullable=True)
    photo_url = Column(String(500), nullable=True)
    is_archived = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User")
    variants = relationship(
        "MortgageVariant", back_populates="scenario", cascade="all, delete-orphan"
    )
    existing_mortgages = relationship(
        "ScenarioExistingMortgage",
        back_populates="scenario",
        cascade="all, delete-orphan",
        order_by="ScenarioExistingMortgage.sort_order, ScenarioExistingMortgage.id",
    )


class ScenarioExistingMortgage(Base):
    """Bestaande hypotheek die in dit scenario wordt meegenomen (LIN-44)."""
    __tablename__ = "scenario_existing_mortgages"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(
        Integer, ForeignKey("mortgage_scenarios.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name = Column(String(100), nullable=False)
    balance_eur = Column(Numeric(12, 2), nullable=False, default=0)
    mortgage_type = Column(String(20), nullable=False, default="annuity")  # "annuity" | "interest_only"
    rate_pct = Column(Numeric(6, 3), nullable=True)
    months_remaining = Column(Integer, nullable=True)
    monthly_payment_eur = Column(Numeric(10, 2), nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)

    scenario = relationship("MortgageScenario", back_populates="existing_mortgages")


class MortgageVariant(Base):
    """Rentevast-keuze binnen één hypotheek-scenario."""
    __tablename__ = "mortgage_variants"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("mortgage_scenarios.id", ondelete="CASCADE"), nullable=False)
    fixed_years = Column(Integer, nullable=False)
    interest_rate_override = Column(Numeric(6, 4), nullable=True)

    scenario = relationship("MortgageScenario", back_populates="variants")

    __table_args__ = (
        UniqueConstraint("scenario_id", "fixed_years", name="uq_variant_scenario_fixed"),
    )


class MortgageScenarioBudget(Base):
    """Scenario-specifieke budget-override per categorie."""
    __tablename__ = "mortgage_scenario_budgets"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(
        Integer, ForeignKey("mortgage_scenarios.id", ondelete="CASCADE"), nullable=False,
    )
    category_id = Column(
        Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False,
    )
    amount = Column(Numeric(12, 2), nullable=False, default=0)

    scenario = relationship("MortgageScenario")
    category = relationship("Category")

    __table_args__ = (
        UniqueConstraint(
            "scenario_id", "category_id", name="uq_scenario_budget_scenario_category",
        ),
    )


class PortfolioPriceSnapshot(Base):
    __tablename__ = "portfolio_price_snapshots"

    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("portfolio_assets.id", ondelete="CASCADE"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    price_eur = Column(Numeric(16, 4), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    asset = relationship("PortfolioAsset")

    __table_args__ = (
        UniqueConstraint("asset_id", "year", "month", name="uq_price_snapshot_asset_year_month"),
    )


class SchedulerRunLog(Base):
    """Eén rij per scheduler-job-uitvoering; gebruikt door /admin/scheduler."""

    __tablename__ = "scheduler_run_log"

    id = Column(Integer, primary_key=True)
    job_id = Column(String(64), nullable=False, index=True)
    started_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False, default="running")  # running|ok|error
    summary = Column(Text, nullable=True)
