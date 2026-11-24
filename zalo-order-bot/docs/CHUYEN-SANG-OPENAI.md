# Prompt: chuyển phần AI của bot từ Claude (Anthropic) sang OpenAI

> Dán toàn bộ phần dưới đây cho ChatGPT, hoặc cho Codex nếu nó mở được thư mục code.
> Không dán API key vào khung chat. Key chỉ nhập vào Terminal khi script cài đặt hỏi.

---

## Bối cảnh

Repo GitHub `hoangantuan7-crypto/hoangbui`, nhánh chính `delivery/completed-assets`. Dự án nằm trong thư mục
`zalo-order-bot/`. Đây là bot Python 3.13, viết thuần thư viện chuẩn: urllib, sqlite3, threading.

Bot chạy trong Docker, cạnh ZaloCRM tự host trên máy Mac của chủ shop (`http://localhost:3080`). Nó làm 3 việc:
- Đọc tin Zalo qua API của ZaloCRM. Chỉ đọc, không bao giờ gửi tin Zalo.
- Báo việc qua 5 bot Telegram: Điều phối, Sale, Kế toán, Kho, Kỹ thuật.
- Ghi Google Sheet qua Apps Script.

Hiện bot dùng **Claude (Anthropic)** cho 6 việc AI. Mình muốn chuyển sang **OpenAI**.

Đọc trước:
- `CLAUDE.md` ở gốc repo: kiến trúc và quy tắc.
- `zalo-order-bot/README.md`.

Chạy test (bắt buộc pass trước và sau khi sửa):

```sh
cd zalo-order-bot
python3 -m unittest discover -s tests
```

Không chạy được kiểu `python -m unittest tests.test_x`, vì các file test import lẫn nhau. Muốn chạy 1 file thì dùng
`discover -s tests -p test_x.py`.

## Mục tiêu

1. Tạo **một lớp AI dùng chung** `bot/llm.py`, chọn nhà cung cấp bằng biến môi trường
   `AI_PROVIDER=openai|anthropic`. Mặc định là `openai` nếu có `OPENAI_API_KEY`, không thì `anthropic`.
   Giữ Claude làm đường lui.
2. Đổi cả 6 chỗ gọi AI dưới đây sang lớp chung đó. **Giữ nguyên** tên hàm, tham số và kiểu trả về, vì test và
   `crm_main.py` đang dùng đúng các tên này.
3. AI vẫn là **tùy chọn**: không có key hoặc chưa cài gói `openai` thì bot vẫn chạy đầy đủ phần không cần AI. Không
   được crash.

## 6 chỗ đang gọi Claude

| # | File · hàm | Việc làm | Đầu vào | Đầu ra | Model hiện tại |
|---|---|---|---|---|---|
| 1 | `bot/ai_parser.py` · `ai_parse_order(message, sender)` | Đọc tin khách viết tự do → đơn hàng | chữ + system prompt `SYSTEM` | JSON theo `SCHEMA` → `ParsedOrder` hoặc `None` | `CLAUDE_MODEL` (mặc định claude-opus-5-5) |
| 2 | `bot/ai_assistant.py` · `ask_bot(bot, question, store)` | Hỏi đáp từng bộ phận ("Kho ơi…") dựa trên số liệu thật | chữ + `system_prompt(bot)` | chữ, có tiền tố biểu tượng bot | `CLAUDE_MODEL` |
| 3 | `bot/customer_info.py` · `ai_read(image, media_type, caption)` | Đọc ảnh thông tin khách (nhiều khách / ảnh) | 1 ảnh + `PROMPT` | JSON theo `SCHEMA` (`customers[]`) → `list[dict]` hoặc `None` | `CLAUDE_VISION_MODEL` (claude-haiku-5-5) |
| 4 | `bot/orders.py` · `ai_read_order(image, media_type, text, codes)` | Đọc phiếu đơn / phiếu giao hàng / giấy ghi tay → đơn có giá từng món, cọc | 1 ảnh (hoặc chỉ chữ) + `PROMPT` + danh sách mã kho | JSON theo `SCHEMA` (đơn) → `dict` hoặc `None` | `CLAUDE_VISION_MODEL` |
| 5 | `bot/summary.py` · `describe_image(image, media, caption)` | Tóm tắt 1 ảnh trong nhóm Kho / Kế toán (≤ 4 dòng) | 1 ảnh + `DESCRIBE` | chữ hoặc `None` | `CLAUDE_VISION_MODEL` |
| 6 | `bot/summary.py` · `summarize(group, entries, start, end, fetch)` + `_call(content)` | `/tonghop`: tóm tắt tin nhóm, **xen kẽ tối đa 15 ảnh** ngay sau dòng `[ảnh]` tương ứng | nhiều khối chữ + ảnh | chữ hoặc `None` | `CLAUDE_VISION_MODEL` |

