"""
S/R Zone Breakout Strategy
Conditional strategy on 15m, 1h, 4h.

Detects price breaking through an S/R zone with conviction (strong body + volume).
LONG: Close breaks above resistance zone with strong body and volume
SHORT: Close breaks below support zone with strong body and volume
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class SRBreakoutStrategy(BaseStrategy):
    name = "S/R Zone Breakout"
    description = "Price breaks and retests a key zone"
    timeframes = ["15m", "1h", "4h"]
    version = "1.1"

    # Minimum zone strength for breakout
    MIN_ZONE_STRENGTH = 0.25

    # Minimum body-to-range ratio for a "strong" breakout candle
    MIN_BODY_RATIO = 0.50

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        if not sr_zones or not candles or len(candles) < 3:
            return None

        candle = candles[-1]

        # Need a candle with meaningful range and body
        if candle.range_size <= 0:
            return None

        body_ratio = candle.body_size / candle.range_size

        # Must be a strong-bodied candle (not a doji or indecision)
        if body_ratio < self.MIN_BODY_RATIO:
            return None

        close = candle.close

        # Check each zone for breakout
        for zone in sr_zones:
            strength = zone.get('strength_score', 0)
            if strength < self.MIN_ZONE_STRENGTH:
                continue

            zone_upper = zone.get('zone_upper', zone.get('price_level', 0))
            zone_lower = zone.get('zone_lower', zone.get('price_level', 0))
            zone_type = zone.get('zone_type', '')
            zone_price = zone.get('price_level', 0)

            # --- LONG breakout: breaking above resistance ---
            if zone_type in ('resistance', 'both'):
                if close > zone_upper and candle.is_bullish:
                    # Verify the previous candle was below or at the zone (actual breakout)
                    prev_candle = candles[-2]
                    if prev_candle.close <= zone_upper:
                        signal = self._build_breakout_signal(
                            symbol, timeframe, candles, indicators, zone,
                            direction="LONG",
                        )
                        if signal:
                            return signal

            # --- SHORT breakout: breaking below support ---
            if zone_type in ('support', 'both'):
                if close < zone_lower and candle.is_bearish:
                    # Verify the previous candle was above or at the zone
                    prev_candle = candles[-2]
                    if prev_candle.close >= zone_lower:
                        signal = self._build_breakout_signal(
                            symbol, timeframe, candles, indicators, zone,
                            direction="SHORT",
                        )
                        if signal:
                            return signal

        return None

    def _build_breakout_signal(self, symbol, timeframe, candles, indicators, zone, direction):
        """Build a SetupSignal from a detected breakout."""
        close = candles[-1].close
        zone_price = zone.get('price_level', 0)
        strength = zone.get('strength_score', 0)

        # Confidence scoring
        confidence = 0.55

        # +0.10 if volume above average
        if indicators.volume_ma_20 and candles[-1].volume > indicators.volume_ma_20:
            confidence += 0.10

        # +0.10 if strong volume (>1.5× vol_ma)
        if indicators.volume_ma_20 and candles[-1].volume > indicators.volume_ma_20 * 1.5:
            confidence += 0.10

        # +0.10 if EMA trend aligns
        if indicators.ema_50 is not None:
            if direction == "LONG" and close > indicators.ema_50:
                confidence += 0.10
            elif direction == "SHORT" and close < indicators.ema_50:
                confidence += 0.10

        # +0.10 if retest pattern: one of the last 2 candles touched the zone from the other side
        if len(candles) >= 3:
            retest_detected = False
            for prev in candles[-3:-1]:  # Check 2nd and 3rd most recent
                if direction == "LONG":
                    # Retest = previous candle touched zone from below
                    zone_upper = zone.get('zone_upper', zone_price)
                    if prev.high >= zone.get('zone_lower', zone_price) and prev.close <= zone_upper:
                        retest_detected = True
                        break
                else:
                    # Retest = previous candle touched zone from above
                    zone_lower = zone.get('zone_lower', zone_price)
                    if prev.low <= zone.get('zone_upper', zone_price) and prev.close >= zone_lower:
                        retest_detected = True
                        break

            if retest_detected:
                confidence += 0.10

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=min(confidence, 1.0),
            entry=close,
            notes=f"S/R zone breakout {'above resistance' if direction == 'LONG' else 'below support'} "
                  f"at ${zone_price:,.2f} (strength: {strength:.2f}) on {timeframe}.",
        )

    def calculate_sl(self, signal, candles, atr):
        """
        For breakout SL: place at the zone center.
        Broken resistance becomes support (and vice versa).
        Falls back to 1.5× ATR if zone info isn't extractable.
        """
        entry = signal.entry or candles[-1].close
        if signal.direction == "LONG":
            return round(entry - (1.5 * atr), 8)
        else:
            return round(entry + (1.5 * atr), 8)
