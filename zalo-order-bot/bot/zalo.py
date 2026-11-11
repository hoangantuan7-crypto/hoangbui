"""Client tối giản cho Zalo Bot Platform (bot.zaloplatforms.com).

API có dạng giống Telegram: POST {ZALO_API_BASE}/bot<TOKEN>/<method>.
Nếu Zalo đổi địa chỉ, chỉ cần đặt lại biến môi trường ZALO_API_BASE.
"""
import json
import logging
import urllib.request

log = logging.getLogger(__name__)
MAX_TEXT = 2000  # giới hạn độ dài 1 tin nhắn


class ZaloBot:
    def __init__(self, token: str, base: str = "https://bot-api.zaloplatforms.com"):
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
        if not data.get("ok", True):
            raise RuntimeError(f"Zalo {method} lỗi: {data}")
        return data.get("result", data)

    def send_text(self, chat_id: str, text: str):
        for chunk in split_text(text):
            self.call("sendMessage", {"chat_id": chat_id, "text": chunk})

    def get_updates(self, timeout: int = 30) -> list[dict]:
        result = self.call("getUpdates", {"timeout": str(timeout)}, timeout=timeout + 10)
        if not result:
            return []
        return result if isinstance(result, list) else [result]

    def set_webhook(self, url: str, secret: str):
        return self.call("setWebhook", {"url": url, "secret_token": secret})

    def delete_webhook(self):
        return self.call("deleteWebhook")


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


def extract_message(update: dict) -> tuple[str, str, str] | None:
    """Lấy (chat_id, text, tên người gửi) từ 1 sự kiện; None nếu không phải tin nhắn chữ."""
    msg = update.get("message") or update.get("result", {}).get("message")
    if not msg:
        return None
    sender = msg.get("from") or {}
    if sender.get("is_bot"):
        return None
    text = msg.get("text")
    chat = msg.get("chat") or {}
    chat_id = chat.get("id") or sender.get("id")
    if not text or not chat_id:
        return None
    return str(chat_id), text, sender.get("display_name") or sender.get("name") or ""
