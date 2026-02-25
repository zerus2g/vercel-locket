from flask import Flask, render_template, request, jsonify, session, redirect
from api import LocketAPI
import config
from config import TOKEN_SETS
from functools import wraps
import dotenv
import os
import time
import json
from notifications import send_telegram_notification

app = Flask(__name__)
dotenv.load_dotenv()

# ── Session Config ──
app.secret_key = os.getenv("SECRET_KEY", "locket-gold-default-secret-key-change-me")

# ── Admin Credentials from .env ──
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

subscription_ids = [
    "locket_1600_1y",
    "locket_199_1m",
    "locket_199_1m_only",
    "locket_3600_1y",
    "locket_399_1m_only",
]

api = LocketAPI()

# ── In-Memory Stats Tracker (Vercel Serverless Compatible) ──
class StatsTracker:
    def __init__(self):
        self.stats = {
            "total_unlocks": 0,
            "daily_unlocks": {},
            "errors": 0,
            "start_time": time.time()
        }
        self.recent_activity = []
        self.max_activity = 10

    def add_success(self, username, product_id):
        self.stats["total_unlocks"] += 1
        
        today = time.strftime("%Y-%m-%d")
        self.stats["daily_unlocks"][today] = self.stats["daily_unlocks"].get(today, 0) + 1
        
        activity = {
            "username": username,
            "timestamp": int(time.time() * 1000),
            "product_id": product_id,
            "status": "success"
        }
        self.recent_activity.insert(0, activity)
        if len(self.recent_activity) > self.max_activity:
            self.recent_activity.pop()

    def add_error(self):
        self.stats["errors"] += 1

    def get_recent(self):
        return self.recent_activity

    def get_admin_stats(self):
        today = time.strftime("%Y-%m-%d")
        today_unlocks = self.stats["daily_unlocks"].get(today, 0)
        
        daily_chart = []
        for d, count in sorted(self.stats["daily_unlocks"].items())[-7:]:
            daily_chart.append({"date": d, "count": count})
            
        return {
            "total_unlocks": self.stats["total_unlocks"],
            "today_unlocks": today_unlocks,
            "total_errors": self.stats["errors"],
            "queue_size": 0,
            "avg_processing_time": 0,
            "daily_chart": daily_chart,
            "uptime_seconds": int(time.time() - self.stats["start_time"])
        }

tracker = StatsTracker()


# ── In-Memory Site Settings (Admin-editable) ──
class SiteSettings:
    def __init__(self):
        self.settings = {
            "announcement": "",
            "maintenance_mode": False,
            "dns_hostname": "62d63b.dns.nextdns.io",
            "max_daily_unlocks": 0,
            "qr_donate_url": "",            # URL ảnh QR donate
        }

    def get_all(self):
        return self.settings.copy()

    def update(self, new_settings):
        for key in self.settings:
            if key in new_settings:
                self.settings[key] = new_settings[key]

site_settings = SiteSettings()


