# Phase 4: Defensive Coding Against Quantitative Traps — Implementation Plan

## Objective

Prevent the 5 quantitative traps that silently corrupt signals. These defenses must be baked into Phase 1 from day one, not retrofitted after bugs are found.

---

## 4A: Trap 1 — Forward-Fill (ffill) Leak

### The Trap
If you `ffill()` a zone blindly without a mitigation kill switch, you drag mitigated or invalidated zones into the future, causing fake signals:

```python
# WRONG — ffill with no mitigation kill switch: dead zone persists forever
df['fvg_upper'] = df['fvg_upper'].ffill()
df['fvg_lower'] = df['fvg_lower'].ffill()
# Zone from candle 100 still shows as active on candle 500, long after mitigation
```

**But**: Banning ffill entirely is equally wrong. Without ffill, a zone formed at candle 10 is invisible at candle 15 even if never mitigated. Spatial states MUST be forward-filled to persist across time.

### The Fix: Masked Forward-Filling (ffill + mitigation kill switch)

```python
# CORRECT — ffill for persistence, mitigation mask for death
def extract_fvgs(df, mitigation_type='wick'):
    # Step 1: Set zone boundaries at creation candles only
    df['fvg_upper'] = np.where(bullish_fvg_detected, upper_val, np.nan)
    df['fvg_lower'] = np.where(bullish_fvg_detected, lower_val, np.nan)
    
    # Step 2: Forward-fill so zone persists across time (REQUIRED)
    df['fvg_upper'] = df['fvg_upper'].ffill()
    df['fvg_lower'] = df['fvg_lower'].ffill()
    
    # Step 3: Shift active flag by +1 (lookahead bias defense)
    df['fvg_active'] = df['fvg_upper'].notna().shift(1).fillna(False)
    
    # Step 4: Mitigation kill switch — detect when price enters zone
    if mitigation_type == 'wick':
        # Bullish FVG: low drops into the gap → mitigated
        # Bearish FVG: high rises into the gap → mitigated
        bullish_mitigated = df['fvg_upper'].notna() & (df['low'] <= df['fvg_lower'])
        bearish_mitigated = df['fvg_upper'].notna() & (df['high'] >= df['fvg_upper'])
    else:  # body
        bullish_mitigated = df['fvg_upper'].notna() & (df['close'] <= df['fvg_lower'])
        bearish_mitigated = df['fvg_upper'].notna() & (df['close'] >= df['fvg_upper'])
    
    # Step 5: FORCEFULLY NaN the zone the exact moment it's invalidated
    mitigated_mask = bullish_mitigated | bearish_mitigated
    df.loc[mitigated_mask, ['fvg_upper', 'fvg_lower', 'fvg_volume']] = np.nan
    
    # Step 6: Recompute active — dead zone is now False
    df['fvg_active'] = df['fvg_active'] & df['fvg_upper'].notna()
```

**The state machine in this pattern**:
- `ffill()` = persistence (zone lives until killed)
- `mitigation_mask` + `NaN` = death (zone killed at exact candle of invalidation)
- `fvg_active` = `shift(1)` AND `notna()` = only alive after confirmation, dead after mitigation
```

### Enforcement
Add a linter rule or test that prohibits bare `.ffill()` on zone columns:
```python
# tests/test_defensive_coding.py
def test_no_ffill_leak():
    """Verify that mitigated zones do not leak into future candles."""
    df = create_test_df_with_fvg()
    df = extract_fvgs(df)
    
    # Find where FVG was mitigated
    mitigated_idx = df[df['low'] <= df['fvg_lower']].index[0]
    
    # Verify fvg_active is False for ALL candles after mitigation
    assert not df.loc[mitigated_idx:, 'fvg_active'].any(), \
        "FVG active after mitigation — ffill leak detected"
    
    # Verify fvg_upper/lower are NaN after mitigation
    assert df.loc[mitigated_idx:, 'fvg_upper'].isna().all(), \
        "FVG upper not NaN after mitigation"
```

---

## 4B: Trap 2 — Lookahead Bias in Zone Tracking

### The Trap
A zone cannot be marked as active on the same candle it originates if confirmation requires the close of a subsequent candle.

Example: FVG forms between candles C1 and C3. C3 must close above C1's high to confirm the bullish gap. But the strategy scans C3 while it's still open, sees the high, and fires a signal before the gap is confirmed.

### The Fix: `.shift(1)` on Active Flags

```python
# WRONG — Zone active before confirming candle closes
df['fvg_active'] = ~df['fvg_upper'].isna()

