"""
RSI Reversal Strategy
Reactive strategy on 15m, 1h, 4h.

LONG: RSI crosses above oversold zone with trend context
SHORT: RSI crosses below overbought zone with trend context
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class RSIReversalStrategy(BaseStrategy):
    name = "RSI Reversal"
    description = "RSI reversal from oversold/overbought with trend alignment"
    timeframes = ["15m", "1h", "4h"]
    version = "1.1"

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

        if oversold_reversal:
            direction = "LONG"
        else:
            direction = "SHORT"

        # Confidence scoring
        confidence = 0.55

        # +0.10 if trend alignment (price above/below major EMA)
        if oversold_reversal:
            if indicators.ema_200 is not None and close > indicators.ema_200:
                confidence += 0.10
            elif indicators.ema_50 is not None and close > indicators.ema_50:
                confidence += 0.10
        else:
            if indicators.ema_200 is not None and close < indicators.ema_200:
                confidence += 0.10
            elif indicators.ema_50 is not None and close < indicators.ema_50:
                confidence += 0.10

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

        rsi_condition = "oversold reversal (RSI crossed above 35)" if oversold_reversal else "overbought reversal (RSI crossed below 65)"

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

    def calculate_sl(self, signal, candles, atr):
        """Structural SL: Behind the reversal candle's rejection wick."""
        if signal.direction == "LONG":
            recent_low = min(c.low for c in candles[-3:])
            return round(recent_low - (0.2 * atr), 8)
        else:
            recent_high = max(c.high for c in candles[-3:])
            return round(recent_high + (0.2 * atr), 8)

    def calculate_tp(self, signal, candles, atr):
        """Risk-based TP: 1.5R and 3.0R from structural stop."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.2)
        if signal.direction == "LONG":
            return (round(entry + (1.5 * risk), 8), round(entry + (3.0 * risk), 8))
        else:
            return (round(entry - (1.5 * risk), 8), round(entry - (3.0 * risk), 8))
