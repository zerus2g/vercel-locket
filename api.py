import json
import requests
import time
import os
import random
import re
from redis_store import token_store

class LocketAPI:
    def __init__(self):
        # Tracking rate limits for RevenueCat API
        self.rate_limit_info = {
            "remaining": None,
            "limit": None,
            "reset": None,
            "last_updated": None,
        }

    def getUserByUsername(self, username):
        """
        Scrapes locket.cam to find the user's UID, name, and profile picture
        without needing a Locket account/Firebase token.
        """
        if not username:
            raise ValueError("Username is required")

        url = f"https://locket.cam/{username}"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        response = requests.get(url, headers=headers, timeout=10)
        html = response.text
        
        # 1. Extract UID
        uid_match = re.search(r'/invites/([A-Za-z0-9]{28})', html)
        if not uid_match:
            # Try alternate fallback method
            lp = re.search(r'link=([^\s"\'>]+)', html)
            if lp:
                try:
                    d = lp.group(1).replace('%3A', ':').replace('%2F', '/')
                    dm = re.search(r'/invites/([A-Za-z0-9]{28})', d)
                    if dm:
                        uid_match = dm
                except:
                    pass
                    
        if not uid_match:
            raise Exception("User not found or UID extraction failed. Ensure the username is correct.")
            
        uid = uid_match.group(1)
        
        # 2. Extract Name
        # Looking for <meta property="og:title" content="Name on Locket">
        name_match = re.search(r'og:title"\s+content="([^"]+) on Locket|content="([^"]+) on Locket"\s+property="og:title', html)
        first_name = username
        last_name = ""
        if name_match:
            full_name = (name_match.group(1) or name_match.group(2) or username).split(" \u2022")[0].strip()
            parts = full_name.split(" ", 1)
            first_name = parts[0]
            if len(parts) > 1:
                last_name = parts[1]
                
        # 3. Extract Avatar
        # Looking for <meta property="og:image" content="...">
        avatar_match = re.search(r'og:image"\s+content="([^"]+)"|content="([^"]+)"\s+property="og:image', html)
        avatar_url = ""
        if avatar_match:
            avatar_url = avatar_match.group(1) or avatar_match.group(2)
            
        # Format the response exactly like the original API to easily drop-in replace
        return {
            "result": {
                "data": {
                    "uid": uid,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "profile_picture_url": avatar_url
                }
            }
        }

    def restorePurchase(self, uid):
        """
        Restores the purchase using a token set from Redis.
        """
        url = "https://api.revenuecat.com/v1/receipts"

        # Select payload config via Round-Robin, ignoring dead tokens
        token_config = token_store.get_next_token()
        if not token_config:
            raise Exception("Tất cả Token hiện tại đều đã Die hoặc Hết dung lượng khởi chạy. Xin báo Admin nạp thêm!")

        token_name = token_config.get('name', 'Unknown')
        
        fetch_token = token_config.get('fetch_token')
        app_transaction = token_config.get('app_transaction')
        is_sandbox = token_config.get('is_sandbox', False)

        if not fetch_token or not app_transaction:
            raise Exception("Invalid TOKEN_SET config: missing fetch_token or app_transaction")

        payload_data = {
            "product_id": "locket_199_1m", 
            "fetch_token": fetch_token, 
            "app_transaction": app_transaction,
            "app_user_id": uid, 
            "is_restore": True, 
            "store_country": "VNM", 
            "currency": "VND",
            "price": "49000", 
            "normal_duration": "P1M", 
            "subscription_group_id": "21419447",
            "observer_mode": False, 
            "initiation_source": "restore", 
            "offers": [],
            "attributes": { 
                "$attConsentStatus": { "updated_at_ms": int(time.time() * 1000), "value": "notDetermined" } 
            }
        }

        payload = json.dumps(payload_data)

        headers = {
            'Host': 'api.revenuecat.com',
            'Authorization': 'Bearer appl_JngFETzdodyLmCREOlwTUtXdQik',
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'X-Platform': 'iOS',
            'X-Platform-Version': 'Version 16.7.5 (Build 20H307)',
            'X-Platform-Device': 'iPhone10,5',
            'X-Platform-Flavor': 'native',
            'X-Version': '5.41.0',
            'X-Client-Version': '2.32.2',
            'X-Client-Bundle-ID': 'com.locket.Locket',
            'X-Client-Build-Version': '3',
            'X-StoreKit2-Enabled': 'true',
            'X-StoreKit-Version': '2',
            'X-Observer-Mode-Enabled': 'false',
            'X-Is-Sandbox': str(is_sandbox).lower(),
            'X-Storefront': 'VNM',
            'X-Apple-Device-Identifier': '2518071A-4AC9-44BE-B44C-A7056AD9BBFD',
            'X-Preferred-Locales': 'vi_VN',
        }
        
        if token_config.get('hash_params'):
            headers['X-Post-Params-Hash'] = token_config['hash_params']
        if token_config.get('hash_headers'):
            headers['X-Headers-Hash'] = token_config['hash_headers']

        response = requests.post(url, headers=headers, data=payload)
        self._update_rate_limit(response)
        
        if response.ok:
            result = response.json()
            result["__used_token_name"] = token_name
            return result
        else:
            err_text = response.text
            # Identify dead token responses
            if response.status_code in [401, 403] or "Invalid token" in err_text or "not authorized" in err_text.lower() or "Invalid API Key" in err_text:
                token_store.ban_token(token_name)
                raise Exception(f"Token Bị Tử Hình [{token_name}]: {err_text}")
            raise Exception(f"API request failed with status code {response.status_code}: {err_text}")

    def _update_rate_limit(self, response):
        """Extract rate limit info from response headers."""
        import time as _time
        self.rate_limit_info["remaining"] = response.headers.get("X-RateLimit-Remaining", response.headers.get("x-ratelimit-remaining"))
        self.rate_limit_info["limit"] = response.headers.get("X-RateLimit-Limit", response.headers.get("x-ratelimit-limit"))
        self.rate_limit_info["reset"] = response.headers.get("X-RateLimit-Reset", response.headers.get("x-ratelimit-reset"))
        self.rate_limit_info["last_updated"] = _time.time()
        # Convert to int if present
        for key in ["remaining", "limit"]:
            if self.rate_limit_info[key] is not None:
                try:
                    self.rate_limit_info[key] = int(self.rate_limit_info[key])
                except (ValueError, TypeError):
                    pass

    def get_rate_limit_info(self):
        """Return current rate limit tracking info."""
        return self.rate_limit_info.copy()

