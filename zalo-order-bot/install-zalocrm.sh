#!/usr/bin/env bash
# Cài bot báo đơn vào máy chủ ZaloCRM.
# Cách dùng (đứng trong thư mục ZaloCRM, đã chép thư mục zalo-order-bot vào đó):
#   bash zalo-order-bot/install-zalocrm.sh
#
# Script tự làm:
#   1. Lấy (hoặc tạo) API key của ZaloCRM và tài khoản Zalo đang kết nối, đọc thẳng từ CSDL
#      (nút "Tạo key"/"Lưu webhook" trên giao diện ZaloCRM hiện bị lỗi nên không dùng).
#   2. Cấu hình Webhook của ZaloCRM trỏ về bot, có chữ ký bí mật.
#   3. Ghi cấu hình vào .env, build và chạy container order-bot.
#
# Chạy không hỏi (dùng cho GitHub Actions): khi không có bàn phím (stdin không phải terminal),
# script lấy câu trả lời từ biến môi trường và không in tên/SĐT ra log:
#   REPORT_GROUP     tên nhóm Zalo nhận báo đơn (mặc định giữ giá trị cũ hoặc "Bot đơn hàng")
#   ACCOUNT_NUMBER   số thứ tự tài khoản Zalo (mặc định 1 = tài khoản đang kết nối gần nhất)
#   REPLACE_WEBHOOK  "c" để cho phép thay webhook đang trỏ chỗ khác
#   TELEGRAM_TOKEN   token bot Telegram (từ @BotFather) – có token thì bot chỉ ĐỌC Zalo, báo qua Telegram
set -euo pipefail

INTERACTIVE=0; [ -t 0 ] && INTERACTIVE=1
ask() {  # ask "câu hỏi" BIẾN_MÔI_TRƯỜNG giá_trị_mặc_định
  local answer=""
  if [ "$INTERACTIVE" = 1 ]; then read -rp "$1" answer; else answer="${!2:-}"; fi
  printf '%s' "${answer:-$3}"
}

# Chạy được cả với bash 3.2 có sẵn trên macOS (không dùng mapfile, mảng kết hợp...).
COMPOSE=(docker compose -f docker-compose.yml -f zalo-order-bot/docker-compose.zalocrm.yml)
BASE=(docker compose)   # thao tác với ZaloCRM (db, app) không cần file của bot -> không có cảnh báo biến thiếu
WEBHOOK_URL="http://order-bot:8090/"

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mLỖI: %s\033[0m\n' "$*" >&2; exit 1; }

[ -f docker-compose.yml ] && [ -f .env ] || die "Hãy chạy script trong thư mục ZaloCRM (nơi có docker-compose.yml và .env)."
[ -f zalo-order-bot/docker-compose.zalocrm.yml ] || die "Chưa chép thư mục zalo-order-bot vào thư mục ZaloCRM."
docker compose version >/dev/null 2>&1 || die "Không tìm thấy 'docker compose'."

env_get() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- || true; }
env_set() {
  if grep -qE "^$1=" .env; then
    local tmp; tmp=$(mktemp)
    awk -v k="$1" -v v="$2" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' .env >"$tmp" && cat "$tmp" >.env && rm -f "$tmp"
  else
    printf '%s=%s\n' "$1" "$2" >>.env
  fi
}

[ -z "$(tail -c1 .env)" ] || echo >>.env   # bảo đảm .env kết thúc bằng dòng mới
DB_USER=$(env_get DB_USER); DB_USER=${DB_USER:-crmuser}
DB_NAME=$(env_get DB_NAME); DB_NAME=${DB_NAME:-zalocrm}
sql() { "${BASE[@]}" exec -T db psql -U "$DB_USER" -d "$DB_NAME" -tA -v ON_ERROR_STOP=1 -c "$1"; }

say "Kiểm tra ZaloCRM đang chạy"
sql "SELECT 1" >/dev/null || die "Không kết nối được CSDL ZaloCRM. Chạy 'docker compose up -d' trước."

