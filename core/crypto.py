"""Encryption at rest and password hashing.

Frames are stored in the database as Fernet-encrypted blobs (AES-128-CBC +
HMAC via the cryptography library). The key comes from, in order:

1. LAKSHYA_SECRET_KEY in the environment (any passphrase; it is derived), or
2. a key file `<data dir>/.secret.key`, created on first use with 0600
   permissions.

Without the key (or passphrase) the database contents are unreadable, so back
up the key file together with the database. Passwords are never stored: only
PBKDF2-HMAC-SHA256 hashes with a per-user salt.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import os
import secrets
import zlib
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_PBKDF2_ITERATIONS = 240_000
_fernets: dict[str, Fernet] = {}


# ---------------------------------------------------------------- data key --
def _derive_key(passphrase: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(passphrase.encode("utf-8")).digest())


def _key_file() -> Path:
    from . import store
    return store.data_dir() / ".secret.key"


def _load_key() -> bytes:
    passphrase = os.environ.get("LAKSHYA_SECRET_KEY", "").strip()
    if passphrase:
        return _derive_key(passphrase)
    path = _key_file()
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def fernet() -> Fernet:
    cache_key = os.environ.get("LAKSHYA_SECRET_KEY", "") or str(_key_file())
    if cache_key not in _fernets:
        _fernets[cache_key] = Fernet(_load_key())
    return _fernets[cache_key]


def encrypt_bytes(raw: bytes) -> str:
    return fernet().encrypt(zlib.compress(raw, 6)).decode("ascii")


def decrypt_bytes(token: str) -> bytes:
    return zlib.decompress(fernet().decrypt(token.encode("ascii")))


# ---------------------------------------------------------------- passwords --
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, iterations, salt, expected = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return hmac_mod.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


__all__ = ["encrypt_bytes", "decrypt_bytes", "hash_password", "verify_password", "InvalidToken", "fernet"]
