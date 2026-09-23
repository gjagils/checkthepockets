"""Enable Banking API client — PSD2 bank connection via enablebanking.com."""

import time
import os
from datetime import datetime, timezone, timedelta

import jwt as pyjwt
import requests
from urllib.parse import urlsplit

from app.config import ENABLE_BANKING_APP_ID, ENABLE_BANKING_PRIVATE_KEY_PATH

API_BASE = "https://api.enablebanking.com"


def _load_private_key() -> bytes:
    # Read the path at call time as well as at import time. This keeps tests and
    # long-running processes correct when configuration is loaded before an
    # integration test sets its environment variables.
    path = os.getenv("ENABLE_BANKING_PRIVATE_KEY_PATH") or ENABLE_BANKING_PRIVATE_KEY_PATH
    with open(path, "rb") as f:
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
        headers={"kid": os.getenv("ENABLE_BANKING_APP_ID") or ENABLE_BANKING_APP_ID},
    )


def _headers() -> dict:
    return {"Authorization": f"Bearer {_make_jwt()}"}


_ID_PATH_PARENTS = {"sessions", "accounts"}


def _redact_url(url) -> str:
    """Path of an API URL without session/account IDs or query parameters."""
    segments = urlsplit(str(url)).path.split("/")
    for i in range(1, len(segments)):
        if segments[i - 1] in _ID_PATH_PARENTS and segments[i]:
            segments[i] = "<id>"
    return "/".join(segments)


class EnableBankingError(requests.HTTPError):
    """HTTP-fout van de Enable Banking API, inclusief de foutcode en
    -melding uit de JSON-body (bv. WRONG_ASPSP_PROVIDED). De standaard
    HTTPError toont alleen de status + reason ("422 Client Error: unknown"),
    wat niets zegt over de werkelijke oorzaak."""

    def __init__(self, response: requests.Response):
        self.code = None
        detail = ""
        try:
            body = response.json()
            self.code = body.get("error")
            parts = [p for p in (body.get("error"), body.get("message")) if p]
            detail = " — ".join(parts)
        except ValueError:
            detail = (response.text or "")[:200]
        msg = f"{response.status_code} {detail or 'onbekende fout'} (pad: {_redact_url(response.url)})"
        super().__init__(msg, response=response)


def safe_error_message(exc: Exception) -> str:
    """Error text for logs and users without session/account IDs.

    Network errors from requests quote the full request path, so only the
    exception type is kept for those.
    """
    if isinstance(exc, EnableBankingError):
        return str(exc)
    if isinstance(exc, requests.RequestException):
        return f"verbinding met Enable Banking mislukt ({type(exc).__name__})"
    return f"{type(exc).__name__}: {exc}"


def _check(r: requests.Response) -> requests.Response:
    """raise_for_status(), maar met de API-foutmelding in de exception."""
    if not r.ok:
        raise EnableBankingError(r)
    return r


# ── Public API helpers ──────────────────────────────────────────────────────


DEFAULT_CONSENT_DAYS = 180


def list_banks(country: str = "NL", psu_type: str | None = None) -> list[dict]:
    """Return list of available ASPSPs (banks) for a country.

    Met psu_type (bv. "personal") worden alleen banken teruggegeven die dat
    type klant ondersteunen — een business-only bank geeft anders een 422
    bij /auth."""
    r = requests.get(f"{API_BASE}/aspsps", params={"country": country}, headers=_headers())
    _check(r)
    banks = r.json().get("aspsps", [])
    if psu_type:
        banks = [b for b in banks if psu_type in (b.get("psu_types") or [])]
    return banks


def _norm_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def find_bank(name: str, country: str = "NL", banks: list[dict] | None = None) -> dict | None:
    """Zoek een ASPSP op naam, ongevoelig voor hoofdletters en spaties.

    Enable Banking eist bij /auth de exacte naam ("bunq", niet "Bunq") en
    antwoordt anders met 422 WRONG_ASPSP_PROVIDED. Geeft het ASPSP-record
    terug (met de canonieke naam) of None."""
    wanted = _norm_name(name)
    if not wanted:
        return None
    if banks is None:
        banks = list_banks(country)
    return next((b for b in banks if _norm_name(b.get("name", "")) == wanted), None)


def consent_days_for(bank: dict | None, requested_days: int = DEFAULT_CONSENT_DAYS) -> int:
    """Aantal dagen consent om aan te vragen, begrensd op het maximum van de
    bank (maximum_consent_validity, in seconden). Een te lange geldigheid
    wordt door de API geweigerd."""
    max_seconds = (bank or {}).get("maximum_consent_validity")
    if not max_seconds:
        return requested_days
    return max(1, min(requested_days, int(max_seconds) // 86400))


def start_authorization(
    bank_name: str,
    bank_country: str,
    redirect_url: str,
    state: str,
    valid_days: int = DEFAULT_CONSENT_DAYS,
    psu_type: str = "personal",
) -> dict:
    """Start PSD2 authorization flow. Returns {url, authorization_id}.

    bank_name moet de exacte ASPSP-naam zijn — gebruik find_bank()."""
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
    _check(r)
    return r.json()


def create_session(code: str) -> dict:
    """Exchange authorization code for a session. Returns {session_id, accounts: [...]}."""
    r = requests.post(f"{API_BASE}/sessions", json={"code": code}, headers=_headers())
    _check(r)
    return r.json()


def get_session(session_id: str) -> dict:
    """Get session status and accounts."""
    r = requests.get(f"{API_BASE}/sessions/{session_id}", headers=_headers())
    _check(r)
    return r.json()


def delete_session(session_id: str) -> None:
    """Revoke consent and delete session."""
    r = requests.delete(f"{API_BASE}/sessions/{session_id}", headers=_headers())
    _check(r)


def get_account_details(account_uid: str) -> dict:
    """Get account holder info and IBAN."""
    r = requests.get(f"{API_BASE}/accounts/{account_uid}/details", headers=_headers())
    _check(r)
    return r.json()


def get_balances(account_uid: str) -> dict:
    """Get current balances for an account."""
    r = requests.get(f"{API_BASE}/accounts/{account_uid}/balances", headers=_headers())
    _check(r)
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
        _check(r)
        data = r.json()
        all_transactions.extend(data.get("transactions", []))
        continuation_key = data.get("continuation_key")
        if not continuation_key:
            break
        params["continuation_key"] = continuation_key

    return all_transactions
