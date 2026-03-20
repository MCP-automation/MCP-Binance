from __future__ import annotations
import asyncio
import logging
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file FIRST
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env", override=True)

sys.path.insert(0, str(ROOT_DIR))

from core.security import SecretsVault
from core.logging import LoggingManager
from core.config import LoggingConfig


async def _start_mcp_server(vault: SecretsVault, max_retries: int = 3) -> None:
    from app_context import ApplicationContext
    from dashboard.manager import DashboardManager
    from mcp_app.server.runner import MCPServerRunner
    from aiohttp import ClientConnectorError

    logger = logging.getLogger(__name__)
    ctx = None
    dashboard = None
    retry_count = 0

    while retry_count < max_retries:
        try:
            logger.info(
                "MCP Trading Server starting... (attempt %d/%d)", retry_count + 1, max_retries
            )

            ctx = await ApplicationContext.create(ROOT_DIR, vault=vault)
            logger.info("Application context initialized successfully.")

            dashboard = DashboardManager(
                ctx, host=ctx.config.dashboard.host, port=ctx.config.dashboard.port
            )

            if ctx.config.dashboard.enabled:
                dashboard.start_in_thread()
                logger.info("Dashboard started on port %d", ctx.config.dashboard.port)

            logger.info("Initializing MCP Server Runner...")
            runner = MCPServerRunner(ctx)

            logger.info("Starting MCP stdio server loop...")
            await runner.run()

            break

        except ClientConnectorError as e:
            retry_count += 1
            logger.warning(
                "Connection error (attempt %d/%d): %s", retry_count, max_retries, str(e)[:100]
            )
            if ctx:
                try:
                    await ctx.shutdown()
                except:
                    pass
            if retry_count < max_retries:
                wait_time = 2**retry_count
                logger.info("Retrying in %d seconds...", wait_time)
                await asyncio.sleep(wait_time)
            else:
                logger.error("Max retries reached. Could not connect to Binance.")
                print(
                    f"ERROR: Could not connect to Binance after {max_retries} attempts.",
                    file=sys.stderr,
                )

        except (KeyboardInterrupt, BrokenPipeError, ConnectionResetError) as e:
            logger.info("Connection closed or interrupted: %s", str(e)[:100])
            break

        except Exception as e:
            logger.error("Server error: %s", str(e)[:200])
            print(f"ERROR: {str(e)[:500]}", file=sys.stderr)
            break

        finally:
            if dashboard and ctx and ctx.config.dashboard.enabled:
                try:
                    dashboard.stop_server()
                except:
                    pass
            if ctx:
                try:
                    await ctx.shutdown()
                except:
                    pass


def _unlock_vault(root_dir: Path) -> SecretsVault:
    vault = SecretsVault(root_dir / "vault")
    logger = logging.getLogger(__name__)

    env_passphrase = os.environ.get("BINANCE_MCP_PASSPHRASE")

    if env_passphrase:
        try:
            vault.unlock(env_passphrase)
            logger.info("Vault unlocked via environment variable.")
            return vault
        except Exception as e:
            logger.warning("Could not unlock vault (%s) — reinitializing vault.", e)
            try:
                vault.initialize(env_passphrase)
                logger.info("Vault reinitialized successfully.")
                return vault
            except Exception as reinit_err:
                logger.error("Vault reinitialization failed: %s", reinit_err)
                sys.exit(1)
    else:
        logger.error("No BINANCE_MCP_PASSPHRASE found. Headless unlock failed.")
        sys.exit(1)


def main() -> None:
    import os
    from dotenv import load_dotenv

    # Load environment variables from .env file FIRST
    ROOT_DIR = Path(__file__).parent
    load_dotenv(ROOT_DIR / ".env", override=True)

    LoggingManager.initialize(LoggingConfig(log_dir=ROOT_DIR / "logs"))
    logger = logging.getLogger(__name__)

    # Pre-flight check: Verify credentials exist
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")

    print("=" * 60, file=sys.stderr)
    print("Binance Trading MCP Server v1.0", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    if not api_key or not api_secret:
        print("\n❌ ERROR: No API credentials found!", file=sys.stderr)
        print("\nPlease set in .env file:", file=sys.stderr)
        print("  BINANCE_API_KEY=your_api_key", file=sys.stderr)
        print("  BINANCE_API_SECRET=your_api_secret", file=sys.stderr)
        print("\nOr set as environment variables.", file=sys.stderr)
        sys.exit(1)

    print(f"✅ API Key found: {api_key[:8]}...{api_key[-4:]}", file=sys.stderr)

    vault = SecretsVault(ROOT_DIR / "vault")

    if not vault.is_initialized:
        passphrase = os.environ.get("BINANCE_MCP_PASSPHRASE")
        if passphrase:
            logger.info("Vault not initialized — auto-initializing from environment variables.")
            vault.initialize(passphrase)
            api_key = os.environ.get("BINANCE_API_KEY", "")
            api_secret = os.environ.get("BINANCE_API_SECRET", "")
            if api_key and api_secret:
                vault.set("BINANCE_LIVE_API_KEY", api_key)
                vault.set("BINANCE_LIVE_API_SECRET", api_secret)
                logger.info("API credentials stored in vault from environment variables.")
        else:
            print("\n[!] Setup required. Please run setup wizard first.\n", file=sys.stderr)
            from setup_wizard import run_setup_wizard

            run_setup_wizard(ROOT_DIR)
            return

    else:
        # Vault exists — sync fresh keys from .env into vault
        passphrase = os.environ.get("BINANCE_MCP_PASSPHRASE")
        if passphrase:
            try:
                vault.unlock(passphrase)
                vault.set("BINANCE_LIVE_API_KEY", api_key)
                vault.set("BINANCE_LIVE_API_SECRET", api_secret)
                logger.info("Vault keys synced from .env.")
            except Exception as e:
                logger.warning("Could not sync vault keys: %s — reinitializing vault with current passphrase.", e)
                try:
                    vault.initialize(passphrase)
                    vault.set("BINANCE_LIVE_API_KEY", api_key)
                    vault.set("BINANCE_LIVE_API_SECRET", api_secret)
                    logger.info("Vault reinitialized with fresh credentials from .env.")
                except Exception as reinit_err:
                    logger.error("Vault reinitialization failed: %s", reinit_err)

    unlocked_vault = _unlock_vault(ROOT_DIR)

    try:
        asyncio.run(_start_mcp_server(unlocked_vault))
    except KeyboardInterrupt:
        print("\nServer stopped by user.", file=sys.stderr)
    except Exception as exc:
        print(f"FATAL: Server crashed: {exc}", file=sys.stderr)
        logger.critical("Server crashed: %s", exc, exc_info=True)
        sys.exit(1)

    print("\nServer shutdown complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
