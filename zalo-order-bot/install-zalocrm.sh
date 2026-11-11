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
set -euo pipefail

INTERACTIVE=0; [ -t 0 ] && INTERACTIVE=1
ask() {  # ask "câu hỏi" BIẾN_MÔI_TRƯỜNG giá_trị_mặc_định
  local answer=""
  if [ "$INTERACTIVE" = 1 ]; then read -rp "$1" answer; else answer="${!2:-}"; fi
  printf '%s' "${answer:-$3}"
}

COMPOSE=(docker compose -f docker-compose.yml -f zalo-order-bot/docker-compose.zalocrm.yml)
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
sql() { "${COMPOSE[@]}" exec -T db psql -U "$DB_USER" -d "$DB_NAME" -tA -v ON_ERROR_STOP=1 -c "$1"; }

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
mapfile -t ACCOUNTS < <(sql "SELECT id || '|' || coalesce(display_name,'?') || '|' || coalesce(phone,'') || '|' || status
                             FROM zalo_accounts WHERE org_id='$ORG_ID' ORDER BY (status='connected') DESC, last_connected_at DESC NULLS LAST")
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

say "Nhóm Zalo nhận báo đơn"
CUR_GROUP=$(env_get ORDER_BOT_REPORT_GROUP)
GROUP=$(ask "Tên nhóm Zalo [${CUR_GROUP:-Bot đơn hàng}]: " REPORT_GROUP "${CUR_GROUP:-Bot đơn hàng}")
echo "Nhóm báo đơn: $GROUP"

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
env_set ORDER_BOT_REPORT_GROUP "$GROUP"
grep -qE "^ORDER_BOT_REPORT_TIMES=" .env || env_set ORDER_BOT_REPORT_TIMES "08:00,17:00"
grep -qE "^ORDER_BOT_REMIND_MINUTES=" .env || env_set ORDER_BOT_REMIND_MINUTES "30"

say "Build và chạy bot"
"${COMPOSE[@]}" up -d --build order-bot

say "Kiểm tra ZaloCRM gọi được bot"
sleep 3
if "${COMPOSE[@]}" exec -T app node -e "fetch('$WEBHOOK_URL').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"; then
  echo "OK – ZaloCRM đã thấy bot."
else
  die "ZaloCRM chưa gọi được bot. Xem log: docker logs zalo-order-bot"
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
