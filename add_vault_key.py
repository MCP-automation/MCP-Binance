"""
Utility to manually add or update API keys in the encrypted vault.
Run: python add_vault_key.py
"""
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from core.security import SecretsVault
from core.security.vault import VaultDecryptionError, VaultNotInitializedError

REQUIRED_KEYS = [
    ("BINANCE_LIVE_API_KEY",       "Binance Live API Key    (used by ExchangeManager for all live market types)"),
    ("BINANCE_LIVE_API_SECRET",    "Binance Live API Secret (used by ExchangeManager for all live market types)"),
    ("BINANCE_FUTURES_API_KEY",    "Binance Futures API Key (used by ccxt for futures order execution; falls back to LIVE key if blank)"),
    ("BINANCE_FUTURES_API_SECRET", "Binance Futures API Secret"),
]
OPTIONAL_KEYS = [
    ("BINANCE_TESTNET_API_KEY",    "Binance Testnet API Key    (used when testnet_enabled=true in config)"),
    ("BINANCE_TESTNET_API_SECRET", "Binance Testnet API Secret"),
]


def main() -> None:
    vault = SecretsVault(ROOT / "vault")

    if not vault.is_initialized:
        print("ERROR: Vault has not been initialized yet.")
        print("Run setup_wizard.py first to create and initialize the vault.")
        sys.exit(1)

    print("\n=== Binance MCP — Vault Key Manager ===\n")
    print("Enter your vault passphrase to unlock:")
    passphrase = getpass.getpass("  Vault passphrase: ")

    try:
        vault.unlock(passphrase)
    except VaultDecryptionError:
        print("ERROR: Wrong passphrase or corrupted vault.")
        sys.exit(1)

    existing = vault.list_keys()
    print(f"\nVault unlocked. Keys currently stored: {existing or ['(none)']}\n")

    print("─" * 60)
    print("REQUIRED KEYS (leave blank to keep existing value):")
    print("─" * 60)
    updates: dict[str, str] = {}

    for key, description in REQUIRED_KEYS:
        current = "SET" if key in existing else "NOT SET"
        print(f"\n  {key}  [{current}]")
        print(f"  {description}")
        value = getpass.getpass(f"  Enter value (blank = keep current): ").strip()
        if value:
            updates[key] = value
            print(f"  -> Will update {key}")
        else:
            print(f"  -> Keeping current value")

    print("\n" + "─" * 60)
    print("OPTIONAL KEYS (leave blank to skip):")
    print("─" * 60)
    for key, description in OPTIONAL_KEYS:
        current = "SET" if key in existing else "NOT SET"
        print(f"\n  {key}  [{current}]")
        print(f"  {description}")
        value = getpass.getpass(f"  Enter value (blank = skip): ").strip()
        if value:
            updates[key] = value
            print(f"  -> Will update {key}")

    if not updates:
        print("\nNo changes made.")
        return

    vault.set_bulk(updates)
    print(f"\n  Saved {len(updates)} key(s) to vault: {list(updates.keys())}")
    print("\nDone. Keys stored securely in the encrypted vault.")
    print("You do NOT need to edit any .py or .env files — the app reads from the vault.\n")


if __name__ == "__main__":
    main()