# RIGHT — Zone active only on candle AFTER the confirming displacement candle closes
df['fvg_active'] = ~df['fvg_upper'].isna().shift(1).fillna(False)
```

For every zone-producing function:
1. Zone is DETECTED at candle index `i` (using data from candles ≤ i)
2. Zone is marked ACTIVE starting at candle index `i + 1` (after the confirming candle closes)
3. Zone `created_at` is set to `df.iloc[i]['open_time']` (the formation candle's time)

### Implementation in `market_structure.py`

```python
def _stamp_zone_active(df, zone_upper_col, zone_lower_col, zone_id_col, active_col):
    """
    Standardized pattern for all zone extractors:
    Mark zone as active on the candle AFTER formation.
    """
    # Zone columns are set at the detection candle (index i)
    # Shift active flag to index i+1
    df[active_col] = df[zone_id_col].notna().shift(1).fillna(False)
    return df
```

### Test
```python
def test_lookahead_bias_prevention():
    """Zone active flag must not be True on the same candle it's detected."""
    df = create_test_df_with_fvg(at_candle=50)
    df = extract_fvgs(df)
    
    # The FVG forms at candle 50 (using candles 48, 49, 50)
    # It should become active at candle 51, not 50
    assert not df.loc[50, 'fvg_active'], \
        "FVG active on formation candle — lookahead bias"
    assert df.loc[51, 'fvg_active'], \
        "FVG not active on candle after formation"
```

---

## 4C: Trap 3 — Mitigation Desync (Wick vs. Body)

### The Trap
Different market participants consider zones mitigated differently:
- **FVGs**: Traders accept wick mitigation (price just needs to touch the gap)
- **Order Blocks**: Institutions require body close beyond the block (wick doesn't count)

If your code treats both the same, you get false mitigations (or missed ones).

### The Fix: Parameterized Mitigation Type

```python
def extract_fvgs(df, mitigation_type='wick'):
    """
    mitigation_type: 'wick' — high/low touches zone → mitigated
                     'body' — close enters zone → mitigated
    """
    ...
    
    if mitigation_type == 'wick':
        bullish_mitigated = df['low'] <= df['fvg_lower']
        bearish_mitigated = df['high'] >= df['fvg_upper']
    elif mitigation_type == 'body':
        bullish_mitigated = df['close'] <= df['fvg_lower']
        bearish_mitigated = df['close'] >= df['fvg_upper']
    else:
        raise ValueError(f"Unknown mitigation_type: {mitigation_type}")

def extract_order_blocks(df, mitigation_type='body'):
    """
    mitigation_type: 'body' (default for OBs) — close beyond block → mitigated
                     'wick' — high/low beyond block → mitigated
    """
    ...
```

### Default Conventions
| Zone Type | Default Mitigation | Rationale |
|-----------|-------------------|-----------|
| FVG | `'wick'` | Gap considered filled on any touch |
| Order Block | `'body'` | Institution must commit with a close |
| S/R Zone | `'wick'` | Support/resistance tested by wick |

### Test
```python
def test_mitigation_type_wicks():
    """Wick mitigation: zone dies on wick touch, even if body doesn't enter."""
    df = create_df_with_fvg_and_wick_touch()
    df = extract_fvgs(df, mitigation_type='wick')
    assert not df.iloc[-1]['fvg_active']  # Wick touched → dead

def test_mitigation_type_body():
    """Body mitigation: zone survives wick touch, dies only on body close."""
    df = create_df_with_fvg_and_wick_touch()
    df = extract_fvgs(df, mitigation_type='body')
    assert df.iloc[-1]['fvg_active']  # Wick touched but body didn't → alive
```

---

## 4D: Trap 4 — NaN Propagation and Type Coercion

### The Trap
A single NaN in a feature column can silently infect downstream calculations, causing `df['confidence']` to become NaN, which causes `signal = 0` (since NaN ≥ 0.75 is False), which means missed trades.

```python
# WRONG — NaN propagates
df['confidence'] = 0.50
df['confidence'] += np.where(df['fvg_active'] & (df['rsi'] < 30), 0.20, 0.0)
# If rsi is NaN, df['rsi'] < 30 is False, so 0.20 is NOT added.
# No crash, but the signal is silently weaker than it should be.
```

### The Fix: Explicit NaN Guards Everywhere

```python
# RIGHT — Explicit NaN handling
@staticmethod
def safe_lt(series: pd.Series, threshold: float) -> pd.Series:
    """Less-than comparison treating NaN as False."""
    return series.notna() & (series < threshold)

@staticmethod
def safe_gt(series: pd.Series, threshold: float) -> pd.Series:
    """Greater-than comparison treating NaN as False."""
    return series.notna() & (series > threshold)

@staticmethod
def safe_between(series: pd.Series, lower: float, upper: float) -> pd.Series:
    """Between check treating NaN as False."""
    return series.notna() & (series >= lower) & (series <= upper)

