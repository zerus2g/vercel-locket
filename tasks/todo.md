# Task Tracker

## Active Tasks
_None_

## Completed Tasks
### Sửa lỗi Lưu Trữ nhiều Token trên Vercel
- [x] Cập nhật `redis_store.py`: Thêm `RedisTokenStore`.
- [x] Cập nhật `app.py`: Sửa API Load/Save Token dùng mảng Append array trên Redis.
- [x] Cập nhật `api.py`: Import RedisTokenStore và Random từ đó.
- [x] Cập nhật `admin.html`: Sửa JS Append token thay vì đè & Nút Clear Token.

### Tính năng mới: Upload Ảnh QR Donate
- [x] Sửa `admin.html`: Thay thẻ text input thành thẻ `<input type="file">`
- [x] Sửa `admin.html`: Thêm FileReader Javascript để mã hóa ảnh sang Base64
- [x] Sửa `admin.html`: Thêm preview ảnh mini + Nút Xóa Ảnh
- [x] Fix lỗi Vercel: Dùng chuỗi Base64 thay vì file vật lý để lách hệ thống Serverless của Vercel
- [x] Kiểm tra tương thích `index.html` (Native hỗ trợ hiển thị thẻ img src Base64).

### Đồng bộ múi giờ UTC+7
- [x] Sửa `redis_store.py`: Thay đổi `time.time()` và `datetime.now()` thành múi giờ Việt Nam.
- [x] Sửa `app.py`: Logic admin biểu đồ và số lượt chia thành VN Time để đúng 0:00 là reset.
- [x] Sửa lỗi sai lệch hiển thị 7 tiếng.

### Thêm Persistent Storage (Vercel KV / Redis)
- [x] Viết implementation plan
- [x] Thêm thư viện `redis` vào `requirements.txt`
- [x] Tạo module `redis_store.py` quản lý connection & data models
- [x] Sửa `app.py`: Thay in-memory `SiteSettings` thành data từ Redis
- [x] Sửa `app.py`: Thay in-memory `StatsTracker` thành data từ Redis
- [x] Phân tích và phát hiện lỗi do Vercel reset `.env` khi đổi mật khẩu (Sửa lưu password vào Redis)
- [x] Viết hướng dẫn user cài Redis qua Vercel

### Serialize Requests + Chuyển Link Profile
- [x] Cập nhật `app.py` — thêm threading.Lock + 429 response
- [x] Cập nhật `app.py` — thêm `/api/queue-status` endpoint
- [x] Cập nhật `index.html` — chuyển link profile `ea8f9rwt` → `3pad7k9r`
- [x] Cập nhật `index.html` — auto-retry logic khi nhận 429
- [x] Cập nhật `index.html` — thêm i18n entries cho queue UI (EN + VI)
- [x] Trả về lại 1 con game Backend hoành tráng
