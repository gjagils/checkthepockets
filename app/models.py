import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Date,
    DateTime,
    Text,
    ForeignKey,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


transaction_tags = Table(
    "transaction_tags",
    Base.metadata,
    Column("transaction_id", Integer, ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan")
    savings_plans = relationship("SavingsPlan", back_populates="user", cascade="all, delete-orphan")
    budgets = relationship("Budget", back_populates="user", cascade="all, delete-orphan")
    tags = relationship("Tag", back_populates="user", cascade="all, delete-orphan")
    rules = relationship("Rule", back_populates="user", cascade="all, delete-orphan")
    recurring_transactions = relationship("RecurringTransaction", back_populates="user", cascade="all, delete-orphan")
    portfolio_assets = relationship("PortfolioAsset", back_populates="user", cascade="all, delete-orphan")
    portfolio_persons = relationship("PortfolioPerson", back_populates="user", cascade="all, delete-orphan")
    portfolio_holdings = relationship("PortfolioHolding", back_populates="user", cascade="all, delete-orphan")
    networth_accounts = relationship("NetWorthAccount", back_populates="user", cascade="all, delete-orphan")
    networth_snapshots = relationship("NetWorthSnapshot", back_populates="user", cascade="all, delete-orphan")
    plaid_connections = relationship("PlaidConnection", back_populates="user", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    iban = Column(String(34), nullable=True)
    bank = Column(String(50), nullable=False)  # "abn_amro", "bunq", "ics"
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

    user = relationship("User", back_populates="categories")
    account = relationship("Account", back_populates="categories")
    transactions = relationship("Transaction", back_populates="category")
    savings_lines = relationship("SavingsLine", back_populates="category")
    budgets = relationship("Budget", back_populates="category")

    __table_args__ = (
        UniqueConstraint("user_id", "account_id", "name", name="uq_user_account_category"),
    )


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="tags")
    transactions = relationship("Transaction", secondary=transaction_tags, back_populates="tags")

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_tag"),
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

    # THEN actions
    assign_category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    assign_tag_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="rules")
    assign_category = relationship("Category")
    assign_tag = relationship("Tag")


class RecurringTransaction(Base):
    __tablename__ = "recurring_transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(150), nullable=False)
    amount_expected = Column(Numeric(12, 2), nullable=False)
    frequency = Column(String(20), nullable=False)  # "monthly", "weekly", "yearly", "quarterly"
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    counterparty = Column(String(255), nullable=True)
    description_match = Column(String(255), nullable=True)  # for auto-detection
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="recurring_transactions")
    category = relationship("Category")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    date = Column(Date, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="EUR")
    description = Column(Text, nullable=True)
    counterparty = Column(String(255), nullable=True)
    counterparty_iban = Column(String(34), nullable=True)
    balance_after = Column(Numeric(12, 2), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    parent_id = Column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True)
    import_hash = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    account = relationship("Account", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    tags = relationship("Tag", secondary=transaction_tags, back_populates="transactions")
    parent = relationship("Transaction", remote_side="Transaction.id", backref="children")


class SavingsPlan(Base):
    __tablename__ = "savings_plans"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    year = Column(Integer, nullable=False)
    starting_balance = Column(Numeric(12, 2), default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="savings_plans")
    account = relationship("Account", back_populates="savings_plans")
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
    name = Column(String(100), nullable=False)       # "Goud", "Zilver", "Bitcoin"
    symbol = Column(String(20), nullable=False)       # "XAU", "XAG", "bitcoin"
    asset_class = Column(String(20), nullable=False)  # "metal", "crypto"
    unit = Column(String(20), default="oz")           # "oz", "gram", "coin"
    current_price_eur = Column(Numeric(16, 4), default=0)
    price_updated_at = Column(DateTime, nullable=True)
    monthly_growth_pct = Column(Numeric(6, 2), default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="portfolio_assets")
    holdings = relationship("PortfolioHolding", back_populates="asset", cascade="all, delete-orphan")


class PortfolioPerson(Base):
    __tablename__ = "portfolio_persons"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="portfolio_persons")
    holdings = relationship("PortfolioHolding", back_populates="person", cascade="all, delete-orphan")


class PortfolioHolding(Base):
    __tablename__ = "portfolio_holdings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    asset_id = Column(Integer, ForeignKey("portfolio_assets.id", ondelete="CASCADE"), nullable=False)
    person_id = Column(Integer, ForeignKey("portfolio_persons.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Numeric(16, 8), default=0)

    user = relationship("User", back_populates="portfolio_holdings")
    asset = relationship("PortfolioAsset", back_populates="holdings")
    person = relationship("PortfolioPerson", back_populates="holdings")

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


class PlaidConnection(Base):
    __tablename__ = "plaid_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    institution_id = Column(String(100), nullable=True)        # Plaid institution ID (e.g. "ins_1")
    institution_name = Column(String(255), nullable=False)     # Human-readable name
    access_token = Column(String(255), nullable=False)         # Permanent Plaid access token
    item_id = Column(String(100), nullable=False)              # Plaid item identifier
    plaid_account_id = Column(String(100), nullable=True)      # Plaid account ID
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    cursor = Column(Text, nullable=True)                       # transactions/sync cursor
    status = Column(String(20), default="active")              # "active", "error", "expired"
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="plaid_connections")
    account = relationship("Account")
