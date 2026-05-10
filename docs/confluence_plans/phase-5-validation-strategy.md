# Phase 5: Validation Strategy — Implementation Plan

## Objective

Prove the extraction layer is honest before trusting the strategy layer. Every extractor must be isolated, tested against known data, and manually verified against TradingView before any strategy consumes its output.

---

## 5A: Validation Philosophy

> "A strategy is only as honest as its extractors. If `fvg_active` flips to `True` on the wrong candle, the strategy is trading a phantom. Validate the eyes before you trust what they see."

### The Chain of Trust
```
Binance Raw Data → Extractor → Feature Columns → Strategy → Signal
                                        ↑
                                  VALIDATE HERE
```
If the extractor produces wrong `fvg_active` values, no amount of strategy tuning will fix it.

---

## 5B: Isolated Extractor Tests

### 5B-1: Test Data Generation

Create a utility that generates known-price DataFrames with deliberate patterns:

```python
# tests/test_data_factory.py

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def create_bullish_fvg_df() -> pd.DataFrame:
    """
    Create a DataFrame with a known bullish FVG.
    Pattern: C1 high < C2 close, C3 low > C1 high (gap between C1 and C3)
    
    C1: open=100, high=102, low=98,  close=101  (bullish)
    C2: open=101, high=105, low=100, close=104  (bullish impulse)
    C3: open=104, high=108, low=103, close=106  (bullish, gap left between C1.high=102 and C3.low=103)
    
    Bullish FVG zone: upper=C3.low=103, lower=C1.high=102
    """
    ...
    
def create_bearish_fvg_df() -> pd.DataFrame:
    """
    Bearish FVG: C3.high < C1.low
    FVG zone: upper=C1.low, lower=C3.high
    """
    ...

def create_mitigated_fvg_df() -> pd.DataFrame:
    """
    FVG forms, then 3 candles later, price drops back into the gap.
    fvg_active should be False after that candle.
    """
    ...

def create_multi_zone_df() -> pd.DataFrame:
    """Multiple overlapping FVGs and OBs."""
    ...

def create_cho_ch_event_df() -> pd.DataFrame:
    """Known swing points followed by a body close break."""
    ...

def create_no_event_df() -> pd.DataFrame:
    """Ranging market with no FVGs, no OBs, no ChoCh."""
    ...

def create_binance_real_data(symbol='BTCUSDT', timeframe='1h', limit=500) -> pd.DataFrame:
    """Fetch real Binance data for parity testing."""
    ...
```

### 5B-2: FVG Extractor Tests

