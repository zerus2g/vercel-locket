# Task Tracker

## Active Tasks
_None_

## Completed Tasks

### Thêm Persistent Storage (Vercel KV / Redis)
- [x] Viết implementation plan
- [x] Chờ user approve plan
- [x] Thêm thư viện `redis` vào `requirements.txt`
- [x] Tạo module `redis_store.py` quản lý connection & data models
- [x] Sửa `app.py`: Thay in-memory `SiteSettings` thành data từ Redis
- [x] Sửa `app.py`: Thay in-memory `StatsTracker` thành data từ Redis
- [x] Test kết nối Redis local/mock
- [x] Viết hướng dẫn user lấy biến môi trường `REDIS_URL` bỏ vào Vercel

### Serialize Requests + Chuyển Link Profile
- [x] Cập nhật `app.py` — thêm threading.Lock + 429 response
- [x] Cập nhật `app.py` — thêm `/api/queue-status` endpoint
- [x] Cập nhật `app.py` — fix notification signature mismatch
- [x] Cập nhật `app.py` — fix entitlement key check
- [x] Cập nhật `index.html` — chuyển link profile `ea8f9rwt` → `3pad7k9r`
- [x] Cập nhật `index.html` — auto-retry logic khi nhận 429
- [x] Cập nhật `index.html` — thêm i18n entries cho queue UI (EN + VI)
- [x] Verify code changes
