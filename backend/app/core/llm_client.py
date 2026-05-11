"""
LLM Client v2 — Structured Context Evaluation

Receives a structured multi-dimensional payload from llm_context_builder
instead of flat text from Candle/Indicators objects. The structured format
lets the LLM reason across 5 dimensions with precise numeric data.

The prompt is now a clean system prompt + JSON payload → LLM → JSON verdict.
"""

import json
import logging
from typing import Optional, Dict, Any, Tuple

from pydantic import BaseModel, Field, ValidationError

from app.core.llm_providers.factory import get_llm_provider

logger = logging.getLogger(__name__)

LLM_CONFIDENCE_THRESHOLD = 4  # Minimum score (1-10) for CONFIRM verdict


class LLMVerdictSchema(BaseModel):
    """Chain-of-thought verdict: reasoning MUST come before verdict."""
    reasoning: str = Field(...,
        description="Step-by-step analysis across all 5 dimensions. Be specific with numbers.")
    confidence_score: int = Field(...,
        description="Confidence 1-10. 1=extremely risky, 10=textbook setup.")
    verdict: str = Field(...,
        description="Must be exactly CONFIRM, REJECT, or MODIFY.")
    modified_sl: Optional[float] = Field(None)
    modified_tp1: Optional[float] = Field(None)
    modified_tp2: Optional[float] = Field(None)


class LLMClient:
    """
    Evaluates trading signals via LLM using structured market context.

    The context payload contains 5 dimensions:
      1. signal_metadata    — symbol, strategy, timeframe, direction, levels
      2. market_structure   — bias, BOS/CHoCH, OB, FVG, sweep, swing levels
      3. indicators         — RSI+gradient+divergence, EMA alignment, MACD, BB, ADX
      4. volume             — RVOL, climax status
      5. htf_context        — primary + higher timeframe biases
      6. recent_price_action — last 20 OHLCV candles
    """

    SYSTEM_PROMPT = (
        "You are an elite crypto trading risk manager. Your job is to PROTECT capital. "
        "You will receive a structured JSON payload containing market context across "
        "5 dimensions: market structure, indicators, volume, multi-timeframe context, "
        "and recent price action.\n\n"
        "ANALYZE EACH DIMENSION in your reasoning:\n"
        "1. Market Structure: Is the bias aligned with the trade direction? "
        "Are there BOS/CHoCH events confirming? Is price near an OB or FVG?\n"
        "2. Indicators: Is RSI gradient aligned? Any divergence? Are EMAs stacked "
        "correctly? Is MACD accelerating in the trade direction?\n"
        "3. Volume: Is RVOL > 1.0 confirming participation? Any climax exhaustion?\n"
        "4. HTF Context: Do higher timeframes support or oppose this trade?\n"
        "5. Price Action: Check recent candles for rejection wicks, engulfing, pin bars.\n\n"
        "DECISION RULES:\n"
        "- CONFIRM: All dimensions align. Confidence >= 7 required. Strategy confidence + "
        "market alignment both strong.\n"
        "- REJECT: Any dimension strongly opposes (counter-trend, low volume, negative divergence). "
        "Default to REJECT if unsure.\n"
        "- MODIFY: Trade is valid but SL/TP need adjustment based on ATR or structural levels.\n\n"
        "Respond ONLY in valid JSON (no markdown, no code blocks):\n"
        '{"reasoning": "...", "confidence_score": 5, "verdict": "CONFIRM", '
        '"modified_sl": null, "modified_tp1": null, "modified_tp2": null}'
    )

    @staticmethod
    def _build_prompt(context: Dict[str, Any]) -> str:
        """Build the user prompt from the structured context payload."""
        meta = context.get('signal_metadata', {})
        structure = context.get('market_structure', {})
        indicators = context.get('indicators', {})
        volume = context.get('volume', {})
        htf = context.get('htf_context', {})

        prompt = (
            f"EVALUATE THIS TRADING SIGNAL:\n\n"
            f"Symbol: {meta.get('symbol')} | Strategy: {meta.get('strategy')} | "
            f"TF: {meta.get('timeframe')} | Side: {meta.get('side')}\n"
            f"Entry: {meta.get('entry')} | SL: {meta.get('sl')} | "
            f"TP1: {meta.get('tp1')} | TP2: {meta.get('tp2')}\n"
            f"Strategy Confidence: {meta.get('confidence')} | Regime: {meta.get('regime')}\n\n"

            f"═══ MARKET STRUCTURE ═══\n"
            f"Bias: {structure.get('current_bias')} | Structural: {structure.get('structural_bias')}\n"
            f"Last SMC Event: {structure.get('last_event', 'N/A')}\n"
            f"Liquidity Sweep Recent: {structure.get('liquidity_sweep_recent', False)}\n"
            f"OB Active: {structure.get('nearest_order_block', {}).get('active', False)}\n"
            f"FVG Status: {structure.get('fvg_status', 'N/A')}\n"
            f"Swing High: {structure.get('recent_swing_high')} | "
            f"Swing Low: {structure.get('recent_swing_low')}\n"
            f"Price Position in Range: {structure.get('price_position_in_range_pct', 'N/A')}%\n\n"

            f"═══ INDICATORS ═══\n"
            f"RSI: {indicators.get('rsi', 'N/A')} | "
            f"Gradient: {indicators.get('rsi_gradient', 'N/A')} | "
            f"Divergence: {indicators.get('rsi_divergence', 'N/A')}\n"
            f"EMA Alignment: {indicators.get('ema_alignment', 'N/A')}\n"
            f"BB State: {indicators.get('bb_state', 'N/A')}\n"
            f"ADX: {indicators.get('adx', 'N/A')} | "
            f"Trend Strength: {indicators.get('trend_strength', 'N/A')}\n"
        )

        if indicators.get('macd'):
            m = indicators['macd']
            prompt += f"MACD: Hist={m.get('histogram')} | {m.get('momentum')} | {m.get('direction')}\n"

        if indicators.get('ema_values'):
            prompt += f"EMA Values: {indicators['ema_values']}\n"

        prompt += (
            f"\n═══ VOLUME ═══\n"
            f"RVOL: {volume.get('rvol', 'N/A')}x | "
            f"Volume Climax: {volume.get('is_climax', False)}\n\n"

            f"═══ HTF CONTEXT ═══\n"
            f"Primary Bias: {htf.get('primary_bias', 'N/A')}\n"
        )

        for k, v in htf.items():
            if k != 'primary_bias':
                prompt += f"{k}: {v}\n"

        prompt += (
            f"\n═══ RECENT PRICE ACTION ═══\n"
            f"See attached candles array in the context.\n"
            f"Look for: pin bars (long wick, small body), engulfing candles, "
            f"doji indecision, and support/resistance tests.\n\n"
            f"Respond with JSON only: {{\"reasoning\": \"...\", \"confidence_score\": N, "
            f"\"verdict\": \"CONFIRM|REJECT|MODIFY\", \"modified_sl\": null, ...}}"
        )

        return prompt

    @staticmethod
    def evaluate_signal(context: Dict[str, Any]) -> Tuple[Optional[LLMVerdictSchema], str, str]:
        """
        Evaluate a trading signal using the structured context payload.

        Args:
            context: Dict from llm_context_builder.build_llm_context()

        Returns:
            Tuple: (parsed LLMVerdictSchema or None, prompt_text, raw_response_text)
        """
        prompt = LLMClient._build_prompt(context)

        try:
            provider = get_llm_provider()
            content, raw_response = provider.evaluate_prompt(
                LLMClient.SYSTEM_PROMPT, prompt
            )

            if not content:
                return None, prompt, raw_response

            logger.info(f"[LLMClient] Received response ({len(content)} chars)")

            return _parse_llm_response(content, prompt, raw_response)

        except Exception as e:
            logger.error(f"Unexpected error in LLM evaluate_signal: {e}")
            return None, prompt, f"ERROR: {e}"


