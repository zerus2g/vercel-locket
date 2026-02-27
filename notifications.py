import os
import json
import time
import requests

def send_telegram_notification(username, uid, product_id, raw_json):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("Telegram notification skipped: Token or Chat ID not set.")
        return

    used_token = raw_json.pop("__used_token_name", "Unknown")

    subscription_info = json.dumps(
        raw_json.get("subscriber", {}).get("entitlements", {}).get("Gold", {}), indent=2
    )

    message = f"✅ <b>Locket Gold Unlocked!</b>\n\n👤 <b>User:</b> {username} ({uid})\n🔑 <b>Token:</b> {used_token}\n⏰ <b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n<b>Subscription Info:</b>\n<pre>{subscription_info}</pre>"
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send Telegram notification: {e}")
