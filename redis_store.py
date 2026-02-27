import os
import json
import time
import redis
from datetime import datetime, timezone, timedelta
import logging

# Configure logger
logger = logging.getLogger(__name__)

# Initialize Redis client if REDIS_URL is provided, else fallback to None
redis_url = os.environ.get("REDIS_URL")
redis_client = None

if redis_url:
    try:
        redis_client = redis.from_url(redis_url, decode_responses=True)
        # Test connection
        redis_client.ping()
        logger.info("✅ Connected to Redis successfully.")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Redis: {e}")
        redis_client = None
else:
    logger.warning("⚠️ No REDIS_URL provided. Falling back to in-memory storage (Data will be lost on Vercel restart).")


class RedisSiteSettings:
    """
    Manages site settings using Redis. Falls back to in-memory dict if Redis is unavailable.
    """
    REDIS_KEY = "locket_admin:site_settings"
    
    def __init__(self):
        self._memory_fallback = {
            "maintenance_mode": False,
            "announcement": "",
            "dns_hostname": "ff384a.dns.nextdns.io",
            "max_daily_unlocks": 0,
            "qr_donate_url": "https://i.imgur.com/your-qr.png",
            "welcome_popup": "Chào mừng bạn đến với Locket Gold Unlocker! 🎉",
        }

    @property
    def admin_username(self):
        # 1. Check Store first (Redis or Memory Fallback)
        data = self.settings
        if "admin_username" in data:
            return data["admin_username"]
        # 2. Fallback to Env
        return os.environ.get("ADMIN_USERNAME", "admin")

    @admin_username.setter
    def admin_username(self, value):
        s = self.settings
        s["admin_username"] = value
        self.settings = s

    @property
    def admin_password(self):
        # 1. Check Store first (Redis or Memory Fallback)
        data = self.settings
        if "admin_password" in data:
            return data["admin_password"]
        # 2. Fallback to Env
        return os.environ.get("ADMIN_PASSWORD", "123456")

    @admin_password.setter
    def admin_password(self, value):
        s = self.settings
        s["admin_password"] = value
        self.settings = s

    @property
    def settings(self):
        if not redis_client:
            return self._memory_fallback
            
        try:
            data = redis_client.get(self.REDIS_KEY)
            if data:
                return json.loads(data)
            else:
                # Initialize default in Redis
                self.settings = self._memory_fallback
                return self._memory_fallback
        except Exception as e:
            logger.error(f"Redis get site_settings error: {e}")
            return self._memory_fallback

    @settings.setter
    def settings(self, value):
        if not redis_client:
            self._memory_fallback = value
            return
            
        try:
            redis_client.set(self.REDIS_KEY, json.dumps(value))
        except Exception as e:
            logger.error(f"Redis set site_settings error: {e}")
            self._memory_fallback = value


