# Phase 1: Feature Extraction Layer — Implementation Plan

## Objective

Strip all mathematical calculations out of `app/strategies/`. Strategies become pure logic gates and confidence scoring. All math moves to `app/core/` as a pure extraction layer.

## Current State: Math/Logic Entanglement

Math is currently scattered across strategy files:
- **`order_block_retest.py`**: Impulse detection, OB identification, FVG detection, BOS validation — ~200 lines of math before any trading logic
- **`fvg_mitigation.py`**: FVG gap calculation, mitigation tracking, OB adjacency checks
- **`smc_structure_shift.py`**: Swing point mapping, trend determination, ChoCh/BOS classification
- **`smc_liquidity_sweep.py`**: Liquidity sweep detection
- **`sr_breakout.py` / `sr_rejection.py`**: Zone intersection math

All of this belongs in `app/core/` as reusable, contract-enforcing extractors.

---

## 1A: Continuous State Module (`app/core/indicators.py`)

### Current Implementation Review
`IndicatorService` at `app/core/indicators.py` already computes EMAs, RSI, MACD, Bollinger, Keltner, ATR, Volume MA. It returns raw `pd.Series`. This is structurally correct but needs contract hardening.

### Required Changes

#### 1. NaN Policy Enforcement
**Problem**: When EMA period > available candles, `ewm().mean()` returns NaN for early rows. If strategies do `df['rsi'] < 30`, NaN rows silently fail (neither True nor False).

**Fix**: Every indicator function MUST document its NaN zone and provide a `min_candles` attribute. No indicator function should propagate NaN across the entire column.

```python
@staticmethod
def compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """
    Contract:
      - Input: pd.Series of close prices (any length)
      - Output: pd.Series of same index, float64
      - NaN policy: First (period + 1) values are NaN (insufficient history).
        These NaNs are EXPECTED and must be handled by consumers via .isna() guards.
      - No side effects: Does not mutate input, does not modify DataFrame in place.
    """
    if len(closes) < period + 1:
        return pd.Series([np.nan] * len(closes), index=closes.index, dtype='float64')
    # Existing Wilder's smoothing logic — unchanged
    ...
```

#### 2. Remove Caching from the Extraction Layer
**Problem**: The current `_cache` on `IndicatorService` couples extraction to caching. A strategy that calls `compute_rsi()` directly should get a pure function, not a cache-check.

**Fix**: Split into:
- `app/core/indicators.py` — Pure stateless functions (no cache, no DB)
- `app/core/indicator_service.py` — Caching wrapper for API use (rename current class)

The extraction layer (`indicators.py`) exposes pure functions. The service layer wraps them.

#### 3. Required Functions (No New Ones, Just Contract-Hardened)

| Function | Input | Output | Min Candles |
|----------|-------|--------|-------------|
| `compute_ema(closes, period)` | Series | Series | `period` |
| `compute_rsi(closes, period=14)` | Series | Series | `period + 1` |
| `compute_macd(closes, fast=12, slow=26, signal=9)` | Series | dict of Series | `slow + signal` |
| `compute_bollinger(closes, period=20, std_dev=2.0)` | Series | dict of Series | `period` |
| `compute_atr(highs, lows, closes, period=14)` | 3 Series | Series | `period + 1` |
| `compute_keltner(highs, lows, closes, ema_period=20, atr_period=10, multiplier=1.5)` | 3 Series | dict of Series | `ema_period` |
| `compute_volume_ma(volumes, period=20)` | Series | Series | `period` |

#### 4. Implementation Steps

1. Create `app/core/indicator_service.py` — Move current `IndicatorService` class there, keep cache + DB fetch logic
2. Refactor `app/core/indicators.py` — Pure stateless functions only, each with docstring contract
3. Add `min_candles` property to each function (as a `__min_candles__` attribute or module constant dict)
4. Add `_assert_no_nan_propagation()` test utility that verifies NaN columns don't bleed into non-NaN columns
5. Update all imports: strategies import from `app.core.indicators`, API blueprints import from `app.core.indicator_service`