# Usage in strategy:
df['confidence'] += np.where(df['fvg_active'] & safe_lt(df['rsi'], 30), 0.20, 0.0)
```

### Zone Distance Calculations
When computing distance between two zones (e.g., OB to FVG):

```python
# WRONG — If either zone is NaN, distance becomes NaN and propagates
distance = abs(df['ob_upper'] - df['fvg_lower'])

# RIGHT — Guard against NaN
def compute_zone_distance(df, zone1_upper, zone1_lower, zone2_upper, zone2_lower):
    """Compute distance between two active zones. Returns NaN if either is inactive."""
    both_active = df[zone1_upper].notna() & df[zone2_upper].notna()
    distance = pd.Series(np.nan, index=df.index)
    
    # Distance = min distance between the two zone boundaries
    d1 = abs(df.loc[both_active, zone1_upper] - df.loc[both_active, zone2_lower])
    d2 = abs(df.loc[both_active, zone1_lower] - df.loc[both_active, zone2_upper])
    distance[both_active] = np.minimum(d1, d2)
    
    return distance
```

### Test Suite for NaN Propagation

```python
# tests/test_nan_propagation.py

def test_rsi_nan_does_not_infect_confidence():
    """RSI NaN should not cause confidence to become NaN."""
    df = pd.DataFrame({
        'close': [100, 101, 102, 103, 104],
        'rsi': [np.nan, np.nan, np.nan, np.nan, 45.0],
        'ob_active': [False, False, False, True, True],
    })
    strategy = OrderBlockRetestStrategy()
    df = strategy.generate_signals(df)
    assert not df['confidence'].isna().any(), \
        "NaN in RSI propagated to confidence"
    assert df['signal'].notna().all(), \
        "NaN in RSI propagated to signal"

def test_zone_distance_with_nan():
    """Distance between zones should be NaN (not crash) when one zone is inactive."""
    df = pd.DataFrame({
        'ob_upper': [100.0, np.nan, 100.0],
        'ob_lower': [99.0, np.nan, 99.0],
        'fvg_upper': [101.0, 101.0, np.nan],
        'fvg_lower': [100.5, 100.5, np.nan],
    })
    distance = compute_zone_distance(df, 'ob_upper', 'ob_lower', 'fvg_upper', 'fvg_lower')
    assert distance.iloc[0] == 0.5  # Both active → valid distance
    assert pd.isna(distance.iloc[1])  # OB inactive → NaN
    assert pd.isna(distance.iloc[2])  # FVG inactive → NaN

def test_confidence_never_nan():
    """After generate_signals(), confidence must be 0.0, not NaN, for all rows."""
    # Create a DataFrame with sparse/incomplete data
    df = create_sparse_test_df()
    df = strategy.pre_process(df)  # May produce NaNs in feature columns
    df = strategy.generate_signals(df)
    
    # Confidence should be 0.0 for rows where signal can't fire
    assert (df['confidence'].fillna(-1) >= 0).all(), \
        "Confidence column contains NaN values"
```

---

## 4E: Trap 5 — The Vectorization Bottleneck

### The Trap
Using `iterrows()` or Python `for` loops over DataFrames kills performance when scanning multiple tickers.

### The Fix: Vectorized Operations Only

```python
# WRONG — O(n) Python loop
for idx, row in df.iterrows():
    if row['close'] > row['ema_200']:
        df.at[idx, 'signal'] = 1

# RIGHT — Vectorized, O(1) in Python, O(n) in C
df['signal'] = np.where(df['close'] > df['ema_200'], 1, 0)
```

### Performance Rules for Extraction Layer

1. **No `iterrows()` or `itertuples()` in extractors** — use `np.where`, boolean masks, `.rolling()`, `.shift()`
2. **Zone detection can use vectorized shift comparisons**:
   ```python
   # Instead of looping over every 3-candle window:
   bullish_fvg = (df['low'].shift(0) > df['high'].shift(2))  # C3.low > C1.high
   bearish_fvg = (df['high'].shift(0) < df['low'].shift(2))  # C3.high < C1.low
   ```
3. **For inherently sequential logic (like OB impulse counting)**, use `numba`-accelerated loops or accept a hybrid with a small Cython loop, but never pure Python `for` over 1000+ rows
4. **Use `pd.concat` for building results, never row-by-row append**

### Impulse Detection — The Hard Case

OB impulse detection is inherently sequential (need to count consecutive bullish candles). Two acceptable approaches:

**Option A: Numba-accelerated loop** (recommended)
```python
import numba

