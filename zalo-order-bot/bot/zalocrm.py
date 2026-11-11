"""Kết nối với ZaloCRM (github.com/vuongnguyenbinh/ZaloCRM).

- Nhận sự kiện qua Webhook của ZaloCRM: {"event", "timestamp", "data": {...}}, ký HMAC-SHA256
  ở header X-Webhook-Signature.
- Gửi tin nhắn qua API công khai: POST /api/public/messages/send (header X-API-Key).
"""
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

from .zalo import split_text


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    if not secret:
        return True  # chưa đặt secret bên ZaloCRM thì ZaloCRM không ký
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


class ZaloCRM:
    def __init__(self, base_url: str, api_key: str):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self._conv_cache: dict[str, dict] = {}
        self._cache_at = 0.0

    def _request(self, method: str, path: str, payload: dict | None = None, query: dict | None = None):
        url = self.base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode() or "{}")

    # ---------- hội thoại ----------
    def refresh_conversations(self):
        data = self._request("GET", "/api/public/conversations", query={"limit": 100})
        for c in data.get("conversations", []):
            self._conv_cache[c["id"]] = c
        self._cache_at = time.time()

    def conversation(self, conversation_id: str) -> dict | None:
        if conversation_id not in self._conv_cache or time.time() - self._cache_at > 600:
            self.refresh_conversations()
        return self._conv_cache.get(conversation_id)

    def find_group(self, name_key: str) -> dict | None:
        """Tìm nhóm chat theo tên (đã chuẩn hóa không dấu)."""
        from .text import norm

        self.refresh_conversations()
        for c in self._conv_cache.values():
            contact = c.get("contact") or {}
            if c.get("threadType") == "group" and norm(contact.get("fullName") or "") == name_key:
                return c
        return None

    # ---------- gửi tin ----------
    def send(self, account_id: str, conv: dict, text: str):
        for chunk in split_text(text):
            self._request("POST", "/api/public/messages/send", {
                "zaloAccountId": account_id,
                "threadId": conv["externalThreadId"],
                "threadType": conv.get("threadType", "user"),
                "content": chunk,
            })
