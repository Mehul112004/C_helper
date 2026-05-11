"""
Base Strategy — Clean Framework v3.0

Every strategy is a set of independent conditions (gates).
Some gates are HARD (must pass), others are SOFT (quality contributors).

Confidence = (hard_gates_passed + soft_gates_passed) / total_gates
This makes confidence transparent, comparable across strategies, and data-driven.

Market regime gating: each strategy declares which regimes it operates in.
Strategies that fire in wrong regimes = noise signals = filtered.

Feature system: each strategy declares required_features.
pre_process() loads only what's needed + market regime + ADX.

Entry/Stop/Target convention:
  - Entry: next bar open (realistic fill)
  - SL: beyond the most recent structural pivot + ATR buffer
  - TP1: nearest structural level (swing high/low or S/R zone)
  - TP2: next structural level (farther swing or S/R zone)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict
import pandas as pd
import numpy as np


@dataclass(frozen=True)
class Candle:
    """Immutable representation of a single OHLCV candle bar."""
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_db_row(cls, row: dict) -> 'Candle':
        open_time = row['open_time']
        if isinstance(open_time, str):
            open_time = datetime.fromisoformat(open_time)
        return cls(
            open_time=open_time,
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=float(row['volume']),
        )

    @classmethod
    def from_df_row(cls, row: pd.Series) -> 'Candle':
        open_time = row['open_time']
        if isinstance(open_time, str):
            open_time = datetime.fromisoformat(open_time)
        elif isinstance(open_time, pd.Timestamp):
            open_time = open_time.to_pydatetime()
        return cls(
            open_time=open_time,
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=float(row['volume']),
        )

    @property
    def body_size(self) -> float: return abs(self.close - self.open)
    @property
    def range_size(self) -> float: return self.high - self.low
    @property
    def upper_wick(self) -> float: return self.high - max(self.open, self.close)
    @property
    def lower_wick(self) -> float: return min(self.open, self.close) - self.low
    @property
    def is_bullish(self) -> bool: return self.close > self.open
    @property
    def is_bearish(self) -> bool: return self.close < self.open


@dataclass
class Indicators:
    """Legacy indicator snapshot — kept for backward compatibility."""
    ema_9: Optional[float] = None
    ema_21: Optional[float] = None
    ema_50: Optional[float] = None
    ema_100: Optional[float] = None
    ema_200: Optional[float] = None
    rsi_14: Optional[float] = None
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    atr_14: Optional[float] = None
    volume_ma_20: Optional[float] = None
    prev_ema_9: Optional[float] = None
    prev_ema_21: Optional[float] = None


@dataclass
class SetupSignal:
    """A single trading signal from any strategy."""
    strategy_name: str
    symbol: str
    timeframe: str
    direction: str          # 'LONG' or 'SHORT'
    confidence: float       # 0.0 to 1.0 — fraction of gates passed
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    notes: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    gates_passed: List[str] = field(default_factory=list)
    gates_failed: List[str] = field(default_factory=list)
    htf_context: Optional[dict] = None
    regime: str = "UNKNOWN"

    def to_dict(self) -> dict:
        return {
            'strategy_name': self.strategy_name,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'direction': self.direction,
            'confidence': round(self.confidence, 4),
            'entry': self.entry,
            'sl': self.sl,
            'tp1': self.tp1,
            'tp2': self.tp2,
            'notes': self.notes,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'gates_passed': self.gates_passed,
            'gates_failed': self.gates_failed,
            'regime': self.regime,
        }


class BaseStrategy(ABC):
    """
    Abstract base for all strategies.

    Subclass contract:
      - Set class-level: name, timeframes, required_features, allowed_regimes
      - Override: generate_signals(df) → returns df with 'signal', 'direction', 'confidence'
      - Override: calculate_sl(signal, df, atr) for custom stop placement
      - Override: calculate_tp(signal, df, atr) for custom target placement
    """

    name: str = "Unnamed"
    version: str = "3.0"
    timeframes: List[str] = []

    # ── Market context gating ──
    # Which regimes this strategy is designed for (empty = all regimes)
    allowed_regimes: List[str] = []  # e.g. ['TRENDING_UP', 'TRENDING_DOWN']
    require_htf_alignment: bool = True

    # ── Confidence threshold ──
    min_confidence: float = 0.5  # Must pass at least 50% of total gates

    # ── Feature declaration ──
    required_features: List[str] = []
    # Valid: 'ema', 'rsi', 'macd', 'bb', 'atr', 'adx', 'volume_ma',
    #        'fvg', 'ob', 'sr', 'choch', 'bos', 'volume_climax', 'liquidity_sweep'

    # ── Risk parameters ──
    sl_atr_mult: float = 1.0      # SL = pivot ± sl_atr_mult * ATR
    tp1_rr: float = 1.5           # Minimum RR for TP1 (overridden by structural TP)
    tp2_rr: float = 3.0           # Minimum RR for TP2

    # ═══════════════════════════════════════════════════════════════
    #  Orchestration (called by StrategyRunner)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def get_required_lookback(cls) -> int:
        """Minimum candles needed for this strategy's features."""
        if any(f in cls.required_features for f in ['ob', 'fvg', 'sr']):
            return 500
        if 'ema' in cls.required_features:
            return 300
        return 200

    @classmethod
    def get_min_candles(cls) -> int:
        """Absolute minimum candles before any signal can fire."""
        return 50

    @classmethod
    def pre_process(cls, df: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        Dynamically load only the features this strategy requires.
        Always adds: adx (for regime), ema_50/100/200 (for HTF), atr (for SL)
        """
        df = df.copy()

        # ── Core indicators (always loaded for regime + HTF) ──
        from app.core.indicators import compute_ema, compute_atr, compute_adx
        for p in [50, 100, 200]:
            col = f'ema_{p}'
            if col not in df.columns:
                df[col] = compute_ema(df['close'], period=p)
        if 'adx' not in df.columns:
            df['adx'] = compute_adx(df['high'], df['low'], df['close'])
        if 'atr' not in df.columns:
            df['atr'] = compute_atr(df['high'], df['low'], df['close'])

        # ── Strategy-requested features ──
        if 'ema' in cls.required_features:
            from app.core.indicators import compute_ema
            for p in [9, 21]:
                col = f'ema_{p}'
                if col not in df.columns:
                    df[col] = compute_ema(df['close'], period=p)

        if 'rsi' in cls.required_features:
            from app.core.indicators import compute_rsi
            if 'rsi' not in df.columns:
                df['rsi'] = compute_rsi(df['close'])

        if 'macd' in cls.required_features:
            from app.core.indicators import compute_macd
            if 'macd_line' not in df.columns:
                macd = compute_macd(df['close'])
                df['macd_line'] = macd['macd_line']
                df['macd_signal'] = macd['macd_signal']
                df['macd_histogram'] = macd['macd_histogram']

        if 'bb' in cls.required_features:
            from app.core.indicators import compute_bollinger
            if 'bb_upper' not in df.columns:
                bb = compute_bollinger(df['close'])
                df['bb_upper'] = bb['bb_upper']
                df['bb_middle'] = bb['bb_middle']
                df['bb_lower'] = bb['bb_lower']
                df['bb_width'] = bb['bb_width']

        if 'volume_ma' in cls.required_features:
            from app.core.indicators import compute_volume_ma
            if 'volume_ma' not in df.columns:
                df['volume_ma'] = compute_volume_ma(df['volume'])

        # ── Spatial state ──
        if 'fvg' in cls.required_features:
            from app.core.market_structure import extract_fvgs
            fvg_cols = ['fvg_active', 'fvg_upper', 'fvg_lower']
            if not all(c in df.columns for c in fvg_cols):
                df = extract_fvgs(df)

        if 'ob' in cls.required_features:
            from app.core.market_structure import extract_order_blocks
            ob_cols = ['ob_active', 'ob_upper', 'ob_lower', 'ob_direction']
            if not all(c in df.columns for c in ob_cols):
                df = extract_order_blocks(df)

        if 'sr' in cls.required_features:
            from app.core.sr_engine import SREngine
            if 'sr_active' not in df.columns:
                df = SREngine.detect_zones_df(df, symbol=symbol, timeframe=timeframe)

        # ── Temporal state ──
        if 'choch' in cls.required_features or 'bos' in cls.required_features:
            from app.core.events import detect_choch
            if 'event_choch_bullish' not in df.columns:
                events_df = detect_choch(df)
                for col in events_df.columns:
                    if col not in df.columns:
                        df[col] = events_df[col]

        if 'volume_climax' in cls.required_features:
            from app.core.events import detect_volume_climax
            if 'event_volume_climax' not in df.columns:
                climax_df = detect_volume_climax(df)
                for col in climax_df.columns:
                    if col not in df.columns:
                        df[col] = climax_df[col]

        if 'liquidity_sweep' in cls.required_features:
            from app.core.events import detect_liquidity_sweep
            if 'event_sweep_bullish' not in df.columns:
                sweep_df = detect_liquidity_sweep(df)
                for col in sweep_df.columns:
                    if col not in df.columns:
                        df[col] = sweep_df[col]

        # ── Market regime detection ──
        from app.core.market_regime import detect_market_regime
        df = detect_market_regime(df)

        return df

    # ═══════════════════════════════════════════════════════════════
    #  Signal generation (override this)
    # ═══════════════════════════════════════════════════════════════

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Override to define strategy logic.

        Must add columns: 'signal' (0/1), 'direction' ('LONG'/'SHORT'/None),
                          'confidence' (0-1)

        Should use the self.evaluate_gates() pattern for transparent scoring.
        """
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0
        return df

    # ═══════════════════════════════════════════════════════════════
    #  Gate evaluation helpers (use in generate_signals)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def evaluate_gate(condition: pd.Series, name: str, weight: float = 1.0) -> pd.Series:
        """
        Evaluate a single gate condition.
        Returns a Series of 0 or weight (for confidence accumulation).
        """
        result = pd.Series(0.0, index=condition.index)
        result[condition] = weight
        return result

    @staticmethod
    def hard_gate(condition: pd.Series, name: str) -> pd.Series:
        """Hard gate: must be True for signal to fire."""
        return condition.astype(bool)

    @staticmethod
    def soft_gate(condition: pd.Series, name: str, weight: float = 1.0) -> pd.Series:
        """Soft gate: adds to confidence if True."""
        result = pd.Series(0.0, index=condition.index)
        result[condition.astype(bool)] = weight
        return result

    # ═══════════════════════════════════════════════════════════════
    #  Risk calculators (can override)
    # ═══════════════════════════════════════════════════════════════

    def calculate_sl(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> float:
        """
        Default: Structural SL beyond the recent 5-bar pivot + ATR buffer.
        """
        if signal_idx < 5:
            return None
        window = df.iloc[max(0, signal_idx - 20):signal_idx + 1]
        if signal.direction == 'LONG':
            pivot = window['low'].rolling(5).min().iloc[-1]
            return round(pivot - (self.sl_atr_mult * atr), 8)
        else:
            pivot = window['high'].rolling(5).max().iloc[-1]
            return round(pivot + (self.sl_atr_mult * atr), 8)

    def calculate_tp(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> tuple:
        """
        Default: Risk-based TP at 1.5R and 3.0R.
        Override for structural targets.
        """
        if signal.entry is None:
            return (None, None)
        sl = signal.sl
        if sl is None:
            return (None, None)
        risk = abs(signal.entry - sl)
        if risk <= 0:
            risk = atr * 0.2
        if signal.direction == 'LONG':
            return (round(signal.entry + self.tp1_rr * risk, 8),
                    round(signal.entry + self.tp2_rr * risk, 8))
        else:
            return (round(signal.entry - self.tp1_rr * risk, 8),
                    round(signal.entry - self.tp2_rr * risk, 8))

    def should_confirm_with_llm(self, signal: SetupSignal) -> bool:
        """Whether to send this signal to the LLM for confirmation."""
        return True  # Enabled by default — v2 structured context payload


# ── Utility: safe boolean comparisons (NaN → False) ──

def safe_lt(series: pd.Series, threshold: float) -> pd.Series:
    return series.notna() & (series < threshold)

def safe_gt(series: pd.Series, threshold: float) -> pd.Series:
    return series.notna() & (series > threshold)

def safe_between(series: pd.Series, lower: float, upper: float) -> pd.Series:
    return series.notna() & (series >= lower) & (series <= upper)
