"""
RSI Reversal Strategy
Reactive strategy on 1h, 4h.

LONG: RSI crosses above 30 from oversold territory (prev RSI < 30) with trend alignment
SHORT: RSI crosses below 70 from overbought territory (prev RSI > 70) with trend alignment
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class RSIReversalStrategy(BaseStrategy):
    name = "RSI Reversal"
    description = "RSI < 30 or > 70 with trend alignment"
    timeframes = ["1h", "4h"]
    version = "1.0"

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        # Guard: need current and previous RSI values
        if indicators.rsi_14 is None or indicators.prev_rsi_14 is None:
            return None

        rsi = indicators.rsi_14
        prev_rsi = indicators.prev_rsi_14
        close = candles[-1].close

        # Detect oversold reversal: RSI was < 30, now crosses above 30
        oversold_reversal = prev_rsi < 30 and rsi >= 30

        # Detect overbought reversal: RSI was > 70, now crosses below 70
        overbought_reversal = prev_rsi > 70 and rsi <= 70

        if not oversold_reversal and not overbought_reversal:
            return None

        # Trend alignment filter: must be in a supportive trend context
        if oversold_reversal:
            # For LONG reversals, prefer price above at least one major EMA
            has_trend_support = False
            if indicators.ema_200 is not None and close > indicators.ema_200:
                has_trend_support = True
            elif indicators.ema_50 is not None and close > indicators.ema_50:
                has_trend_support = True
            if not has_trend_support:
                return None
            direction = "LONG"
        else:
            # For SHORT reversals, prefer price below at least one major EMA
            has_trend_support = False
            if indicators.ema_200 is not None and close < indicators.ema_200:
                has_trend_support = True
            elif indicators.ema_50 is not None and close < indicators.ema_50:
                has_trend_support = True
            if not has_trend_support:
                return None
            direction = "SHORT"

        # Confidence scoring
        confidence = 0.55

        # +0.15 if MACD histogram confirms direction
        if indicators.macd_histogram is not None:
            if direction == "LONG" and indicators.macd_histogram > 0:
                confidence += 0.15
            elif direction == "SHORT" and indicators.macd_histogram < 0:
                confidence += 0.15

        # +0.10 if volume spike (above average)
        if indicators.volume_ma_20 and candles[-1].volume > indicators.volume_ma_20:
            confidence += 0.10

        # +0.10 if near an S/R zone (adds confluence)
        if sr_zones:
            for zone in sr_zones:
                zone_price = zone.get('price_level', 0)
                if zone_price > 0:
                    distance_pct = abs(close - zone_price) / close
                    if distance_pct < 0.02:  # Within 2% of a zone
                        confidence += 0.10
                        break

        rsi_condition = "oversold reversal (RSI crossed above 30)" if oversold_reversal else "overbought reversal (RSI crossed below 70)"

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=min(confidence, 1.0),
            entry=close,
            notes=f"RSI {rsi_condition} on {timeframe}. "
                  f"RSI: {prev_rsi:.1f} → {rsi:.1f}",
        )