```python
# tests/test_extract_fvgs.py

class TestExtractFVGs:
    
    def test_bullish_fvg_detection(self):
        """Bullish FVG detected when C3.low > C1.high."""
        df = create_bullish_fvg_df()
        df = extract_fvgs(df)
        
        # FVG should be active on candle 4 (index 3), NOT candle 3 (index 2)
        # Because active flag shifts by 1 (lookahead bias prevention)
        assert not df.loc[2, 'fvg_active'], "FVG active on formation candle"
        assert df.loc[3, 'fvg_active'], "FVG not active after formation"
        assert df.loc[3, 'fvg_upper'] == 103.0
        assert df.loc[3, 'fvg_lower'] == 102.0
    
    def test_bearish_fvg_detection(self):
        """Bearish FVG detected when C3.high < C1.low."""
        ...
    
    def test_no_false_positive(self):
        """Ranging market should not produce FVGs."""
        df = create_no_event_df()
        df = extract_fvgs(df)
        assert not df['fvg_active'].any(), "False FVG detected in ranging market"
    
    def test_mitigation_wicks(self):
        """FVG mitigated when wick touches zone boundary."""
        df = create_mitigated_fvg_df()
        df = extract_fvgs(df, mitigation_type='wick')
        
        mitigated_idx = df[df['low'] <= df['fvg_lower']].index[0]
        assert not df.loc[mitigated_idx, 'fvg_active'], "FVG still active after wick mitigation"
        assert df.loc[mitigated_idx:, 'fvg_active'].sum() == 0, "FVG re-activated after mitigation"
    
    def test_mitigation_body(self):
        """FVG NOT mitigated by wick when mitigation_type='body'."""
        df = create_mitigated_fvg_df()  # Wick touches but body doesn't
        df = extract_fvgs(df, mitigation_type='body')
        # The wick touch should NOT mitigate when type is body
        wick_touch_idx = df[df['low'] <= df['fvg_lower']].index[0]
        assert df.loc[wick_touch_idx, 'fvg_active'], "FVG incorrectly mitigated by wick (body mode)"
    
    def test_ffill_leak_prevention(self):
        """Mitigated FVG must not appear active in future candles."""
        df = create_mitigated_fvg_df()
        df = extract_fvgs(df)
        
        mitigated_idx = df[df['low'] <= df['fvg_lower']].index[0]
        future_active = df.loc[mitigated_idx + 1:, 'fvg_active']
        assert not future_active.any(), f"FVG leaked past mitigation: {future_active.sum()} active rows"
    
    def test_lookahead_bias_prevention(self):
        """FVG active flag must not use future data."""
        # Create a DataFrame where the FVG would only be detectable
        # AFTER the formation candle closes
        df = create_bullish_fvg_df()
        half_df = df.iloc[:3].copy()  # Only first 3 candles (formation incomplete)
        
        # Verify extract_fvgs on partial data doesn't mark zone as active
        result = extract_fvgs(half_df)
        # With only 3 candles, the shift(1) should prevent activation
        assert not result.iloc[-1]['fvg_active'], "Lookahead: zone active before candle close"
    
    def test_zone_contract_compliance(self):
        """Every zone must have the contract columns."""
        df = create_bullish_fvg_df()
        df = extract_fvgs(df)
        
        required_cols = ['fvg_active', 'fvg_upper', 'fvg_lower', 'fvg_volume', 'fvg_created_at']
        for col in required_cols:
            assert col in df.columns, f"Missing contract column: {col}"
        
        # Type checks
        assert df['fvg_active'].dtype == bool
        assert df['fvg_upper'].dtype == np.float64
        assert df['fvg_lower'].dtype == np.float64
```

### 5B-3: Order Block Extractor Tests

```python
# tests/test_extract_order_blocks.py

class TestExtractOrderBlocks:
    
    def test_bullish_ob_detection(self):
        """Bullish OB = last bearish candle before bullish impulse."""
        ...
    
    def test_impulse_min_length(self):
        """OB requires minimum impulse length (default 2)."""
        ...
    
    def test_atr_displacement_gate(self):
        """Impulse must exceed ATR * displacement threshold."""
        ...
    
    def test_bos_requirement(self):
        """OB must break structure (impulse exceeds prior swing)."""
        ...
    
    def test_ob_mitigation_body_close(self):
        """Bullish OB mitigated when close drops below ob_low."""
        ...
    
    def test_ob_cooldown(self):
        """OB in cooldown should not be treated as active for retest."""
        ...
```

### 5B-4: Temporal Event Tests

```python
# tests/test_extract_events.py

class TestChoChDetection:
    
    def test_bullish_choch(self):
        """Bearish trend then body close above last swing high → ChoCh."""
        ...
    
    def test_bos_vs_choch(self):
        """BOS in trend direction, ChoCh against trend."""
        ...
    
    def test_wick_only_no_choch(self):
        """Wick through swing without body close → NOT a ChoCh."""
        ...
    
    def test_recent_rolling_memory(self):
        """event_choch_bullish_recent stays True for rolling(10) candles."""
        ...

class TestVolumeClimaxDetection:
    
    def test_volume_climax_trigger(self):
        """Volume > 2x volume_ma triggers climax event."""
        ...
    
    def test_bullish_climax(self):
        """Climax + bullish close → bullish climax."""
        ...
```

---

## 5C: TradingView Manual Verification Protocol

### Step 1: Export Test Data

