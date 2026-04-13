"""
S/R Zone Rejection Strategy
Conditional strategy on 4h, 1D.

Looks for price approaching a support/resistance zone and producing a rejection
candle pattern (pin bar / hammer / shooting star).

LONG: Price wick penetrates support zone but closes above it — lower wick ≥ 60% of range
SHORT: Price wick penetrates resistance zone but closes below it — upper wick ≥ 60% of range
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class SRRejectionStrategy(BaseStrategy):
    name = "S/R Zone Rejection"
    description = "Price approaches key zone, waits for rejection candle"
    timeframes = ["4h", "1D"]
    version = "1.0"

    # Minimum zone strength to consider
    MIN_ZONE_STRENGTH = 0.3

    # Minimum wick-to-range ratio for a rejection candle
    MIN_WICK_RATIO = 0.60

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        if not sr_zones or not candles:
            return None

        candle = candles[-1]

        # Need a candle with meaningful range
        if candle.range_size <= 0:
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
                # Wick penetrates the zone: candle low goes into or below the zone
                wick_entered = candle.low <= zone_upper
                # But candle closes above the zone
                closed_above = candle.close > zone_upper
                # Pin bar pattern: lower wick is ≥ 60% of total range
                lower_wick_ratio = candle.lower_wick / candle.range_size if candle.range_size > 0 else 0

                if wick_entered and closed_above and lower_wick_ratio >= self.MIN_WICK_RATIO:
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
                # Wick penetrates the zone: candle high goes into or above the zone
                wick_entered = candle.high >= zone_lower
                # But candle closes below the zone
                closed_below = candle.close < zone_lower
                # Upper wick: shooting star pattern
                upper_wick_ratio = candle.upper_wick / candle.range_size if candle.range_size > 0 else 0

                if wick_entered and closed_below and upper_wick_ratio >= self.MIN_WICK_RATIO:
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
        """
        Place SL beyond the zone:
        LONG: SL = zone_lower - 0.5× ATR
        SHORT: SL = zone_upper + 0.5× ATR

        Falls back to default if zone info isn't available in the signal notes.
        """
        entry = signal.entry or candles[-1].close
        if signal.direction == "LONG":
            return round(entry - (1.5 * atr), 8)
        else:
            return round(entry + (1.5 * atr), 8)

    def calculate_tp(self, signal, candles, atr):
        """TP1 = 2× risk, TP2 = 3× risk from entry."""
        entry = signal.entry or candles[-1].close
        risk = 1.5 * atr  # matches SL distance
        if signal.direction == "LONG":
            return (round(entry + 2.0 * risk, 8), round(entry + 3.0 * risk, 8))
        else:
            return (round(entry - 2.0 * risk, 8), round(entry - 3.0 * risk, 8))
