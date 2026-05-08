import json
import logging
import requests
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from pydantic import BaseModel, Field, ValidationError

from app.core.base_strategy import SetupSignal, Candle, Indicators
from app.core.llm_providers.factory import get_llm_provider

logger = logging.getLogger(__name__)

# Minimum confidence score from LLM to allow a CONFIRM verdict
LLM_CONFIDENCE_THRESHOLD = 4

class LLMVerdictSchema(BaseModel):
    """Chain-of-Thought schema: reasoning MUST come before verdict to prevent hallucination."""
    reasoning: str = Field(..., description="Step-by-step analysis: (1) trend alignment, (2) candle momentum check, (3) S/R proximity, (4) risk/reward assessment. Be specific about numbers.")
    confidence_score: int = Field(..., description="Confidence in the trade on a scale of 1-10. 1=extremely risky, 10=textbook setup.")
    verdict: str = Field(..., description="Must be exactly CONFIRM, REJECT, or MODIFY. Derived from your reasoning above.")
    modified_sl: Optional[float] = Field(None, description="Suggested Stop Loss if verdict is MODIFY")
    modified_tp1: Optional[float] = Field(None, description="Suggested TP1 if verdict is MODIFY")
    modified_tp2: Optional[float] = Field(None, description="Suggested TP2 if verdict is MODIFY")

