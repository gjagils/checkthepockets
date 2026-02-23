"""
GoCardless / Nordigen Bank Account Data API client.

Handles authentication, institution listing, requisition creation,
and transaction fetching. Uses the REST API directly with requests.

API docs: https://developer.gocardless.com/bank-account-data/overview
"""

import hashlib
import logging
import datetime
from decimal import Decimal
from typing import Any

import requests

from app.config import NORDIGEN_SECRET_ID, NORDIGEN_SECRET_KEY, NORDIGEN_BASE_URL

logger = logging.getLogger(__name__)

# Module-level token cache
_token_cache: dict[str, Any] = {}


class NordigenError(Exception):
    """Raised when the Nordigen API returns an error."""
    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


def _get_access_token() -> str:
    """Get a valid access token, refreshing if needed."""
    now = datetime.datetime.utcnow()

    # Check if we have a valid cached token
    if _token_cache.get("access") and _token_cache.get("access_expires", now) > now:
        return _token_cache["access"]

    # Try refresh token first
    if _token_cache.get("refresh") and _token_cache.get("refresh_expires", now) > now:
        try:
            resp = requests.post(
                f"{NORDIGEN_BASE_URL}/token/refresh/",
                json={"refresh": _token_cache["refresh"]},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                _token_cache["access"] = data["access"]
                _token_cache["access_expires"] = now + datetime.timedelta(
                    seconds=data.get("access_expires", 86400) - 60
                )
                return _token_cache["access"]
        except requests.RequestException:
            pass

    # Get new token pair
    if not NORDIGEN_SECRET_ID or not NORDIGEN_SECRET_KEY:
        raise NordigenError("NORDIGEN_SECRET_ID en NORDIGEN_SECRET_KEY moeten ingesteld zijn")

    resp = requests.post(
        f"{NORDIGEN_BASE_URL}/token/new/",
        json={
            "secret_id": NORDIGEN_SECRET_ID,
            "secret_key": NORDIGEN_SECRET_KEY,
        },
        timeout=15,
    )

    if resp.status_code != 200:
        raise NordigenError(
            f"Kan geen Nordigen token ophalen: {resp.text}",
            status_code=resp.status_code,
        )

    data = resp.json()
    _token_cache["access"] = data["access"]
    _token_cache["refresh"] = data["refresh"]
    _token_cache["access_expires"] = now + datetime.timedelta(
        seconds=data.get("access_expires", 86400) - 60
    )
    _token_cache["refresh_expires"] = now + datetime.timedelta(
        seconds=data.get("refresh_expires", 2592000) - 60
    )

    return _token_cache["access"]


def _headers() -> dict[str, str]:
    """Get authorization headers."""
    token = _get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_institutions(country: str = "NL") -> list[dict]:
    """
    Get list of available banking institutions for a country.
    Returns list of dicts with id, name, logo, etc.
    """
    resp = requests.get(
        f"{NORDIGEN_BASE_URL}/institutions/",
        params={"country": country},
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        raise NordigenError(
            f"Kan bankenlijst niet ophalen: {resp.text}",
            status_code=resp.status_code,
        )
    return resp.json()


def create_requisition(
    institution_id: str,
    redirect_url: str,
    reference: str = "",
    user_language: str = "NL",
    access_valid_for_days: int = 90,
) -> dict:
    """
    Create a new requisition (bank connection request).
    Returns dict with id, link (redirect URL for user), etc.
    """
    # First create an end-user agreement
    agreement_resp = requests.post(
        f"{NORDIGEN_BASE_URL}/agreements/enduser/",
        json={
            "institution_id": institution_id,
            "max_historical_days": 730,
            "access_valid_for_days": access_valid_for_days,
            "access_scope": ["balances", "details", "transactions"],
        },
        headers=_headers(),
        timeout=15,
    )

    agreement_id = None
    if agreement_resp.status_code == 201:
        agreement_id = agreement_resp.json().get("id")
    else:
        # Some institutions don't support custom agreements; proceed without
        logger.warning("Could not create agreement: %s", agreement_resp.text)

    body: dict[str, Any] = {
        "redirect": redirect_url,
        "institution_id": institution_id,
        "reference": reference,
        "user_language": user_language,
    }
    if agreement_id:
        body["agreement"] = agreement_id

    resp = requests.post(
        f"{NORDIGEN_BASE_URL}/requisitions/",
        json=body,
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise NordigenError(
            f"Kan requisition niet aanmaken: {resp.text}",
            status_code=resp.status_code,
        )

    result = resp.json()

    # Include access_valid_for_days in result for caller
    if agreement_resp.status_code == 201:
        agreement_data = agreement_resp.json()
        result["_access_valid_for_days"] = agreement_data.get("access_valid_for_days", access_valid_for_days)
    else:
        result["_access_valid_for_days"] = access_valid_for_days

    return result


def get_requisition(requisition_id: str) -> dict:
    """Get requisition status and linked accounts."""
    resp = requests.get(
        f"{NORDIGEN_BASE_URL}/requisitions/{requisition_id}/",
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        raise NordigenError(
            f"Kan requisition niet ophalen: {resp.text}",
            status_code=resp.status_code,
        )
    return resp.json()


def get_account_details(account_id: str) -> dict:
    """Get account metadata (IBAN, name, etc.)."""
    resp = requests.get(
        f"{NORDIGEN_BASE_URL}/accounts/{account_id}/details/",
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        raise NordigenError(
            f"Kan accountgegevens niet ophalen: {resp.text}",
            status_code=resp.status_code,
        )
    return resp.json().get("account", resp.json())


def get_transactions(account_id: str, date_from: str | None = None) -> list[dict]:
    """
    Fetch transactions for a Nordigen account.
    date_from: ISO date string (YYYY-MM-DD) for incremental sync.
    Returns list of transaction dicts (booked transactions).
    """
    params = {}
    if date_from:
        params["date_from"] = date_from

    resp = requests.get(
        f"{NORDIGEN_BASE_URL}/accounts/{account_id}/transactions/",
        params=params,
        headers=_headers(),
        timeout=30,
    )
    if resp.status_code != 200:
        raise NordigenError(
            f"Kan transacties niet ophalen: {resp.text}",
            status_code=resp.status_code,
        )

    data = resp.json()
    # Nordigen returns {"transactions": {"booked": [...], "pending": [...]}}
    transactions = data.get("transactions", data)
    booked = transactions.get("booked", [])
    return booked


def parse_nordigen_transaction(tx: dict) -> dict:
    """
    Parse a Nordigen transaction dict into our standard format.
    Returns dict with: date, amount, currency, description, counterparty,
    counterparty_iban, balance_after, import_hash.
    """
    # Transaction ID for deduplication
    tx_id = tx.get("transactionId") or tx.get("internalTransactionId") or ""

    # Amount
    amount_info = tx.get("transactionAmount", {})
    amount = Decimal(str(amount_info.get("amount", "0")))
    currency = amount_info.get("currency", "EUR")

    # Date
    date_str = tx.get("bookingDate") or tx.get("valueDate") or ""

    # Description: try multiple fields
    description_parts = []
    for field in ("remittanceInformationUnstructured", "remittanceInformationUnstructuredArray",
                  "additionalInformation"):
        val = tx.get(field)
        if isinstance(val, list):
            description_parts.extend(val)
        elif val:
            description_parts.append(val)
    description = " ".join(description_parts).strip()

    # Counterparty
    creditor = tx.get("creditorName") or ""
    debtor = tx.get("debtorName") or ""
    counterparty = creditor or debtor or None

    # Counterparty IBAN
    creditor_acc = tx.get("creditorAccount", {})
    debtor_acc = tx.get("debtorAccount", {})
    counterparty_iban = creditor_acc.get("iban") or debtor_acc.get("iban") or None

    # Balance after (not always available)
    balance_after = None
    if tx.get("balanceAfterTransaction"):
        bal = tx["balanceAfterTransaction"].get("balanceAmount", {})
        try:
            balance_after = Decimal(str(bal.get("amount", "0")))
        except Exception:
            pass

    # Deduplication hash: use Nordigen transaction ID
    if tx_id:
        import_hash = hashlib.sha256(f"NORDIGEN-{tx_id}".encode()).hexdigest()
    else:
        # Fallback: hash based on content
        raw = f"NORDIGEN|{date_str}|{amount}|{description}|{counterparty or ''}"
        import_hash = hashlib.sha256(raw.encode()).hexdigest()

    return {
        "date": date_str,
        "amount": amount,
        "currency": currency,
        "description": description or counterparty or "Onbekende transactie",
        "counterparty": counterparty,
        "counterparty_iban": counterparty_iban,
        "balance_after": balance_after,
        "import_hash": import_hash,
    }


def delete_requisition(requisition_id: str) -> bool:
    """Delete a requisition from Nordigen."""
    try:
        resp = requests.delete(
            f"{NORDIGEN_BASE_URL}/requisitions/{requisition_id}/",
            headers=_headers(),
            timeout=15,
        )
        return resp.status_code in (200, 204)
    except requests.RequestException:
        return False
