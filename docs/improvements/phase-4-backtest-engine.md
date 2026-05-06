# Phase 4: Backtest Engine MTF Merge

**Goal**: Add lookahead-safe HTF data merging to the backtest engine so MTF strategies can be backtested without future data leakage.

**Risk**: **High** — this changes backtest result correctness. Old runs will not match new runs.  
**Depends on**: Phase 1

## Files Changed

| Action | File | What |
|--------|------|------|
| MODIFY | `backend/app/core/backtest_engine.py` | Add `merge_htf_context()`, update `run()` |
| MODIFY | `backend/app/core/strategy_runner.py` | Update `scan_historical()` for MTF walk |

## Step 4.1 — Add `merge_htf_context()` Static Method

**File**: `backend/app/core/backtest_engine.py`

```python
@staticmethod
def merge_htf_context(ltf_df: pd.DataFrame, htf_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge HTF indicator data into LTF DataFrame with lookahead prevention.

    The critical operation is shift(1) BEFORE ffill():
    - At 10:15 on the 5m chart, you can NOT see the 10:00-11:00 1H candle's close
    - shift(1) ensures the 10:15 bar only sees the COMPLETED 09:00-10:00 candle
    - ffill() carries the last completed HTF values forward to all LTF bars

    Returns: LTF DataFrame with htf_* prefixed columns added.
    """
    htf_indicators = BacktestEngine.compute_indicators_from_df(htf_df)

    # Build HTF values indexed by open_time
    htf_ind_df = pd.DataFrame({'open_time': htf_df['open_time']})
    for key in ['ema_50', 'ema_200', 'rsi_14', 'macd_histogram', 'atr_14']:
        if key in htf_indicators:
            htf_ind_df[f'htf_{key}'] = [v['value'] for v in htf_indicators[key]]
    htf_ind_df = htf_ind_df.set_index('open_time')

    # CRITICAL: shift(1) prevents lookahead bias
    htf_ind_df = htf_ind_df.shift(1)

    # Reindex to LTF timestamps with forward fill
    ltf_times = pd.DatetimeIndex(ltf_df['open_time'])
    htf_aligned = htf_ind_df.reindex(ltf_times, method='ffill')

    result = ltf_df.copy()
    for col in htf_aligned.columns:
        result[col] = htf_aligned[col].values
    return result
```

## Step 4.2 — Add HTF Candle Boundary Detection

**File**: `backend/app/core/backtest_engine.py`

Utility to detect when a new HTF candle boundary is crossed during the bar-by-bar walk:

```python
@staticmethod
def _htf_candle_boundaries(ltf_df: pd.DataFrame, htf_df: pd.DataFrame) -> set[int]:
    """
    Return set of LTF bar indices where a new HTF candle just closed.
    Used to trigger update_context() during historical walk.
    """
    htf_close_times = set(htf_df['open_time'].values)
    boundaries = set()
    for idx, row in ltf_df.iterrows():
        if row['open_time'] in htf_close_times:
            boundaries.add(idx)
    return boundaries
```

## Step 4.3 — Update `run()` for MTF

**File**: `backend/app/core/backtest_engine.py`

Extend `BacktestEngine.run()` to accept optional HTF parameters:

```python
@classmethod
def run(cls, symbol, timeframe, start_date, end_date, strategies,
        strategy_names, initial_capital=10000.0, risk_pct=0.01,
        context_timeframe=None):  # NEW param
```

When `context_timeframe` is provided:
1. Fetch HTF candles from DB alongside LTF candles
2. Call `merge_htf_context()` to produce the merged DataFrame
3. Compute HTF indicator series separately
4. Pass HTF boundary info to `scan_historical()`
5. Set `engine_version = '2.0'` on the BacktestRun record

## Step 4.4 — Update `scan_historical()` for MTF Walk

**File**: `backend/app/core/strategy_runner.py`

Extend `scan_historical()` with optional MTF params:

```python
@classmethod
def scan_historical(cls, strategies, symbol, timeframe, candle_df,
                    indicator_series, sr_zones, min_confidence_override=None,
                    htf_candle_df=None, htf_indicator_series=None,
                    htf_boundaries=None):  # NEW params
```

At each bar in the walk:
- If `idx` is in `htf_boundaries`, call `strategy.update_context()` with the HTF data available at that point
- For MTF strategies, call `run_mtf_scan()` instead of `run_single_scan()`
- For legacy strategies, behavior is unchanged

## Verification

- [ ] `merge_htf_context()` produces a DataFrame with `htf_*` columns
- [ ] At LTF bar T, the `htf_ema_50` value corresponds to the HTF candle that CLOSED before T (not the one containing T)
- [ ] A simple test: create a 4-bar HTF series with values [10, 20, 30, 40]. Merge with 16-bar LTF series. Verify first 4 LTF bars see `NaN` (shifted), bars 5-8 see `10`, bars 9-12 see `20`, etc.
- [ ] Backtest with `context_timeframe=None` produces identical results to before (legacy path)
- [ ] `engine_version` is `'2.0'` for MTF backtests, `'1.0'` for legacy
- [ ] All existing backtest tests pass unchanged