Ngoài ra:
- `ai_available()` trong `bot/ai_parser.py` hiện kiểm tra `ANTHROPIC_API_KEY` và import `anthropic`. Hàm này
  được import ở `crm_main.py`, `handlers.py`, `customer_info.py`, `summary.py`, `ai_assistant.py`. Sửa để trả `True`
  khi nhà cung cấp đang chọn có key và có gói Python tương ứng. **Giữ nguyên tên hàm và chỗ import.**
- Test đang mock các tên sau, không đổi tên chúng:
  - `bot.ai_parser.ai_available`, `bot.crm_main.ai_available`
  - `bot.crm_main.ai_read_order`, `bot.crm_main.describe_image`, `bot.crm_main.summarize`
  - `bot.customer_info.ai_read`, `bot.summary._call`
- Mọi chỗ gọi đang bắt lỗi kết nối / lỗi API → ghi `log.warning` tiếng Việt → trả `None`. Trường hợp từ chối trả
  lời hoặc bị cắt vì hết token cũng trả `None`. **Giữ nguyên hành vi này** với OpenAI.

## Gợi ý cách viết `bot/llm.py`

- Hàm chung, ví dụ:
  `complete(parts, system=None, schema=None, max_tokens=3000, vision=False) -> str | None`.
  - `parts` là danh sách trung lập: `{"text": "..."}` hoặc `{"image": bytes, "media_type": "image/jpeg"}`.
  - `vision=True` thì dùng model đọc ảnh.
- Với OpenAI, dùng SDK Python chính thức `openai`:
  - Ảnh gửi dạng base64 data URL: `data:<media_type>;base64,<...>`.
  - JSON dùng structured outputs với `json_schema` (`strict: true`). Các `SCHEMA` hiện có đã đặt
    `additionalProperties: false` và liệt kê đủ `required`, kiểm tra lại cho hợp chế độ strict.
  - Bắt các lớp lỗi kết nối và lỗi trạng thái của SDK, rồi trả `None`.
  - Kiểm tra tên lớp lỗi, tên tham số và tên model theo **tài liệu OpenAI hiện tại**, không viết theo trí nhớ.
- Model đặt bằng biến môi trường, **không cố định trong code**:
  - `OPENAI_MODEL`: cho mục 1, 2.
  - `OPENAI_VISION_MODEL`: cho mục 3–6. Phải là model **đọc được ảnh**, đọc tốt chữ viết tay tiếng Việt, giá rẻ.
  - Chọn model mới nhất phù hợp trên platform.openai.com.
- Ảnh định dạng lạ đã được đổi sang JPEG ở `customer_info.to_supported_image`. Kiểm tra lại danh sách định dạng ảnh
  OpenAI nhận.

## Cấu hình phải sửa (quy tắc của repo: thêm biến cấu hình là sửa 3 chỗ)

1. `bot/crm_main.py` · `main()` và docstring đầu file: thêm `AI_PROVIDER`, `OPENAI_API_KEY`, `OPENAI_MODEL`,
   `OPENAI_VISION_MODEL`.
