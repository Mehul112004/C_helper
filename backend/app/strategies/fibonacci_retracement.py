"""
Fibonacci Retracement Strategy (LTF/MTF — 15m / 1h / 4h)

After a significant price impulse (swing), price tends to retrace to
predictable percentage levels before continuing in the original direction.
This strategy identifies three entry tiers — the 38.2% level, the
"golden pocket" (50%–61.8%), and the 0.786 deep zone — and fires when
price shows a rejection candle or engulfing pattern with at least one
secondary confluence met.

Entry Zones (tiered):
  - SECONDARY:  38.2% retracement level — lowest probability, requires 2 confluences
  - PRIMARY:    Golden Pocket (50.0%–61.8%) — highest probability reversal zone, 1 confluence
  - DEEP (Crypto Special): 78.6% retracement — deep liquidity sweep zone, 2 confluences

Confluences (hard-gated, not optional boosters):
  1. Historical S/R zone overlaps the Fibonacci entry zone
  2. RSI shows oversold (<40) or overbought (>60) condition (crypto-adjusted)
  3. Volume exhaustion on the retracement candle (sellers/buyers drying up)
  4. EMA-200 trend alignment (price above for LONG, below for SHORT)

Trigger (Step 4 — requires confluence gate to pass first):
  - Rejection candle with significant opposing wick, OR
  - Bullish/bearish engulfing pattern at the Fibonacci level

Risk Management:
  - SL:  Computed from Fibonacci structure (next level below entry zone)
  - TP1: Previous Swing High/Low (structural target)
  - TP2: Fibonacci 1.618 extension

Swing Detection:
  Uses the fractal pivot algorithm from app.core.fractals with configurable
  pivot bar count for confirmed swing highs/lows.
"""

