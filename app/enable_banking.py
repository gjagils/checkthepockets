"""Enable Banking API client — PSD2 bank connection via enablebanking.com."""

import time
from datetime import datetime, timezone, timedelta

import jwt as pyjwt
import requests

from app.config import ENABLE_BANKING_APP_ID, ENABLE_BANKING_PRIVATE_KEY_PATH

API_BASE = "https://api.enablebanking.com"


def _load_private_key() -> bytes:
    with open(ENABLE_BANKING_PRIVATE_KEY_PATH, "rb") as f:
        return f.read()


def _make_jwt() -> str:
    """Create a short-lived RS256 JWT for Enable Banking API auth."""
    iat = int(time.time())
    payload = {
        "iss": "enablebanking.com",
        "aud": "api.enablebanking.com",
        "iat": iat,
        "exp": iat + 3600,
    }
    return pyjwt.encode(
        payload,
        _load_private_key(),
        algorithm="RS256",
        headers={"kid": ENABLE_BANKING_APP_ID},
    )


def _headers() -> dict:
    return {"Authorization": f"Bearer {_make_jwt()}"}


# ── Public API helpers ──────────────────────────────────────────────────────


def list_banks(country: str = "NL") -> list[dict]:
    """Return list of available ASPSPs (banks) for a country."""
    r = requests.get(f"{API_BASE}/aspsps", params={"country": country}, headers=_headers())
    r.raise_for_status()
    return r.json().get("aspsps", [])


def start_authorization(
    bank_name: str,
    bank_country: str,
    redirect_url: str,
    state: str,
    valid_days: int = 90,
    psu_type: str = "personal",
) -> dict:
    """Start PSD2 authorization flow. Returns {url, authorization_id}."""
    body = {
        "access": {
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=valid_days)).isoformat(),
        },
        "aspsp": {
            "name": bank_name,
            "country": bank_country,
        },
        "state": state,
        "redirect_url": redirect_url,
        "psu_type": psu_type,
    }
    r = requests.post(f"{API_BASE}/auth", json=body, headers=_headers())
    r.raise_for_status()
    return r.json()


def create_session(code: str) -> dict:
    """Exchange authorization code for a session. Returns {session_id, accounts: [...]}."""
    r = requests.post(f"{API_BASE}/sessions", json={"code": code}, headers=_headers())
    r.raise_for_status()
    return r.json()


def get_session(session_id: str) -> dict:
    """Get session status and accounts."""
    r = requests.get(f"{API_BASE}/sessions/{session_id}", headers=_headers())
    r.raise_for_status()
    return r.json()


def delete_session(session_id: str) -> None:
    """Revoke consent and delete session."""
    r = requests.delete(f"{API_BASE}/sessions/{session_id}", headers=_headers())
    r.raise_for_status()


def get_account_details(account_uid: str) -> dict:
    """Get account holder info and IBAN."""
    r = requests.get(f"{API_BASE}/accounts/{account_uid}/details", headers=_headers())
    r.raise_for_status()
    return r.json()


def get_balances(account_uid: str) -> dict:
    """Get current balances for an account."""
    r = requests.get(f"{API_BASE}/accounts/{account_uid}/balances", headers=_headers())
    r.raise_for_status()
    return r.json()


def get_transactions(
    account_uid: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Fetch transactions for an account. Handles pagination via continuation_key."""
    params = {}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to

    all_transactions = []
    while True:
        r = requests.get(
            f"{API_BASE}/accounts/{account_uid}/transactions",
            params=params,
            headers=_headers(),
        )
        r.raise_for_status()
        data = r.json()
        all_transactions.extend(data.get("transactions", []))
        continuation_key = data.get("continuation_key")
        if not continuation_key:
            break
        params["continuation_key"] = continuation_key

    return all_transactions
