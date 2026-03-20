import hashlib
import os
import platform
import base64
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend


def _machine_fingerprint() -> bytes:
    node = platform.node()
    machine = platform.machine()
    processor = platform.processor()
    raw = f"{node}:{machine}:{processor}"
    return hashlib.sha256(raw.encode()).digest()


def derive_vault_key(passphrase: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    if salt is None:
        salt = _machine_fingerprint()[:16] + os.urandom(16)

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
        backend=default_backend(),
    )
    raw_key = kdf.derive(passphrase.encode("utf-8"))
    fernet_key = base64.urlsafe_b64encode(raw_key)
    return fernet_key, salt
