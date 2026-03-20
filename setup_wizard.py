from __future__ import annotations
import asyncio
import getpass
import os
import sys
from pathlib import Path
from typing import Callable

from core.config import AppConfig, ConfigManager, TradingMode, MarketType
from core.security import SecretsVault


class WizardStep:
    def __init__(self, key: str, prompt: str, secret: bool = False,
                 validator: Callable[[str], str | None] | None = None,
                 default: str | None = None, optional: bool = False) -> None:
        self.key = key
        self.prompt = prompt
        self.secret = secret
        self.validator = validator
        self.default = default
        self.optional = optional

    def ask(self) -> str | None:
        prompt_text = self.prompt
        if self.default:
            prompt_text += f" [{self.default}]"
        if self.optional:
            prompt_text += " (optional, press Enter to skip)"
        prompt_text += ": "

        while True:
            if self.secret:
                value = getpass.getpass(prompt_text)
            else:
                value = input(prompt_text).strip()

            if not value:
                if self.default is not None:
                    return self.default
                if self.optional:
                    return None
                print("  ✗ This field is required.")
                continue

            if self.validator:
                error = self.validator(value)
                if error:
                    print(f"  ✗ {error}")
                    continue

            return value


def _validate_non_empty(value: str) -> str | None:
    if not value.strip():
        return "Value cannot be empty."
    return None


def _validate_positive_float(value: str) -> str | None:
    try:
        f = float(value)
        if f <= 0:
            return "Must be a positive number."
        return None
    except ValueError:
        return "Must be a valid number."


def _validate_passphrase(value: str) -> str | None:
    if len(value) < 8:
        return "Passphrase must be at least 8 characters long."
    return None


def _print_banner() -> None:
    print("\n" + "=" * 60)
    print("   BINANCE MCP TRADING SERVER — FIRST RUN SETUP WIZARD")
    print("=" * 60)
    print("\nThis wizard will configure your trading server securely.")
    print("All sensitive credentials are encrypted with a passphrase")
    print("derived from your machine fingerprint + your vault password.\n")