ORG_ID=$(sql "SELECT id FROM organizations ORDER BY created_at LIMIT 1")
[ -n "$ORG_ID" ] || die "ZaloCRM chưa có tổ chức nào. Vào web ZaloCRM tạo tài khoản admin trước."

setting() { sql "SELECT value_plain FROM app_settings WHERE org_id='$ORG_ID' AND setting_key='$1'"; }
set_setting() {
  sql "INSERT INTO app_settings (id, org_id, setting_key, value_plain, created_at, updated_at)
       VALUES (gen_random_uuid()::text, '$ORG_ID', '$1', '$2', now(), now())
       ON CONFLICT (org_id, setting_key) DO UPDATE SET value_plain = EXCLUDED.value_plain, updated_at = now()" >/dev/null
}

say "API key"
API_KEY=$(setting public_api_key)
if [ -z "$API_KEY" ]; then
  API_KEY="zcrm_$(openssl rand -hex 24)"
  set_setting public_api_key "$API_KEY"
  echo "Đã tạo API key mới."
else
  echo "Dùng API key đang có."
fi

say "Tài khoản Zalo dùng để gửi báo cáo"
ACCOUNT_ROWS=$(sql "SELECT id || '|' || coalesce(display_name,'?') || '|' || coalesce(phone,'') || '|' || status
                    FROM zalo_accounts WHERE org_id='$ORG_ID' ORDER BY (status='connected') DESC, last_connected_at DESC NULLS LAST")
ACCOUNTS=()
while IFS= read -r row; do [ -n "$row" ] && ACCOUNTS+=("$row"); done <<<"$ACCOUNT_ROWS"
[ ${#ACCOUNTS[@]} -gt 0 ] || die "ZaloCRM chưa có tài khoản Zalo nào. Vào web ZaloCRM thêm và quét QR trước."
for i in "${!ACCOUNTS[@]}"; do
  IFS='|' read -r _ name phone status <<<"${ACCOUNTS[$i]}"
  if [ "$INTERACTIVE" = 1 ]; then
    echo "  $((i + 1)). $name $phone ($status)"
  else  # log GitHub có thể công khai: không in tên, SĐT
    echo "  $((i + 1)). ${name:0:1}*** ($status)"
  fi
done
CHOICE=1
if [ ${#ACCOUNTS[@]} -gt 1 ]; then
  CHOICE=$(ask "Chọn số tài khoản Zalo [1]: " ACCOUNT_NUMBER 1)
fi
[[ "$CHOICE" =~ ^[0-9]+$ ]] && [ "$CHOICE" -ge 1 ] && [ "$CHOICE" -le ${#ACCOUNTS[@]} ] || die "Số tài khoản không hợp lệ: $CHOICE"
ACCOUNT_ID=$(cut -d'|' -f1 <<<"${ACCOUNTS[$((CHOICE - 1))]}")
echo "Dùng tài khoản số $CHOICE."

say "Nhận thông báo qua Telegram"
CUR_TG=$(env_get ORDER_BOT_TELEGRAM_TOKEN)
if [ -n "$CUR_TG" ]; then HINT="Enter = giữ token cũ"; else HINT="Enter = bỏ qua, báo qua nhóm Zalo"; fi
TG_TOKEN=$(ask "Dán token bot Telegram ($HINT): " TELEGRAM_TOKEN "$CUR_TG")
TG_TOKEN=$(printf '%s' "$TG_TOKEN" | tr -d '[:space:]')
TG_NAME=""
PAIR_CODE=""
GROUP=$(env_get ORDER_BOT_REPORT_GROUP)
tg_username() {  # tg_username TOKEN "tên bot" -> in @username, dừng nếu token sai
  [[ "$1" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]] \
    || die "Token $2 không đúng dạng (dạng đúng: 123456789:AAH...). Copy lại từ @BotFather."
  local me
  me=$(curl -fsS --max-time 20 "https://api.telegram.org/bot$1/getMe" 2>/dev/null) \
    || die "Telegram không nhận token $2 (sai token, hoặc máy không vào được Telegram)."
  printf '%s' "$me" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p'
}
DEPT_CODES="SALE KETOAN KHO KYTHUAT"
dept_label() { case "$1" in SALE) echo "Bot Sale";; KETOAN) echo "Bot Kế toán";; KHO) echo "Bot Kho";; KYTHUAT) echo "Bot Kỹ thuật";; esac; }
DEPT_LINES=""
if [ -n "$TG_TOKEN" ]; then
  TG_NAME=$(tg_username "$TG_TOKEN" "Bot Điều phối")
  echo "🧭 Bot Điều phối: @$TG_NAME"
  say "Bot riêng cho từng bộ phận (Enter = bỏ qua, Bot Điều phối báo thay)"
  SEEN=" $TG_TOKEN "
  for D in $DEPT_CODES; do
    CUR=$(env_get "ORDER_BOT_TELEGRAM_TOKEN_$D")
    if [ -n "$CUR" ]; then H="Enter = giữ token cũ"; else H="Enter = bỏ qua"; fi
    T=$(ask "Token $(dept_label "$D") ($H): " "TELEGRAM_TOKEN_$D" "$CUR")
    T=$(printf '%s' "$T" | tr -d '[:space:]')
    if [ -n "$T" ]; then
      case "$SEEN" in *" $T "*) die "Token $(dept_label "$D") trùng với bot khác. Mỗi bot phải tạo riêng với @BotFather.";; esac
      SEEN="$SEEN$T "
      U=$(tg_username "$T" "$(dept_label "$D")")
      echo "   $(dept_label "$D"): @$U"
      DEPT_LINES="$DEPT_LINES     @$U  ($(dept_label "$D"))\n"
    fi
    eval "TOKEN_$D=\$T"
  done
  PAIR_CODE=$(env_get ORDER_BOT_PAIR_CODE)
  [ -n "$PAIR_CODE" ] || PAIR_CODE=$(LC_ALL=C tr -dc '0-9' </dev/urandom 2>/dev/null | head -c 6 || true)
  echo "Bot chỉ ĐỌC tin Zalo, không gửi tin nào qua Zalo."
else
  say "Nhóm Zalo nhận báo đơn"
  GROUP=$(ask "Tên nhóm Zalo [${GROUP:-Bot đơn hàng}]: " REPORT_GROUP "${GROUP:-Bot đơn hàng}")
  echo "Nhóm báo đơn: $GROUP"
fi

say "Cấu hình Webhook ZaloCRM -> bot"
OLD_URL=$(setting webhook_url)
if [ -n "$OLD_URL" ] && [ "$OLD_URL" != "$WEBHOOK_URL" ]; then
  [ "$INTERACTIVE" = 1 ] && echo "ZaloCRM đang gửi webhook tới: $OLD_URL" || echo "ZaloCRM đang gửi webhook tới một địa chỉ khác."
  OK=$(ask "Thay bằng bot báo đơn? (c/k) [k]: " REPLACE_WEBHOOK k)
  [ "$OK" = "c" ] || die "Đã dừng, không thay đổi gì. (Trên GitHub: bật ô 'Cho phép thay webhook' rồi chạy lại.)"
fi
SECRET=$(env_get ORDER_BOT_WEBHOOK_SECRET)
SECRET=${SECRET:-$(openssl rand -hex 24)}
set_setting webhook_url "$WEBHOOK_URL"
set_setting webhook_secret "$SECRET"

say "Ghi cấu hình vào .env"
env_set ORDER_BOT_API_KEY "$API_KEY"
env_set ORDER_BOT_WEBHOOK_SECRET "$SECRET"
env_set ORDER_BOT_ACCOUNT_ID "$ACCOUNT_ID"
env_set ORDER_BOT_REPORT_GROUP "${GROUP:-Bot đơn hàng}"
env_set ORDER_BOT_TELEGRAM_TOKEN "$TG_TOKEN"
[ -z "$PAIR_CODE" ] || env_set ORDER_BOT_PAIR_CODE "$PAIR_CODE"
if [ -n "$TG_TOKEN" ]; then
  for D in $DEPT_CODES; do eval "env_set ORDER_BOT_TELEGRAM_TOKEN_$D \"\$TOKEN_$D\""; done
fi
grep -qE "^ORDER_BOT_REPORT_TIMES=" .env || env_set ORDER_BOT_REPORT_TIMES "08:00,17:00"
grep -qE "^ORDER_BOT_REMIND_MINUTES=" .env || env_set ORDER_BOT_REMIND_MINUTES "30"
grep -qE "^ORDER_BOT_MEETING_TIME=" .env || env_set ORDER_BOT_MEETING_TIME "18:00"
MEETING_AT=$(env_get ORDER_BOT_MEETING_TIME)

say "Build và chạy bot"
"${COMPOSE[@]}" up -d --build order-bot

say "Kiểm tra ZaloCRM gọi được bot"
sleep 3
if "${BASE[@]}" exec -T app node -e "fetch('$WEBHOOK_URL').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"; then
  echo "OK – ZaloCRM đã thấy bot."
else
  die "ZaloCRM chưa gọi được bot. Xem log: docker logs zalo-order-bot"
fi

if [ -n "$TG_TOKEN" ]; then
  cat <<EOF

✅ CÀI XONG – báo đơn qua Telegram!

Việc còn lại trên điện thoại (mã ghép nối: $PAIR_CODE):
  1. Mở Bot Điều phối @$TG_NAME, bấm Start, gõ:   /batdau $PAIR_CODE
     -> chat riêng của anh với Bot Điều phối: nhận báo cáo tổng + báo sự cố.
EOF
  if [ -n "$DEPT_LINES" ]; then
    printf '  2. Mở lần lượt từng bot bộ phận, bấm Start, gõ  /batdau %s  trong mỗi bot:\n' "$PAIR_CODE"
    printf "$DEPT_LINES"
    printf '     -> bot nào có việc quá hạn sẽ nhắn RIÊNG cho anh.\n'
  fi
  cat <<EOF
  3. PHÒNG ĐIỀU PHỐI:
     a) Nhắn @BotFather:  /setprivacy  -> chọn @$TG_NAME -> Disable
        (để Bot Điều phối đọc được lệnh trong nhóm như /xong K5)
     b) Tạo 1 nhóm Telegram, thêm Bot Điều phối và các bot bộ phận vào nhóm, rồi gõ trong nhóm:
          /batdau@$TG_NAME $PAIR_CODE phong
     -> Bot Điều phối sẽ gọi tên từng bot giao việc trong nhóm này.
  4. Nhờ ai nhắn vào Zalo shop: "lấy em 2 tủ lavabo 80 nhé"
     -> trong phòng: Bot Điều phối giao việc cho Bot Sale, Bot Sale xác nhận (khoảng 15 giây).
  5. Họp: gõ "họp công ty" hoặc "họp bộ phận kho" trong phòng. Bot tự họp công ty lúc ${MEETING_AT:-18:00} mỗi ngày.
     Hỏi riêng: "Kho ơi, tủ của anh Nam đến đâu rồi?" (cần ANTHROPIC_API_KEY trong .env).

Mã ghép nối: $PAIR_CODE  (giữ kín – ai có mã này sẽ xem được tin khách)
Xem log bot:      docker logs -f zalo-order-bot
Kiểm tra bot:     docker exec zalo-order-bot python -m bot.crm_main --check
EOF
  exit 0
fi

cat <<EOF

✅ CÀI XONG!

Việc còn lại trên điện thoại:
  1. Tạo nhóm Zalo tên đúng "$GROUP", có tài khoản Zalo đang kết nối ZaloCRM
     và số Zalo của anh / nhân viên.
  2. Dùng số Zalo của anh nhắn vào nhóm:  /help
     -> bot trả lời hướng dẫn là chạy được.
  3. Thử nhờ ai nhắn vào Zalo shop: "lấy em 2 tủ lavabo 80 nhé"
     -> nhóm sẽ nhận tin 🔔 báo đơn.

Xem log bot:      docker logs -f zalo-order-bot
Khởi động lại:    ${COMPOSE[*]} restart order-bot
Cập nhật bot:     chép thư mục zalo-order-bot mới rồi chạy lại script này
EOF
