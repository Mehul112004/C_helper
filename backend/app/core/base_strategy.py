"""
Base Strategy Contract & Core Data Classes
Defines the universal data structures for the strategy engine:
- Candle: Immutable OHLCV bar representation
- Indicators: Snapshot of all indicator values at a given bar
- SetupSignal: The output of every strategy scan
- BaseStrategy: Abstract base class all strategies must implement
"""

from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd


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
        """Create a Candle from a Candle.to_dict() result."""
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
        """Create a Candle from a pandas DataFrame row."""
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
    def body_size(self) -> float:
        """Absolute size of the candle body (|close - open|)."""
        return abs(self.close - self.open)

    @property
    def range_size(self) -> float:
        """Total range of the candle (high - low)."""
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        """Size of the upper wick."""
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        """Size of the lower wick."""
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        """True if close > open."""
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        """True if close < open."""
        return self.close < self.open


@dataclass
class Indicators:
    """
    Snapshot of all technical indicator values at a specific candle index.
    Includes current-bar and previous-bar values for crossover detection.
    """
    # Current bar indicators
    ema_9: Optional[float] = None
    ema_21: Optional[float] = None
    ema_50: Optional[float] = None
    ema_100: Optional[float] = None
    ema_200: Optional[float] = None
    rsi_14: Optional[float] = None
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_width: Optional[float] = None
    kc_upper: Optional[float] = None
    kc_lower: Optional[float] = None
    atr_14: Optional[float] = None
    volume_ma_20: Optional[float] = None

    # Previous bar indicators (for crossover detection)
    prev_ema_9: Optional[float] = None
    prev_ema_21: Optional[float] = None
    prev_macd_line: Optional[float] = None
    prev_macd_signal: Optional[float] = None
    prev_macd_histogram: Optional[float] = None
    prev_rsi_14: Optional[float] = None
    prev_bb_upper: Optional[float] = None
    prev_bb_lower: Optional[float] = None
    prev_bb_width: Optional[float] = None
    prev_kc_upper: Optional[float] = None
    prev_kc_lower: Optional[float] = None

    # Bollinger Band width history (last 20 values) for squeeze detection
    bb_width_history: list = field(default_factory=list)
    # RSI history (last 5 values) for momentum hook detection
    rsi_14_history: list = field(default_factory=list)
    # EMA 21 history (last 5 values) for slope detection
    ema_21_history: list = field(default_factory=list)
    # MACD histogram history (last 5 values) for momentum direction
    macd_hist_history: list = field(default_factory=list)

    @classmethod
    def from_series(cls, series_dict: dict, idx: int) -> 'Indicators':
        """
        Build an Indicators snapshot from full indicator series at position idx.

        Args:
            series_dict: Dict of indicator name → list of {time, value} dicts
                         (from IndicatorService.compute_all() with include_series=True)
            idx: The candle index to extract values for

        Returns:
            Indicators instance with current and previous bar values populated
        """
        def _safe_get(series_list: list, position: int) -> Optional[float]:
            """Safely extract a value from a series list at a given position."""
            if not series_list or position < 0 or position >= len(series_list):
                return None
            val = series_list[position].get('value') if isinstance(series_list[position], dict) else series_list[position]
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            return float(val)

        # Extract Bollinger width history (last 20 values up to and including idx)
        bb_width_series = series_dict.get('bb_width', [])
        bb_history_start = max(0, idx - 19)
        bb_width_history = []
        for i in range(bb_history_start, min(idx + 1, len(bb_width_series))):
            val = _safe_get(bb_width_series, i)
            if val is not None:
                bb_width_history.append(val)

        # Extract RSI history (last 5 values up to and including idx)
        rsi_series = series_dict.get('rsi_14', [])
        rsi_history_start = max(0, idx - 4)
        rsi_14_history = []
        for i in range(rsi_history_start, min(idx + 1, len(rsi_series))):
            val = _safe_get(rsi_series, i)
            if val is not None:
                rsi_14_history.append(val)

        # Extract EMA 21 history (last 5 values up to and including idx)
        ema_21_series = series_dict.get('ema_21', [])
        ema_21_history_start = max(0, idx - 4)
        ema_21_history = []
        for i in range(ema_21_history_start, min(idx + 1, len(ema_21_series))):
            val = _safe_get(ema_21_series, i)
            if val is not None:
                ema_21_history.append(val)

        # Extract MACD histogram history (last 5 values up to and including idx)
        macd_hist_series = series_dict.get('macd_histogram', [])
        macd_hist_start = max(0, idx - 4)
        macd_hist_history = []
        for i in range(macd_hist_start, min(idx + 1, len(macd_hist_series))):
            val = _safe_get(macd_hist_series, i)
            if val is not None:
                macd_hist_history.append(val)

        return cls(
            # Current bar
            ema_9=_safe_get(series_dict.get('ema_9', []), idx),
            ema_21=_safe_get(series_dict.get('ema_21', []), idx),
            ema_50=_safe_get(series_dict.get('ema_50', []), idx),
            ema_100=_safe_get(series_dict.get('ema_100', []), idx),
            ema_200=_safe_get(series_dict.get('ema_200', []), idx),
            rsi_14=_safe_get(series_dict.get('rsi_14', []), idx),
            macd_line=_safe_get(series_dict.get('macd_line', []), idx),
            macd_signal=_safe_get(series_dict.get('macd_signal', []), idx),
            macd_histogram=_safe_get(series_dict.get('macd_histogram', []), idx),
            bb_upper=_safe_get(series_dict.get('bb_upper', []), idx),
            bb_middle=_safe_get(series_dict.get('bb_middle', []), idx),
            bb_lower=_safe_get(series_dict.get('bb_lower', []), idx),
            bb_width=_safe_get(series_dict.get('bb_width', []), idx),
            kc_upper=_safe_get(series_dict.get('kc_upper', []), idx),
            kc_lower=_safe_get(series_dict.get('kc_lower', []), idx),
            atr_14=_safe_get(series_dict.get('atr_14', []), idx),
            volume_ma_20=_safe_get(series_dict.get('volume_ma_20', []), idx),

            # Previous bar
            prev_ema_9=_safe_get(series_dict.get('ema_9', []), idx - 1),
            prev_ema_21=_safe_get(series_dict.get('ema_21', []), idx - 1),
            prev_macd_line=_safe_get(series_dict.get('macd_line', []), idx - 1),
            prev_macd_signal=_safe_get(series_dict.get('macd_signal', []), idx - 1),
            prev_macd_histogram=_safe_get(series_dict.get('macd_histogram', []), idx - 1),
            prev_rsi_14=_safe_get(series_dict.get('rsi_14', []), idx - 1),
            prev_bb_upper=_safe_get(series_dict.get('bb_upper', []), idx - 1),
            prev_bb_lower=_safe_get(series_dict.get('bb_lower', []), idx - 1),
            prev_bb_width=_safe_get(series_dict.get('bb_width', []), idx - 1),
            prev_kc_upper=_safe_get(series_dict.get('kc_upper', []), idx - 1),
            prev_kc_lower=_safe_get(series_dict.get('kc_lower', []), idx - 1),

            # Bollinger width history
            bb_width_history=bb_width_history,
            
            # RSI history
            rsi_14_history=rsi_14_history,

            # EMA 21 history
            ema_21_history=ema_21_history,

            # MACD histogram history
            macd_hist_history=macd_hist_history,
        )


