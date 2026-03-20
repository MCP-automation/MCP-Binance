
import os
import asyncio
from dotenv import load_dotenv
import ccxt.async_support as ccxt
import traceback

async def test_key(name, exchange_class, params):
    print(f"\n--- Testing {name} ---")
    exchange = exchange_class(params)
    try:
        print(f"Connecting to {name}...")
        # For non-futures, try fetch_balance
        # For futures, try fetch_balance(params={'type': 'future'})
        balance = await exchange.fetch_balance()
        print(f"  SUCCESS! Balance USDT: {balance.get('USDT', {}).get('total', 'N/A')}")
        return True
    except ccxt.AuthenticationError as e:
        print(f"  AUTH ERROR: {str(e)}")
    except ccxt.NetworkError as e:
        print(f"  NETWORK ERROR: {str(e)}")
    except Exception as e:
        print(f"  GENERAL ERROR: {type(e).__name__}: {str(e)}")
        # print(traceback.format_exc())
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

    # Test 1: Mainnet
    await test_key("Mainnet (binanceusdm)", ccxt.binanceusdm, {
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
    })

    # Test 2: Testnet (Futures)
    print("\n--- Testing Testnet (Sandbox) ---")
    testnet_exchange = ccxt.binance({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "future"}
    })
    testnet_exchange.set_sandbox_mode(True)
    try:
        balance = await testnet_exchange.fetch_balance()
        print(f"  SUCCESS! Balance USDT: {balance.get('USDT', {}).get('total', 'N/A')}")
    except ccxt.AuthenticationError as e:
        print(f"  AUTH ERROR: {str(e)}")
    except ccxt.NetworkError as e:
        print(f"  NETWORK ERROR: {str(e)}")
    except Exception as e:
        print(f"  GENERAL ERROR: {type(e).__name__}: {str(e)}")
    finally:
        await testnet_exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
