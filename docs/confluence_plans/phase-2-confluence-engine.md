# Phase 2: Generalized Confluence Engine — Implementation Plan

## Objective

Transform `BaseStrategy` from a bare abstract class into a feature-aware orchestrator. Replace rigid boolean AND-gate strategy logic with weighted scoring matrices. Solve the "0 Trades Curse of Dimensionality" where requiring 5 simultaneous conditions produces near-zero signals.

---

## 2A: BaseStrategy Orchestrator Refactor

### Current State
`BaseStrategy` at `app/core/base_strategy.py` is an ABC with:
- Abstract `scan(symbol, timeframe, candles, indicators, sr_zones, htf_candles)` 
- SL/TP calculators
- No feature awareness, no preprocessing

### Target State

```python
class BaseStrategy(ABC):
    name: str
    description: str
    timeframes: list[str]
    version: str
    min_confidence: float = 0.50
    
    # ── Feature Declaration ──
    # Subclasses declare what they consume. The orchestrator provides it.
    required_features: list[str] = []  
    # Valid values: 'rsi', 'ema', 'macd', 'bb', 'atr', 'fvg', 'ob', 'sr', 
    #               'choch', 'bos', 'volume_climax', 'liquidity_sweep'
    
    # ── Configuration ──
    feature_config: dict = {}  
    # e.g., {'rsi_period': 14, 'ema_periods': [9, 21, 50, 200], 'fvg_mitigation': 'wick'}
    
    # ── Orchestration (called by StrategyRunner, NOT by subclasses) ──
    @classmethod
    def get_required_lookback(cls) -> int:
        """Returns minimum candles needed based on declared features."""
        if any(f in cls.required_features for f in ['ob', 'fvg', 'sr']):
            return 1000  # Spatial zones need deep history
        if 'ema_200' in cls.required_features or any(
            cls.feature_config.get('ema_periods', []) and 
            max(cls.feature_config.get('ema_periods', [0])) >= 200
        ):
            return 300
        return 150  # Default safe buffer
    
    @classmethod
    def pre_process(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        Dynamically loads only the features this specific strategy requires.
        
        This is called ONCE per strategy per candle close, not once per signal scan.
        The resulting DataFrame is passed to scan().
        """
        config = cls.feature_config
        
        # ── Continuous State ──
        if 'rsi' in cls.required_features:
            df['rsi'] = compute_rsi(df['close'], period=config.get('rsi_period', 14))
        if 'ema' in cls.required_features:
            periods = config.get('ema_periods', [9, 21, 50, 200])
            for p in periods:
                df[f'ema_{p}'] = compute_ema(df['close'], period=p)
        if 'macd' in cls.required_features:
            macd = compute_macd(df['close'])
            df['macd_line'] = macd['macd_line']
            df['macd_signal'] = macd['macd_signal']
            df['macd_histogram'] = macd['macd_histogram']
        if 'bb' in cls.required_features:
            bb = compute_bollinger(df['close'])
            df['bb_upper'] = bb['bb_upper']
            df['bb_middle'] = bb['bb_middle']
            df['bb_lower'] = bb['bb_lower']
        if 'atr' in cls.required_features:
            df['atr'] = compute_atr(df['high'], df['low'], df['close'], 
                                     period=config.get('atr_period', 14))
        if 'volume_ma' in cls.required_features:
            df['volume_ma'] = compute_volume_ma(df['volume'], 
                                                 period=config.get('volume_ma_period', 20))
        
        # ── Spatial State (Zones) ──
        if 'fvg' in cls.required_features:
            df = extract_fvgs(df, mitigation_type=config.get('fvg_mitigation', 'wick'))
        if 'ob' in cls.required_features:
            df = extract_order_blocks(df)
        if 'sr' in cls.required_features:
            df = detect_active_sr_zones(df)  # New function from refactored sr_engine
        
        # ── Temporal State (Events) ──
        if 'choch' in cls.required_features or 'bos' in cls.required_features:
            events = detect_choch(df)
            for col in events.columns:
                df[col] = events[col]
        if 'volume_climax' in cls.required_features:
            climax = detect_volume_climax(df)
            for col in climax.columns:
                df[col] = climax[col]
        if 'liquidity_sweep' in cls.required_features:
            sweep = detect_liquidity_sweep(df)
            for col in sweep.columns:
                df[col] = sweep[col]
        
        return df
    
    # ── Abstract: Subclass implements scoring logic, NOT extraction ──
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Pure logic. Receives a pre-processed DataFrame with all requested features.
        Must return DataFrame with at minimum:
            df['signal'] — 1 or 0
            df['confidence'] — 0.0 to 1.0
        May return additional columns for context (direction, notes, etc.).
        """
        ...
    
    # ── Legacy compatibility (temporary, phased out) ──
    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        """
        Legacy wrapper. Converts old-style inputs to DataFrame, calls pre_process
        and generate_signals, converts back to SetupSignal.
        This is REMOVED in Phase 2 completion.
        """
        ...
```

