"""
S/R Zone Rejection Strategy
Conditional strategy on 1h, 4h, 1d.

Looks for price approaching a support/resistance zone and producing a rejection
candle pattern (pin bar / hammer / shooting star).

LONG: Price wick penetrates support zone but closes above it — lower wick ≥ 60% of range
SHORT: Price wick penetrates resistance zone but closes below it — upper wick ≥ 60% of range
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class SRRejectionStrategy(BaseStrategy):
    name = "S/R Zone Rejection"
    description = "Price approaches key zone, waits for rejection candle"
    timeframes = ["1h", "4h", "1d"]
    version = "1.1"

    # Minimum zone strength to consider
    MIN_ZONE_STRENGTH = 0.3

    # Minimum wick-to-range ratio for a rejection candle
    MIN_WICK_RATIO = 0.60

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if not sr_zones or not candles:
            return None

        candle = candles[-1]

        # Need a candle with meaningful range
        if candle.range_size <= 0:
            return None

        # ═══════ Exhaustion Guards ═══════
        if indicators.atr_14 and candle.body_size > 2 * indicators.atr_14:
            return None

        # Check against each S/R zone
        for zone in sr_zones:
            strength = zone.get('strength_score', 0)
            if strength < self.MIN_ZONE_STRENGTH:
                continue

            zone_upper = zone.get('zone_upper', zone.get('price_level', 0))
            zone_lower = zone.get('zone_lower', zone.get('price_level', 0))
            zone_type = zone.get('zone_type', '')
            zone_price = zone.get('price_level', 0)

            # --- Check for SUPPORT rejection (LONG) ---
            if zone_type in ('support', 'both'):
                # RSI exhaustion: already overbought → don't go LONG
                if indicators.rsi_14 is not None and indicators.rsi_14 > 75:
                    continue

                # Wick must enter the zone from above (dip into it, not blow through entirely)
                zone_width = zone_upper - zone_lower
                wick_entered = candle.low <= zone_upper and candle.low >= zone_lower - zone_width
                # Body must have started above the zone (not opened inside it)
                body_above = min(candle.open, candle.close) > zone_upper
                # Candle closes above the zone
                closed_above = candle.close > zone_upper
                # Pin bar pattern: lower wick is ≥ 60% of total range
                lower_wick_ratio = candle.lower_wick / candle.range_size if candle.range_size > 0 else 0

                if wick_entered and body_above and closed_above and lower_wick_ratio >= self.MIN_WICK_RATIO:
                    signal = self._build_signal(
                        symbol, timeframe, candle, indicators, zone,
                        direction="LONG",
                        pattern="pin bar / hammer",
                        wick_ratio=lower_wick_ratio,
                    )
                    if signal:
                        return signal

            # --- Check for RESISTANCE rejection (SHORT) ---
            if zone_type in ('resistance', 'both'):
                # RSI exhaustion: already oversold → don't go SHORT
                if indicators.rsi_14 is not None and indicators.rsi_14 < 25:
                    continue

                # Wick must enter the zone from below
                zone_width = zone_upper - zone_lower
                wick_entered = candle.high >= zone_lower and candle.high <= zone_upper + zone_width
                # Body must have started below the zone
                body_below = max(candle.open, candle.close) < zone_lower
                # Candle closes below the zone
                closed_below = candle.close < zone_lower
                # Upper wick: shooting star pattern
                upper_wick_ratio = candle.upper_wick / candle.range_size if candle.range_size > 0 else 0

                if wick_entered and body_below and closed_below and upper_wick_ratio >= self.MIN_WICK_RATIO:
                    signal = self._build_signal(
                        symbol, timeframe, candle, indicators, zone,
                        direction="SHORT",
                        pattern="shooting star",
                        wick_ratio=upper_wick_ratio,
                    )
                    if signal:
                        return signal

        return None

    def _build_signal(self, symbol, timeframe, candle, indicators, zone,
                      direction, pattern, wick_ratio):
        """Build a SetupSignal from a detected rejection."""
        close = candle.close
        zone_price = zone.get('price_level', 0)
        strength = zone.get('strength_score', 0)

        # Confidence scoring
        confidence = 0.60

        # +0.00 to +0.20 based on zone strength (scaled)
        confidence += strength * 0.20

        # +0.10 if volume spike
        if indicators.volume_ma_20 and candle.volume > indicators.volume_ma_20:
            confidence += 0.10

        # +0.05 if RSI alignment (not yet overbought/oversold in wrong direction)
        if indicators.rsi_14 is not None:
            if direction == "LONG" and indicators.rsi_14 < 60:
                confidence += 0.05
            elif direction == "SHORT" and indicators.rsi_14 > 40:
                confidence += 0.05

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=min(confidence, 1.0),
            entry=close,
            notes=f"S/R zone rejection at ${zone_price:,.2f} (strength: {strength:.2f}). "
                  f"Pattern: {pattern} (wick ratio: {wick_ratio:.0%}) on {timeframe}.",
        )

    def calculate_sl(self, signal, candles, atr):
        """Structural SL: Behind the rejection candle's wick + tiny buffer."""
        if signal.direction == "LONG":
            return round(candles[-1].low - (1.0 * atr), 8)
        else:
            return round(candles[-1].high + (1.0 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """Risk-based TP: 2R and 3.5R from structural stop."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.1)
        if signal.direction == "LONG":
            return (round(entry + (2.0 * risk), 8), round(entry + (3.5 * risk), 8))
        else:
            return (round(entry - (2.0 * risk), 8), round(entry - (3.5 * risk), 8))
