import json
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from .keyderivation import derive_vault_key


class VaultError(Exception):
    pass


class VaultNotInitializedError(VaultError):
    pass


class VaultDecryptionError(VaultError):
    pass


class SecretsVault:
    _SALT_FILE = "vault.salt"
    _DATA_FILE = "vault.enc"

    def __init__(self, vault_dir: Path) -> None:
        self._vault_dir = vault_dir
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        self._salt_path = vault_dir / self._SALT_FILE
        self._data_path = vault_dir / self._DATA_FILE
        self._fernet: Fernet | None = None

    @property
    def is_initialized(self) -> bool:
        return self._salt_path.exists() and self._data_path.exists()

    def initialize(self, passphrase: str) -> None:
        fernet_key, salt = derive_vault_key(passphrase)
        self._salt_path.write_bytes(salt)
        self._fernet = Fernet(fernet_key)
        self._persist({})

    def unlock(self, passphrase: str) -> None:
        if not self.is_initialized:
            raise VaultNotInitializedError("Vault has not been initialized yet.")
        salt = self._salt_path.read_bytes()
        fernet_key, _ = derive_vault_key(passphrase, salt)
        self._fernet = Fernet(fernet_key)
        self._load()

    def _assert_unlocked(self) -> None:
        if self._fernet is None:
            raise VaultError("Vault is locked. Call unlock() first.")

    def _load(self) -> dict:
        self._assert_unlocked()
        try:
            encrypted = self._data_path.read_bytes()
            decrypted = self._fernet.decrypt(encrypted)
            return json.loads(decrypted.decode("utf-8"))
        except InvalidToken:
            raise VaultDecryptionError("Invalid passphrase or corrupted vault.")

    def _persist(self, data: dict) -> None:
        self._assert_unlocked()
        raw = json.dumps(data, indent=2).encode("utf-8")
        encrypted = self._fernet.encrypt(raw)
        tmp_path = self._data_path.with_suffix(".tmp")
        tmp_path.write_bytes(encrypted)
        tmp_path.replace(self._data_path)

    def set(self, key: str, value: str) -> None:
        data = self._load()
        data[key] = value
        self._persist(data)

    def get(self, key: str) -> str | None:
        data = self._load()
        return data.get(key)

    def get_required(self, key: str) -> str:
        value = self.get(key)
        if value is None:
            raise VaultError(f"Required secret '{key}' not found in vault.")
        return value

    def delete(self, key: str) -> None:
        data = self._load()
        data.pop(key, None)
        self._persist(data)

    def list_keys(self) -> list[str]:
        return list(self._load().keys())

    def set_bulk(self, entries: dict[str, str]) -> None:
        data = self._load()
        data.update(entries)
        self._persist(data)

    def lock(self) -> None:
        self._fernet = None
