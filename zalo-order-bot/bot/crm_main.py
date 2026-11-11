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
  SHOP_NAMES / SHOP_UIDS  tên / mã nick Zalo của shop (script cài đặt tự điền) – để nhận ra tin shop trả lời
  REPLY_MINUTES           khách chờ bao nhiêu phút chưa được trả lời thì nhắc, mặc định 15
  WORK_HOURS              giờ làm việc để nhắc, mặc định 07:00-21:00
  MEETING_TIME            giờ họp công ty tự động mỗi ngày, mặc định 18:00 (để trống = tắt)
  REMIND_MINUTES          nhắc lại tin khách chưa xử lý sau bao nhiêu phút, mặc định 30
  PORT                    cổng nhận webhook, mặc định 8090
  DB_PATH                 mặc định orders.db
  TELEGRAM_BOT_TOKEN      token bot Telegram (lấy từ @BotFather). Có token -> bot chỉ ĐỌC Zalo,
                          mọi thông báo/lệnh qua Telegram, không gửi tin Zalo nào
  TELEGRAM_TOKEN_SALE / _KETOAN / _KHO / _KYTHUAT
                          (tùy chọn) token bot riêng của từng bộ phận; bộ phận chưa có bot -> Bot Điều phối báo thay
  PAIR_CODE               mã ghép nối: gõ "/batdau <mã>" cho bot Telegram để nhận thông báo
  ANTHROPIC_API_KEY       (tùy chọn) tự nhận đơn từ tin nhắn khách viết tự do
