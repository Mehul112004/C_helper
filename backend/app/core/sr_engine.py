"""
S/R Zone Detection Engine
Detects Support/Resistance zones from candle data using multiple methods:
- Swing high/low detection (configurable lookback)
- Round psychological numbers
- Previous day/week highs and lows
- Zone merging and strength scoring
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.models.db import db, Candle, SRZone
from app.core.indicators import IndicatorService


# Timeframe weights for strength scoring
# Higher timeframe zones carry more weight
TIMEFRAME_WEIGHTS = {
    '1D': 0.40,
    '4h': 0.30,
    '1h': 0.20,
    '15m': 0.10,
    '5m': 0.05,
}

# Round number increments per symbol for psychological levels
ROUND_NUMBER_CONFIG = {
    'BTCUSDT': {'small': 1000, 'large': 5000},
    'ETHUSDT': {'small': 100, 'large': 500},
    'SOLUSDT': {'small': 10, 'large': 50},
    'XRPUSDT': {'small': 0.10, 'large': 0.50},
}

# Default for unknown symbols
DEFAULT_ROUND_CONFIG = {'small': 100, 'large': 500}

# Symbols supported by the platform
SUPPORTED_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT']


class SREngine:
    """Detects and manages S/R zones for the platform."""

    # ---------- Detection Methods ----------

    @staticmethod
    def detect_swing_points(df: pd.DataFrame, lookback: int = 5) -> list[dict]:
        """
        Detect swing highs and swing lows from candle data.

        A swing high: candle high is the highest high in a window of ±lookback candles.
        A swing low: candle low is the lowest low in a window of ±lookback candles.

        Args:
            df: DataFrame with columns ['open_time', 'high', 'low', 'close']
            lookback: Number of candles on each side to check (default 5)

        Returns:
            List of zone dicts with keys: price_level, zone_type, detection_method, timestamp
        """
        zones = []
        highs = df['high'].values
        lows = df['low'].values
        times = df['open_time'].values

        for i in range(lookback, len(df) - lookback):
            # Check for swing high
            window_highs = highs[i - lookback: i + lookback + 1]
            if highs[i] == window_highs.max():
                zones.append({
                    'price_level': float(highs[i]),
                    'zone_type': 'resistance',
                    'detection_method': 'swing',
                    'timestamp': pd.Timestamp(times[i]).to_pydatetime(),
                })

            # Check for swing low
            window_lows = lows[i - lookback: i + lookback + 1]
            if lows[i] == window_lows.min():
                zones.append({
                    'price_level': float(lows[i]),
                    'zone_type': 'support',
                    'detection_method': 'swing',
                    'timestamp': pd.Timestamp(times[i]).to_pydatetime(),
                })

        return zones

    @staticmethod
    def detect_round_numbers(symbol: str, current_price: float, range_pct: float = 0.15) -> list[dict]:
        """
        Generate zones at psychologically significant round numbers near current price.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            current_price: Latest price to anchor the round number search
            range_pct: How far above/below current price to generate levels (default ±15%)

        Returns:
            List of zone dicts for round number levels
        """
        config = ROUND_NUMBER_CONFIG.get(symbol, DEFAULT_ROUND_CONFIG)
        zones = []

        price_lower = current_price * (1 - range_pct)
        price_upper = current_price * (1 + range_pct)

        for increment_key in ['small', 'large']:
            increment = config[increment_key]

            # Start from the nearest round number at or below price_lower
            # Use round() to handle floating point arithmetic for small increments
            start = round((price_lower // increment) * increment, 10)
            level = start

            while level <= price_upper:
                # Only include levels within the actual range bounds
                if level > 0 and level >= price_lower and level <= price_upper:
                    # Determine if support or resistance relative to current price
                    if level < current_price:
                        zone_type = 'support'
                    elif level > current_price:
                        zone_type = 'resistance'
                    else:
                        zone_type = 'both'

                    zones.append({
                        'price_level': round(float(level), 10),
                        'zone_type': zone_type,
                        'detection_method': 'round_number',
                        'timestamp': datetime.utcnow(),
                    })
                level = round(level + increment, 10)

        # Deduplicate (large increments are subsets of small ones)
        seen = set()
        unique_zones = []
        for z in zones:
            key = round(z['price_level'], 8)
            if key not in seen:
                seen.add(key)
                unique_zones.append(z)

        return unique_zones

    @staticmethod
    def detect_prev_period_hl(symbol: str) -> list[dict]:
        """
        Detect previous day and previous week high/low levels.
        These are strong institutional levels — uses 1D candles regardless of analysis timeframe.

        Args:
            symbol: Trading pair

        Returns:
            List of zone dicts for previous period H/L levels
        """
        zones = []

        # Fetch recent 1D candles (need at least 7 for previous week)
        candles_1d = (
            Candle.query
            .filter_by(symbol=symbol, timeframe='1D')
            .order_by(Candle.open_time.desc())
            .limit(10)
            .all()
        )

        if len(candles_1d) >= 2:
            # Previous day high/low (second most recent 1D candle)
            prev_day = candles_1d[1]
            zones.append({
                'price_level': float(prev_day.high),
                'zone_type': 'resistance',
                'detection_method': 'prev_day_hl',
                'timestamp': prev_day.open_time,
            })
            zones.append({
                'price_level': float(prev_day.low),
                'zone_type': 'support',
                'detection_method': 'prev_day_hl',
                'timestamp': prev_day.open_time,
            })

        if len(candles_1d) >= 6:
            # Previous week high/low (candles index 1 through 5 → last 5 trading days)
            week_candles = candles_1d[1:6]
            week_high = max(c.high for c in week_candles)
            week_low = min(c.low for c in week_candles)

            zones.append({
                'price_level': float(week_high),
                'zone_type': 'resistance',
                'detection_method': 'prev_week_hl',
                'timestamp': week_candles[0].open_time,
            })
            zones.append({
                'price_level': float(week_low),
                'zone_type': 'support',
                'detection_method': 'prev_week_hl',
                'timestamp': week_candles[-1].open_time,
            })

        return zones

    # ---------- Zone Processing ----------

    @staticmethod
    def calculate_zone_width(price_level: float, atr: float) -> tuple[float, float]:
        """
        Calculate zone upper and lower bounds based on ATR.
        Zone width = price_level ± (0.25 × ATR)

        Args:
            price_level: Center of the zone
            atr: Current ATR value

        Returns:
            Tuple of (zone_upper, zone_lower)
        """
        half_width = 0.25 * atr
        return (price_level + half_width, price_level - half_width)

    @staticmethod
    def merge_zones(zones: list[dict], atr: float) -> list[dict]:
        """
        Merge overlapping zones that are within 0.5 × ATR of each other.
        When merging, keep the zone with higher touch count / more recent timestamp.

        Args:
            zones: List of candidate zone dicts
            atr: Current ATR value for determining merge threshold

        Returns:
            Merged list of unique zones
        """
        if not zones or atr <= 0:
            return zones

        merge_threshold = 0.5 * atr
        # Sort by price level
        sorted_zones = sorted(zones, key=lambda z: z['price_level'])
        merged = []

        for zone in sorted_zones:
            if not merged:
                merged.append(zone)
                continue

            last = merged[-1]
            if abs(zone['price_level'] - last['price_level']) <= merge_threshold:
                # Merge: keep average price level, prefer the more significant type
                avg_price = (last['price_level'] + zone['price_level']) / 2.0
                last['price_level'] = avg_price

                # If one is support and other is resistance, mark as 'both'
                if last['zone_type'] != zone['zone_type']:
                    last['zone_type'] = 'both'

                # Keep the more recent timestamp
                if zone.get('timestamp') and last.get('timestamp'):
                    if zone['timestamp'] > last['timestamp']:
                        last['timestamp'] = zone['timestamp']

                # Prefer the more descriptive method, or combine
                if last['detection_method'] != zone['detection_method']:
                    last['detection_method'] = last['detection_method']  # keep first
            else:
                merged.append(zone)

        return merged

    @staticmethod
    def score_zone(zone: dict, df: pd.DataFrame, timeframe: str) -> dict:
        """
        Assign a strength score to a zone based on historical touches and timeframe weight.

        Strength = min(1.0, (touch_count × 0.15) + timeframe_weight)

        A touch = any candle whose high or low falls within the zone band.

        Args:
            zone: Zone dict with price_level, zone_upper, zone_lower
            df: DataFrame of candles for touch counting
            timeframe: Origin timeframe of this zone

        Returns:
            Updated zone dict with strength_score and touch_count
        """
        upper = zone.get('zone_upper', zone['price_level'])
        lower = zone.get('zone_lower', zone['price_level'])

        # Count touches: candles where high >= lower AND low <= upper (price entered the zone)
        touches = ((df['high'] >= lower) & (df['low'] <= upper)).sum()
        touch_count = int(touches)

        tf_weight = TIMEFRAME_WEIGHTS.get(timeframe, 0.10)
        strength = min(1.0, (touch_count * 0.15) + tf_weight)

        # Find the most recent touch
        touch_mask = (df['high'] >= lower) & (df['low'] <= upper)
        if touch_mask.any():
            last_tested = df.loc[touch_mask, 'open_time'].iloc[-1]
            if isinstance(last_tested, pd.Timestamp):
                last_tested = last_tested.to_pydatetime()
        else:
            last_tested = None

        zone['strength_score'] = round(strength, 4)
        zone['touch_count'] = touch_count
        zone['last_tested'] = last_tested

        return zone

    # ---------- Full Zone Detection Pipeline ----------

    @classmethod
    def detect_zones(cls, symbol: str, timeframe: str, swing_lookback: int = 5) -> list[dict]:
        """
        Full S/R zone detection pipeline for a symbol/timeframe:
        1. Fetch candles from DB
        2. Run all detection methods
        3. Calculate zone widths using ATR
        4. Merge nearby zones
        5. Score zones for strength

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            swing_lookback: Lookback period for swing detection

        Returns:
            List of fully processed zone dicts ready for DB insertion
        """
        # Fetch candle data
        candles = (
            Candle.query
            .filter_by(symbol=symbol, timeframe=timeframe)
            .order_by(Candle.open_time.desc())
            .limit(500)
            .all()
        )

        if len(candles) < swing_lookback * 2 + 1:
            print(f"[SREngine] Insufficient data for {symbol}/{timeframe}: "
                  f"{len(candles)} candles (need at least {swing_lookback * 2 + 1})")
            return []

        data = [c.to_dict() for c in candles]
        df = pd.DataFrame(data)
        df['open_time'] = pd.to_datetime(df['open_time'])
        df = df.sort_values('open_time').reset_index(drop=True)

        # Compute ATR for zone width calculations
        atr_series = IndicatorService.compute_atr(df['high'], df['low'], df['close'], 14)
        current_atr = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0
        current_price = float(df['close'].iloc[-1])

        if current_atr <= 0:
            # Fallback: use 1% of current price as ATR proxy
            current_atr = current_price * 0.01

        # ---------- Run detection methods ----------
        all_zones = []

        # 1. Swing highs/lows
        swing_zones = cls.detect_swing_points(df, lookback=swing_lookback)
        all_zones.extend(swing_zones)

        # 2. Round psychological numbers
        round_zones = cls.detect_round_numbers(symbol, current_price)
        all_zones.extend(round_zones)

        # 3. Previous day/week H/L
        period_zones = cls.detect_prev_period_hl(symbol)
        all_zones.extend(period_zones)

        if not all_zones:
            return []

        # ---------- Calculate zone widths ----------
        for zone in all_zones:
            upper, lower = cls.calculate_zone_width(zone['price_level'], current_atr)
            zone['zone_upper'] = upper
            zone['zone_lower'] = lower

        # ---------- Merge nearby zones ----------
        merged_zones = cls.merge_zones(all_zones, current_atr)

        # Recalculate widths after merging (price_levels may have changed)
        for zone in merged_zones:
            upper, lower = cls.calculate_zone_width(zone['price_level'], current_atr)
            zone['zone_upper'] = upper
            zone['zone_lower'] = lower

        # ---------- Score zones ----------
        for zone in merged_zones:
            cls.score_zone(zone, df, timeframe)

        # Add symbol and timeframe metadata
        for zone in merged_zones:
            zone['symbol'] = symbol
            zone['timeframe'] = timeframe

        return merged_zones

    # ---------- Database Persistence ----------

    @classmethod
    def persist_zones(cls, symbol: str, timeframe: str, zones: list[dict]):
        """
        Persist detected zones to the database.
        Uses upsert logic: update existing zones, insert new ones.

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            zones: List of zone dicts from detect_zones()
        """
        from sqlalchemy.dialects.postgresql import insert

        if not zones:
            return

        for zone in zones:
            zone_record = {
                'symbol': zone['symbol'],
                'timeframe': zone['timeframe'],
                'price_level': round(zone['price_level'], 8),
                'zone_upper': round(zone['zone_upper'], 8),
                'zone_lower': round(zone['zone_lower'], 8),
                'zone_type': zone['zone_type'],
                'detection_method': zone['detection_method'],
                'strength_score': zone.get('strength_score', 0.0),
                'touch_count': zone.get('touch_count', 0),
                'last_tested': zone.get('last_tested'),
            }

            stmt = insert(SRZone).values(**zone_record)
            do_upsert = stmt.on_conflict_do_update(
                constraint='uq_sr_zone',
                set_={
                    'zone_upper': stmt.excluded.zone_upper,
                    'zone_lower': stmt.excluded.zone_lower,
                    'zone_type': stmt.excluded.zone_type,
                    'strength_score': stmt.excluded.strength_score,
                    'touch_count': stmt.excluded.touch_count,
                    'last_tested': stmt.excluded.last_tested,
                    'updated_at': db.func.now(),
                }
            )
            db.session.execute(do_upsert)

        db.session.commit()
        print(f"[SREngine] Persisted {len(zones)} zones for {symbol}/{timeframe}")

    @classmethod
    def full_refresh(cls, symbol: str, timeframe: str):
        """
        Full S/R zone refresh: detect all zones and persist to DB.
        Called on 4h candle close.
        """
        print(f"[SREngine] Full refresh for {symbol}/{timeframe}...")
        zones = cls.detect_zones(symbol, timeframe)
        if zones:
            cls.persist_zones(symbol, timeframe, zones)
        else:
            print(f"[SREngine] No zones detected for {symbol}/{timeframe}")

    @classmethod
    def minor_update(cls, symbol: str, timeframe: str):
        """
        Minor zone update: only swing point detection on latest data window.
        Called on 1h candle close. Adds new swing points without full recalculation.
        """
        print(f"[SREngine] Minor update for {symbol}/{timeframe}...")

        candles = (
            Candle.query
            .filter_by(symbol=symbol, timeframe=timeframe)
            .order_by(Candle.open_time.desc())
            .limit(50)  # Only recent window
            .all()
        )

        if len(candles) < 11:  # Need at least 2*lookback+1 candles
            return

        data = [c.to_dict() for c in candles]
        df = pd.DataFrame(data)
        df['open_time'] = pd.to_datetime(df['open_time'])
        df = df.sort_values('open_time').reset_index(drop=True)

        # Detect new swing points
        swing_zones = cls.detect_swing_points(df, lookback=5)

        if not swing_zones:
            return

        # Calculate ATR for zone widths
        atr_series = IndicatorService.compute_atr(df['high'], df['low'], df['close'], 14)
        current_atr = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0
        current_price = float(df['close'].iloc[-1])

        if current_atr <= 0:
            current_atr = current_price * 0.01

        for zone in swing_zones:
            upper, lower = cls.calculate_zone_width(zone['price_level'], current_atr)
            zone['zone_upper'] = upper
            zone['zone_lower'] = lower
            zone['symbol'] = symbol
            zone['timeframe'] = timeframe
            cls.score_zone(zone, df, timeframe)

        cls.persist_zones(symbol, timeframe, swing_zones)
