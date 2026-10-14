"""Minimal bunq API client for a personal API key (ACT-31a: connect and list accounts).

Flow: POST /installation (own RSA public key) → POST /device-server (binds the
API key to this device and IP) → POST /session-server → GET monetary-account.
POST bodies are signed with the client's private key. The server's response
signature is not verified (transport security is TLS only); this client only reads.

Secrets (API key, tokens, private key) never appear in exceptions or logs.
"""
import base64
import json
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

logger = logging.getLogger(__name__)

USER_AGENT = "checkthepockets/1.0"
TIMEOUT = 20


class BunqError(Exception):
    """Failure talking to bunq; message is safe to show to the user."""

    def __init__(self, message: str, status: int | None = None, kind: str = "error"):
        super().__init__(message)
        self.status = status
        self.kind = kind  # "auth" (key/installation/IP rejected), "rate_limit", "error"


@dataclass
class BunqAccount:
    kind: str            # e.g. MonetaryAccountBank, MonetaryAccountSavings
    id: int
    description: str
    status: str
    iban: str | None
    balance: Decimal | None
    currency: str


@dataclass
class BunqSession:
    token: str
    user_id: int
    installation_token: str
    private_key_pem: str


def generate_private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _public_key_pem(private_key_pem: str) -> str:
    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def _sign(private_key_pem: str, body: str) -> str:
    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    signature = key.sign(body.encode(), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode()


def _item(response: dict, name: str) -> dict | None:
    for entry in response.get("Response", []):
        if isinstance(entry, dict) and name in entry:
            return entry[name]
    return None


def _error_message(response) -> str:
    try:
        errors = response.json().get("Error") or []
        text = "; ".join(e.get("error_description", "") for e in errors if isinstance(e, dict)).strip()
    except ValueError:
        text = ""
    return text or f"bunq gaf HTTP {response.status_code}"


class BunqClient:
    def __init__(self, base_url: str, http=requests):
        self.base_url = base_url.rstrip("/")
        self.http = http

    def _request(self, method: str, path: str, *, token: str | None = None,
                 body: dict | None = None, private_key_pem: str | None = None) -> dict:
        headers = {
            "User-Agent": USER_AGENT,
            "Cache-Control": "no-cache",
            "X-Bunq-Language": "nl_NL",
            "X-Bunq-Region": "nl_NL",
            "X-Bunq-Geolocation": "0 0 0 0 000",
            "X-Bunq-Client-Request-Id": str(uuid.uuid4()),
        }
        data = None
        if token:
            headers["X-Bunq-Client-Authentication"] = token
        if body is not None:
            data = json.dumps(body)
            headers["Content-Type"] = "application/json"
            if private_key_pem:
                headers["X-Bunq-Client-Signature"] = _sign(private_key_pem, data)
        try:
            response = self.http.request(
                method, f"{self.base_url}{path}", headers=headers, data=data, timeout=TIMEOUT)
        except requests.RequestException as exc:
            # exc text can contain the URL only; never the headers or body.
            raise BunqError("bunq is niet bereikbaar (netwerkfout of time-out).") from exc
        if response.status_code == 429:
            raise BunqError("Te veel verzoeken naar bunq; probeer het over een paar seconden opnieuw.",
                            429, "rate_limit")
        if response.status_code >= 400:
            kind = "auth" if response.status_code in (401, 403) else "error"
            raise BunqError(_error_message(response), response.status_code, kind)
        try:
            return response.json()
        except ValueError as exc:
            raise BunqError("Onverwacht antwoord van bunq (geen JSON).", response.status_code) from exc

    def register(self, api_key: str) -> tuple[str, str]:
        """Create installation and register this device. Returns (private_key_pem, installation_token)."""
        private_key_pem = generate_private_key_pem()
        installation = self._request(
            "POST", "/installation", body={"client_public_key": _public_key_pem(private_key_pem)})
        token = (_item(installation, "Token") or {}).get("token")
        if not token:
            raise BunqError("bunq gaf geen installatietoken terug.")
        self._request(
            "POST", "/device-server", token=token, private_key_pem=private_key_pem,
            body={"description": "Check The Pockets", "secret": api_key})
        return private_key_pem, token

    def open_session(self, api_key: str, private_key_pem: str, installation_token: str) -> BunqSession:
        response = self._request(
            "POST", "/session-server", token=installation_token, private_key_pem=private_key_pem,
            body={"secret": api_key})
        token = (_item(response, "Token") or {}).get("token")
        user_id = None
        for entry in response.get("Response", []):
            if isinstance(entry, dict):
                for name, value in entry.items():
                    if name.startswith("User") and isinstance(value, dict) and value.get("id"):
                        user_id = value["id"]
        if not token or not user_id:
            raise BunqError("bunq gaf geen sessie of gebruiker terug.")
        return BunqSession(token, int(user_id), installation_token, private_key_pem)

    def connect(self, api_key: str, private_key_pem: str | None = None,
                installation_token: str | None = None) -> BunqSession:
        """Open a session, (re)registering the device when needed.

        A stored installation is tried first. If bunq rejects it (for example after
        the IP address changed) the device is registered again once, with the same key.
        """
        if private_key_pem and installation_token:
            try:
                return self.open_session(api_key, private_key_pem, installation_token)
            except BunqError as exc:
                if exc.kind != "auth":
                    raise
                logger.info("bunq: opgeslagen installatie geweigerd, apparaat opnieuw registreren")
            except ValueError:
                logger.warning("bunq: opgeslagen sleutelpaar onleesbaar, apparaat opnieuw registreren")
        private_key_pem, installation_token = self.register(api_key)
        return self.open_session(api_key, private_key_pem, installation_token)

    def list_accounts(self, session: BunqSession) -> list[BunqAccount]:
        response = self._request(
            "GET", f"/user/{session.user_id}/monetary-account?count=200", token=session.token)
        accounts = []
        for entry in response.get("Response", []):
            if not isinstance(entry, dict):
                continue
            for kind, value in entry.items():
                if not kind.startswith("MonetaryAccount") or not isinstance(value, dict):
                    continue
                iban = next((a.get("value") for a in value.get("alias") or []
                             if isinstance(a, dict) and a.get("type") == "IBAN"), None)
                balance = value.get("balance") or {}
                try:
                    amount = Decimal(balance["value"]) if balance.get("value") is not None else None
                except (InvalidOperation, KeyError):
                    amount = None
                accounts.append(BunqAccount(
                    kind=kind, id=int(value.get("id", 0)),
                    description=value.get("description") or "",
                    status=value.get("status") or "",
                    iban=iban, balance=amount, currency=balance.get("currency") or "EUR",
                ))
        return accounts