"""
import json
import logging
import os
import re
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
from .parser import looks_like_order, parse_command, parse_order
from .dept_bots import ALLOWED, BOT_NAMES, DIEUPHOI, FREE_TEXT_ORDERS, dept_help, not_allowed
from .departments import DEPTS, ROOM, TONG, dept_icon, dept_list, dept_name, parse_dept, route
from .ai_assistant import ask_bot, parse_address
from .followup import dissatisfied, in_work_hours, needs_reply, parse_ts, short, utc_now, wait_text, waiting_lines
from .meeting import COMPANY, build_meeting, flatten, parse_meeting
from .reports import full_report, lead_line, report_leads
from .text import norm
from .zalo import split_text
from .telegram import Telegram, pairing_reply
from .zalocrm import ZaloCRM, verify_signature

log = logging.getLogger("zalocrm-bot")


class CRMBot:
    def __init__(self, store: Store, crm: ZaloCRM, report_group: str, account_id: str = "",
                 scan_groups: bool = False, telegram: Telegram | None = None, pair_code: str = "",
                 dept_bots: dict[str, Telegram] | None = None):
        self.store = store
        self.crm = crm
        self.report_key = norm(report_group)
        if account_id:
            store.set_setting("account_id", account_id)
        self.tg = telegram          # có Telegram: chỉ ĐỌC Zalo, mọi thông báo gửi qua Telegram
        # 5 bot riêng: "dieuphoi" + bot của từng bộ phận (bộ phận chưa có bot -> Bot Điều phối báo thay)
        self.bots: dict[str, Telegram] = ({DIEUPHOI: telegram, **(dept_bots or {})} if telegram else {})
        if telegram:
            # chat ghép nối từ bản cũ (1 bot) thuộc Bot Điều phối
            store.conn.execute(f"UPDATE chats SET chat_id='{DIEUPHOI}:' || chat_id WHERE chat_id NOT LIKE '%:%'")
            store.conn.commit()
        self.pair_code = pair_code
        self.usernames: dict[str, str] = {}  # tên @ của từng bot (để gọi tên nhau trong phòng điều phối)
        self.poll_failures = 0
        self.ask = ask_bot            # hỏi đáp bằng AI (thay được trong test)
        self.remind_minutes = 30
        self.meeting_time = "18:00"   # họp công ty tự động mỗi ngày
        # Nick Zalo của shop: tin gửi từ điện thoại có thể bị ZaloCRM ghi nhầm là tin khách -> nhận ra bằng tên/mã
        self.shop_names: set[str] = set()
        self.shop_uids: set[str] = set()
        self.reply_minutes = 15       # khách chờ quá ngần này phút chưa được trả lời -> nhắc anh
        self.second_minutes = 60      # vẫn chưa trả lời -> nhắc lần 2
        self.work_hours = "07:00-21:00"
        self.scan_groups = scan_groups  # mặc định chỉ quét chat riêng; nhóm cộng đồng dễ báo nhầm
        self.lock = threading.Lock()
        self.recent_out: deque[str] = deque(maxlen=50)  # chống bot tự đọc lại tin của chính nó

    # ---------- gửi vào nhóm báo cáo ----------
    def report_conv(self) -> dict | None:
        if self.tg:
            return None  # chế độ Telegram: không dùng nhóm Zalo
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

    def send_report(self, text: str, dept: str | None = None) -> bool:
        """Gửi tin. Chế độ Telegram: dept=None -> chat tổng (không có thì mọi chat);
        dept=<bộ phận> -> nhóm của bộ phận đó + chat tổng."""
        if self.tg:
            chats = self.targets(dept)
            if not chats:
                log.warning("Chưa có chat Telegram nào ghép nối (gõ /batdau <mã> cho bot Telegram)")
                return False
            for key in chats:
                self._tg_send(key, text)
            return True
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
        text = (data.get("content") or "").strip()
        is_self = (event == "message.sent" or str(data.get("senderUid") or "") in self.shop_uids
                   or (bool(data.get("senderName")) and norm(data["senderName"]) in self.shop_names))
        if is_self and text in self.recent_out:
            return
        conv = self.crm.conversation(data.get("conversationId", ""))
        if not conv:
            log.warning("Bỏ qua: API ZaloCRM không trả về cuộc trò chuyện %s", data.get("conversationId"))
            return
        report = self.report_conv()
        contact = conv.get("contact") or {}
        name, phone = contact.get("fullName") or "", contact.get("phone") or ""
        is_text = data.get("contentType") in (None, "", "text") and bool(text)
        if not (report and conv["id"] == report["id"]):
            self.track_reply(conv, name, phone, data, is_self, text if is_text else "")
        if not is_text:
            log.info("Bỏ qua: không phải tin chữ")
            return

        target = None  # bộ phận nhận tin (None = chat tổng)
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
            elif not parse_command(text) and (conv.get("threadType") != "group" or self.scan_groups):
                reply, target, lead_id = self._customer_message(text, conv["id"], name, phone)
            else:
                reply = None
        if reply and target and self.room_key():
            self.assign_in_room(reply, target, lead_id)
        elif reply:
            self.send_report(reply, target)

    def _customer_message(self, text: str, conv_id: str, name: str, phone: str) -> tuple:
        """Bot điều phối: đọc tin khách, chọn bộ phận, báo vào nhóm bộ phận đó. Không nhắn lại cho khách.
        Trả về (nội dung báo, bộ phận, mã việc)."""
        dept = route(text)
        if dept is None and ai_available() and looks_like_order(text):
            dept = "sale"
        if dept is None:
            return None, None, None
        lead_id, is_new = self.store.add_lead(conv_id, name or "Khách", phone, dept, text)
        if not is_new:
            return None, None, None  # khách nhắn tiếp cùng việc: gộp vào tin cũ, không báo trùng
        who = (name or "Khách") + (f" ({phone})" if phone else "")
        icon, dname, title = DEPTS[dept]
        lines = [f"{icon} {dname.upper()} – {title} – K{lead_id}", f"👤 {who}", f"💬 “{text}”"]
        if dept == "sale" and ai_available():
            order = ai_parse_order(text, name)
            if order:
                oid = self.store.add_order(name or order.customer, order.items, order.phone or phone,
                                           order.note, conv_id, text)
                lines.append("🤖 Bot đã ghi thử thành đơn, anh kiểm tra lại:\n" + _confirm_order(self.store, oid))
        lines.append(f"→ Xong gõ /xong K{lead_id} · Sai bộ phận: /chuyen K{lead_id} <bộ phận>")
        return "\n".join(lines), dept, lead_id

    def remind_pending(self, minutes: int, now: datetime | None = None) -> bool:
        """Nhắc các tin khách đã chờ quá `minutes` phút mà chưa ai xử lý."""
        now = now or datetime.now()
        with self.lock:
            leads = self.store.leads_to_remind(minutes, now)
            if not leads:
                return False
            self.store.mark_reminded([lead["id"] for lead in leads])
        sent = False
        for dept in dict.fromkeys(lead["kind"] for lead in leads):  # giữ thứ tự, mỗi bộ phận 1 tin
            group = [lead for lead in leads if lead["kind"] == dept]
            text = "\n".join([f"⏰ {dept_icon(dept)} {dept_name(dept).upper()}: CÒN {len(group)} TIN KHÁCH "
                              f"CHƯA XỬ LÝ (quá {minutes} phút)"]
                             + [lead_line(lead, now) for lead in group]
                             + ["  → /xong K<mã> khi đã xử lý"])
            sent |= self.report_problem(text, dept) if self.room_key() else self.send_report(text, dept)
        return sent

    # ---------- Phòng điều phối: Bot Điều phối gọi tên từng bot giao việc ----------
    def room_key(self) -> str | None:
        """Nhóm Telegram làm phòng điều phối (ghép bằng "/batdau <mã> phong" với Bot Điều phối)."""
        if not self.tg:
            return None
        for key, dept in self.store.subscribed_rows():
            if dept == ROOM and key.startswith(f"{DIEUPHOI}:"):
                return key
        return None

    def mention(self, botname: str) -> str:
        icon, title = BOT_NAMES[botname]
        user = self.usernames.get(botname)
        return f"{icon} @{user}" if user else f"{icon} {title}"

    def assign_in_room(self, text: str, dept: str, lead_id: int):
        """Bot Điều phối giao việc trong phòng, bot bộ phận xác nhận nhận việc ngay trong phòng."""
        room = self.room_key()
        group_id = room.partition(":")[2]
        own_bot = dept in self.bots and dept != DIEUPHOI
        self._tg_send(room, f"🧭 Giao việc K{lead_id} cho {self.mention(dept) if own_bot else dept_name(dept)}\n\n{text}")
        if own_bot:
            icon, title = BOT_NAMES[dept]
            try:
                self.bots[dept].send(group_id, f"{icon} {title}: Đã nhận việc K{lead_id}. Xử lý xong gõ /xong K{lead_id}")
            except Exception:  # noqa: BLE001
                log.exception("%s không nhắn được vào phòng điều phối", title)
                self.report_problem(f"⚠️ {title} không nhắn được vào phòng điều phối – anh thêm {title} vào nhóm "
                                    f"giúp em. Việc K{lead_id} vẫn đang chờ.")

    def report_problem(self, text: str, dept: str | None = None) -> bool:
        """Có vấn đề -> bot phụ trách nhắn RIÊNG cho anh (chat 1-1 với bot đó).
        Bộ phận chưa có bot riêng hoặc anh chưa kết nối riêng với bot đó -> Bot Điều phối nhắn riêng."""
        if not self.tg:
            return self.send_report(text, dept)

        def private(botname, depts):
            return [k for k, d in self.store.subscribed_rows()
                    if k.startswith(f"{botname}:") and not k.partition(":")[2].startswith("-") and d in depts]

        keys = private(dept, {dept}) if dept and dept in self.bots and dept != DIEUPHOI else []
        keys = keys or private(DIEUPHOI, {TONG}) or private(DIEUPHOI, set(DEPTS))
        for key in keys:
            self._tg_send(key, text)
        return bool(keys)

    def load_usernames(self):
        for name, tg in self.bots.items():
            try:
                self.usernames[name] = tg.get_me().get("username", "")
            except Exception:  # noqa: BLE001
                log.warning("Không lấy được tên %s (token sai?)", BOT_NAMES[name][1])

    def should_handle(self, botname: str, chat_id: str, text: str, reply_to: str | None = None) -> bool:
        """Trong nhóm (chat_id âm) nhiều bot cùng nghe: lệnh có @tên chỉ bot đó trả lời,
        lệnh không có @ chỉ Bot Điều phối trả lời – tránh 5 bot cùng trả lời 1 câu."""
        if not str(chat_id).startswith("-"):
            return True
        text = (text or "").strip()
        if not text.startswith("/"):
            # Trong nhóm chỉ Bot Điều phối đọc câu thường, và chỉ khi là: ghi đơn, gọi họp,
            # gọi tên 1 bot để hỏi, hoặc trả lời (reply) tin của 1 bot. Còn lại: không trả lời.
            return botname == DIEUPHOI and bool(parse_order(text) or parse_meeting(text)
                                                 or parse_address(text, self.usernames) or reply_to)
        m = re.match(r"^/\w+@(\w+)", text)
        if m:
            return m.group(1).lower() == self.usernames.get(botname, "").lower()
        return botname == DIEUPHOI

    # ---------- Khách chờ trả lời ----------
    def track_reply(self, conv: dict, name: str, phone: str, data: dict, is_self: bool, text: str):
        """Ghi ai nói cuối trong từng cuộc chat; khách tỏ ý chưa được giải đáp đúng -> báo riêng anh ngay."""
        thread = conv.get("threadType") or "user"
        at = parse_ts(data.get("sentAt")).isoformat()
        if is_self:
            self.store.shop_said(conv["id"], at)
            return
        if not text:
            return  # khách gửi sticker/ảnh: không tính là câu hỏi cần trả lời
        prev = self.store.customer_said(conv["id"], name or "Khách", phone, thread, at, text, needs_reply(text))
        if (dissatisfied(text) and prev is not None and prev["last_shop_at"]
                and (thread == "user" or self.scan_groups)):
            who = (name or "Khách") + (f" ({phone})" if phone else "")
            self.report_problem(f"⚠️ {who} có vẻ CHƯA ĐƯỢC GIẢI ĐÁP ĐÚNG:\n💬 “{short(text, 200)}”\n"
                                "→ Anh xem lại câu khách hỏi trước đó và trả lời lại giúp em.")

    def unanswered_text(self, now: datetime | None = None, min_minutes: float = 0) -> str:
        now = now or utc_now()
        rows = [r for r in self.store.waiting_convs(self.scan_groups)
                if (now - parse_ts(r["wait_since"])).total_seconds() >= min_minutes * 60]
        if not rows:
            return "✅ Không có khách nào đang chờ anh trả lời."
        return "\n".join([f"💬 {len(rows)} KHÁCH ĐANG CHỜ ANH TRẢ LỜI"] + waiting_lines(rows, now)
                         + ["→ Trả lời khách trên Zalo là bot tự thôi nhắc."])

    def check_unanswered(self, now: datetime | None = None, local: datetime | None = None) -> bool:
        """Nhắc khách chờ quá reply_minutes (lần 1) và quá second_minutes (lần 2), chỉ trong giờ làm việc."""
        now, local = now or utc_now(), local or datetime.now()
        if not in_work_hours(local, self.work_hours):
            return False
        first, second = [], []
        for r in self.store.waiting_convs(self.scan_groups):
            mins = (now - parse_ts(r["wait_since"])).total_seconds() / 60
            if r["remind_level"] == 0 and mins >= self.reply_minutes:
                first.append(r)
            elif r["remind_level"] == 1 and mins >= self.second_minutes:
                second.append(r)
        sent = False
        if first:
            self.store.set_remind_level([r["conv_id"] for r in first], 1)
            sent |= self.report_problem("\n".join(
                [f"💬 {len(first)} KHÁCH ĐANG CHỜ ANH TRẢ LỜI"] + waiting_lines(first, now)
                + ["→ Trả lời khách trên Zalo là bot tự thôi nhắc. Xem tất cả: /chuatraloi"]))
        if second:
            self.store.set_remind_level([r["conv_id"] for r in second], 2)
            sent |= self.report_problem("\n".join(
                [f"⏰ NHẮC LẦN 2 – {len(second)} KHÁCH CHỜ QUÁ {wait_text(self.second_minutes)}"]
                + waiting_lines(second, now)))
        return sent

    # ---------- Họp & hỏi đáp ----------
    def _speak(self, botname: str, group_id: str, text: str):
        """1 bot lên tiếng trong nhóm; bot đó chưa có hoặc chưa vào nhóm thì Bot Điều phối nói thay."""
        bot = self.bots.get(botname)
        if bot is not None and botname != DIEUPHOI:
            try:
                bot.send(group_id, text)
                return
            except Exception:  # noqa: BLE001
                log.warning("%s chưa nhắn được vào nhóm, Bot Điều phối nói thay", BOT_NAMES[botname][1])
        self.bots[DIEUPHOI].send(group_id, text)

    def run_meeting(self, scope: str, dept: str | None, chat_key: str, auto: bool = False) -> str | None:
        """Họp trong nhóm: từng bot lần lượt báo cáo bằng chính tên mình.
        Họp trong chat riêng: bot đang chat gửi 1 tin tổng hợp cả cuộc họp."""
        with self.lock:
            msgs = build_meeting(self.store, scope, dept, datetime.now(), self.remind_minutes, auto)
        botname, _, chat = chat_key.partition(":")
        if chat.startswith("-") and self.bots:
            for speaker, text in msgs:
                self._speak(speaker, chat, text)
            return None
        return flatten(msgs)

    def auto_meeting(self, now: datetime):
        """Họp công ty tự động (mặc định 18:00): trong phòng điều phối nếu có, không thì gửi riêng cho anh."""
        room = self.room_key()
        if room:
            self.run_meeting(COMPANY, None, room, auto=True)
            return
        with self.lock:
            text = flatten(build_meeting(self.store, COMPANY, None, now, self.remind_minutes, auto=True))
        self.send_report(text)

    def answer(self, bot: str, question: str, raw_chat: str) -> str | None:
        """Hỏi riêng 1 bộ phận. Trong nhóm: chính bot được hỏi trả lời; chat riêng: trả lời ngay trong chat."""
        reply = self.ask(bot, question, self.store)
        if raw_chat.startswith("-") and self.bots:
            self._speak(bot, raw_chat, reply)
            return None
        return reply

    # ---------- Telegram: chọn bot + chat nhận tin ----------
    def targets(self, dept: str | None) -> list[str]:
        """Khóa chat ("<bot>:<chat_id>") nhận tin.
        dept=None: báo cáo tổng -> chat tổng của Bot Điều phối.
        dept có bot riêng -> chat của bot bộ phận đó (+ nhóm bộ phận ghép vào Bot Điều phối).
        dept chưa có bot riêng -> Bot Điều phối: nhóm bộ phận + chat tổng."""
        rows = self.store.subscribed_rows()
        dp = [(k, d) for k, d in rows if k.startswith(f"{DIEUPHOI}:") and d != ROOM]
        tong = [k for k, d in dp if d == TONG]
        if dept is None:
            return tong or [k for k, _ in dp]
        mine = [k for k, d in rows if k.startswith(f"{dept}:") and dept in self.bots] + [k for k, d in dp if d == dept]
        if dept in self.bots and dept != DIEUPHOI:
            return mine or tong  # bot bộ phận chưa ai ghép nối -> báo về chat tổng, không sót việc
        return mine + tong

    def _tg_send(self, key: str, text: str):
        botname, _, chat_id = key.partition(":")
        bot = self.bots.get(botname) or self.bots.get(DIEUPHOI)
        try:
            bot.send(chat_id, text)
        except Exception:  # noqa: BLE001 - 1 chat lỗi không chặn chat khác
            log.exception("Gửi Telegram (%s) thất bại", botname)

    def dept_only_chats(self, dept: str) -> list[str]:
        return [k for k, d in self.store.subscribed_rows() if d == dept]

    def send_daily(self, now: datetime):
        """Báo cáo giờ cố định: chat tổng nhận báo cáo đầy đủ, nhóm bộ phận nhận việc tồn của mình."""
        with self.lock:
            text = full_report(self.store, now)
            per_dept = {d: report_leads(self.store, now, d) for d in DEPTS}
        self.send_report(text)
        if self.tg:
            for dept, body in per_dept.items():
                for key in self.dept_only_chats(dept):
                    self._tg_send(key, f"🗓 {now:%d/%m} – việc của bộ phận\n\n{body}")

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
                                            "content": m.get("content"), "contentType": m.get("contentType"),
                                            "senderName": m.get("senderName"), "sentAt": m.get("sentAt")}})
        if stamps and max(stamps) > cursor:
            self.store.set_setting("poll_cursor", max(stamps))
        if count:
            self.store.set_setting("last_poll_msg", f"{datetime.now():%d/%m %H:%M:%S}")
        return count

    def poll_tick(self):
        """1 vòng hỏi tin. Lỗi 3 lần liên tiếp -> Bot Điều phối nhắn riêng anh (1 lần), đọc lại được thì báo."""
        try:
            self.poll_once()
            self.store.prune_seen()
            if self.poll_failures >= 3:
                self.report_problem("✅ Bot Điều phối đã đọc lại được tin nhắn Zalo từ ZaloCRM.")
            self.poll_failures = 0
        except Exception:  # noqa: BLE001
            log.exception("Lỗi khi hỏi tin nhắn mới từ ZaloCRM")
            self.poll_failures += 1
            if self.poll_failures == 3:  # báo 1 lần, không spam
                self.report_problem("⚠️ Bot Điều phối không đọc được tin Zalo từ ZaloCRM (3 lần liên tiếp).\n"
                                    "Kiểm tra: ZaloCRM còn chạy không, tài khoản Zalo còn kết nối không.")

    def poller(self, seconds: int):
        while True:
            self.poll_tick()
            time.sleep(seconds)

    # ---------- Telegram: nhận lệnh ----------
    def handle_telegram(self, chat_id: str, text: str, sender: str = "", botname: str = DIEUPHOI,
                        reply_to: str | None = None) -> str | None:
        """Tin nhắn gửi tới 1 bot Telegram. botname: "dieuphoi" hoặc mã bộ phận của bot đó."""
        text = (text or "").strip()
        if not text:
            return None
        raw_chat = str(chat_id)
        bot_dept = None if botname == DIEUPHOI else botname
        room = self.room_key()
        in_room = bool(bot_dept and room and room.partition(":")[2] == str(chat_id))
        chat_id = f"{botname}:{chat_id}"
        icon, title = BOT_NAMES[botname]
        paired = pairing_reply(text, self.pair_code)
        if paired:
            ok, reply = paired
            if ok and bot_dept:
                self.store.subscribe(chat_id, sender, True, bot_dept)
                log.info("Đã ghép nối thêm 1 chat với %s", title)
                return (f"✅ Đã kết nối với {icon} {title}!\nBot sẽ báo vào đây mọi việc của bộ phận "
                        f"{dept_name(bot_dept)} và nhắc lại nếu quá hạn. Gõ /help để xem lệnh.")
            if ok:
                words = text.split()
                dept = parse_dept(words[2]) if len(words) > 2 else TONG
                if dept is None:
                    return f"❓ Không rõ bộ phận '{words[2]}'. Chọn: {dept_list()} – hoặc bỏ trống để nhận tất cả."
                self.store.subscribe(chat_id, sender, True, dept)
                log.info("Đã ghép nối thêm 1 chat Telegram (%s)", dept)
                if dept == ROOM:
                    return ("✅ Đã đặt nhóm này làm PHÒNG ĐIỀU PHỐI.\nBot Điều phối sẽ giao việc ở đây, gọi tên từng "
                            "bot bộ phận. Nhớ thêm Bot Sale, Kế toán, Kho, Kỹ thuật vào nhóm.\n"
                            "Việc quá hạn và sự cố: từng bot nhắn RIÊNG cho anh.")
                return reply + "\n" + (f"📌 Chat này là nhóm {dept_icon(dept)} {dept_name(dept)}: chỉ nhận việc của "
                                       "bộ phận này." if dept != TONG else
                                       "📌 Chat TỔNG: nhận mọi tin và báo cáo tổng hợp.")
            elif self.store.is_subscribed(chat_id):
                return "✅ Chat này đã được kết nối. Gõ /help để xem lệnh."
            return reply
        if not self.store.is_subscribed(chat_id) and not in_room:  # bot bộ phận trong phòng điều phối: tự nhận lệnh
            return pairing_reply("/batdau", self.pair_code)[1]
        cmd = parse_command(text)
        # --- Họp: "họp công ty", "họp bộ phận kho", "/hop", "/hop kho" ---
        meeting = None if cmd else parse_meeting(text, default_dept=bot_dept)
        if meeting:
            return self.run_meeting(meeting[0], meeting[1], chat_id)
        # --- Hỏi riêng bộ phận: "Kho ơi, …", "@VHKhoBot …", trả lời (reply) tin của 1 bot ---
        if not cmd and not parse_order(text):
            addressed = parse_address(text, self.usernames)
            if not addressed and reply_to:
                addressed = (reply_to, text)
            if not addressed and not raw_chat.startswith("-"):
                addressed = (botname, text)  # chat riêng với bot: câu thường = hỏi chính bot đó
            if addressed:
                return self.answer(addressed[0], addressed[1], raw_chat)
        if bot_dept:  # bot bộ phận: chỉ nhận lệnh riêng của bộ phận
            if cmd and cmd.name == "help":
                return dept_help(bot_dept)
            if cmd and cmd.name not in ALLOWED[bot_dept]:
                return not_allowed(bot_dept, cmd.name)
            if not cmd and botname not in FREE_TEXT_ORDERS:
                return "Gõ /help để xem các lệnh của bot này."
        if cmd and cmd.name == "dangky":
            return "Chat này đã được kết nối rồi."
        if cmd and cmd.name == "huydangky":
            self.store.subscribe(chat_id, sender, False)
            return "🔕 Đã ngắt kết nối. Gõ /batdau <mã> để kết nối lại."
        if cmd and cmd.name == "chuatraloi":
            return self.unanswered_text()
        my_dept = bot_dept or self.store.chat_dept(chat_id)
        if cmd and cmd.name == "choxuly":
            with self.lock:
                return report_leads(self.store, dept=None if my_dept in (TONG, ROOM) else my_dept)
        if cmd and cmd.name == "bophan" and bot_dept:
            return f"📌 Đây là {icon} {title}: chỉ báo và nhận việc của bộ phận {dept_name(bot_dept)}."
        if cmd and cmd.name == "bophan":
            return (f"📌 Chat này: {dept_icon(my_dept)} {dept_name(my_dept)}.\n"
                    f"Đổi bộ phận: /batdau <mã> <bộ phận>. Các bộ phận: {dept_list()}, tong (nhận tất cả).")
        with self.lock:
            reply = handle_message(self.store, text, f"tg:{chat_id}", sender)
        if cmd and cmd.name == "chuyen" and reply and reply.startswith("↪️"):
            lead = self.store.get_lead(int(re.sub(r"\D", "", cmd.args.split()[0])))
            body = f"↪️ Việc chuyển sang {dept_icon(lead['kind'])} {dept_name(lead['kind'])}:\n" + lead_line(lead, datetime.now())
            if self.room_key():
                self.assign_in_room(body, lead["kind"], lead["id"])
            else:
                self.send_report(body, lead["kind"])
        return reply or "Gõ /help để xem các lệnh."

    def telegram_loop(self, botname: str = DIEUPHOI):
        tg = self.bots[botname]
        setting = "tg_offset" if botname == DIEUPHOI else f"tg_offset_{botname}"
        offset = int(self.store.get_setting(setting, "0") or 0)
        while True:
            try:
                for upd in tg.get_updates(offset):
                    offset = max(offset, int(upd["update_id"]) + 1)
                    self.store.set_setting(setting, str(offset))
                    msg = upd.get("message") or {}
                    chat = msg.get("chat") or {}
                    sender = (msg.get("from") or {}).get("first_name", "")
                    if not chat.get("id") or (msg.get("from") or {}).get("is_bot"):
                        continue
                    replied = ((msg.get("reply_to_message") or {}).get("from") or {}).get("username", "")
                    reply_to = next((n for n, u in self.usernames.items() if u and u.lower() == replied.lower()), None)
                    if not self.should_handle(botname, str(chat["id"]), msg.get("text", ""), reply_to):
                        continue
                    reply = self.handle_telegram(chat["id"], msg.get("text", ""), sender, botname, reply_to)
                    if reply:
                        tg.send(str(chat["id"]), reply)
            except Exception:  # noqa: BLE001
                log.exception("Lỗi %s, thử lại sau 5 giây", BOT_NAMES[botname][1])
                time.sleep(5)

    # ---------- báo cáo định kỳ ----------
    def scheduler(self, times: list[str], remind_minutes: int = 30):
        sent = set()
        while True:
            now = datetime.now()
            try:
                self.remind_pending(remind_minutes, now)
                self.check_unanswered()
            except Exception:  # noqa: BLE001
                log.exception("Nhắc tin khách thất bại")
            tag = f"{now.date()} {now:%H:%M}"
            if self.meeting_time and f"{now:%H:%M}" == self.meeting_time and f"hop {tag}" not in sent:
                sent.add(f"hop {tag}")
                try:
                    self.auto_meeting(now)
                except Exception:  # noqa: BLE001
                    log.exception("Họp tự động thất bại")
            if f"{now:%H:%M}" in times and tag not in sent:
                sent.add(tag)
                try:
                    self.send_daily(now)
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
    if bot.tg:
        print("2. Các bot Telegram:")
        rows = bot.store.subscribed_rows()
        for name in [DIEUPHOI, *DEPTS]:
            icon, title = BOT_NAMES[name]
            if name not in bot.bots:
                print(f"   {icon} {title}: chưa tạo – Bot Điều phối báo thay")
                continue
            try:
                user = "@" + bot.bots[name].get_me().get("username", "?")
            except Exception as e:  # noqa: BLE001
                user, ok = f"LỖI token ({e})", False
            n = sum(1 for k, _ in rows if k.startswith(f"{name}:"))
            print(f"   {icon} {title}: {user} – {n} chat đã kết nối"
                  + ("" if n else f" (mở bot, gõ /batdau {bot.pair_code or '<mã>'})"))
        if not any(k.startswith(f"{DIEUPHOI}:") and d == TONG for k, d in rows):
            print("3. CHƯA có chat tổng: mở Bot Điều phối, gõ /batdau <mã> để nhận báo cáo tổng.")
            ok = False
        else:
            print("3. Chat tổng: có")
        report, groups = True, []
    else:
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
                 scan_groups=os.environ.get("SCAN_GROUPS", "0") == "1",
                 telegram=Telegram(os.environ["TELEGRAM_BOT_TOKEN"]) if os.environ.get("TELEGRAM_BOT_TOKEN") else None,
                 pair_code=os.environ.get("PAIR_CODE", ""),
                 dept_bots={d: Telegram(os.environ[f"TELEGRAM_TOKEN_{d.upper()}"]) for d in DEPTS
                            if os.environ.get(f"TELEGRAM_TOKEN_{d.upper()}")})
    if "--check" in sys.argv:
        raise SystemExit(check(bot, os.environ.get("ZALOCRM_WEBHOOK_SECRET", "")))
    if "--send-report" in sys.argv:  # gửi báo cáo ngay rồi thoát (nút trên GitHub Actions)
        if not bot.send_report(full_report(store)):
            raise SystemExit("Chưa gửi được: chưa có chat Telegram nào ghép nối "
                             "(hoặc chưa tìm thấy nhóm Zalo báo đơn). Xem: python -m bot.crm_main --check")
        return
    times = [t.strip() for t in os.environ.get("REPORT_TIMES", "08:00,17:00").split(",") if t.strip()]
    remind = int(os.environ.get("REMIND_MINUTES", "30"))
    bot.remind_minutes = remind
    bot.shop_names = {norm(n) for n in os.environ.get("SHOP_NAMES", "").split(",") if n.strip()}
    bot.shop_uids = {u.strip() for u in os.environ.get("SHOP_UIDS", "").split(",") if u.strip()}
    bot.reply_minutes = int(os.environ.get("REPLY_MINUTES", "15"))
    bot.work_hours = os.environ.get("WORK_HOURS", "07:00-21:00").strip()
    bot.meeting_time = os.environ.get("MEETING_TIME", "18:00").strip()  # để trống = tắt họp tự động
    threading.Thread(target=bot.scheduler, args=(times, remind), daemon=True).start()
    bot.load_usernames()
    for name in bot.bots:
        threading.Thread(target=bot.telegram_loop, args=(name,), daemon=True).start()
    if bot.bots:
        log.info("Chế độ Telegram: chỉ đọc tin Zalo. Bot đang chạy: %s",
                 ", ".join(BOT_NAMES[n][1] for n in bot.bots))
    poll = int(os.environ.get("POLL_SECONDS", "15"))
    if poll > 0:
        threading.Thread(target=bot.poller, args=(poll,), daemon=True).start()
    serve(bot, int(os.environ.get("PORT", "8090")), os.environ.get("ZALOCRM_WEBHOOK_SECRET", ""))


if __name__ == "__main__":
    main()
