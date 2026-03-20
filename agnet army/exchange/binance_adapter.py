import hmac
import hashlib
import time
import threading
import requests
from typing import Dict, Any, List, Optional
from urllib.parse import urlencode
from datetime import datetime
from collections import deque
import logging

from exchange.exchange_adapter import (
    ExchangeAdapter,
    ExchangeError,
    RateLimitError,
    InsufficientBalanceError,
    TickerPrice,
    Position,
    AccountBalance,
    OrderResponse,
)


logger = logging.getLogger(__name__)


class BinanceAdapter(ExchangeAdapter):
    BASE_URL = "https://fapi.binance.com"
    WEBSOCKET_URL = "wss://fstream.binance.com/ws"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
        rate_limit_calls: int = 120,
        rate_limit_period: float = 60.0,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet

        if testnet:
            self.BASE_URL = "https://testnet.binancefuture.com"
            self.WEBSOCKET_URL = "wss://stream.testnet.binance.vision/ws"

        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json", "X-MBX-APIKEY": api_key})

        self._rate_limit_calls = rate_limit_calls
        self._rate_limit_period = rate_limit_period
        self._request_times: deque = deque(maxlen=rate_limit_calls)
        self._lock = threading.Lock()

        self._ticker_cache: Dict[str, TickerPrice] = {}
        self._ticker_cache_time: Dict[str, float] = {}
        self._ticker_cache_ttl = 1.0

        self._24h_ticker_cache: Dict[str, Dict[str, Any]] = {}
        self._24h_ticker_cache_time: Dict[str, float] = {}
        self._24h_ticker_cache_ttl = 60.0  # Cache 24h ticker for 1 minute

    def _acquire_rate_limit(self) -> None:
        with self._lock:
            now = time.time()

            while self._request_times and now - self._request_times[0] > self._rate_limit_period:
                self._request_times.popleft()

            if len(self._request_times) >= self._rate_limit_calls:
                sleep_time = self._rate_limit_period - (now - self._request_times[0])
                if sleep_time > 0:
                    logger.warning(f"Rate limit reached, sleeping {sleep_time:.2f}s")
                    time.sleep(sleep_time)
                    now = time.time()
                    while (
                        self._request_times
                        and now - self._request_times[0] > self._rate_limit_period
                    ):
                        self._request_times.popleft()

            self._request_times.append(now)

    def _generate_signature(self, params: str) -> str:
        return hmac.new(
            self.api_secret.encode("utf-8"), params.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _request(
        self,
        method: str,
        endpoint: str,
        signed: bool = False,
        params: Optional[Dict[str, Any]] = None,
        retry_count: int = 3,
    ) -> Any:
        params = params or {}

        for attempt in range(retry_count):
            try:
                self._acquire_rate_limit()
                url = f"{self.BASE_URL}{endpoint}"

                if signed:
                    params["timestamp"] = int(time.time() * 1000)
                    query_string = urlencode(sorted(params.items()))
                    signature = self._generate_signature(query_string)
                    query_string += f"&signature={signature}"
                    url = f"{url}?{query_string}"
                else:
                    url = f"{url}?{urlencode(params)}"

                response = self.session.request(method, url, timeout=10)

                if response.status_code == 429:
                    logger.warning(f"Rate limit hit, attempt {attempt + 1}/{retry_count}")
                    time.sleep(2**attempt)
                    continue

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    code = error_data.get("code", response.status_code)
                    msg = error_data.get("msg", "Unknown error")

                    if code == -1003:
                        raise RateLimitError(msg)
                    if code == -1001:
                        raise InsufficientBalanceError(msg)
                    raise ExchangeError(msg, code)

                return response.json()

            except requests.exceptions.RequestException as e:
                logger.error(f"Request error: {e}")
                if attempt == retry_count - 1:
                    raise ExchangeError(f"Request failed: {e}")
                time.sleep(2**attempt)

        return None

    def get_ticker(self, symbol: str) -> TickerPrice:
        cache_key = symbol.upper()
        now = time.time()

        if cache_key in self._ticker_cache:
            if now - self._ticker_cache_time.get(cache_key, 0) < self._ticker_cache_ttl:
                return self._ticker_cache[cache_key]

        try:
            data = self._request(
                "GET", "/fapi/v1/ticker/bookTicker", params={"symbol": symbol.upper()}
            )

            ticker = TickerPrice(
                symbol=symbol.upper(),
                bid=float(data["bidPrice"]),
                ask=float(data["askPrice"]),
                last=float(data.get("lastPrice", data["bidPrice"])),
                volume_24h=0.0,
                timestamp=datetime.now(),
            )

            self._ticker_cache[cache_key] = ticker
            self._ticker_cache_time[cache_key] = now
            return ticker

        except Exception as e:
            logger.error(f"Failed to get ticker: {e}")
            raise ExchangeError(f"Failed to get ticker: {e}")

    def get_24h_ticker(self, symbol: str) -> Dict[str, Any]:
        cache_key = symbol.upper()
        now = time.time()

        if cache_key in self._24h_ticker_cache:
            if now - self._24h_ticker_cache_time.get(cache_key, 0) < self._24h_ticker_cache_ttl:
                return self._24h_ticker_cache[cache_key]

        try:
            data = self._request("GET", "/fapi/v1/ticker/24hr", params={"symbol": symbol.upper()})

            self._24h_ticker_cache[cache_key] = data
            self._24h_ticker_cache_time[cache_key] = now
            return data

        except Exception as e:
            logger.error(f"Failed to get 24h ticker: {e}")
            raise ExchangeError(f"Failed to get 24h ticker: {e}")

    def get_balance(self, asset: str = "USDT") -> AccountBalance:
        balances = self.get_all_balances()
        for balance in balances:
            if balance.asset.upper() == asset.upper():
                return balance
        return AccountBalance(asset=asset, free=0.0, locked=0.0, total=0.0)

    def get_all_balances(self) -> List[AccountBalance]:
        try:
            data = self._request("GET", "/fapi/v1/balance", signed=True)
            return [
                AccountBalance(
                    asset=item["asset"],
                    free=float(item["free"]),
                    locked=float(item["locked"]),
                    total=float(item["free"]) + float(item["locked"]),
                )
                for item in data
            ]
        except Exception as e:
            logger.error(f"Failed to get balances: {e}")
            return []

    def get_position(self, symbol: str) -> Optional[Position]:
        positions = self.get_all_positions()
        for pos in positions:
            if pos.symbol.upper() == symbol.upper() and pos.quantity != 0:
                return pos
        return None

    def get_all_positions(self) -> List[Position]:
        try:
            data = self._request("GET", "/fapi/v1/account", signed=True)
            positions = []

            for pos in data.get("positions", []):
                quantity = float(pos.get("positionAmt", 0))
                if quantity == 0:
                    continue

                entry_price = float(pos.get("entryPrice", 0))
                leverage = int(pos.get("leverage", 1))
                current_price = float(pos.get("markPrice", entry_price))

                notional = abs(quantity * current_price)
                margin = notional / leverage if leverage > 0 else notional

                unrealized = float(pos.get("unrealizedProfit", 0))
                realized = float(pos.get("isolatedMargin", 0))

                positions.append(
                    Position(
                        symbol=pos["symbol"],
                        side="LONG" if quantity > 0 else "SHORT",
                        quantity=abs(quantity),
                        entry_price=entry_price,
                        current_price=current_price,
                        leverage=leverage,
                        unrealized_pnl=unrealized,
                        realized_pnl=realized,
                        notional_value=notional,
                        margin_used=margin,
                    )
                )

            return positions

        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    def place_market_order(
        self, symbol: str, side: str, quantity: float, reduce_only: bool = False
    ) -> OrderResponse:
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "quantity": quantity,
            "reduceOnly": reduce_only,
        }

        try:
            data = self._request("POST", "/fapi/v1/order", signed=True, params=params)
            return self._parse_order_response(data)
        except Exception as e:
            logger.error(f"Market order failed: {e}")
            raise

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
    ) -> OrderResponse:
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "LIMIT",
            "quantity": quantity,
            "price": price,
            "timeInForce": time_in_force,
            "reduceOnly": reduce_only,
        }

        try:
            data = self._request("POST", "/fapi/v1/order", signed=True, params=params)
            return self._parse_order_response(data)
        except Exception as e:
            logger.error(f"Limit order failed: {e}")
            raise

    def cancel_order(self, symbol: str, order_id: int) -> bool:
        try:
            self._request(
                "DELETE",
                "/fapi/v1/order",
                signed=True,
                params={"symbol": symbol.upper(), "orderId": str(order_id)},
            )
            return True
        except Exception as e:
            logger.error(f"Cancel order failed: {e}")
            return False

    def get_order(self, symbol: str, order_id: int) -> Optional[OrderResponse]:
        try:
            data = self._request(
                "GET",
                "/fapi/v1/order",
                signed=True,
                params={"symbol": symbol.upper(), "orderId": str(order_id)},
            )
            return self._parse_order_response(data)
        except Exception as e:
            logger.error(f"Get order failed: {e}")
            return None

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        try:
            self._request(
                "POST",
                "/fapi/v1/leverage",
                signed=True,
                params={"symbol": symbol.upper(), "leverage": leverage},
            )
            return True
        except Exception as e:
            logger.error(f"Set leverage failed: {e}")
            return False

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[List[Any]]:
        params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        return self._request("GET", "/fapi/v1/klines", params=params)

    def get_server_time(self) -> int:
        return self._request("GET", "/fapi/v1/time")["serverTime"]

    def _parse_order_response(self, data: Dict[str, Any]) -> OrderResponse:
        return OrderResponse(
            order_id=int(data["orderId"]),
            symbol=data["symbol"],
            side=data["side"],
            quantity=float(data["origQty"]),
            price=float(data.get("price", 0)),
            filled_quantity=float(data["executedQty"]),
            avg_fill_price=float(data.get("avgPrice", data.get("price", 0))),
            status=data["status"],
            client_order_id=data.get("clientOrderId"),
        )

    def is_connected(self) -> bool:
        try:
            self.get_server_time()
            return True
        except:
            return False

    def update_ticker_cache(self, symbol: str, ticker: TickerPrice) -> None:
        self._ticker_cache[symbol.upper()] = ticker
        self._ticker_cache_time[symbol.upper()] = time.time()

    def update_24h_ticker_cache(self, symbol: str, data: Dict[str, Any]) -> None:
        self._24h_ticker_cache[symbol.upper()] = data
        self._24h_ticker_cache_time[symbol.upper()] = time.time()
