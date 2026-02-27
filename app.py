from flask import Flask, render_template, request, jsonify, session, redirect
from api import LocketAPI
import config
from config import TOKEN_SETS
from functools import wraps
import dotenv
import os
import time
import json
import threading
from datetime import datetime, timezone, timedelta
from notifications import send_telegram_notification
from redis_store import site_settings, tracker, token_store

app = Flask(__name__)
dotenv.load_dotenv()

# ── Session Config ──
app.secret_key = os.getenv("SECRET_KEY", "locket-gold-default-secret-key-[SECRET_KEY_PLACEHOLDER]")

subscription_ids = [
    "locket_1600_1y",
    "locket_199_1m",
    "locket_199_1m_only",
    "locket_3600_1y",
    "locket_399_1m_only",
]

api = LocketAPI()

# ── Restore Lock (Vercel-compatible serialization) ──
restore_lock = threading.Lock()
restore_busy = False  # Track if currently processing


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
    
    if username == site_settings.admin_username and password == site_settings.admin_password:
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
    return jsonify({"success": True, "settings": site_settings.settings})

@app.route("/api/admin/settings", methods=["POST"])
@admin_required
def update_admin_settings():
    data = request.json
    if not data:
        return jsonify({"success": False, "msg": "No data provided"}), 400
    
    current = site_settings.settings
    current.update(data)
    site_settings.settings = current
    
    return jsonify({"success": True, "msg": "Cài đặt đã được lưu!", "settings": site_settings.settings})


# ── Public Site Settings (read-only, for index.html) ──
@app.route("/api/site-settings", methods=["GET"])
def public_site_settings():
    """Return public-facing site settings (announcement, maintenance, dns)."""
    s = site_settings.settings
    return jsonify({
        "success": True,
        "announcement": s.get("announcement", ""),
        "maintenance_mode": s.get("maintenance_mode", False),
        "dns_hostname": s.get("dns_hostname", ""),
        "qr_donate_url": s.get("qr_donate_url", ""),
        "welcome_popup": s.get("welcome_popup", ""),
    })


# ── Token Management (Protected) ──
@app.route("/api/admin/tokens", methods=["GET"])
@admin_required
def get_tokens():
    """Return current TOKEN_SETS (sanitized for display)."""
    tokens = []
    tokens_list = token_store.get_tokens()
    for t in tokens_list:
        tokens.append({
            "name": t.get("name", "Unnamed"),
            "fetch_token": t.get("fetch_token", "")[:80] + "..." if len(t.get("fetch_token", "")) > 80 else t.get("fetch_token", ""),
            "app_transaction": t.get("app_transaction", "")[:80] + "..." if len(t.get("app_transaction", "")) > 80 else t.get("app_transaction", ""),
            "is_sandbox": t.get("is_sandbox", False),
        })
    return jsonify({"success": True, "tokens": tokens, "count": len(tokens_list)})

@app.route("/api/admin/tokens", methods=["POST"])
@admin_required
def append_tokens():
    """Append new tokens at runtime via Redis."""
    data = request.json
    if not data or "tokens" not in data:
        return jsonify({"success": False, "msg": "No token data provided"}), 400
    
    new_tokens = data["tokens"]
    if not isinstance(new_tokens, list) or len(new_tokens) == 0:
        return jsonify({"success": False, "msg": "tokens must be a non-empty list"}), 400
    
    from config import TOKEN_SETS
    default_app_tx = TOKEN_SETS[0].get("app_transaction") if TOKEN_SETS else ""

    # Validate each token
    for i, tok in enumerate(new_tokens):
        if not tok.get("app_transaction"):
            tok["app_transaction"] = default_app_tx
            
        if not tok.get("fetch_token") or not tok.get("app_transaction"):
            return jsonify({"success": False, "msg": f"Token #{i+1} thiếu fetch_token hoặc app_transaction"}), 400
    
    # Append to Redis
    current_tokens = token_store.append_tokens(new_tokens)
    
    return jsonify({"success": True, "msg": f"Đã thêm {len(new_tokens)} token(s) thành công!", "count": len(current_tokens)})

@app.route("/api/admin/tokens/clear", methods=["DELETE"])
@admin_required
def clear_tokens():
    """Clear all tokens from Redis."""
    token_store.clear_tokens()
    return jsonify({"success": True, "msg": "Đã xóa toàn bộ Token thành công!"})

@app.route("/api/admin/tokens/<token_name>", methods=["DELETE"])
@admin_required
def delete_token(token_name):
    """Delete a specific token by name from Redis."""
    success = token_store.delete_token(token_name)
    if success:
        return jsonify({"success": True, "msg": f"Đã xóa Token '{token_name}' thành công!"})
    else:
        return jsonify({"success": False, "msg": f"Không tìm thấy Token '{token_name}'"}), 404


