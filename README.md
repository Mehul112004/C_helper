# Crypto Signal Intelligence Platform — Final Roadmap

---

## 1. Platform Overview

A personal, local, single-user crypto signal intelligence tool. It watches BTC, ETH, SOL, and XRP across multiple timeframes, identifies high-quality trade setups using technical strategies and pattern recognition, and delivers LLM-confirmed signals to the web UI and Telegram. No automated trading. All signals are acted on manually.

---

## 2. Core Philosophy

- **Not a trading bot.** No order execution, no API keys for exchanges, no automated positions.
- **Signal intelligence only.** The platform is an analyst. You are the trader.
- **LLM as final judge.** The LLM is never used for continuous market scanning. It is invoked once per candidate signal and returns a verdict.
- **Quality over quantity.** Target: 5–6 confirmed signals per day across all symbols and timeframes.
- **Fully local.** No cloud dependencies. Flask backend + React frontend + LM Studio, all running on your machine.
- **Modular by design.** Strategies, data sources, and notification channels are all pluggable.

---

## 3. Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React (Vite + TypeScript) |
| Backend | Python Flask |
| Database | PostgreSQL with TimescaleDB extension |
| Market data | Binance REST API + WebSocket (primary) |
| Historical data import | Binance API + CSV upload |
| LLM | LM Studio — local HTTP API (OpenAI-compatible) |
| Notifications | Telegram Bot API |
| Strategy execution | Python — sandboxed hot-reload engine |
| Charts | Lightweight Charts (TradingView library) |

---

## 4. Target Symbols & Timeframes

**Symbols:** BTCUSDT · ETHUSDT · SOLUSDT · XRPUSDT

**Timeframe roles:**

| Timeframe | Role |
|---|---|
| 1D | Primary trend direction, major S/R zones |
| 4h | Setup identification, structure analysis |
| 1h | Signal confirmation, entry timing |
| 15m | Entry precision, SL refinement |
| 5m | Optional — fine entry on fast-moving setups |

Higher timeframes (1D, 4h) determine trend bias and key levels. Lower timeframes (1h, 15m) confirm entry patterns and refine levels.

---

## 5. Web UI — Four Pages

### 5.1 Signal Feed (primary daily-use page)

Two tabs on one page:

**Tab 1 — Watching**
Cards for setups currently being monitored. A watching card is created when a strategy identifies a zone or condition worth tracking but the trigger candle has not yet closed. These are "setups in progress."

Each watching card displays:
- Symbol + timeframe
- Direction bias (LONG / SHORT)
- Zone or level being watched (e.g. "Resistance at $3,420")
- Condition waiting for (e.g. "Bearish engulfing on 1h close")
- Strategies active for this setup
- Time elapsed since setup was identified
- A mini price chart showing the zone

**Tab 2 — Confirmed Signals**
Cards for signals that have triggered, passed LLM review, and been sent to Telegram. These are actionable.

Each confirmed signal card displays:
- Symbol + direction badge (LONG green / SHORT red)
- Timeframe
- Entry, SL, TP1, TP2 levels
- Risk/reward ratio
- Strategy or strategies that generated this signal
- LLM verdict badge + expandable reasoning text
- Timestamp
- Signal outcome (ACTIVE / HIT_TP1 / HIT_TP2 / HIT_SL / EXPIRED) — updated automatically

**Analysis session panel (sidebar or top bar):**
- Start a new analysis session: select symbol + active strategies
- Up to 2 simultaneous analysis sessions
- Each session shows as a labelled block (e.g. "BTCUSDT — S/R Zones, EMA Crossover")
- Sessions reset on browser close/refresh

---

### 5.2 Backtesting Page

**Configuration panel:**
- Symbol selector (BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT)
- Timeframe selector (5m, 15m, 1h, 4h, 1D)
- Date range picker (start date / end date)
- Strategy selector (multi-select from all available built-in and custom strategies)
- Initial capital input
- Risk per trade (% of capital)
- Run Backtest button

**Results — Summary metrics panel:**

| Metric | Description |
|---|---|
| Total trades | Number of signals taken |
| Win rate | % of trades that hit TP1 or TP2 |
| Total PnL | Net profit/loss in USD and % |
| Sharpe ratio | Risk-adjusted return |
| Sortino ratio | Downside risk-adjusted return |
| Max drawdown | Largest peak-to-trough loss |
| Avg risk/reward | Average RR across all trades |
| Profit factor | Gross profit / gross loss |
| Avg trade duration | Mean time from entry to close |
| Best trade / Worst trade | Individual extremes |

