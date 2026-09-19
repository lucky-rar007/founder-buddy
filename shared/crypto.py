"""
Encryption utilities for securing sensitive configuration values.

Uses Fernet symmetric encryption from the `cryptography` package.
The encryption key can be provided in two ways (in priority order):
  1. ENCRYPTION_KEY environment variable (recommended for Docker/cloud deployments)
  2. data/.encryption_key file (auto-generated on first use; gitignored)
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
_KEY_FILE = _WORKSPACE_ROOT / "data" / ".encryption_key"
_SIG_FILE = _KEY_FILE.with_name(".encryption_key.sig")


class ConfigEncryptor:
    """
    Fernet-based encryptor for configuration secrets.

    On first instantiation, generates a new key and persists it with an integrity digest.
    On subsequent uses, loads and verifies the existing key.
    """

    def __init__(self):
        self.key: bytes = self._load_or_create_key()
        self.cipher = Fernet(self.key)

    def _load_or_create_key(self) -> bytes:
        """Load key from ENCRYPTION_KEY env var, existing file, or generate a new one."""
        import hashlib
        import hmac

        # Priority 1: ENCRYPTION_KEY environment variable (for Docker/cloud deployments)
        env_key = os.environ.get("ENCRYPTION_KEY", "").strip()
        if env_key:
            try:
                key = env_key.encode("utf-8")
                Fernet(key)  # Validate it's a valid Fernet key
                logger.info("[Crypto] Encryption key loaded from ENCRYPTION_KEY environment variable.")
                return key
            except Exception:
                logger.warning("[Crypto] ENCRYPTION_KEY env var is invalid. Falling back to key file.")

        # Priority 2: Existing key file with integrity check (S-4)
        if _KEY_FILE.exists():
            key = _KEY_FILE.read_bytes().strip()
            if key:
                if _SIG_FILE.exists():
                    expected_sig = _SIG_FILE.read_text().strip()
                    actual_sig = hashlib.sha256(key).hexdigest()
                    if not hmac.compare_digest(expected_sig, actual_sig):
                        logger.error("[Crypto] Key file integrity check failed! Key file may have been tampered with.")
                        raise ValueError("Encryption key integrity check failed: signature mismatch.")
                else:
                    # Write signature for legacy key file
                    try:
                        _SIG_FILE.write_text(hashlib.sha256(key).hexdigest())
                    except Exception:
                        pass
                return key

        # Priority 3: Generate new key and persist to file with signature
        key = Fernet.generate_key()
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_bytes(key)
        try:
            _SIG_FILE.write_text(hashlib.sha256(key).hexdigest())
        except Exception:
            pass

        # Restrict to owner-only read/write (0o600)
        try:
            import stat
            _KEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
            if _SIG_FILE.exists():
                _SIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except (OSError, AttributeError):
            pass  # Windows may not support POSIX permissions fully
        logger.info("[Crypto] Generated new encryption key and saved to file with integrity signature.")
        return key

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a string value.

        Args:
            plaintext: The value to encrypt.

        Returns:
            Base64-encoded ciphertext string.
        """
        if not plaintext:
            return ""
        return self.cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a previously encrypted value.

        Args:
            ciphertext: Base64-encoded ciphertext from encrypt().

        Returns:
            Original plaintext string.

        Raises:
            InvalidToken: If the ciphertext is invalid or the key doesn't match.
        """
        if not ciphertext:
            return ""
        try:
            return self.cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.error("[Crypto] Failed to decrypt value — invalid token or wrong key.")
            raise


# Module-level singleton
decryptor = ConfigEncryptor()