class RedisStatsTracker:
    """
    Tracks statistics and recent activity using Redis lists and hashes.
    Falls back to in-memory if Redis is unavailable.
    """
    PREFIX = "locket_admin"
    STATS_KEY = f"{PREFIX}:stats"
    DAILY_KEY = f"{PREFIX}:daily_stats"
    ACTIVITY_KEY = f"{PREFIX}:recent_activity"
    
    def __init__(self):
        self.start_time = time.time()
        # In-memory fallbacks
        self._mem_stats = {
            "total_unlocks": 0,
            "total_errors": 0,
            "daily_unlocks": {}
        }
        self._mem_activity = []

    def get_uptime(self):
        return time.time() - self.start_time

    @property # Maintain compatibility with app.py access patterns
    def stats(self): 
        if not redis_client:
            return self._mem_stats
            
        try:
            total_unlocks = int(redis_client.hget(self.STATS_KEY, "total_unlocks") or 0)
            total_errors = int(redis_client.hget(self.STATS_KEY, "total_errors") or 0)
            
            # Get all daily stats
            daily_dict = redis_client.hgetall(self.DAILY_KEY)
            # Convert values to int
            daily_dict = {k: int(v) for k, v in daily_dict.items()}
            
            return {
                "total_unlocks": total_unlocks,
                "total_errors": total_errors,
                "daily_unlocks": daily_dict
            }
        except Exception as e:
            logger.error(f"Redis get stats error: {e}")
            return self._mem_stats

    def add_success(self, username, product_id="locket_199_1m", used_token="Unknown"):
        vn_tz = timezone(timedelta(hours=7))
        today = datetime.now(vn_tz).strftime("%Y-%m-%d")
        
        if not redis_client:
            self._mem_stats["total_unlocks"] += 1
            self._mem_stats["daily_unlocks"][today] = self._mem_stats["daily_unlocks"].get(today, 0) + 1
            
            self._mem_activity.insert(0, {
                "username": username,
                "product_id": product_id,
                "used_token": used_token,
                "status": "success",
                "timestamp": datetime.now(vn_tz).isoformat()
            })
            self._mem_activity = self._mem_activity[:20]
            return

        try:
            # 1. Update stats
            redis_client.hincrby(self.STATS_KEY, "total_unlocks", 1)
            redis_client.hincrby(self.DAILY_KEY, today, 1)
            
            # 2. Add to recent activity list
            activity = json.dumps({
                "username": username,
                "product_id": product_id,
                "used_token": used_token,
                "status": "success",
                "timestamp": datetime.now(vn_tz).isoformat()
            })
            redis_client.lpush(self.ACTIVITY_KEY, activity)
            
            # 3. Trim list to keep only latest 20 items
            redis_client.ltrim(self.ACTIVITY_KEY, 0, 19)
            
        except Exception as e:
            logger.error(f"Redis add_success error: {e}")

    def add_error(self, username="Unknown", error_msg="Unknown Error", used_token="Unknown"):
        vn_tz = timezone(timedelta(hours=7))
        if not redis_client:
            self._mem_stats["total_errors"] += 1
            
            self._mem_activity.insert(0, {
                "username": username,
                "product_id": error_msg,
                "used_token": used_token,
                "status": "error",
                "timestamp": datetime.now(vn_tz).isoformat()
            })
            self._mem_activity = self._mem_activity[:20]
            return
            
        try:
            redis_client.hincrby(self.STATS_KEY, "total_errors", 1)
            
            activity = json.dumps({
                "username": username,
                "product_id": error_msg,
                "used_token": used_token,
                "status": "error",
                "timestamp": datetime.now(vn_tz).isoformat()
            })
            redis_client.lpush(self.ACTIVITY_KEY, activity)
            redis_client.ltrim(self.ACTIVITY_KEY, 0, 19)
        except Exception as e:
            logger.error(f"Redis add_error error: {e}")

    def get_recent(self, limit=10):
        if not redis_client:
            return self._mem_activity[:limit]
            
        try:
            items = redis_client.lrange(self.ACTIVITY_KEY, 0, limit - 1)
            return [json.loads(item) for item in items]
        except Exception as e:
            logger.error(f"Redis get_recent error: {e}")
            return self._mem_activity[:limit]

# --- TOKEN STORE ---
class RedisTokenStore:
    """
    Manages fetch tokens using Redis list. Falls back to in-memory list if Redis is unavailable.
    """
    TOKENS_KEY = "locket_admin:fetch_tokens"

    def __init__(self):
        from config import TOKEN_SETS
        self._mem_tokens = list(TOKEN_SETS)

    def get_tokens(self):
        """Get list of token dicts."""
        if not redis_client:
            return self._mem_tokens
            
        try:
            tokens_json = redis_client.get(self.TOKENS_KEY)
            if tokens_json:
                return json.loads(tokens_json)
            else:
                # If missing, populate from config
                from config import TOKEN_SETS
                default_tokens = list(TOKEN_SETS)
                self.save_tokens(default_tokens)
                return default_tokens
        except Exception as e:
            logger.error(f"Redis get_tokens error: {e}")
            return self._mem_tokens

    def save_tokens(self, tokens_list):
        """Save list of token dicts."""
        if not redis_client:
            self._mem_tokens = tokens_list
            return
            
        try:
            redis_client.set(self.TOKENS_KEY, json.dumps(tokens_list))
        except Exception as e:
            logger.error(f"Redis save_tokens error: {e}")

    def append_tokens(self, new_tokens):
        """Append new tokens to list."""
        current_tokens = self.get_tokens()
        current_tokens.extend(new_tokens)
        self.save_tokens(current_tokens)
        return current_tokens

    def delete_token(self, token_name):
        """Delete a token by its name."""
        tokens = self.get_tokens()
        updated_tokens = [t for t in tokens if t.get("name") != token_name]
        if len(tokens) != len(updated_tokens):
            self.save_tokens(updated_tokens)
            return True
        return False

    def clear_tokens(self):
        """Clear all tokens except fallback memory."""
        self._mem_tokens = []
        if redis_client:
            try:
                redis_client.delete(self.TOKENS_KEY)
            except Exception as e:
                logger.error(f"Redis clear_tokens error: {e}")


# Instantiate globals
site_settings = RedisSiteSettings()
tracker = RedisStatsTracker()
token_store = RedisTokenStore()