# ── Change Admin Password (Protected) ──
@app.route("/api/admin/change-password", methods=["POST"])
@admin_required
def change_password():
    data = request.json
    current = data.get("current_password", "")
    new_pw = data.get("new_password", "")
    confirm = data.get("confirm_password", "")
    
    if current != site_settings.admin_password:
        return jsonify({"success": False, "msg": "Mật khẩu hiện tại không đúng!"}), 400
    
    if len(new_pw) < 4:
        return jsonify({"success": False, "msg": "Mật khẩu mới phải có ít nhất 4 ký tự!"}), 400
    
    if new_pw != confirm:
        return jsonify({"success": False, "msg": "Mật khẩu xác nhận không khớp!"}), 400
    
    site_settings.admin_password = new_pw
    return jsonify({"success": True, "msg": "Đổi mật khẩu thành công!"})


# ── Queue Status (For frontend polling) ──
@app.route("/api/queue-status", methods=["GET"])
def queue_status():
    """Return whether the server is currently processing a request."""
    return jsonify({
        "success": True,
        "busy": restore_busy,
        "status": "processing" if restore_busy else "idle"
    })


# ── Restore Purchase (Serialized 1-Click) ──
@app.route("/api/restore", methods=["POST"])
def restore_purchase():
    """Serialized Endpoint for Vercel — only 1 request at a time."""
    global restore_busy

    # Check maintenance mode
    if site_settings.settings.get("maintenance_mode"):
        return jsonify({"success": False, "msg": "Hệ thống đang bảo trì. Vui lòng quay lại sau!"}), 503

    # Check daily limit
    max_daily = site_settings.settings.get("max_daily_unlocks", 0)
    if max_daily > 0:
        today = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
        today_count = tracker.stats.get("daily_unlocks", {}).get(today, 0)
        if today_count >= max_daily:
            return jsonify({"success": False, "msg": f"Đã đạt giới hạn {max_daily} lần mở khóa trong ngày. Vui lòng quay lại ngày mai!"}), 429

    if not api:
        return jsonify({"success": False, "msg": "API not initialized. Check server logs."}), 500

    data = request.json
    username = data.get("username")

    if not username:
        return jsonify({"success": False, "msg": "Username is required"}), 400

    # ── Serialize: Only 1 restore at a time ──
    acquired = restore_lock.acquire(blocking=False)
    if not acquired:
        return jsonify({
            "success": False,
            "busy": True,
            "msg": "Hệ thống đang xử lý yêu cầu khác. Vui lòng đợi..."
        }), 429

    try:
        restore_busy = True

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
            if "Gold" in entitlements:
                product_id = entitlements["Gold"].get("product_identifier", "locket_199_1m")
            elif "gold" in entitlements:
                product_id = entitlements["gold"].get("product_identifier", "locket_199_1m")
        except:
            pass

        msg = f"Purchase {product_id} for {username} successfully!"

        # Update stats
        tracker.add_success(username, product_id)
        
        # Notification (correct 4-param signature)
        try:
            send_telegram_notification(username, uid, product_id, restore_result)
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
            send_telegram_notification(username, "", "error", {"error": str(e)})
        except:
            pass
        return jsonify({"success": False, "msg": f"An error occurred: {str(e)}"}), 500

    finally:
        restore_busy = False
        restore_lock.release()


# ── Activity Feed ──
@app.route("/api/recent-activity", methods=["GET"])
def recent_activity():
    """Return the recent in-memory activity."""
    return jsonify({"success": True, "activity": tracker.get_recent()})

# ── Admin Dashboard Stats (Protected) ──
@app.route("/api/admin/stats", methods=["GET"])
@admin_required
def admin_stats():
    """Return admin stats retrieved from Redis."""
    stats = tracker.stats
    
    # Format daily unlocks for charts
    daily_chart = []
    daily_unlocks = stats.get("daily_unlocks", {})
    for d, c in sorted(daily_unlocks.items()):
        daily_chart.append({"date": d, "count": c})
        
    # Ensure at least today's data for the chart by padding with zero
    vn_tz = timezone(timedelta(hours=7))
    today = datetime.now(vn_tz).strftime("%Y-%m-%d")
    if not daily_chart:
        daily_chart = [{"date": today, "count": 0}]
        
    return jsonify({
        "success": True, 
        "total_unlocks": stats.get("total_unlocks", 0),
        "today_unlocks": daily_unlocks.get(today, 0),
        "total_errors": stats.get("total_errors", 0),
        "avg_processing_time": 0,
        "daily_chart": daily_chart,
        "uptime_seconds": int(tracker.get_uptime())
    })

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
