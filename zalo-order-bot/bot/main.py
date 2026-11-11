"""Chạy bot: python -m bot.main

Biến môi trường:
  ZALO_BOT_TOKEN      token bot lấy ở bot.zaloplatforms.com (bắt buộc)
  ZALO_API_BASE       mặc định https://bot-api.zaloplatforms.com
  DB_PATH             mặc định orders.db
  REPORT_TIMES        giờ gửi báo cáo tự động, mặc định "08:00,17:00"
  ADMIN_CHAT_IDS      chat_id luôn nhận báo cáo (phân tách bằng dấu phẩy)
  WEBHOOK_URL         nếu đặt -> chạy webhook (cần HTTPS), không thì dùng long polling
  WEBHOOK_SECRET      chuỗi bí mật 8-256 ký tự cho webhook
  PORT                cổng webhook, mặc định 8080
  ANTHROPIC_API_KEY   (tùy chọn) bật đọc đơn viết tự do bằng Claude
"""
import hmac
import json
import logging
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .db import Store
from .handlers import handle_message
from .reports import full_report
from .zalo import ZaloBot, extract_message

log = logging.getLogger("zalo-order-bot")


def process_update(bot: ZaloBot, store: Store, update: dict, lock: threading.Lock):
    parsed = extract_message(update)
    if not parsed:
        return
    chat_id, text, sender = parsed
    with lock:
        reply = handle_message(store, text, chat_id, sender)
    if reply:
        bot.send_text(chat_id, reply)


def scheduler(bot: ZaloBot, store: Store, lock: threading.Lock, times: list[str], admins: list[str]):
    sent = set()
    while True:
        now = datetime.now()
        slot = now.strftime("%H:%M")
        tag = f"{now.date()} {slot}"
        if slot in times and tag not in sent:
            sent.add(tag)
            with lock:
                text = full_report(store, now)
                targets = set(store.subscribed_chats()) | set(admins)
            for chat_id in targets:
                try:
                    bot.send_text(chat_id, text)
                except Exception:  # noqa: BLE001 - một chat lỗi không chặn chat khác
                    log.exception("Gửi báo cáo tới %s thất bại", chat_id)
        time.sleep(20)


def run_polling(bot: ZaloBot, store: Store, lock: threading.Lock):
    log.info("Đang chạy chế độ long polling…")
    while True:
        try:
            for update in bot.get_updates():
                process_update(bot, store, update, lock)
        except Exception:  # noqa: BLE001
            log.exception("Lỗi khi lấy tin nhắn, thử lại sau 5 giây")
            time.sleep(5)


def run_webhook(bot: ZaloBot, store: Store, lock: threading.Lock, port: int, secret: str):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            token = self.headers.get("X-Bot-Api-Secret-Token", "")
            if not hmac.compare_digest(token, secret):
                self.send_response(403)
                self.end_headers()
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.end_headers()
            try:
                process_update(bot, store, json.loads(body or b"{}"), lock)
            except Exception:  # noqa: BLE001
                log.exception("Lỗi xử lý webhook")

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

    log.info("Webhook lắng nghe cổng %s", port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("ZALO_BOT_TOKEN")
    if not token:
        raise SystemExit("Thiếu ZALO_BOT_TOKEN")
    bot = ZaloBot(token, os.environ.get("ZALO_API_BASE", "https://bot-api.zaloplatforms.com"))
    store = Store(os.environ.get("DB_PATH", "orders.db"))
    lock = threading.Lock()
    times = [t.strip() for t in os.environ.get("REPORT_TIMES", "08:00,17:00").split(",") if t.strip()]
    admins = [c.strip() for c in os.environ.get("ADMIN_CHAT_IDS", "").split(",") if c.strip()]
    threading.Thread(target=scheduler, args=(bot, store, lock, times, admins), daemon=True).start()

    webhook_url = os.environ.get("WEBHOOK_URL")
    if webhook_url:
        secret = os.environ.get("WEBHOOK_SECRET", "")
        if not 8 <= len(secret) <= 256:
            raise SystemExit("WEBHOOK_SECRET phải dài 8-256 ký tự")
        bot.set_webhook(webhook_url, secret)
        run_webhook(bot, store, lock, int(os.environ.get("PORT", "8080")), secret)
    else:
        try:
            bot.delete_webhook()
        except Exception:  # noqa: BLE001 - chưa từng đặt webhook
            pass
        run_polling(bot, store, lock)


if __name__ == "__main__":
    main()