**Results — Equity curve chart:**
- Line chart showing portfolio value over time
- Drawdown shaded below the curve
- Zoomable and pannable

**Results — Trade chart:**
- Full price chart for the tested symbol and timeframe
- All trades plotted directly on the chart:
  - Entry marker (triangle up for LONG, triangle down for SHORT)
  - SL line (red dashed)
  - TP1 line (green dashed)
  - TP2 line (green dashed, lighter)
  - Trade outcome color-coded (green = TP hit, red = SL hit, gray = expired)
- Zoomable so individual trades can be inspected

**Results — Per-trade log table:**
- Columns: #, Date, Symbol, Timeframe, Direction, Entry, SL, TP1, TP2, Exit price, Outcome, PnL, Duration, Strategy
- Sortable by any column
- Exportable as CSV

---

### 5.3 Strategy IDE Page

**Layout:**
- Left panel: list of all strategies (built-in and custom), with enable/disable toggle and delete option for custom ones
- Right panel: Python code editor (Monaco Editor — same editor as VS Code)

**Editor features:**
- Syntax highlighting (Python)
- Basic autocomplete for platform classes and methods
- Error display inline (syntax errors shown before saving)
- Save button — hot-loads the strategy into the live engine without restart
- A built-in strategy template shown when creating a new strategy

**Strategy base class contract:**

```python
from platform.base import BaseStrategy, SetupSignal, Candle, Indicators

class MyStrategy(BaseStrategy):
    name = "My Strategy Name"
    description = "What this strategy looks for"
    timeframes = ["1h", "4h"]  # timeframes this strategy operates on

    def scan(self, symbol: str, timeframe: str,
             candles: list[Candle], indicators: Indicators,
             sr_zones: list) -> SetupSignal | None:
        """
        Called on every candle close for each active timeframe.
        Return a SetupSignal if a setup is detected, or None.
        """
        pass

    # --- Optional overrides ---

    def calculate_sl(self, signal: SetupSignal, candles: list[Candle]) -> float:
        """Override default ATR-based SL calculation."""
        pass

    def calculate_tp(self, signal: SetupSignal, candles: list[Candle]) -> tuple[float, float]:
        """Override default TP1 and TP2 calculation. Returns (tp1, tp2)."""
        pass

    def should_confirm_with_llm(self, signal: SetupSignal) -> bool:
        """Override to skip LLM confirmation for this strategy. Default: True."""
        return True
```

**SetupSignal object:**

```python
SetupSignal(
    direction="LONG",        # or "SHORT"
    confidence=0.75,         # 0.0 to 1.0
    entry=None,              # optional — platform calculates if None
    notes="Price rejected off $3,180 support with pin bar"  # optional context for LLM
)
```

**Hot-reload behavior:**
- On save, the strategy file is validated (syntax check, base class check)
- If valid: loaded immediately into the strategy registry, available for selection in analysis sessions and backtester
- If invalid: error shown in the editor, previous version (if any) remains active
- Custom strategies persist in the database across backend restarts (browser session reset does not affect saved strategies)

---

### 5.4 Historical Data Page

**Import options:**

**Option A — Binance API fetch:**
- Symbol input (BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, or custom)
- Timeframe selector
- Date range picker
- Fetch button — pulls paginated OHLCV from Binance REST API
- Progress bar for large date ranges
- Data source label: "Binance" (modular — Delta Exchange and others can be added)

**Option B — CSV upload:**
- Drag-and-drop or file picker
- Expected column format (Binance standard export):

```
open_time | open | high | low | close | volume | close_time |
quote_volume | count | taker_buy_volume | taker_buy_quote_volume | ignore
```

- On upload: validate all required columns are present and correctly typed
- If malformed: reject with a clear error message specifying exactly what is wrong (missing columns, wrong types, unparseable dates, etc.)
- If valid: show a preview of first 10 rows, symbol + timeframe selector, confirm import button
- Duplicate handling: if data for that symbol/timeframe/date range already exists, ask user whether to overwrite or skip

**Data management table:**
- Lists all stored historical datasets
- Columns: Symbol, Timeframe, From, To, Rows, Source, Imported at
- Delete button per dataset
- Re-fetch button (re-pulls from source to update)

---

