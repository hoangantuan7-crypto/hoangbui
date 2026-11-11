import unittest
from datetime import datetime, timedelta, timezone

from bot.crm_main import CRMBot
from bot.db import Store
from tests_helpers import CONVS, FakeCRM
from test_room import BOSS, FakeTG


def ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat().replace("+00:00", "Z")


def m(i, text, when, sender="Anh Nam", stype="contact", ctype="text"):
    return {"id": f"h{i}", "senderType": stype, "senderName": sender, "content": text,
            "contentType": ctype, "sentAt": when}


class HistoryTest(unittest.TestCase):
    def setUp(self):
        CONVS["c-lan"] = {"id": "c-lan", "threadType": "user", "externalThreadId": "u2",
                          "contact": {"fullName": "Chị Lan", "phone": "0988"}}
        CONVS["c-me"] = {"id": "c-me", "threadType": "user", "externalThreadId": "u3",
                         "contact": {"fullName": "Mẹ", "phone": ""}}
        CONVS["c-old"] = {"id": "c-old", "threadType": "user", "externalThreadId": "u4",
                          "contact": {"fullName": "Khách cũ", "phone": ""}}
        self.crm, self.dp = FakeCRM(), FakeTG("VHDieuPhoiBot")
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913",
                          scan_groups="1")
        self.bot.shop_names = {"viet hoang noi that"}
        self.bot.staff_env = {"phat"}
        self.bot.handle_telegram(BOSS, "/batdau 482913")
        self.dp.sent.clear()
        # Anh Nam: hỏi đặt hàng 2 ngày trước, chưa ai trả lời -> bị bỏ quên
        self.crm.msgs["c-nam"] = [m(1, "anh ơi lấy em 2 tủ lavabo 80 nhé", ago(days=2)),
                                  m(2, "còn không anh", ago(days=2, minutes=-5))]
        # Chị Lan: hỏi, nhân viên Phát đã trả lời (ZaloCRM ghi nhầm là contact) -> không sót
        self.crm.msgs["c-lan"] = [m(3, "gương 60 giá bao nhiêu", ago(days=1), sender="Chị Lan"),
                                  m(4, "dạ 1tr2 chị ạ", ago(hours=23), sender="Phát")]
        # Mẹ: chat gia đình -> sẽ /boqua
        self.crm.msgs["c-me"] = [m(5, "con ơi mua giúp mẹ 2 cái vòi sen nhé", ago(hours=5), sender="Mẹ")]
        # Khách cũ: quá 7 ngày -> không quét
        self.crm.msgs["c-old"] = [m(6, "lấy 1 tủ 60", ago(days=10), sender="Khách cũ")]
        for c, msgs in self.crm.msgs.items():
            CONVS[c]["lastMessageAt"] = max(x["sentAt"] for x in msgs)

    def tearDown(self):
        for c in ("c-lan", "c-me", "c-old"):
            CONVS.pop(c)
        CONVS["c-nam"].pop("lastMessageAt", None)

    def test_scan_finds_forgotten_customers_and_missed_orders(self):
        self.bot.handle_telegram(BOSS, "/boqua Mẹ")
        text = self.bot.scan_history(7)
        self.assertIn("1 KHÁCH CHƯA ĐƯỢC TRẢ LỜI", text)
        self.assertIn("Anh Nam", text)
        self.assertNotIn("Chị Lan", text.split("Đã tạo")[0])   # nhân viên đã trả lời
        self.assertNotIn("Mẹ", text.split("Chat gia đình")[0])  # đã bỏ qua
        self.assertNotIn("Khách cũ", text)                      # ngoài 7 ngày
        self.assertIn("Đã tạo 1 việc bị sót: 🛒 Sale 1", text)
        self.assertIn("SALE (1)", self.bot.handle_telegram(BOSS, "/choxuly").upper())
        self.assertIn("Anh Nam", self.bot.handle_telegram(BOSS, "/chuatraloi"))

    def test_scan_does_not_flood_reminders_afterwards(self):
        self.bot.scan_history(7)
        self.dp.sent.clear()
        self.bot.remind_pending(30)                        # việc cũ đã được tổng hợp: không nhắc ngay lại
        self.assertFalse(self.bot.check_unanswered(local=datetime(2026, 1, 1, 9, 0)))  # chưa tới mốc 1 giờ lần 2
        self.assertEqual(self.dp.sent, [])

    def test_scanned_messages_are_not_processed_again_live(self):
        self.bot.scan_history(7)
        self.dp.sent.clear()
        self.bot.handle_event({"source": "hỏi định kỳ", "event": "message.received",
                               "data": {"messageId": "h1", "conversationId": "c-nam",
                                        "content": "anh ơi lấy em 2 tủ lavabo 80 nhé", "contentType": "text"}})
        self.assertEqual(self.dp.sent, [])

    def test_telegram_command_runs_in_background_and_replies(self):
        reply = self.bot.handle_telegram(BOSS, "/quetlai 7")
        self.assertIn("Đang quét lại tin 7 ngày", reply)
        import time
        for _ in range(50):
            if self.dp.to(BOSS):
                break
            time.sleep(0.05)
        self.assertIn("QUÉT LẠI 7 NGÀY", self.dp.to(BOSS)[-1])

    def test_boqua_command(self):
        h = self.bot.handle_telegram
        self.assertIn("• Cả nhà Yêu", h(BOSS, "/boqua Cả nhà Yêu, Mẹ"))
        self.assertTrue(self.bot.is_muted_name("Bố (nhóm Cả nhà Yêu)"))
        self.assertIn("• Mẹ", h(BOSS, "/boqua"))
        self.assertNotIn("• Mẹ", h(BOSS, "/boqua xoa Mẹ"))
        self.assertFalse(self.bot.is_muted_name("Mẹ"))

    def test_muted_chat_gets_no_live_alert(self):
        self.bot.handle_telegram(BOSS, "/boqua Mẹ")
        self.dp.sent.clear()
        self.bot.handle_event({"source": "hỏi định kỳ", "event": "message.received",
                               "data": {"messageId": "x1", "conversationId": "c-me", "senderName": "Mẹ",
                                        "content": "con ơi mua giúp mẹ 2 cái vòi sen nhé", "contentType": "text"}})
        self.assertEqual(self.dp.sent, [])


if __name__ == "__main__":
    unittest.main()