from app.core.fractals import build_swing_map
from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class FibonacciRetracementStrategy(BaseStrategy):
    name = "Fibonacci Retracement"
    description = (
        "Detects swing impulses, computes Fibonacci retracement levels, and "
        "fires when price retraces into a Fibonacci zone (38.2%, golden pocket "
        "50%-61.8%, or 78.6% deep zone) with candlestick rejection or "
        "engulfing pattern AND required confluence confirmation."
    )
    timeframes = ["15m", "1h", "4h"]
    version = "2.0"
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

    # Deep zone (Issue #1 — Crypto Special)
    DEEP_ZONE_LEVEL = 0.786
    DEEP_ZONE_TOLERANCE_ATR = 0.3  # Price must be within ±0.3 ATR of 78.6%

    # Rejection candle requirements
    MIN_WICK_TO_BODY_RATIO = 0.8  # Wick must be ≥ 80% of body size

    # Volume exhaustion threshold (Issue #4)
    VOLUME_EXHAUSTION_RATIO = 0.70  # Retracement candle volume < 70% of avg

    # RSI confluence thresholds (Issue #5 — crypto-adjusted)
    RSI_OVERSOLD = 40
    RSI_OVERBOUGHT = 60

    # Confluence requirements per zone (Issue #3)
    MIN_CONFLUENCES_PRIMARY = 1     # Golden Pocket requires ≥ 1 confluence
    MIN_CONFLUENCES_SECONDARY = 2   # 38.2% requires ≥ 2 confluences
    MIN_CONFLUENCES_DEEP = 2        # 0.786 requires ≥ 2 confluences

    # Impulse volume gate (Issue #9)
    MIN_IMPULSE_VOLUME_RATIO = 0.8  # Avg swing volume must be ≥ 80% of volume MA

    # Regime filter lookback (Bug #3 — exposed as class constant)
    EMA_TREND_LOOKBACK = 3  # Bars for EMA-21 monotonicity check

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

    def _is_near_786(self, price: float, swing_high: float, swing_low: float,
                     direction: str, atr: float) -> bool:
        """Check if price is near the 78.6% retracement level (deep/crypto zone)."""
        fib_786 = self._compute_fib_level(swing_high, swing_low, self.DEEP_ZONE_LEVEL, direction)
        return abs(price - fib_786) <= self.DEEP_ZONE_TOLERANCE_ATR * atr

    # ── Trigger Validation ───────────────────────────────────────────────

    def _has_rejection_candle(self, candle: Candle, direction: str, atr: float) -> bool:
        """
        Validate that the current candle shows a rejection pattern.

        Doji path (Issue #10): If body is negligible (< 5% ATR), accept if the
        relevant wick is ≥ 0.5× ATR — doji with long wick is a strong reversal signal.

        Normal path:
          LONG: Lower wick ≥ MIN_WICK_TO_BODY_RATIO × body_size AND closes bullish
          SHORT: Upper wick ≥ MIN_WICK_TO_BODY_RATIO × body_size AND closes bearish
        """
        # Doji path: negligible body but significant wick
        if candle.body_size < atr * 0.05:
            if direction == "LONG":
                return candle.lower_wick >= atr * 0.5
            else:
                return candle.upper_wick >= atr * 0.5

        # Normal path: wick-to-body ratio
        if direction == "LONG":
            return (candle.lower_wick >= self.MIN_WICK_TO_BODY_RATIO * candle.body_size
                    and candle.is_bullish)
        else:
            return (candle.upper_wick >= self.MIN_WICK_TO_BODY_RATIO * candle.body_size
                    and candle.is_bearish)

    def _has_engulfing_pattern(self, candles: list[Candle], direction: str) -> bool:
        """
        Detect a bullish or bearish engulfing pattern (Issue #8).

        LONG:  Previous candle bearish, current candle bullish, current body
               fully engulfs previous body.
        SHORT: Previous candle bullish, current candle bearish, current body
               fully engulfs previous body.
        """
        if len(candles) < 2:
            return False
        current = candles[-1]
        prev = candles[-2]

        if direction == "LONG":
            return (prev.is_bearish and current.is_bullish and
                    current.close > prev.open and current.open < prev.close and
                    current.body_size > prev.body_size)
        else:
            return (prev.is_bullish and current.is_bearish and
                    current.close < prev.open and current.open > prev.close and
                    current.body_size > prev.body_size)

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

    # ── Regime Filter (Issue #2) ─────────────────────────────────────────

    @classmethod
    def _is_trending(cls, indicators: Indicators, direction: str) -> bool:
        """
        Validate that the market is in a trending regime using EMA-21 slope.

        Requires EMA-21 to be monotonically trending over the last
        EMA_TREND_LOOKBACK bars. Fibonacci retracements are unreliable
        in choppy, sideways markets.
        """
        lookback = cls.EMA_TREND_LOOKBACK
        if len(indicators.ema_21_history) < lookback:
            return False  # Insufficient data — fail safe

        recent = indicators.ema_21_history[-lookback:]

        # Guard against None values during indicator warm-up
        if any(v is None for v in recent):
            return False

        if direction == "LONG":
            return recent[-1] > recent[-2] > recent[-3]
        else:
            return recent[-1] < recent[-2] < recent[-3]

    # ── Confluence Evaluation (Issue #3) ─────────────────────────────────

    def _evaluate_confluences(self, current: Candle, indicators: Indicators,
                              sr_zones: list[dict], direction: str,
                              fib_zone_low: float, fib_zone_high: float) -> tuple[int, float, dict]:
        """
        Evaluate all secondary confluences and return a count + confidence delta.

        Confluences checked:
          1. S/R zone overlap with the Fibonacci entry zone
          2. RSI oversold/overbought (crypto-adjusted 40/60)
          3. Volume exhaustion on the retracement candle
          4. EMA-200 trend alignment

        Returns:
            (confluences_met, confidence_delta, details_dict)
        """
        confluences_met = 0
        confidence_delta = 0.0
        details = {
            'sr_confluence': False,
            'rsi_confluence': False,
            'volume_exhaustion': False,
            'volume_data_available': True,
            'ema200_aligned': False,
        }

        # Confluence 1: S/R zone overlap
        if self._has_sr_confluence(sr_zones, fib_zone_low, fib_zone_high):
            confluences_met += 1
            confidence_delta += 0.08
            details['sr_confluence'] = True

        # Confluence 2: RSI oversold/overbought (Issue #5 — crypto-adjusted)
        if indicators.rsi_14 is not None:
            if direction == "LONG" and indicators.rsi_14 < self.RSI_OVERSOLD:
                confluences_met += 1
                confidence_delta += 0.08
                details['rsi_confluence'] = True
            elif direction == "SHORT" and indicators.rsi_14 > self.RSI_OVERBOUGHT:
                confluences_met += 1
                confidence_delta += 0.08
                details['rsi_confluence'] = True

        # Confluence 3: Volume exhaustion (Issue #4)
        if indicators.volume_ma_20 and indicators.volume_ma_20 > 0:
            if current.volume < indicators.volume_ma_20 * self.VOLUME_EXHAUSTION_RATIO:
                confluences_met += 1
                confidence_delta += 0.07
                details['volume_exhaustion'] = True
        else:
            details['volume_data_available'] = False

        # Confluence 4: EMA-200 trend alignment
        if indicators.ema_200 is not None:
            if direction == "LONG" and current.close > indicators.ema_200:
                confluences_met += 1
                confidence_delta += 0.07
                details['ema200_aligned'] = True
            elif direction == "SHORT" and current.close < indicators.ema_200:
                confluences_met += 1
                confidence_delta += 0.07
                details['ema200_aligned'] = True

        return confluences_met, confidence_delta, details

    # ── Structural SL Computation (Issue #6) ─────────────────────────────

    def _compute_structural_sl(self, direction: str, zone_type: str,
                               swing_high: float, swing_low: float, atr: float) -> float:
        """
        Compute stop-loss from Fibonacci structure, not arbitrary ATR offsets.

        Rules from Step 5:
          - Entry at Golden Pocket (0.500-0.618) → SL below/above 0.786 level
          - Entry at 0.786 deep zone → SL below/above the Swing Low/High
          - Entry at 0.382 → SL below/above 0.500 level
        """
        if zone_type == "golden_pocket":
            fib_786 = self._compute_fib_level(swing_high, swing_low, 0.786, direction)
            sl_buffer = atr * 0.2
            if direction == "LONG":
                return round(fib_786 - sl_buffer, 8)
            else:
                return round(fib_786 + sl_buffer, 8)

        elif zone_type == "deep_786":
            sl_buffer = atr * 0.3
            if direction == "LONG":
                return round(swing_low - sl_buffer, 8)
            else:
                return round(swing_high + sl_buffer, 8)

        else:  # zone_type == "secondary_382"
            fib_50 = self._compute_fib_level(swing_high, swing_low, 0.500, direction)
            sl_buffer = atr * 0.2
            if direction == "LONG":
                return round(fib_50 - sl_buffer, 8)
            else:
                return round(fib_50 + sl_buffer, 8)

    # ── Structural TP Computation (Issue #7) ─────────────────────────────

    @staticmethod
    def _compute_structural_tp(direction: str, swing_high: float, swing_low: float,
                               swing_range: float) -> tuple[float, float]:
        """
        Compute take-profit from Fibonacci extensions, not generic R-multiples.

        Rules from Step 5:
          - TP1: Previous Swing High (LONG) or Swing Low (SHORT) — structural target
          - TP2: 1.618 Fibonacci extension of the impulse leg
        """
        if direction == "LONG":
            tp1 = swing_high
            tp2 = swing_high + (swing_range * 0.618)  # 1.618 extension
        else:
            tp1 = swing_low
            tp2 = swing_low - (swing_range * 0.618)   # 1.618 extension

        return round(tp1, 8), round(tp2, 8)

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
                # Issue #2: Regime filter — require EMA-21 trending upward
                if not self._is_trending(indicators, "LONG"):
                    return None

                # Issue #9: Validate impulse leg had sufficient volume
                if not self._validate_impulse_volume(window, last_swing_low, last_swing_high, indicators):
                    return None

                # Validate that price has actually retraced (below the swing high)
                if current.close < swing_high_price:
                    signal = self._check_entry(
                        symbol, timeframe, candles, current, indicators, sr_zones,
                        swing_high_price, swing_low_price, swing_range, atr,
                        direction="LONG",
                    )
                    if signal:
                        return signal

        # ═══════ BEARISH SETUP (retracement after a drop) ═══════
        # The swing low must come AFTER the swing high → downward impulse
        if last_swing_low['index'] > last_swing_high['index']:
            if swing_range >= self.MIN_IMPULSE_ATR * atr:
                # Issue #2: Regime filter — require EMA-21 trending downward
                if not self._is_trending(indicators, "SHORT"):
                    return None

                # Issue #9: Validate impulse leg had sufficient volume
                if not self._validate_impulse_volume(window, last_swing_high, last_swing_low, indicators):
                    return None

                # Validate that price has actually retraced (above the swing low)
                if current.close > swing_low_price:
                    signal = self._check_entry(
                        symbol, timeframe, candles, current, indicators, sr_zones,
                        swing_high_price, swing_low_price, swing_range, atr,
                        direction="SHORT",
                    )
                    if signal:
                        return signal

        return None

    # ── Impulse Volume Validation (Issue #9) ─────────────────────────────

    def _validate_impulse_volume(self, window: list[Candle],
                                 swing_start: dict, swing_end: dict,
                                 indicators: Indicators) -> bool:
        """
        Validate that the impulse leg was backed by above-average volume.

        Step 1 requires the impulse to be 'backed by heavy trading volume'.
        A 3× ATR swing on thin weekend liquidity should not qualify.
        """
        if not indicators.volume_ma_20 or indicators.volume_ma_20 <= 0:
            return True  # No volume data — allow through (fail open)

        start_idx = swing_start['index']
        end_idx = swing_end['index']
        if start_idx < 0 or start_idx >= len(window):
            return True  # Pathological index — fail open
        if start_idx >= end_idx or end_idx >= len(window):
            return True  # Invalid range — fail open

        swing_candles = window[start_idx:end_idx + 1]
        if not swing_candles:
            return True

        avg_swing_volume = sum(c.volume for c in swing_candles) / len(swing_candles)
        return avg_swing_volume >= indicators.volume_ma_20 * self.MIN_IMPULSE_VOLUME_RATIO

    # ── Unified Entry Check ──────────────────────────────────────────────

    def _check_entry(self, symbol, timeframe, candles, current, indicators, sr_zones,
                     swing_high, swing_low, swing_range, atr, direction):
        """
        Unified entry check for both LONG and SHORT directions.

        Gate sequence (matches the 5-step methodology):
          1. EMA direction check (short-term trend must agree)
          2. Determine which Fibonacci zone price is in
          3. Evaluate confluences and enforce minimum count
          4. Validate trigger (rejection candle OR engulfing pattern)
          5. Compute structural SL/TP from Fibonacci levels
          6. Build and return the signal
        """
        # ── Gate 1: EMA direction agreement (shallow zones only) ──
        # Deep retracements (0.786) inherently drag EMA-9 below/above EMA-21
        # during the pullback. The macro trend is already validated by
        # _is_trending() (EMA-21 slope monotonicity) in scan(). Applying
        # the EMA cross gate to deep zones would silently reject every
        # 0.786 entry — the exact scenario Issue #1 was built to catch.

        # ── Gate 2: Determine Fibonacci zone ──
        in_golden_pocket = self._is_in_golden_pocket(current.close, swing_high, swing_low, direction)
        near_382 = self._is_near_382(current.close, swing_high, swing_low, direction, atr)
        near_786 = self._is_near_786(current.close, swing_high, swing_low, direction, atr)

        if not in_golden_pocket and not near_382 and not near_786:
            return None

        # Resolve zone type and label (priority: golden pocket > 786 > 382)
        if in_golden_pocket:
            zone_type = "golden_pocket"
            zone_label = "golden pocket (50%-61.8%)"
            base_confidence = 0.65
            min_confluences = self.MIN_CONFLUENCES_PRIMARY
        elif near_786:
            zone_type = "deep_786"
            zone_label = "78.6% deep zone (crypto special)"
            base_confidence = 0.62
            min_confluences = self.MIN_CONFLUENCES_DEEP
        else:
            zone_type = "secondary_382"
            zone_label = "38.2% level"
            base_confidence = 0.58
            min_confluences = self.MIN_CONFLUENCES_SECONDARY

        # ── Scoped Gate 1: EMA direction agreement ──
        # Only apply short-term EMA cross gate for shallow zones (not deep retracements)
        if zone_type != "deep_786":
            if indicators.ema_9 is not None and indicators.ema_21 is not None:
                if direction == "LONG" and indicators.ema_9 < indicators.ema_21:
                    return None
                if direction == "SHORT" and indicators.ema_9 > indicators.ema_21:
                    return None

        # ── Gate 3: Confluence evaluation (Issue #3 — hard gate) ──
        # Compute the Fibonacci zone bounds for S/R overlap check
        fib_zone_low, fib_zone_high = self._get_zone_bounds(
            zone_type, swing_high, swing_low, direction, atr
        )

        confluences_met, confidence_delta, confluence_details = self._evaluate_confluences(
            current, indicators, sr_zones, direction, fib_zone_low, fib_zone_high
        )

        if confluences_met < min_confluences:
            return None  # Insufficient confluence — no signal

        # ── Gate 4: Trigger validation (Issue #8 — rejection OR engulfing) ──
        has_trigger = (self._has_rejection_candle(current, direction, atr) or
                       self._has_engulfing_pattern(candles, direction))
        if not has_trigger:
            return None

        # ── Confidence scoring ──
        confidence = base_confidence + confidence_delta

        # +0.05 strong rejection wick (wick > 1.5× body)
        if direction == "LONG" and current.lower_wick > current.body_size * 1.5:
            confidence += 0.05
        elif direction == "SHORT" and current.upper_wick > current.body_size * 1.5:
            confidence += 0.05

        confidence = min(confidence, 1.0)

        # ── Step 5: Structural SL/TP (Issues #6, #7) ──
        sl = self._compute_structural_sl(direction, zone_type, swing_high, swing_low, atr)
        tp1, tp2 = self._compute_structural_tp(direction, swing_high, swing_low, swing_range)

        # ── Compute Fib levels for notes ──
        fib_382 = self._compute_fib_level(swing_high, swing_low, 0.382, direction)
        fib_50 = self._compute_fib_level(swing_high, swing_low, 0.500, direction)
        fib_618 = self._compute_fib_level(swing_high, swing_low, 0.618, direction)
        fib_786 = self._compute_fib_level(swing_high, swing_low, 0.786, direction)

        # Build confluence summary
        conf_flags = []
        if confluence_details['sr_confluence']:
            conf_flags.append("S/R")
        if confluence_details['rsi_confluence']:
            conf_flags.append(f"RSI({indicators.rsi_14:.1f})")
        if confluence_details['volume_exhaustion']:
            conf_flags.append("VolExhaust")
        if confluence_details['ema200_aligned']:
            conf_flags.append("EMA200")
        conf_summary = ", ".join(conf_flags) if conf_flags else "none"

        dir_label = "Bullish" if direction == "LONG" else "Bearish"
        swing_arrow = (f"{swing_low:.2f} → {swing_high:.2f}" if direction == "LONG"
                       else f"{swing_high:.2f} → {swing_low:.2f}")

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=confidence,
            entry=current.close,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            notes=(
                f"{dir_label} Fibonacci retracement: price in {zone_label}. "
                f"Swing: {swing_arrow} "
                f"(range: {swing_range:.2f}, {swing_range / atr:.1f}x ATR). "
                f"Fib 38.2%={fib_382:.2f}, 50%={fib_50:.2f}, "
                f"61.8%={fib_618:.2f}, 78.6%={fib_786:.2f}. "
                f"Trigger at {current.close:.2f}. "
                f"Confluences ({confluences_met}): {conf_summary}. "
                f"SL={sl:.2f}, TP1={tp1:.2f}, TP2={tp2:.2f}."
            ),
        )

    # ── Zone Bounds Helper ───────────────────────────────────────────────

    def _get_zone_bounds(self, zone_type: str, swing_high: float, swing_low: float,
                         direction: str, atr: float) -> tuple[float, float]:
        """
        Get the price bounds of the active Fibonacci zone for S/R overlap checks.
        Returns (low_price, high_price) regardless of direction.
        """
        if zone_type == "golden_pocket":
            fib_50 = self._compute_fib_level(swing_high, swing_low, 0.500, direction)
            fib_618 = self._compute_fib_level(swing_high, swing_low, 0.618, direction)
            return min(fib_50, fib_618), max(fib_50, fib_618)

        elif zone_type == "deep_786":
            fib_786 = self._compute_fib_level(swing_high, swing_low, 0.786, direction)
            tolerance = self.DEEP_ZONE_TOLERANCE_ATR * atr
            return fib_786 - tolerance, fib_786 + tolerance

        else:  # secondary_382
            fib_382 = self._compute_fib_level(swing_high, swing_low, 0.382, direction)
            tolerance = self.SECONDARY_ZONE_TOLERANCE_ATR * atr
            return fib_382 - tolerance, fib_382 + tolerance

    # ── SL / TP (Fallbacks) ──────────────────────────────────────────────

    def calculate_sl(self, signal, candles, atr):
        """
        Fallback SL computation. The primary SL is computed structurally
        from Fibonacci levels at scan time and attached to signal.sl.
        If missing, falls back to structural wick + 1.0 ATR.
        """
        if signal.sl is not None:
            return signal.sl

        if signal.direction == "LONG":
            return round(candles[-1].low - (1.0 * atr), 8)
        else:
            return round(candles[-1].high + (1.0 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """
        Fallback TP computation. The primary TP is computed from Fibonacci
        extensions and swing structure at scan time.
        If already set, return the scan-time values.
        """
        if signal.tp1 is not None and signal.tp2 is not None:
            return (signal.tp1, signal.tp2)

        # Fallback: risk-based TP
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