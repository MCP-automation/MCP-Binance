
import os
import asyncio
from dotenv import load_dotenv
import ccxt.async_support as ccxt

async def test_key(name, exchange_class, params):
    print(f"\nTesting {name}...")
    exchange = exchange_class(params)
    try:
        balance = await exchange.fetch_balance()
        print(f"  ✅ SUCCESS! Balance USDT: {balance.get('USDT', {}).get('total', 'N/A')}")
        return True
    except Exception as e:
        print(f"  ❌ FAILED: {str(e)}")
        return False
    finally:
        await exchange.close()

async def main():
    load_dotenv(override=True)
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    
    if not api_key or not api_secret:
        print("No keys found in .env")
        return

    print(f"API Key: {api_key[:8]}...{api_key[-4:]}")

    # Test 1: Mainnet Futures
    await test_key("Mainnet Futures", ccxt.binanceusdm, {
        "apiKey": api_key,
        "secret": api_secret,
    })

    # Test 2: Testnet Futures (Sandbox)
    exchange_params = {
        "apiKey": api_key,
        "secret": api_secret,
    }
    print("\nTesting Testnet Futures...")
    testnet_exchange = ccxt.binance({**exchange_params, "options": {"defaultType": "future"}})
    testnet_exchange.set_sandbox_mode(True)
    try:
        balance = await testnet_exchange.fetch_balance()
        print(f"  ✅ SUCCESS! Balance USDT: {balance.get('USDT', {}).get('total', 'N/A')}")
    except Exception as e:
        print(f"  ❌ FAILED: {str(e)}")
    finally:
        await testnet_exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
