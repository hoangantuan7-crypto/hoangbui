# 🤖 Bot Zalo tổng hợp đơn hàng

Bot chat trên Zalo giúp **không trượt đơn**: quét tin nhắn của khách, thấy khách đặt hàng, hỏi hàng hoặc báo chuyển khoản
là **báo ngay** vào nhóm Zalo của anh. Tin nào quá 30 phút chưa xử lý thì bot nhắc lại. Bot cũng **tự đẩy báo cáo** mỗi ngày:

- 🛁 **Cần lên đơn tủ lavabo cho ai**: đơn có tủ lavabo nhưng chưa đặt xưởng, và tủ đã đặt nhưng chờ xưởng quá 10 ngày.
- ⚠️ **Khách nào đang thiếu hàng**: lấy tồn kho chia cho đơn cũ trước, khách nào không đủ hàng thì bot báo thiếu bao nhiêu.
- 📦 **Nhắc đặt hàng nhà cung cấp**: tổng hàng khách đang chờ cộng tồn tối thiểu, trừ đi tồn hiện có.
- 📞 **Nhắc gọi khách quen đặt lại**: dựa vào chu kỳ đặt hàng trung bình của từng khách.

Viết bằng Python thuần, không cần cài thư viện. Dữ liệu lưu trong file SQLite `orders.db`.


## Dùng với ZaloCRM (khuyên dùng)

### Báo đơn qua Telegram (khuyên dùng)

Ở chế độ này bot **chỉ đọc** tin nhắn Zalo qua ZaloCRM và **không gửi bất kỳ tin nào qua Zalo**.
Thông báo đơn, nhắc việc, báo cáo 8h và 17h, và các lệnh `/choxuly`, `/xong K5`... đều nằm trong Telegram.

1. Trong Telegram, nhắn **@BotFather** → `/newbot`, đặt tên (ví dụ "Việt Hoàng báo đơn") và username kết thúc bằng `bot`.
   BotFather sẽ gửi **token** dạng `123456789:AAH...`.
2. Chạy script cài đặt. Đến câu hỏi token thì dán token vào:
   ```sh
   cd ~/zcrm && git -C ~/hoangbui pull -q && cp -r ~/hoangbui/zalo-order-bot . && bash zalo-order-bot/install-zalocrm.sh
   ```
3. Script in ra **mã ghép nối** gồm 6 số. Mở bot trong Telegram, bấm Start rồi gõ `/batdau <mã>`.
   Muốn nhân viên cùng nhận thông báo: thêm bot vào một nhóm Telegram, rồi gõ lệnh đó trong nhóm.

Người không có mã ghép nối không xem được gì và không ra lệnh được cho bot. Gõ `/huydangky` để ngắt một chat.

### 5 bot riêng và phòng điều phối

Anh có thể dùng **5 bot Telegram riêng**, mỗi bot có tên và khung chat riêng, nhưng cả 5 dùng chung một kho dữ liệu:

| Bot | Việc |
|---|---|
| 🧭 Bot Điều phối | Đọc tin Zalo, chia việc, gửi báo cáo tổng, báo sự cố (ví dụ không đọc được Zalo) |
| 🛒 Bot Sale | Đặt hàng, hỏi giá. Lệnh: ghi đơn, `/donmo`, `/nhac`, `/giao`… |
| 💰 Bot Kế toán | Chuyển khoản, hóa đơn, công nợ |
| 📦 Bot Kho | Giao hàng, đổi trả. Lệnh: `/thieu`, `/ton`, `/nhap`, `/lavabo`, `/datxuong`… |
| 🔧 Bot Kỹ thuật | Lắp đặt, bảo hành, sửa chữa |

Mỗi bot chỉ nhận lệnh của bộ phận mình. Gõ `/help` trong từng bot để xem danh sách lệnh.

**Tạo bot:** nhắn @BotFather `/newbot`, mỗi bot một lần (5 lần), mỗi lần ra một token khác nhau. Sau đó chạy script cài
đặt và dán từng token khi script hỏi. Bộ phận nào bỏ qua (bấm Enter) thì Bot Điều phối báo thay.

**Kết nối:** mở từng bot, bấm Start, gõ `/batdau <mã>`.

