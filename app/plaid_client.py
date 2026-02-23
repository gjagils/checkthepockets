"""
Plaid Bank Account Data API client.

Handles Link token creation, public token exchange, institution lookup,
and transaction syncing. Uses the REST API directly with requests.

API docs: https://plaid.com/docs/api/
"""

import hashlib
import logging
from decimal import Decimal
from typing import Any

import requests

from app.config import PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV, PLAID_REDIRECT_URI

logger = logging.getLogger(__name__)

PLAID_BASE_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}


class PlaidError(Exception):
    """Raised when the Plaid API returns an error."""
    def __init__(self, message: str, error_code: str | None = None, status_code: int | None = None):
        self.error_code = error_code
        self.status_code = status_code
        super().__init__(message)


def _base_url() -> str:
    return PLAID_BASE_URLS.get(PLAID_ENV, PLAID_BASE_URLS["sandbox"])


def _post(endpoint: str, payload: dict, timeout: int = 15) -> dict:
    """Make an authenticated POST request to the Plaid API."""
    if not PLAID_CLIENT_ID or not PLAID_SECRET:
        raise PlaidError("PLAID_CLIENT_ID en PLAID_SECRET moeten ingesteld zijn")

    payload["client_id"] = PLAID_CLIENT_ID
    payload["secret"] = PLAID_SECRET

    resp = requests.post(
        f"{_base_url()}{endpoint}",
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )

    if resp.status_code != 200:
        data = {}
        try:
            data = resp.json()
        except Exception:
            pass
        error_msg = data.get("error_message", resp.text)
        error_code = data.get("error_code")
        raise PlaidError(
            f"Plaid API fout: {error_msg}",
            error_code=error_code,
            status_code=resp.status_code,
        )

    return resp.json()


def create_link_token(
    user_id: str,
    country_codes: list[str] | None = None,
    language: str = "nl",
    products: list[str] | None = None,
) -> str:
    """
    Create a Plaid Link token for initializing the Link widget.
    Returns the link_token string.
    """
    if country_codes is None:
        country_codes = ["NL", "BE", "DE", "FR", "GB"]
    if products is None:
        products = ["transactions"]

    payload = {
        "user": {"client_user_id": str(user_id)},
        "client_name": "Check The Pockets",
        "products": products,
        "country_codes": country_codes,
        "language": language,
    }
    if PLAID_REDIRECT_URI:
        payload["redirect_uri"] = PLAID_REDIRECT_URI

    data = _post("/link/token/create", payload)

    return data["link_token"]


def exchange_public_token(public_token: str) -> dict:
    """
    Exchange a public_token from Plaid Link for a permanent access_token.
    Returns dict with access_token and item_id.
    """
    data = _post("/item/public_token/exchange", {
        "public_token": public_token,
    })

    return {
        "access_token": data["access_token"],
        "item_id": data["item_id"],
    }


def get_item(access_token: str) -> dict:
    """Get item (connection) details."""
    return _post("/item/get", {"access_token": access_token})


def get_institution(institution_id: str, country_codes: list[str] | None = None) -> dict:
    """Get institution details by ID."""
    if country_codes is None:
        country_codes = ["NL", "BE", "DE", "FR", "GB"]

    data = _post("/institutions/get_by_id", {
        "institution_id": institution_id,
        "country_codes": country_codes,
    })

    return data.get("institution", {})


def get_accounts(access_token: str) -> list[dict]:
    """Get all accounts linked to an item."""
    data = _post("/accounts/get", {"access_token": access_token})
    return data.get("accounts", [])


def sync_transactions(access_token: str, cursor: str | None = None) -> dict:
    """
    Fetch transactions using the /transactions/sync endpoint.
    Returns dict with: added, modified, removed, next_cursor, has_more.
    """
    payload: dict[str, Any] = {"access_token": access_token}
    if cursor:
        payload["cursor"] = cursor

    all_added = []
    all_modified = []
    all_removed = []
    has_more = True
    next_cursor = cursor or ""

    while has_more:
        payload["cursor"] = next_cursor if next_cursor else None
        if not payload.get("cursor"):
            payload.pop("cursor", None)

        data = _post("/transactions/sync", payload, timeout=30)

        all_added.extend(data.get("added", []))
        all_modified.extend(data.get("modified", []))
        all_removed.extend(data.get("removed", []))
        next_cursor = data.get("next_cursor", "")
        has_more = data.get("has_more", False)

    return {
        "added": all_added,
        "modified": all_modified,
        "removed": all_removed,
        "next_cursor": next_cursor,
    }


def parse_plaid_transaction(tx: dict) -> dict:
    """
    Parse a Plaid transaction dict into our standard format.
    Returns dict with: date, amount, currency, description, counterparty,
    counterparty_iban, balance_after, import_hash.
    """
    tx_id = tx.get("transaction_id", "")

    # Amount: Plaid uses positive for debits, negative for credits (opposite of our convention)
    raw_amount = tx.get("amount", 0)
    amount = Decimal(str(-raw_amount))  # Flip sign: our convention is negative=expense

    currency = (tx.get("iso_currency_code") or tx.get("unofficial_currency_code") or "EUR").upper()

    date_str = tx.get("date", "")

    # Description
    name = tx.get("name") or tx.get("merchant_name") or ""
    original_description = tx.get("original_description") or ""
    description = name or original_description or "Onbekende transactie"

    # Counterparty
    counterparty = tx.get("merchant_name") or name or None
    counterparty_details = tx.get("counterparties", [])
    if counterparty_details and isinstance(counterparty_details, list):
        counterparty = counterparty_details[0].get("name") or counterparty

    # Plaid doesn't provide counterparty IBAN
    counterparty_iban = None

    # Balance after (not available per-transaction in Plaid sync)
    balance_after = None

    # Deduplication hash
    if tx_id:
        import_hash = hashlib.sha256(f"PLAID-{tx_id}".encode()).hexdigest()
    else:
        raw = f"PLAID|{date_str}|{amount}|{description}|{counterparty or ''}"
        import_hash = hashlib.sha256(raw.encode()).hexdigest()

    return {
        "date": date_str,
        "amount": amount,
        "currency": currency,
        "description": description,
        "counterparty": counterparty,
        "counterparty_iban": counterparty_iban,
        "balance_after": balance_after,
        "import_hash": import_hash,
    }


def remove_item(access_token: str) -> bool:
    """Remove an item (disconnect bank)."""
    try:
        _post("/item/remove", {"access_token": access_token})
        return True
    except PlaidError:
        return False