class LLMClient:
    """
    Client for interacting with the local LM Studio instance.
    Formats market context and parses the JSON response using Pydantic.
    """

    @staticmethod
    def _build_legacy_prompt(
        signal: SetupSignal,
        candles: list[Candle],
        indicators: Indicators,
        sr_zones: list[dict],
        htf_candles: list[Candle] = None
    ) -> str:
        """Original single-TF prompt builder — used when signal has no MTF context."""
        recent_candles = candles[-20:] if len(candles) >= 20 else candles
        candle_text = "Recent Candles (OHLCV):\n"
        for c in recent_candles:
            candle_text += f"{c.open_time.strftime('%Y-%m-%d %H:%M')} O:{c.open:.2f} H:{c.high:.2f} L:{c.low:.2f} C:{c.close:.2f} V:{c.volume:.0f}\n"

        ind_parts = []
        if indicators.rsi_14 is not None:
            ind_parts.append(f"RSI(14): {indicators.rsi_14:.1f}")
        if indicators.macd_line is not None:
            ind_parts.append(f"MACD: {indicators.macd_line:.4f}, Signal: {indicators.macd_signal:.4f}, Hist: {indicators.macd_histogram:.4f}")
        if indicators.ema_9 is not None:
            ind_parts.append(f"EMA9: {indicators.ema_9:.2f}")
        if indicators.ema_21 is not None:
            ind_parts.append(f"EMA21: {indicators.ema_21:.2f}")
        if indicators.ema_50 is not None:
            ind_parts.append(f"EMA50: {indicators.ema_50:.2f}")
        if indicators.ema_200 is not None:
            ind_parts.append(f"EMA200: {indicators.ema_200:.2f}")
        if indicators.bb_upper is not None:
            ind_parts.append(f"BB: U:{indicators.bb_upper:.2f} M:{indicators.bb_middle:.2f} L:{indicators.bb_lower:.2f}")
        if indicators.atr_14 is not None:
            ind_parts.append(f"ATR(14): {indicators.atr_14:.4f}")
        ind_text = "Indicators:\n" + "\n".join(ind_parts) + "\n" if ind_parts else ""

        current = candles[-1] if candles else None
        momentum_text = ""
        if current and indicators.atr_14:
            range_ratio = current.range_size / indicators.atr_14 if indicators.atr_14 > 0 else 0
            body_ratio = current.body_size / indicators.atr_14 if indicators.atr_14 > 0 else 0
            candle_type = "BULLISH" if current.is_bullish else "BEARISH"
            momentum_text = (
                f"Candle Momentum Analysis (SETUP CANDLE):\n"
                f"  Type: {candle_type} | Body: {current.body_size:.2f} | Range: {current.range_size:.2f}\n"
                f"  Body/ATR ratio: {body_ratio:.2f}x | Range/ATR ratio: {range_ratio:.2f}x\n"
                f"  Upper wick: {current.upper_wick:.2f} | Lower wick: {current.lower_wick:.2f}\n"
                f"  NOTE: Body/ATR > 1.0x = aggressive candle. Range/ATR > 1.5x = abnormal volatility.\n\n"
            )

        sr_text = ""
        if sr_zones:
            sr_text = "S/R Zones:\n"
            for z in sr_zones[:5]:
                sr_text += f"  {z.get('zone_type')} at {z.get('price_level')} (score: {z.get('strength_score', 0):.2f})\n"

        tf_warning = ""
        if signal.timeframe in ['5m', '15m']:
            tf_warning = "WARNING: This is a low timeframe (5m/15m) signal which is highly noisy. You MUST be extremely critical and strictly REJECT this signal unless there is absolute perfect confluence across all indicators and strong S/R zones. Default to REJECT for these unless perfectly clear.\n\n"

        htf_text = ""
        if htf_candles:
            htf_text = "Higher Timeframe (Macro Trend) Candles:\n"
            for c in htf_candles[-10:]:
                htf_text += f"{c.open_time.strftime('%Y-%m-%d %H:%M')} O:{c.open:.2f} C:{c.close:.2f}\n"

        prompt = (
            f"You are an elite crypto trading risk manager. Your job is to PROTECT capital. "
            f"Review this algorithmic signal and decide: CONFIRM, REJECT, or MODIFY.\n\n"
            f"{tf_warning}"
            f"CRITICAL RULES:\n"
            f"1. You MUST write your full reasoning FIRST, then assign a confidence score, then give the verdict.\n"
            f"2. Only reference indicators that are provided in the data below. Do NOT invent or hallucinate data points.\n"
            f"3. If you are unsure, REJECT. Capital preservation is the priority.\n\n"
            f"VERIFICATION STEPS (analyze each one in your reasoning):\n"
            f"1. Candle Momentum: Check the Body/ATR and Range/ATR ratios. If the setup candle is abnormally large (body > 1.0x ATR), "
            f"this may be a momentum crash, not a pullback. Be very suspicious.\n"
            f"2. Trend Alignment: Does the signal align with the Higher Timeframe trend? If not, REJECT.\n"
            f"3. Micro-Structure: Are you buying into immediate resistance or shorting into support? If yes, REJECT.\n"
            f"4. Risk/Reward: Is the SL too tight for current ATR volatility? If yes, MODIFY the SL to be safer.\n\n"
            f"Pair: {signal.symbol} | TF: {signal.timeframe} | Dir: {signal.direction} | Strategy: {signal.strategy_name}\n"
            f"Entry: {signal.entry} | SL: {signal.sl} | TP1: {signal.tp1} | TP2: {signal.tp2} | Conf: {signal.confidence:.2f}\n"
            f"Notes: {signal.notes}\n\n"
            f"{momentum_text}"
            f"{ind_text}\n"
            f"{sr_text}\n"
            f"{htf_text}\n"
            f"{candle_text}\n"
            f"Respond ONLY in valid JSON. Write reasoning FIRST, then confidence_score (1-10), then verdict:\n"
            f'{{"reasoning": "your step-by-step analysis here", "confidence_score": 1, "verdict": "CONFIRM|REJECT|MODIFY", '
            f'"modified_sl": null, "modified_tp1": null, "modified_tp2": null}}\n'
        )
        return prompt

    @staticmethod
    def _build_dual_context_prompt(
        signal: SetupSignal,
        candles: list[Candle],
        indicators: Indicators,
        sr_zones: list[dict],
        htf_context=None,
    ) -> str:
        """Build a dual-context prompt with MACRO CONTEXT + MICRO TRIGGER sections."""
        context_tf = signal.context_tf or "HTF"
        execution_tf = signal.execution_tf or signal.timeframe

        # --- MACRO CONTEXT ---
        macro_parts = [f"=== MACRO CONTEXT (HTF — {context_tf}) ==="]

        if htf_context is not None:
            regime = getattr(htf_context, 'regime', 'NEUTRAL')
            macro_parts.append(f"Regime: {regime}")

            active_zones = getattr(htf_context, 'active_zones', [])
            if active_zones:
                zones_text = "Active Zones:"
                for az in active_zones[:5]:
                    zones_text += f"\n  {az.zone_type} ({az.direction}) [{az.bottom:.2f} - {az.top:.2f}]"
                macro_parts.append(zones_text)

            indicators_snapshot = getattr(htf_context, 'indicators_snapshot', {})
            if indicators_snapshot:
                snap_parts = []
                if indicators_snapshot.get('ema_50'):
                    snap_parts.append(f"EMA50={indicators_snapshot['ema_50']:.2f}")
                if indicators_snapshot.get('ema_200'):
                    snap_parts.append(f"EMA200={indicators_snapshot['ema_200']:.2f}")
                if indicators_snapshot.get('rsi_14'):
                    snap_parts.append(f"RSI={indicators_snapshot['rsi_14']:.1f}")
                if indicators_snapshot.get('atr_14'):
                    snap_parts.append(f"ATR={indicators_snapshot['atr_14']:.4f}")
                if snap_parts:
                    macro_parts.append("HTF Indicators: " + ", ".join(snap_parts))

        if signal.htf_context_summary:
            macro_parts.append(f"Summary: {signal.htf_context_summary}")

        macro_section = "\n".join(macro_parts) + "\n\n"

        # --- MICRO TRIGGER ---
        micro_parts = [f"=== MICRO TRIGGER (LTF — {execution_tf}) ==="]

        if signal.ltf_trigger_summary:
            micro_parts.append(f"Trigger: {signal.ltf_trigger_summary}")

        if indicators:
            ltf_parts = []
            if indicators.ema_9 is not None:
                ltf_parts.append(f"EMA9={indicators.ema_9:.2f}")
            if indicators.ema_21 is not None:
                ltf_parts.append(f"EMA21={indicators.ema_21:.2f}")
            if indicators.rsi_14 is not None:
                ltf_parts.append(f"RSI={indicators.rsi_14:.1f}")
            if indicators.atr_14 is not None:
                ltf_parts.append(f"ATR={indicators.atr_14:.4f}")
            if ltf_parts:
                micro_parts.append("LTF Indicators: " + ", ".join(ltf_parts))

            current = candles[-1] if candles else None
            if current and indicators.atr_14:
                body_ratio = current.body_size / indicators.atr_14 if indicators.atr_14 > 0 else 0
                range_ratio = current.range_size / indicators.atr_14 if indicators.atr_14 > 0 else 0
                candle_type = "BULLISH" if current.is_bullish else "BEARISH"
                micro_parts.append(
                    f"Trigger Candle: {candle_type} | "
                    f"Body/ATR: {body_ratio:.2f}x | Range/ATR: {range_ratio:.2f}x | "
                    f"U-wick: {current.upper_wick:.2f} | L-wick: {current.lower_wick:.2f}"
                )

        if candles:
            recent = candles[-10:] if len(candles) >= 10 else candles
            ltf_candle_text = "LTF Candles (last 10):\n"
            for c in recent:
                ltf_candle_text += f"  {c.open_time.strftime('%Y-%m-%d %H:%M')} O:{c.open:.2f} H:{c.high:.2f} L:{c.low:.2f} C:{c.close:.2f} V:{c.volume:.0f}\n"
            micro_parts.append(ltf_candle_text.strip())

        micro_section = "\n".join(micro_parts) + "\n\n"

        # --- TRADE PROPOSAL ---
        trade_parts = [
            "=== TRADE PROPOSAL ===",
            f"Direction: {signal.direction}",
            f"Entry: {signal.entry}",
            f"SL: {signal.sl}",
            f"TP1: {signal.tp1}, TP2: {signal.tp2}",
            f"Confidence: {signal.confidence:.2f}",
            f"Strategy: {signal.strategy_name}",
            f"Notes: {signal.notes}",
        ]
        trade_section = "\n".join(trade_parts) + "\n\n"

        prompt = (
            f"You are an elite crypto trading risk manager. Your job is to PROTECT capital. "
            f"Review this algorithmic signal and decide: CONFIRM, REJECT, or MODIFY.\n\n"
            f"CRITICAL RULES:\n"
            f"1. You MUST write your full reasoning FIRST, then assign a confidence score, then give the verdict.\n"
            f"2. Only reference data provided below. Do NOT invent or hallucinate data points.\n"
            f"3. If you are unsure, REJECT. Capital preservation is the priority.\n\n"
            f"VERIFICATION STEPS:\n"
            f"1. MACRO ALIGNMENT: Does the MICRO trigger align with the MACRO context (regime + active zones)?\n"
            f"2. ZONE INTERACTION: Is the entry near a valid Active Zone from the HTF context? If not, REJECT.\n"
            f"3. CANDLE QUALITY: Does the trigger candle show proper rejection or confirmation?\n"
            f"4. RISK/REWARD: Is the SL too tight for current ATR volatility? If yes, MODIFY.\n\n"
            f"Your job: Does the MICRO trigger align with the MACRO context?\n"
            f"Confirm, Reject, or Modify the trade with reasoning.\n\n"
            f"{macro_section}"
            f"{micro_section}"
            f"{trade_section}"
            f"Respond ONLY in valid JSON. Write reasoning FIRST, then confidence_score (1-10), then verdict:\n"
            f'{{"reasoning": "your step-by-step analysis here", "confidence_score": 1, "verdict": "CONFIRM|REJECT|MODIFY", '
            f'"modified_sl": null, "modified_tp1": null, "modified_tp2": null}}\n'
        )
        return prompt

    @staticmethod
    def _build_prompt_context(
        signal: SetupSignal,
        candles: list[Candle],
        indicators: Indicators,
        sr_zones: list[dict],
        htf_candles: list[Candle] = None,
        htf_context=None,
    ) -> str:
        """
        Routes to legacy or dual-context prompt builder based on signal MTF metadata.
        """
        if signal.context_tf and signal.htf_context_summary:
            return LLMClient._build_dual_context_prompt(
                signal, candles, indicators, sr_zones, htf_context
            )
        return LLMClient._build_legacy_prompt(
            signal, candles, indicators, sr_zones, htf_candles
        )

    @staticmethod
    def evaluate_signal(
        signal: SetupSignal,
        candles: list[Candle],
        indicators: Indicators,
        sr_zones: list[dict],
        htf_candles: list[Candle] = None,
        htf_context=None,
    ) -> Tuple[Optional[LLMVerdictSchema], str, str]:
        """
        Sends the signal and context to the configured LLM synchronously.
        Returns a tuple: (parsed LLMVerdictSchema or None, prompt used, raw response text).
        """
        prompt = LLMClient._build_prompt_context(signal, candles, indicators, sr_zones, htf_candles, htf_context)
        
        system_prompt = (
            "You are a quantitative trading risk manager. "
            "You may use your internal reasoning capabilities first. "
            "However, your final, conclusive output MUST be a valid JSON object matching the requested schema. "
            "CRITICAL: Do NOT use newlines (\\n) inside JSON string values. Write the JSON reasoning key as a single paragraph."
        )

        try:
            provider = get_llm_provider()
            content, raw_response = provider.evaluate_prompt(system_prompt, prompt)
            
            if not content:
                # Logging happens in provider, just return
                return None, prompt, raw_response

            logger.info(f"[LLMClient] Received response ({len(content)} chars)")
            
            # Defensive strip of markdown codeblocks occasionally generated by LLMs
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # Some models wrap in <think>...</think> tags — strip those
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8:].strip()
            
            # Try to find JSON object if there's extra text around it
            if not content.startswith("{"):
                json_start = content.find("{")
                if json_start != -1:
                    content = content[json_start:]
            if not content.endswith("}"):
                json_end = content.rfind("}")
                if json_end != -1:
                    content = content[:json_end + 1]

            # Parse with builtin JSON parser allowing strict=False for control characters (e.g. unescaped newlines)
            raw_dict = json.loads(content, strict=False)
            parsed = LLMVerdictSchema.model_validate(raw_dict)
            
            # Ensure proper string matching
            if parsed.verdict not in ('CONFIRM', 'REJECT', 'MODIFY'):
                logger.error(f"LLM produced invalid verdict: {parsed.verdict}")
                return None, prompt, raw_response

            # Clamp confidence_score to valid range
            parsed.confidence_score = max(1, min(10, parsed.confidence_score))

            # Safety net: auto-downgrade low-confidence CONFIRMs
            if parsed.verdict == 'CONFIRM' and parsed.confidence_score < LLM_CONFIDENCE_THRESHOLD:
                logger.warning(
                    f"[LLMClient] Auto-downgrade: LLM said CONFIRM but confidence_score={parsed.confidence_score} "
                    f"(< {LLM_CONFIDENCE_THRESHOLD}). Overriding to REJECT."
                )
                parsed.verdict = 'REJECT'
                parsed.reasoning += f" [AUTO-REJECTED: confidence_score {parsed.confidence_score}/10 below threshold {LLM_CONFIDENCE_THRESHOLD}]"

            return parsed, prompt, raw_response
            
        except json.JSONDecodeError as e:
            logger.error(f"LLM JSON Decode error: {str(e)}\nRaw Response: {content}")
            return None, prompt, f"ERROR: JSONDecodeError - {str(e)}\nRaw block: {raw_response}"
        except ValidationError as e:
            logger.error(f"LLM JSON Schema validation error: {str(e)}\nRaw Response: {content}")
            return None, prompt, f"ERROR: ValidationError - {str(e)}\nRaw block: {raw_response}"
        except Exception as e:
            logger.error(f"Unexpected error in LLM evaluate_signal: {str(e)}")
            return None, prompt, f"ERROR: Unexpected exception - {str(e)}"

    @staticmethod
    def ping_status() -> bool:
        """
        Pings the LLM backend to verify it is online.
        """
        provider = get_llm_provider()
        return provider.ping_status()
