import unittest
from datetime import datetime, timedelta

from bot.ai_assistant import dept_snapshot, parse_address
from bot.crm_main import CRMBot
from bot.db import Store
from bot.meeting import build_meeting, parse_meeting
from tests_helpers import FakeCRM, msg
from test_room import BOSS, ROOM, FakeTG


class ParseTest(unittest.TestCase):
    def test_meeting_phrases(self):
        cases = {
            "họp công ty": ("congty", None), "Họp toàn bộ nhé": ("congty", None), "/hop": ("congty", None),
            "họp bộ phận kho": ("bophan", "kho"), "họp sale": ("bophan", "sale"), "/hop kho": ("bophan", "kho"),
            "/hop@VHDieuPhoiBot ke toan": ("bophan", "ketoan"), "họp kỹ thuật ngay": ("bophan", "kythuat"),
            "mở cuộc họp giao ban": ("congty", None),
            "hộp gỗ tủ lavabo 80 còn không": None, "Kho ơi tủ anh Nam đến đâu rồi": None,
            "họp xong rồi mọi người về đi ăn cơm thôi": None,
        }
        for text, want in cases.items():
            self.assertEqual(parse_meeting(text), want, text)
        self.assertEqual(parse_meeting("họp", default_dept="kho"), ("bophan", "kho"))

    def test_address(self):
        u = {"kho": "VHKhoBot"}
        self.assertEqual(parse_address("Kho ơi, tủ của anh Nam đến đâu rồi?", u), ("kho", "tủ của anh Nam đến đâu rồi?"))
        self.assertEqual(parse_address("Kế toán ơi hôm nay ai chuyển khoản", u)[0], "ketoan")
        self.assertEqual(parse_address("@VHKhoBot còn bao nhiêu vòi sen", u), ("kho", "còn bao nhiêu vòi sen"))
        self.assertEqual(parse_address("Bot kỹ thuật: lịch lắp tuần này", u)[0], "kythuat")
        self.assertIsNone(parse_address("kho hàng hôm nay nhiều quá", u))
        self.assertIsNone(parse_address("sale off cuối tuần nhé", u))