**Phòng điều phối:** tạo một nhóm Telegram gồm anh và cả 5 bot.
- Nhắn @BotFather `/setprivacy`, chọn Bot Điều phối, chọn **Disable**.
- Trong nhóm, gõ `/batdau@<tên Bot Điều phối> <mã> phong`.

Từ đó:
- Có việc mới: Bot Điều phối **gọi tên** bot phụ trách ngay trong nhóm ("Giao việc K5 cho @BotKyThuat…"), và bot đó
  xác nhận "Đã nhận việc K5".
- Có vấn đề (việc quá 30 phút chưa xử lý, bot chưa được thêm vào nhóm, không đọc được Zalo): bot phụ trách
  **nhắn riêng cho anh**.
- Trong nhóm: gõ `/xong K5`, `/choxuly`, `/chuyen K5 kho` (Bot Điều phối trả lời). Lệnh riêng của một bot thì gọi tên
  bot đó, ví dụ `/thieu@<tên Bot Kho>`. Tin trò chuyện thường trong nhóm, các bot không trả lời.

Telegram không cho bot đọc tin của bot khác trong nhóm. Vì cả 5 bot chạy chung một chương trình, chúng phối hợp với
nhau từ bên trong; trong nhóm anh vẫn thấy từng bot lên tiếng.

### Nhắc khách chưa được trả lời (miễn phí, không cần AI)

- **Khách nhắn mà quá 15 phút chưa được trả lời** (kể cả khi anh đã đọc tin nhưng quên trả lời): Bot Điều phối
  nhắn riêng anh danh sách khách đang chờ, kèm câu khách hỏi và thời gian đã chờ. Quá 1 giờ thì nhắc lần 2.
  Anh trả lời khách trên Zalo là bot tự thôi nhắc. Chỉ nhắc trong giờ làm việc 07:00–21:00.
- **Khách có vẻ chưa được giải đáp đúng**: sau khi shop đã trả lời, khách nhắn kiểu "không phải, ý em là…",
  "em hỏi cái khác mà", "anh chưa trả lời câu em hỏi", "???". Bot báo riêng anh ngay để anh trả lời lại.
- Gõ `/chuatraloi` để xem ngay khách nào đang chờ. Cuộc họp 18:00 cũng báo số khách chờ, và khách chờ quá 1 giờ
  nằm trong mục "Cần anh quyết".
- Những tin chỉ để chốt chuyện như "ok anh nhé", "cảm ơn anh", sticker thì không cần trả lời, bot không nhắc.
- Việc của từng bộ phận (K5…) **không tự đóng khi anh trả lời khách**. Việc chỉ đóng khi gõ `/xong K5`, vì trả lời
  rồi chưa chắc vấn đề đã xong.

Một số bản ZaloCRM ghi nhầm tin anh trả lời bằng điện thoại thành tin của khách. Script cài đặt tự lấy **tên nick
Zalo của shop** (`ORDER_BOT_SHOP_NAMES`), nhờ đó bot vẫn nhận ra đó là shop trả lời và không báo nhầm thành việc.
Đổi thời gian bằng `ORDER_BOT_REPLY_MINUTES` và `ORDER_BOT_WORK_HOURS` trong `.env`.

### Họp với các bot và hỏi riêng từng bộ phận

**Họp:** gõ tự do trong phòng điều phối hoặc trong chat riêng với một bot.

| Gõ | Kết quả |
|---|---|
| "họp công ty", "họp toàn bộ", `/hop` | Bot Điều phối mở họp. Bot Sale, Kế toán, Kho, Kỹ thuật lần lượt báo cáo: việc mới, đã xong, đang chờ, quá hạn, thiếu hàng, tủ lavabo chờ xưởng. Cuối cùng Bot Điều phối liệt kê **"Cần anh quyết"**. |
| "họp bộ phận kho", "họp sale", `/hop kythuat` | Họp riêng một bộ phận: bot đó báo cáo chi tiết từng việc. |
| "họp" trong chat riêng với Bot Kho | Họp riêng bộ phận Kho. |

