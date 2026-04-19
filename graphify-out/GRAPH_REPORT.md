# Graph Report - .  (2026-04-19)

## Corpus Check
- 124 files · ~76,855 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1285 nodes · 3946 edges · 69 communities detected
- Extraction: 36% EXTRACTED · 64% INFERRED · 0% AMBIGUOUS · INFERRED: 2523 edges (avg confidence: 0.56)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Strategy Implementations|Strategy Implementations]]
- [[_COMMUNITY_SR Engine & Scheduling|S/R Engine & Scheduling]]
- [[_COMMUNITY_BaseStrategy Contract|BaseStrategy Contract]]
- [[_COMMUNITY_Signals & Notifications|Signals & Notifications]]
- [[_COMMUNITY_Indicators & Backtesting|Indicators & Backtesting]]
- [[_COMMUNITY_Strategy Registry & Loader|Strategy Registry & Loader]]
- [[_COMMUNITY_Data Ingestion & Binance|Data Ingestion & Binance]]
- [[_COMMUNITY_SSE PubSub System|SSE Pub/Sub System]]
- [[_COMMUNITY_Docs & Fix Plans|Docs & Fix Plans]]
- [[_COMMUNITY_LLM Client & Providers|LLM Client & Providers]]
- [[_COMMUNITY_Frontend API Client|Frontend API Client]]
- [[_COMMUNITY_SMC & Fibonacci Strategies|SMC & Fibonacci Strategies]]
- [[_COMMUNITY_UI Config Panels|UI Config Panels]]
- [[_COMMUNITY_Trade Log Component|Trade Log Component]]
- [[_COMMUNITY_App Router & Layout|App Router & Layout]]
- [[_COMMUNITY_Signal Pipeline Concepts|Signal Pipeline Concepts]]
- [[_COMMUNITY_Data Import Endpoints|Data Import Endpoints]]
- [[_COMMUNITY_Watching Card UI|Watching Card UI]]
- [[_COMMUNITY_SLTP Calculation|SL/TP Calculation]]
- [[_COMMUNITY_Rejected Card UI|Rejected Card UI]]
- [[_COMMUNITY_Confirmed Card UI|Confirmed Card UI]]
- [[_COMMUNITY_LLM Queue & Signals|LLM Queue & Signals]]
- [[_COMMUNITY_LLM Provider Architecture|LLM Provider Architecture]]
- [[_COMMUNITY_Mini Chart Component|Mini Chart Component]]
- [[_COMMUNITY_Analysis Sessions Hook|Analysis Sessions Hook]]
- [[_COMMUNITY_SSE React Hook|SSE React Hook]]
- [[_COMMUNITY_Metrics Summary UI|Metrics Summary UI]]
- [[_COMMUNITY_Equity Curve Chart|Equity Curve Chart]]
- [[_COMMUNITY_Trade Chart Viz|Trade Chart Viz]]
- [[_COMMUNITY_Watching Tab UI|Watching Tab UI]]
- [[_COMMUNITY_Historical Data Page|Historical Data Page]]
- [[_COMMUNITY_Telegram Testing|Telegram Testing]]
- [[_COMMUNITY_DB Migration Script|DB Migration Script]]
- [[_COMMUNITY_App Configuration|App Configuration]]
- [[_COMMUNITY_Bug Fix Knowledge Base|Bug Fix Knowledge Base]]
- [[_COMMUNITY_Database Architecture|Database Architecture]]
- [[_COMMUNITY_ESLint Config|ESLint Config]]
- [[_COMMUNITY_Vite Build Config|Vite Build Config]]
- [[_COMMUNITY_Backtest Types|Backtest Types]]
- [[_COMMUNITY_Signal Types|Signal Types]]
- [[_COMMUNITY_Signal Feed Page|Signal Feed Page]]
- [[_COMMUNITY_Rejected Tab|Rejected Tab]]
- [[_COMMUNITY_Confirmed Tab|Confirmed Tab]]
- [[_COMMUNITY_Flask Entry Point|Flask Entry Point]]
- [[_COMMUNITY_Candle From Dict|Candle From Dict]]
- [[_COMMUNITY_Candle From DataFrame|Candle From DataFrame]]
- [[_COMMUNITY_Candle Body Size|Candle Body Size]]
- [[_COMMUNITY_Candle Range Size|Candle Range Size]]
- [[_COMMUNITY_Upper Wick Property|Upper Wick Property]]
- [[_COMMUNITY_Lower Wick Property|Lower Wick Property]]
- [[_COMMUNITY_Bullish Check|Bullish Check]]
- [[_COMMUNITY_Bearish Check|Bearish Check]]
- [[_COMMUNITY_Indicators Snapshot|Indicators Snapshot]]
- [[_COMMUNITY_Strategy Scan Method|Strategy Scan Method]]
- [[_COMMUNITY_Backend Init|Backend Init]]
- [[_COMMUNITY_LLM Evaluate Prompt|LLM Evaluate Prompt]]
- [[_COMMUNITY_LLM Ping Status|LLM Ping Status]]
- [[_COMMUNITY_Providers Init|Providers Init]]
- [[_COMMUNITY_Stream Active Check|Stream Active Check]]
- [[_COMMUNITY_Platform Overview|Platform Overview]]
- [[_COMMUNITY_Tech Stack|Tech Stack]]
- [[_COMMUNITY_Symbols & Timeframes|Symbols & Timeframes]]
- [[_COMMUNITY_Design Rationale|Design Rationale]]
- [[_COMMUNITY_Default SLTP|Default SL/TP]]
- [[_COMMUNITY_Frontend Entry|Frontend Entry]]
- [[_COMMUNITY_Vite Logo|Vite Logo]]
- [[_COMMUNITY_React Logo|React Logo]]
- [[_COMMUNITY_UI Icons|UI Icons]]
- [[_COMMUNITY_Favicon|Favicon]]

