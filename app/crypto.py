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
_encryption_configured = bool(FIELD_ENCRYPTION_KEY)

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
        if value is None:
            return value
        if _encryption_configured and _fernet is None:
            raise RuntimeError("FIELD_ENCRYPTION_KEY is configured but invalid; refusing plain-text storage")
        if _fernet is None:
            return value
        try:
            return _fernet.encrypt(value.encode()).decode()
        except Exception as exc:
            raise RuntimeError("Unable to encrypt sensitive field; refusing plain-text storage") from exc

    def process_result_value(self, value, dialect):
        """Decrypt after reading from DB."""
        if value is None:
            return value
        if _fernet is None:
            if _encryption_configured:
                raise RuntimeError("FIELD_ENCRYPTION_KEY is configured but invalid; refusing to return ciphertext")
            return value
        # Values without Fernet's marker are legacy plaintext. Ciphertext that
        # has the marker but fails authentication is corruption/key mismatch.
        if not value.startswith("gAAAA"):
            return value
        try:
            return _fernet.decrypt(value.encode()).decode()
        except Exception as exc:
            raise RuntimeError("Unable to decrypt sensitive field; key may be wrong or data corrupted") from exc


def encryption_enabled() -> bool:
    return _fernet is not None


def encrypt_existing_transactions(db) -> int:
    """
    Encrypt transactions that are still stored as plain text.
    Only useful when FIELD_ENCRYPTION_KEY is newly set.
    Returns number of transactions processed.

    The raw column values are read with type_coerce (the ORM would hand back the
    already-decrypted value, so a plaintext/ciphertext check on it is meaningless)
    and written back through a Core UPDATE, which runs the encrypting bind processor.
    """
    if _fernet is None:
        return 0

    from sqlalchemy import Text, select, type_coerce, update
    from app.models import Transaction

    fields = ("counterparty", "counterparty_iban", "description")
    rows = db.execute(
        select(Transaction.id, *[type_coerce(getattr(Transaction, f), Text) for f in fields])
    ).all()
    count = 0
    for row in rows:
        values = {
            field: raw
            for field, raw in zip(fields, row[1:])
            if raw and not raw.startswith("gAAAA")
        }
        if values:
            db.execute(update(Transaction).where(Transaction.id == row[0]).values(**values))
            count += 1

    db.commit()
    return count