def _parse_llm_response(
    content: str, prompt: str, raw_response: str
) -> Tuple[Optional[LLMVerdictSchema], str, str]:
    """Parse the LLM's JSON response, handling common formatting issues."""

    # Strip markdown code blocks
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    # Strip <think>...</think> tags (some models)
    if "<think>" in content:
        think_end = content.find("</think>")
        if think_end != -1:
            content = content[think_end + 8:].strip()

    # Find JSON object boundaries
    if not content.startswith("{"):
        json_start = content.find("{")
        if json_start != -1:
            content = content[json_start:]
    if not content.endswith("}"):
        json_end = content.rfind("}")
        if json_end != -1:
            content = content[:json_end + 1]

    try:
        raw_dict = json.loads(content, strict=False)
        parsed = LLMVerdictSchema.model_validate(raw_dict)

        if parsed.verdict not in ('CONFIRM', 'REJECT', 'MODIFY'):
            logger.error(f"LLM produced invalid verdict: {parsed.verdict}")
            return None, prompt, raw_response

        parsed.confidence_score = max(1, min(10, parsed.confidence_score))

        # Auto-downgrade low-confidence CONFIRMs
        if parsed.verdict == 'CONFIRM' and parsed.confidence_score < LLM_CONFIDENCE_THRESHOLD:
            logger.warning(
                f"[LLMClient] Auto-downgrade: CONFIRM but confidence={parsed.confidence_score} "
                f"< {LLM_CONFIDENCE_THRESHOLD}. Overriding to REJECT."
            )
            parsed.verdict = 'REJECT'
            parsed.reasoning += (
                f" [AUTO-REJECTED: confidence {parsed.confidence_score}/10 "
                f"below threshold {LLM_CONFIDENCE_THRESHOLD}]"
            )

        return parsed, prompt, raw_response

    except json.JSONDecodeError as e:
        logger.error(f"LLM JSON decode error: {e}\nContent: {content[:200]}")
        return None, prompt, f"JSONDecodeError: {e}"
    except ValidationError as e:
        logger.error(f"LLM schema validation error: {e}")
        return None, prompt, f"ValidationError: {e}"


@staticmethod
def ping_status() -> bool:
    """Check if the LLM backend is online."""
    provider = get_llm_provider()
    return provider.ping_status()
