"""Quick smoke-test: initialise ccxt Binance USD-M Futures, load markets, print BTCUSDT ticker.

Uses async ccxt with an aiohttp ThreadedResolver to bypass aiodns DNS failures on Windows.
"""
import asyncio
import aiohttp
import ccxt.async_support as ccxt


async def main() -> None:
    exchange = ccxt.binanceusdm({"enableRateLimit": True})

    # Bypass aiodns (breaks on Windows) — use the threaded resolver backed by socket.getaddrinfo
    resolver = aiohttp.ThreadedResolver()
    connector = aiohttp.TCPConnector(resolver=resolver)
    exchange.session = aiohttp.ClientSession(connector=connector)

    try:
        print("Loading markets...")
        await exchange.load_markets()
        print(f"Markets loaded: {len(exchange.markets)} symbols available")

        print("\nFetching BTCUSDT ticker...")
        ticker = await exchange.fetch_ticker("BTC/USDT:USDT")
        print(f"  Symbol    : {ticker['symbol']}")
        print(f"  Last price: {ticker['last']}")
        print(f"  Bid / Ask : {ticker['bid']} / {ticker['ask']}")
        print(f"  24h High  : {ticker['high']}")
        print(f"  24h Low   : {ticker['low']}")
        print(f"  Volume    : {ticker['baseVolume']}")
        print("\nConnection OK.")
    finally:
        await exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
