from __future__ import annotations
import logging
from decimal import Decimal
from pathlib import Path

from core.config import AppConfig, ConfigManager
from core.database import DatabaseConnectionPool, UnitOfWork
from core.logging import LoggingManager
from core.security import SecretsVault

logger = logging.getLogger(__name__)


class ApplicationContext:
    _instance: "ApplicationContext | None" = None

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._config_manager: ConfigManager | None = None
        self._db_pool: DatabaseConnectionPool | None = None
        self._uow: UnitOfWork | None = None
        self._vault: SecretsVault | None = None
        self._exchange_manager = None
        self._risk_manager = None
        self._backtest_runner = None
        self._ready = False

    @classmethod
    def get(cls) -> "ApplicationContext":
        if cls._instance is None:
            raise RuntimeError("ApplicationContext not initialized.")
        return cls._instance

    @classmethod
    async def create(
        cls, root_dir: Path, vault: SecretsVault | None = None
    ) -> "ApplicationContext":
        instance = cls(root_dir)
        instance._vault = vault
        await instance._bootstrap()
        cls._instance = instance
        return instance

    async def _bootstrap(self) -> None:
        self._config_manager = ConfigManager(self._root_dir / "config")
        config = self._config_manager.load()

        LoggingManager.initialize(config.logging)
        logger.info("Logging initialized at level %s.", config.logging.level.value)

        if self._vault is None:
            self._vault = SecretsVault(self._root_dir / "vault")

        self._db_pool = DatabaseConnectionPool(config.database)
        await self._db_pool.initialize()
        self._uow = UnitOfWork(self._db_pool)

        await self._init_exchange(config)
        self._init_risk(config)
        self._init_backtest()

        self._ready = True
        logger.info("ApplicationContext fully bootstrapped.")

    async def _init_exchange(self, config: AppConfig) -> None:
        import os
        from exchange.manager import UnifiedExchangeManager
        from core.security.validator import validate_and_get_credentials

        use_testnet = config.binance_api.testnet_enabled

        logger.info("Loading Binance credentials...")

        # Get credentials from environment or vault
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")

        # Fallback to vault if not in env
        if not api_key and self._vault:
            api_key = self._vault.get("binance_live_api_key") or self._vault.get(
                "BINANCE_TESTNET_API_KEY"
            )
            api_secret = self._vault.get("binance_live_api_secret") or self._vault.get(
                "BINANCE_TESTNET_API_SECRET"
            )

        # Validate credentials BEFORE using them
        if api_key and api_secret:
            logger.info("Validating Binance credentials...")
            _, _, result = await validate_and_get_credentials(
                testnet=use_testnet, vault=self._vault
            )

            if not result.is_valid:
                err = result.error_message or ""
                # ANY validation failure → degrade to public data mode instead of crashing.
                # This covers: IP whitelist (-2015), wrong network, missing permissions,
                # placeholder keys, format errors, network timeouts, etc.
                logger.warning(
                    "⚠️  Credential validation FAILED — starting in PUBLIC DATA MODE.\n"
                    "    Reason : %s\n"
                    "    Effect : Trading tools are disabled. Market data tools work normally.\n"
                    "    Fix    : Check your API key on Binance → API Management:\n"
                    "             · IP restriction must be set to 'Unrestricted' (or whitelist your IP)\n"
                    "             · 'Enable Futures' permission must be checked\n"
                    "             · Key must not be expired or revoked\n"
                    "             · Use Live keys for mainnet, Testnet keys for testnet",
                    err,
                )
                api_key = ""
                api_secret = ""
            else:
                logger.info("✅ Credential validation SUCCESS!")
                logger.info("   Source: %s", result.source.value)
                logger.info("   Account Type: %s", result.account_type)
                logger.info("   USDT Balance: %s", result.balance)
        else:
            logger.warning("⚠️ No API credentials found. Running in public data mode only.")
            logger.warning("   Set BINANCE_API_KEY and BINANCE_API_SECRET in .env file")

        self._exchange_manager = UnifiedExchangeManager(
            api_key=api_key or "",
            api_secret=api_secret or "",
            testnet=use_testnet,
        )
        await self._exchange_manager.initialize()
        logger.info("ExchangeManager initialized (testnet=%s).", use_testnet)

    def _init_risk(self, config: AppConfig) -> None:
        from risk.manager import RiskManager

        risk_cfg = config.risk
        initial_equity = Decimal(str(config.paper_initial_balance_usdt))

        self._risk_manager = RiskManager(
            uow=self._uow,
            initial_account_equity=initial_equity,
            per_trade_loss_pct=Decimal(str(risk_cfg.max_loss_per_trade_pct)),
            daily_loss_limit_pct=Decimal(str(risk_cfg.daily_drawdown_kill_pct)),
            max_open_positions=risk_cfg.max_open_positions,
            portfolio_risk_limit_pct=Decimal(str(risk_cfg.max_open_positions)),
            kelly_fraction=Decimal(str(risk_cfg.kelly_fraction)),
        )
        logger.info("RiskManager initialized (equity=%.2f).", config.paper_initial_balance_usdt)

    def _init_backtest(self) -> None:
        from backtesting.orchestrator import BacktestRunner

        self._backtest_runner = BacktestRunner(
            exchange_manager=self._exchange_manager,
            uow=self._uow,
        )
        logger.info("BacktestRunner initialized.")

    @property
    def config(self) -> AppConfig:
        return self._config_manager.get()

    @property
    def config_manager(self) -> ConfigManager:
        return self._config_manager

    @property
    def db(self) -> UnitOfWork:
        if self._uow is None:
            raise RuntimeError("Database not initialized.")
        return self._uow

    @property
    def vault(self) -> SecretsVault:
        if self._vault is None:
            raise RuntimeError("Vault not initialized.")
        return self._vault

    @property
    def exchange_manager(self):
        if self._exchange_manager is None:
            raise RuntimeError("ExchangeManager not initialized.")
        return self._exchange_manager

    @property
    def risk_manager(self):
        if self._risk_manager is None:
            raise RuntimeError("RiskManager not initialized.")
        return self._risk_manager

    @property
    def backtest_runner(self):
        if self._backtest_runner is None:
            raise RuntimeError("BacktestRunner not initialized.")
        return self._backtest_runner

    @property
    def is_ready(self) -> bool:
        return self._ready

    async def shutdown(self) -> None:
        if self._risk_manager is not None:
            try:
                await self._risk_manager.stop_monitoring()
            except Exception as exc:
                logger.warning("RiskManager stop_monitoring error: %s", exc)
        if self._exchange_manager is not None:
            try:
                await self._exchange_manager.shutdown()
            except Exception as exc:
                logger.warning("ExchangeManager shutdown error: %s", exc)
        if self._db_pool is not None:
            await self._db_pool.close()
        self._ready = False
        logger.info("ApplicationContext shut down cleanly.")
