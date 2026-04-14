import json
import logging
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, ValidationError

from app.core.base_strategy import SetupSignal, Candle, Indicators

logger = logging.getLogger(__name__)

# Config
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_STUDIO_MODEL = "meta-llama-3.1-8b-instruct"
REQUEST_TIMEOUT = 480  # seconds — generous timeout for large context windows on local LLMs

class LLMVerdictSchema(BaseModel):
    verdict: str = Field(..., description="Must be exactly CONFIRM, REJECT, or MODIFY")
    reasoning: str = Field(..., description="2-3 sentence explanation of why this verdict was reached based on the technical context provided.")
    modified_sl: Optional[float] = Field(None, description="Suggested Stop Loss if verdict is MODIFY")
    modified_tp1: Optional[float] = Field(None, description="Suggested TP1 if verdict is MODIFY")
    modified_tp2: Optional[float] = Field(None, description="Suggested TP2 if verdict is MODIFY")

class LLMClient:
    """
    Client for interacting with the local LM Studio instance.
    Formats market context and parses the JSON response using Pydantic.
    """

    @staticmethod
    def _build_prompt_context(
        signal: SetupSignal,
        candles: list[Candle],
        indicators: Indicators,
        sr_zones: list[dict]
    ) -> str:
        """
        Constructs the system/user prompt combining the setup and the raw data.
        Limits the candle data to the last 20 to reduce context size and speed up inference.
        """
        # Take the last 20 candles (reduced from 30 to speed up LLM response)
        recent_candles = candles[-20:] if len(candles) >= 20 else candles
        candle_text = "Recent Candles (OHLCV):\n"
        for c in recent_candles:
            candle_text += f"{c.open_time.strftime('%Y-%m-%d %H:%M')} O:{c.open:.2f} H:{c.high:.2f} L:{c.low:.2f} C:{c.close:.2f} V:{c.volume:.0f}\n"

        # Indicators text — only include non-None values
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

        # S/R Zones text
        sr_text = ""
        if sr_zones:
            sr_text = "S/R Zones:\n"
            for idx, z in enumerate(sr_zones[:5]): # limit to 5
                sr_text += f"  {z.get('zone_type')} at {z.get('price_level')} (score: {z.get('strength_score', 0):.2f})\n"

        prompt = (
            f"You are a crypto trading analyst. Review this algorithmic trade signal and decide: CONFIRM, REJECT, or MODIFY.\n\n"
            f"Pair: {signal.symbol} | TF: {signal.timeframe} | Dir: {signal.direction} | Strategy: {signal.strategy_name}\n"
            f"Entry: {signal.entry} | SL: {signal.sl} | TP1: {signal.tp1} | TP2: {signal.tp2} | Conf: {signal.confidence:.2f}\n"
            f"Notes: {signal.notes}\n\n"
            f"{ind_text}\n"
            f"{sr_text}\n"
            f"{candle_text}\n"
            f"Respond ONLY in valid JSON, no markdown:\n"
            f'{{"verdict": "CONFIRM|REJECT|MODIFY", "reasoning": "string", "modified_sl": null, "modified_tp1": null, "modified_tp2": null}}\n'
        )
        return prompt

    @staticmethod
    def evaluate_signal(
        signal: SetupSignal,
        candles: list[Candle],
        indicators: Indicators,
        sr_zones: list[dict]
    ) -> Optional[LLMVerdictSchema]:
        """
        Sends the signal and context to LM Studio synchronously.
        Returns the parsed LLMVerdictSchema or None on failure.
        """
        prompt = LLMClient._build_prompt_context(signal, candles, indicators, sr_zones)
        
        payload = {
            "model": LM_STUDIO_MODEL,
            "messages": [
                {"role": "system", "content": "You are a quantitative trading system. Output ONLY valid JSON. No markdown, no explanation outside the JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2, # Deterministic reasoning
            "max_tokens": 6000, # Must be high enough to accommodate the model's thinking/reasoning process
            "stream": False
        }

        try:
            logger.info(f"[LLMClient] Sending request to LM Studio (timeout={REQUEST_TIMEOUT}s)...")
            resp = requests.post(LM_STUDIO_URL, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            
            # Extract content
            choices = data.get("choices", [])
            if not choices:
                logger.error(f"[LLMClient] No choices in response: {json.dumps(data)[:500]}")
                return None
            
            content = choices[0].get("message", {}).get("content", "").strip()
            
            if not content:
                # Log the full response for debugging
                logger.error(f"[LLMClient] Empty content from LLM. Full response: {json.dumps(data)[:1000]}")
                logger.error(f"[LLMClient] Finish reason: {choices[0].get('finish_reason', 'unknown')}")
                return None
            
            logger.info(f"[LLMClient] Received response ({len(content)} chars), finish_reason={choices[0].get('finish_reason', 'unknown')}")
            
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

            # Parse with Pydantic
            parsed = LLMVerdictSchema.model_validate_json(content)
            
            # Ensure proper string matching
            if parsed.verdict not in ('CONFIRM', 'REJECT', 'MODIFY'):
                logger.error(f"LLM produced invalid verdict: {parsed.verdict}")
                return None
                
            return parsed
            
        except requests.exceptions.Timeout:
            logger.error(f"[LLMClient] Request timed out after {REQUEST_TIMEOUT}s. Model may be overloaded.")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"LM Studio connection error: {str(e)}")
            return None
        except ValidationError as e:
            logger.error(f"LLM JSON Schema validation error: {str(e)}\nRaw Response: {content}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in LLM evaluate_signal: {str(e)}")
            return None

    @staticmethod
    def ping_status() -> bool:
        """
        Pings the LM Studio /v1/models endpoint to verify it is online.
        """
        url = LM_STUDIO_URL.replace("/chat/completions", "/models")
        try:
            resp = requests.get(url, timeout=5)
            return resp.status_code == 200
        except requests.exceptions.RequestException:
            return False
