"""Gửi thông báo và nhận lệnh qua Telegram Bot API (không cần địa chỉ công khai: dùng long polling).

Bảo mật: bot Telegram ai cũng tìm được, nên chỉ những chat đã gõ đúng mã ghép nối
(/batdau <mã>) mới nhận thông báo và dùng được lệnh.
"""
import hmac
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

    def send(self, chat_id: str, text: str):
        for chunk in split_text(text):
            self.call("sendMessage", {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True})

    def get_updates(self, offset: int, timeout: int = 30) -> list[dict]:
        return self.call("getUpdates", {"offset": offset, "timeout": timeout,
                                        "allowed_updates": ["message"]}, timeout=timeout + 15) or []

    def get_me(self) -> dict:
        return self.call("getMe")


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
