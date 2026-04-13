"""Tests for Enable Banking API integration.

These tests verify:
1. JWT token generation
2. Sandbox API connectivity (listing banks)
3. Transaction mapping from EB format to ParsedTransaction
"""
import os
import time
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

# Set env vars before importing app modules
os.environ.setdefault(
    "ENABLE_BANKING_APP_ID", "05336855-b073-4033-96be-5455f7196a5a"
)
os.environ.setdefault(
    "ENABLE_BANKING_PRIVATE_KEY_PATH",
    os.path.join(os.path.dirname(__file__), "..", "05336855-b073-4033-96be-5455f7196a5a.pem"),
)
# Use SQLite for tests so we don't need psycopg2
os.environ["DATABASE_URL"] = "sqlite:///test_enable_banking.db"


# ── JWT token generation ────────────────────────────────────────────────────


def test_jwt_generation():
    """Verify we can generate a valid JWT with the private key."""
    pem_path = os.environ["ENABLE_BANKING_PRIVATE_KEY_PATH"]
    if not os.path.exists(pem_path):
        pytest.skip("Private key file not found")

    from app.enable_banking import _make_jwt
    import jwt as pyjwt

    token = _make_jwt()
    assert token
    assert isinstance(token, str)

    # Decode without verification to check structure
    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "RS256"
    assert header["kid"] == os.environ["ENABLE_BANKING_APP_ID"]

    payload = pyjwt.decode(token, options={"verify_signature": False})
    assert payload["iss"] == "enablebanking.com"
    assert payload["aud"] == "api.enablebanking.com"
    assert payload["exp"] > time.time()


# ── Sandbox API connectivity ────────────────────────────────────────────────


def test_list_banks_sandbox():
    """Verify we can connect to the sandbox and list Dutch banks."""
    pem_path = os.environ["ENABLE_BANKING_PRIVATE_KEY_PATH"]
    if not os.path.exists(pem_path):
        pytest.skip("Private key file not found")

    from app.enable_banking import list_banks

    banks = list_banks("NL")
    assert isinstance(banks, list)
    assert len(banks) > 0

    # Each bank should have a name and country
    for bank in banks[:3]:
        assert "name" in bank
        assert "country" in bank
        assert bank["country"] == "NL"


def test_list_banks_finland_sandbox():
    """Verify sandbox also works for Finnish banks (common in EB docs)."""
    pem_path = os.environ["ENABLE_BANKING_PRIVATE_KEY_PATH"]
    if not os.path.exists(pem_path):
        pytest.skip("Private key file not found")

    from app.enable_banking import list_banks

    banks = list_banks("FI")
    assert isinstance(banks, list)
    assert len(banks) > 0


# ── Transaction mapping ────────────────────────────────────────────────────


def test_map_eb_transactions_basic():
    """Map a standard Enable Banking transaction to ParsedTransaction."""
    from app.routers.banking import _map_eb_transactions

    raw = [
        {
            "booking_date": "2026-04-10",
            "transaction_amount": {"amount": "-42.50", "currency": "EUR"},
            "remittance_information": ["Boodschappen Albert Heijn"],
            "creditor": {"name": "Albert Heijn"},
            "creditor_account": {"iban": "NL91ABNA0417164300"},
        }
    ]

    result = _map_eb_transactions(raw)
    assert len(result) == 1
    tx = result[0]
    assert tx.date == date(2026, 4, 10)
    assert tx.amount == Decimal("-42.50")
    assert tx.currency == "EUR"
    assert "Albert Heijn" in tx.description
    assert tx.counterparty == "Albert Heijn"
    assert tx.counterparty_iban == "NL91ABNA0417164300"


def test_map_eb_transactions_debit_indicator():
    """DBIT indicator should negate positive amounts."""
    from app.routers.banking import _map_eb_transactions

    raw = [
        {
            "booking_date": "2026-04-10",
            "transaction_amount": {"amount": "100.00", "currency": "EUR"},
            "credit_debit_indicator": "DBIT",
            "remittance_information": ["Betaling"],
        }
    ]

    result = _map_eb_transactions(raw)
    assert len(result) == 1
    assert result[0].amount == Decimal("-100.00")


def test_map_eb_transactions_credit():
    """Credit transactions should stay positive."""
    from app.routers.banking import _map_eb_transactions

    raw = [
        {
            "booking_date": "2026-04-10",
            "transaction_amount": {"amount": "2500.00", "currency": "EUR"},
            "credit_debit_indicator": "CRDT",
            "remittance_information": ["Salaris"],
            "debtor": {"name": "Werkgever B.V."},
            "debtor_account": {"iban": "NL20INGB0001234567"},
        }
    ]

    result = _map_eb_transactions(raw)
    assert len(result) == 1
    tx = result[0]
    assert tx.amount == Decimal("2500.00")
    assert tx.counterparty == "Werkgever B.V."
    assert tx.counterparty_iban == "NL20INGB0001234567"


def test_map_eb_transactions_missing_date_skipped():
    """Transactions without a date should be skipped."""
    from app.routers.banking import _map_eb_transactions

    raw = [
        {
            "transaction_amount": {"amount": "10.00", "currency": "EUR"},
            "remittance_information": ["Test"],
        }
    ]

    result = _map_eb_transactions(raw)
    assert len(result) == 0


def test_map_eb_transactions_with_balance():
    """Balance after transaction should be mapped."""
    from app.routers.banking import _map_eb_transactions

    raw = [
        {
            "booking_date": "2026-04-10",
            "transaction_amount": {"amount": "-15.00", "currency": "EUR"},
            "remittance_information": ["Test"],
            "balance_after_transaction": {
                "balance_amount": {"amount": "1234.56", "currency": "EUR"},
            },
        }
    ]

    result = _map_eb_transactions(raw)
    assert len(result) == 1
    assert result[0].balance_after == Decimal("1234.56")


def test_map_eb_transactions_unstructured_remittance():
    """Handle remittance_information as dict with unstructured list."""
    from app.routers.banking import _map_eb_transactions

    raw = [
        {
            "booking_date": "2026-04-10",
            "transaction_amount": {"amount": "-5.00", "currency": "EUR"},
            "remittance_information": {
                "unstructured": ["Betaling", "aan winkel"],
            },
        }
    ]

    result = _map_eb_transactions(raw)
    assert len(result) == 1
    assert "Betaling" in result[0].description
    assert "winkel" in result[0].description


def test_import_hash_unique():
    """Each transaction should produce a unique import hash."""
    from app.routers.banking import _map_eb_transactions

    raw = [
        {
            "booking_date": "2026-04-10",
            "transaction_amount": {"amount": "-10.00", "currency": "EUR"},
            "remittance_information": ["Transaction A"],
        },
        {
            "booking_date": "2026-04-10",
            "transaction_amount": {"amount": "-10.00", "currency": "EUR"},
            "remittance_information": ["Transaction B"],
        },
    ]

    result = _map_eb_transactions(raw)
    assert len(result) == 2
    assert result[0].import_hash != result[1].import_hash
