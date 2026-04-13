"""
Standalone Telegram test — bypasses the entire app to isolate credential issues.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

print(f"Bot Token: {bot_token[:10]}...{bot_token[-5:]}")
print(f"Chat ID:   {chat_id}")

if not bot_token or not chat_id:
    print("\n❌ Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env")
    exit(1)

# Step 1: Verify the bot token is valid
print("\n--- Step 1: Verifying bot token via getMe ---")
r = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10)
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

if r.status_code != 200:
    print("\n❌ Bot token is INVALID. Double-check with BotFather.")
    exit(1)
print("✅ Bot token is valid.\n")

# Step 2: Send a test message
print("--- Step 2: Sending test message ---")
test_msg = "🧪 *Test from Crypto Signal Intelligence Platform*\n\nIf you see this, Telegram integration is working!"

payload = {
    "chat_id": chat_id,
    "text": test_msg,
    "parse_mode": "Markdown",
}

r2 = requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload, timeout=10)
print(f"Status: {r2.status_code}")
print(f"Response: {r2.json()}")

if r2.status_code == 200:
    msg_id = r2.json().get("result", {}).get("message_id")
    print(f"\n✅ Message sent! message_id={msg_id}")
    print("Check your Telegram app now.")
else:
    error = r2.json().get("description", "unknown error")
    print(f"\n❌ Failed to send: {error}")
    if "chat not found" in error.lower():
        print("   → You need to open your bot in Telegram and press /start first.")
    elif "bot was blocked" in error.lower():
        print("   → You blocked the bot. Unblock it in Telegram.")
