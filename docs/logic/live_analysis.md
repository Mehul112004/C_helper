# Live Analysis Engine — System Logic

## Overview

The Live Analysis Engine enables real-time market scanning via Binance WebSocket streams. Users start **analysis sessions** from the Signal Feed UI, selecting a symbol and strategies. The backend connects to Binance, detects candle closes, runs the selected strategies, and pushes **watching card** updates to the frontend via Server-Sent Events (SSE).

## Architecture

```
Frontend (React)                     Backend (Flask)
─────────────────                    ────────────────
                                     
SignalFeed page ──REST──▶  signals_bp (Blueprint)
  SessionPanel              │
  WatchingTab               ├── LiveScanner (session manager)
  WatchingCard              │     └── BinanceStreamManager (WebSocket)
                            │
  useSSE hook ◀──SSE────── SSEManager (pub/sub)
                            │
                            ├── WatchingManager (setup lifecycle)
                            ├── StrategyRunner (existing, Phase 3)
                            ├── IndicatorService (existing, Phase 2)
                            └── SREngine (existing, Phase 2)
```

## Session Lifecycle

### Starting a Session
1. User selects a **symbol** (e.g. `BTCUSDT`) and **strategies** (e.g. `EMA Crossover`, `RSI Reversal`)
2. `LiveScanner.start_session()` validates:
   - Max 2 active sessions
   - No duplicate symbols across sessions
   - All strategy names exist in the registry
3. Resolves the **union of all timeframes** from selected strategies
4. Creates a `BinanceStreamManager` with combined kline streams
5. Registers `on_candle_close` and `on_price_update` callbacks
6. Starts the WebSocket in a daemon thread
7. Publishes SSE `session_started` event

### During a Session
- **Live price ticks**: Every WebSocket message (closed or unclosed) fires `on_price_update`, which updates the session's `live_price` and publishes a `price_update` SSE event
- **Candle closes**: When `kline.x == True`, the full flow runs (see below)
- **Auto-reconnect**: On WebSocket disconnect, exponential backoff (1s → 60s max, 20 retries)

### Stopping a Session
1. `LiveScanner.stop_session()` sets status to `"stopping"`
2. Closes the WebSocket connection
3. Expires all WATCHING setups for this session via `WatchingManager.expire_all_for_session()`
4. Updates session record status to `"stopped"` in DB
5. Publishes SSE `session_stopped` event

### Session Persistence
Sessions are **ephemeral** — stored in-memory. They reset on:
- Browser close/refresh (SSE connection drops)
- Backend restart
- User manually stopping them

## Candle Close Handler Flow

When a candle closes on Binance:

```
1. Upsert the closed candle into the `candles` DB table
2. Invalidate the indicator cache for this symbol/timeframe
2b. Trigger S/R zone refresh based on candle timeframe:
    - 4h / 1D → SREngine.full_refresh() (full pipeline)
    - 1h / 15m → SREngine.minor_update() (swing points only)
3. Compute fresh indicators via IndicatorService.compute_all()
4. Fetch S/R zones within 3% of the current close price
   (under per-symbol refresh lock to avoid mid-commit reads)
5. Build candle window (last 50 candles from DB)
6. Build Indicators snapshot at the latest index
7. For each active strategy in this session on this timeframe:
   a. Run StrategyRunner.run_single_scan()
   b. If SetupSignal returned:
      - Check for existing WATCHING setup (strategy + symbol + timeframe)
      - If exists → UPDATE (refresh confidence, notes, reset expiry) → SSE "setup_updated"
      - If not → CREATE new WatchingSetup → SSE "setup_detected"
8. Tick expiry on all existing WATCHING setups for this symbol/timeframe:
   - Increment candles_since_detected
   - If >= expiry_candles → mark EXPIRED → SSE "setup_expired"
9. Publish SSE "candle_close" event
```

## Watching Setup Lifecycle

### States
| Status | Description |
|---|---|
| `WATCHING` | Active setup being monitored |
| `EXPIRED` | Setup expired after N candle closes without re-confirmation |
| `CONFIRMED` | Setup confirmed by user (Phase 5) |
| `REJECTED` | Setup rejected by user (Phase 5) |

### Deduplication
When the same strategy fires on the same symbol/timeframe in a subsequent candle close:
- The **existing** card is updated (not duplicated)
- `confidence`, `notes`, `entry`, `sl`, `tp1`, `tp2` are refreshed
- `candles_since_detected` is reset to `0` — the setup is "re-confirmed"

### Expiry
- Default: 3 candle closes (configurable via `SIGNAL_EXPIRY_CANDLES` env var)
- On each candle close for matching symbol/timeframe, `candles_since_detected` increments
- When `candles_since_detected >= expiry_candles` → status becomes `EXPIRED`
- Frontend fades out expired cards after 2 seconds

## SSE Event Types

| Event | Payload | When |
|---|---|---|
| `session_started` | `AnalysisSession` dict | New session created |
| `session_stopped` | `{session_id}` | Session stopped |
| `setup_detected` | `WatchingSetup` dict | New watching card created |
| `setup_updated` | `WatchingSetup` dict | Existing card refreshed (dedup) |
| `setup_expired` | `WatchingSetup` dict | Card expired |
| `price_update` | `{session_id, symbol, price, timestamp}` | Live tick from unclosed candle |
| `candle_close` | `{symbol, timeframe, close, timestamp}` | A candle close was processed |

## Threading Model

```
Main Thread (Flask)
├── serves REST endpoints
└── serves SSE endpoint (blocking generator per client)

WebSocket Thread (per session, daemon)
├── receives Binance kline messages
├── fires on_price_update → publishes SSE event
└── fires on_candle_close → acquires app context → runs full scan pipeline
    ├── S/R zone refresh (full_refresh or minor_update, under per-symbol lock)
    ├── DB operations (upsert candle, query indicators/zones)
    ├── Strategy execution (run_single_scan)
    ├── WatchingManager operations (create/update/expire)
    └── SSE publishing (thread-safe via queue.Queue)

Scheduler Thread (APScheduler, daemon)
├── full_zone_refresh_4h  — every 4h at :01 (active sessions only)
├── full_zone_refresh_1d  — daily at 00:02 (active sessions only)
├── minor_zone_update     — hourly at :03 (active sessions only)
└── startup_full_refresh  — once on boot
```

## Configuration

| Env Key | Default | Description |
|---|---|---|
| `SIGNAL_EXPIRY_CANDLES` | `3` | Number of candle closes before a watching setup expires |
| `DATABASE_URL` | `postgresql://...` | TimescaleDB connection string |

## Database Tables (Phase 4 additions)

### `watching_setups`
Stores detected setups with dedup key: `(session_id, strategy_name, symbol, timeframe)`.

### `analysis_sessions`
Lightweight mirror of in-memory sessions for DB reference and SSE context.
