"""Gửi thông báo và nhận lệnh qua Telegram Bot API (không cần địa chỉ công khai: dùng long polling).

Bảo mật: bot Telegram ai cũng tìm được, nên chỉ những chat đã gõ đúng mã ghép nối
(/batdau <mã>) mới nhận thông báo và dùng được lệnh.
"""
import hmac
import html
import json
import logging
import re
import urllib.request

log = logging.getLogger(__name__)
MAX_TEXT = 4000  # Telegram giới hạn 4096 ký tự/tin


def split_text(text: str, limit: int = MAX_TEXT) -> list[str]:
    chunks, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    return chunks


# 3 mức thông báo (Telegram không cho bot đổi màu chữ -> dùng biểu tượng màu + chữ đậm + khung trích dẫn)
DO, VANG, XANH = "do", "vang", "xanh"
ICONS = {DO: "🔴", VANG: "🟡", XANH: "🟢"}
GREEN_WORDS = ("ĐÃ LÊN ĐƠN", "ĐÃ THU", "ĐÃ BỎ NHÁP")
YELLOW_WORDS = ("NHÁP ĐƠN", "CẦN KIỂM TRA", "không đọc được số điện thoại", "Không tải/đọc được",
                "không lấy được link ảnh", "không đọc được phiếu")
RED_WORDS = ("CHƯA ĐƯỢC GIẢI ĐÁP", "KHÁCH ĐANG CHỜ ANH TRẢ LỜI", "NHẮC LẦN 2", "CHƯA XỬ LÝ (quá",
             "không đọc được tin Zalo", "không nhắn được", "KHÔNG LÊN ĐƯỢC SHEET")
YELLOW_STARTS = ("🧭 Giao việc", "📅 GHI LỊCH", "⏰", "🔔", "🆕", "↪️", "📇")


def alert_level(text: str) -> str:
    """🔴 khách gặp vấn đề / việc quá hạn / bot lỗi · 🟡 việc mới, lịch hẹn, nhắc trước · 🟢 báo cáo, đã xong."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    head = lines[0] if lines else ""
    if any(w in head for w in GREEN_WORDS):
        return XANH
    if any(w in head for w in YELLOW_WORDS):
        return VANG
    if (head.startswith(("⚠️", "❌", "⛔")) or any(w in head for w in RED_WORDS)
            or any(ln.startswith("❌") for ln in lines)):
        return DO
    if head.startswith(YELLOW_STARTS) or re.search(r"– [KLN]\d+$", head):
        return VANG
    return XANH


def format_alert(text: str, level: str, first: bool = True) -> str:
    """Tin thường -> HTML theo mức: 🔴 tiêu đề đậm + nội dung trong khung · 🟡 tiêu đề đậm · 🟢 giữ nguyên."""
    lines = text.split("\n")
    head, body = (lines[0], "\n".join(lines[1:]).strip("\n")) if first else ("", text)
    out = []
    if head:
        title = html.escape(head)
        out.append(f"{ICONS[level]} <b>{title}</b>" if level in (DO, VANG) else f"{ICONS[level]} {title}")
    if body:
        out.append(f"<blockquote>{html.escape(body)}</blockquote>" if level == DO else html.escape(body))
    return "\n".join(out)


class Telegram:
    def __init__(self, token: str, base: str = "https://api.telegram.org"):
        self.url = f"{base.rstrip('/')}/bot{token}"

    def call(self, method: str, payload: dict | None = None, timeout: float = 40):
        req = urllib.request.Request(
            f"{self.url}/{method}",
            data=json.dumps(payload or {}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode() or "{}")
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data.get('description')}")
        return data.get("result")

    def send(self, chat_id: str, text: str, level: str | None = None) -> list[int]:
        """level=None: tin thường (trả lời lệnh). level=do/vang/xanh: thông báo có màu; xanh gửi im lặng.
        Trả về mã các tin đã gửi (để nhận ra khi anh trả lời đúng tin đó)."""
        ids = []
        for i, chunk in enumerate(split_text(text, 3500 if level else MAX_TEXT)):
            payload = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
            if level:
                payload.update(text=format_alert(chunk, level, first=i == 0), parse_mode="HTML",
                               disable_notification=level == XANH)  # 🟢 không rung/không chuông
            try:
                res = self.call("sendMessage", payload)
            except RuntimeError as e:
                if not level or "parse" not in str(e).lower():
                    raise
                log.warning("Telegram không nhận định dạng, gửi lại chữ thường: %s", e)
                res = self.call("sendMessage", {"chat_id": chat_id, "text": f"{ICONS[level]} {chunk}",
                                                "disable_web_page_preview": True})
            if isinstance(res, dict) and res.get("message_id"):
                ids.append(res["message_id"])
        return ids

    def get_updates(self, offset: int, timeout: int = 30) -> list[dict]:
        return self.call("getUpdates", {"offset": offset, "timeout": timeout,
                                        "allowed_updates": ["message"]}, timeout=timeout + 15) or []

    def get_me(self) -> dict:
        return self.call("getMe", timeout=15)


PAIR_RE = re.compile(r"^/(?:batdau|start)(?:@\S+)?\s*(\S*)", re.IGNORECASE)


def pairing_reply(text: str, pair_code: str) -> tuple[bool, str] | None:
    """Xử lý /batdau <mã>. Trả về (ghép_thành_công, câu_trả_lời) hoặc None nếu không phải lệnh ghép."""
    m = PAIR_RE.match(text.strip())
    if not m:
        return None
    code = m.group(1)
    if pair_code and code and hmac.compare_digest(code, pair_code):
        return True, ("✅ Đã kết nối! Từ giờ bot báo đơn khách Zalo vào đây.\n"
                      "Gõ /help để xem lệnh, /choxuly để xem tin khách đang chờ.")
    return False, "🔒 Bot riêng của shop. Gõ /batdau <mã ghép nối> (mã hiện lúc cài bot trên máy tính)."