Mỗi ngày lúc **18:00** bot tự họp công ty trong phòng điều phối. Đổi giờ bằng `ORDER_BOT_MEETING_TIME` trong `.env`,
để trống thì tắt họp tự động.

**Hỏi riêng bộ phận** (cần AI, xem bên dưới):
- Trong phòng: "Kho ơi, tủ của anh Nam đến đâu rồi?", "Kế toán ơi hôm nay ai chuyển khoản?", "@BotKho còn bao nhiêu vòi sen?".
  Hoặc bấm **Trả lời** (reply) vào tin của một bot rồi hỏi tiếp.
- Trong chat riêng với một bot: nhắn tự do, bot đó trả lời.

Bot trả lời **dựa trên dữ liệu thật**: việc đang chờ, đơn hàng, tồn kho, tủ lavabo, việc đã xong. Không có dữ liệu
thì bot nói là chưa có, không tự bịa.

Để bật AI, thêm `ANTHROPIC_API_KEY=...` vào `.env` của ZaloCRM rồi chạy lại script cài đặt. Phí tính theo lượt hỏi;
ước tính khoảng vài trăm đến 1.000 đồng một câu, tùy lượng dữ liệu. Câu hỏi và dữ liệu của bộ phận đó (tên, SĐT,
nội dung tin khách) được gửi tới Claude API để trả lời. Chưa bật AI thì bot gửi số liệu hiện có thay cho câu trả lời.

### Bot điều phối: chia việc cho từng bộ phận

Bot đọc từng tin khách, rồi giao việc cho bộ phận phù hợp:

| Bộ phận | Ví dụ tin khách |
|---|---|
| 🛒 `sale` | "lấy em 2 tủ lavabo 80", "gương 60 giá bao nhiêu", "còn hàng không" |
| 💰 `ketoan` | "em chuyển khoản rồi", "xuất hóa đơn VAT giúp em", "công nợ" |
| 📦 `kho` | "bao giờ giao hàng", "hàng bị vỡ", "đổi hàng" |
| 🔧 `kythuat` | "lắp đặt", "bảo hành", "bị rỉ nước", "vòi bị hỏng" |

Tạo một nhóm Telegram cho mỗi bộ phận, thêm bot vào nhóm, rồi gõ trong nhóm `/batdau <mã> kho` (đổi `kho` thành
`sale`, `ketoan` hoặc `kythuat`). Mỗi nhóm chỉ nhận tin báo, tin nhắc việc trễ và `/choxuly` của bộ phận mình.
Chat ghép nối không kèm bộ phận (`/batdau <mã>`) là **chat tổng**: nhận mọi việc và báo cáo 8h/17h.

- Bot giao nhầm bộ phận: gõ `/chuyen K5 kythuat` để chuyển việc, bộ phận mới được báo ngay.
- Xem chat đang thuộc bộ phận nào: gõ `/bophan`.
- Thêm bộ phận mới, ví dụ marketing: thêm một dòng vào `bot/departments.py` (tên bộ phận và từ khóa).


