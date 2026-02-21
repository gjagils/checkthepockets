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

    __table_args__ = (
        UniqueConstraint("user_id", "iban", "bank", name="uq_user_account"),
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
    category = Column(String(100), nullable=True)
    import_hash = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    account = relationship("Account", back_populates="transactions")
