"""Chạy bot gắn với ZaloCRM: python -m bot.crm_main

Biến môi trường:
  ZALOCRM_URL             địa chỉ ZaloCRM, vd http://app:3000 (cùng docker) hoặc http://IP:3080
  ZALOCRM_API_KEY         API key tạo ở menu "API & Webhook" của ZaloCRM
  ZALOCRM_WEBHOOK_SECRET  Webhook Secret đã nhập ở ZaloCRM (nên đặt)
  ZALOCRM_REPORT_GROUP    tên nhóm Zalo nhận báo cáo và gõ lệnh, vd "Bot đơn hàng"
  ZALOCRM_ACCOUNT_ID      (tùy chọn) id tài khoản Zalo trong ZaloCRM dùng để gửi tin.
                          Bỏ trống thì bot tự học khi ZaloCRM báo sự kiện zalo.connected.
  REPORT_TIMES            mặc định "08:00,17:00"
  POLL_SECONDS            bao lâu hỏi ZaloCRM tin mới 1 lần (giây), mặc định 15; 0 = chỉ dùng webhook
  SCAN_GROUPS             "1" = quét cả tin trong nhóm Zalo (mặc định chỉ chat riêng với khách)
  REMIND_MINUTES          nhắc lại tin khách chưa xử lý sau bao nhiêu phút, mặc định 30
  PORT                    cổng nhận webhook, mặc định 8090
  DB_PATH                 mặc định orders.db
  ANTHROPIC_API_KEY       (tùy chọn) tự nhận đơn từ tin nhắn khách viết tự do
"""
import json
import logging
import os
import sys
import threading
import time
import urllib.error
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .ai_parser import ai_available, ai_parse_order
from .db import Store
from .handlers import _confirm_order, handle_message
from .parser import looks_like_order, parse_command
from .detect import classify
from .reports import full_report, lead_line
from .text import norm
from .zalo import split_text
from .zalocrm import ZaloCRM, verify_signature

log = logging.getLogger("zalocrm-bot")