2. `docker-compose.zalocrm.yml`, khối `environment` của service `order-bot`: thêm
   `OPENAI_API_KEY: ${OPENAI_API_KEY:-}`, `AI_PROVIDER: ${ORDER_BOT_AI_PROVIDER:-}`, `OPENAI_MODEL` và
   `OPENAI_VISION_MODEL` theo cùng kiểu `${ORDER_BOT_…:-}`.
3. `install-zalocrm.sh`, mục "AI đọc ảnh…" (khoảng dòng 215–235):
   - Hỏi thêm OpenAI API key bằng **`ask_secret`** (ẩn chữ khi dán). Enter để giữ key cũ, Enter để bỏ qua.
   - Kiểm tra key bắt đầu bằng `sk-`. Thử `curl -fsS --max-time 20 https://api.openai.com/v1/models -H "Authorization: Bearer $KEY"`.
     Đúng thì in "OK – khóa OpenAI dùng được", sai thì cảnh báo nhưng vẫn cài tiếp.
   - Ghi vào `.env` bằng `env_set OPENAI_API_KEY ...`. Có key OpenAI thì đặt `ORDER_BOT_AI_PROVIDER=openai`.
   - Script phải **chạy được trên bash 3.2 của macOS**: không `mapfile`, không `${x,,}`, không mảng kết hợp.
     **Không bao giờ in key ra màn hình.**
4. `Dockerfile`: thêm `RUN pip install --no-cache-dir openai || echo "..."` (cài không được thì bot vẫn chạy). Giữ
   dòng `anthropic` để còn đường lui.

## Quy tắc bắt buộc giữ

- Mọi chữ bot gửi người dùng, comment và README viết **tiếng Việt**, cùng giọng hiện tại: bot xưng "em", gọi "anh".
- Giữ nguyên các prompt tiếng Việt (`SYSTEM`, `PROMPT`, `DESCRIBE`, prompt tổng hợp) và `SCHEMA`. Chỉ đổi cách gửi.
- Không đổi luồng xử lý, màu thông báo (🔴🟡🟢 ở `bot/telegram.py`), Google Sheet, Telegram hay ZaloCRM.
- Mọi truy cập SQLite đi qua `Store` (`_LockedConnection`), vì có nhiều luồng chạy cùng lúc.
- Không đưa key, token, mã ghép nối Telegram, link Apps Script hay mã bí mật Sheet vào code, commit hoặc log.
- Dữ liệu khách (tên, SĐT, ảnh phiếu) sẽ gửi sang OpenAI. Ghi rõ điều này trong README như đang ghi cho Claude.

## Test cần thêm

- `tests/test_llm.py`: giả lập client OpenAI (mock), kiểm tra:
  - JSON hợp lệ thì trả đúng `dict` / `list`.
  - Lỗi kết nối, lỗi API, từ chối, hết token thì trả `None`.
  - Ảnh được chuyển thành data URL.
  - `ai_available()` đúng theo `AI_PROVIDER` và key.
  - `summarize` xen kẽ đúng thứ tự chữ / ảnh.
- Toàn bộ test cũ vẫn pass.

## Bàn giao

1. Danh sách file đã sửa, chạy `python3 -m unittest discover -s tests` báo OK.
2. Cập nhật `zalo-order-bot/README.md`: mục AI dùng OpenAI, cách lấy key, cách đặt giới hạn chi tiêu hằng tháng.
3. Chủ shop cập nhật bot bằng đúng lệnh này (không đổi lệnh):
   ```sh
   cd ~/zcrm && git -C ~/hoangbui pull -q && cp -r ~/hoangbui/zalo-order-bot . && bash zalo-order-bot/install-zalocrm.sh
   ```
4. Thử thật sau khi cập nhật:
   - Gửi 1 ảnh phiếu xuất kho vào nhóm Zalo "PHÍ GIAO NHẬN…": Bot Kho nhận "📷 ảnh – em đọc được: …".
   - Gửi 1 ảnh giấy viết tay vào nhóm "THÔNG TIN KHÁCH HÀNG": Bot Sale báo khách hoặc đơn đang quan tâm.
   - Gõ `/tonghop <số nhóm> 1` để xem tổng hợp có đọc ảnh.