```python
# scripts/export_for_tradingview_verification.py
"""
Export a Binance DataFrame with extracted FVGs, OBs, and events
to CSV for side-by-side comparison with TradingView.
"""

import pandas as pd
from app.core.market_structure import extract_fvgs, extract_order_blocks
from app.core.events import detect_choch
from app.core.data_utils import get_finalized_candles

def export_verification_data(symbol='BTCUSDT', timeframe='1h', limit=200):
    df = get_finalized_candles(symbol, timeframe, limit=limit)
    df = extract_fvgs(df)
    df = extract_order_blocks(df)
    df = detect_choch(df)
    
    # Add human-readable columns for manual verification
    df['fvg_readable'] = df.apply(
        lambda r: f"FVG {r['fvg_lower']:.2f}-{r['fvg_upper']:.2f}" 
        if r['fvg_active'] else '', axis=1
    )
    df['ob_readable'] = df.apply(
        lambda r: f"OB {r['ob_lower']:.2f}-{r['ob_upper']:.2f} ({r.get('ob_direction','')})" 
        if r['ob_active'] else '', axis=1
    )
    
    output_path = f'verification_{symbol}_{timeframe}_{pd.Timestamp.now():%Y%m%d_%H%M}.csv'
    df.to_csv(output_path, index=False)
    print(f"Exported to {output_path}")
    print(f"FVGs detected: {df['fvg_active'].sum()}")
    print(f"OBs detected: {df['ob_active'].sum()}")
    print(f"ChoCh events: {df['event_choch_bullish'].sum()} bullish, {df['event_choch_bearish'].sum()} bearish")

if __name__ == '__main__':
    export_verification_data('BTCUSDT', '1h')
    export_verification_data('ETHUSDT', '4h')
```

### Step 2: Manual Verification Checklist

For each exported CSV, open the same chart on TradingView and verify:

#### FVG Verification
- [ ] Find the first `fvg_active == True` row in the CSV
- [ ] Note the `open_time` of that candle
- [ ] On TradingView, navigate to that exact candle
- [ ] Visually confirm: Is there a gap between C1 high and C3 low (bullish) or C1 low and C3 high (bearish)?
- [ ] Verify: Does `fvg_active` become `True` on the candle AFTER the gap forms? (Not the formation candle itself)
- [ ] Verify: When price touches the FVG zone later, does `fvg_active` become `False` on exactly that candle?
- [ ] Verify: No `fvg_active == True` rows exist after mitigation

#### Order Block Verification
- [ ] Find the first `ob_active == True` row
- [ ] Verify: The OB candle is a bearish candle before a bullish impulse (for bullish OB) or vice versa
- [ ] Verify: The impulse is at least `impulse_min` candles long
- [ ] Verify: The impulse breaks the prior structure (BOS)
- [ ] Verify: `ob_active` becomes `False` when a candle closes beyond the block

#### ChoCh Verification
- [ ] Find a `event_choch_bullish == True` row
- [ ] Verify: The prevailing trend was bearish (lower highs, lower lows)
- [ ] Verify: This candle's body closed above the most recent swing high
- [ ] Verify: `event_choch_bullish_recent` stays `True` for the next 10 candles

#### Edge Case Verification
- [ ] Find a wick-only piercing of a swing level — verify it does NOT trigger ChoCh (body close required)
- [ ] Find a ranging market section — verify no false FVGs or OBs
- [ ] Find a zone that forms but is immediately invalidated — verify `active` only True for 1 candle

### Step 3: Document Discrepancies

Create a `verification_results.md` file documenting any discrepancies found:

```markdown
# Verification Results — 2026-05-10

## BTCUSDT 1h (200 candles)

### FVG Detection
| CSV Row | open_time | Expected | Actual | Match? |
|---------|-----------|----------|--------|--------|
| 45 | 2026-05-09 14:00 | Bullish FVG at 65100-65200 | Bullish FVG at 65110-65205 | ~ |
| 78 | 2026-05-09 20:00 | Mitigation at 20:00 | Mitigation at 21:00 | OFF BY 1 |

### OB Detection
...

## Discrepancies Found
1. **Mitigation timing off by 1 candle**: FVG at row 78 was mitigated at 20:00 on TV but marked at 21:00 in CSV.
   - Root cause: shift(1) delay adding an extra candle
   - Fix: TBD
```