# ── Auth Decorator ──
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return jsonify({"success": False, "msg": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ── Public Pages ──
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/admin")
def admin_page():
    return render_template("admin.html")


# ── Admin Auth Endpoints ──
@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.json
    username = data.get("username", "")
    password = data.get("password", "")
    
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session["admin_logged_in"] = True
        session["admin_user"] = username
        return jsonify({"success": True, "msg": "Đăng nhập thành công!"})
    else:
        return jsonify({"success": False, "msg": "Sai tên đăng nhập hoặc mật khẩu!"}), 401

@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return jsonify({"success": True, "msg": "Đã đăng xuất!"})

@app.route("/api/admin/check", methods=["GET"])
def admin_check():
    """Check if the current session is authenticated."""
    if session.get("admin_logged_in"):
        return jsonify({"success": True, "logged_in": True, "user": session.get("admin_user")})
    return jsonify({"success": True, "logged_in": False})


# ── Admin Settings Endpoints (Protected) ──
@app.route("/api/admin/settings", methods=["GET"])
@admin_required
def get_admin_settings():
    return jsonify({"success": True, "settings": site_settings.get_all()})

@app.route("/api/admin/settings", methods=["POST"])
@admin_required
def update_admin_settings():
    data = request.json
    if not data:
        return jsonify({"success": False, "msg": "No data provided"}), 400
    site_settings.update(data)
    return jsonify({"success": True, "msg": "Cài đặt đã được lưu!", "settings": site_settings.get_all()})


# ── Public Site Settings (read-only, for index.html) ──
@app.route("/api/site-settings", methods=["GET"])
def public_site_settings():
    """Return public-facing site settings (announcement, maintenance, dns)."""
    s = site_settings.get_all()
    return jsonify({
        "success": True,
        "announcement": s["announcement"],
        "maintenance_mode": s["maintenance_mode"],
        "dns_hostname": s["dns_hostname"],
        "qr_donate_url": s["qr_donate_url"],
    })


# ── Token Management (Protected) ──
@app.route("/api/admin/tokens", methods=["GET"])
@admin_required
def get_tokens():
    """Return current TOKEN_SETS (sanitized for display)."""
    tokens = []
    for t in config.TOKEN_SETS:
        tokens.append({
            "name": t.get("name", "Unnamed"),
            "fetch_token": t.get("fetch_token", "")[:80] + "..." if len(t.get("fetch_token", "")) > 80 else t.get("fetch_token", ""),
            "app_transaction": t.get("app_transaction", "")[:80] + "..." if len(t.get("app_transaction", "")) > 80 else t.get("app_transaction", ""),
            "is_sandbox": t.get("is_sandbox", False),
        })
    return jsonify({"success": True, "tokens": tokens, "count": len(config.TOKEN_SETS)})

@app.route("/api/admin/tokens", methods=["POST"])
@admin_required
def update_tokens():
    """Update TOKEN_SETS at runtime."""
    data = request.json
    if not data or "tokens" not in data:
        return jsonify({"success": False, "msg": "No token data provided"}), 400
    
    new_tokens = data["tokens"]
    if not isinstance(new_tokens, list) or len(new_tokens) == 0:
        return jsonify({"success": False, "msg": "tokens must be a non-empty list"}), 400
    
    # Validate each token
    for i, tok in enumerate(new_tokens):
        if not tok.get("fetch_token") or not tok.get("app_transaction"):
            return jsonify({"success": False, "msg": f"Token #{i+1} thiếu fetch_token hoặc app_transaction"}), 400
    
    # Replace in-memory TOKEN_SETS
    config.TOKEN_SETS.clear()
    config.TOKEN_SETS.extend(new_tokens)
    
    return jsonify({"success": True, "msg": f"Đã cập nhật {len(new_tokens)} token(s) thành công!", "count": len(new_tokens)})


# ── Change Admin Password (Protected) ──
@app.route("/api/admin/change-password", methods=["POST"])
@admin_required
def change_password():
    global ADMIN_PASSWORD
    data = request.json
    current = data.get("current_password", "")
    new_pw = data.get("new_password", "")
    confirm = data.get("confirm_password", "")
    
    if current != ADMIN_PASSWORD:
        return jsonify({"success": False, "msg": "Mật khẩu hiện tại không đúng!"}), 400
    
    if len(new_pw) < 4:
        return jsonify({"success": False, "msg": "Mật khẩu mới phải có ít nhất 4 ký tự!"}), 400
    
    if new_pw != confirm:
        return jsonify({"success": False, "msg": "Mật khẩu xác nhận không khớp!"}), 400
    
    ADMIN_PASSWORD = new_pw
    return jsonify({"success": True, "msg": "Đổi mật khẩu thành công!"})


# ── Restore Purchase (Synchronous 1-Click) ──
@app.route("/api/restore", methods=["POST"])
def restore_purchase():
    """Synchronous Endpoint for Vercel (1-Click)"""
    # Check maintenance mode
    if site_settings.settings.get("maintenance_mode"):
        return jsonify({"success": False, "msg": "Hệ thống đang bảo trì. Vui lòng quay lại sau!"}), 503

    # Check daily limit
    max_daily = site_settings.settings.get("max_daily_unlocks", 0)
    if max_daily > 0:
        today = time.strftime("%Y-%m-%d")
        today_count = tracker.stats["daily_unlocks"].get(today, 0)
        if today_count >= max_daily:
            return jsonify({"success": False, "msg": f"Đã đạt giới hạn {max_daily} lần mở khóa trong ngày. Vui lòng quay lại ngày mai!"}), 429

    if not api:
        return jsonify({"success": False, "msg": "API not initialized. Check server logs."}), 500

    data = request.json
    username = data.get("username")

    if not username:
        return jsonify({"success": False, "msg": "Username is required"}), 400

    try:
        # 1. Scrape the UID from locket.cam silently
        print(f"Scraping UID for: {username}")
        account_info = api.getUserByUsername(username)
        
        if not account_info or "result" not in account_info:
            return jsonify({"success": False, "msg": "User not found or API error"}), 404
            
        user_data = account_info.get("result", {}).get("data")
        if not user_data:
            return jsonify({"success": False, "msg": "User data not found"}), 404
            
        uid = user_data.get("uid")
        
        # 2. Proceed with restore directly
        print(f"Restoring purchase for UID: {uid}")
        restore_result = api.restorePurchase(uid)
        
        # Extract product_id from the restore result
        product_id = "locket_199_1m"
        try:
            entitlements = restore_result.get("subscriber", {}).get("entitlements", {})
            if "gold" in entitlements:
                product_id = entitlements["gold"].get("product_identifier", "locket_199_1m")
        except:
            pass

        msg = f"Purchase {product_id} for {username} successfully!"

        # Update stats
        tracker.add_success(username, product_id)
        
        # Notification
        try:
            send_telegram_notification(f"✅ *Gold Unlocked!*\nUser: `{username}`\nProduct: `{product_id}`")
        except:
            pass
            
        return jsonify({
            "success": True, 
            "result": restore_result,
            "msg": msg
        })

    except Exception as e:
        print(f"Error processing restore: {e}")
        tracker.add_error()
        try:
            send_telegram_notification(f"❌ *Fail!*\nUser: `{username}`\nError: `{str(e)}`")
        except:
            pass
        return jsonify({"success": False, "msg": f"An error occurred: {str(e)}"}), 500


# ── Activity Feed ──
@app.route("/api/recent-activity", methods=["GET"])
def recent_activity():
    """Return the recent in-memory activity."""
    return jsonify({"success": True, "activity": tracker.get_recent()})

# ── Admin Dashboard Stats (Protected) ──
@app.route("/api/admin/stats", methods=["GET"])
@admin_required
def admin_stats():
    """Return in-memory admin stats."""
    return jsonify({"success": True, **tracker.get_admin_stats()})

# ── Rate Limit ──
@app.route("/api/rate-limit", methods=["GET"])
def rate_limit_info():
    """Return current rate limit tracking info."""
    if not api:
        return jsonify({"success": False, "msg": "API not initialized"}), 500
    info = api.get_rate_limit_info()
    return jsonify({"success": True, **info})

if __name__ == "__main__":
    app.run(debug=True, port=5001)
