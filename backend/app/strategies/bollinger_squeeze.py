"""
Bollinger Band Squeeze Strategy (v2.0)
Reactive strategy on 15m, 1h, 4h.

Implements the full 6-step institutional-grade Bollinger Squeeze methodology:
  1. Volatility Compression — TTM Squeeze (BB inside KC)
  2. Directional Bias — HTF trend + MACD momentum
  3. Fake-Out Detection — Opposite-band liquidity sweep lookback
  4. Expansion + Volume Validation — Hard gates on volume and band expansion
  5. Pullback / Retest Entry — Split entry: aggressive breakout + conservative retest
  6. Invalidation — SL at BB middle (thesis nullification level)

Signals:
  LONG: Squeeze → bullish breakout + volume + expansion + directional bias
  SHORT: Squeeze → bearish breakdown + volume + expansion + directional bias
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class BollingerSqueezeStrategy(BaseStrategy):
    name = "Bollinger Band Squeeze"
    description = "TTM Squeeze breakout with Keltner Channel validation and split entry"
    timeframes = ["15m", "1h", "4h"]
    version = "2.0"

    # ── Configuration ──────────────────────────────────────────────
    MIN_BB_HISTORY = 10        # Minimum bb_width values for squeeze analysis
    MIN_SQUEEZE_BARS = 3       # Minimum consecutive squeeze bars to validate
    FAKEOUT_LOOKBACK = 5       # Bars to look back for opposite-band liquidity sweep
    RETEST_LOOKBACK_MIN = 3    # Min bars after breakout before retest is valid
    RETEST_LOOKBACK_MAX = 8    # Max bars after breakout to still consider retest

    # ── Step 1: Volatility Compression (TTM Squeeze) ───────────────

    def _is_squeeze(self, indicators: Indicators) -> bool:
        """
        Detect if a TTM Squeeze was active on the previous bar.
        Squeeze = Bollinger Bands fitting completely inside Keltner Channels.

        Falls back to bb_width < mean heuristic if KC data is unavailable
        (cold-boot safety).
        """
        # Primary: Keltner Channel comparison (TTM Squeeze)
        if (indicators.prev_bb_upper is not None and
                indicators.prev_bb_lower is not None and
                indicators.prev_kc_upper is not None and
                indicators.prev_kc_lower is not None):
            return (indicators.prev_bb_upper < indicators.prev_kc_upper and
                    indicators.prev_bb_lower > indicators.prev_kc_lower)

        # Fallback: bb_width below its own mean (less reliable)
        history = indicators.bb_width_history
        if len(history) < self.MIN_BB_HISTORY:
            return False
        if indicators.prev_bb_width is None:
            return False
        avg_width = sum(history) / len(history)
        return indicators.prev_bb_width < avg_width * 0.8  # Stricter: 80% of average

    def _squeeze_duration(self, indicators: Indicators) -> int:
        """
        Count consecutive squeeze bars from the bb_width_history.
        Uses the bb_width < avg heuristic since we only have scalar history.
        Returns 0 if insufficient data.
        """
        history = indicators.bb_width_history
        if len(history) < self.MIN_BB_HISTORY:
            return 0

        avg_width = sum(history) / len(history)
        count = 0
        # Walk backwards from the most recent (end of list)
        for val in reversed(history):
            if val < avg_width:
                count += 1
            else:
                break
        return count

    # ── Step 2: Directional Bias (HTF + Momentum) ──────────────────

    def _directional_bias(self, indicators: Indicators, htf_candles, close: float):
        """
        Determine directional bias using MACD momentum + HTF trend.

        Returns:
            "BULL", "BEAR", or None (no clear bias → no signal)
        """
        macd_bias = None
        htf_bias = None

        # MACD histogram momentum direction (curling)
        hist = indicators.macd_hist_history
        if len(hist) >= 3:
            # Check if histogram is curling upward or downward
            if hist[-1] > hist[-2]:
                macd_bias = "BULL"
            elif hist[-1] < hist[-2]:
                macd_bias = "BEAR"

        # HTF trend: compare HTF close vs HTF 10-bar midrange
        if htf_candles and len(htf_candles) >= 10:
            htf_high = max(c.high for c in htf_candles[-10:])
            htf_low = min(c.low for c in htf_candles[-10:])
            htf_mid = (htf_high + htf_low) / 2
            htf_close = htf_candles[-1].close
            if htf_close > htf_mid:
                htf_bias = "BULL"
            else:
                htf_bias = "BEAR"

        # If we have both, they must agree
        if macd_bias and htf_bias:
            if macd_bias == htf_bias:
                return macd_bias
            return None  # Conflicting → no clear bias

        # If only one is available, use it
        return macd_bias or htf_bias

    # ── Step 3: Fake-Out / Liquidity Sweep Detection ───────────────

    def _detect_fakeout_precursor(self, candles, indicators: Indicators):
        """
        Look back N bars for a recent opposite-band breach that snapped back.
        This indicates a liquidity sweep already happened → makes the current
        breakout direction more credible.

        Returns:
            "BULL" if a bearish fakeout was detected (bullish setup stronger)
            "BEAR" if a bullish fakeout was detected (bearish setup stronger)
            None if no fakeout detected
        """
        if len(candles) < self.FAKEOUT_LOOKBACK + 1:
            return None
        if indicators.bb_upper is None or indicators.bb_lower is None:
            return None

        lookback = candles[-(self.FAKEOUT_LOOKBACK + 1):-1]

        bearish_fakeout = False  # Wick below lower band that snapped back
        bullish_fakeout = False  # Wick above upper band that snapped back

        for candle in lookback:
            # Check for a bearish fakeout: wick below lower band but close inside
            if (candle.low < indicators.bb_lower and
                    candle.close > indicators.bb_lower):
                bearish_fakeout = True
            # Check for a bullish fakeout: wick above upper band but close inside
            if (candle.high > indicators.bb_upper and
                    candle.close < indicators.bb_upper):
                bullish_fakeout = True

        if bearish_fakeout and not bullish_fakeout:
            return "BULL"  # Bearish trap → bullish breakout more credible
        if bullish_fakeout and not bearish_fakeout:
            return "BEAR"  # Bullish trap → bearish breakdown more credible
        return None

    # ── Step 5: Retest Detection ───────────────────────────────────

    def _detect_retest(self, candles, indicators: Indicators):
        """
        Detect a pullback/retest after a recent breakout.

        Looks back 3-8 bars for a breakout candle (close beyond band + expansion),
        then checks if the current candle is near BB middle and showing rejection.

        Returns:
            "LONG" if bullish retest detected
            "SHORT" if bearish retest detected
            None if no retest pattern
        """
        if len(candles) < self.RETEST_LOOKBACK_MAX + 1:
            return None
        if indicators.bb_middle is None or indicators.atr_14 is None:
            return None

        close = candles[-1].close
        atr = indicators.atr_14

        # Is current candle near the BB middle? (within 0.4 ATR)
        distance_to_middle = abs(close - indicators.bb_middle)
        if distance_to_middle > 0.4 * atr:
            return None

        # Look back for a recent breakout
        lookback = candles[-(self.RETEST_LOOKBACK_MAX + 1):-self.RETEST_LOOKBACK_MIN]

        for candle in lookback:
            # Check for a previous bullish breakout (close above upper)
            if (indicators.bb_upper is not None and
                    candle.close > indicators.bb_upper and
                    candle.is_bullish):
                # Current candle must hold above bb_middle (not close below)
                if close >= indicators.bb_middle:
                    # Check for rejection: lower wick shows buying pressure
                    current = candles[-1]
                    if current.lower_wick > current.body_size * 0.3:
                        return "LONG"

            # Check for a previous bearish breakdown (close below lower)
            if (indicators.bb_lower is not None and
                    candle.close < indicators.bb_lower and
                    candle.is_bearish):
                # Current candle must hold below bb_middle
                if close <= indicators.bb_middle:
                    # Check for rejection: upper wick shows selling pressure
                    current = candles[-1]
                    if current.upper_wick > current.body_size * 0.3:
                        return "SHORT"

        return None

    # ── Main Scan ──────────────────────────────────────────────────

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        # ── Guard: need core indicator values ──
        if indicators.bb_upper is None or indicators.bb_lower is None:
            return None
        if indicators.bb_width is None or indicators.prev_bb_width is None:
            return None
        if indicators.bb_middle is None:
            return None
        if len(candles) < 10:
            return None

        close = candles[-1].close

        # ── Path A: Retest Entry (Step 5) ──────────────────────────
        # Check for retest FIRST — it has higher conviction than raw breakout
        retest_dir = self._detect_retest(candles, indicators)
        if retest_dir is not None:
            confidence = 0.55

            # Volume should be present but doesn't need to be extreme for retest
            if indicators.volume_ma_20 and candles[-1].volume > indicators.volume_ma_20:
                confidence += 0.05

            # HTF alignment boost
            bias = self._directional_bias(indicators, htf_candles, close)
            if bias == ("BULL" if retest_dir == "LONG" else "BEAR"):
                confidence += 0.10

            # EMA 50 alignment
            if indicators.ema_50 is not None:
                if retest_dir == "LONG" and close > indicators.ema_50:
                    confidence += 0.05
                elif retest_dir == "SHORT" and close < indicators.ema_50:
                    confidence += 0.05

            # Retest entry inherent bonus (safer entry)
            confidence += 0.05

            return SetupSignal(
                strategy_name=self.name,
                symbol=symbol,
                timeframe=timeframe,
                direction=retest_dir,
                confidence=min(confidence, 1.0),
                entry=close,
                notes=(
                    f"Bollinger squeeze RETEST entry on {timeframe}. "
                    f"Price pulled back to BB middle ({indicators.bb_middle:.2f}) "
                    f"and held. Entry type: retest (conservative)."
                ),
            )

        # ── Path B: Breakout Entry (Steps 1-4) ─────────────────────

        # Step 1: Was there a squeeze on the previous bar?
        if not self._is_squeeze(indicators):
            return None

        # Step 4a: HARD GATE — Band must be expanding
        if indicators.bb_width <= indicators.prev_bb_width:
            return None

        # Step 4b: Detect breakout direction
        breakout_up = close > indicators.bb_upper
        breakout_down = close < indicators.bb_lower
        if not breakout_up and not breakout_down:
            return None

        direction = "LONG" if breakout_up else "SHORT"

        # Step 4c: HARD GATE — Volume must be above MA
        if not indicators.volume_ma_20:
            return None
        if candles[-1].volume <= indicators.volume_ma_20:
            return None

        # Step 2: Directional bias check
        bias = self._directional_bias(indicators, htf_candles, close)
        if bias is not None:
            expected = "BULL" if direction == "LONG" else "BEAR"
            if bias != expected:
                # Directional bias conflicts with breakout → reject
                return None

        # ── Confidence Scoring ─────────────────────────────────────
        confidence = 0.50  # Base: squeeze + breakout + volume + expansion all confirmed

        # +0.10 if volume > 2× MA (strong surge)
        if candles[-1].volume > indicators.volume_ma_20 * 2.0:
            confidence += 0.10

        # +0.05 if volume > 3× MA (extreme surge)
        if candles[-1].volume > indicators.volume_ma_20 * 3.0:
            confidence += 0.05

        # +0.10 if HTF alignment confirmed
        if bias is not None:
            confidence += 0.10

        # +0.05 if MACD momentum aligned (individual check, separate from HTF)
        hist = indicators.macd_hist_history
        if len(hist) >= 3:
            macd_curling_up = hist[-1] > hist[-2]
            if direction == "LONG" and macd_curling_up:
                confidence += 0.05
            elif direction == "SHORT" and not macd_curling_up:
                confidence += 0.05

        # +0.10 if fake-out precursor detected (Step 3)
        fakeout = self._detect_fakeout_precursor(candles, indicators)
        if fakeout is not None:
            expected_fakeout = "BULL" if direction == "LONG" else "BEAR"
            if fakeout == expected_fakeout:
                confidence += 0.10

        # +0.05 if squeeze duration ≥ 5 bars (well-coiled spring)
        duration = self._squeeze_duration(indicators)
        if duration >= 5:
            confidence += 0.05

        # +0.05 if EMA 50 alignment
        if indicators.ema_50 is not None:
            if direction == "LONG" and close > indicators.ema_50:
                confidence += 0.05
            elif direction == "SHORT" and close < indicators.ema_50:
                confidence += 0.05

        bb_direction = "above upper band" if breakout_up else "below lower band"

        # Build detailed notes
        components = []
        if bias:
            components.append(f"HTF bias: {bias}")
        if fakeout:
            components.append(f"fakeout precursor: {fakeout}")
        if duration >= 5:
            components.append(f"squeeze duration: {duration} bars")
        vol_ratio = candles[-1].volume / indicators.volume_ma_20
        components.append(f"vol ratio: {vol_ratio:.1f}×")
        extra = ", ".join(components)

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=min(confidence, 1.0),
            entry=close,
            notes=(
                f"Bollinger squeeze BREAKOUT {bb_direction} on {timeframe}. "
                f"BB width: {indicators.prev_bb_width:.6f} → {indicators.bb_width:.6f}. "
                f"Entry type: breakout (aggressive). {extra}"
            ),
        )

    # ── Step 6: Invalidation-Aware SL ──────────────────────────────

    def calculate_sl(self, signal, candles, atr):
        """
        SL at the BB middle (the thesis invalidation level).

        If price re-enters the squeeze zone and crosses the 20-period mean,
        the setup is dead. We place SL at BB middle ± small ATR buffer.

        Falls back to structural SL if BB middle is not recoverable.
        """
        # Try to estimate BB middle from candle data
        # We use the last candle's context — bb_middle was available during scan
        # Since we can't access indicators here, use the structural approach
        # anchored to the mean (average of last 20 closes as proxy)
        if len(candles) >= 20:
            bb_middle_proxy = sum(c.close for c in candles[-20:]) / 20
            if signal.direction == "LONG":
                sl = bb_middle_proxy - (0.3 * atr)
                # But never set SL above entry (invalid)
                if signal.entry and sl >= signal.entry:
                    sl = signal.entry - (0.5 * atr)
                return round(sl, 8)
            else:
                sl = bb_middle_proxy + (0.3 * atr)
                if signal.entry and sl <= signal.entry:
                    sl = signal.entry + (0.5 * atr)
                return round(sl, 8)

        # Fallback: structural SL
        if signal.direction == "LONG":
            recent_low = min(c.low for c in candles[-3:])
            return round(recent_low - (0.3 * atr), 8)
        else:
            recent_high = max(c.high for c in candles[-3:])
            return round(recent_high + (0.3 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """Risk-based TP: 2R and 3.5R — wider targets for breakout momentum."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.2)
        if signal.direction == "LONG":
            return (round(entry + (2.0 * risk), 8), round(entry + (3.5 * risk), 8))
        else:
            return (round(entry - (2.0 * risk), 8), round(entry - (3.5 * risk), 8))