## God Nodes (most connected - your core abstractions)
1. `SetupSignal` - 275 edges
2. `Candle` - 245 edges
3. `Indicators` - 233 edges
4. `BaseStrategy` - 185 edges
5. `IndicatorService` - 92 edges
6. `TrendPullbackConfluenceStrategy` - 84 edges
7. `FibonacciRetracementStrategy` - 84 edges
8. `SRRejectionStrategy` - 79 edges
9. `BollingerSqueezeStrategy` - 79 edges
10. `SRBreakoutStrategy` - 79 edges

## Surprising Connections (you probably didn't know these)
- `Get S/R Zones Endpoint` --conceptually_related_to--> `detect_zones()`  [INFERRED]
  docs/logic/api_endpoints.md → backend/app/core/sr_engine.py
- `Volume Profile Detection (Deferred)` --conceptually_related_to--> `detect_zones()`  [INFERRED]
  docs/backlog.md → backend/app/core/sr_engine.py
- `BacktestEngine (Vectorized)` --calls--> `compute_all()`  [INFERRED]
  docs/walkthroughs/walkthrough-phase-7.md → backend/app/core/indicators.py
- `detect_zones()` --calls--> `Swing Point Detection`  [EXTRACTED]
  backend/app/core/sr_engine.py → docs/logic/sr_engine.md
- `detect_zones()` --calls--> `Round Number Detection`  [EXTRACTED]
  backend/app/core/sr_engine.py → docs/logic/sr_engine.md

## Hyperedges (group relationships)
- **End-to-End Signal Pipeline** — live_analysis_candle_close_flow, strategy_engine_runner, llm_queue_manager, confirmed_signal_model, readme_telegram_integration [EXTRACTED 0.90]
- **Built-in Trading Strategies** — strategy_engine_ema_crossover, strategy_engine_rsi_reversal, strategy_engine_bollinger_squeeze, strategy_engine_macd_momentum, strategy_engine_sr_rejection, strategy_engine_sr_breakout [EXTRACTED 1.00]
- **9-Phase Build Sequence** — phase1_foundation, phase2_indicators, phase3_strategy, phase4_live_analysis, phase5_llm_confirmation, phase6_telegram, phase7_backtesting, phase8_strategy_ide, phase9_polish [EXTRACTED 1.00]

## Communities

### Community 0 - "Strategy Implementations"
Cohesion: 0.02
Nodes (157): BaseStrategy, Candle, from_df_row(), from_series(), Indicators, Immutable representation of a single OHLCV candle bar., Universal output of every strategy's scan() method.     This object flows throug, Serialize to a JSON-safe dictionary. (+149 more)