def _print_section(title: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


class SetupWizard:
    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._vault = SecretsVault(root_dir / "vault")
        self._config_manager = ConfigManager(root_dir / "config")

    def run(self) -> None:
        _print_banner()

        _print_section("VAULT SECURITY SETUP")
        print("Your vault password encrypts all API keys and secrets.")
        print("Choose a strong password — you will need it every time the server starts.\n")

        passphrase = self._collect_vault_passphrase()
        self._vault.initialize(passphrase)
        print("  ✓ Vault initialized and encrypted.\n")

        _print_section("BINANCE API CREDENTIALS")
        print("You need separate API keys for Spot/Futures (live) and Testnet.\n")
        self._collect_binance_keys()

        _print_section("TRADING CONFIGURATION")
        config_updates = self._collect_trading_config()

        _print_section("TELEGRAM NOTIFICATIONS (Optional)")
        self._collect_telegram_config()

        _print_section("DASHBOARD CONFIGURATION")
        self._collect_dashboard_config(config_updates)

        self._apply_config(config_updates)

        _print_section("SETUP COMPLETE")
        print("  ✓ All settings saved successfully.")
        print("  ✓ Run start.bat to launch the trading server.\n")
        print("=" * 60 + "\n")

    def _collect_vault_passphrase(self) -> str:
        while True:
            pw1 = getpass.getpass("  Enter vault passphrase: ")
            if len(pw1) < 8:
                print("  ✗ Passphrase must be at least 8 characters.")
                continue
            pw2 = getpass.getpass("  Confirm vault passphrase: ")
            if pw1 != pw2:
                print("  ✗ Passphrases do not match. Try again.")
                continue
            return pw1

    def _collect_binance_keys(self) -> None:
        steps = [
            WizardStep("BINANCE_LIVE_API_KEY", "  Live API Key", secret=True, validator=_validate_non_empty),
            WizardStep("BINANCE_LIVE_API_SECRET", "  Live API Secret", secret=True, validator=_validate_non_empty),
            WizardStep("BINANCE_FUTURES_API_KEY", "  Futures API Key (can be same as live)", secret=True, validator=_validate_non_empty),
            WizardStep("BINANCE_FUTURES_API_SECRET", "  Futures API Secret", secret=True, validator=_validate_non_empty),
            WizardStep("BINANCE_TESTNET_API_KEY", "  Testnet API Key", secret=True, optional=True),
            WizardStep("BINANCE_TESTNET_API_SECRET", "  Testnet API Secret", secret=True, optional=True),
        ]
        bulk: dict[str, str] = {}
        for step in steps:
            value = step.ask()
            if value:
                bulk[step.key] = value
                print(f"  ✓ {step.key} saved.")
        self._vault.set_bulk(bulk)

    def _collect_trading_config(self) -> dict:
        updates: dict = {}

        print("  Trading mode options: paper / live / both")
        mode_raw = input("  Trading mode [both]: ").strip().lower() or "both"
        mode_map = {"paper": TradingMode.PAPER, "live": TradingMode.LIVE, "both": TradingMode.BOTH}
        updates["trading_mode"] = mode_map.get(mode_raw, TradingMode.BOTH)

        balance_raw = input("  Paper trading initial balance in USDT [10000]: ").strip() or "10000"
        try:
            updates["paper_initial_balance_usdt"] = float(balance_raw)
        except ValueError:
            updates["paper_initial_balance_usdt"] = 10_000.0

        print("\n  Risk Management:")
        risk_updates: dict = {}

        max_loss_raw = input("  Max loss per trade % [1.0]: ").strip() or "1.0"
        try:
            risk_updates["max_loss_per_trade_pct"] = float(max_loss_raw)
        except ValueError:
            risk_updates["max_loss_per_trade_pct"] = 1.0

        dd_raw = input("  Daily drawdown kill-switch % [5.0]: ").strip() or "5.0"
        try:
            risk_updates["daily_drawdown_kill_pct"] = float(dd_raw)
        except ValueError:
            risk_updates["daily_drawdown_kill_pct"] = 5.0

        max_pos_raw = input("  Max open positions [10]: ").strip() or "10"
        try:
            risk_updates["max_open_positions"] = int(max_pos_raw)
        except ValueError:
            risk_updates["max_open_positions"] = 10

        sizing_raw = input("  Position sizing mode — kelly or fixed [fixed]: ").strip().lower() or "fixed"
        risk_updates["position_sizing_mode"] = sizing_raw if sizing_raw in ("kelly", "fixed") else "fixed"

        if risk_updates["position_sizing_mode"] == "fixed":
            pct_raw = input("  Fixed position size % of portfolio [1.0]: ").strip() or "1.0"
            try:
                risk_updates["fixed_position_pct"] = float(pct_raw)
            except ValueError:
                risk_updates["fixed_position_pct"] = 1.0

        updates["risk"] = risk_updates
        return updates

    def _collect_telegram_config(self) -> None:
        enable_raw = input("  Enable Telegram notifications? (y/n) [n]: ").strip().lower()
        if enable_raw != "y":
            return
        token = getpass.getpass("  Telegram bot token: ").strip()
        chat_id = input("  Telegram chat ID: ").strip()
        if token and chat_id:
            self._vault.set("TELEGRAM_BOT_TOKEN", token)
            self._vault.set("TELEGRAM_CHAT_ID", chat_id)
            print("  ✓ Telegram credentials saved.")
        self._config_manager.update_nested("telegram", enabled=True, chat_id=chat_id)

    def _collect_dashboard_config(self, config_updates: dict) -> None:
        port_raw = input("  Dashboard port [8765]: ").strip() or "8765"
        try:
            port = int(port_raw)
        except ValueError:
            port = 8765
        config_updates.setdefault("dashboard", {})
        if isinstance(config_updates.get("dashboard"), dict):
            config_updates["dashboard"]["port"] = port

    def _apply_config(self, updates: dict) -> None:
        config = self._config_manager.load()
        data = config.model_dump()

        risk_updates = updates.pop("risk", {})
        dashboard_updates = updates.pop("dashboard", {})

        for key, value in updates.items():
            if key in data:
                data[key] = value.value if hasattr(value, "value") else value

        if risk_updates:
            data["risk"].update(risk_updates)

        if dashboard_updates:
            data["dashboard"].update(dashboard_updates)

        from core.config.schema import AppConfig
        updated_config = AppConfig.model_validate(data)
        self._config_manager._config = updated_config
        self._config_manager.save()


def run_setup_wizard(root_dir: Path) -> None:
    wizard = SetupWizard(root_dir)
    wizard.run()