## 6. Signal Pipeline — Full Detail

### Stage 1: Market scan (continuous, per candle close)

- On every candle close for each active analysis session, the engine runs all selected strategies against the latest candles + indicators for that symbol/timeframe
- Indicators computed before strategies run: EMA 9, EMA 21, EMA 50, EMA 200, RSI 14, MACD (12/26/9), Bollinger Bands (20/2), ATR 14, volume MA
- S/R zones are pre-computed and cached, refreshed every 4h candle close

### Stage 2: Setup detected → Watching card

- A strategy's `scan()` returns a `SetupSignal`
- Platform records the setup: symbol, timeframe, direction, condition, strategy names, timestamp
- A watching card appears in the UI (Signal Feed → Watching tab)
- Watching card is NOT sent to Telegram
- If the condition is not met within a configurable expiry window (default: 3 candle closes on the signal's timeframe), the watching card is marked EXPIRED and removed from the active feed

### Stage 3: Condition met → Candidate signal

- On each candle close, the engine checks all watching setups: has the trigger condition been met?
- Trigger conditions are defined per strategy (e.g. "bearish engulfing closed below the zone")
- If met: a full candidate signal is assembled with entry, SL (ATR-based default or strategy override), TP1, TP2

### Stage 4: LLM confirmation

**Context sent to LLM:**
- Symbol, timeframe, direction
- Last 30 candles (OHLCV) for the signal's timeframe
- Last 10 candles for the next higher timeframe (trend bias)
- Current indicator values (RSI, MACD, EMA positions, volume vs MA)
- Identified S/R zones within 3% of current price
- The candidate signal JSON (entry, SL, TP1, TP2)
- Strategy names and the notes field from SetupSignal
- Instruction: return JSON with `verdict` (CONFIRM / REJECT / MODIFY), `reasoning` (2–3 sentences plain English), and optionally `modified_sl`, `modified_tp1`, `modified_tp2` if verdict is MODIFY

**LLM settings:**
- Endpoint: `http://localhost:1234/v1/chat/completions`
- Temperature: 0.2 (deterministic)
- Recommended models: Mistral 7B Instruct, Llama 3 8B Instruct, Qwen 2.5 7B
- Timeout: 30 seconds. If LM Studio is unreachable, signal is queued as PENDING and retried every 60 seconds

**LLM response handling:**
- CONFIRM: signal proceeds to publication
- REJECT: signal is dropped, watching card marked REJECTED, reason stored
- MODIFY: signal levels are updated with LLM-suggested values, then published

### Stage 5: Signal publication

- Confirmed signal card appears in UI (Signal Feed → Confirmed tab)
- Telegram message sent immediately
- Signal stored in database with full context for historical review

---

## 7. Telegram Integration

**Setup:**
- Telegram Bot Token (stored in `.env`)
- Chat ID (your personal chat or a private channel)
- Configurable in a settings panel (no code change required)

**Message format:**

```
🟢 CONFIRMED SIGNAL         (🔴 for SHORT)

Pair      : ETHUSDT
Direction : LONG
Timeframe : 4h
Entry     : $3,240.00
SL        : $3,180.00
TP1       : $3,310.00
TP2       : $3,420.00
R/R       : 1 : 2.3
Strategy  : S/R Zone + EMA Crossover
Confidence: 78%

Analysis  : Strong bullish structure on 4h
with clean bounce off $3,180 support.
Volume confirms. Bias aligns with 1D trend.

⏱ 14 Jan 2025  10:32 UTC
```

**Signal outcome updates (optional):**
- When the platform detects price hitting TP1, TP2, or SL (via live price feed), send a follow-up Telegram message:
  - "✅ ETHUSDT LONG — TP1 hit at $3,310"
  - "❌ ETHUSDT LONG — SL hit at $3,180"

---

## 8. Built-in Strategies (shipped with platform)

All built-in strategies follow the same `BaseStrategy` contract and are available immediately without the IDE.

| Strategy | Mode | Timeframes | Description |
|---|---|---|---|
| EMA Crossover | Reactive | 15m, 1h, 4h | EMA 9 crosses EMA 21 with EMA 50 trend filter |
| RSI Reversal | Reactive | 1h, 4h | RSI < 30 or > 70 with trend alignment |
| Bollinger Band Squeeze | Reactive | 1h, 4h | Price breaks out of bands after low-volatility squeeze |
| MACD Momentum | Reactive | 1h, 4h, 1D | MACD/signal cross with histogram confirmation |
| S/R Zone Rejection | Conditional | 4h, 1D | Price approaches key zone, waits for rejection candle |
| S/R Zone Breakout | Conditional | 1h, 4h | Price breaks and retests a key zone |

More strategies (BoS, CHoCH, Order Blocks, Fair Value Gaps, etc.) can be added at any time via the IDE or as future built-in additions.

---

## 9. S/R Zone Detection Engine

This is a core platform component, not a user-facing strategy. It runs in the background and feeds zone data to all strategies.

**Detection methods:**
- Swing high / swing low detection (configurable lookback period)
- Round number levels (psychological levels — $3,000, $3,500, etc.)
- Previous day / week high and low
- High-volume node detection (where price has spent significant time)

**Zone properties:**
- Price level (center of zone)
- Zone width (ATR-based tolerance band)
- Strength score (how many times price has respected this level)
- Type (support / resistance / both)
- Timeframe origin (1D zone vs 4h zone — higher timeframe zones have more weight)
- Last tested timestamp

**Zone refresh:**
- Full recalculation on every 4h candle close
- Minor update (add new swing points) on every 1h candle close

---

## 10. Database Schema (overview)

```
candles          — OHLCV data (symbol, timeframe, open_time, open, high, low, close, volume)
sr_zones         — detected S/R zones with strength scores
watching_setups  — active watching cards (symbol, timeframe, strategy, condition, expiry)
signals          — all confirmed signals with full context and outcome
strategies       — registered strategies (name, code, type: builtin/custom, enabled)
backtest_runs    — backtest configurations and summary results
backtest_trades  — individual trade records per backtest run
settings         — platform config (Telegram token, chat ID, LLM endpoint, etc.)
```

`candles` uses TimescaleDB hypertable partitioned by `open_time` for fast time-range queries.

---

## 11. Build Phases

### Phase 1 — Project foundation & data layer

**Goal:** Backend and frontend scaffolded, historical data importable, candle data queryable.

- Flask project structure with blueprints (data, strategies, signals, backtest, settings)
- PostgreSQL + TimescaleDB setup (Docker: `timescale/timescaledb:latest-pg15`)
- Candles table + hypertable setup
- Binance REST API integration — fetch and store OHLCV for all symbols and timeframes
- CSV import endpoint — validate Binance export format, parse, store
- Historical data page UI — Binance fetch form + CSV upload with validation + data management table
- Basic React scaffold (Vite + TypeScript, React Router, layout shell)

**Deliverable:** Historical data can be imported from both Binance API and CSV. Data is stored and queryable.

---

### Phase 2 — Indicator engine & S/R zone detection

**Goal:** All indicators computed on stored candles. S/R zones detected and stored.

- Indicator computation service: EMA 9/21/50/200, RSI 14, MACD, Bollinger Bands, ATR 14, volume MA
- Indicators computed and cached on candle close (not recomputed on every request)
- S/R zone detection engine: swing high/low, round numbers, previous day/week H/L
- Zone strength scoring and timeframe weighting
- Zone refresh scheduler (every 4h close)
- API endpoints: `/api/indicators`, `/api/sr-zones`

**Deliverable:** For any symbol/timeframe, indicators and S/R zones are available via API.

---

### Phase 3 — Strategy engine & BaseStrategy contract

**Goal:** Strategy system built. Built-in strategies implemented. Strategies produce SetupSignal objects.

- `BaseStrategy` abstract class with full contract (scan, calculate_sl, calculate_tp, should_confirm_with_llm)
- `SetupSignal` and `Candle` data classes
- Strategy registry — loads and tracks all available strategies
- All 6 built-in strategies implemented and tested against historical data
- Strategy selector API (enable/disable per analysis session)
- Unit tests for each built-in strategy against known historical setups

**Deliverable:** Built-in strategies run against historical data and produce correct SetupSignal objects.

---

### Phase 4 — Live analysis engine & watching cards

**Goal:** Live market scanning running. Watching cards appearing in the UI.

- Binance WebSocket integration — live price and candle stream for all 4 symbols
- Candle-close event system — triggers strategy scan at close of each candle
- Analysis session management — start/stop sessions, up to 2 simultaneously, reset on browser close
- Watching setup lifecycle manager — creates, monitors, expires watching setups
- Server-Sent Events (SSE) endpoint — pushes watching card updates to frontend in real time
- Signal Feed page UI — two tabs (Watching / Confirmed), analysis session panel, watching cards with mini chart

**Deliverable:** Start an analysis session in the UI, watch cards appear as setups are identified live.

---

### Phase 5 — LLM confirmation pipeline & confirmed signals

**Goal:** Candidate signals flow through LLM, confirmed signals appear in UI.

- LM Studio HTTP client (`http://localhost:1234/v1/chat/completions`)
- Context builder — assembles candle history, indicators, S/R zones, signal JSON into structured prompt
- Prompt template — deterministic, instructs LLM to return structured JSON verdict
- LLM response parser — extracts verdict, reasoning, optional modified levels
- Async confirmation queue — non-blocking, retries if LM Studio is unreachable
- Signal storage — confirmed signals saved to database with full context
- Confirmed signal cards in UI — LLM verdict badge, expandable reasoning, outcome tracking
- LM Studio connection status indicator in UI header

**Deliverable:** Candidate signals are reviewed by LLM. Confirmed signals appear on the Confirmed tab.

---

### Phase 6 — Telegram notifications

**Goal:** Confirmed signals and outcome updates sent to Telegram automatically.

- Telegram Bot API integration (python-telegram-bot library)
- Bot token + chat ID stored in `.env`, configurable via settings page
- Message formatter — produces the agreed signal format with emoji, levels, R/R, LLM reasoning
- Send on signal confirmation — fires immediately when LLM returns CONFIRM or MODIFY
- Outcome update messages — sends TP1/TP2 hit or SL hit follow-up when price level is reached
- Telegram delivery status tracked in database (sent / failed)
- Retry on failure (up to 3 attempts)

**Deliverable:** Confirmed signals arrive in Telegram automatically with correct formatting.

---

### Phase 7 — Backtesting engine

**Goal:** Any strategy can be backtested against historical data with full metrics and charts.

- Vectorized backtest runner (pandas-based — fast, not loop-based)
- Entry/SL/TP logic consistent with live engine (same ATR calculations, same zone detection)
- Metrics calculator: total trades, win rate, total PnL, Sharpe ratio, Sortino ratio, max drawdown, avg R/R, profit factor, avg trade duration, best/worst trade
- Equity curve data generation
- Per-trade log with all fields
- Trade chart data — entry/SL/TP levels per trade mapped to OHLCV timestamps
- Backtest API endpoint: `/api/backtest` — accepts symbol, timeframe, date range, strategies, capital, risk %
- Backtesting page UI:
  - Configuration panel
  - Summary metrics cards
  - Equity curve chart (Lightweight Charts)
  - Trade chart with all trades plotted (entry triangles, SL/TP lines, outcome colors)
  - Per-trade log table (sortable, CSV export)

**Deliverable:** Full backtest with visual results for any strategy/symbol/timeframe/date range.

---

### Phase 8 — Strategy IDE

**Goal:** Custom strategies can be written in the browser, saved, and hot-loaded into the live engine.

- Monaco Editor integration in React (same as VS Code)
- Strategy file management — create, edit, delete custom strategies
- Save → validate → hot-reload pipeline:
  - Syntax validation (Python AST parse)
  - Base class compliance check (has `scan()`, correct signature)
  - If valid: load into strategy registry immediately
  - If invalid: show inline error, do not load
- Custom strategies stored in database (survive backend restart)
- Built-in strategy template shown on "New Strategy" creation
- Platform classes and type hints available as autocomplete context
- Strategy IDE page UI — left panel (strategy list with toggles), right panel (Monaco editor)
- Custom strategies appear in analysis session selector and backtester immediately after save

**Deliverable:** Write a strategy in the browser, save it, use it in a live session or backtest without any backend restart.

---

### Phase 9 — Polish & hardening

**Goal:** Platform is reliable, informative, and pleasant to use daily.

- Settings page: Telegram bot token + chat ID, LLM endpoint URL, model name, default risk %, signal expiry window
- Error handling throughout: API failures, LM Studio offline, Binance WebSocket reconnection, malformed strategy code
- Signal outcome auto-tracker: monitors live price against all active confirmed signals, marks HIT_TP1 / HIT_TP2 / HIT_SL / EXPIRED
- Confirmed signal history — all past signals with outcomes, filterable by symbol/direction/strategy/outcome
- Performance summary on signal feed page: personal win rate on confirmed signals, total signals this week
- Dark mode UI (default)
- Loading states, empty states, and error states for all pages
- Environment setup documentation (`README.md` covering Docker, LM Studio, Telegram bot setup)

**Deliverable:** Platform is production-ready for daily personal use.

---

## 12. Project File Structure (planned)

```
crypto-signal-platform/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── blueprints/
│   │   │   ├── data.py          # historical data import/fetch
│   │   │   ├── signals.py       # signal feed, watching setups
│   │   │   ├── strategies.py    # strategy registry, IDE save/load
│   │   │   ├── backtest.py      # backtest runner
│   │   │   └── settings.py      # platform config
│   │   ├── core/
│   │   │   ├── base_strategy.py # BaseStrategy, SetupSignal, Candle
│   │   │   ├── indicators.py    # all indicator computations
│   │   │   ├── sr_engine.py     # S/R zone detection
│   │   │   ├── scanner.py       # live analysis session manager
│   │   │   ├── llm_client.py    # LM Studio integration
│   │   │   ├── telegram.py      # Telegram bot integration
│   │   │   └── strategy_loader.py # hot-reload engine
│   │   ├── strategies/
│   │   │   ├── ema_crossover.py
│   │   │   ├── rsi_reversal.py
│   │   │   ├── bollinger_squeeze.py
│   │   │   ├── macd_momentum.py
│   │   │   ├── sr_rejection.py
│   │   │   └── sr_breakout.py
│   │   ├── models/
│   │   │   └── db.py            # SQLAlchemy models
│   │   └── utils/
│   │       ├── binance.py       # Binance REST + WebSocket client
│   │       └── csv_parser.py    # CSV import validator + parser
│   ├── migrations/
│   ├── tests/
│   ├── .env.example
│   ├── requirements.txt
│   └── run.py
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── SignalFeed/
│   │   │   ├── Backtest/
│   │   │   ├── StrategyIDE/
│   │   │   └── HistoricalData/
│   │   ├── components/
│   │   │   ├── WatchingCard/
│   │   │   ├── SignalCard/
│   │   │   ├── TradeChart/
│   │   │   ├── EquityCurve/
│   │   │   └── StrategyEditor/
│   │   ├── hooks/
│   │   ├── api/
│   │   └── types/
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml           # PostgreSQL + TimescaleDB
└── README.md
```

---

## 13. Environment & Setup Requirements

```env
# .env
DATABASE_URL=postgresql://user:password@localhost:5432/signals_db
BINANCE_API_KEY=               # optional — only needed for authenticated endpoints
BINANCE_API_SECRET=            # optional
LM_STUDIO_URL=http://localhost:1234
LM_STUDIO_MODEL=mistral-7b-instruct
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
SIGNAL_EXPIRY_CANDLES=3        # watching setup expires after N candle closes
DEFAULT_RISK_PERCENT=1.0       # default % of capital risked per trade
```

---

## 14. Key Design Decisions & Rationale

| Decision | Rationale |
|---|---|
| Binance as primary data source | Best API stability, free WebSocket, highest liquidity on target pairs |
| TimescaleDB over plain PostgreSQL | Native time-series partitioning, fast OHLCV range queries, standard SQL |
| SSE over WebSocket for UI updates | Simpler server-side, sufficient for signal push (low frequency) |
| Vectorized backtester (pandas) | 10–100x faster than loop-based, handles years of 5m data in seconds |
| Monaco Editor for IDE | Industry standard, Python syntax support, zero learning curve |
| LLM called once per candidate signal | Practical — keeps latency acceptable, avoids burning LM Studio on noise |
| Strategy hot-reload via registry | No backend restart needed, custom strategies survive as database records |
| Single-user, no auth | Local tool, no exposure — keeps the build lean |
| CSV import uses Binance export format | Most common source for manual historical data, well-documented columns |
| Delta Exchange as future modular addition | Same interface as Binance client, swappable via data source enum |

---

## 15. Iteration Protocol

Each phase follows this sequence before moving to the next:

1. **Design review** — agree on API contracts, data shapes, and component layout before writing code
2. **Backend implementation** — build and test with mock/historical data first
3. **Frontend integration** — connect React components to real endpoints
4. **End-to-end test** — verify the full flow works as expected
5. **Sign-off** — explicit confirmation before starting the next phase

---

*Status: Roadmap finalised. Ready to begin Phase 1.*