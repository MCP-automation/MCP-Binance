from __future__ import annotations
import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any, Optional
from decimal import Decimal
from datetime import datetime, timedelta
from urllib.parse import urlencode

import aiohttp
import httpx
from aiohttp import ClientSession, TCPConnector

logger = logging.getLogger(__name__)


class RateLimitTracker:
    def __init__(self):
        self.weight_used = 0
        self.weight_limit = 1200
        self.weight_reset_time = 0
        self.order_count = 0
        self.order_count_limit = 100000
        self.order_count_reset_time = 0

    def update_from_headers(self, headers: dict) -> None:
        if "x-mbx-used-weight-1m" in headers:
            self.weight_used = int(headers["x-mbx-used-weight-1m"])
        if "x-mbx-order-count-1m" in headers:
            self.order_count = int(headers["x-mbx-order-count-1m"])

    def is_rate_limited(self) -> bool:
        return (
            self.weight_used >= self.weight_limit * 0.9
            or self.order_count >= self.order_count_limit * 0.9
        )

    def time_until_reset(self) -> float:
        if self.weight_reset_time > 0:
            return max(0, self.weight_reset_time - time.time())
        return 0


class BinanceAPIError(Exception):
    pass


class RateLimitError(BinanceAPIError):
    pass


class ConnectionError(BinanceAPIError):
    pass


class ValidationError(BinanceAPIError):
    pass


class UnifiedHTTPClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.session: Optional[ClientSession] = None
        self.rate_limiter = RateLimitTracker()
        self._connector: Optional[TCPConnector] = None

    async def __aenter__(self) -> UnifiedHTTPClient:
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def initialize(self) -> None:
        try:
            resolver = aiohttp.AsyncResolver(nameservers=["8.8.8.8", "8.8.4.4"])
        except Exception:
            resolver = None  # aiodns not available; fall back to default resolver
        self._connector = TCPConnector(
            resolver=resolver,
            limit=100,
            limit_per_host=10,
            ttl_dns_cache=300,
            ssl=True,
            keepalive_timeout=30,
        )
        self.session = ClientSession(
            connector=self._connector,
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        )
        logger.debug(
            "UnifiedHTTPClient initialized for %s (testnet=%s)",
            self.base_url,
            self.testnet,
        )

    async def close(self) -> None:
        if self.session:
            await self.session.close()
        if self._connector:
            await self._connector.close()
        logger.debug("UnifiedHTTPClient closed")

    def _generate_signature(self, params: dict) -> str:
        query_string = urlencode(params)
        return hmac.new(
            self.api_secret.encode(),
            query_string.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _build_signed_request(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = self._generate_signature(params)
        return params

    def _build_headers(self, signed: bool = False) -> dict:
        headers = {"Accept": "application/json"}
        # Only attach the API key for authenticated (signed) requests.
        # Sending an invalid or malformed key on public endpoints (e.g. /klines,
        # /ticker) causes Binance to reject with -2014 even though no auth
        # is required for those calls.
        if signed and self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        return headers

    async def _handle_rate_limit(self) -> None:
        wait_time = self.rate_limiter.time_until_reset()
        if wait_time > 0:
            logger.warning("Rate limit approaching, waiting %.1f seconds", wait_time)
            await asyncio.sleep(wait_time + 1)

    async def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        signed: bool = False,
        data: Optional[dict] = None,
    ) -> dict:
        if params is None:
            params = {}
        if data is None:
            data = {}

        url = f"{self.base_url}{endpoint}"
        headers = self._build_headers(signed=signed)

        if signed:
            if params:
                params = self._build_signed_request(params)
            if data:
                data = self._build_signed_request(data)

        await self._handle_rate_limit()

        last_error = None
        for attempt in range(self.max_retries):
            try:
                async with self.session.request(
                    method,
                    url,
                    params=params if method.upper() == "GET" else None,
                    data=data if data and method.upper() in ("POST", "PUT") else None,
                    json=json_data if json_data and method.upper() in ("POST", "PUT") else None,
                    headers=headers,
                ) as response:
                    self.rate_limiter.update_from_headers(response.headers)

                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        logger.warning(
                            "Rate limit hit, waiting %d seconds",
                            retry_after,
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    if response.status == 418:
                        logger.error("IP ban detected, immediate backoff required")
                        raise RateLimitError("IP temporarily banned from Binance")

                    if response.status >= 400:
                        error_text = await response.text()
                        logger.error(
                            "API error %d: %s",
                            response.status,
                            error_text[:200],
                        )

                        if response.status == 400:
                            raise ValidationError(f"Binance API validation error: {error_text}")
                        elif response.status in (401, 403):
                            raise BinanceAPIError(f"Authentication failed: {error_text}")
                        elif response.status >= 500:
                            last_error = ConnectionError(
                                f"Binance server error {response.status}: {error_text}"
                            )
                            if attempt < self.max_retries - 1:
                                wait_time = 2**attempt * self.backoff_factor
                                logger.warning(
                                    "Server error, retrying in %.1f seconds",
                                    wait_time,
                                )
                                await asyncio.sleep(wait_time)
                                continue
                            raise last_error
                        else:
                            raise BinanceAPIError(f"API error {response.status}: {error_text}")

                    result = await response.json()
                    return result

            except asyncio.TimeoutError as e:
                last_error = ConnectionError(f"Request timeout: {str(e)}")
                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt * self.backoff_factor
                    logger.warning("Timeout, retrying in %.1f seconds", wait_time)
                    await asyncio.sleep(wait_time)
                    continue
                raise last_error

            except aiohttp.ClientError as e:
                last_error = ConnectionError(f"HTTP client error: {str(e)}")
                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt * self.backoff_factor
                    logger.warning("Connection error, retrying in %.1f seconds", wait_time)
                    await asyncio.sleep(wait_time)
                    continue
                raise last_error

        if last_error:
            raise last_error
        raise ConnectionError("Max retries exceeded")

    async def get(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        signed: bool = False,
    ) -> dict:
        return await self.request("GET", endpoint, params=params, signed=signed)

    async def post(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        data: Optional[dict] = None,
        signed: bool = False,
    ) -> dict:
        return await self.request(
            "POST",
            endpoint,
            params=params,
            json_data=json_data,
            data=data,
            signed=signed,
        )

    async def delete(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        signed: bool = False,
    ) -> dict:
        return await self.request("DELETE", endpoint, params=params, signed=signed)

    async def put(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        data: Optional[dict] = None,
        signed: bool = False,
    ) -> dict:
        return await self.request(
            "PUT",
            endpoint,
            params=params,
            json_data=json_data,
            data=data,
            signed=signed,
        )