---

## 1B: Spatial State Module

### 1B-i: `app/core/market_structure.py` (NEW FILE)

This is the biggest new file. It extracts FVG and Order Block logic from strategies into pure DataFrame functions.

#### Universal Zone Contract (Enforced Here)
Every function that produces zones MUST append columns following this naming convention:

```
{prefix}_active:     bool    — True while zone exists and is unmitigated
{prefix}_upper:      float64 — Upper boundary price
{prefix}_lower:      float64 — Lower boundary price
{prefix}_volume:     float64 — Zone volume (for confidence scaling)
{prefix}_created_at: datetime — Candle open_time when zone was formed
```

#### Function: `extract_fvgs(df, mitigation_type='wick', lookback=50) -> pd.DataFrame`

**Moved from**: `fvg_mitigation.py` (lines 86-210), `order_block_retest.py` (`_find_fvg`, lines 56-87)

**Algorithm**:
```
For each 3-candle window (i-2, i-1, i):
  Bullish FVG: candle[i].low > candle[i-2].high
    → zone = candle[i-2].high to candle[i].low
  Bearish FVG: candle[i].high < candle[i-2].low
    → zone = candle[i].low to candle[i-2].high
```

**Contract Implementation**:
```python
def extract_fvgs(df: pd.DataFrame, mitigation_type: str = 'wick', lookback: int = 50) -> pd.DataFrame:
    """
    Extract Fair Value Gaps from price action.

    Args:
        df: DataFrame with columns [open, high, low, close, volume, open_time]
        mitigation_type: 'wick' (default) or 'body' — what counts as mitigation
        lookback: How many candles to scan backward

    Returns:
        DataFrame with added columns:
            fvg_active:   bool — True if unmitigated FVG exists at this candle
            fvg_upper:    float64 — upper boundary
            fvg_lower:    float64 — lower boundary
            fvg_volume:   float64 — volume of the impulse candle
            fvg_created_at: datetime64 — formation candle open_time

    CRITICAL: Zones are shifted by +1 (active on candle AFTER displacement close).
    Mitigated zones are NaN'd out, NOT forward-filled.
    """
```

**Trap 2 Defense (Lookahead Bias)**:
- FVG forms between C1 and C3. The confirming displacement happens on C3's close.
- `fvg_active` is set to `True` starting at C4 (shifted by 1), not C3.
- This prevents the strategy from trading a zone on the same candle it forms.

**Masked Forward-Filling (The ONLY safe ffill pattern for Spatial States)**:

Banning `ffill()` entirely would kill spatial zones — a zone formed at candle 10 must persist to candle 15 so the strategy can see it there. The rule is: **ffill is mandatory for zone lifetime, but ffill must be killed by mitigation, not left to bleed.**

```python
# CORRECT: Masked Forward-Filling for Spatial Zone Tracking
# Step 1: Set zone boundaries only at creation candles
df['fvg_upper'] = np.where(bullish_fvg_detected, upper_val, np.nan)
df['fvg_lower'] = np.where(bullish_fvg_detected, lower_val, np.nan)

# Step 2: Forward-fill so zone persists across time (ESSENTIAL — do not skip)
df['fvg_upper'] = df['fvg_upper'].ffill()
df['fvg_lower'] = df['fvg_lower'].ffill()

# Step 3: Shift active flag by +1 (lookahead bias defense)
df['fvg_active_raw'] = df['fvg_upper'].notna()
df['fvg_active'] = df['fvg_active_raw'].shift(1).fillna(False)

# Step 4: Apply mitigation mask to FORCEFULLY kill the zone
# Bullish FVG mitigated when low pierces the lower boundary
bullish_mitigated = df['fvg_upper'].notna() & (df['low'] <= df['fvg_lower'])
bearish_mitigated = df['fvg_upper'].notna() & (df['high'] >= df['fvg_upper'])
df.loc[bullish_mitigated | bearish_mitigated, ['fvg_upper', 'fvg_lower']] = np.nan

# Step 5: Recompute active from NaN state (now dead zone is truly dead)
df['fvg_active'] = df['fvg_active'] & df['fvg_upper'].notna()
```

