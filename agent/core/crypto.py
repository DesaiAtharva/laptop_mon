"""
agent/core/crypto.py — Authenticated Encryption & Key Management.

Adheres to:
- Authenticated encryption (AES-256-GCM) for journal payloads and spool files.
- Edge Case E22: If encryption key is unavailable, NEVER upload plaintext, keep files, report status.
- Zero OS-specific imports. Key store uses pluggable backend or secure storage abstraction.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KeyStoreProtocol(Protocol):
    """Protocol for secure key retrieval from OS secure store or memory."""

    def get_encryption_key(self) -> Optional[bytes]:
        """Returns 32-byte key or None if unavailable/locked."""
        ...

    def set_encryption_key(self, key: bytes) -> None:
        """Stores the 32-byte encryption key."""
        ...


class FileKeyStore:
    """
    Standard filesystem key store with restricted file permissions.
    Used when OS-specific credential managers are not directly invoked.
    """

    def __init__(self, key_path: str) -> None:
        self.key_path = key_path

    def get_encryption_key(self) -> Optional[bytes]:
        if not os.path.exists(self.key_path):
            return None
        try:
            with open(self.key_path, "rb") as f:
                key = f.read()
                if len(key) == 32:
                    return key
                return None
        except OSError:
            return None

    def set_encryption_key(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Key must be 32 bytes (256 bits)")
        os.makedirs(os.path.dirname(os.path.abspath(self.key_path)), exist_ok=True)
        # Write with owner-only permissions where supported
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = 0o600
        fd = os.open(self.key_path, flags, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(key)


class InMemoryKeyStore:
    """In-memory key store for tests and deterministic simulations."""

    def __init__(self, initial_key: Optional[bytes] = None) -> None:
        self._key: Optional[bytes] = initial_key

    def get_encryption_key(self) -> Optional[bytes]:
        return self._key

    def set_encryption_key(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Key must be 32 bytes (256 bits)")
        self._key = key

    def revoke_key(self) -> None:
        """Simulates key loss or locked key store (E22)."""
        self._key = None


class CryptoManager:
    """
    Manages authenticated encryption and decryption for the agent.
    """

    def __init__(self, key_store: KeyStoreProtocol) -> None:
        self.key_store = key_store

    def is_key_available(self) -> bool:
        """Returns True if a valid 32-byte encryption key is accessible."""
        return self.key_store.get_encryption_key() is not None

    def generate_and_save_key(self) -> bytes:
        """Generates a fresh 256-bit cryptographically secure key and persists it."""
        key = AESGCM.generate_key(bit_length=256)
        self.key_store.set_encryption_key(key)
        return key

    def encrypt(self, plaintext: bytes, associated_data: Optional[bytes] = None) -> Tuple[bytes, bytes]:
        """
        Encrypts plaintext using AES-256-GCM.
        Returns (ciphertext_with_auth_tag, nonce).
        Raises KeyError if key is unavailable (E22).
        """
        key = self.key_store.get_encryption_key()
        if key is None:
            raise KeyError("Encryption key is unavailable (E22)")

        aesgcm = AESGCM(key)
        # Standard 96-bit (12-byte) nonce for AES-GCM
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data)
        return ciphertext, nonce

    def decrypt(self, ciphertext: bytes, nonce: bytes, associated_data: Optional[bytes] = None) -> bytes:
        """
        Decrypts ciphertext using AES-256-GCM with authenticated verification.
        Raises KeyError if key is unavailable, or cryptography.exceptions.InvalidTag on tamper.
        """
        key = self.key_store.get_encryption_key()
        if key is None:
            raise KeyError("Encryption key is unavailable (E22)")

        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, associated_data)
