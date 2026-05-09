"""
RSI Reversal Strategy
Reactive strategy on 15m, 1h, 4h.

LONG: RSI crosses above oversold zone with trend context
SHORT: RSI crosses below overbought zone with trend context
"""

from datetime import datetime

from app.core.base_strategy import (
    BaseStrategy, Candle, ExecutionMode, Indicators, SetupSignal,
)


class RSIReversalStrategy(BaseStrategy):
    name = "RSI Reversal"
    description = "RSI reversal from oversold/overbought with trend alignment"
    timeframes = ["15m", "1h", "4h"]
    version = "1.2"
    min_confidence = 0.60

    execution_mode = ExecutionMode.ON_CLOSE
    context_tf = "4h"
    execution_tf = "15m"

    def update_context(self, symbol, htf_candles, htf_indicators, sr_zones):
        ctx = self._get_ctx(symbol)
        ctx.clear()

        rsi = htf_indicators.rsi_14
        if rsi is not None:
            if rsi < 35:
                ctx.regime = "OVERSOLD"
            elif rsi > 65:
                ctx.regime = "OVERBOUGHT"
            else:
                ctx.regime = "NEUTRAL"

        ctx.indicators_snapshot = {
            'rsi_14': rsi,
            'ema_50': htf_indicators.ema_50,
            'ema_200': htf_indicators.ema_200,
        }
        ctx.last_updated = datetime.utcnow()

    def evaluate_trigger(self, symbol, timeframe, ltf_candles, ltf_indicators, current_price):
        ctx = self._get_ctx(symbol)
        if not ctx.last_updated:
            return None

        signal = self.scan(symbol, timeframe, ltf_candles, ltf_indicators, [], None)
        if signal is None:
            return None

        if ctx.regime == "OVERSOLD" and signal.direction == "SHORT":
            return None
        if ctx.regime == "OVERBOUGHT" and signal.direction == "LONG":
            return None

        signal.htf_context_summary = f"HTF regime: {ctx.regime} (RSI {ctx.indicators_snapshot.get('rsi_14', 'N/A')})"
        signal.ltf_trigger_summary = f"RSI reversal on {timeframe}"
        return signal

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
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

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """Risk-based TP: 2.0R and 4.0R from structural stop."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.2)
        if signal.direction == "LONG":
            return (round(entry + (2.0 * risk), 8), round(entry + (4.0 * risk), 8))
        else:
            return (round(entry - (2.0 * risk), 8), round(entry - (4.0 * risk), 8))