**The key insight**: `ffill()` is the persistence mechanism. The mitigation mask is the kill switch. Together they form a state machine, not a leak. Without ffill, zones die immediately after birth. With ffill but no kill switch, dead zones haunt the future.

**Mitigation Detection** (Trap: Mitigation Desync):
```python
if mitigation_type == 'wick':
    # Wick mitigation: high/low touches zone
    bullish_mitigated = df['low'] <= df['fvg_lower']
    bearish_mitigated = df['high'] >= df['fvg_upper']
elif mitigation_type == 'body':
    # Body mitigation: close enters zone
    bullish_mitigated = df['close'] <= df['fvg_lower']
    bearish_mitigated = df['close'] >= df['fvg_upper']
```

#### Function: `extract_order_blocks(df, impulse_min=2, impulse_max=5, atr_displacement=1.5) -> pd.DataFrame`

**Moved from**: `order_block_retest.py` (lines 168-353, the entire scan logic)

**Algorithm**:
```
For each bearish candle (bullish OB candidate) or bullish candle (bearish OB candidate):
  1. Count consecutive bullish/bearish candles after it (impulse)
  2. Verify impulse length >= impulse_min and <= impulse_max
  3. Verify ATR-normalized displacement >= atr_displacement
  4. Verify Break of Structure (impulse breaks prior swing)
  5. If valid: create zone at OB candle's high/low
```

**Contract Implementation**:
```python
def extract_order_blocks(
    df: pd.DataFrame,
    impulse_min: int = 2,
    impulse_max: int = 5,
    atr_displacement: float = 1.5
) -> pd.DataFrame:
    """
    Returns DataFrame with:
        ob_active:      bool
        ob_upper:       float64
        ob_lower:       float64
        ob_volume:      float64 — OB candle volume
        ob_direction:   str — 'bullish' or 'bearish'
        ob_created_at:  datetime64
    """
```

**Mitigation for OBs**:
- Bullish OB mitigated when `close < ob_lower` (body close below block)
- Bearish OB mitigated when `close > ob_upper` (body close above block)
- Default: body-close mitigation for OBs (institutional logic)

#### Critical Constraint: The Overlapping Zone Problem (Single-Zone V1 Contract)

A flat DataFrame with `fvg_upper`/`fvg_lower` columns can only track **one zone at a time**. If a bullish FVG forms at T0 and another bullish FVG forms at T5 before T0 is mitigated, T5 overwrites the column values and T0 vanishes from memory.

**The Contract (V1)**: `extract_fvgs()` returns ONLY the **most recently formed unmitigated FVG**. Older unmitigated FVGs are dropped from the DataFrame (not tracked). This is documented explicitly:

```python
def extract_fvgs(df, mitigation_type='wick', lookback=50):
    """
    Returns the MOST RECENTLY FORMED unmitigated FVG only.
    
    If a new FVG forms while an older one is still active, the older one
    is removed from tracking. The system prioritizes freshness over history.
    
    Future versions (V2) may support multi-zone tracking via a numba-compiled
    zone registry, but V1 accepts this limitation to preserve vectorization speed.
    """
```

Why this is acceptable for V1:
- In practice, overlapping same-type zones on the same side (two bullish FVGs simultaneously active) is rare on HTF charts
- The nearest zone matters most for strategy decisions (price interacts with the closest one first)
- The alternative (list-in-cell or numbered columns) destroys pandas vectorization and would require a full numba rewrite — defer to V2

