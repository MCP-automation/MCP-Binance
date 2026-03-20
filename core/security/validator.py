"""
Credential Validator - Tests API keys against Binance before use.
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class CredentialSource(Enum):
    ENV = "environment_variable"
    VAULT = "encrypted_vault"
    ENV_FILE = ".env_file"
    NONE = "none"


@dataclass
class ValidationResult:
    is_valid: bool
    source: CredentialSource
    error_message: Optional[str] = None
    balance: Optional[float] = None
    account_type: Optional[str] = None


class BinanceCredentialValidator:
    """Validates Binance API credentials against the exchange."""

    MIN_KEY_LENGTH = 16
    MAX_KEY_LENGTH = 64

    def __init__(self, testnet: bool = False):
        self.testnet = testnet

    def _get_from_env(self) -> tuple[Optional[str], Optional[str]]:
        """Get credentials from environment variables."""
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")
        if api_key or api_secret:
            logger.debug("Credentials found in environment variables")
            return api_key, api_secret
        return None, None

    def _validate_format(self, api_key: str, api_secret: str) -> Optional[str]:
        """Validate key format."""
        if not api_key or not api_secret:
            return "API key or secret is empty"

        if len(api_key) < self.MIN_KEY_LENGTH:
            return f"API key too short (min {self.MIN_KEY_LENGTH} chars)"

        if len(api_key) > self.MAX_KEY_LENGTH:
            return f"API key too long (max {self.MAX_KEY_LENGTH} chars)"

        if len(api_secret) < self.MIN_KEY_LENGTH:
            return f"API secret too short (min {self.MIN_KEY_LENGTH} chars)"

        # Check for common invalid patterns
        if api_key.startswith("YOUR_") or "placeholder" in api_key.lower():
            return "API key appears to be a placeholder"

        return None

    async def validate_credentials(
        self, api_key: str, api_secret: str, vault=None, vault_key_prefix: str = ""
    ) -> ValidationResult:
        """
        Validate credentials by testing against Binance API.

        Returns ValidationResult with:
        - is_valid: True if credentials work
        - source: Where credentials came from
        - error_message: Error details if invalid
        - balance: USDT balance if valid
        """
        # Try environment variables first
        env_key, env_secret = self._get_from_env()
        if env_key and env_secret:
            api_key = env_key
            api_secret = env_secret
            source = CredentialSource.ENV
        elif vault:
            # Try vault
            key_name = f"{vault_key_prefix}api_key" if vault_key_prefix else "binance_api_key"
            secret_name = (
                f"{vault_key_prefix}api_secret" if vault_key_prefix else "binance_api_secret"
            )

            api_key = vault.get(key_name) or api_key
            api_secret = vault.get(secret_name) or api_secret

            if api_key and api_secret:
                source = CredentialSource.VAULT
            else:
                source = CredentialSource.NONE
        else:
            source = CredentialSource.NONE

        # Check if we have credentials
        if not api_key or not api_secret:
            return ValidationResult(
                is_valid=False,
                source=source,
                error_message="No API credentials found in environment or vault",
            )

        # Validate format
        format_error = self._validate_format(api_key, api_secret)
        if format_error:
            return ValidationResult(
                is_valid=False,
                source=source,
                error_message=f"Invalid credential format: {format_error}",
            )

        # Test against Binance
        return await self._test_binance_connection(api_key, api_secret, source)

    async def _test_binance_connection(
        self, api_key: str, api_secret: str, source: CredentialSource
    ) -> ValidationResult:
        """Test connection to Binance using async ccxt."""
        exchange = None
        try:
            import ccxt.async_support as ccxt  # ← async version is required here
            import aiohttp

            # Create exchange instance
            if self.testnet:
                exchange = ccxt.binance(
                    {
                        "apiKey": api_key,
                        "secret": api_secret,
                        "enableRateLimit": True,
                        "options": {"defaultType": "future"},
                    }
                )
                exchange.set_sandbox_mode(True)
            else:
                exchange = ccxt.binanceusdm(
                    {
                        "apiKey": api_key,
                        "secret": api_secret,
                        "enableRateLimit": True,
                        "options": {"adjustForTimeDifference": True},
                    }
                )

            # Use ThreadedResolver to avoid aiodns issues on Windows
            resolver = aiohttp.ThreadedResolver()
            connector = aiohttp.TCPConnector(resolver=resolver)
            exchange.session = aiohttp.ClientSession(connector=connector)

            # Properly await the async balance call
            balance = await exchange.fetch_balance()

            usdt_balance = balance.get("USDT", {}).get("total", 0.0)

            logger.info(
                "Credential validation successful! Source: %s, USDT Balance: %s",
                source.value,
                usdt_balance,
            )

            return ValidationResult(
                is_valid=True,
                source=source,
                balance=usdt_balance,
                account_type="LIVE" if not self.testnet else "TESTNET",
            )

        except Exception as e:
            # Safely import sync ccxt for error-type checking
            try:
                import ccxt as ccxt_sync
                AuthError = ccxt_sync.AuthenticationError
                NetError = ccxt_sync.NetworkError
            except Exception:
                AuthError = None
                NetError = None

            error_msg = str(e)

            if AuthError and isinstance(e, AuthError):
                if "-2015" in error_msg or ("Invalid" in error_msg and "IP" in error_msg) or "permissions for action" in error_msg:
                    detail = (
                        "API key rejected by Binance (code -2015). Three possible causes:\n"
                        "  1. WRONG NETWORK: You may be using a Live API key against Testnet (or vice versa).\n"
                        "     Testnet keys must be generated at https://testnet.binance.vision/\n"
                        "  2. IP WHITELIST: Your API key has 'Restrict access to trusted IPs only' enabled.\n"
                        "     Either add your current IP to the whitelist on Binance, or set it to 'Unrestricted'.\n"
                        "  3. MISSING PERMISSIONS: The API key does not have the required permissions enabled\n"
                        "     (e.g. 'Enable Futures' must be checked for futures trading)."
                    )
                    logger.error(detail)
                    return ValidationResult(is_valid=False, source=source, error_message=detail)
                elif "-2008" in error_msg or "Invalid Api-Key" in error_msg:
                    return ValidationResult(
                        is_valid=False, source=source,
                        error_message="Invalid API Key - Check Binance API credentials",
                    )
                elif "-2014" in error_msg or "API-key" in error_msg:
                    return ValidationResult(
                        is_valid=False, source=source, error_message="API Key format error"
                    )
                elif "-1022" in error_msg or "signature" in error_msg:
                    return ValidationResult(
                        is_valid=False, source=source,
                        error_message="Invalid API Secret - Signature verification failed",
                    )
                else:
                    return ValidationResult(
                        is_valid=False, source=source,
                        error_message=f"Authentication failed: {error_msg[:100]}",
                    )
            elif NetError and isinstance(e, NetError):
                return ValidationResult(
                    is_valid=False, source=source,
                    error_message=f"Network error: {error_msg[:100]}",
                )
            else:
                return ValidationResult(
                    is_valid=False, source=source,
                    error_message=f"Validation error: {error_msg[:100]}",
                )
        finally:
            # Always close the async exchange session to avoid resource leaks
            if exchange is not None:
                try:
                    await exchange.close()
                except Exception:
                    pass


async def validate_and_get_credentials(
    testnet: bool = False, vault=None
) -> tuple[str, str, ValidationResult]:
    """
    Convenience function to validate and get credentials.

    Returns: (api_key, api_secret, validation_result)
    """
    validator = BinanceCredentialValidator(testnet=testnet)

    # Get credentials from env
    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")

    # If empty, try vault
    if not api_key and vault:
        api_key = vault.get("binance_live_api_key") or vault.get("BINANCE_TESTNET_API_KEY") or ""
        api_secret = (
            vault.get("binance_live_api_secret") or vault.get("BINANCE_TESTNET_API_SECRET") or ""
        )

    # Validate
    result = await validator.validate_credentials(api_key or "", api_secret or "", vault=vault)

    return api_key, api_secret, result

