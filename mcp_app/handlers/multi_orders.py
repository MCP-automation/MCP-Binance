"""
MCP Handler: Multi-Symbol Order Placement
Scan symbols for entry signals and place orders automatically
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


async def handle_place_multi_symbol_orders(params: dict) -> str:
    """
    Scan symbols for EMA crossover entry signals and place orders.
    
    Parameters:
        - symbols (list): Symbols to scan
        - timeframe (str): Candle interval (default: 1h)
        - fast_ema (int): Fast EMA period (default: 12)
        - slow_ema (int): Slow EMA period (default: 26)
        - risk_per_trade (float): Risk % per trade (default: 1.0)
        - max_positions (int): Max open positions (default: 10)
        - quantity (float, optional): Fixed quantity per order
    
    Returns:
        JSON with placed orders
    """
    try:
        ctx = ApplicationContext.get()
        
        # Extract parameters
        symbols = params.get("symbols", [])
        timeframe = params.get("timeframe", "1h").upper()
        fast_ema = int(params.get("fast_ema", 12))
        slow_ema = int(params.get("slow_ema", 26))
        risk_pct = float(params.get("risk_per_trade", 1.0))
        max_positions = int(params.get("max_positions", 10))
        quantity = params.get("quantity")
        
        if not symbols:
            return json.dumps({
                "success": False,
                "error": "symbols parameter is required"
            })
        
        if risk_pct <= 0 or risk_pct > 10:
            return json.dumps({
                "success": False,
                "error": "risk_per_trade must be between 0.1 and 10"
            })
        
        logger.info(f"Scanning {len(symbols)} symbols for entry signals")
        
        # Get current positions
        positions = await ctx.exchange_manager.get_positions()
        open_positions = [p for p in positions if p["quantity"] > 0]
        
        if len(open_positions) >= max_positions:
            return json.dumps({
                "success": False,
                "error": f"Max positions ({max_positions}) reached"
            })
        
        # Fetch data
        async with BinanceFuturesDataFetcher(
            testnet=ctx.config.binance_api.testnet_enabled
        ) as fetcher:
            batch_data = await fetcher.get_klines_batch(
                symbols=symbols,
                interval=timeframe,
                limit=100,
                concurrent=10
            )
        
        # Scan for signals
        signals = []
        
        for symbol in symbols:
            if symbol not in batch_data or not batch_data[symbol]:
                continue
            
            try:
                # Check if already open
                if any(p["symbol"] == symbol for p in open_positions):
                    logger.info(f"Skipping {symbol}: already open")
                    continue
                
                candles = batch_data[symbol]
                
                # Convert to DataFrame
                df = pd.DataFrame([
                    {
                        "close": float(c.close),
                        "volume": float(c.volume),
                    }
                    for c in candles
                ])
                
                # Get signal
                strategy = EMACrossoverStrategy(
                    fast_period=fast_ema,
                    slow_period=slow_ema
                )
                signal = await strategy.get_signal(df)
                
                if signal and signal["direction"] == "BUY":
                    signals.append({
                        "symbol": symbol,
                        "signal": "BUY",
                        "price": float(candles[-1].close),
                        "strength": signal.get("strength", 0.5)
                    })
                    logger.info(f"✓ BUY signal: {symbol}")
            
            except Exception as e:
                logger.warning(f"Signal scan error for {symbol}: {e}")
                continue
        
        # Sort by signal strength
        signals.sort(key=lambda x: x["strength"], reverse=True)
        
        # Place orders up to max positions
        available_slots = max_positions - len(open_positions)
        orders_to_place = signals[:available_slots]
        
        placed_orders = []
        
        for signal in orders_to_place:
            try:
                symbol = signal["symbol"]
                
                # Calculate quantity
                if quantity:
                    qty = float(quantity)
                else:
                    # Use risk-based sizing
                    account = await ctx.exchange_manager.get_account()
                    equity = Decimal(str(account.get("total_equity", 1000)))
                    max_loss = equity * Decimal(str(risk_pct / 100))
                    # Simplified: assume 2% stop loss
                    qty = float(max_loss / (Decimal(str(signal["price"])) * Decimal("0.02")))
                
                # Place market order
                order = await ctx.exchange_manager.place_order(
                    symbol=symbol,
                    side="BUY",
                    quantity=qty,
                    market_type="USDM_FUTURES"
                )
                
                placed_orders.append({
                    "symbol": symbol,
                    "order_id": order.get("orderId"),
                    "quantity": qty,
                    "price": signal["price"],
                    "status": "PLACED"
                })
                
                logger.info(f"✓ Order placed: {symbol} {qty} @ {signal['price']}")
            
            except Exception as e:
                logger.error(f"Error placing order for {symbol}: {e}")
                continue
        
        logger.info(f"✓ Placed {len(placed_orders)} orders")
        
        return json.dumps({
            "success": True,
            "signals_found": len(signals),
            "orders_placed": len(placed_orders),
            "orders": placed_orders,
            "available_slots": available_slots,
            "skipped_reason": "max_positions" if len(signals) > available_slots else None
        })
    
    except Exception as e:
        logger.error(f"Multi-symbol order error: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": str(e)
        })
