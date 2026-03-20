# PHASE 6: WEB DASHBOARD

## Overview

Phase 6 implements a professional real-time web dashboard for monitoring trading activity, risk metrics, positions, and performance with WebSocket live updates.

---

## Three Core Components

### 1. DashboardServer (`dashboard/server.py`)

**Purpose**: FastAPI web server with WebSocket support

**Endpoints**:

#### GET /api/health
Health check endpoint
```
Response: {"status": "healthy", "timestamp": "ISO-datetime"}
```

#### GET /api/dashboard
Complete dashboard data snapshot
```
Response:
{
  "timestamp": "ISO-datetime",
  "account": {
    "equity": float,
    "initial_equity": float,
    "total_pnl": float,
    "total_pnl_pct": float
  },
  "risk": {
    "total_exposure": float,
    "exposure_pct": float,
    "drawdown_pct": float,
    "daily_loss": float,
    "daily_loss_pct": float
  },
  "positions": {
    "open_count": int,
    "max_allowed": int,
    "is_within_limits": bool
  }
}
```

#### GET /api/positions
Open positions with details
```
Response:
{
  "success": bool,
  "positions": [
    {
      "symbol": "BTCUSDT",
      "quantity": float,
      "entry_price": float,
      "stop_loss": float,
      "take_profit": float,
      "max_loss_pct": float,
      "risk_reward": float,
      "created_at": "ISO-datetime"
    }
  ]
}
```

#### GET /api/metrics
Risk metrics summary
```
Response:
{
  "success": bool,
  "metrics": {
    "account_equity": float,
    "total_risk_exposure": float,
    "total_risk_pct": float,
    "open_positions": int,
    "daily_loss": float,
    "drawdown_pct": float,
    "is_within_limits": bool,
    "breached_limits": [string]
  }
}
```

#### WebSocket /ws/updates
Real-time updates via WebSocket
```
Connection: 
  - "initial" → Complete dashboard data on connect
  - "refresh" → Manual refresh request
  - "ping" → Keep-alive check
```

---

### 2. DashboardManager (`dashboard/manager.py`)

**Purpose**: Lifecycle management and configuration

**Features**:
- Async server startup/shutdown
- Thread-safe operation
- Status monitoring
- Configuration management

**API**:
```python
manager = DashboardManager(
    app_context=ctx,
    host="0.0.0.0",
    port=8000
)

await manager.start()
manager.start_in_thread()
manager.stop_server()
status = manager.get_status()
```

---

### 3. DashboardRoutes (`dashboard/routes.py`)

**Purpose**: Additional API endpoints for detailed data

**Endpoints**:

#### GET /api/summary
Complete account summary with all metrics

#### GET /api/equity-history?days=30
Equity curve data and daily returns

#### GET /api/trades?limit=50
Trade history with P&L details

#### GET /api/symbols-stats
Per-symbol statistics

#### GET /api/risk-breakdown
Risk distribution across positions

#### GET /api/daily-stats
Daily trading statistics

---

## Frontend (HTML/CSS/JavaScript)

**Features**:
- Real-time WebSocket updates
- Responsive design (mobile/desktop)
- Color-coded metrics (green=good, red=warning)
- Automatic reconnection with exponential backoff
- Position table with live data
- Status indicator with pulse animation

**Sections**:
1. **Account Balance** - Equity, P&L, returns
2. **Risk Metrics** - Drawdown, daily loss, limits
3. **Positions** - Open count, exposure, status
4. **Equity Curve** - Historical chart placeholder
5. **Position Table** - All open trades

---

## Architecture

```
Frontend (React/Vanilla JS)
    ↓ (WebSocket)
DashboardServer (FastAPI)
    ↓
DashboardRoutes (API Endpoints)
    ↓
Phase 1-5 Systems
```

---

## Real-Time Updates

WebSocket connection with automatic reconnection:
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/updates');

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.type === 'initial') {
    // Load complete data
  } else if (message.type === 'update') {
    // Incremental update
  }
};

// Keep-alive: send ping every 30 seconds
setInterval(() => ws.send('ping'), 30000);
```

---

## Installation

Add to requirements.txt:
```
fastapi==0.115.1
uvicorn==0.32.1
websockets==15.0
```

---

## Deployment

### Start Server
```python
from dashboard import DashboardManager

manager = DashboardManager(app_context, port=8000)
await manager.start()
```

### Access Dashboard
```
http://localhost:8000
```

### WebSocket Connection
```
ws://localhost:8000/ws/updates
```

---

## Data Aggregation

Dashboard aggregates data from all phases:

**From Phase 1**:
- Logging (all events persisted)
- Database (trade history)

**From Phase 2**:
- Current positions
- Ticker prices
- Order status

**From Phase 3**:
- Risk metrics
- Equity curve
- Daily statistics

**From Phase 4**:
- Backtest results
- Historical performance

**From Phase 5**:
- MCP tool results
- Strategy configs

---

## Performance Optimizations

- **Lazy Loading**: Equity chart loads separately
- **Data Caching**: Summary cached for 5 seconds
- **WebSocket Batching**: Updates bundled every 1 second
- **Compression**: JSON responses compressed
- **Rate Limiting**: Per-endpoint rate limits

---

## Testing

Phase 6 includes 40+ tests:
- Health check endpoint
- Dashboard data formats
- Position endpoint
- Metrics endpoint
- Route completeness
- Error handling
- WebSocket connection
- Data aggregation

Run tests:
```bash
pytest tests/integration/test_phase6_dashboard.py -v
```

---

## Monitoring

Real-time monitoring includes:
- Account equity
- Drawdown percentage
- Daily loss tracking
- Open position count
- Risk exposure
- Portfolio concentration
- Trade history
- Performance metrics

---

## Responsive Design

- **Desktop**: Full 3-column layout
- **Tablet**: 2-column layout
- **Mobile**: Single column with scrolling

---

## Integration with All Phases

**Phase 1**: Database persistence, logging
**Phase 2**: Live prices, position tracking
**Phase 3**: Risk monitoring, limits enforcement
**Phase 4**: Performance metrics, backtest results
**Phase 5**: MCP tool results display

---

## Next Phase

Phase 7: Telegram Notifications
- SMS/Telegram alerts
- Risk breach notifications
- Trade execution alerts
- Daily summary reports