### 1B-ii: `app/core/sr_engine.py` (REFACTOR)

#### Function: `extract_liquidity_levels(df, pivot_bars=3) -> pd.DataFrame`

**Moved from**: `smc_liquidity_sweep.py`

**Contract**:
```python
def extract_liquidity_levels(df: pd.DataFrame, pivot_bars: int = 3) -> pd.DataFrame:
    """
    Returns:
        liq_active:     bool
        liq_upper:      float64 — equal highs liquidity
        liq_lower:      float64 — equal lows liquidity
        liq_direction:  str — 'buy_side' or 'sell_side'
        liq_created_at: datetime64
    """
```

#### Implementation Steps for `market_structure.py`

1. **Week 1: Port FVG extraction**
   - Copy FVG detection logic from `fvg_mitigation.py` and `order_block_retest.py`
   - Convert from Candle-object iteration to vectorized pandas operations
   - Implement zone contract (active, upper, lower, volume, created_at)
   - Implement shift(+1) for lookahead bias prevention
   - Implement NaN-on-mitigation for forward-fill leak prevention
   - Write unit tests against known TradingView data

2. **Week 2: Port OB extraction**
   - Copy OB detection logic from `order_block_retest.py`
   - Handle the variable-length impulse loop (this is the hardest to vectorize — may need a hybrid approach)
   - Implement BOS validation as a separate helper
   - Implement cooldown tracking as a zone staleness metric (not a gate — that's strategy logic)

3. **Week 3: Port liquidity level extraction**
   - Extract from `smc_liquidity_sweep.py`
   - Handle equal highs / equal lows clustering

### 1B-ii: `app/core/sr_engine.py` (REFACTOR)

**Current implementation is already close to correct.** The `SREngine.detect_zones()` pipeline produces zone dicts with `zone_upper`, `zone_lower`, `strength_score`. Key changes:

1. **Add DataFrame output mode**: Currently returns list of dicts. Add a `detect_zones_df(df) -> pd.DataFrame` method that appends `sr_active`, `sr_upper`, `sr_lower` columns following the universal zone contract.

2. **Add `sr_created_at`**: Zones currently track `last_tested` and `created_at` in the DB. Surface this in the DataFrame output.

3. **Remove `persist_zones()` from extraction layer**: Persistence is a Phase 3 concern. The extraction function should be pure.

---

## 1C: Temporal State Module (`app/core/events.py`) (NEW FILE)

### Purpose
Handle instantaneous triggers that happen on a single candle — events that are NOT zones. Events are boolean masks.

### Functions

#### `detect_choch(df, pivot_bars=3) -> pd.DataFrame`

**Moved from**: `smc_structure_shift.py` (lines 38-256) and `fractals.py` (swing map building)

**Contract**:
```python
def detect_choch(df: pd.DataFrame, pivot_bars: int = 3) -> pd.DataFrame:
    """
    Detect Change of Character (ChoCh) and Break of Structure (BOS) events.

    Returns DataFrame with columns:
        event_choch_bullish:         bool — True ONLY on exact breakout candle
        event_choch_bearish:         bool
        event_bos_bullish:           bool
        event_bos_bearish:           bool
        event_choch_bullish_recent:  bool — rolling(10).max() of event_choch_bullish
        event_choch_bearish_recent:  bool
        event_bos_bullish_recent:    bool
        event_bos_bearish_recent:    bool

    CRITICAL: Events are NOT zones. They fire on a single candle and their
    _recent columns decay naturally via rolling window. No forward-fill.
    """
```

**Surgical Detail — Body Close vs Wick**:
- ChoCh/BOS requires body close beyond the swing point (not wick)
- This is the existing logic in `smc_structure_shift.py` (lines 106, 148)
- Expose as `confirmation='body'` parameter (default) with `'wick'` option

**Algorithm** (ported from existing strategies):
```
1. Build swing map via fractals.py:find_fractal_points(df, pivot_bars)
2. Determine trend direction from last 4 swing points
3. Find most recent swing high and swing low
4. For each candle after swing:
   - Bullish BOS: bull trend + body close above swing high → event_bos_bullish = True
   - Bearish BOS: bear trend + body close below swing low → event_bos_bearish = True
   - Bullish ChoCh: bear trend + body close above swing high → event_choch_bullish = True
   - Bearish ChoCh: bull trend + body close below swing low → event_choch_bearish = True
5. Compute _recent columns via rolling(10).max()
6. CRITICAL: Cancel opposing event memory (see below)
```

**Critical: Opposing Event Memory Cancellation**

Naive `rolling(10).max()` on `event_choch_bullish` keeps the memory alive for 10 candles even if a Bearish ChoCh fires on candle 4. This creates a phantom "recent bullish ChoCh" in a bearish macro environment, causing false long signals.

```python
# WRONG — Bearish ChoCh at candle 4 does NOT cancel the bullish ChoCh from candle 1
df['choch_bullish_recent'] = df['event_choch_bullish'].rolling(10).max().fillna(0).astype(int)

# RIGHT — Opposing events cancel each other's recent memory
# Find the index of the most recent event in each rolling window
def _most_recent_idx(series):
    """Return the relative index (0-9) of the most recent True in a rolling window."""
    arr = series.values
    for i in range(len(arr) - 1, -1, -1):
        if arr[i]:
            return i
    return -1

bullish_recent = df['event_choch_bullish'].rolling(10).max().fillna(0).astype(bool)
bearish_recent = df['event_choch_bearish'].rolling(10).max().fillna(0).astype(bool)

last_bullish_idx = df['event_choch_bullish'].rolling(10).apply(
    _most_recent_idx, raw=True
).fillna(-1)
last_bearish_idx = df['event_choch_bearish'].rolling(10).apply(
    _most_recent_idx, raw=True
).fillna(-1)

# Bullish ChoCh is "recent" ONLY if there's no bearish ChoCh more recent than it
df['choch_bullish_recent'] = bullish_recent & (last_bullish_idx >= last_bearish_idx)
df['choch_bearish_recent'] = bearish_recent & (last_bearish_idx >= last_bullish_idx)
```

This prevents a strategy from seeing `choch_bullish_recent=True` while the most recent structural event was bearish. A massive dump that triggers a bearish ChoCh instantly zeroes out the bullish ChoCh memory.

**Performance note**: `rolling().apply()` is expensive on large DataFrames. For production, implement this with a numba-accelerated window function or use `rolling().max()` only on an "effective recent" column that is already gated by direction. The above is the logically correct algorithm; optimize in implementation.

#### `detect_volume_climax(df, volume_ma_period=20, threshold=2.0) -> pd.DataFrame`

**Moved from**: `volume_climax.py`

```python
def detect_volume_climax(df, volume_ma_period=20, threshold=2.0) -> pd.DataFrame:
    """
    Returns:
        event_volume_climax:          bool — True on climax candle
        event_volume_climax_bullish:  bool — climax + bullish close
        event_volume_climax_bearish:  bool — climax + bearish close
        event_volume_climax_recent:   bool — rolling(5).max()
    """
```

#### `detect_liquidity_sweep(df, pivot_bars=3) -> pd.DataFrame`

**Moved from**: `smc_liquidity_sweep.py`

```python
def detect_liquidity_sweep(df, pivot_bars=3) -> pd.DataFrame:
    """
    Returns:
        event_sweep_bullish:   bool — wick below swing low, close back above
        event_sweep_bearish:   bool — wick above swing high, close back below
        event_sweep_recent:    bool — rolling(10).max()
    """
```

---

## Trap Defenses Embedded in Phase 1

### T1: Live Candle Poisoning
**Location**: Data fetching utility
**Action**: Create `get_finalized_candles()` in a shared data utility (not in strategies)
```python
# app/core/data_utils.py (NEW)
class StaleDataError(Exception):
    """Raised when finalized candles are too old to be reliable."""
    pass

def get_finalized_candles(
    symbol: str,
    timeframe: str,
    limit: int = 500,
    as_of_ms: int = None,
    start_date: datetime = None,
    end_date: datetime = None,
) -> pd.DataFrame:
    """
    Returns ONLY closed candles. Time-agnostic — callers inject the reference time.

    Two query modes:
      - Live mode:  `get_finalized_candles(symbol, tf, limit=500)` 
                    Uses wall-clock utcnow() for staleness + open-candle filtering.
      - Backtest:   `get_finalized_candles(symbol, tf, start_date=..., end_date=...)`
                    Uses simulated time for all checks. Staleness guard is DISABLED
                    in date-range mode because the "last candle" is the end of the
                    simulation window, not a live market condition.

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe (e.g., '1h')
        limit: Max candles to return (live mode only)
        as_of_ms: Reference timestamp in ms. Live scanner passes utcnow();
                  backtester passes end_date_ms. Defaults to utcnow().
        start_date: If provided, query by date range instead of limit (backtest mode)
        end_date: Required if start_date is provided

    Guards (live mode only):
    1. Drops unclosed candles (is_closed=False or evolving candle)
    2. Raises StaleDataError if the most recent closed candle is older than
       2x the timeframe duration (prevents strategies from firing on stale data
       when the WebSocket drops or gap-healer fails)

    Guards (both modes):
    1. Drops rows where open_time + timeframe_duration > as_of_ms
       (these candles have not yet closed from the reference time's perspective)
    """
    tf_ms = _timeframe_to_ms(timeframe)
    
    # Resolve the reference time: caller-injected or wall clock
    if as_of_ms is not None:
        now_ms = as_of_ms
    else:
        now_ms = int(datetime.utcnow().timestamp() * 1000)
    
    # Determine query mode
    is_backtest = start_date is not None and end_date is not None
    
    if is_backtest:
        candles = Candle.query \
            .filter_by(symbol=symbol, timeframe=timeframe) \
            .filter(Candle.open_time >= start_date) \
            .filter(Candle.open_time <= end_date) \
            .order_by(Candle.open_time.asc()) \
            .all()
    else:
        candles = Candle.query \
            .filter_by(symbol=symbol, timeframe=timeframe) \
            .order_by(Candle.open_time.desc()) \
            .limit(limit + 1) \
            .all()
        # Reverse to ascending for proper time ordering
        candles = list(reversed(candles))
    
    df = pd.DataFrame([c.to_dict() for c in candles])
    
    if len(df) == 0:
        return df
    
    # Guard: Drop unclosed candles (relative to as_of_ms, not wall clock)
    if 'is_closed' in df.columns:
        df = df[df['is_closed'] == True]
    
    df['open_time_ms'] = pd.to_datetime(df['open_time']).astype('int64') // 10**6
    df = df[df['open_time_ms'] + tf_ms <= now_ms]
    df = df.sort_values('open_time').reset_index(drop=True)
    
    # Staleness guard: LIVE MODE ONLY
    # In backtest mode, the "last candle" is the end of the simulation window,
    # which is expected to be far in the past. Staleness has no meaning there.
    if not is_backtest and len(df) > 0:
        last_candle_time_ms = df['open_time_ms'].iloc[-1]
        age_ms = now_ms - last_candle_time_ms
        max_age_ms = tf_ms * 2
        if age_ms > max_age_ms:
            raise StaleDataError(
                f"Most recent closed candle for {symbol} {timeframe} is "
                f"{age_ms / 1000:.0f}s old (max allowed: {max_age_ms / 1000:.0f}s). "
                f"WebSocket may be disconnected or gap-healer failed."
            )
    
    return df
```

### T2: Gap-Heal Race Condition
**Location**: `LiveScanner._on_candle_close()`
**Action**: The gap heal MUST be synchronous and blocking. Add an await/gate pattern:
```python
def _on_candle_close(self, session_id, symbol, timeframe, candle_data):
    # Step 0: Upsert candle
    self._upsert_candle(candle_data)
    
    # Step 1: Block and heal gaps (synchronous, must complete)
    gap_healed = self._detect_and_heal_gap(symbol, timeframe, candle_data['open_time'])
    
    # Step 2: Re-fetch candles ONLY after gap heal completes
    df = get_finalized_candles(symbol, timeframe, limit=self.get_required_lookback())
    
    # Step 3: Run extraction pipeline
    ...
```

### T3: Lookback Horizon
**Location**: `BaseStrategy.get_required_lookback()` (Phase 2, but the data fetcher in Phase 1 must support it)
**Action**: All extraction functions accept variable-length DataFrames. The orchestrator (Phase 2) determines the minimum length. Phase 1 just ensures functions work correctly with any length.

### T4: Intra-candle Invalidation
**Accepted latency**. No Phase 1 action needed. The Watching card remains until `_on_candle_close()` re-evaluates mitigation.

---

## File Manifest for Phase 1

| File | Action | Lines (approx) |
|------|--------|----------------|
| `app/core/indicators.py` | REFACTOR — pure functions, contracts | ~200 |
| `app/core/indicator_service.py` | NEW — caching wrapper (move existing class) | ~150 |
| `app/core/market_structure.py` | NEW — FVG + OB + liquidity extraction | ~600 |
| `app/core/events.py` | NEW — ChoCh/BOS/volume/sweep events | ~400 |
| `app/core/sr_engine.py` | MODIFY — add `detect_zones_df()` | +100 |
| `app/core/data_utils.py` | NEW — `get_finalized_candles()` | ~50 |
| `app/core/fractals.py` | MODIFY — add DataFrame-based API alongside Candle-based | +150 |
| `tests/test_market_structure.py` | NEW — FVG/OB extraction tests | ~300 |
| `tests/test_events.py` | NEW — temporal event tests | ~200 |
| `tests/test_indicators_contract.py` | NEW — NaN propagation tests | ~100 |

## Phase 1 Validation Gates

Before proceeding to Phase 2, these must pass:

1. **Continuity Gate**: Every indicator function returns Series with same index as input, no dropped rows
2. **NaN Gate**: No NaN value in column X causes NaN in column Y (test with a deliberately short DataFrame)
3. **Lookahead Gate**: `fvg_active` at candle index `i` uses only data from candles `≤ i-1` (test by comparing with and without future data)
4. **Mitigation Gate**: When price crosses `fvg_lower`, `fvg_active` becomes False on the same candle and stays False for all subsequent candles
5. **Mitigation-Clearing Gate** (replaces No-Forward-Fill Gate): Verify that ffill is used for zone persistence, but mitigated zones revert to NaN and do NOT bleed into subsequent rows. The pattern must be: `ffill()` → `mitigation_mask` → `NaN` → recompute active. Mitigation must be the terminal state for a zone.
6. **Opposing Event Cancel Gate**: When a bullish ChoCh fires, then a bearish ChoCh fires at candle N+3, `choch_bullish_recent` must be `False` at candle N+3 (bearish event cancels bullish memory). Test with a deliberately alternating sequence of events.
7. **Staleness Gate**: `get_finalized_candles()` must raise `StaleDataError` when the most recent closed candle is older than 2x the timeframe duration
8. **Single-Zone Contract Gate**: `extract_fvgs()` must document that it tracks only the most recently formed unmitigated zone. Test that when a second FVG forms before the first is mitigated, only the second one appears in `fvg_upper`/`fvg_lower`
9. **TradingView Parity Gate**: Run on known Binance data, export CSV, manually verify 5+ FVG/OB events against TradingView chart
