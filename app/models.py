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
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan")
    savings_plans = relationship("SavingsPlan", back_populates="user", cascade="all, delete-orphan")


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

    __table_args__ = (
        UniqueConstraint("user_id", "account_id", "name", name="uq_user_account_category"),
    )


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
    parent_id = Column(Integer, nullable=True)
    import_hash = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    account = relationship("Account", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")


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
