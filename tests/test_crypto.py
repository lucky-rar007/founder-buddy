"""
Tests for ConfigEncryptor (Fernet encryption and key integrity verification).
"""

import os
import pytest
from cryptography.fernet import InvalidToken
from shared.crypto import ConfigEncryptor


def test_encrypt_decrypt_roundtrip():
    """Verify that plaintext strings can be encrypted and decrypted back accurately."""
    encryptor = ConfigEncryptor()
    secret = "my-super-secret-azure-client-secret-12345!@#"
    ciphertext = encryptor.encrypt(secret)

    assert ciphertext != secret
    assert isinstance(ciphertext, str)
    decrypted = encryptor.decrypt(ciphertext)
    assert decrypted == secret


def test_empty_string_handling():
    """Verify encrypt and decrypt return empty strings for empty input."""
    encryptor = ConfigEncryptor()
    assert encryptor.encrypt("") == ""
    assert encryptor.decrypt("") == ""


def test_invalid_token_handling():
    """Verify decrypting corrupted or invalid ciphertext raises InvalidToken."""
    encryptor = ConfigEncryptor()
    with pytest.raises(InvalidToken):
        encryptor.decrypt("invalid-base64-not-a-fernet-token")


def test_tampered_key_detection(tmp_path, monkeypatch):
    """Verify that modifying the key file without updating signature raises ValueError."""
    key_file = tmp_path / ".encryption_key"
    sig_file = tmp_path / ".encryption_key.sig"

    monkeypatch.setattr("shared.crypto._KEY_FILE", key_file)
    monkeypatch.setattr("shared.crypto._SIG_FILE", sig_file)

    # First initialization generates key and sig
    enc1 = ConfigEncryptor()
    assert key_file.exists()
    assert sig_file.exists()

    # Now tamper with key file
    key_file.write_bytes(b"tampered-corrupted-key-bytes-here!!")

    # Second initialization should detect signature mismatch
    with pytest.raises(ValueError, match="integrity check failed"):
        ConfigEncryptor()
