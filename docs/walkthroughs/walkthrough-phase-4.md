# Phase 4: Live Analysis Engine — Walkthrough

## Summary

Implemented the full Live Analysis Engine for the Crypto Signal Intelligence Platform. Users can now start real-time analysis sessions from the Signal Feed UI, selecting a symbol and strategies. The backend connects to Binance WebSocket streams, detects candle closes, runs strategies, and pushes watching card updates to the frontend via SSE.

## Changes Made

### Backend — New Files (8)

| File | Purpose |
|---|---|
| [sse.py](file:///Users/artemis/Mehul/C_helper/backend/app/core/sse.py) | Thread-safe SSE pub/sub manager with subscriber queues, keepalive, and dead-subscriber cleanup |
| [scanner.py](file:///Users/artemis/Mehul/C_helper/backend/app/core/scanner.py) | `LiveScanner` singleton — manages sessions (max 2), coordinates candle-close → strategy execution → watching setup lifecycle |
| [watching.py](file:///Users/artemis/Mehul/C_helper/backend/app/core/watching.py) | `WatchingManager` — CRUD for watching setups with deduplication (update existing on re-fire) and configurable expiry |
| [signals_bp.py](file:///Users/artemis/Mehul/C_helper/backend/app/blueprints/signals_bp.py) | REST + SSE blueprint: session start/stop, watching setup queries, SSE event stream endpoint |
| [test_sse.py](file:///Users/artemis/Mehul/C_helper/backend/tests/test_sse.py) | 15 tests — subscribe/unsubscribe, publish, thread safety, queue overflow, keepalive |
| [test_binance_ws.py](file:///Users/artemis/Mehul/C_helper/backend/tests/test_binance_ws.py) | 20 tests — URL construction, message parsing, candle-close detection, lifecycle, reconnection |
| [test_watching.py](file:///Users/artemis/Mehul/C_helper/backend/tests/test_watching.py) | 14 tests — create/update dedup, tick expiry, session cleanup, queries |
| [test_scanner.py](file:///Users/artemis/Mehul/C_helper/backend/tests/test_scanner.py) | 11 tests — session lifecycle, max-2 enforcement, duplicate rejection, timeframe resolution |

### Backend — Modified Files (4)

| File | Changes |
|---|---|
| [binance.py](file:///Users/artemis/Mehul/C_helper/backend/app/utils/binance.py) | Added `BinanceStreamManager` class — WebSocket kline streams with candle-close detection, live price tracking, auto-reconnect |
| [db.py](file:///Users/artemis/Mehul/C_helper/backend/app/models/db.py) | Added `WatchingSetup` and `AnalysisSessionRecord` models with `to_dict()` serialization |
| [__init__.py](file:///Users/artemis/Mehul/C_helper/backend/app/__init__.py) | Registered `signals_bp`, initialized `LiveScanner` with app context, added `atexit` shutdown hook, `test_config` parameter for create_app |
| [.env](file:///Users/artemis/Mehul/C_helper/backend/.env) | Added `SIGNAL_EXPIRY_CANDLES=3` |

### Frontend — New Files (8)

| File | Purpose |
|---|---|
| [signals.ts](file:///Users/artemis/Mehul/C_helper/frontend/src/types/signals.ts) | TypeScript interfaces: `AnalysisSession`, `WatchingSetup`, `PriceUpdate`, `SSEEvent`, `Strategy` |
| [useSSE.ts](file:///Users/artemis/Mehul/C_helper/frontend/src/hooks/useSSE.ts) | SSE connection hook with auto-reconnect and typed event dispatching |
| [useAnalysisSessions.ts](file:///Users/artemis/Mehul/C_helper/frontend/src/hooks/useAnalysisSessions.ts) | Session CRUD hook with strategy fetching and max-2 enforcement |
| [SignalFeed.tsx](file:///Users/artemis/Mehul/C_helper/frontend/src/pages/SignalFeed/SignalFeed.tsx) | Main page — SSE integration, session management, Watching/Confirmed tabs |
| [SessionPanel.tsx](file:///Users/artemis/Mehul/C_helper/frontend/src/pages/SignalFeed/SessionPanel.tsx) | Session cards with live price ticker, new session form with strategy picker |
| [WatchingTab.tsx](file:///Users/artemis/Mehul/C_helper/frontend/src/pages/SignalFeed/WatchingTab.tsx) | Responsive grid of watching cards with empty state |
| [ConfirmedTab.tsx](file:///Users/artemis/Mehul/C_helper/frontend/src/pages/SignalFeed/ConfirmedTab.tsx) | Phase 5 placeholder |
| [WatchingCard.tsx](file:///Users/artemis/Mehul/C_helper/frontend/src/components/WatchingCard/WatchingCard.tsx) | Card component: direction badge, confidence bar, mini chart, entry/SL/TP, elapsed time, expiry indicator |
| [MiniChart.tsx](file:///Users/artemis/Mehul/C_helper/frontend/src/components/WatchingCard/MiniChart.tsx) | TradingView Lightweight Charts area chart (80px) with entry line |

### Frontend — Modified Files (2)

| File | Changes |
|---|---|
| [App.tsx](file:///Users/artemis/Mehul/C_helper/frontend/src/App.tsx) | Added `SignalFeed` route, active-page highlighting via `NavLink` component |
| [client.ts](file:///Users/artemis/Mehul/C_helper/frontend/src/api/client.ts) | Added Phase 4 API functions: `fetchActiveSessions`, `startSession`, `stopSession`, `fetchWatchingSetups`, `fetchWatchingSetup`, `fetchStrategies` |

### Config / Deps (2)

| File | Changes |
|---|---|
| [environment.yml](file:///Users/artemis/Mehul/C_helper/backend/environment.yml) | Added `websocket-client` dependency |
| package.json | Added `lightweight-charts` (`npm install`) |

### Documentation (1)

| File | Purpose |
|---|---|
| [live_analysis.md](file:///Users/artemis/Mehul/C_helper/docs/logic/live_analysis.md) | Full system documentation: architecture, session lifecycle, candle-close handler flow, watching setup lifecycle, SSE events, threading model |

---

**Total: 25 files** (16 new, 7 modified, 2 config/dep updates)

## Verification Results

### Backend Tests — 60/60 passing
```
tests/test_sse.py         — 15 passed
tests/test_binance_ws.py  — 20 passed
tests/test_watching.py    — 14 passed
tests/test_scanner.py     — 11 passed
```

### Frontend Build — Clean
```
tsc --noEmit    ✓ (0 errors)
vite build      ✓ (built in 186ms)
```

## Key Design Decisions Implemented

1. **SSE (not WebSocket)** for frontend push — unidirectional server→client
2. **Ephemeral sessions** — in-memory only, reset on browser close
3. **One symbol per session, max 2 concurrent** — with duplicate symbol rejection
4. **Live price ticker** — extracted from every unclosed candle tick, pushed via `price_update` SSE event
5. **Watching card deduplication** — same strategy+symbol+timeframe updates existing card, resets expiry counter
6. **`websocket-client`** (threaded) for Binance streams — compatible with Flask's synchronous model
