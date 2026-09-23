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

LIVE_TESTS = os.getenv("ENABLE_BANKING_LIVE_TESTS", "false").lower() == "true"

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
    if not LIVE_TESTS:
        pytest.skip("Live Enable Banking tests disabled; set ENABLE_BANKING_LIVE_TESTS=true")
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
    if not LIVE_TESTS:
        pytest.skip("Live Enable Banking tests disabled; set ENABLE_BANKING_LIVE_TESTS=true")
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


# ── Bank lookup, consent-duur en foutmeldingen ─────────────────────────────


_NL_BANKS = [
    {"name": "bunq", "country": "NL", "psu_types": ["personal", "business"], "maximum_consent_validity": 15552000},
    {"name": "ABN AMRO", "country": "NL", "psu_types": ["business", "personal"], "maximum_consent_validity": 15552000},
    {"name": "Trade Republic", "country": "NL", "psu_types": ["personal"], "maximum_consent_validity": 7776000},
    {"name": "BNG Bank", "country": "NL", "psu_types": ["business"], "maximum_consent_validity": 15552000},
]


def test_find_bank_is_case_insensitive():
    """'Bunq' (zoals de oude placeholder suggereerde) moet 'bunq' opleveren —
    de API weigert anders met 422 WRONG_ASPSP_PROVIDED."""
    from app.enable_banking import find_bank

    assert find_bank("Bunq", banks=_NL_BANKS)["name"] == "bunq"
    assert find_bank("BUNQ", banks=_NL_BANKS)["name"] == "bunq"
    assert find_bank("abn amro", banks=_NL_BANKS)["name"] == "ABN AMRO"


def test_find_bank_normalizes_whitespace():
    from app.enable_banking import find_bank

    assert find_bank("  ABN   AMRO ", banks=_NL_BANKS)["name"] == "ABN AMRO"


def test_find_bank_unknown_returns_none():
    from app.enable_banking import find_bank

    assert find_bank("Rabo", banks=_NL_BANKS) is None
    assert find_bank("", banks=_NL_BANKS) is None
    assert find_bank("   ", banks=_NL_BANKS) is None


def test_list_banks_filters_on_psu_type():
    from app.enable_banking import list_banks

    class FakeResp:
        ok = True
        def json(self):
            return {"aspsps": _NL_BANKS}

    with patch("app.enable_banking.requests.get", return_value=FakeResp()), \
         patch("app.enable_banking._headers", return_value={}):
        names = [b["name"] for b in list_banks("NL", psu_type="personal")]

    assert "bunq" in names and "ABN AMRO" in names
    assert "BNG Bank" not in names  # business-only


def test_consent_days_clamped_to_bank_maximum():
    from app.enable_banking import consent_days_for, DEFAULT_CONSENT_DAYS

    assert DEFAULT_CONSENT_DAYS == 180
    assert consent_days_for(_NL_BANKS[0]) == 180          # 15552000s = 180d
    assert consent_days_for(_NL_BANKS[2]) == 90           # Trade Republic: 7776000s = 90d
    assert consent_days_for(None) == 180                  # onbekend → default
    assert consent_days_for({"maximum_consent_validity": 0}) == 180
    assert consent_days_for(_NL_BANKS[0], requested_days=30) == 30


def test_enable_banking_error_includes_api_message():
    """De exception moet de foutcode + melding uit de JSON-body bevatten, niet
    alleen '422 Client Error: unknown'."""
    from app.enable_banking import EnableBankingError, _check

    class FakeResp:
        ok = False
        status_code = 422
        url = "https://api.enablebanking.com/auth"
        text = '{"code": 422, "message": "Wrong ASPSP name provided", "error": "WRONG_ASPSP_PROVIDED"}'
        def json(self):
            return {"code": 422, "message": "Wrong ASPSP name provided", "error": "WRONG_ASPSP_PROVIDED", "detail": None}

    with pytest.raises(EnableBankingError) as exc:
        _check(FakeResp())

    assert exc.value.code == "WRONG_ASPSP_PROVIDED"
    assert "Wrong ASPSP name provided" in str(exc.value)
    assert "WRONG_ASPSP_PROVIDED" in str(exc.value)
    assert "422" in str(exc.value)


def test_enable_banking_error_non_json_body():
    from app.enable_banking import EnableBankingError, _check

    class FakeResp:
        ok = False
        status_code = 502
        url = "https://api.enablebanking.com/sessions"
        text = "<html>Bad Gateway</html>"
        def json(self):
            raise ValueError("not json")

    with pytest.raises(EnableBankingError) as exc:
        _check(FakeResp())

    assert exc.value.code is None
    assert "502" in str(exc.value)
    assert "Bad Gateway" in str(exc.value)


def test_check_returns_response_when_ok():
    from app.enable_banking import _check

    class FakeResp:
        ok = True

    r = FakeResp()
    assert _check(r) is r


def test_consent_valid_until_from_session_response():
    """Gebruik de echte vervaldatum uit access.valid_until (met tijdzone) als
    naïeve UTC; val terug op nu + fallback als het veld ontbreekt."""
    from datetime import datetime, timedelta
    from app.routers.banking import _consent_valid_until

    dt = _consent_valid_until({"access": {"valid_until": "2026-12-01T10:30:00+02:00"}}, fallback_days=180)
    assert dt == datetime(2026, 12, 1, 8, 30, 0)
    assert dt.tzinfo is None

    dt = _consent_valid_until({"access": {"valid_until": "2026-12-01T10:30:00Z"}}, fallback_days=180)
    assert dt == datetime(2026, 12, 1, 10, 30, 0)

    before = datetime.utcnow()
    dt = _consent_valid_until({}, fallback_days=90)
    assert timedelta(days=89, hours=23) < dt - before < timedelta(days=90, minutes=1)

    dt = _consent_valid_until({"access": {"valid_until": "garbage"}}, fallback_days=10)
    assert timedelta(days=9, hours=23) < dt - datetime.utcnow() < timedelta(days=10, minutes=1)
