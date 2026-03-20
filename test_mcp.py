import asyncio
import sys
from pathlib import Path

ROOT = Path(r"c:\Users\Naman\Downloads\binance_mcp\binance_mcp")
sys.path.insert(0, str(ROOT))

from core.security import SecretsVault
from app_context import ApplicationContext
from mcp_app.server.runner import MCPServerRunner
from main import _unlock_vault

async def main():
    print("Testing MCP Tools...")
    vault = _unlock_vault(ROOT)
    ctx = await ApplicationContext.create(ROOT, vault=vault)
    runner = MCPServerRunner(ctx)
    
    # Test tool 1: get_futures_symbols
    print("\n--- Testing get_futures_symbols ---")
    symbols = await runner.get_futures_symbols()
    print("Fetched symbols:", len(symbols.get("symbols", [])))
    
    # Test tool 2: get_risk_metrics
    print("\n--- Testing get_risk_metrics ---")
    metrics = await runner.get_risk_metrics()
    print("Risk metrics:", metrics)
    
    await ctx.shutdown()
    print("\nSuccess! Tools are working.")

if __name__ == "__main__":
    asyncio.run(main())
