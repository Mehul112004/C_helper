import json
import logging
import requests
from typing import Tuple, Optional
from app.core.llm_providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)

class OpenAICompatibleProvider(BaseLLMProvider):
    """
    Provider that interfaces with any API matching the OpenAI Chat Completions structure.
    Works for LM Studio, Groq, OpenRouter, OpenAI, etc.
    """
    def __init__(self, api_url: str, model: str, api_key: str = None, timeout: int = 200, max_tokens: int = 2500):
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
            "temperature": 0.2, # Deterministic reasoning
            "max_tokens": self.max_tokens,
            "stream": False
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            # Send OpenRouter specific headers if needed
            if "openrouter" in self.api_url.lower():
                headers["HTTP-Referer"] = "http://localhost:5000"
                headers["X-Title"] = "Crypto Signal Helper"

        try:
            logger.info(f"[{self.__class__.__name__}] Sending request to {self.api_url} (model={self.model}, timeout={self.timeout}s)...")
            resp = requests.post(self.api_url, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            
            choices = data.get("choices", [])
            if not choices:
                logger.error(f"[{self.__class__.__name__}] No choices in response: {json.dumps(data)[:500]}")
                return None, json.dumps(data)
                
            content = choices[0].get("message", {}).get("content", "").strip()
            
            if not content:
                logger.error(f"[{self.__class__.__name__}] Empty content from LLM. Finish reason: {choices[0].get('finish_reason', 'unknown')}")
                return None, json.dumps(data)
                
            return content, json.dumps(data)
            
        except requests.exceptions.Timeout:
            logger.error(f"[{self.__class__.__name__}] Request timed out after {self.timeout}s.")
            return None, "ERROR: Request timed out"
        except requests.exceptions.RequestException as e:
            logger.error(f"[{self.__class__.__name__}] Connection error: {str(e)}")
            raw_resp = getattr(e.response, 'text', '') if hasattr(e, 'response') and e.response else ''
            return None, f"ERROR: Connection error - {str(e)}\nResponse: {raw_resp}"
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] Unexpected error: {str(e)}")
            return None, f"ERROR: Unexpected exception - {str(e)}"

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