---

## 5D: Invalidation Test Suite

Test the extractors on deliberately adversarial data:

### 5D-1: Spectacular Failure Scenarios

```python
# tests/test_invalidation_scenarios.py

class TestInvalidationScenarios:
    
    def test_ob_fails_spectacularly(self):
        """
        Scenario: OB forms at resistance. Price breaks through with a massive
        engulfing candle. ob_active should flip to False immediately.
        """
        ...
    
    def test_fvg_sliced_through(self):
        """
        Scenario: FVG forms during low volume. High volume spike slices
        completely through the gap in one candle. fvg_active should die.
        """
        ...
    
    def test_double_mitigation(self):
        """
        Scenario: Zone mitigated, price reverses back into zone.
        Zone should NOT re-activate (already dead).
        """
        ...
    
    def test_cho_ch_in_ranging_market(self):
        """
        Scenario: Choppy ranging market with many swing points.
        No real trend exists. ChoCh should NOT fire.
        """
        ...

    def test_same_candle_formation_and_mitigation(self):
        """
        Scenario (rare but real): A candle both creates an FVG AND mitigates
        it within the same candle (massive wick on both sides).
        The zone should never be marked active.
        """
        ...
    
    def test_flat_market_no_zones(self):
        """
        Scenario: Dead flat market (all opens = closes).
        No zones should form at all.
        """
        df = pd.DataFrame({
            'open': [100.0] * 50,
            'high': [100.0] * 50,
            'low': [100.0] * 50,
            'close': [100.0] * 50,
            'volume': [1.0] * 50,
        })
        df = extract_fvgs(df)
        assert not df['fvg_active'].any()
        df = extract_order_blocks(df)
        assert not df['ob_active'].any()
```

### 5D-2: Real-World Failure Backtest

Run extractors on historical data from a period known to be difficult:

```python
# scripts/test_extractors_on_historical.py

def test_on_crash_data():
    """
    Test extractors on:
    - March 2020 COVID crash (massive volatility, many zones forming and breaking)
    - May 2021 crash (Elon Musk, rapid reversals)
    - November 2022 FTX collapse (extreme wick action)
    
    These periods expose edge cases: fast mitigation, wick-only breaches,
    overlapping zones, and structural shifts.
    """
    periods = [
        ('2020-03-10', '2020-03-15', 'COVID Crash'),
        ('2021-05-15', '2021-05-22', 'Elon Crash'),
        ('2022-11-06', '2022-11-12', 'FTX Collapse'),
    ]
    
    for start, end, label in periods:
        df = get_finalized_candles('BTCUSDT', '1h', start_date=start, end_date=end)
        df = extract_fvgs(df)
        df = extract_order_blocks(df)
        df = detect_choch(df)
        
        # Sanity checks
        fvg_count = df['fvg_active'].sum()
        ob_count = df['ob_active'].sum()
        choch_count = df['event_choch_bullish'].sum() + df['event_choch_bearish'].sum()
        
        print(f"{label}: FVGs={fvg_count}, OBs={ob_count}, ChoChs={choch_count}")
        
        # No zone should be active for more than 200 consecutive candles
        # (institutional zones don't last forever in high volatility)
        fvg_streaks = df['fvg_active'].astype(int).groupby(
            (df['fvg_active'] != df['fvg_active'].shift()).cumsum()
        ).cumsum()
        max_streak = fvg_streaks.max()
        assert max_streak < 500, f"FVG active for {max_streak} consecutive candles in {label}"
```

---

## 5E: Integration Test — Extractors → Strategies → Signals

**NOTE**: This test requires strategies to have `generate_signals()` implemented.
The 13 existing strategies still use the legacy `scan()` interface. This test
becomes active AFTER Phase 2 strategy rewrites are complete, not before.

For now, use the standalone extractor tests (5B) to validate extractors in isolation.

Once extractors are validated in isolation, test the full pipeline:

```python
# tests/test_integration_pipeline.py

class TestFullPipeline:
    
    def test_extractors_to_strategy_e2e(self):
        """
        End-to-end: Raw data → extractors → pre_process → generate_signals → SetupSignal
        
        Verifies:
        1. Extractors produce valid feature columns
        2. pre_process loads them correctly
        3. generate_signals produces non-zero confidence for valid setups
        4. No NaN in final confidence/signal columns
        """
        from app.strategies.order_block_retest import OrderBlockRetestStrategy
        
        df = get_finalized_candles('BTCUSDT', '4h', limit=1000)
        strategy = OrderBlockRetestStrategy()
        
        # Phase 1: Extractors
        df = extract_fvgs(df)
        df = extract_order_blocks(df)
        df = detect_choch(df)
        
        # Phase 2: Strategy pre_process
        df = strategy.pre_process(df)
        
        # Phase 3: Generate signals
        df = strategy.generate_signals(df)
        
        # Assertions
        assert df['confidence'].notna().all(), "NaN in confidence"
        assert df['signal'].notna().all(), "NaN in signal"
        assert df['signal'].sum() > 0, "No signals generated"
        assert df['confidence'].max() <= 1.0, "Confidence > 1.0"
        
        # Every signal row should have non-NaN confidence
        signal_rows = df[df['signal'] == 1]
        assert (signal_rows['confidence'] >= strategy.min_confidence).all(), \
            "Signal with confidence below threshold"
    
    def test_all_strategies_produce_signals(self):
        """
        Smoke test: Every enabled strategy must produce at least 1 signal
        on 2000 candles of real BTCUSDT 4h data.
        
        Strategies that produce 0 signals have a logic bug or threshold too high.
        """
        from app.core.strategy_loader import registry
        
        df = get_finalized_candles('BTCUSDT', '4h', limit=2000)
        
        for strategy in registry.get_enabled():
            if '4h' not in strategy.timeframes:
                continue
            
            df_copy = df.copy()
            df_copy = strategy.pre_process(df_copy)
            df_copy = strategy.generate_signals(df_copy)
            
            signal_count = df_copy['signal'].sum()
            print(f"  {strategy.name}: {signal_count} signals")
            
            # At least 1 signal per 2000 candles (0.05% hit rate minimum)
            assert signal_count >= 1, \
                f"{strategy.name} produced 0 signals on 2000 candles — possible logic error"
```

---

## 5F: Continuous Validation (CI/CD)

Add to the CI pipeline:

```yaml
# .github/workflows/validate-extractors.yml
name: Validate Extractors

on:
  push:
    paths:
      - 'backend/app/core/market_structure.py'
      - 'backend/app/core/events.py'
      - 'backend/app/core/indicators.py'
      - 'backend/app/core/sr_engine.py'

jobs:
  extractor-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run extractor unit tests
        run: pytest tests/test_extract_fvgs.py tests/test_extract_order_blocks.py tests/test_extract_events.py -v
      - name: Run defensive coding tests
        run: pytest tests/test_defensive_coding.py tests/test_nan_propagation.py -v
      - name: Run invalidation scenarios
        run: pytest tests/test_invalidation_scenarios.py -v
      - name: Audit for forbidden patterns
        run: python scripts/audit_extraction_code.py backend/app/core/market_structure.py backend/app/core/events.py
      - name: Run performance benchmark
        run: pytest tests/test_extraction_performance.py -v
```

---

## Phase 5 Validation Gates

Extractor validation gates (apply NOW, before strategy rewrites):
1. **Extractor Isolation Gate**: All extractor unit tests pass
2. **Invalidation Gate**: All adversarial scenarios pass
3. **Performance Gate**: 100k-row extraction completes in < 2 seconds
4. **Contract Compliance Gate**: Every zone has the Universal Zone Contract columns

Integration gates (apply AFTER Phase 2 strategy rewrites):
5. **Smoke Test Gate**: Full pipeline (extractors → strategy → signal) produces valid output on real Binance data
6. **TradingView Parity Gate**: Manual verification of 5+ FVGs, 3+ OBs, 3+ ChoCh events against TradingView
7. **CI Gate**: All validation tests run in CI pipeline on push to extraction layer files