class MeetingTest(unittest.TestCase):
    def setUp(self):
        self.crm = FakeCRM()
        self.dp = FakeTG("VHDieuPhoiBot")
        self.d = {"sale": FakeTG("VHSaleBot"), "ketoan": FakeTG("VHKeToanBot"),
                  "kho": FakeTG("VHKhoBot"), "kythuat": FakeTG("VHKyThuatBot")}
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913", dept_bots=self.d)
        self.bot.load_usernames()
        self.asked = []
        self.bot.ask = lambda bot, q, store: (self.asked.append((bot, q)), f"[{bot}] trả lời: {q}")[1]
        h = self.bot.handle_telegram
        h(BOSS, "/batdau 482913")
        for name in self.d:
            h(BOSS, "/batdau 482913", botname=name)
        h(ROOM, "/batdau 482913 phong")
        for t in [self.dp, *self.d.values()]:
            t.sent.clear()
        # dữ liệu: 1 việc kỹ thuật cũ (quá hạn), 1 việc kế toán đã xong, 1 đơn thiếu hàng
        self.bot.handle_event(msg("message.received", "c-nam", "Vòi sen bị hỏng rồi em ơi"))
        self.bot.store.conn.execute("UPDATE leads SET created_at=?",
                                    ((datetime.now() - timedelta(hours=2)).replace(microsecond=0).isoformat(),))
        self.bot.handle_event(msg("message.received", "c-nam", "Em chuyển khoản rồi nhé"))
        self.bot.store.close_leads(2)
        self.bot.store.add_order("Chị Lan", [("vòi sen", 3)])
        for t in [self.dp, *self.d.values()]:
            t.sent.clear()

    def test_company_meeting_in_room_each_bot_speaks(self):
        self.assertIsNone(self.bot.handle_telegram(ROOM, "Họp công ty nhé"))
        self.assertIn("Bắt đầu HỌP CÔNG TY", self.dp.to(ROOM)[0])
        self.assertIn("Quá hạn 1", self.d["kythuat"].to(ROOM)[0])
        self.assertIn("Xong 1", self.d["ketoan"].to(ROOM)[0])
        self.assertIn("Thiếu hàng: 1 khách", self.d["kho"].to(ROOM)[0])
        self.assertEqual(len(self.d["sale"].to(ROOM)), 1)
        closing = self.dp.to(ROOM)[-1]
        self.assertIn("CẦN ANH QUYẾT", closing)
        self.assertIn("K1", closing)
        self.assertIn("vòi sen thiếu 3", closing)

    def test_department_meeting_detail(self):
        self.bot.handle_telegram(ROOM, "/hop kythuat")
        report = self.d["kythuat"].to(ROOM)[0]
        self.assertIn("Việc đang chờ", report)
        self.assertIn("K1 Anh Nam", report)
        self.assertEqual(self.d["kho"].to(ROOM), [])  # họp bộ phận: bot khác không phát biểu

    def test_meeting_in_private_chat_is_one_message(self):
        text = self.bot.handle_telegram(BOSS, "họp", botname="kho")
        self.assertIn("HỌP BỘ PHẬN KHO", text)
        self.assertIn("Bot Kho", text)

    def test_auto_meeting_at_1800(self):
        self.bot.auto_meeting(datetime.now())
        self.assertIn("HỌP CÔNG TY tự động", self.dp.to(ROOM)[0])

    def test_ask_department_in_room_answered_by_that_bot(self):
        self.assertIsNone(self.bot.handle_telegram(ROOM, "Kho ơi, tủ của anh Nam đến đâu rồi?"))
        self.assertEqual(self.asked[-1], ("kho", "tủ của anh Nam đến đâu rồi?"))
        self.assertIn("[kho] trả lời", self.d["kho"].to(ROOM)[0])

    def test_reply_to_bot_message_asks_that_bot(self):
        self.bot.handle_telegram(ROOM, "còn mấy cái nữa?", reply_to="ketoan")
        self.assertEqual(self.asked[-1][0], "ketoan")
        self.assertTrue(self.bot.should_handle("dieuphoi", ROOM, "còn mấy cái nữa?", reply_to="ketoan"))

    def test_private_free_text_asks_that_bot(self):
        reply = self.bot.handle_telegram(BOSS, "hôm nay có ai chuyển khoản không", botname="ketoan")
        self.assertEqual(reply, "[ketoan] trả lời: hôm nay có ai chuyển khoản không")
        reply = self.bot.handle_telegram(BOSS, "hôm nay thế nào em")
        self.assertEqual(self.asked[-1][0], "dieuphoi")

    def test_room_chatter_still_ignored(self):
        self.assertFalse(self.bot.should_handle("dieuphoi", ROOM, "chiều nay mưa to quá"))
        self.assertTrue(self.bot.should_handle("dieuphoi", ROOM, "họp công ty"))
        self.assertTrue(self.bot.should_handle("dieuphoi", ROOM, "Kho ơi còn vòi sen không"))
        self.assertFalse(self.bot.should_handle("kho", ROOM, "Kho ơi còn vòi sen không"))  # Điều phối chuyển lời

    def test_snapshot_contains_real_data(self):
        snap = dept_snapshot(self.bot.store, "kho")
        self.assertIn("Chị Lan", snap)
        self.assertIn("vòi sen", snap)
        self.assertNotIn("KẾ TOÁN", dept_snapshot(self.bot.store, "kythuat").upper().split("BOT ")[0])

    def test_meeting_without_any_work(self):
        msgs = build_meeting(Store(":memory:"), "congty", None, datetime.now())
        self.assertIn("Không có việc nào cần anh quyết", msgs[-1][1])
        self.assertIn("không tồn việc", msgs[1][1])


if __name__ == "__main__":
    unittest.main()
