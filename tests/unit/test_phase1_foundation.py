from __future__ import annotations
import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from core.security import SecretsVault
from core.security.vault import VaultDecryptionError, VaultNotInitializedError
from core.config import AppConfig, ConfigManager, TradingMode
from core.database import DatabaseConnectionPool, UnitOfWork
from core.database.schema import SCHEMA_VERSION


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestSecretsVault:
    def test_uninitialized_raises(self, tmp_dir):
        vault = SecretsVault(tmp_dir / "vault")
        assert not vault.is_initialized
        with pytest.raises(VaultNotInitializedError):
            vault.unlock("anypass")

    def test_initialize_and_unlock(self, tmp_dir):
        vault = SecretsVault(tmp_dir / "vault")
        vault.initialize("strongpass123")
        assert vault.is_initialized
        vault.lock()
        vault.unlock("strongpass123")
        assert vault.list_keys() == []

    def test_wrong_passphrase_raises(self, tmp_dir):
        vault = SecretsVault(tmp_dir / "vault")
        vault.initialize("correctpass")
        vault.lock()
        with pytest.raises(VaultDecryptionError):
            vault.unlock("wrongpass")

    def test_set_and_get(self, tmp_dir):
        vault = SecretsVault(tmp_dir / "vault")
        vault.initialize("pass1234")
        vault.set("API_KEY", "my_secret_key")
        assert vault.get("API_KEY") == "my_secret_key"

    def test_missing_key_returns_none(self, tmp_dir):
        vault = SecretsVault(tmp_dir / "vault")
        vault.initialize("pass1234")
        assert vault.get("NONEXISTENT") is None

    def test_delete_key(self, tmp_dir):
        vault = SecretsVault(tmp_dir / "vault")
        vault.initialize("pass1234")
        vault.set("KEY1", "value1")
        vault.delete("KEY1")
        assert vault.get("KEY1") is None

    def test_bulk_set(self, tmp_dir):
        vault = SecretsVault(tmp_dir / "vault")
        vault.initialize("pass1234")
        vault.set_bulk({"A": "1", "B": "2", "C": "3"})
        assert vault.list_keys() == ["A", "B", "C"]

    def test_persistence_across_unlock(self, tmp_dir):
        vault_dir = tmp_dir / "vault"
        v1 = SecretsVault(vault_dir)
        v1.initialize("pass1234")
        v1.set("PERSIST_KEY", "persist_value")

        v2 = SecretsVault(vault_dir)
        v2.unlock("pass1234")
        assert v2.get("PERSIST_KEY") == "persist_value"


class TestConfigManager:
    def test_load_creates_defaults(self, tmp_dir):
        mgr = ConfigManager(tmp_dir / "config")
        config = mgr.load()
        assert isinstance(config, AppConfig)
        assert config.trading_mode == TradingMode.BOTH

    def test_save_and_reload(self, tmp_dir):
        mgr = ConfigManager(tmp_dir / "config")
        mgr.load()
        mgr.update(paper_initial_balance_usdt=25_000.0)
        mgr2 = ConfigManager(tmp_dir / "config")
        config = mgr2.load()
        assert config.paper_initial_balance_usdt == 25_000.0

    def test_invalid_key_raises(self, tmp_dir):
        mgr = ConfigManager(tmp_dir / "config")
        mgr.load()
        with pytest.raises(Exception):
            mgr.update(nonexistent_key="value")


class TestDatabase:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_pool_initialize(self, tmp_dir):
        from core.config import DatabaseConfig
        cfg = DatabaseConfig(path=tmp_dir / "test.db")
        pool = DatabaseConnectionPool(cfg)
        self._run(pool.initialize())
        result = self._run(pool.fetch_one("SELECT version FROM schema_migrations LIMIT 1"))
        assert result["version"] == SCHEMA_VERSION
        self._run(pool.close())

    def test_session_repository(self, tmp_dir):
        from core.config import DatabaseConfig
        cfg = DatabaseConfig(path=tmp_dir / "test.db")
        pool = DatabaseConnectionPool(cfg)
        self._run(pool.initialize())
        uow = UnitOfWork(pool)
        session = self._run(uow.sessions.create("both", "1.0.0"))
        assert session["id"] is not None
        assert session["trading_mode"] == "both"
        fetched = self._run(uow.sessions.get_by_id(session["id"]))
        assert fetched["id"] == session["id"]
        self._run(pool.close())

    def test_strategy_repository(self, tmp_dir):
        from core.config import DatabaseConfig
        cfg = DatabaseConfig(path=tmp_dir / "test.db")
        pool = DatabaseConnectionPool(cfg)
        self._run(pool.initialize())
        uow = UnitOfWork(pool)
        strategy = self._run(uow.strategies.create({
            "name": "EMA Crossover",
            "timeframe": "1h",
            "market_type": "usd_m_futures",
            "description": "Test strategy",
        }))
        assert strategy["name"] == "EMA Crossover"
        self._run(uow.strategies.set_active(strategy["id"]))
        active = self._run(uow.strategies.get_active())
        assert active["id"] == strategy["id"]
        self._run(pool.close())

    def test_order_repository(self, tmp_dir):
        from core.config import DatabaseConfig
        cfg = DatabaseConfig(path=tmp_dir / "test.db")
        pool = DatabaseConnectionPool(cfg)
        self._run(pool.initialize())
        uow = UnitOfWork(pool)
        order = self._run(uow.orders.create({
            "symbol": "BTCUSDT",
            "market_type": "usd_m_futures",
            "side": "BUY",
            "order_type": "MARKET",
            "quantity": 0.01,
            "is_paper": True,
        }))
        assert order["symbol"] == "BTCUSDT"
        assert order["status"] == "pending"
        self._run(uow.orders.update_status(order["id"], "filled", avg_fill_price=65000.0, filled_quantity=0.01))
        updated = self._run(uow.orders.get_by_id(order["id"]))
        assert updated["status"] == "filled"
        self._run(pool.close())
