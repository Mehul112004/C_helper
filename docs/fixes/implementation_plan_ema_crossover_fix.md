# Fix EMA Crossover Strategy Issues (V2)

This implementation plan details the steps required to resolve the 7 identified issues in the `ema_crossover.py` strategy, incorporating feedback to solidify the HTF checks, correctly establish SR zone entry-blocking, and rigorously handle Volume and TP conditions.

## User Review Required

> [!WARNING]
> **Signature Changes across all strategies:**
> Passing `htf_candles` into `scan()` and `sr_zones` into `calculate_tp()` requires updating the method signatures in `BaseStrategy`. To prevent Python `TypeError` exceptions from mismatched arguments, I will also need to update the method signatures of **all other strategy files** (12 other files) to accept these optional arguments, even if they don't actively use them yet. 

## Proposed Changes

### Core Infrastructure
Changes required to support `htf_candles` passing and S/R zone injection for Take-Profit calculations.

#### [MODIFY] [base_strategy.py](file:///Users/artemis/Mehul/C_helper/backend/app/core/base_strategy.py)
- Update `BaseStrategy.scan` signature to include `htf_candles: list[Candle] = None`.
- Update `BaseStrategy.calculate_tp` signature to include `sr_zones: list[dict] = None` and remove the default calculation proxy logic for non-supplied zones.
- Update `Indicators` class to track the last 5 periods of `ema_21` by introducing `ema_21_history = field(default_factory=list)`. This is required to calculate meaningful EMA slope over multiple bars.
- Update `Indicators.from_series()` to properly extract the last 5 `ema_21` snapshots into the new list.

#### [MODIFY] [strategy_runner.py](file:///Users/artemis/Mehul/C_helper/backend/app/core/strategy_runner.py)
- Update `run_single_scan` signature to accept `htf_candles=None` as a parameter.
- Pass `htf_candles=htf_candles` into the `strategy.scan()` call.
- Pass `sr_zones=sr_zones` strictly into the `strategy.calculate_tp()` call (i.e. `strategy.calculate_tp(signal, candles, atr, sr_zones=sr_zones)`) since the current runtime only handles the first 3 positional arguments.

#### [MODIFY] [scanner.py](file:///Users/artemis/Mehul/C_helper/backend/app/core/scanner.py)
- In `_on_candle_close`, invoke `self._fetch_htf_candles(symbol, timeframe)` *before* the strategy loop begins.
- Pass the fetched `htf_candles` directly into the `StrategyRunner.run_single_scan()` invocation. Ensure `sr_zones` remains in the passed parameters and propagates through accurately.

---

### Strategy Modifications
Implementing the 7 specific bug fixes to the EMA strategy.

#### [MODIFY] [ema_crossover.py](file:///Users/artemis/Mehul/C_helper/backend/app/strategies/ema_crossover.py)
- Update `scan` and `calculate_tp` method signatures to match the new abstract base class.
- **ISSUE-EMA-1 (HTF Regime & Flat EMA Check)**:
  - **HTF Consistency:** If `htf_candles` are present, ensure that at least 2 of the last 3 HTF candles closed consecutively in sync with the trend (e.g. `c[-1].is_bullish and c[-2].is_bullish` or `c[-2].is_bullish and c[-3].is_bullish` for a Long alignment). This confirms the trend while forgiving a single brief pullback wick.
  - **MACRO Convergence:** If `(ema_9 - ema_21) / close` represents a microscopic band (e.g., `< 0.0005`), or if the difference between `ema_21` locally and `indicators.ema_21_history[0]` indicates practically flatlining momentum, reject the signal. *Note on indexing*: `from_series()` populates `_history` fields sequentially from oldest to newest (like `bb_width_history`), meaning `[0]` is the oldest value (5 periods ago) and `[-1]` is the most recent, ensuring the slope calculation `ema_21 - ema_21_history[0]` correctly reflects the 5-bar delta.
- **ISSUE-EMA-2 (Volume Gate)**: 
  - Overhaul logic from a `+0.10` confidence modifier to a harsh constraint. 
  - Fail-closed mechanic: `if indicators.volume_ma_20 is None or candles[-1].volume < indicators.volume_ma_20: return None`.
- **ISSUE-EMA-3 (S/R Zone Refusal)**: 
  - In `scan()`, build a proxy logic map (simulated tp1 value leveraging 1.5R structure) before producing the trade. 
  - Iterate `sr_zones`. Reject if `zone_lower < tp1_proxy` and `zone_upper > entry` with a blocking `zone_type` (`both` or `resistance`/`support`). A separate explicit rule will check if we hit an unyielding block.
- **ISSUE-EMA-4 (Stop Loss Window)**: 
  - Change `candles[-3:]` to `candles[-4:-1]` in `calculate_sl` calculation (exempts the crossover candle). 
  - Enforce a specific ATR bumper increment logic utilizing `0.3 * atr`.
- **ISSUE-EMA-5 (Falsy Checking)**:
  - Resolves standard python falsy bug inside `calculate_tp` by forcing robust None checks: `entry = signal.entry if signal.entry is not None else candles[-1].close`.
- **ISSUE-EMA-6 (S/R Aware TP1)**:
  - Inside `calculate_tp`, after finalizing standard 1.5R geometry rules as `raw_tp1`, iterate `sr_zones`.
  - Check pathing: If a dense blocking zone sits firmly between Entry and `raw_tp1`, readjust TP1 safely.
- **ISSUE-EMA-7 (Equal EMA Issue)**:
  - Restructure entry parsing rules utilizing boolean `prev_below` / `prev_above` conditions (e.g., `prev_below = indicators.prev_ema_9 < indicators.prev_ema_21`) validating crossing geometry correctly.

---

### Other Strategy Interfaces

#### [MODIFY] All 12 Other Strategies
- Update the signatures in `scan` and `calculate_tp` to accept the new kwargs (`htf_candles: list[Candle] = None` and `sr_zones: list[dict] = None`) to prevent `TypeError` failures during runtime loops. They will initially ignore these additions.

## Verification Plan

- Backtesting and manual verification will monitor logs targeting `ema_crossover.py` against standard execution rules ensuring:
  1. Spits out `None` consistently if HTF history triggers failures.
  2. Spits out `None` if volume gates remain breached.
