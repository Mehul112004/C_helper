import json
import logging
import time
import requests
from typing import Tuple, Optional
from app.core.llm_providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)

# HTTP status codes that warrant a retry
RETRYABLE_STATUSES = {429, 502, 503, 504}

class OpenAICompatibleProvider(BaseLLMProvider):
    """
    Provider that interfaces with any API matching the OpenAI Chat Completions structure.
    Works for LM Studio, Groq, OpenRouter, OpenAI, etc.
    """

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAYS = [5, 20, 60]  # seconds — escalating backoff
    RATE_LIMIT_FALLBACK_DELAY = 30  # seconds — used when no Retry-After header

    def __init__(self, api_url: str, model: str, api_key: str = None, timeout: int = 200, max_tokens: int = 500):
        self.api_url = api_url
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens

    def evaluate_prompt(self, system_prompt: str, user_prompt: str) -> Tuple[Optional[str], str]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
            "stream": False
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            if "openrouter" in self.api_url.lower():
                headers["HTTP-Referer"] = "http://localhost:5000"
                headers["X-Title"] = "Crypto Signal Helper"

        last_error = ""
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                logger.info(
                    f"[{self.__class__.__name__}] Sending request to {self.api_url} "
                    f"(model={self.model}, timeout={self.timeout}s)"
                    f"{f', attempt {attempt + 1}/{self.MAX_RETRIES + 1}' if attempt > 0 else ''}"
                )
                resp = requests.post(self.api_url, json=payload, headers=headers, timeout=self.timeout)

                # ── Handle rate limiting (429) and transient server errors (502-504) ──
                if resp.status_code in RETRYABLE_STATUSES:
                    # Extract Retry-After header if present
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = int(retry_after)
                        except ValueError:
                            delay = self.RATE_LIMIT_FALLBACK_DELAY
                    elif resp.status_code == 429:
                        delay = self.RATE_LIMIT_FALLBACK_DELAY
                    else:
                        delay = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]

                    error_body = resp.text[:300] if resp.text else "No response body"
                    logger.warning(
                        f"[{self.__class__.__name__}] Rate limited (HTTP {resp.status_code}). "
                        f"Retry-After: {retry_after or 'not set'}, backing off {delay}s. "
                        f"Body: {error_body}"
                    )

                    if attempt < self.MAX_RETRIES:
                        for _ in range(delay):
                            time.sleep(1)
                        continue
                    else:
                        return None, f"ERROR: HTTP {resp.status_code} after {self.MAX_RETRIES + 1} attempts. {error_body}"

                resp.raise_for_status()
                data = resp.json()

                choices = data.get("choices", [])
                if not choices:
                    logger.error(f"[{self.__class__.__name__}] No choices in response: {json.dumps(data)[:500]}")
                    return None, json.dumps(data)

                content = choices[0].get("message", {}).get("content", "")
                if content is None:
                    content = ""
                content = content.strip()

                if not content:
                    finish_reason = choices[0].get('finish_reason', 'unknown')
                    logger.error(f"[{self.__class__.__name__}] Empty content. Finish reason: {finish_reason}")
                    if finish_reason == "length":
                        return None, "ERROR: Truncated text/Exceeded TPM Context. Prompt might be too long."
                    return None, json.dumps(data)

                return content, json.dumps(data)

            except requests.exceptions.Timeout:
                logger.error(f"[{self.__class__.__name__}] Request timed out after {self.timeout}s.")
                last_error = "ERROR: Request timed out"
            except requests.exceptions.RequestException as e:
                logger.error(f"[{self.__class__.__name__}] Connection error: {str(e)}")
                raw_resp = getattr(e.response, 'text', '') if hasattr(e, 'response') and e.response else ''
                last_error = f"ERROR: Connection error - {str(e)}\nResponse: {raw_resp}"
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}] Unexpected error: {str(e)}")
                last_error = f"ERROR: Unexpected exception - {str(e)}"

            # Only retry non-HTTP errors (network issues, timeouts)
            if attempt < self.MAX_RETRIES:
                delay = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]
                logger.info(f"[{self.__class__.__name__}] Retrying in {delay}s...")
                for _ in range(delay):
                    time.sleep(1)

        return None, last_error

    def ping_status(self) -> bool:
        """
        Pings the provider to verify connectivity. 
        For local instances (like LM Studio), attempts to hit /models.
        For cloud instances, assumes True to save latency, or falls back to a ping if necessary.
        """
        if "localhost" in self.api_url or "127.0.0.1" in self.api_url:
            url = self.api_url.replace("/chat/completions", "/models")
            try:
                resp = requests.get(url, timeout=5)
                return resp.status_code == 200
            except requests.exceptions.RequestException:
                return False
        
        # Cloud integrations usually are up, failures handled at run time.
        return True