@dataclass
class SetupSignal:
    """
    Universal output of every strategy's scan() method.
    This object flows through the entire signal pipeline:
    strategy → watching card → LLM confirmation → Telegram.
    """
    strategy_name: str          # e.g. "EMA Crossover"
    symbol: str                 # e.g. "BTCUSDT"
    timeframe: str              # e.g. "4h"
    direction: str              # "LONG" or "SHORT"
    confidence: float           # 0.0 to 1.0
    entry: Optional[float] = None       # platform calculates if None
    sl: Optional[float] = None          # stop-loss
    tp1: Optional[float] = None         # take-profit 1
    tp2: Optional[float] = None         # take-profit 2
    notes: str = ""                     # context for LLM
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if self.direction not in ("LONG", "SHORT"):
            raise ValueError(f"direction must be 'LONG' or 'SHORT', got '{self.direction}'")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {self.confidence}")

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dictionary."""
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
        }


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Phase 2: Feature-aware orchestrator with weighted scoring matrix.

    Subclasses must implement:
      - scan() (legacy, being phased out) OR
      - generate_signals() (Phase 2, DataFrame-based scoring)

    Class attributes:
        name: Human-readable strategy name
        description: What this strategy looks for
        timeframes: List of timeframes this strategy operates on
        version: Strategy version string
        min_confidence: Minimum confidence threshold for signals (default 0.5)
        required_features: List of feature names this strategy consumes
        feature_config: Dict of feature-specific configuration
    """

    name: str = "Unnamed Strategy"
    description: str = ""
    timeframes: list = []  # Subclasses MUST override with their own list literal
    version: str = "1.0"
    min_confidence: float = 0.5     # Configurable per strategy; session/runner can override

    # ── Phase 2: Feature Declaration ──
    required_features: list[str] = []
    # Valid values: 'rsi', 'ema', 'macd', 'bb', 'bb_width_history', 'atr',
    #               'volume_ma', 'fvg', 'ob', 'sr', 'choch', 'bos',
    #               'volume_climax', 'liquidity_sweep'
    feature_config: dict = {}
    # e.g., {'rsi_period': 14, 'ema_periods': [9, 21, 50, 200], 'fvg_mitigation': 'wick'}

    # ── Phase 2: Orchestration ──

    @classmethod
    def get_required_lookback(cls) -> int:
        """Returns minimum candles needed based on declared features."""
        if any(f in cls.required_features for f in ['ob', 'fvg', 'sr']):
            return 1000
        if 'ema' in cls.required_features:
            periods = cls.feature_config.get('ema_periods', [])
            if periods and max(periods) >= 200:
                return 300
        return 150

    @classmethod
    def get_min_candles(cls) -> int:
        """Returns absolute minimum candles before any signal can fire."""
        if any(f in cls.required_features for f in ['ob', 'fvg']):
            return 50
        if 'ema' in cls.required_features:
            periods = cls.feature_config.get('ema_periods', [9])
            return max(periods) + 20
        return 30

    @classmethod
    def pre_process(cls, df: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        Dynamically loads only the features this specific strategy requires.

        Called ONCE per strategy per candle close. The resulting DataFrame
        is passed to generate_signals().
        """
        config = cls.feature_config

        # ── Continuous State ──
        if 'rsi' in cls.required_features:
            from app.core.indicators import compute_rsi
            df = df.copy() if 'rsi' not in df.columns else df
            df['rsi'] = compute_rsi(df['close'], period=config.get('rsi_period', 14))

        if 'ema' in cls.required_features:
            from app.core.indicators import compute_ema
            periods = config.get('ema_periods', [9, 21, 50, 200])
            for p in periods:
                col = f'ema_{p}'
                if col not in df.columns:
                    df = df.copy() if col not in df.columns else df
                    df[col] = compute_ema(df['close'], period=p)

        if 'macd' in cls.required_features:
            from app.core.indicators import compute_macd
            if 'macd_line' not in df.columns:
                macd = compute_macd(df['close'])
                df = df.copy()
                df['macd_line'] = macd['macd_line']
                df['macd_signal'] = macd['macd_signal']
                df['macd_histogram'] = macd['macd_histogram']

        if 'bb' in cls.required_features:
            from app.core.indicators import compute_bollinger
            if 'bb_upper' not in df.columns:
                bb = compute_bollinger(df['close'])
                df = df.copy()
                df['bb_upper'] = bb['bb_upper']
                df['bb_middle'] = bb['bb_middle']
                df['bb_lower'] = bb['bb_lower']
                df['bb_width'] = bb['bb_width']

        if 'bb_width_history' in cls.required_features:
            if 'bb_width' not in df.columns:
                from app.core.indicators import compute_bollinger
                bb = compute_bollinger(df['close'])
                df = df.copy()
                df['bb_width'] = bb['bb_width']
            if 'bb_width_avg_20' not in df.columns:
                df['bb_width_avg_20'] = df['bb_width'].rolling(20).mean()

        if 'atr' in cls.required_features:
            from app.core.indicators import compute_atr
            if 'atr' not in df.columns:
                df = df.copy()
                df['atr'] = compute_atr(df['high'], df['low'], df['close'],
                                         period=config.get('atr_period', 14))

        if 'volume_ma' in cls.required_features:
            from app.core.indicators import compute_volume_ma
            if 'volume_ma' not in df.columns:
                df = df.copy()
                df['volume_ma'] = compute_volume_ma(df['volume'],
                                                     period=config.get('volume_ma_period', 20))

        # ── Spatial State (Zones) ──
        if 'fvg' in cls.required_features:
            from app.core.market_structure import extract_fvgs
            df = extract_fvgs(df, mitigation_type=config.get('fvg_mitigation', 'wick'))

        if 'ob' in cls.required_features:
            from app.core.market_structure import extract_order_blocks
            df = extract_order_blocks(df)

        if 'sr' in cls.required_features:
            from app.core.sr_engine import SREngine
            df = SREngine.detect_zones_df(df, symbol=symbol, timeframe=timeframe)

        # ── Temporal State (Events) ──
        if 'choch' in cls.required_features or 'bos' in cls.required_features:
            from app.core.events import detect_choch
            events_df = detect_choch(df)
            for col in events_df.columns:
                if col not in df.columns:
                    df[col] = events_df[col]

        if 'volume_climax' in cls.required_features:
            from app.core.events import detect_volume_climax
            climax_df = detect_volume_climax(df)
            for col in climax_df.columns:
                if col not in df.columns:
                    df[col] = climax_df[col]

        if 'liquidity_sweep' in cls.required_features:
            from app.core.events import detect_liquidity_sweep
            sweep_df = detect_liquidity_sweep(df)
            for col in sweep_df.columns:
                if col not in df.columns:
                    df[col] = sweep_df[col]

        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Phase 2: Pure logic. Receives a pre-processed DataFrame.

        Override this to implement weighted scoring.
        Must return DataFrame with at minimum:
            df['signal']      — 1 or 0
            df['direction']   — 'LONG', 'SHORT', or None
            df['confidence']  — 0.0 to 1.0
        Should also return confidence breakdown columns: df['conf_base'],
        df['conf_fvg'], etc. for Phase 3 context_data serialization.
        """
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0
        return df

    # ── Legacy interface (existing strategies) ──

    def scan(
        self,
        symbol: str,
        timeframe: str,
        candles: list[Candle],
        indicators: Indicators,
        sr_zones: list[dict],
        htf_candles: list[Candle] = None,
    ) -> Optional[SetupSignal]:
        """
        Legacy entry point. Existing strategies override this directly.
        Phase 2 strategies should override generate_signals() instead
        and can leave this unimplemented.
        """
        raise NotImplementedError(
            f"{self.name}: scan() not implemented. "
            f"Either override scan() or implement generate_signals() for Phase 2."
        )

    def calculate_sl(self, signal: SetupSignal, candles: list[Candle], atr: float) -> float:
        """
        Override to customize stop-loss calculation.
        Default: Structural SL behind the recent 3-candle pivot + 0.5 ATR buffer.
        """
        if signal.direction == "LONG":
            recent_low = min(c.low for c in candles[-3:])
            return round(recent_low - (0.5 * atr), 8)
        else:
            recent_high = max(c.high for c in candles[-3:])
            return round(recent_high + (0.5 * atr), 8)

    def calculate_tp(self, signal: SetupSignal, candles: list[Candle], atr: float, sr_zones: list[dict] = None) -> tuple:
        """
        Override to customize take-profit calculation.
        Default: Risk-based TP at 1.5R and 3.0R from structural stop.
        Returns (tp1, tp2).
        """
        entry = signal.entry if signal.entry is not None else candles[-1].close
        sl = signal.sl if signal.sl is not None else self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.2)  # Fallback floor
        if signal.direction == "LONG":
            return (round(entry + (1.5 * risk), 8), round(entry + (3.0 * risk), 8))
        else:
            return (round(entry - (1.5 * risk), 8), round(entry - (3.0 * risk), 8))

    def should_confirm_with_llm(self, signal: SetupSignal) -> bool:
        """Override to skip LLM confirmation for this strategy. Default: True."""
        return True
