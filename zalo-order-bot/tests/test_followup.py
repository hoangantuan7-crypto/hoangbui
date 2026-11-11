import unittest
from datetime import datetime, timedelta, timezone

from bot.crm_main import CRMBot
from bot.db import Store
from bot.followup import dissatisfied, in_work_hours, needs_reply
from bot.meeting import build_meeting
from tests_helpers import FakeCRM
from test_room import BOSS, FakeTG

T0 = datetime(2026, 11, 12, 2, 0, tzinfo=timezone.utc)  # 09:00 giờ VN


def zmsg(i, conv, text, minutes, sender="Anh Nam", sender_type="contact", ctype="text"):
    """Tin như bot lấy từ API ZaloCRM: ZaloCRM có thể ghi nhầm tin shop gửi từ điện thoại là 'contact'."""
    at = (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
    return {"source": "hỏi định kỳ", "event": "message.sent" if sender_type == "self" else "message.received",
            "data": {"messageId": f"m{i}", "conversationId": conv, "content": text, "contentType": ctype,
                     "senderName": sender, "sentAt": at}}


class TextRulesTest(unittest.TestCase):
    def test_rules(self):
        for t in ["ok em", "Ok anh nhé", "cảm ơn anh nhiều ạ", "Dạ vâng ạ", "👍"]:
            self.assertFalse(needs_reply(t), t)
        for t in ["tủ 80 có màu xám không anh?", "anh báo giá giúp em", "ok nhưng còn màu trắng không"]:
            self.assertTrue(needs_reply(t), t)
        for t in ["???", "không phải, ý em là tủ treo", "em hỏi cái tủ 60 mà", "anh chưa trả lời câu em hỏi"]:
            self.assertTrue(dissatisfied(t), t)
        self.assertFalse(dissatisfied("tủ 80 có màu xám không anh?"))
        self.assertTrue(in_work_hours(datetime(2026, 1, 1, 9, 0), "07:00-21:00"))
        self.assertFalse(in_work_hours(datetime(2026, 1, 1, 22, 30), "07:00-21:00"))


class FollowupTest(unittest.TestCase):
    def setUp(self):
        self.crm, self.dp = FakeCRM(), FakeTG("VHDieuPhoiBot")
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913")
        self.bot.shop_names = {"viet hoang noi that"}
        self.bot.handle_telegram(BOSS, "/batdau 482913")
        self.dp.sent.clear()
        self.nine = datetime(2026, 11, 12, 9, 0)

    def check(self, minutes):
        return self.bot.check_unanswered(T0 + timedelta(minutes=minutes), self.nine)

    def test_unanswered_customer_is_reminded_twice_then_stops(self):
        self.bot.handle_event(zmsg(1, "c-nam", "tủ 80 có màu xám không anh?", 0))
        self.assertFalse(self.check(10))                       # mới 10 phút: chưa nhắc
        self.assertTrue(self.check(16))                        # quá 15 phút: nhắc lần 1
        self.assertIn("1 KHÁCH ĐANG CHỜ ANH TRẢ LỜI", self.dp.to(BOSS)[-1])
        self.assertIn("Anh Nam (0912345678) – chờ 16 phút", self.dp.to(BOSS)[-1])
        self.assertFalse(self.check(30))                       # không nhắc lặp
        self.assertTrue(self.check(61))                        # quá 1 giờ: nhắc lần 2
        self.assertIn("NHẮC LẦN 2", self.dp.to(BOSS)[-1])
        self.assertFalse(self.check(300))

    def test_shop_reply_misrecorded_as_customer_still_counts_as_reply(self):
        self.bot.handle_event(zmsg(1, "c-nam", "anh báo giá giúp em tủ 80", 0))
        # anh trả lời bằng điện thoại, ZaloCRM ghi nhầm là 'contact' nhưng tên người gửi là nick shop
        self.bot.handle_event(zmsg(2, "c-nam", "dạ chiều mai bên em giao hàng ạ", 5, sender="Việt Hoàng Nội Thất"))
        self.assertFalse(self.check(20))
        self.assertIn("Không có khách nào", self.bot.handle_telegram(BOSS, "/chuatraloi"))
        # và câu trả lời của shop KHÔNG bị báo nhầm thành việc "giao hàng" của Kho
        self.assertNotIn("KHO", " ".join(self.dp.to(BOSS)))

    def test_read_but_forgot_to_reply(self):
        self.bot.handle_event(zmsg(1, "c-nam", "em muốn đặt 2 tủ lavabo 80", 0))
        self.bot.handle_event(zmsg(2, "c-nam", "anh ơi còn không ạ", 3))   # khách nhắn thêm: gộp, giữ giờ chờ
        self.assertTrue(self.check(16))
        text = self.dp.to(BOSS)[-1]
        self.assertIn("chờ 16 phút", text)
        self.assertIn("còn không", text)

    def test_closing_words_do_not_need_reply(self):
        self.bot.handle_event(zmsg(1, "c-nam", "tủ 80 giá bao nhiêu anh", 0))
        self.bot.handle_event(zmsg(2, "c-nam", "dạ 5 triệu ạ", 2, sender="Việt Hoàng Nội Thất"))
        self.bot.handle_event(zmsg(3, "c-nam", "ok anh nhé", 4))
        self.bot.handle_event(zmsg(4, "c-nam", "sticker", 5, ctype="sticker"))
        self.assertFalse(self.check(60))

    def test_wrong_answer_is_flagged_immediately(self):
        self.bot.handle_event(zmsg(1, "c-nam", "tủ treo 60 còn màu trắng không anh", 0))
        self.bot.handle_event(zmsg(2, "c-nam", "dạ tủ đặt sàn 60 còn ạ", 2, sender="Việt Hoàng Nội Thất"))
        self.bot.handle_event(zmsg(3, "c-nam", "không phải, ý em là tủ treo cơ", 3))
        self.assertIn("CHƯA ĐƯỢC GIẢI ĐÁP ĐÚNG", self.dp.to(BOSS)[-1])
        self.assertIn("ý em là tủ treo", self.dp.to(BOSS)[-1])
        self.assertTrue(self.check(20))  # và vẫn đang chờ anh trả lời lại

    def test_no_reminder_outside_work_hours(self):
        self.bot.handle_event(zmsg(1, "c-nam", "anh ơi báo giá giúp em", 0))
        self.assertFalse(self.bot.check_unanswered(T0 + timedelta(minutes=30), datetime(2026, 11, 12, 22, 0)))
        self.assertTrue(self.bot.check_unanswered(T0 + timedelta(minutes=600), datetime(2026, 11, 13, 7, 5)))

    def test_meeting_mentions_waiting_customers(self):
        two_hours_ago = (datetime.now(timezone.utc) - T0).total_seconds() / 60 - 120
        self.bot.handle_event(zmsg(1, "c-nam", "anh ơi báo giá giúp em", two_hours_ago))
        msgs = build_meeting(self.bot.store, "congty", None, datetime.now())
        self.assertIn("Đang có 1 khách chờ anh trả lời", msgs[0][1])
        self.assertIn("Anh Nam chờ anh trả lời", msgs[-1][1])

    def test_groups_are_not_tracked_by_default(self):
        self.bot.handle_event(zmsg(1, "c-group", "mọi người ơi chiều nay họp", 0))
        self.assertFalse(self.check(60))


if __name__ == "__main__":
    unittest.main()
