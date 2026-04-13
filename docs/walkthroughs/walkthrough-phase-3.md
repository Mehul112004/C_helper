# Phase 3: Strategy Engine — Walkthrough

## Summary

Implemented the complete strategy engine layer for the Crypto Signal Intelligence Platform. This phase builds on top of the Phase 1 data layer and Phase 2 indicator engine to provide a pluggable framework where strategies consume indicators and S/R zones to produce `SetupSignal` objects.

## Changes Made

### Core Framework (3 new files)

| File | Purpose |
|---|---|
| [base_strategy.py](file:///Users/artemis/Mehul/C_helper/backend/app/core/base_strategy.py) | `Candle`, `Indicators`, `SetupSignal` dataclasses + `BaseStrategy` abstract class |
| [strategy_loader.py](file:///Users/artemis/Mehul/C_helper/backend/app/core/strategy_loader.py) | `StrategyRegistry` — discovers, loads, and manages strategy lifecycle |
| [strategy_runner.py](file:///Users/artemis/Mehul/C_helper/backend/app/core/strategy_runner.py) | `StrategyRunner` — orchestrates scan execution with safety wrapping |

### Built-in Strategies (7 new files)

| Strategy | File | Mode | Timeframes |
|---|---|---|---|
| EMA Crossover | [ema_crossover.py](file:///Users/artemis/Mehul/C_helper/backend/app/strategies/ema_crossover.py) | Reactive | 15m, 1h, 4h |
| RSI Reversal | [rsi_reversal.py](file:///Users/artemis/Mehul/C_helper/backend/app/strategies/rsi_reversal.py) | Reactive | 1h, 4h |
| Bollinger Squeeze | [bollinger_squeeze.py](file:///Users/artemis/Mehul/C_helper/backend/app/strategies/bollinger_squeeze.py) | Reactive | 1h, 4h |
| MACD Momentum | [macd_momentum.py](file:///Users/artemis/Mehul/C_helper/backend/app/strategies/macd_momentum.py) | Reactive | 1h, 4h, 1D |
| S/R Zone Rejection | [sr_rejection.py](file:///Users/artemis/Mehul/C_helper/backend/app/strategies/sr_rejection.py) | Conditional | 4h, 1D |
| S/R Zone Breakout | [sr_breakout.py](file:///Users/artemis/Mehul/C_helper/backend/app/strategies/sr_breakout.py) | Conditional | 1h, 4h |

### API & Infrastructure (2 new files, 2 modified files)

| File | Change |
|---|---|
| [strategies_bp.py](file:///Users/artemis/Mehul/C_helper/backend/app/blueprints/strategies_bp.py) | New blueprint with 4 API endpoints |
| [db.py](file:///Users/artemis/Mehul/C_helper/backend/app/models/db.py) | Added `Strategy` model |
| [__init__.py](file:///Users/artemis/Mehul/C_helper/backend/app/__init__.py) | Registered blueprint + registry init on startup |

### Tests (4 new files, 85 tests)

| File | Tests | Coverage |
|---|---|---|
| [test_base_strategy.py](file:///Users/artemis/Mehul/C_helper/backend/tests/test_base_strategy.py) | 19 | Candle, Indicators, SetupSignal, BaseStrategy contract |
| [test_strategies.py](file:///Users/artemis/Mehul/C_helper/backend/tests/test_strategies.py) | 30 | All 6 strategies with positive/negative/edge cases |
| [test_strategy_runner.py](file:///Users/artemis/Mehul/C_helper/backend/tests/test_strategy_runner.py) | 10 | Default population, exception safety, historical scan |
| [test_strategy_loader.py](file:///Users/artemis/Mehul/C_helper/backend/tests/test_strategy_loader.py) | 13 | Registry discovery, enable/disable, min_confidence |

### Documentation (1 new file)

| File | Content |
|---|---|
| [strategy_engine.md](file:///Users/artemis/Mehul/C_helper/docs/logic/strategy_engine.md) | Full logic documentation for all components |

## Key Design Decisions

1. **Configurable confidence threshold** — `min_confidence` is a class attribute on `BaseStrategy` (default 0.5) that can also be overridden per-session via `StrategyRunner.run_single_scan(min_confidence_override=...)`.

2. **Stateless scan()** — Strategies' `scan()` methods receive all data they need as arguments. Previous-bar indicators are included in the `Indicators` dataclass (`prev_ema_9`, `prev_macd_line`, etc.), and `bb_width_history` provides a lookback window for squeeze detection.

3. **Exception safety** — `StrategyRunner.run_single_scan()` wraps each strategy in a try/except so a crashing strategy never takes down the engine.

4. **Auto-discovery** — The `StrategyRegistry` uses `importlib` to find strategies at startup. Adding a new strategy is as simple as dropping a `.py` file in `app/strategies/`.

## Test Results

```
============================= 131 passed in 0.37s ==============================
```

Full suite including Phase 2 regression tests — all passing.

## Phase 3 Transition Checklist

- [x] BaseStrategy classes correctly mandate scan() methods
- [x] 6 built-in strategies correctly parse indicators and identify proper setups
- [x] Output from strategy scans properly forms SetupSignal objects
- [x] Unit tests for built-in strategies pass on historical data
