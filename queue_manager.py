import json
import time
import queue
import threading
import uuid
from datetime import datetime
import os
import tempfile
from filelock import FileLock, Timeout

QUEUE_STATE_FILE = "queue_state.json"
QUEUE_LOCK_FILE = "queue_state.json.lock"

class QueueManager:
    def __init__(self, api_instance, subscription_ids, send_notification_func, refresh_token_func):
        self.queue = queue.Queue()
        self.lock = threading.Lock()
        self.client_requests = {}  # client_id -> request data
        self.processing_times = []  # Track processing times for estimates
        self.current_processing = None
        
        # Activity feed and admin stats
        self.recent_activity = []  # Last 20 successful unlocks
        self.stats = {
            "total_unlocks": 0,
            "total_errors": 0,
            "daily_unlocks": {},  # date_str -> count
            "start_time": datetime.now().isoformat(),
        }
        
        # Dependencies from main app
        self.api = api_instance
        self.subscription_ids = subscription_ids
        self.send_telegram_notification = send_notification_func
        self.refresh_api_token = refresh_token_func

        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

        # Load state from file
        self._load_state()
        print("Queue manager initialized and worker thread started")

    def set_api(self, new_api_instance):
        """Update the API instance after a token refresh"""
        self.api = new_api_instance

    def _save_state(self):
        """Save current queue state to file with atomic write and cross-platform locking"""
        try:
            state = {
                "client_requests": {},
                "processing_times": self.processing_times,
                "recent_activity": self.recent_activity,
                "stats": self.stats,
            }

            with self.lock:
                for client_id, data in self.client_requests.items():
                    req_data = data.copy()
                    if req_data.get("added_at"):
                        req_data["added_at"] = req_data["added_at"].isoformat()
                    if req_data.get("started_at"):
                        req_data["started_at"] = req_data["started_at"].isoformat()
                    if req_data.get("completed_at"):
                        req_data["completed_at"] = req_data["completed_at"].isoformat()
                    state["client_requests"][client_id] = req_data

            file_lock = FileLock(QUEUE_LOCK_FILE, timeout=5)
            try:
                with file_lock:
                    temp_fd, temp_path = tempfile.mkstemp(
                        dir=os.path.dirname(QUEUE_STATE_FILE) or ".", suffix=".tmp"
                    )
                    try:
                        with os.fdopen(temp_fd, "w") as f:
                            json.dump(state, f, indent=2)
                            f.flush()
                            os.fsync(f.fileno())

                        os.replace(temp_path, QUEUE_STATE_FILE)
                        print(f"Queue state saved: {len(state['client_requests'])} requests")
                    except Exception as e:
                        try:
                            os.unlink(temp_path)
                        except OSError:
                            pass
                        raise e
            except Timeout:
                print("Could not acquire lock to save queue state.")

        except Exception as e:
            print(f"Error saving queue state: {e}")

    def _load_state(self):
        """Load queue state from file using cross-platform locking"""
        if not os.path.exists(QUEUE_STATE_FILE):
            return

        file_lock = FileLock(QUEUE_LOCK_FILE, timeout=5)
        try:
            with file_lock:
                try:
                    with open(QUEUE_STATE_FILE, "r") as f:
                        state = json.load(f)

                    if "processing_times" in state:
                        self.processing_times = state["processing_times"]
                    if "recent_activity" in state:
                        self.recent_activity = state["recent_activity"]
                    if "stats" in state:
                        self.stats.update(state["stats"])

                    if "client_requests" in state:
                        with self.lock:
                            loaded_requests = []
                            for client_id, data in state["client_requests"].items():
                                if data.get("added_at"):
                                    data["added_at"] = datetime.fromisoformat(data["added_at"])
                                if data.get("started_at"):
                                    data["started_at"] = datetime.fromisoformat(data["started_at"])
                                if data.get("completed_at"):
                                    data["completed_at"] = datetime.fromisoformat(data["completed_at"])

                                self.client_requests[client_id] = data
                                loaded_requests.append((client_id, data))

                            loaded_requests.sort(key=lambda x: x[1]["added_at"])

                            for client_id, data in loaded_requests:
                                if data["status"] == "waiting":
                                    self.queue.put(client_id)
                                    print(f"Re-queued waiting request: {client_id}")
                                elif data["status"] == "processing":
                                    data["status"] = "waiting"
                                    data["started_at"] = None
                                    self.client_requests[client_id] = data
                                    self.queue.put(client_id)
                                    print(f"Re-queued interrupted request: {client_id}")

                    print(f"Loaded {len(self.client_requests)} requests from state file")
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON state: {e}")
                except Exception as e:
                    print(f"Error loading queue state: {e}")
        except Timeout:
            print("Could not acquire lock to load queue state.")

    def add_to_queue(self, username):
        """Add a request to the queue and return client_id"""
        client_id = str(uuid.uuid4())
        request_data = {
            "username": username,
            "status": "waiting",
            "result": None,
            "error": None,
            "added_at": datetime.now(),
            "started_at": None,
            "completed_at": None,
        }

        with self.lock:
            self.client_requests[client_id] = request_data
            self.queue.put(client_id)

        print(f"Added {username} to queue with client_id: {client_id}")
        self._save_state()
        return client_id

    def get_global_status(self):
        """Get global queue status (not tied to any client)"""
        with self.lock:
            total_waiting = self.queue.qsize()
            if self.current_processing:
                total_waiting += 1

            avg_time = 5
            if self.processing_times:
                avg_time = sum(self.processing_times[-10:]) / len(self.processing_times[-10:])

            estimated_time = int(total_waiting * avg_time)

            return {
                "status": "idle" if total_waiting == 0 else "active",
                "total_queue": total_waiting,
                "estimated_time": estimated_time,
                "avg_processing_time": avg_time,
            }

    def get_recent_activity(self, limit=10):
        """Return recent successful unlocks for the activity feed."""
        with self.lock:
            return self.recent_activity[-limit:][::-1]  # newest first

    def get_admin_stats(self):
        """Return admin dashboard statistics."""
        with self.lock:
            today_str = datetime.now().strftime("%Y-%m-%d")
            today_unlocks = self.stats["daily_unlocks"].get(today_str, 0)
            
            # Last 7 days chart data
            daily_data = []
            for i in range(6, -1, -1):
                from datetime import timedelta
                d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                daily_data.append({
                    "date": d,
                    "count": self.stats["daily_unlocks"].get(d, 0),
                })
            
            return {
                "total_unlocks": self.stats["total_unlocks"],
                "total_errors": self.stats["total_errors"],
                "today_unlocks": today_unlocks,
                "uptime_since": self.stats["start_time"],
                "queue_size": self.queue.qsize(),
                "avg_processing_time": round(sum(self.processing_times[-10:]) / len(self.processing_times[-10:]), 1) if self.processing_times else 5,
                "daily_chart": daily_data,
            }

    def get_status(self, client_id):
        """Get current status of a request"""
        if client_id not in self.client_requests:
            print(f"Client ID {client_id} not in memory, reloading state...")
            self._load_state()

        with self.lock:
            if client_id not in self.client_requests:
                return {
                    "client_id": client_id,
                    "status": "not_found",
                    "position": 0,
                    "total_queue": self.queue.qsize(),
                    "estimated_time": 0,
                    "result": None,
                    "error": "Request not found. It may have been completed or expired.",
                }

            request_data = self.client_requests[client_id].copy()

            position = self._get_position(client_id)
            total_queue = self.queue.qsize()
            if self.current_processing and self.current_processing != client_id:
                total_queue += 1

            estimated_time = self._estimate_wait_time(position)

            return {
                "client_id": client_id,
                "status": request_data["status"],
                "position": position,
                "total_queue": total_queue,
                "estimated_time": estimated_time,
                "result": request_data["result"],
                "error": request_data["error"],
            }

    def _get_position(self, client_id):
        if self.current_processing == client_id:
            return 0

        queue_list = list(self.queue.queue)
        if client_id in queue_list:
            return queue_list.index(client_id) + 1

        if client_id in self.client_requests:
            status = self.client_requests[client_id]["status"]
            if status in ["completed", "error"]:
                return 0

        return 0

    def _estimate_wait_time(self, position):
        if position == 0:
            return 0

        avg_time = 5
        if self.processing_times:
            avg_time = sum(self.processing_times[-10:]) / len(self.processing_times[-10:])

        return int(position * avg_time)

    def _process_queue(self):
        print("Queue worker thread started")
        while True:
            try:
                client_id = self.queue.get(timeout=1)

                with self.lock:
                    if client_id not in self.client_requests:
                        continue

                    self.current_processing = client_id
                    self.client_requests[client_id]["status"] = "processing"
                    self.client_requests[client_id]["started_at"] = datetime.now()

                self._save_state()

                print(f"Processing request for client_id: {client_id}")

                self._process_request(client_id)

                with self.lock:
                    self.current_processing = None
                    if client_id in self.client_requests:
                        self.client_requests[client_id]["completed_at"] = datetime.now()

                        started = self.client_requests[client_id]["started_at"]
                        completed = self.client_requests[client_id]["completed_at"]
                        duration = (completed - started).total_seconds()
                        self.processing_times.append(duration)

                        if len(self.processing_times) > 20:
                            self.processing_times.pop(0)

                self._save_state()
                self._cleanup_old_requests()

                self.queue.task_done()
                print("Waiting 5 seconds before next request to ensure stability...")
                time.sleep(5)

            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error in queue processing: {e}")
                with self.lock:
                    self.current_processing = None

    def _cleanup_old_requests(self):
        try:
            with self.lock:
                current_time = datetime.now()
                to_remove = []

                for client_id, data in self.client_requests.items():
                    if data["status"] in ["completed", "error"]:
                        completed_at = data.get("completed_at")
                        if completed_at:
                            age = (current_time - completed_at).total_seconds()
                            if age > 600:
                                to_remove.append(client_id)

                for client_id in to_remove:
                    del self.client_requests[client_id]
                    print(f"Cleaned up old request: {client_id}")

                if to_remove:
                    self._save_state()
        except Exception as e:
            print(f"Error cleaning up old requests: {e}")

    def _process_request(self, client_id):
        try:
            with self.lock:
                if client_id not in self.client_requests:
                    print(f"Client ID {client_id} disappeared during processing")
                    return
                username = self.client_requests[client_id]["username"]

            print(f"Processing restore for: {username}")

            try:
                account_info = self.api.getUserByUsername(username)
            except Exception as e:
                if "401" in str(e) or "Unauthenticated" in str(e):
                    print(f"Creating new token because of {e}")
                    if self.refresh_api_token():
                        account_info = self.api.getUserByUsername(username)
                    else:
                        raise e
                else:
                    raise e

            if not account_info or "result" not in account_info:
                raise Exception("User not found or API error")

            user_data = account_info.get("result", {}).get("data")
            if not user_data:
                raise Exception("User data not found")

            uid_target = user_data.get("uid")
            if not uid_target:
                raise Exception("UID not found for user")

            try:
                restore_result = self.api.restorePurchase(uid_target)
            except Exception as e:
                if "401" in str(e) or "Unauthenticated" in str(e):
                    print(f"Creating new token because of {e}")
                    if self.refresh_api_token():
                        restore_result = self.api.restorePurchase(uid_target)
                    else:
                        raise e
                else:
                    raise e

            entitlements = restore_result.get("subscriber", {}).get("entitlements", {})
            gold_entitlement = entitlements.get("Gold", {})

            if gold_entitlement.get("product_identifier") in self.subscription_ids:
                self.send_telegram_notification(
                    username,
                    uid_target,
                    gold_entitlement.get("product_identifier"),
                    restore_result,
                )

                with self.lock:
                    if client_id in self.client_requests:
                        self.client_requests[client_id]["status"] = "completed"
                        self.client_requests[client_id]["result"] = {
                            "success": True,
                            "msg": f"Purchase {gold_entitlement.get('product_identifier')} for {username} successfully!",
                        }
                        # Record activity for the feed
                        self.recent_activity.append({
                            "username": username,
                            "product_id": gold_entitlement.get('product_identifier'),
                            "timestamp": datetime.now().isoformat(),
                        })
                        if len(self.recent_activity) > 20:
                            self.recent_activity = self.recent_activity[-20:]
                        # Update admin stats
                        self.stats["total_unlocks"] += 1
                        today_str = datetime.now().strftime("%Y-%m-%d")
                        self.stats["daily_unlocks"][today_str] = self.stats["daily_unlocks"].get(today_str, 0) + 1
            else:
                raise Exception(f"Restore purchase failed. Gold entitlement not found for {username}.")

        except Exception as e:
            print(f"Error processing request for {client_id}: {e}")
            with self.lock:
                if client_id in self.client_requests:
                    self.client_requests[client_id]["status"] = "error"
                    self.client_requests[client_id]["error"] = str(e)
                self.stats["total_errors"] += 1