### Community 1 - "S/R Engine & Scheduling"
Cohesion: 0.02
Nodes (165): Get S/R Zones Endpoint, Volume Profile Detection (Deferred), backtest_history(), export_backtest_csv(), get_backtest_run(), Backtest API Blueprint Endpoints for running backtests, fetching history, and ex, List past backtest runs, most recent first., Fetch full results for a specific backtest run, including all trades. (+157 more)

### Community 2 - "BaseStrategy Contract"
Cohesion: 0.08
Nodes (81): BaseStrategy, BollingerSqueezeStrategy, EMACrossoverStrategy, FibonacciRetracementStrategy, MACDMomentumStrategy, RSIReversalStrategy, SRBreakoutStrategy, SRRejectionStrategy (+73 more)

### Community 3 - "Signals & Notifications"
Cohesion: 0.03
Nodes (81): ping_status(), ConfirmedSignal, LLMPromptLog, Tracks detected trade setups that are being monitored (watching cards).     Crea, Final trade signals that have passed the LLM confirmation pipeline.     Displaye, Trade signals that were rejected by the LLM confirmation pipeline., Logs every interaction with the LLM.      Loose coupling referencing 'watching_s, RejectedSignal (+73 more)

### Community 4 - "Indicators & Backtesting"
Cohesion: 0.03
Nodes (63): Get Indicators Endpoint, build_equity_curve(), compute_indicators_from_df(), compute_metrics(), run(), simulate_trades(), get_indicators(), invalidate_cache() (+55 more)

### Community 5 - "Strategy Registry & Loader"
Cohesion: 0.04
Nodes (49): run_backtest(), Strategy, create_app(), get_git_commit_id(), run_backtests(), _strip_tz(), sync_data_for_timeframe(), init_scheduler() (+41 more)

### Community 6 - "Data Ingestion & Binance"
Cohesion: 0.06
Nodes (30): BinanceStreamManager, fetch_klines(), Build the combined stream URL for all symbol/timeframe pairs., Handle incoming WebSocket messages., Handle WebSocket errors., Handle WebSocket close — attempt reconnection if still running., Handle successful WebSocket connection., Create and run a new WebSocket connection. (+22 more)

### Community 7 - "SSE Pub/Sub System"
Cohesion: 0.1
Nodes (21): SSE (Server-Sent Events) Manager Thread-safe pub/sub for pushing real-time event, Thread-safe pub/sub manager for Server-Sent Events.      Multiple frontend clien, Create a new subscriber queue and register it.          Returns:             A q, Remove a subscriber queue. Called when SSE connection closes.          Args:, Publish an event to all active subscribers.          Events that cannot be deliv, Return the current number of active subscribers., Send a keepalive (None) to all subscribers.         Used by the SSE endpoint whe, SSEManager (+13 more)

### Community 8 - "Docs & Fix Plans"
Cohesion: 0.05
Nodes (43): BacktestEngine (Vectorized), HTF Regime & Flat EMA Check, EMA Crossover Fix Plan V2, EMA S/R Zone Refusal Fix, EMA Volume Gate Fix, React Frontend (Vite + TypeScript), Hero Image Asset, Candle Close Data Flow (+35 more)

### Community 9 - "LLM Client & Providers"
Cohesion: 0.06
Nodes (20): ABC, BaseLLMProvider, evaluate_prompt(), Abstract base class for all LLM providers., from_db_row(), Base Strategy Contract & Core Data Classes Defines the universal data structures, BaseLLMProvider, get_llm_provider() (+12 more)

### Community 10 - "Frontend API Client"
Cohesion: 0.06
Nodes (10): handleRunBacktest(), handleSubmit(), fetchDatasets(), fetchLLMLogs(), importBinanceData(), importCsvData(), runBacktest(), handleSubmit() (+2 more)

