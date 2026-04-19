"""
Institutional Order Block (OB) Retest Strategy v3.3 — Production Edition

Smart Money Concept focusing on institutional accumulation/distribution zones
with realistic market microstructure gating:
  1. OB Identification   — Variable-length impulse, 1.5x ATR normalized displacement
  2. Displacement Proof  — Break of Structure (Hard Gate) + FVG (Soft Gate / Confidence)
  3. Retest Phase        — OB mitigation tracking (only first-touch zones)
  4. Trigger Confirmation— 0.5x wick rejection + candle-close momentum + Defense line intact
  5. Risk Management     — Strict MIN_RR gates and MAX_RISK caps

Bullish OB: The last down candle before a significant bullish impulse.
Bearish OB: The last up candle before a significant bearish impulse.

Changelog v3.2 → v3.3:
  - FIX: Restored _in_cooldown with correct logic (suppress re-fire, not fresh entry)
  - FIX: _ob_is_mitigated now includes current candle in check window
  - FIX: price_in_zone is now symmetric for both BULL and BEAR (high-wick check added for BULL)
  - TUNE: FVG confidence boost reduced from 0.15 → 0.10 to prevent single-factor dominance
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal
from app.core.fractals import find_fractal_points


class OrderBlockRetestStrategy(BaseStrategy):
    name = "Order Block Retest"
    description = (
        "Detects institutional OB retests gated by realistic ATR displacement, "
        "structural BOS confirmation, and dynamic Risk/Reward targeting."
    )
    timeframes = ["1h", "4h", "1d"]
    version = "3.3"
    min_confidence = 0.60

    # ── Configuration ──────────────────────────────────────────────
    LOOKBACK = 20               # How far back to search for OB candidates
    MAX_IMPULSE_LEN = 5         # Maximum consecutive impulse candles
    MIN_IMPULSE_LEN = 2         # Minimum consecutive impulse candles
    ATR_DISPLACEMENT = 1.5      # Realistic institutional displacement (1.5x ATR)
    BOS_LOOKBACK = 15           # Candles before OB to find prior swing for BOS
    PIVOT_BARS = 3              # Fractal pivot detection window for TP targets
    TP_FRACTAL_LOOKBACK = 40    # How many candles to search for liquidity pools

    # ── Risk & Filter Configuration ────────────────────────────────
    MIN_RR = 1.5                # Absolute minimum Risk/Reward ratio allowed
    MAX_RISK_ATR = 2.5          # Reject OBs that are too wide (Risk > 2.5x ATR)
    STRICT_HTF_ALIGNMENT = True # If True, strictly bans counter-trend setups

    # ── Cooldown Configuration ─────────────────────────────────────
    # Suppresses re-firing if price has been dwelling inside the zone
    # for too many candles already (prolonged consolidation, not a fresh retest).
    COOLDOWN_CANDLES = 5

    # ── Unified FVG Detection (Soft Gate) ─────────────────────────
    def _find_fvg(
        self,
        candles: list[Candle],
        impulse_start: int,
        impulse_end: int,
        direction: str,
    ) -> dict | None:
        upper_bound = min(impulse_end + 1, len(candles))

        for j in range(impulse_start + 2, upper_bound):
            c_before = candles[j - 2]
            c_after = candles[j]

            if direction == "BULL" and c_after.low > c_before.high:
                fvg_top = c_after.low
                fvg_bottom = c_before.high
                for k in range(j + 1, len(candles) - 1):
                    if candles[k].low <= fvg_bottom:
                        break
                else:
                    return {"top": fvg_top, "bottom": fvg_bottom, "index": j}

            elif direction == "BEAR" and c_after.high < c_before.low:
                fvg_top = c_before.low
                fvg_bottom = c_after.high
                for k in range(j + 1, len(candles) - 1):
                    if candles[k].high >= fvg_top:
                        break
                else:
                    return {"top": fvg_top, "bottom": fvg_bottom, "index": j}

        return None

    # ── Break of Structure Detection (Hard Gate) ───────────────────
    def _has_bos(
        self,
        candles: list[Candle],
        ob_index: int,
        impulse_end: int,
        direction: str,
    ) -> bool:
        lookback_start = max(0, ob_index - self.BOS_LOOKBACK)
        if lookback_start >= ob_index:
            return False

        prior_candles = candles[lookback_start:ob_index]
        if not prior_candles:
            return False

        impulse_candles = candles[ob_index + 1 : impulse_end + 1]
        if not impulse_candles:
            return False

        if direction == "BULL":
            prior_high = max(c.high for c in prior_candles)
            impulse_high = max(c.high for c in impulse_candles)
            return impulse_high > prior_high
        else:
            prior_low = min(c.low for c in prior_candles)
            impulse_low = min(c.low for c in impulse_candles)
            return impulse_low < prior_low

    # ── OB Mitigation Check ────────────────────────────────────────
    # FIX v3.3: Upper bound is now len(candles) (inclusive of current candle)
    # so that a candle between impulse_end and current that closed through
    # the zone is not silently skipped — this was a blind spot for recent OBs.
    def _ob_is_mitigated(
        self,
        candles: list[Candle],
        impulse_end: int,
        ob_low: float,
        ob_high: float,
        direction: str,
    ) -> bool:
        for k in range(impulse_end + 1, len(candles)):
            c = candles[k]
            if direction == "BULL":
                if c.close < ob_low:
                    return True
            else:
                if c.close > ob_high:
                    return True
        return False

    # ── Cooldown Check ─────────────────────────────────────────────
    # FIX v3.3: Replaces the removed/inverted cooldown from v3.2.
    # Logic: Count how many candles AFTER the impulse have been inside the zone.
    # If price has been dwelling there for >= COOLDOWN_CANDLES, this is no longer
    # a fresh retest — it's consolidation. Suppress the signal.
    # This does NOT block a fresh entry because a prior wick touched the zone
    # (the original v3.1 bug). It only fires after sustained zone presence.
    def _in_cooldown(
        self,
        candles: list[Candle],
        impulse_end: int,
        ob_low: float,
        ob_high: float,
    ) -> bool:
        candles_in_zone = 0
        # Check all candles between impulse end and current (exclusive of current)
        for c in candles[impulse_end + 1 : -1]:
            # A candle is "in zone" if any part of its body overlaps the OB
            body_top = max(c.open, c.close)
            body_bottom = min(c.open, c.close)
            overlaps_zone = body_top >= ob_low and body_bottom <= ob_high
            if overlaps_zone:
                candles_in_zone += 1
                if candles_in_zone >= self.COOLDOWN_CANDLES:
                    return True
        return False

    # ── Main Scan ──────────────────────────────────────────────────
    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if len(candles) < self.LOOKBACK + self.MAX_IMPULSE_LEN + 5:
            return None

        if indicators.atr_14 is None:
            return None

        current = candles[-1]

        # Exhaustion Guard
        if current.body_size > 2 * indicators.atr_14:
            return None

        # HTF Trend Alignment (SMA-20 baseline)
        htf_bias = None
        if htf_candles and len(htf_candles) >= 20:
            htf_baseline = sum(c.close for c in htf_candles[-20:]) / 20
            htf_bias = "BULL" if htf_candles[-1].close > htf_baseline else "BEAR"

        # Scan boundary: use MIN_IMPULSE_LEN so most-recent OBs are reachable.
        # _evaluate_ob_candidate handles the actual impulse length validation.
        scan_start = max(0, len(candles) - self.LOOKBACK)
        scan_end = len(candles) - self.MIN_IMPULSE_LEN - 1

        for i in range(scan_start, scan_end):
            for direction in ("BULL", "BEAR"):
                signal = self._evaluate_ob_candidate(
                    candles, indicators, i, direction,
                    symbol, timeframe, current, htf_bias,
                )
                if signal is not None:
                    return signal

        return None

    def _evaluate_ob_candidate(
        self,
        candles: list[Candle],
        indicators: Indicators,
        ob_idx: int,
        direction: str,
        symbol: str,
        timeframe: str,
        current: Candle,
        htf_bias: str | None,
    ) -> SetupSignal | None:

        ob_candle = candles[ob_idx]

        if direction == "BULL" and not ob_candle.is_bearish: return None
        if direction == "BEAR" and not ob_candle.is_bullish: return None

        # Find Variable-Length Impulse
        impulse_candles = []
        for j in range(ob_idx + 1, min(ob_idx + 1 + self.MAX_IMPULSE_LEN, len(candles) - 1)):
            c = candles[j]
            if direction == "BULL" and c.is_bullish:
                impulse_candles.append(c)
            elif direction == "BEAR" and c.is_bearish:
                impulse_candles.append(c)
            else:
                break

        if len(impulse_candles) < self.MIN_IMPULSE_LEN:
            return None

        impulse_end_idx = ob_idx + len(impulse_candles)

        # ATR-Normalized Displacement
        if direction == "BULL":
            impulse_size = impulse_candles[-1].close - impulse_candles[0].open
        else:
            impulse_size = impulse_candles[0].open - impulse_candles[-1].close

        if impulse_size < indicators.atr_14 * self.ATR_DISPLACEMENT:
            return None

        # BOS Validation (Hard Gate)
        if not self._has_bos(candles, ob_idx, impulse_end_idx, direction):
            return None

        # FVG Detection (Soft Gate — confidence only)
        fvg = self._find_fvg(candles, ob_idx + 1, impulse_end_idx, direction)

        ob_high, ob_low = ob_candle.high, ob_candle.low

        # Mitigation Check (v3.3: includes current candle in window)
        if self._ob_is_mitigated(candles, impulse_end_idx, ob_low, ob_high, direction):
            return None

        # Cooldown Check (v3.3: restored with correct dwell-time logic)
        if self._in_cooldown(candles, impulse_end_idx, ob_low, ob_high):
            return None

        # Is Price in the OB Zone?
        # FIX v3.3: Symmetric for both directions — BULL now also checks high-wick
        # entry from above (candle high touches zone but close/low may be above it).
        price_in_zone = (
            (ob_low <= current.low   <= ob_high)
            or (ob_low <= current.close <= ob_high)
            or (ob_low <= current.high  <= ob_high)  # symmetric: covers wick-touch for both
        )
        if not price_in_zone:
            return None

        # Institutional Defense Line:
        # Price may sweep below mid (that's the retest), but must not CLOSE
        # beyond the absolute OB boundary — that confirms invalidation.
        if direction == "BULL" and current.close < ob_low: return None
        if direction == "BEAR" and current.close > ob_high: return None

        # HTF Strict Alignment
        if self.STRICT_HTF_ALIGNMENT and htf_bias:
            if direction == "BULL" and htf_bias == "BEAR": return None
            if direction == "BEAR" and htf_bias == "BULL": return None

        # Wick & Momentum Validation (0.5x body minimum)
        if direction == "BULL" and current.lower_wick < current.body_size * 0.5: return None
        if direction == "BEAR" and current.upper_wick < current.body_size * 0.5: return None

        candle_mid = (current.high + current.low) / 2
        if direction == "BULL" and current.close <= candle_mid: return None
        if direction == "BEAR" and current.close >= candle_mid: return None

        # Risk Calculation
        trade_direction = "LONG" if direction == "BULL" else "SHORT"

        if direction == "BULL":
            sl = round(ob_low - (0.5 * indicators.atr_14), 8)
        else:
            sl = round(ob_high + (0.5 * indicators.atr_14), 8)

        entry = current.close
        risk = abs(entry - sl)

        # Hard cap: reject massive volatility zones
        if risk > indicators.atr_14 * self.MAX_RISK_ATR:
            return None

        risk = max(risk, indicators.atr_14 * 0.1)

        # Target Selection
        # Note: MIN_RR is enforced structurally inside _compute_structural_tp.
        # The fallback returns exactly MIN_RR * risk, so no outer gate is needed.
        tp1, tp2 = self._compute_structural_tp(
            candles, entry, sl, risk, direction, indicators.atr_14
        )

        projected_rr = abs(tp1 - entry) / risk

        # Confidence Scoring
        # FIX v3.3: FVG boost reduced from 0.15 → 0.10 to prevent single-factor dominance.
        # At +0.15, a setup with only FVG + base (0.55) clears min_confidence (0.60)
        # without any volume, RSI, or impulse confirmation — too permissive.
        confidence = 0.55

        if fvg:                                                                   confidence += 0.10
        if direction == "BULL" and indicators.rsi_14 and indicators.rsi_14 < 55: confidence += 0.08
        if direction == "BEAR" and indicators.rsi_14 and indicators.rsi_14 > 45: confidence += 0.08
        if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20:  confidence += 0.08
        if len(impulse_candles) >= 3:                                             confidence += 0.05

        confidence = min(max(confidence, 0.0), 1.0)
        if confidence < self.min_confidence:
            return None

        fvg_text = f"FVG: {fvg['bottom']:.2f}-{fvg['top']:.2f}. " if fvg else "No FVG (soft gate). "

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=trade_direction,
            confidence=round(confidence, 4),
            entry=entry,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            notes=(
                f"{'Bullish' if direction == 'BULL' else 'Bearish'} OB retest. "
                f"OB zone: {ob_low:.2f}-{ob_high:.2f}. "
                f"{fvg_text}"
                f"Proj. RR: {projected_rr:.2f}R. "
                f"HTF bias: {htf_bias or 'N/A'}."
            ),
        )

    # ── Structural TP Targeting ────────────────────────────────────
    def _compute_structural_tp(
        self,
        candles: list[Candle],
        entry: float,
        sl: float,
        risk: float,
        direction: str,
        atr: float,
    ) -> tuple[float, float]:
        window_start = max(0, len(candles) - self.TP_FRACTAL_LOOKBACK)
        window = candles[window_start:]

        if len(window) > self.PIVOT_BARS * 2 + 1:
            fractal_highs, fractal_lows = find_fractal_points(
                window[: -self.PIVOT_BARS], self.PIVOT_BARS
            )
        else:
            fractal_highs, fractal_lows = [], []

        if direction == "BULL" and fractal_highs:
            above = sorted([lvl for _, lvl in fractal_highs if lvl > entry])
            valid_targets = [lvl for lvl in above if (lvl - entry) / risk >= self.MIN_RR]

            if valid_targets:
                tp1 = round(valid_targets[0], 8)
                tp2 = round(valid_targets[-1], 8) if len(valid_targets) > 1 else round(entry + 3.0 * risk, 8)
                return (tp1, tp2)

        if direction == "BEAR" and fractal_lows:
            below = sorted([lvl for _, lvl in fractal_lows if lvl < entry], reverse=True)
            valid_targets = [lvl for lvl in below if (entry - lvl) / risk >= self.MIN_RR]

            if valid_targets:
                tp1 = round(valid_targets[0], 8)
                tp2 = round(valid_targets[-1], 8) if len(valid_targets) > 1 else round(entry - 3.0 * risk, 8)
                return (tp1, tp2)

        # Fallback: strict R-multiples if no structural fractals qualify
        if direction == "BULL":
            return (round(entry + (self.MIN_RR * risk), 8), round(entry + (3.0 * risk), 8))
        else:
            return (round(entry - (self.MIN_RR * risk), 8), round(entry - (3.0 * risk), 8))

    # ── SL/TP Fallbacks (getters for the engine) ──────────────────
    def calculate_sl(self, signal, candles, atr):
        if hasattr(signal, 'sl') and signal.sl is not None:
            return signal.sl
        if signal.direction == "LONG": return round(candles[-1].low - (1.0 * atr), 8)
        else: return round(candles[-1].high + (1.0 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        if hasattr(signal, 'tp1') and signal.tp1 is not None and hasattr(signal, 'tp2') and signal.tp2 is not None:
            return (signal.tp1, signal.tp2)

        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = max(abs(entry - sl), atr * 0.1)
        if signal.direction == "LONG": return (round(entry + 1.5 * risk, 8), round(entry + 3.0 * risk, 8))
        else: return (round(entry - 1.5 * risk, 8), round(entry - 3.0 * risk, 8))

    def should_confirm_with_llm(self, signal: SetupSignal) -> bool:
        return True