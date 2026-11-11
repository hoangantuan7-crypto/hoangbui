import unittest
from datetime import datetime, timedelta

from bot.crm_main import CRMBot
from bot.db import Store
from tests_helpers import FakeCRM, msg


class FakeTG:
    def __init__(self, username, fail_group=False):
        self.username, self.sent, self.fail_group = username, [], fail_group

    def send(self, chat_id, text):
        if self.fail_group and str(chat_id).startswith("-"):
            raise RuntimeError("Forbidden: bot is not a member of the group chat")
        self.sent.append((str(chat_id), text))

    def get_me(self):
        return {"username": self.username}

    def to(self, chat_id):
        return [t for c, t in self.sent if c == chat_id]


ROOM, BOSS = "-100500", "777"


class RoomTest(unittest.TestCase):
    """Phòng điều phối: nhóm có anh + 5 bot. Bot Điều phối gọi tên giao việc; vấn đề thì nhắn riêng anh."""

    def setUp(self, kho_fails=False):
        self.crm = FakeCRM()
        self.dp = FakeTG("VHDieuPhoiBot")
        self.d = {"sale": FakeTG("VHSaleBot"), "ketoan": FakeTG("VHKeToanBot"),
                  "kho": FakeTG("VHKhoBot", fail_group=kho_fails), "kythuat": FakeTG("VHKyThuatBot")}
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913", dept_bots=self.d)
        self.bot.load_usernames()
        h = self.bot.handle_telegram
        h(BOSS, "/batdau 482913")                                  # chat riêng anh – Bot Điều phối
        for name in self.d:
            h(BOSS, "/batdau 482913", botname=name)                # chat riêng anh – từng bot bộ phận
        self.assertIn("PHÒNG ĐIỀU PHỐI", h(ROOM, "/batdau 482913 phong"))
        for t in [self.dp, *self.d.values()]:
            t.sent.clear()

    def test_dispatcher_calls_bot_by_name_and_bot_confirms_in_room(self):
        self.bot.handle_event(msg("message.received", "c-nam", "Vòi sen bị hỏng rồi em ơi, còn bảo hành không"))
        call = self.dp.to(ROOM)
        self.assertEqual(len(call), 1)
        self.assertIn("Giao việc K1 cho 🔧 @VHKyThuatBot", call[0])
        self.assertIn("Anh Nam", call[0])
        self.assertIn("Đã nhận việc K1", self.d["kythuat"].to(ROOM)[0])
        # công việc bình thường: không làm phiền chat riêng của anh
        self.assertEqual(self.dp.to(BOSS), [])
        self.assertEqual(self.d["kythuat"].to(BOSS), [])
        self.assertEqual(self.crm.sent, [])

    def test_overdue_work_is_messaged_privately_by_the_responsible_bot(self):
        self.bot.handle_event(msg("message.received", "c-nam", "Em chuyển khoản rồi nhé"))
        self.bot.remind_pending(30, datetime.now() + timedelta(minutes=31))
        self.assertIn("KẾ TOÁN: CÒN 1 TIN", self.d["ketoan"].to(BOSS)[0])  # Bot Kế toán nhắn riêng anh
        self.assertEqual(len(self.dp.to(ROOM)), 1)  # phòng chỉ có lần giao việc, không có tin nhắc

    def test_dispatcher_reports_zalo_problems_privately_once(self):
        def boom():
            raise OSError("ZaloCRM không chạy")
        real = self.bot.poll_once
        self.bot.poll_once = boom
        for _ in range(5):  # 5 vòng hỏi lỗi liên tiếp -> chỉ nhắn 1 lần
            self.bot.poll_tick()
        self.assertEqual(len(self.dp.to(BOSS)), 1)
        self.assertIn("không đọc được tin Zalo", self.dp.to(BOSS)[0])
        self.bot.poll_once = real  # ZaloCRM chạy lại
        self.bot.poll_tick()
        self.assertIn("đã đọc lại được", self.dp.to(BOSS)[-1])
        self.assertEqual(self.dp.to(ROOM), [])

    def test_bot_not_in_room_tells_boss_privately(self):
        self.setUp(kho_fails=True)
        self.bot.handle_event(msg("message.received", "c-nam", "Bao giờ giao hàng cho anh"))
        self.assertIn("Giao việc K1 cho 📦 @VHKhoBot", self.dp.to(ROOM)[0])
        self.assertIn("Bot Kho không nhắn được vào phòng", self.dp.to(BOSS)[0])

    def test_only_one_bot_answers_each_command_in_room(self):
        sh = self.bot.should_handle
        self.assertTrue(sh("dieuphoi", ROOM, "/choxuly"))
        self.assertFalse(sh("kho", ROOM, "/choxuly"))
        self.assertTrue(sh("kho", ROOM, "/thieu@VHKhoBot"))
        self.assertFalse(sh("dieuphoi", ROOM, "/thieu@VHKhoBot"))
        self.assertFalse(sh("sale", ROOM, "/thieu@VHKhoBot"))
        self.assertTrue(sh("kho", BOSS, "/thieu"))  # chat riêng: bot luôn trả lời
        self.assertTrue(sh("dieuphoi", ROOM, "/batdau@VHDieuPhoiBot 482913 phong"))
        self.assertFalse(sh("dieuphoi", ROOM, "ok mọi người, chiều nay họp nhé"))  # không trả lời tin thường
        self.assertTrue(sh("dieuphoi", ROOM, "Đơn chị Lan: 1 tủ lavabo 60cm"))
        self.assertIn("PHÒNG ĐIỀU PHỐI", self.bot.handle_telegram("-100999", "/batdau@VHDieuPhoiBot 482913 phong"))

    def test_room_commands(self):
        self.bot.handle_event(msg("message.received", "c-nam", "Bao giờ giao hàng cho anh"))  # Kho, K1
        self.assertIn("Kho (1)", self.bot.handle_telegram(ROOM, "/choxuly"))
        self.assertIn("Đã chuyển K1", self.bot.handle_telegram(ROOM, "/chuyen K1 kythuat"))
        self.assertIn("Giao việc K1 cho 🔧 @VHKyThuatBot", self.dp.to(ROOM)[-1])
        self.assertIn("Đã xử lý tin K1", self.bot.handle_telegram(ROOM, "/xong K1"))


if __name__ == "__main__":
    unittest.main()
