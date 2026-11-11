# 🤖 Bot Zalo tổng hợp đơn hàng

Bot chat trên Zalo giúp **không trượt đơn**: quét tin nhắn của khách, thấy khách đặt hàng, hỏi hàng hoặc báo chuyển khoản
là **báo ngay** vào nhóm Zalo của anh. Tin nào quá 30 phút chưa xử lý thì bot nhắc lại. Bot cũng **tự đẩy báo cáo** mỗi ngày:

- 🛁 **Cần lên đơn tủ lavabo cho ai**: đơn có tủ lavabo nhưng chưa đặt xưởng, và tủ đã đặt nhưng chờ xưởng quá 10 ngày.
- ⚠️ **Khách nào đang thiếu hàng**: lấy tồn kho chia cho đơn cũ trước, khách nào không đủ hàng thì bot báo thiếu bao nhiêu.
- 📦 **Nhắc đặt hàng nhà cung cấp**: tổng hàng khách đang chờ cộng tồn tối thiểu, trừ đi tồn hiện có.
- 📞 **Nhắc gọi khách quen đặt lại**: dựa vào chu kỳ đặt hàng trung bình của từng khách.

Viết bằng Python thuần, không cần cài thư viện. Dữ liệu lưu trong file SQLite `orders.db`.


## Dùng với ZaloCRM (khuyên dùng)