### StrategyRunner Changes

`StrategyRunner` (`app/core/strategy_runner.py`) must be updated to call the new pipeline:

```python
class StrategyRunner:
    def run_single_scan(self, strategy, symbol, timeframe):
        """
        New flow:
        1. Get required lookback from strategy
        2. Fetch finalized candles from DB
        3. Call strategy.pre_process(df) — adds all feature columns
        4. Call strategy.generate_signals(df) — returns signal + confidence
        5. Take the LAST row's signal/confidence
        6. If signal == 1 and confidence >= min_confidence, build SetupSignal
        """
        lookback = strategy.get_required_lookback()
        df = get_finalized_candles(symbol, timeframe, limit=lookback)
        
        if len(df) < strategy.get_min_candles():
            return None  # Insufficient data
        
        df = strategy.pre_process(df)
        df = strategy.generate_signals(df)
        
        last = df.iloc[-1]
        if last.get('signal', 0) != 1:
            return None
        if last.get('confidence', 0) < strategy.min_confidence:
            return None
        
        # Build SetupSignal from the last row
        ...
```

---

## 2B: Weighted Scoring Matrix Pattern

### The Problem: Curse of Dimensionality

Current strategies use rigid AND gates across 5+ conditions:
```python
# Current pattern (broken)
if (ema_cross and rsi_in_range and volume_above_ma and sr_zone_near and macd_confirm):
    signal = True  # Fires ~0.05% of the time
```

If each condition has a 40% chance of being true independently, the AND of 5 conditions fires 0.4^5 = 1% of the time. Add any noise and it drops to 0%.

### The Solution: Base Requirements + Additive Modifiers

```python
def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
    """
    Pattern for ALL strategies in the new system.
    
    Step 1: Define absolute base requirements (MUST be true)
    Step 2: Start confidence at base level (e.g., 0.50)
    Step 3: Add modifiers for each confluence factor
    Step 4: Trigger signal when confidence crosses threshold
    """
    # ── Step 1: Base Requirement (Hard Gate) ──
    # Only 1-2 absolute requirements. Everything else is additive.
    base_setup = df['ob_active'] & (df['close'] > df['ema_200'])
    
    # ── Step 2: Base Confidence ──
    df['confidence'] = np.where(base_setup, 0.50, 0.0)
    
    # ── Step 3: Additive Confluence (Soft Gates) ──
    # Each modifier adds to confidence ONLY if base_setup is true
    
    # FVG overlap with OB zone
    fvg_overlap = df['fvg_active'] & (df['fvg_lower'] <= df['ob_upper'])
    df['confidence'] += np.where(base_setup & fvg_overlap, 0.20, 0.0)
    
    # RSI in oversold territory
    df['confidence'] += np.where(base_setup & (df['rsi'] < 30), 0.15, 0.0)
    
    # Recent bullish ChoCh
    df['confidence'] += np.where(base_setup & (df['event_choch_bullish_recent'] == 1), 0.10, 0.0)
    
    # Volume confirmation
    df['confidence'] += np.where(base_setup & (df['volume'] > df['volume_ma']), 0.05, 0.0)
    
    # ── Step 4: Signal Trigger ──
    # Confidence threshold is configurable per strategy
    df['signal'] = np.where(df['confidence'] >= self.threshold, 1, 0)
    df['direction'] = np.where(df['signal'] == 1, 'LONG', None)
    
    return df
```

