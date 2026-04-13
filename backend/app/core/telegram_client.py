import os
import requests
import logging

logger = logging.getLogger(__name__)

class TelegramBotClient:
    """
    Lightweight, synchronous client for sending Telegram messages using requests.
    Designed to be used within background queues/threads safely.
    """
    
    def __init__(self):
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        
        if self.bot_token:
            self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        else:
            self.base_url = None
            
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)
        
    def send_message(self, text: str, reply_to_message_id: str | None = None) -> dict | None:
        """
        Send a notification to the configured chat.
        Returns the JSON response from Telegram if successful, else None.
        May raise requests.RequestException on network errors.
        """
        if not self.is_configured():
            logger.warning("Telegram is not configured. Skipping message delivery.")
            return None
            
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        
        if reply_to_message_id:
            payload["reply_parameters"] = {
                "message_id": int(reply_to_message_id)
            }
            
        # 10s timeout to avoid locking background threads indefinitely
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Telegram API Error [{response.status_code}]: {response.text}")
            return None

telegram_client = TelegramBotClient()
