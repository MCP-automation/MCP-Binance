"""
MCP Handler: Multi-Symbol Backtest
Run EMA crossover strategy backtest on multiple USDM Futures symbols
"""

from __future__ import annotations
import asyncio
import json
import logging
from decimal import Decimal

from app_context import ApplicationContext
from backtesting.data.binance_fetcher import BinanceFuturesDataFetcher
from backtesting.strategies.ema_crossover import EMACrossoverStrategy
import pandas as pd

logger = logging.getLogger(__name__)


async def handle_run_multi_symbol_backtest(params: dict) -> str:
    """
    Run EMA crossover strategy on multiple symbols.
    
    Parameters:
        - symbols (list): Symbols to test
        - timeframe (str): Candle interval (1h, 4h, 1d)
        - fast_ema (int): Fast EMA period (default: 12)
        - slow_ema (int): Slow EMA period (default: 26)
        - lookback (int): Candles to fetch (default: 500)
        - top_n (int): Return top N performers (default: 10)
    
    Returns:
        JSON with backtest results sorted by Sharpe ratio
    """
    try:
        ctx = ApplicationContext.get()
        
        # Extract parameters
        symbols = params.get("symbols", [])
        timeframe = params.get("timeframe", "1h").upper()
        fast_ema = int(params.get("fast_ema", 12))
        slow_ema = int(params.get("slow_ema", 26))
        lookback = int(params.get("lookback", 500))
        top_n = int(params.get("top_n", 10))
        
        if not symbols:
            return json.dumps({
                "success": False,
                "error": "symbols parameter is required"
            })
        
        logger.info(f"Starting multi-symbol backtest on {len(symbols)} symbols")
        
        # Fetch data
        async with BinanceFuturesDataFetcher(
            testnet=ctx.config.binance_api.testnet_enabled
        ) as fetcher:
            batch_data = await fetcher.get_klines_batch(
                symbols=symbols,
                interval=timeframe,
                limit=lookback,
                concurrent=10
            )
        
        # Run backtest on each symbol
        results = []
        
        for symbol in symbols:
            if symbol not in batch_data or not batch_data[symbol]:
                logger.warning(f"No data for {symbol}, skipping")
                continue
            
            try:
                candles = batch_data[symbol]
                
                # Convert to DataFrame for strategy
                df = pd.DataFrame([
                    {
                        "timestamp": c.timestamp,
                        "open": float(c.open),
                        "high": float(c.high),
                        "low": float(c.low),
                        "close": float(c.close),
                        "volume": float(c.volume),
                    }
                    for c in candles
                ])
                
                # Run strategy
                strategy = EMACrossoverStrategy(
                    fast_period=fast_ema,
                    slow_period=slow_ema
                )
                metrics = await strategy.backtest(df)
                
                # Store result
                results.append({
                    "symbol": symbol,
                    "trades": metrics.get("trades", 0),
                    "win_rate": metrics.get("win_rate", 0),
                    "pnl": str(metrics.get("pnl", 0)),
                    "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                    "max_drawdown": metrics.get("max_drawdown", 0),
                    "return_pct": metrics.get("return_pct", 0)
                })
                
                logger.info(f"✓ {symbol}: {metrics['trades']} trades, "
                           f"WR: {metrics['win_rate']:.1f}%")
            
            except Exception as e:
                logger.error(f"Error backtesting {symbol}: {e}")
                continue
        
        # Sort by Sharpe ratio
        results.sort(
            key=lambda x: x["sharpe_ratio"],
            reverse=True
        )
        
        top_results = results[:top_n]
        
        logger.info(f"✓ Backtest complete. Top performer: "
                   f"{top_results[0]['symbol'] if top_results else 'N/A'}")
        
        return json.dumps({
            "success": True,
            "timeframe": timeframe,
            "symbols_tested": len(results),
            "top_n": top_n,
            "results": top_results,
            "summary": {
                "avg_trades": sum(r["trades"] for r in results) / len(results) if results else 0,
                "avg_win_rate": sum(r["win_rate"] for r in results) / len(results) if results else 0,
                "avg_sharpe": sum(r["sharpe_ratio"] for r in results) / len(results) if results else 0
            }
        })
    
    except Exception as e:
        logger.error(f"Multi-symbol backtest error: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": str(e)
        })