Nếu anh đang dùng [ZaloCRM](https://github.com/vuongnguyenbinh/ZaloCRM) để quản lý Zalo cá nhân, bot nhận tin nhắn
qua **Webhook** của ZaloCRM và gửi báo cáo bằng **API** của ZaloCRM. Anh không cần tạo bot Zalo riêng.

### Cách dễ nhất: bấm nút trên GitHub (dùng được cả trên điện thoại)

**Làm 1 lần trên máy tính – khai báo máy chủ:** vào kho code trên GitHub → **Settings → Secrets and variables →
Actions → New repository secret**, tạo các secret sau:

| Tên secret | Giá trị |
|---|---|
| `SERVER_HOST` | IP máy chủ ZaloCRM |
| `SERVER_USER` | tài khoản SSH, thường là `root` |
| `SERVER_PASSWORD` | mật khẩu SSH (hoặc dùng `SERVER_SSH_KEY` = khóa SSH riêng) |
| `SERVER_PORT` | chỉ cần nếu cổng SSH khác 22 |

GitHub mã hóa các secret này. Ngay cả khi kho code để công khai, người khác cũng không xem được.

**Mỗi lần dùng (máy tính hoặc app GitHub trên điện thoại):** mở kho code → tab **Actions** → chọn
**Bot báo đơn Zalo** → **Run workflow**, chọn việc cần làm rồi bấm **Run workflow**:
- **Cài đặt / cập nhật bot**: chép bot mới nhất lên máy chủ và chạy script cài đặt.
- **Khởi động lại bot**
- **Xem tình trạng bot**: bot có đang chạy không, có bao nhiêu lỗi trong 24 giờ qua.
- **Gửi báo cáo ngay vào nhóm Zalo**: dùng để thử bot.

Dấu ✅ xanh là thành công. Dấu ❌ đỏ thì bấm vào lần chạy đó để xem bước nào lỗi; câu báo lỗi viết bằng tiếng Việt.

Nhật ký chạy không in tên, SĐT hay tin nhắn khách, vì kho code công khai thì ai cũng xem được nhật ký.

### Hoặc cài bằng dòng lệnh (khoảng 5 phút)

Đăng nhập SSH vào máy chủ đang chạy ZaloCRM, rồi làm 3 bước sau.

**1. Tải bot về và chép vào thư mục ZaloCRM** (đổi `~/ZaloCRM` nếu anh cài ở chỗ khác):

```sh
cd ~
git clone https://github.com/hoangantuan7-crypto/hoangbui.git
cp -r hoangbui/zalo-order-bot ~/ZaloCRM/
```

Nếu kho code để chế độ riêng tư, `git clone` sẽ hỏi tên đăng nhập GitHub và mật khẩu. Ở ô mật khẩu, anh dán
**Personal Access Token** (tạo tại GitHub → Settings → Developer settings → Tokens).

**2. Chạy script cài đặt:**

```sh
cd ~/ZaloCRM
bash zalo-order-bot/install-zalocrm.sh
```

Script hỏi 2 câu: chọn tài khoản Zalo nào để gửi báo cáo (nếu có nhiều) và tên nhóm (mặc định "Bot đơn hàng").
Sau đó script tự làm các việc sau:
- lấy hoặc tạo API key của ZaloCRM;
- cấu hình Webhook có chữ ký bí mật;
- ghi các biến `ORDER_BOT_*` vào `.env`;
- build và chạy container `zalo-order-bot`;
- kiểm tra ZaloCRM đã gọi được bot.

> Script ghi cấu hình thẳng vào CSDL vì trong bản ZaloCRM hiện tại, nút **Lưu** webhook không lưu được
> (giao diện gửi `webhookUrl` nhưng máy chủ đọc `url`) và nút **Tạo key mới** không hiện key ra.
> Anh **đừng bấm Lưu webhook** trên giao diện ZaloCRM sau khi cài, vì làm vậy sẽ xóa cấu hình.

**3. Trên điện thoại:**
1. Tạo nhóm Zalo đúng tên đã chọn, có tài khoản Zalo đang kết nối ZaloCRM và số Zalo của anh hoặc nhân viên.
2. Dùng **số Zalo của anh** (không phải số đang kết nối ZaloCRM) nhắn vào nhóm `/help`. Bot trả lời là chạy được.
3. Nhờ ai đó nhắn vào Zalo shop "lấy em 2 tủ lavabo 80 nhé". Nhóm sẽ nhận tin 🔔 báo đơn.

Lệnh hay dùng trên máy chủ:

```sh
docker logs -f zalo-order-bot                    # xem bot đang làm gì
cd ~/ZaloCRM && docker compose -f docker-compose.yml -f zalo-order-bot/docker-compose.zalocrm.yml restart order-bot
```

**Cập nhật bot bản mới:** chạy `cd ~/hoangbui && git pull`, rồi `cp -r zalo-order-bot ~/ZaloCRM/`,
rồi chạy lại `bash zalo-order-bot/install-zalocrm.sh`. Dữ liệu đơn hàng nằm trong volume Docker nên không bị mất.

Đổi giờ gửi báo cáo hoặc thời gian nhắc lại: sửa `ORDER_BOT_REPORT_TIMES` và `ORDER_BOT_REMIND_MINUTES` trong `.env`
của ZaloCRM, rồi chạy lại script. Muốn bật AI thì thêm `ANTHROPIC_API_KEY=...` vào `.env`.

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