@numba.jit(nopython=True)
def _detect_impulse_lengths(close, open_, bearish_mask, max_len):
    """Fast impulse length detection using numba."""
    n = len(close)
    impulse_len = np.zeros(n, dtype=np.int32)
    for i in range(n):
        if bearish_mask[i]:  # This is an OB candidate
            count = 0
            for j in range(i + 1, min(i + 1 + max_len, n)):
                if close[j] > open_[j]:  # Bullish candle
                    count += 1
                else:
                    break
            impulse_len[i] = count
    return impulse_len
```

**Option B: Vectorized with `.rolling()`** (acceptable if max impulse is small)
```python
# For MAX_IMPULSE_LEN=5, unroll the loop:
for offset in range(1, 6):
    df[f'bullish_{offset}'] = (df['close'].shift(-offset) > df['open'].shift(-offset))
df['impulse_len'] = (
    df['bullish_1'].astype(int) + 
    df['bullish_2'].astype(int) + ...  # Only count consecutive
)
```

### Benchmark Requirement
Before committing extraction code, benchmark on 100,000 rows:
```python
def test_extraction_performance():
    df = generate_test_df(100_000)
    start = time.time()
    df = extract_fvgs(df)
    df = extract_order_blocks(df)
    elapsed = time.time() - start
    assert elapsed < 2.0, f"Extraction took {elapsed:.2f}s, target < 2.0s for 100k rows"
```

---

## 4F: Additional Defensive Patterns

### 4F-1: Zone ID Tracking
Each zone must have a unique ID so mitigation can target the exact zone, not all zones:

```python
_zone_counter = 0

def _next_zone_id():
    global _zone_counter
    _zone_counter += 1
    return _zone_counter

# During extraction:
df.loc[formation_mask, 'fvg_zone_id'] = _next_zone_id()
```

### 4F-2: Staleness Decay
Zones should not have infinite lifetime. Add a staleness flag:

```python
df['fvg_staleness'] = (df.index - df.groupby('fvg_zone_id')['fvg_created_at'].transform('first'))
# Strategies can check: df['fvg_staleness'] < 50 to only consider "fresh" zones
```

### 4F-3: Minimum Zone Size
Reject zones that are too thin to be meaningful:

```python
MIN_ZONE_SIZE_RATIO = 0.0005  # 0.05% of price (e.g., $25 for $50,000 BTC)
zone_size = abs(df['fvg_upper'] - df['fvg_lower'])
df.loc[zone_size < df['close'] * MIN_ZONE_SIZE_RATIO, ['fvg_upper', 'fvg_lower']] = np.nan
```

### 4F-4: Duplicate Zone Detection
Prevent the same zone from being detected multiple times:

```python
# After detecting a zone, suppress detection in the next N candles
for i in range(1, 4):
    df.loc[df.index[formation_idx + i], 'fvg_zone_id'] = np.nan  # Suppress nearby duplicates
```

---

## 4G: Code Audit Script

Add a lint script that checks extraction code for known trap patterns:

```python
# scripts/audit_extraction_code.py
import ast
import sys

FORBIDDEN_PATTERNS = [
    ('iterrows()', 'Vectorization bottleneck'),
    ('itertuples()', 'Vectorization bottleneck'),
    ('for idx, row in df', 'Vectorization bottleneck'),
    ('df.at[', 'Scalar assignment in loop — use boolean masking'),
    ('df.loc[idx', 'Scalar assignment in loop — use boolean masking'),
]

def audit_file(filepath):
    with open(filepath) as f:
        source = f.read()
    
    violations = []
    for pattern, risk in FORBIDDEN_PATTERNS:
        if pattern in source:
            violations.append(f"  {risk}: found '{pattern}'")
    
    if violations:
        print(f"FAIL: {filepath}")
        for v in violations:
            print(v)
        return 1
    return 0

exit(sum(audit_file(f) for f in sys.argv[1:]))
```

---

## Phase 4 Validation Gates

1. **Mitigation-Clearing Gate** (replaces No-ffill Gate): `ffill()` must be used for zone persistence but mitigated zones must revert to NaN. Verify no zone survives more than 1 candle past its mitigation point.
2. **No iterrows Gate**: `grep -r "iterrows\|itertuples" app/core/` returns empty (except in comments/tests)
3. **Lookahead Gate**: For any zone, `active == True` at index `i` implies zone creation data comes from indices `< i`
4. **Mitigation Gate**: After mitigation, zone columns are NaN for all subsequent candles
5. **NaN Gate**: `df['confidence']` and `df['signal']` contain zero NaN values after `generate_signals()`
6. **Performance Gate**: 100k-row extraction completes in < 2 seconds
7. **Mitigation Type Gate**: Every extractor function has `mitigation_type` parameter and honors it