class CRMBot:
    def __init__(self, store: Store, crm: ZaloCRM, report_group: str, account_id: str = "",
                 scan_groups: bool = False):
        self.store = store
        self.crm = crm
        self.report_key = norm(report_group)
        if account_id:
            store.set_setting("account_id", account_id)
        self.scan_groups = scan_groups  # mặc định chỉ quét chat riêng; nhóm cộng đồng dễ báo nhầm
        self.lock = threading.Lock()
        self.recent_out: deque[str] = deque(maxlen=50)  # chống bot tự đọc lại tin của chính nó

    # ---------- gửi vào nhóm báo cáo ----------
    def report_conv(self) -> dict | None:
        conv_id = self.store.get_setting("report_conv_id")
        conv = self.crm.conversation(conv_id) if conv_id else None
        if conv is None and self.report_key:
            conv = self.crm.find_group(self.report_key)
            if conv:
                self.store.set_setting("report_conv_id", conv["id"])
                log.info("Đã tìm thấy nhóm báo cáo")
            else:
                log.warning("Chưa thấy nhóm Zalo tên '%s' trong ZaloCRM (nhóm phải có ít nhất 1 tin nhắn)",
                            self.report_key)
        return conv

    def send_report(self, text: str) -> bool:
        account_id = self.store.get_setting("account_id")
        conv = self.report_conv()
        if not account_id or not conv:
            log.warning("Chưa gửi được: thiếu %s", "account_id" if not account_id else "nhóm báo cáo")
            return False
        self.recent_out.extend(chunk.strip() for chunk in split_text(text))
        self.crm.send(account_id, conv, text)
        return True

    # ---------- xử lý sự kiện webhook ----------
    def handle_event(self, payload: dict):
        event = payload.get("event", "")
        data = payload.get("data") or {}
        source = payload.get("source", "webhook")
        if source == "webhook":
            self.store.set_setting("last_event", f"{datetime.now():%d/%m %H:%M:%S} {event}")
        if data.get("messageId") and not self.store.mark_seen(str(data["messageId"])):
            return  # đã xử lý (qua webhook hoặc qua hỏi định kỳ)
        log.info("Nhận %s qua %s (loại tin: %s)", event, source, data.get("contentType", "-"))
        if event == "zalo.connected" and data.get("accountId"):
            if not self.store.get_setting("account_id"):
                self.store.set_setting("account_id", data["accountId"])
                log.info("Đã nhận tài khoản Zalo %s", data["accountId"])
            return
        if event not in ("message.received", "message.sent"):
            return
        if data.get("contentType") not in (None, "", "text"):
            log.info("Bỏ qua: không phải tin chữ")
            return
        text = (data.get("content") or "").strip()
        if not text:
            return
        is_self = event == "message.sent"
        if is_self and text in self.recent_out:
            return
        conv = self.crm.conversation(data.get("conversationId", ""))
        if not conv:
            log.warning("Bỏ qua: API ZaloCRM không trả về cuộc trò chuyện %s", data.get("conversationId"))
            return
        report = self.report_conv()
        contact = conv.get("contact") or {}
        name, phone = contact.get("fullName") or "", contact.get("phone") or ""

        with self.lock:
            if report and conv["id"] == report["id"]:
                # Nhóm báo cáo: nhận lệnh và ghi đơn như bot thường
                reply = handle_message(self.store, text, conv["id"])
            elif is_self:
                # Anh/nhân viên gõ "Đơn: ..." hoặc lệnh ngay trong chat với khách -> trả lời vào nhóm báo cáo
                reply = handle_message(self.store, text, conv["id"], use_ai=False,
                                       default_customer=name, phone=phone)
                if reply:
                    if reply.startswith("✅ Đã ghi đơn"):
                        self.store.close_leads(conv_id=conv["id"])  # đã lên đơn -> tin khách coi như xong
                    reply = f"[chat với {name}]\n{reply}"
                else:
                    self.store.mark_conv_replied(conv["id"])  # anh đã trả lời khách -> thôi nhắc lại
            elif not parse_command(text) and (conv.get("threadType") != "group" or self.scan_groups):
                reply = self._customer_message(text, conv["id"], name, phone)
            else:
                reply = None
        if reply:
            self.send_report(reply)

    def _customer_message(self, text: str, conv_id: str, name: str, phone: str) -> str | None:
        """Quét tin khách: có ý đặt hàng / báo chuyển khoản -> báo ngay vào nhóm. Không nhắn lại cho khách."""
        kind = classify(text)
        if kind is None and not (ai_available() and looks_like_order(text)):
            return None
        lead_id, is_new = self.store.add_lead(conv_id, name or "Khách", phone, kind or "order", text)
        if not is_new:
            return None  # khách nhắn tiếp cùng đơn: gộp vào tin cũ, không báo trùng
        who = (name or "Khách") + (f" ({phone})" if phone else "")
        title = "💰 KHÁCH BÁO CHUYỂN KHOẢN / CỌC" if kind == "payment" else "🔔 KHÁCH ĐẶT HÀNG / HỎI HÀNG"
        lines = [f"{title} – K{lead_id}", f"👤 {who}", f"💬 “{text}”"]
        if kind != "payment" and ai_available():
            order = ai_parse_order(text, name)
            if order:
                oid = self.store.add_order(name or order.customer, order.items, order.phone or phone,
                                           order.note, conv_id, text)
                lines.append("🤖 Bot đã ghi thử thành đơn, anh kiểm tra lại:\n" + _confirm_order(self.store, oid))
        lines.append(f"→ Xử lý xong gõ /xong K{lead_id}")
        return "\n".join(lines)

    def remind_pending(self, minutes: int, now: datetime | None = None) -> bool:
        """Nhắc các tin khách đã chờ quá `minutes` phút mà chưa ai xử lý."""
        now = now or datetime.now()
        with self.lock:
            leads = self.store.leads_to_remind(minutes, now)
            if not leads:
                return False
            text = "\n".join([f"⏰ CÒN {len(leads)} TIN KHÁCH CHƯA XỬ LÝ (quá {minutes} phút)"]
                             + [lead_line(lead, now) for lead in leads]
                             + ["  → /xong K<mã> khi đã xử lý"])
            self.store.mark_reminded([lead["id"] for lead in leads])
        return self.send_report(text)

    # ---------- hỏi ZaloCRM định kỳ (không cần webhook) ----------
    def poll_once(self) -> int:
        """Lấy tin nhắn mới qua API công khai và xử lý như webhook. Trả về số tin mới."""
        convs = self.crm.refresh_conversations()
        stamps = [c["lastMessageAt"] for c in convs if c.get("lastMessageAt")]
        cursor = self.store.get_setting("poll_cursor")
        if not cursor:  # lần đầu: chỉ xử lý tin đến sau thời điểm này, không quét lại lịch sử
            self.store.set_setting("poll_cursor", max(stamps) if stamps else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            log.info("Bắt đầu theo dõi tin nhắn mới từ ZaloCRM")
            return 0
        count = 0
        for conv in convs:
            if not conv.get("lastMessageAt") or conv["lastMessageAt"] <= cursor:
                continue
            for m in reversed(self.crm.messages(conv["id"])):
                if (m.get("sentAt") or "") <= cursor:
                    continue
                count += 1
                self.handle_event({"source": "hỏi định kỳ",
                                   "event": "message.sent" if m.get("senderType") == "self" else "message.received",
                                   "data": {"messageId": m.get("id"), "conversationId": conv["id"],
                                            "content": m.get("content"), "contentType": m.get("contentType")}})
        if stamps and max(stamps) > cursor:
            self.store.set_setting("poll_cursor", max(stamps))
        if count:
            self.store.set_setting("last_poll_msg", f"{datetime.now():%d/%m %H:%M:%S}")
        return count

    def poller(self, seconds: int):
        while True:
            try:
                self.poll_once()
                self.store.prune_seen()
            except Exception:  # noqa: BLE001
                log.exception("Lỗi khi hỏi tin nhắn mới từ ZaloCRM")
            time.sleep(seconds)

    # ---------- báo cáo định kỳ ----------
    def scheduler(self, times: list[str], remind_minutes: int = 30):
        sent = set()
        while True:
            now = datetime.now()
            try:
                self.remind_pending(remind_minutes, now)
            except Exception:  # noqa: BLE001
                log.exception("Nhắc tin khách thất bại")
            tag = f"{now.date()} {now:%H:%M}"
            if f"{now:%H:%M}" in times and tag not in sent:
                sent.add(tag)
                try:
                    with self.lock:
                        text = full_report(self.store, now)
                    self.send_report(text)
                except Exception:  # noqa: BLE001
                    log.exception("Gửi báo cáo định kỳ thất bại")
            time.sleep(20)


def serve(bot: CRMBot, port: int, secret: str):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if not verify_signature(secret, body, self.headers.get("X-Webhook-Signature", "")):
                log.warning("Từ chối webhook: sai chữ ký (Webhook Secret trong ZaloCRM khác ORDER_BOT_WEBHOOK_SECRET)")
                bot.store.set_setting("last_event", f"{datetime.now():%d/%m %H:%M:%S} SAI CHỮ KÝ")
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            try:
                payload = json.loads(body or b"{}")
            except json.JSONDecodeError:
                return
            threading.Thread(target=self._process, args=(payload,), daemon=True).start()

        @staticmethod
        def _process(payload):
            try:
                bot.handle_event(payload)
            except Exception:  # noqa: BLE001
                log.exception("Lỗi xử lý sự kiện %s", payload.get("event"))

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    log.info("Đang nhận webhook ZaloCRM ở cổng %s", port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


def check(bot: CRMBot, secret: str) -> int:
    """In tình trạng kết nối để tìm lỗi (python -m bot.crm_main --check)."""
    ok = True
    print("1. API key ZaloCRM: ", end="")
    try:
        bot.crm.refresh_conversations()
        convs = list(bot.crm._conv_cache.values())
        groups = [c for c in convs if c.get("threadType") == "group"]
        print(f"OK – đọc được {len(convs)} cuộc trò chuyện, {len(groups)} nhóm")
    except urllib.error.HTTPError as e:
        print(f"LỖI {e.code}" + (" – API key sai" if e.code == 401 else ""))
        return 1
    except OSError as e:
        print(f"LỖI – không gọi được ZaloCRM ({e})")
        return 1
    print("2. Tài khoản Zalo gửi tin:", "có" if bot.store.get_setting("account_id") else "CHƯA CÓ")
    ok &= bool(bot.store.get_setting("account_id"))
    report = bot.crm.find_group(bot.report_key) if bot.report_key else None
    print(f"3. Nhóm báo cáo '{bot.report_key}':", "ĐÃ THẤY" if report else "CHƯA THẤY")
    if not report:
        ok = False
        print("   Các nhóm ZaloCRM đang có:", ", ".join(
            norm((c.get("contact") or {}).get("fullName") or "?") for c in groups[:15]) or "(không có)")
    print("4. Webhook Secret:", "có" if secret else "KHÔNG ĐẶT")
    last = bot.store.get_setting("last_event")
    print("5. Webhook từ ZaloCRM:", last or "chưa nhận (không sao – bot tự hỏi tin mới định kỳ)")
    polled = bot.store.get_setting("last_poll_msg")
    print("6. Tự hỏi tin mới:", ("đang chạy – lần cuối có tin mới lúc " + polled) if polled
          else ("đang chạy – chưa có tin mới" if bot.store.get_setting("poll_cursor") else "CHƯA CHẠY"))
    ok &= bool(bot.store.get_setting("poll_cursor"))
    return 0 if ok else 1


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    url, key = os.environ.get("ZALOCRM_URL"), os.environ.get("ZALOCRM_API_KEY")
    if not url or not key:
        raise SystemExit("Thiếu ZALOCRM_URL hoặc ZALOCRM_API_KEY")
    store = Store(os.environ.get("DB_PATH", "orders.db"))
    bot = CRMBot(store, ZaloCRM(url, key), os.environ.get("ZALOCRM_REPORT_GROUP", ""),
                 os.environ.get("ZALOCRM_ACCOUNT_ID", ""),
                 scan_groups=os.environ.get("SCAN_GROUPS", "0") == "1")
    if "--check" in sys.argv:
        raise SystemExit(check(bot, os.environ.get("ZALOCRM_WEBHOOK_SECRET", "")))
    if "--send-report" in sys.argv:  # gửi báo cáo ngay rồi thoát (nút trên GitHub Actions)
        if not bot.send_report(full_report(store)):
            raise SystemExit("Chưa gửi được: bot chưa tìm thấy nhóm Zalo báo đơn hoặc tài khoản Zalo. "
                             "Hãy nhắn 1 tin vào nhóm rồi thử lại.")
        return
    times = [t.strip() for t in os.environ.get("REPORT_TIMES", "08:00,17:00").split(",") if t.strip()]
    remind = int(os.environ.get("REMIND_MINUTES", "30"))
    threading.Thread(target=bot.scheduler, args=(times, remind), daemon=True).start()
    poll = int(os.environ.get("POLL_SECONDS", "15"))
    if poll > 0:
        threading.Thread(target=bot.poller, args=(poll,), daemon=True).start()
    serve(bot, int(os.environ.get("PORT", "8090")), os.environ.get("ZALOCRM_WEBHOOK_SECRET", ""))


if __name__ == "__main__":
    main()
