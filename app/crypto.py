"""
Field-level encryption for sensitive transaction data (Sprint 16).

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the cryptography library.
Encryption is transparent via SQLAlchemy TypeDecorator.

Set FIELD_ENCRYPTION_KEY in environment to enable encryption.
Generate a key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If FIELD_ENCRYPTION_KEY is not set, data is stored as plain text (backward compatible).
If a value cannot be decrypted (legacy unencrypted data), it is returned as-is.
"""

import logging
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config import FIELD_ENCRYPTION_KEY

logger = logging.getLogger(__name__)

_fernet = None

if FIELD_ENCRYPTION_KEY:
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(FIELD_ENCRYPTION_KEY.encode())
        logger.info("Field encryption enabled.")
    except Exception as exc:
        logger.error("Failed to initialize field encryption: %s", exc)


class EncryptedText(TypeDecorator):
    """
    Transparently encrypts/decrypts a text value using Fernet.
    Falls back to plain text when FIELD_ENCRYPTION_KEY is not set.
    Handles legacy unencrypted rows gracefully (returns plain text as-is).
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Encrypt before writing to DB."""
        if value is None or _fernet is None:
            return value
        try:
            return _fernet.encrypt(value.encode()).decode()
        except Exception:
            return value

    def process_result_value(self, value, dialect):
        """Decrypt after reading from DB."""
        if value is None or _fernet is None:
            return value
        try:
            return _fernet.decrypt(value.encode()).decode()
        except Exception:
            # Legacy unencrypted value — return as-is
            return value


def encryption_enabled() -> bool:
    return _fernet is not None


def encrypt_existing_transactions(db) -> int:
    """
    Re-save all transactions to trigger encryption of existing plain-text data.
    Only useful when FIELD_ENCRYPTION_KEY is newly set.
    Returns number of transactions processed.
    """
    if _fernet is None:
        return 0

    from app.models import Transaction
    transactions = db.query(Transaction).all()
    count = 0
    for tx in transactions:
        # Access the raw value to check if it's already encrypted (starts with 'gAAA')
        for field in ("counterparty", "counterparty_iban", "description"):
            val = getattr(tx, field)
            if val and not val.startswith("gAAA"):
                # Unencrypted — re-assign to trigger encryption on next flush
                setattr(tx, field, val)
                count += 1
                break

    db.commit()
    return count
