from flask import Flask, render_template, request, jsonify, Response
from api import LocketAPI
import dotenv
import os
import time
import json

# Import our new modules
from queue_manager import QueueManager
from notifications import send_telegram_notification

app = Flask(__name__)

dotenv.load_dotenv()

# Initialize API and Auth
subscription_ids = [
    "locket_1600_1y",
    "locket_199_1m",
    "locket_199_1m_only",
    "locket_3600_1y",
    "locket_399_1m_only",
]

# Initialize API
api = LocketAPI()
queue_manager = QueueManager(api, subscription_ids, send_telegram_notification, None)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


@app.route("/api/get-user-info", methods=["POST"])
def get_user_info():
    if not api:
        return jsonify(
            {"success": False, "msg": "API not initialized. Check server logs."}
        ), 500

    data = request.json
    username = data.get("username")

    try:
        # User lookup
        print(f"Looking up user: {username}")
        account_info = api.getUserByUsername(username)

        # Check if we got a valid response structure
        if not account_info or "result" not in account_info:
            return jsonify(
                {"success": False, "msg": "User not found or API error"}
            ), 404

        user_data = account_info.get("result", {}).get("data")
        if not user_data:
            return jsonify({"success": False, "msg": "User data not found"}), 404

        # Extract relevant user information
        user_info = {
            "uid": user_data.get("uid"),
            "username": user_data.get("username"),
            "first_name": user_data.get("first_name", ""),
            "last_name": user_data.get("last_name", ""),
            "profile_picture_url": user_data.get("profile_picture_url", ""),
        }

        return jsonify({"success": True, "data": user_info})

    except Exception as e:
        print(f"Error in get user info: {e}")
        return jsonify({"success": False, "msg": f"An error occurred: {str(e)}"}), 500


@app.route("/api/restore", methods=["POST"])
def restore_purchase():
    """Add request to queue and return client_id for tracking"""
    if not api:
        return jsonify(
            {"success": False, "msg": "API not initialized. Check server logs."}
        ), 500

    data = request.json
    username = data.get("username")

    if not username:
        return jsonify({"success": False, "msg": "Username is required"}), 400

    try:
        # Add to queue
        client_id = queue_manager.add_to_queue(username)

        # Get initial status
        status = queue_manager.get_status(client_id)

        return jsonify(
            {
                "success": True,
                "client_id": client_id,
                "position": status["position"],
                "total_queue": status["total_queue"],
                "estimated_time": status["estimated_time"],
            }
        )

    except Exception as e:
        print(f"Error adding to queue: {e}")
        return jsonify({"success": False, "msg": f"An error occurred: {str(e)}"}), 500


@app.route("/api/queue/global-status", methods=["GET"])
def global_queue_status():
    """Get overall queue statistics for all users"""
    status = queue_manager.get_global_status()
    return jsonify({"success": True, **status})


@app.route("/api/queue/status", methods=["POST"])
def queue_status():
    """Get current queue status for a client"""
    data = request.json
    client_id = data.get("client_id")

    if not client_id:
        return jsonify({"success": False, "msg": "client_id is required"}), 400

    status = queue_manager.get_status(client_id)

    # If not found, still return success with a recoverable status to allow client-side retry
    if status.get("status") == "not_found":
        return jsonify({"success": True, **status}), 200

    return jsonify({"success": True, **status})


# ── SSE Endpoints ──────────────────────────────────────────────────────────────

@app.route("/api/queue/stream/<client_id>")
def queue_stream(client_id):
    """Server-Sent Events stream for real-time queue status updates."""
    def generate():
        last_status = None
        while True:
            status = queue_manager.get_status(client_id)
            status_json = json.dumps({"success": True, **status})
            # Only send if status changed to reduce traffic
            if status_json != last_status:
                yield f"data: {status_json}\n\n"
                last_status = status_json
            # Stop streaming if terminal state
            if status.get("status") in ("completed", "error", "not_found"):
                break
            time.sleep(1)
    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.route("/api/queue/global-stream")
def global_queue_stream():
    """SSE stream for global queue statistics."""
    def generate():
        while True:
            status = queue_manager.get_global_status()
            yield f"data: {json.dumps({'success': True, **status})}\n\n"
            time.sleep(3)
    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ── Activity Feed ──────────────────────────────────────────────────────────────

@app.route("/api/recent-activity", methods=["GET"])
def recent_activity():
    """Return the last 10 successful unlocks for the activity feed."""
    activity = queue_manager.get_recent_activity(limit=10)
    return jsonify({"success": True, "activity": activity})


# ── Admin Dashboard ────────────────────────────────────────────────────────────

@app.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    """Return admin dashboard statistics."""
    stats = queue_manager.get_admin_stats()
    return jsonify({"success": True, **stats})


# ── Rate Limit ─────────────────────────────────────────────────────────────────

@app.route("/api/rate-limit", methods=["GET"])
def rate_limit_info():
    """Return current rate limit tracking info."""
    if not api:
        return jsonify({"success": False, "msg": "API not initialized"}), 500
    info = api.get_rate_limit_info()
    return jsonify({"success": True, **info})


if __name__ == "__main__":
    app.run(debug=True, port=5001)

