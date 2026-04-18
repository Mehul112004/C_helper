"""
Fibonacci Retracement Strategy (LTF/MTF — 15m / 1h / 4h)

After a significant price impulse (swing), price tends to retrace to
predictable percentage levels before continuing in the original direction.
This strategy identifies the "golden pocket" — the 50%–61.8% retracement
zone — and fires when price shows a rejection candle at that level.

Entry Zones:
  - PRIMARY: Golden Pocket (50.0%–61.8%) — highest probability reversal zone
  - SECONDARY: 38.2% retracement level — moderate probability, lower confidence

Confluences Required:
  1. Impulsive swing of at least 3× ATR (filters out noise)
  2. Price retraces into the golden pocket or 38.2% zone
  3. Rejection candle pattern (significant wick opposing the retracement)

Swing Detection:
  Uses the same fractal pivot algorithm as SMCStructureShiftStrategy._find_swings()
  with configurable pivot bar count for confirmed swing highs/lows.
"""

from app.core.fractals import build_swing_map
from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class FibonacciRetracementStrategy(BaseStrategy):
    name = "Fibonacci Retracement"
    description = (
        "Detects swing impulses, computes Fibonacci retracement levels, and "
        "fires when price retraces into the golden pocket (50%-61.8%) with "
        "candlestick rejection and trend confluence."
    )
    timeframes = ["15m", "1h", "4h"]
    version = "1.0"
    min_confidence = 0.60

    # --- Configuration ---
    SWING_LOOKBACK = 30        # Candles to search for the impulse swing
    PIVOT_BARS = 3             # Bars on each side for valid pivot confirmation
    MIN_IMPULSE_ATR = 3.0      # Swing must span ≥ 3× ATR to qualify as impulsive

    # Golden pocket zone boundaries
    GOLDEN_POCKET_UPPER = 0.500  # 50.0% level
    GOLDEN_POCKET_LOWER = 0.618  # 61.8% level

    # Secondary zone
    SECONDARY_ZONE_LEVEL = 0.382
    SECONDARY_ZONE_TOLERANCE_ATR = 0.3  # Price must be within ±0.3 ATR of 38.2%

    # Rejection candle requirements
    MIN_WICK_TO_BODY_RATIO = 0.8  # Wick must be ≥ 80% of body size

    # ── Fibonacci Level Computation ──────────────────────────────────────

    @staticmethod
    def _compute_fib_level(swing_high: float, swing_low: float, ratio: float, direction: str) -> float:
        """
        Calculate a specific Fibonacci retracement price level.

        For a BULLISH retracement (price rallied up, now pulling back down):
          level = swing_high - (swing_high - swing_low) × ratio

        For a BEARISH retracement (price dropped down, now pulling back up):
          level = swing_low + (swing_high - swing_low) × ratio
        """
        swing_range = swing_high - swing_low
        if direction == "LONG":
            return swing_high - (swing_range * ratio)
        else:
            return swing_low + (swing_range * ratio)

    # ── Zone Checks ──────────────────────────────────────────────────────

    def _is_in_golden_pocket(self, price: float, swing_high: float, swing_low: float, direction: str) -> bool:
        """
        Check if price is inside the 50%–61.8% retracement zone (golden pocket).

        For LONG: price retraces downward, so fib_618 < fib_500 — pocket is [fib_618, fib_500]
        For SHORT: price retraces upward, so fib_500 < fib_618 — pocket is [fib_500, fib_618]
        """
        fib_50 = self._compute_fib_level(swing_high, swing_low, self.GOLDEN_POCKET_UPPER, direction)
        fib_618 = self._compute_fib_level(swing_high, swing_low, self.GOLDEN_POCKET_LOWER, direction)

        if direction == "LONG":
            # Bullish retracement: fib_618 is lower, fib_50 is higher
            return fib_618 <= price <= fib_50
        else:
            # Bearish retracement: fib_50 is lower, fib_618 is higher
            return fib_50 <= price <= fib_618

    def _is_near_382(self, price: float, swing_high: float, swing_low: float,
                     direction: str, atr: float) -> bool:
        """Check if price is near the 38.2% retracement level (secondary zone)."""
        fib_382 = self._compute_fib_level(swing_high, swing_low, self.SECONDARY_ZONE_LEVEL, direction)
        return abs(price - fib_382) <= self.SECONDARY_ZONE_TOLERANCE_ATR * atr

    # ── Rejection Candle Validation ──────────────────────────────────────

    def _has_rejection_candle(self, candle: Candle, direction: str) -> bool:
        """
        Validate that the current candle shows a rejection pattern.

        LONG: Lower wick ≥ MIN_WICK_TO_BODY_RATIO × body_size AND closes bullish
        SHORT: Upper wick ≥ MIN_WICK_TO_BODY_RATIO × body_size AND closes bearish
        """
        if candle.body_size <= 0:
            return False

        if direction == "LONG":
            return (candle.lower_wick >= self.MIN_WICK_TO_BODY_RATIO * candle.body_size
                    and candle.is_bullish)
        else:
            return (candle.upper_wick >= self.MIN_WICK_TO_BODY_RATIO * candle.body_size
                    and candle.is_bearish)

    # ── S/R Confluence Check ─────────────────────────────────────────────

    @staticmethod
    def _has_sr_confluence(sr_zones: list[dict], fib_level_low: float, fib_level_high: float) -> bool:
        """
        Check if any S/R zone overlaps the Fibonacci entry zone.
        Returns True if at least one zone's price_level falls within [fib_level_low, fib_level_high].
        """
        for zone in sr_zones:
            zone_price = zone.get('price_level', 0)
            if fib_level_low <= zone_price <= fib_level_high:
                return True
        return False

    # ── Main Scan ────────────────────────────────────────────────────────

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if len(candles) < self.SWING_LOOKBACK + self.PIVOT_BARS + 5:
            return None

        if indicators.atr_14 is None:
            return None

        atr = indicators.atr_14
        current = candles[-1]

        # Build swing map from the lookback window
        window = candles[-(self.SWING_LOOKBACK + self.PIVOT_BARS):]
        swings = build_swing_map(window, self.PIVOT_BARS)


        if len(swings) < 2:
            return None

        # Extract the most recent swing high and swing low
        last_swing_high = None
        last_swing_low = None
        for s in reversed(swings):
            if s['type'] == 'high' and last_swing_high is None:
                last_swing_high = s
            if s['type'] == 'low' and last_swing_low is None:
                last_swing_low = s
            if last_swing_high and last_swing_low:
                break

        if not last_swing_high or not last_swing_low:
            return None

        swing_high_price = last_swing_high['price']
        swing_low_price = last_swing_low['price']
        swing_range = swing_high_price - swing_low_price

        # ═══════ BULLISH SETUP (retracement after a rally) ═══════
        # The swing high must come AFTER the swing low → upward impulse
        if last_swing_high['index'] > last_swing_low['index']:
            # Validate impulse size
            if swing_range >= self.MIN_IMPULSE_ATR * atr:
                # Validate that price has actually retraced (below the swing high)
                if current.close < swing_high_price:
                    signal = self._check_bullish_entry(
                        symbol, timeframe, current, indicators, sr_zones,
                        swing_high_price, swing_low_price, swing_range, atr,
                    )
                    if signal:
                        return signal

        # ═══════ BEARISH SETUP (retracement after a drop) ═══════
        # The swing low must come AFTER the swing high → downward impulse
        if last_swing_low['index'] > last_swing_high['index']:
            if swing_range >= self.MIN_IMPULSE_ATR * atr:
                # Validate that price has actually retraced (above the swing low)
                if current.close > swing_low_price:
                    signal = self._check_bearish_entry(
                        symbol, timeframe, current, indicators, sr_zones,
                        swing_high_price, swing_low_price, swing_range, atr,
                    )
                    if signal:
                        return signal

        return None

    def _check_bullish_entry(self, symbol, timeframe, current, indicators, sr_zones,
                             swing_high, swing_low, swing_range, atr):
        """Check for a LONG entry at the golden pocket or 38.2% level."""
        direction = "LONG"

        # Compute Fibonacci levels for notes
        fib_50 = self._compute_fib_level(swing_high, swing_low, 0.500, direction)
        fib_618 = self._compute_fib_level(swing_high, swing_low, 0.618, direction)
        fib_382 = self._compute_fib_level(swing_high, swing_low, 0.382, direction)

        # Determine which zone we're in
        in_golden_pocket = self._is_in_golden_pocket(current.close, swing_high, swing_low, direction)
        near_382 = self._is_near_382(current.close, swing_high, swing_low, direction, atr)

        if not in_golden_pocket and not near_382:
            return None

        # Require rejection candle
        if not self._has_rejection_candle(current, direction):
            return None

        # Build confidence score
        if in_golden_pocket:
            confidence = 0.65  # Golden pocket = high probability
            zone_label = "golden pocket (50%-61.8%)"
        else:
            confidence = 0.58  # 38.2% = moderate probability
            zone_label = "38.2% level"

        # +0.08 RSI alignment (not overbought — room to grow)
        if indicators.rsi_14 is not None and indicators.rsi_14 < 50:
            confidence += 0.08

        # +0.07 volume spike
        if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20:
            confidence += 0.07

        # +0.05 strong rejection wick (wick > 1.5× body)
        if current.lower_wick > current.body_size * 1.5:
            confidence += 0.05

        # +0.07 EMA trend alignment (price > EMA200)
        if indicators.ema_200 is not None and current.close > indicators.ema_200:
            confidence += 0.07

        # EMA direction check: short-term trend must agree with LONG direction
        if indicators.ema_9 is not None and indicators.ema_21 is not None:
            if indicators.ema_9 < indicators.ema_21:
                return None  # Short-term EMAs are bearish — abort bullish entry

        # +0.08 S/R zone confluence
        # Check if any S/R zone overlaps the golden pocket
        pocket_low = min(fib_50, fib_618)
        pocket_high = max(fib_50, fib_618)
        sr_confluence = self._has_sr_confluence(sr_zones, pocket_low, pocket_high)
        if sr_confluence:
            confidence += 0.08

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction="LONG",
            confidence=min(confidence, 1.0),
            entry=current.close,
            notes=(
                f"Bullish Fibonacci retracement: price in {zone_label}. "
                f"Swing: {swing_low:.2f} → {swing_high:.2f} "
                f"(range: {swing_range:.2f}, {swing_range / atr:.1f}x ATR). "
                f"Fib 38.2%={fib_382:.2f}, 50%={fib_50:.2f}, 61.8%={fib_618:.2f}. "
                f"Rejection at {current.close:.2f}. "
                f"S/R confluence: {'yes' if sr_confluence else 'no'}."
            ),
        )

    def _check_bearish_entry(self, symbol, timeframe, current, indicators, sr_zones,
                             swing_high, swing_low, swing_range, atr):
        """Check for a SHORT entry at the golden pocket or 38.2% level."""
        direction = "SHORT"

        # Compute Fibonacci levels for notes
        fib_50 = self._compute_fib_level(swing_high, swing_low, 0.500, direction)
        fib_618 = self._compute_fib_level(swing_high, swing_low, 0.618, direction)
        fib_382 = self._compute_fib_level(swing_high, swing_low, 0.382, direction)

        # Determine which zone we're in
        in_golden_pocket = self._is_in_golden_pocket(current.close, swing_high, swing_low, direction)
        near_382 = self._is_near_382(current.close, swing_high, swing_low, direction, atr)

        if not in_golden_pocket and not near_382:
            return None

        # Require rejection candle
        if not self._has_rejection_candle(current, direction):
            return None

        # Build confidence score
        if in_golden_pocket:
            confidence = 0.65
            zone_label = "golden pocket (50%-61.8%)"
        else:
            confidence = 0.58
            zone_label = "38.2% level"

        # +0.08 RSI alignment (not oversold — room to fall)
        if indicators.rsi_14 is not None and indicators.rsi_14 > 50:
            confidence += 0.08

        # +0.07 volume spike
        if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20:
            confidence += 0.07

        # +0.05 strong rejection wick
        if current.upper_wick > current.body_size * 1.5:
            confidence += 0.05

        # +0.07 EMA trend alignment (price < EMA200)
        if indicators.ema_200 is not None and current.close < indicators.ema_200:
            confidence += 0.07

        # EMA direction check: short-term trend must agree with SHORT direction
        if indicators.ema_9 is not None and indicators.ema_21 is not None:
            if indicators.ema_9 > indicators.ema_21:
                return None  # Short-term EMAs are bullish — abort bearish entry

        # +0.08 S/R zone confluence
        pocket_low = min(fib_50, fib_618)
        pocket_high = max(fib_50, fib_618)
        sr_confluence = self._has_sr_confluence(sr_zones, pocket_low, pocket_high)
        if sr_confluence:
            confidence += 0.08

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction="SHORT",
            confidence=min(confidence, 1.0),
            entry=current.close,
            notes=(
                f"Bearish Fibonacci retracement: price in {zone_label}. "
                f"Swing: {swing_high:.2f} → {swing_low:.2f} "
                f"(range: {swing_range:.2f}, {swing_range / atr:.1f}x ATR). "
                f"Fib 38.2%={fib_382:.2f}, 50%={fib_50:.2f}, 61.8%={fib_618:.2f}. "
                f"Rejection at {current.close:.2f}. "
                f"S/R confluence: {'yes' if sr_confluence else 'no'}."
            ),
        )

    # ── SL / TP ──────────────────────────────────────────────────────────
    def calculate_sl(self, signal, candles, atr):
        """
        Fallback SL computation. The primary SL should be computed
        at scan time and attached to signal.sl based on the Fib 78.6% level.
        If missing, falls back to structural wick + 0.5 ATR.
        """
        if signal.sl is not None:
            return signal.sl
            
        if signal.direction == "LONG":
            return round(candles[-1].low - (1.0 * atr), 8)
        else:
            return round(candles[-1].high + (1.0 * atr), 8)
    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """Risk-based TP: 1.5R and 3.0R from the structural stop (78.6% level)."""
        entry = signal.entry or candles[-1].close
        sl = signal.sl if signal.sl is not None else self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.1)
        if signal.direction == "LONG":
            return (round(entry + (1.5 * risk), 8), round(entry + (3.0 * risk), 8))
        else:
            return (round(entry - (1.5 * risk), 8), round(entry - (3.0 * risk), 8))
    def should_confirm_with_llm(self, signal: SetupSignal) -> bool:
        return True