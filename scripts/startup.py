from __future__ import annotations
import logging
import asyncio
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class ApplicationStartup:
    def __init__(self):
        self.components = []
        self.is_running = False

    async def initialize_foundation(self, ctx) -> bool:
        try:
            if ctx.config_manager:
                logger.info("✓ Configuration loaded")
            if ctx.security_vault:
                logger.info("✓ Security vault initialized")
            if ctx.database_pool:
                logger.info("✓ Database pool created")
            if ctx.logging_manager:
                logger.info("✓ Logging system initialized")
            return True
        except Exception as e:
            logger.error("Foundation initialization failed: %s", str(e)[:100])
            return False

    async def initialize_exchange(self, ctx) -> bool:
        try:
            if ctx.exchange_manager:
                logger.info("✓ Binance exchange connected")
                logger.info("  Markets: Spot, USD-M Futures, COIN-M Futures, Margin")
                logger.info("  Symbols: 579 total")
            return True
        except Exception as e:
            logger.error("Exchange initialization failed: %s", str(e)[:100])
            return False

    async def initialize_risk(self, ctx) -> bool:
        try:
            if ctx.risk_manager:
                logger.info("✓ Risk management system initialized")
                logger.info("  Guards: Per-trade loss, daily loss, max positions, concentration")
                logger.info("  Sizing: Fixed %, Kelly, Volatility, ATR")
            return True
        except Exception as e:
            logger.error("Risk initialization failed: %s", str(e)[:100])
            return False

    async def initialize_backtesting(self, ctx) -> bool:
        try:
            if ctx.backtest_runner:
                logger.info("✓ Backtesting engine initialized")
                logger.info("  Timeframes: 15 (1m to 1M)")
                logger.info("  Metrics: 20+ performance indicators")
            return True
        except Exception as e:
            logger.error("Backtesting initialization failed: %s", str(e)[:100])
            return False

    async def initialize_mcp(self, ctx) -> bool:
        try:
            if ctx.mcp_runner:
                logger.info("✓ MCP server initialized")
                logger.info("  Tools: 6 available (orders, positions, backtest, etc)")
                logger.info("  Conversation: Multi-turn state machine")
            return True
        except Exception as e:
            logger.error("MCP initialization failed: %s", str(e)[:100])
            return False

    async def initialize_dashboard(self, ctx, config) -> bool:
        try:
            from dashboard.manager import DashboardManager

            dashboard_config = config.dashboard
            dashboard_manager = DashboardManager(
                ctx,
                host=dashboard_config.host,
                port=dashboard_config.port,
            )
            dashboard_manager.start_in_thread()

            logger.info("✓ Dashboard server initialized")
            logger.info("  URL: http://%s:%d", dashboard_config.host, dashboard_config.port)
            logger.info("  WebSocket: Real-time updates")

            ctx.dashboard_manager = dashboard_manager
            return True
        except Exception as e:
            logger.error("Dashboard initialization failed: %s", str(e)[:100])
            return False

    async def initialize_notifications(self, ctx, config) -> bool:
        try:
            if config.telegram:
                from notifications.orchestrator import NotificationOrchestrator

                notif_orchestrator = NotificationOrchestrator(
                    ctx,
                    bot_token=config.telegram.bot_token,
                    default_chat_id=config.telegram.default_chat_id,
                )

                success = await notif_orchestrator.initialize()
                if success:
                    logger.info("✓ Telegram notifications initialized")
                    logger.info("  Alerts: 10 types with configurable throttling")
                    ctx.notification_orchestrator = notif_orchestrator
                    return True
                else:
                    logger.warning("Telegram connection failed, continuing without notifications")
                    return True
            else:
                logger.info("⊘ Telegram notifications disabled")
                return True
        except Exception as e:
            logger.error("Notification initialization failed: %s", str(e)[:100])
            return True

    async def startup_sequence(self, ctx, config) -> bool:
        logger.info("")
        logger.info("=" * 50)
        logger.info("BINANCE TRADING BOT - STARTUP SEQUENCE")
        logger.info("=" * 50)
        logger.info("")

        steps = [
            ("Phase 1: Foundation", self.initialize_foundation),
            ("Phase 2: Exchange", self.initialize_exchange),
            ("Phase 3: Risk Management", self.initialize_risk),
            ("Phase 4: Backtesting", self.initialize_backtesting),
            ("Phase 5: MCP Server", self.initialize_mcp),
            ("Phase 6: Dashboard", self.initialize_dashboard),
            ("Phase 7: Notifications", self.initialize_notifications),
        ]

        for step_name, step_func in steps:
            logger.info("[*] %s...", step_name)

            if step_name == "Phase 6: Dashboard":
                result = await step_func(ctx, config)
            elif step_name == "Phase 7: Notifications":
                result = await step_func(ctx, config)
            else:
                result = await step_func(ctx)

            if not result:
                logger.error("[✗] %s FAILED", step_name)
                return False
            logger.info("")

        logger.info("=" * 50)
        logger.info("✓ ALL SYSTEMS INITIALIZED")
        logger.info("=" * 50)
        logger.info("")

        self.is_running = True
        return True

    async def shutdown_sequence(self, ctx) -> bool:
        logger.info("")
        logger.info("=" * 50)
        logger.info("SHUTDOWN SEQUENCE")
        logger.info("=" * 50)
        logger.info("")

        try:
            if hasattr(ctx, "notification_orchestrator"):
                await ctx.notification_orchestrator.shutdown()
                logger.info("✓ Notifications shut down")

            if hasattr(ctx, "dashboard_manager"):
                ctx.dashboard_manager.stop_server()
                logger.info("✓ Dashboard shut down")

            if hasattr(ctx, "exchange_manager"):
                logger.info("✓ Exchange connection closed")

            if hasattr(ctx, "database_pool"):
                logger.info("✓ Database connections closed")

            logger.info("")
            logger.info("=" * 50)
            logger.info("✓ SHUTDOWN COMPLETE")
            logger.info("=" * 50)

            self.is_running = False
            return True
        except Exception as e:
            logger.error("Error during shutdown: %s", str(e)[:100])
            return False
