# 🤖 Bot Zalo tổng hợp đơn hàng

Bot chat trên Zalo: đọc tin nhắn đơn hàng trong nhóm/chat, lưu lại và **tự đẩy báo cáo** mỗi ngày:

- 🛁 **Cần lên đơn tủ lavabo cho ai**: đơn có tủ lavabo nhưng chưa đặt xưởng, và tủ đã đặt nhưng chờ xưởng quá 10 ngày.
- ⚠️ **Khách nào đang thiếu hàng**: lấy tồn kho chia cho đơn cũ trước, khách nào không đủ hàng thì bot báo thiếu bao nhiêu.
- 📦 **Nhắc đặt hàng nhà cung cấp**: tổng hàng khách đang chờ cộng tồn tối thiểu, trừ đi tồn hiện có.
- 📞 **Nhắc gọi khách quen đặt lại**: dựa vào chu kỳ đặt hàng trung bình của từng khách.

Viết bằng Python thuần, không cần cài thư viện. Dữ liệu lưu trong file SQLite `orders.db`.

## 1. Tạo bot trên Zalo

1. Vào **bot.zaloplatforms.com** (Zalo Bot Platform), đăng nhập Zalo → *Tạo bot* → lấy **Bot Token**.
2. Thêm bot vào nhóm Zalo đặt hàng (hoặc nhắn riêng với bot).

> Bot chỉ đọc được tin nhắn mà Zalo gửi tới bot. Nếu trong nhóm bot chỉ nhận tin có nhắc tên (@bot),
> hãy ghi đơn bằng lệnh `/don ...` hoặc chuyển tiếp tin nhắn đơn cho bot.

## 2. Chạy bot

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

## 3. Cách dùng trong Zalo

| Gõ | Tác dụng |
|---|---|
| `Đơn anh Nam 0912345678: 2 tủ lavabo 80cm; 5 vòi sen` | Ghi đơn (có thể xuống dòng từng món, thêm `Ghi chú: ...`) |
| `/giao 12` · `/giao 12 vòi sen 2` | Giao hết đơn #12, hoặc giao một phần |
| `/datxuong 12` | Đã đặt xưởng tủ lavabo cho đơn #12 |
| `/huy 12` · `/xem 12` | Hủy đơn, hoặc xem chi tiết đơn |
| `/nhap vòi sen 20` · `/ton vòi sen 15` · `/ton` | Nhập kho, đặt lại số tồn, xem kho |
| `/toithieu vòi sen 5` | Đặt mức tồn tối thiểu để bot nhắc nhập hàng |
| `/thieu` · `/lavabo` · `/nhac` · `/donmo` · `/baocao` | Xem các báo cáo |
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
