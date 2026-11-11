import unittest

from bot.crm_main import CRMBot
from bot.db import Store
from bot.telegram import split_text
from tests_helpers import CONVS, FakeCRM, msg


class FakeTG:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


class TelegramModeTest(unittest.TestCase):
    def setUp(self):
        self.crm, self.tg = FakeCRM(), FakeTG()
        self.bot = CRMBot(Store(":memory:"), self.crm, "Bot đơn hàng", "acc-1", telegram=self.tg, pair_code="482913")

    def test_pairing_is_required(self):
        self.assertIn("Bot riêng", self.bot.handle_telegram("111", "/choxuly"))
        self.assertIn("Bot riêng", self.bot.handle_telegram("111", "/batdau 000000"))
        self.assertIn("Đã kết nối", self.bot.handle_telegram("111", "/batdau 482913"))
        self.assertIn("Không có tin khách", self.bot.handle_telegram("111", "/choxuly"))
        self.assertIn("Đã kết nối", self.bot.handle_telegram("222", "/start@ShopBot 482913"))
        self.assertIn("ngắt kết nối", self.bot.handle_telegram("222", "/huydangky"))
        self.assertIn("Bot riêng", self.bot.handle_telegram("222", "/thieu"))

    def test_customer_order_goes_to_telegram_never_to_zalo(self):
        self.bot.handle_telegram("111", "/batdau 482913")
        self.bot.handle_event(msg("message.received", "c-nam", "Anh ơi lấy em 2 tủ lavabo 80cm nhé"))
        self.assertEqual(self.crm.sent, [])  # không gửi gì qua Zalo
        self.assertEqual(len(self.tg.sent), 1)
        chat, text = self.tg.sent[0]
        self.assertEqual(chat, "111")
        self.assertIn("KHÁCH ĐẶT HÀNG", text)
        self.assertIn("Anh Nam (0912345678)", text)
        # đánh dấu xong ngay trong Telegram
        self.assertIn("Đã xử lý tin K1", self.bot.handle_telegram("111", "/xong K1"))

    def test_zalo_commands_are_ignored_in_telegram_mode(self):
        self.bot.handle_telegram("111", "/batdau 482913")
        self.bot.handle_event(msg("message.received", "c-group", "/baocao"))
        self.assertEqual(self.crm.sent, [])
        self.assertEqual(self.tg.sent, [])

    def test_order_and_report_from_telegram(self):
        self.bot.handle_telegram("111", "/batdau 482913")
        self.assertIn("Đã ghi đơn #1", self.bot.handle_telegram("111", "Đơn chị Lan: 1 tủ lavabo 60cm"))
        self.assertIn("chị Lan", self.bot.handle_telegram("111", "/lavabo"))
        self.assertTrue(self.bot.send_report("báo cáo"))
        self.assertEqual(self.tg.sent[-1], ("111", "báo cáo"))

    def test_split_text(self):
        self.assertTrue(all(len(c) <= 4000 for c in split_text("x" * 9000)))


if __name__ == "__main__":
    unittest.main()