### Community 11 - "SMC & Fibonacci Strategies"
Cohesion: 0.14
Nodes (9): _compute_fib_level(), _has_sr_confluence(), build_swing_map(), find_fractal_points(), Fractal and swing detection utilities. Shared across multiple strategy modules (, Build an ordered list of swing points using fractal pivot detection.          Re, Find fractal highs and lows in a list of candles.          A fractal high exists, find_strongest_unbroken_fractal() (+1 more)

### Community 12 - "UI Config Panels"
Cohesion: 0.31
Nodes (5): selectAll(), toggleStrategy(), handleStart(), setSelectedStrategies(), toggleStrategy()

### Community 13 - "Trade Log Component"
Cohesion: 0.33
Nodes (0): 

### Community 14 - "App Router & Layout"
Cohesion: 0.4
Nodes (0): 

### Community 15 - "Signal Pipeline Concepts"
Cohesion: 0.4
Nodes (5): Built-in Strategies Overview, LLM as Final Judge Philosophy, Signal Pipeline, S/R Zone Detection Engine Overview, Telegram Integration

### Community 16 - "Data Import Endpoints"
Cohesion: 0.4
Nodes (5): Import Binance Endpoint, Import CSV Endpoint, CSV Parser, Binance Kline Fetcher, Historical Data Page

### Community 17 - "Watching Card UI"
Cohesion: 0.5
Nodes (0): 

### Community 18 - "SL/TP Calculation"
Cohesion: 0.5
Nodes (2): Override to customize stop-loss calculation.         Default: Structural SL behi, Override to customize take-profit calculation.         Default: Risk-based TP at

### Community 19 - "Rejected Card UI"
Cohesion: 0.67
Nodes (0): 

### Community 20 - "Confirmed Card UI"
Cohesion: 0.67
Nodes (0): 

### Community 21 - "LLM Queue & Signals"
Cohesion: 0.67
Nodes (3): ConfirmedSignal DB Model, Modular LLM Provider System, LLM Queue Manager

### Community 22 - "LLM Provider Architecture"
Cohesion: 0.67
Nodes (3): BaseLLMProvider Abstract Class, LLM Provider Factory, OpenAI Compatible Provider

### Community 23 - "Mini Chart Component"
Cohesion: 1.0
Nodes (0): 

### Community 24 - "Analysis Sessions Hook"
Cohesion: 1.0
Nodes (0): 

### Community 25 - "SSE React Hook"
Cohesion: 1.0
Nodes (0): 

### Community 26 - "Metrics Summary UI"
Cohesion: 1.0
Nodes (0): 

### Community 27 - "Equity Curve Chart"
Cohesion: 1.0
Nodes (0): 

### Community 28 - "Trade Chart Viz"
Cohesion: 1.0
Nodes (0): 

### Community 29 - "Watching Tab UI"
Cohesion: 1.0
Nodes (0): 

### Community 30 - "Historical Data Page"
Cohesion: 1.0
Nodes (0): 

### Community 31 - "Telegram Testing"
Cohesion: 1.0
Nodes (1): Standalone Telegram test — bypasses the entire app to isolate credential issues.

### Community 32 - "DB Migration Script"
Cohesion: 1.0
Nodes (1): Standalone migration script — connects directly to PostgreSQL without going thro

### Community 33 - "App Configuration"
Cohesion: 1.0
Nodes (1): Core Application Configuration Shared configuration constants used across module

### Community 34 - "Bug Fix Knowledge Base"
Cohesion: 1.0
Nodes (2): Fixed Bugs Registry, Strategies Fixes Knowledge Base

### Community 35 - "Database Architecture"
Cohesion: 1.0
Nodes (2): Database Schema Overview, TimescaleDB Rationale

### Community 36 - "ESLint Config"
Cohesion: 1.0
Nodes (0): 

### Community 37 - "Vite Build Config"
Cohesion: 1.0
Nodes (0): 

### Community 38 - "Backtest Types"
Cohesion: 1.0
Nodes (0): 

### Community 39 - "Signal Types"
Cohesion: 1.0
Nodes (0): 

### Community 40 - "Signal Feed Page"
Cohesion: 1.0
Nodes (0): 

### Community 41 - "Rejected Tab"
Cohesion: 1.0
Nodes (0): 

### Community 42 - "Confirmed Tab"
Cohesion: 1.0
Nodes (0): 

### Community 43 - "Flask Entry Point"
Cohesion: 1.0
Nodes (0): 

### Community 44 - "Candle From Dict"
Cohesion: 1.0
Nodes (1): Create a Candle from a Candle.to_dict() result.

### Community 45 - "Candle From DataFrame"
Cohesion: 1.0
Nodes (1): Create a Candle from a pandas DataFrame row.

### Community 46 - "Candle Body Size"
Cohesion: 1.0
Nodes (1): Absolute size of the candle body (|close - open|).

### Community 47 - "Candle Range Size"
Cohesion: 1.0
Nodes (1): Total range of the candle (high - low).

### Community 48 - "Upper Wick Property"
Cohesion: 1.0
Nodes (1): Size of the upper wick.

### Community 49 - "Lower Wick Property"
Cohesion: 1.0
Nodes (1): Size of the lower wick.

### Community 50 - "Bullish Check"
Cohesion: 1.0
Nodes (1): True if close > open.

### Community 51 - "Bearish Check"
Cohesion: 1.0
Nodes (1): True if close < open.

### Community 52 - "Indicators Snapshot"
Cohesion: 1.0
Nodes (1): Build an Indicators snapshot from full indicator series at position idx.

### Community 53 - "Strategy Scan Method"
Cohesion: 1.0
Nodes (1): Called on every candle close for each active timeframe.         Return a SetupSi

### Community 54 - "Backend Init"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "LLM Evaluate Prompt"
Cohesion: 1.0
Nodes (1): Sends the prompt to the LLM backend.                  Args:             system_p

### Community 56 - "LLM Ping Status"
Cohesion: 1.0
Nodes (1): Pings the provider to check if the service is reachable.                  Return

### Community 57 - "Providers Init"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "Stream Active Check"
Cohesion: 1.0
Nodes (1): Check if the stream is currently active.

### Community 59 - "Platform Overview"
Cohesion: 1.0
Nodes (1): Crypto Signal Intelligence Platform

### Community 60 - "Tech Stack"
Cohesion: 1.0
Nodes (1): Tech Stack

### Community 61 - "Symbols & Timeframes"
Cohesion: 1.0
Nodes (1): Target Symbols & Timeframes

### Community 62 - "Design Rationale"
Cohesion: 1.0
Nodes (1): Key Design Decisions & Rationale

### Community 63 - "Default SL/TP"
Cohesion: 1.0
Nodes (1): Default SL/TP Formulas

### Community 64 - "Frontend Entry"
Cohesion: 1.0
Nodes (1): Frontend Entry HTML

### Community 65 - "Vite Logo"
Cohesion: 1.0
Nodes (1): Vite Logo Asset

### Community 66 - "React Logo"
Cohesion: 1.0
Nodes (1): React Logo Asset

### Community 67 - "UI Icons"
Cohesion: 1.0
Nodes (1): UI Icons SVG Sprite

### Community 68 - "Favicon"
Cohesion: 1.0
Nodes (1): Favicon

## Knowledge Gaps
- **132 isolated node(s):** `Standalone Telegram test — bypasses the entire app to isolate credential issues.`, `Standalone migration script — connects directly to PostgreSQL without going thro`, `Strategies API Blueprint Endpoints:   GET    /api/strategies              — List`, `List all registered strategies with their current enabled state and metadata.`, `Get full details for a single strategy.      Args:         name: Strategy name (` (+127 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Mini Chart Component`** (2 nodes): `MiniChart.tsx`, `MiniChart()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Analysis Sessions Hook`** (2 nodes): `useAnalysisSessions.ts`, `useAnalysisSessions()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `SSE React Hook`** (2 nodes): `useSSE.ts`, `useSSE()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Metrics Summary UI`** (2 nodes): `MetricsSummary.tsx`, `formatDuration()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Equity Curve Chart`** (2 nodes): `EquityCurve()`, `EquityCurve.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Trade Chart Viz`** (2 nodes): `TradeChart.tsx`, `buildChart()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Watching Tab UI`** (2 nodes): `WatchingTab.tsx`, `WatchingTab()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Historical Data Page`** (2 nodes): `HistoricalData.tsx`, `HistoricalData()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Telegram Testing`** (2 nodes): `test_telegram.py`, `Standalone Telegram test — bypasses the entire app to isolate credential issues.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `DB Migration Script`** (2 nodes): `fix_db.py`, `Standalone migration script — connects directly to PostgreSQL without going thro`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `App Configuration`** (2 nodes): `config.py`, `Core Application Configuration Shared configuration constants used across module`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bug Fix Knowledge Base`** (2 nodes): `Fixed Bugs Registry`, `Strategies Fixes Knowledge Base`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Database Architecture`** (2 nodes): `Database Schema Overview`, `TimescaleDB Rationale`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `ESLint Config`** (1 nodes): `eslint.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Vite Build Config`** (1 nodes): `vite.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Backtest Types`** (1 nodes): `backtest.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Signal Types`** (1 nodes): `signals.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Signal Feed Page`** (1 nodes): `SignalFeed.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Rejected Tab`** (1 nodes): `RejectedTab.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Confirmed Tab`** (1 nodes): `ConfirmedTab.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Flask Entry Point`** (1 nodes): `run.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Candle From Dict`** (1 nodes): `Create a Candle from a Candle.to_dict() result.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Candle From DataFrame`** (1 nodes): `Create a Candle from a pandas DataFrame row.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Candle Body Size`** (1 nodes): `Absolute size of the candle body (|close - open|).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Candle Range Size`** (1 nodes): `Total range of the candle (high - low).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Upper Wick Property`** (1 nodes): `Size of the upper wick.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Lower Wick Property`** (1 nodes): `Size of the lower wick.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bullish Check`** (1 nodes): `True if close > open.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bearish Check`** (1 nodes): `True if close < open.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Indicators Snapshot`** (1 nodes): `Build an Indicators snapshot from full indicator series at position idx.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Strategy Scan Method`** (1 nodes): `Called on every candle close for each active timeframe.         Return a SetupSi`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Backend Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `LLM Evaluate Prompt`** (1 nodes): `Sends the prompt to the LLM backend.                  Args:             system_p`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `LLM Ping Status`** (1 nodes): `Pings the provider to check if the service is reachable.                  Return`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Providers Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Stream Active Check`** (1 nodes): `Check if the stream is currently active.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Platform Overview`** (1 nodes): `Crypto Signal Intelligence Platform`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Tech Stack`** (1 nodes): `Tech Stack`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Symbols & Timeframes`** (1 nodes): `Target Symbols & Timeframes`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Design Rationale`** (1 nodes): `Key Design Decisions & Rationale`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Default SL/TP`** (1 nodes): `Default SL/TP Formulas`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Frontend Entry`** (1 nodes): `Frontend Entry HTML`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Vite Logo`** (1 nodes): `Vite Logo Asset`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `React Logo`** (1 nodes): `React Logo Asset`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `UI Icons`** (1 nodes): `UI Icons SVG Sprite`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Favicon`** (1 nodes): `Favicon`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SetupSignal` connect `Strategy Implementations` to `S/R Engine & Scheduling`, `BaseStrategy Contract`, `Signals & Notifications`, `Indicators & Backtesting`, `LLM Client & Providers`, `SMC & Fibonacci Strategies`?**
  _High betweenness centrality (0.195) - this node is a cross-community bridge._
- **Why does `Candle` connect `Strategy Implementations` to `S/R Engine & Scheduling`, `BaseStrategy Contract`, `Signals & Notifications`, `LLM Client & Providers`, `SMC & Fibonacci Strategies`?**
  _High betweenness centrality (0.153) - this node is a cross-community bridge._
- **Why does `BaseStrategy` connect `Strategy Implementations` to `S/R Engine & Scheduling`, `BaseStrategy Contract`, `Strategy Registry & Loader`, `LLM Client & Providers`, `SMC & Fibonacci Strategies`, `SL/TP Calculation`?**
  _High betweenness centrality (0.136) - this node is a cross-community bridge._
- **Are the 271 inferred relationships involving `SetupSignal` (e.g. with `LLMQueueManager` and `Background worker that processes SetupSignals through the LLM.     Prevents the`) actually correct?**
  _`SetupSignal` has 271 INFERRED edges - model-reasoned connections that need verification._
- **Are the 243 inferred relationships involving `Candle` (e.g. with `LLMQueueManager` and `Background worker that processes SetupSignals through the LLM.     Prevents the`) actually correct?**
  _`Candle` has 243 INFERRED edges - model-reasoned connections that need verification._
- **Are the 231 inferred relationships involving `Indicators` (e.g. with `LLMQueueManager` and `Background worker that processes SetupSignals through the LLM.     Prevents the`) actually correct?**
  _`Indicators` has 231 INFERRED edges - model-reasoned connections that need verification._
- **Are the 179 inferred relationships involving `BaseStrategy` (e.g. with `StrategyRunner` and `Strategy Runner Orchestrates running strategies against candle data and collecti`) actually correct?**
  _`BaseStrategy` has 179 INFERRED edges - model-reasoned connections that need verification._