import pytest

import app.crypto as crypto


def test_invalid_configured_key_refuses_plaintext(monkeypatch):
    monkeypatch.setattr(crypto, "_encryption_configured", True)
    monkeypatch.setattr(crypto, "_fernet", None)
    with pytest.raises(RuntimeError, match="refusing plain-text"):
        crypto.EncryptedText().process_bind_param("secret", None)


def test_encryption_error_refuses_plaintext(monkeypatch):
    class Broken:
        def encrypt(self, value):
            raise ValueError("broken")

    monkeypatch.setattr(crypto, "_encryption_configured", True)
    monkeypatch.setattr(crypto, "_fernet", Broken())
    with pytest.raises(RuntimeError, match="refusing plain-text"):
        crypto.EncryptedText().process_bind_param("secret", None)


def test_corrupt_ciphertext_is_not_treated_as_legacy_plaintext(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(crypto, "_fernet", Fernet(Fernet.generate_key()))
    with pytest.raises(RuntimeError, match="decrypt"):
        crypto.EncryptedText().process_result_value("gAAAA-corrupt", None)