### Confidence Budget Design Rules

| Condition Type | Max Weight | Rationale |
|---------------|------------|-----------|
| Base requirement | 0.50 | Must be > 0 but < threshold to allow modifiers to matter |
| Primary confluence (zone overlap) | 0.20 | Strong signal, big weight |
| Secondary confluence (RSI, MACD) | 0.15 | Confirming, moderate weight |
| Tertiary confluence (volume, ChoCh) | 0.10 | Nice-to-have, small weight |
| Minor confluence (HTF alignment) | 0.05 | Edge, minimal weight |
| **Threshold** | **0.75** | Requires base + at least 2 modifiers |

The threshold should be tunable per strategy via `strategy.min_confidence`.

---

## 2C: Rewriting Existing Strategies

Each of the 13 strategies must be rewritten to use the new pattern. Here is the migration plan for each:

### Strategy Migration Map

| Strategy | Base Requirement | Modifiers | Threshold |
|----------|-----------------|-----------|-----------|
| **EMA Crossover** | EMA 9 crosses EMA 21 | Close > EMA 50 (+0.20), Close > EMA 200 (+0.10), Volume > MA (+0.10), RSI 40-60 (+0.05) | 0.75 |
| **RSI Reversal** | RSI crosses 30/70 threshold | MACD confirmation (+0.15), Volume (+0.10), Near S/R (+0.10), EMA 200 alignment (+0.10) | 0.70 |
| **MACD Momentum** | MACD crosses signal | Histogram confirmation (+0.15), Momentum buildup (+0.10), EMA 50 (+0.10), Volume (+0.10) | 0.70 |
| **Bollinger Squeeze** | Squeeze state detected | Breakout (+0.15), Volume spike (+0.10), EMA alignment (+0.10), Width expansion (+0.10) | 0.70 |
| **SR Rejection** | Wick enters S/R zone | Body closes opposite (+0.15), Zone strength (+0.10), Volume (+0.10), RSI (+0.05) | 0.75 |
| **SR Breakout** | Close breaks S/R zone | Strong body (+0.15), Volume (+0.10), EMA alignment (+0.10), Retest (+0.10) | 0.70 |
| **Fibonacci Retracement** | Price near fib level | S/R confluence (+0.20), RSI (+0.10), Volume (+0.10), Candlestick pattern (+0.05) | 0.75 |
| **SMC Liquidity Sweep** | Sweep detected | Close reversal (+0.20), Volume (+0.10), FVG nearby (+0.10), RSI (+0.05) | 0.70 |
| **SMC Structure Shift** | ChoCh/BOS event | Volume (+0.15), Strong body (+0.10), RSI momentum (+0.10), FVG (+0.05) | 0.75 |
| **Order Block Retest** | OB active + price in zone | FVG present (+0.15), RSI (+0.10), Volume (+0.10), Impulse strength (+0.05) | 0.70 |
| **FVG Mitigation** | FVG active + price in FVG | OB backing (+0.20), RSI (+0.10), Rejection wick (+0.10), Volume (+0.05) | 0.70 |
| **Trend Pullback Confluence** | EMA stack aligned | RSI hook (+0.15), FVG nearby (+0.15), Volume (+0.10), S/R (+0.10) | 0.75 |
| **Volume Climax** | Climax detected | Reversal pattern (+0.20), RSI extreme (+0.15), S/R nearby (+0.10), FVG (+0.05) | 0.70 |