Nếu anh đang dùng [ZaloCRM](https://github.com/vuongnguyenbinh/ZaloCRM) để quản lý Zalo cá nhân, bot nhận tin nhắn
qua **Webhook** của ZaloCRM và gửi báo cáo bằng **API** của ZaloCRM. Anh không cần tạo bot Zalo riêng.

**Bước 1 – Tạo nhóm báo cáo:** lập 1 nhóm Zalo, ví dụ **"Bot đơn hàng"**, gồm tài khoản Zalo đang kết nối ZaloCRM
và anh/nhân viên. Báo cáo được gửi vào nhóm này, và mọi người gõ lệnh `/thieu`, `/lavabo`... ở đây.

**Bước 2 – Lấy API key:** trong ZaloCRM vào **API & Webhook**, bấm **Tạo key mới** rồi copy key.

**Bước 3 – Chạy bot cùng ZaloCRM:** chép thư mục `zalo-order-bot` vào thư mục ZaloCRM. Thêm vào file `.env` của ZaloCRM:

```
ORDER_BOT_API_KEY=key-vừa-tạo
ORDER_BOT_WEBHOOK_SECRET=mot-chuoi-bi-mat-dai
ORDER_BOT_REPORT_GROUP=Bot đơn hàng
```

Sau đó chạy:

```sh
docker compose -f docker-compose.yml -f zalo-order-bot/docker-compose.zalocrm.yml up -d --build
```

**Bước 4 – Cấu hình Webhook:** trong ZaloCRM vào **API & Webhook**:
- Webhook URL: `http://order-bot:8090/`
- Secret: đúng chuỗi `ORDER_BOT_WEBHOOK_SECRET`

Bấm **Lưu**, rồi bấm **Test Webhook**.

**Bước 5 – Cho bot biết tài khoản Zalo dùng để gửi tin:** sau khi cấu hình webhook, chạy `docker compose restart app`
một lần. Khi ZaloCRM kết nối lại Zalo, nó báo sự kiện `zalo.connected` và bot tự ghi nhớ tài khoản.
Cũng có thể đặt `ORDER_BOT_ACCOUNT_ID` trong `.env`.

Bot hoạt động như sau:

| Tin nhắn | Bot làm gì |
|---|---|
| Gõ trong nhóm "Bot đơn hàng": `Đơn anh Nam: 2 tủ lavabo 80cm`, `/thieu`, `/giao 3`... | Ghi đơn / trả lời ngay trong nhóm |
| Anh gõ `Đơn: 1 tủ lavabo 80cm; 2 vòi sen` **ngay trong chat với khách** | Tự lấy tên + SĐT khách từ ZaloCRM, xác nhận vào nhóm báo cáo (**không nhắn gì cho khách**) |
| Khách nhắn "lấy em 2 tủ lavabo 80 nhé", "gương 60 giá bao nhiêu", "còn hàng không" | **Báo ngay** vào nhóm: 🔔 tên, SĐT khách, nội dung, mã `K5`. Khách nhắn tiếp trong 2 giờ thì gộp chung, không báo trùng |
| Khách nhắn "em chuyển khoản rồi", "đã cọc" | Báo 💰 vào nhóm |
| Tin khách quá 30 phút chưa xử lý | ⏰ Nhắc lại 1 lần. Anh trả lời khách hoặc gõ `/xong K5` thì thôi nhắc |
| Gõ `/choxuly` trong nhóm | Danh sách tin khách còn chờ xử lý (cũng có trong báo cáo 8h và 17h) |
| Bật AI (`ANTHROPIC_API_KEY`) | Bot ghi thử luôn tin khách thành đơn (sản phẩm, số lượng) để anh kiểm tra |
| 8h và 17h mỗi ngày | Gửi báo cáo tổng hợp vào nhóm |

Bot nhận diện tin đặt hàng bằng từ khóa tiếng Việt (tủ lavabo, gương, vòi, sen, bồn cầu, chốt, lấy, giá bao nhiêu...),
nên **không cần AI** vẫn báo đơn được. Bot quét cả chat riêng lẫn nhóm khách. Khách không thể dùng lệnh của bot,
và bot không bao giờ nhắn cho khách. Webhook được kiểm tra chữ ký HMAC
`X-Webhook-Signature` của ZaloCRM.

> Lưu ý: ZaloCRM đăng nhập Zalo cá nhân bằng thư viện không chính thức (zca-js), nên có rủi ro bị Zalo hạn chế tài khoản.
> Bot chỉ gửi vài tin báo cáo mỗi ngày vào 1 nhóm nên rất ít tin, nhưng anh vẫn nên dùng một số Zalo phụ cho chắc.

## Dùng với Zalo Bot chính thức (không có ZaloCRM)

### 1. Tạo bot trên Zalo

1. Vào **bot.zaloplatforms.com** (Zalo Bot Platform), đăng nhập Zalo → *Tạo bot* → lấy **Bot Token**.
2. Thêm bot vào nhóm Zalo đặt hàng (hoặc nhắn riêng với bot).

> Bot chỉ đọc được tin nhắn mà Zalo gửi tới bot. Nếu trong nhóm bot chỉ nhận tin có nhắc tên (@bot),
> hãy ghi đơn bằng lệnh `/don ...` hoặc chuyển tiếp tin nhắn đơn cho bot.

### 2. Chạy bot

```sh
cd zalo-order-bot
export ZALO_BOT_TOKEN="123456:abc..."
export REPORT_TIMES="08:00,17:00"        # giờ tự gửi báo cáo
python3 -m bot.main                       # long polling, chạy được ngay trên máy tính/VPS
```

Chạy webhook (cần tên miền HTTPS):

```sh
export WEBHOOK_URL="https://ten-mien-cua-anh/zalo"
export WEBHOOK_SECRET="mot-chuoi-bi-mat-dai"
export PORT=8080
python3 -m bot.main
```

Bot phải chạy liên tục (VPS, máy tính để bàn bật 24/7, Railway/Render...) thì mới tự gửi báo cáo đúng giờ.

**Đọc tin nhắn đơn viết tự do bằng AI (tùy chọn):** `pip install anthropic` và đặt `ANTHROPIC_API_KEY`.
Khi đó những tin như *"chị Hoa lấy thêm 2 tủ 60 với 3 bộ sen nhé"* cũng được tự ghi thành đơn.
Nếu không bật thì bot chỉ ghi các tin bắt đầu bằng **"Đơn"**.

## Lệnh trong Zalo

| Gõ | Tác dụng |
|---|---|
| `Đơn anh Nam 0912345678: 2 tủ lavabo 80cm; 5 vòi sen` | Ghi đơn (có thể xuống dòng từng món, thêm `Ghi chú: ...`) |
| `/giao 12` · `/giao 12 vòi sen 2` | Giao hết đơn #12, hoặc giao một phần |
| `/datxuong 12` | Đã đặt xưởng tủ lavabo cho đơn #12 |
| `/huy 12` · `/xem 12` | Hủy đơn, hoặc xem chi tiết đơn |
| `/nhap vòi sen 20` · `/ton vòi sen 15` · `/ton` | Nhập kho, đặt lại số tồn, xem kho |
| `/toithieu vòi sen 5` | Đặt mức tồn tối thiểu để bot nhắc nhập hàng |
| `/thieu` · `/lavabo` · `/nhac` · `/donmo` · `/baocao` | Xem các báo cáo |
| `/choxuly` · `/xong K5` | Xem tin khách chờ xử lý, hoặc báo đã xử lý tin K5 |
| `/dangky` · `/huydangky` | Nhóm này nhận hoặc thôi nhận báo cáo tự động |

Sản phẩm có chữ "tủ lavabo", "tủ chậu", "tủ bàn đá"... được coi là hàng **đặt xưởng**. Loại hàng này không trừ kho và không tính vào thiếu hàng.

Mẫu báo cáo:

```
🗓 BÁO CÁO NGÀY 11/11/2026

🛁 CẦN LÊN ĐƠN TỦ LAVABO – 1 đơn
  • #1 anh Nam (0912345678) – 1 tủ lavabo 80cm trắng – chờ 0 ngày

⚠️ THIẾU HÀNG – 1 khách
👤 chị Lan
  • #2 vòi sen: thiếu 2/3 (đơn 11/11)

📦 CẦN ĐẶT HÀNG NHÀ CUNG CẤP
  • vòi sen: đặt thêm 4 (tồn 3, khách đang chờ 5)
```

## Kiểm thử

```sh
cd zalo-order-bot
python3 -m unittest discover -s tests -v
```
