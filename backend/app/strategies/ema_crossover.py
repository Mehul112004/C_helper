"""
EMA Crossover Strategy
Reactive strategy on 5m, 15m, 1h, 4h.

LONG: EMA 9 crosses above EMA 21 with close > EMA 50 (trend filter)
SHORT: EMA 9 crosses below EMA 21 with close < EMA 50 (trend filter)
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class EMACrossoverStrategy(BaseStrategy):
    name = "EMA Crossover"
    description = "EMA 9 crosses EMA 21 with EMA 50 trend filter"
    timeframes = ["5m", "15m", "1h", "4h"]
    version = "1.2"

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        # Guard: need previous bar EMA values for crossover detection
        if indicators.prev_ema_9 is None or indicators.prev_ema_21 is None:
            return None
        if indicators.ema_9 is None or indicators.ema_21 is None:
            return None
            
        # Volume Hard Gate (ISSUE-EMA-2)
        if indicators.volume_ma_20 is None or candles[-1].volume < indicators.volume_ma_20:
            return None

        # Detect crossover (ISSUE-EMA-7)
        prev_above = indicators.prev_ema_9 > indicators.prev_ema_21
        curr_above = indicators.ema_9 > indicators.ema_21
        prev_below = indicators.prev_ema_9 < indicators.prev_ema_21
        curr_below = indicators.ema_9 < indicators.ema_21

        bullish_cross = prev_below and curr_above
        bearish_cross = prev_above and curr_below

        if not bullish_cross and not bearish_cross:
            return None

        close = candles[-1].close
        direction = "LONG" if bullish_cross else "SHORT"

        # Trend filter: EMA 50
        if indicators.ema_50 is not None:
            if bullish_cross and close < indicators.ema_50:
                return None  # Counter-trend long, skip
            if bearish_cross and close > indicators.ema_50:
                return None  # Counter-trend short, skip

        # MACRO Convergence (ISSUE-EMA-1)
        if abs(indicators.ema_9 - indicators.ema_21) / close < 0.0005:
            return None  # EMAs are too tightly coiled/flat
        
        if indicators.ema_21_history:
            # ema_21_history[0] is the oldest value (5 bars ago)
            ema_21_old = indicators.ema_21_history[0]
            if abs(indicators.ema_21 - ema_21_old) / close < 0.0005:
                return None  # EMA slope is horizontal
                
        # HTF Consistency (ISSUE-EMA-1)
        if htf_candles and len(htf_candles) >= 3:
            c1, c2, c3 = htf_candles[-1], htf_candles[-2], htf_candles[-3]
            if direction == "LONG":
                if not ((c1.is_bullish and c2.is_bullish) or (c2.is_bullish and c3.is_bullish)):
                    return None
            else:
                if not ((c1.is_bearish and c2.is_bearish) or (c2.is_bearish and c3.is_bearish)):
                    return None

        # SR Zone Refusal in scan() (ISSUE-EMA-3)
        if sr_zones:
            atr = indicators.atr_14 if indicators.atr_14 is not None else (candles[-1].range_size * 1.5)
            if direction == "LONG":
                sl_proxy = min(c.low for c in candles[-4:-1]) - (0.3 * atr)
            else:
                sl_proxy = max(c.high for c in candles[-4:-1]) + (0.3 * atr)
                
            risk = abs(close - sl_proxy)
            risk = max(risk, atr * 0.2)
            tp1_proxy = close + (1.5 * risk) if direction == "LONG" else close - (1.5 * risk)
            
            for zone in sr_zones:
                strength = zone.get('strength_score', 0)
                if strength < 0.5:
                    continue
                z_upper = zone.get('zone_upper', zone.get('price_level', 0))
                z_lower = zone.get('zone_lower', zone.get('price_level', 0))
                z_type = zone.get('zone_type', '')

                if direction == "LONG" and z_type in ('resistance', 'both'):
                    if z_lower < tp1_proxy and z_upper > close:
                        return None
                elif direction == "SHORT" and z_type in ('support', 'both'):
                    if z_upper > tp1_proxy and z_lower < close:
                        return None

        # Confidence scoring
        confidence = 0.60

        # +0.05 if strong volume (>1.5× vol_ma)
        if candles[-1].volume > indicators.volume_ma_20 * 1.5:
            confidence += 0.05

        # +0.10 if aligned with EMA 200 trend
        if indicators.ema_200 is not None:
            if direction == "LONG" and close > indicators.ema_200:
                confidence += 0.10
            elif direction == "SHORT" and close < indicators.ema_200:
                confidence += 0.10

        # +0.05 if RSI is in mid-range (not overbought/oversold)
        if indicators.rsi_14 is not None and 35 <= indicators.rsi_14 <= 65:
            confidence += 0.05

        cross_type = "bullish" if bullish_cross else "bearish"

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=min(confidence, 1.0),
            entry=close,
            notes=f"EMA 9/21 {cross_type} crossover on {timeframe}",
        )

    def calculate_sl(self, signal, candles, atr):
        """Structural SL: Behind the recent 3-candle pivot that preceded the crossover."""
        if signal.direction == "LONG":
            recent_low = min(c.low for c in candles[-4:-1])
            return round(recent_low - (0.3 * atr), 8)
        else:
            recent_high = max(c.high for c in candles[-4:-1])
            return round(recent_high + (0.3 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """Risk-based TP: 1.5R and 3.0R structurally, adjusted for blocking S/R zones."""
        entry = signal.entry if signal.entry is not None else candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.2)
        
        if signal.direction == "LONG":
            tp1 = entry + (1.5 * risk)
            tp2 = entry + (3.0 * risk)
            
            if sr_zones:
                for zone in sr_zones:
                    if zone.get('zone_type') in ('resistance', 'both') and zone.get('strength_score', 0) > 0.5:
                        z_lower = zone.get('zone_lower', zone.get('price_level', 0))
                        if entry < z_lower < tp1:
                            tp1 = min(tp1, z_lower - (0.05 * atr))
                            
            return (round(tp1, 8), round(tp2, 8))
        else:
            tp1 = entry - (1.5 * risk)
            tp2 = entry - (3.0 * risk)
            
            if sr_zones:
                for zone in sr_zones:
                    if zone.get('zone_type') in ('support', 'both') and zone.get('strength_score', 0) > 0.5:
                        z_upper = zone.get('zone_upper', zone.get('price_level', 0))
                        if entry > z_upper > tp1:
                            tp1 = max(tp1, z_upper + (0.05 * atr))
                            
            return (round(tp1, 8), round(tp2, 8))