### Rewrite Template

Every strategy follows this exact skeleton:

```python
"""
{Strategy Name} — Confluence Engine Edition

Phase 2 rewrite: Pure logic gates and confidence scoring.
All mathematical extraction delegated to app/core/ extraction layer.
"""

from app.core.base_strategy import BaseStrategy
import numpy as np

class {StrategyName}(BaseStrategy):
    name = "{Human Name}"
    description = "{Description}"
    timeframes = ["15m", "1h", "4h"]
    version = "3.0"  # Bump major for Phase 2 rewrite
    min_confidence = 0.70
    
    # Feature declaration
    required_features = ['rsi', 'ema', 'atr']  # Only what this strategy uses
    feature_config = {
        'rsi_period': 14,
        'ema_periods': [9, 21, 50, 200],
        'atr_period': 14,
    }
    
    def generate_signals(self, df):
        """Weighted scoring matrix."""
        
        # Step 1: Base requirements
        ema_cross_up = (df['ema_9'] > df['ema_21']) & (df['ema_9'].shift(1) <= df['ema_21'].shift(1))
        base_setup = ema_cross_up
        
        # Step 2: Base confidence
        df['confidence'] = np.where(base_setup, 0.50, 0.0)
        
        # Step 3: Additive modifiers
        df['confidence'] += np.where(base_setup & (df['close'] > df['ema_50']), 0.20, 0.0)
        df['confidence'] += np.where(base_setup & (df['close'] > df['ema_200']), 0.10, 0.0)
        df['confidence'] += np.where(base_setup & (df['volume'] > df['volume_ma']), 0.10, 0.0)
        
        rsi_ok = df['rsi'].between(40, 60)
        df['confidence'] += np.where(base_setup & rsi_ok, 0.05, 0.0)
        
        # Step 4: Trigger
        df['signal'] = np.where(df['confidence'] >= self.min_confidence, 1, 0)
        df['direction'] = np.where(df['signal'] == 1, 'LONG', None)
        
        return df
    
    # SL/TP remain mostly unchanged
    def calculate_sl(self, signal, candles, atr): ...
    def calculate_tp(self, signal, candles, atr, sr_zones=None): ...
```

---

## 2D: NaN Guard in Scoring

**Critical**: Every use of an indicator value in scoring MUST guard against NaN.

```python
# WRONG — NaN < 30 is False, silently skipping signals
df['confidence'] += np.where(base_setup & (df['rsi'] < 30), 0.15, 0.0)

# RIGHT — Explicit NaN handling
rsi_oversold = df['rsi'].notna() & (df['rsi'] < 30)
df['confidence'] += np.where(base_setup & rsi_oversold, 0.15, 0.0)

# Helper pattern (add to base_strategy.py)
@staticmethod
def _safe_condition(series, condition_fn, default=False):
    """Apply condition to series, treating NaN as default."""
    valid = series.notna()
    result = pd.Series(default, index=series.index)
    result[valid] = condition_fn(series[valid])
    return result
```

---

## 2E: StrategyRunner Pipeline Update

`StrategyRunner` at `app/core/strategy_runner.py` needs a second execution path:

```python
class StrategyRunner:
    
    @staticmethod
    def run_single_scan_v2(strategy, symbol, timeframe, 
                            min_confidence_override=None) -> Optional[SetupSignal]:
        """
        Phase 2 execution path.
        Uses DataFrame-based pipeline with feature extraction.
        """
        # 1. Fetch data
        lookback = strategy.get_required_lookback()
        df = get_finalized_candles(symbol, timeframe, limit=lookback)
        
        if len(df) < strategy.get_min_candles():
            return None
        
        # 2. Pre-process (add features)
        df = strategy.pre_process(df)
        
        # 3. Generate signals
        df = strategy.generate_signals(df)
        
        # 4. Extract last row
        last = df.iloc[-1]
        if last.get('signal', 0) != 1:
            return None
        
        confidence = last.get('confidence', 0)
        threshold = min_confidence_override or strategy.min_confidence
        if confidence < threshold:
            return None
        
        # 5. Build SetupSignal
        direction = last.get('direction', 'LONG')
        entry = last['close']
        
        # Calculate SL/TP
        # We need candles for this — pass the last N rows as Candle objects
        # or refactor calculate_sl/tp to accept DataFrame rows
        ...
        
        return SetupSignal(
            strategy_name=strategy.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=confidence,
            entry=entry,
            ...
        )
```

---

## Trap Defenses in Phase 2

### T3: Lookback Horizon (Memory Leak)
**Fixed by**: `get_required_lookback()` in BaseStrategy.

**How it works**:
- When strategy declares `required_features = ['ob', 'fvg']`, `get_required_lookback()` returns 1000
- This forces `DataFetcher` to pull 1000 candles from DB, not 100
- An OB formed at candle 450 is visible to the strategy
- Without this, using the old `limit=50` would miss 90% of valid OBs

**Validation**: Verify that `get_required_lookback()` returns the correct value for each strategy:
```python
def test_lookback_for_spatial_strategies():
    class TestStrategy(BaseStrategy):
        required_features = ['ob', 'fvg']
    assert TestStrategy.get_required_lookback() >= 500
```

### T1: Live Candle Poisoning
**Fixed by**: `get_finalized_candles()` used in the data fetch step of `run_single_scan_v2()`.

### T2: Gap-Heal Race Condition
**Fixed by**: The gap heal must complete BEFORE `run_single_scan_v2()` is called. The `LiveScanner._on_candle_close()` orchestrates this ordering.

---

## Implementation Sequence

### Week 1: Base Infrastructure
1. Refactor `BaseStrategy` class — add `required_features`, `feature_config`, `pre_process()`, `get_required_lookback()`, `generate_signals()`
2. Create `app/core/data_utils.py` with `get_finalized_candles()`
3. Write `StrategyRunner.run_single_scan_v2()`
4. Keep `run_single_scan()` as legacy path until all strategies are migrated

### Week 2: Strategy Rewrites (Batch 1 — Simple)
1. EMA Crossover (simplest, good test case)
2. RSI Reversal
3. MACD Momentum
4. Bollinger Squeeze

### Week 3: Strategy Rewrites (Batch 2 — Zone-Based)
5. SR Rejection
6. SR Breakout
7. Fibonacci Retracement
8. Trend Pullback Confluence

### Week 4: Strategy Rewrites (Batch 3 — SMC)
9. SMC Structure Shift
10. SMC Liquidity Sweep
11. Order Block Retest
12. FVG Mitigation
13. Volume Climax

### Week 5: Cleanup
1. Remove legacy `scan()` from BaseStrategy
2. Remove legacy `run_single_scan()` from StrategyRunner
3. Update `LiveScanner._on_candle_close()` to use v2 pipeline
4. Full integration test

---

## Phase 2 Validation Gates

1. **Feature Loading Gate**: Every strategy's `pre_process()` produces a DataFrame with all declared features present and non-empty
2. **No Math in Strategies Gate**: `grep -r "\.ewm\|\.rolling\|compute_ema\|compute_rsi" app/strategies/` returns empty
3. **Scoring Range Gate**: For any strategy, `df['confidence'].max()` ≤ 1.0 and `df['confidence'].min()` ≥ 0.0
4. **Signal Count Gate**: Run each strategy on 1000 candles of real data. Each must produce at least 3 signals (sanity check against "0 trades curse")
5. **NaN Safety Gate**: Zero `NaN` values in `df['confidence']` or `df['signal']` columns
6. **Backward Compatibility Gate**: Existing tests in `tests/test_strategies.py` pass with updated expected values
