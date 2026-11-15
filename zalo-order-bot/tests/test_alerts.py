import unittest

from bot.crm_main import CRMBot
from bot.db import Store
from bot.parser import parse_command
from bot.telegram import DO, VANG, XANH, Telegram, alert_level, format_alert
from tests_helpers import FakeCRM, msg


class LevelTG:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, level=None):
        self.sent.append((chat_id, text, level))


class RecordingTelegram(Telegram):
    def __init__(self, fail_html=False):
        super().__init__("123:abc")
        self.payloads, self.fail_html = [], fail_html

    def call(self, method, payload=None, timeout=40):
        if self.fail_html and payload.get("parse_mode"):
            raise RuntimeError("Telegram sendMessage: Bad Request: can't parse entities")
        self.payloads.append(payload)
        return {}


class AlertLevelTest(unittest.TestCase):
    def test_levels_of_bot_messages(self):
        red = ["⚠️ Chị Lan có vẻ CHƯA ĐƯỢC GIẢI ĐÁP ĐÚNG:\n💬 “sai rồi”",
               "💬 2 KHÁCH ĐANG CHỜ ANH TRẢ LỜI\n  • Chị Lan – chờ 20 phút",
               "⏰ NHẮC LẦN 2 – 1 KHÁCH CHỜ QUÁ 1 giờ",
               "⏰ 📦 KHO: CÒN 1 TIN KHÁCH CHƯA XỬ LÝ (quá 30 phút)\n  • K5",
               "⚠️ Bot Điều phối không đọc được tin Zalo từ ZaloCRM (3 lần liên tiếp).",
               "📇 THÔNG TIN KHÁCH HÀNG – 1 khách\n❌ Chị A: không ghi được vào Google Sheet"]
        yellow = ["🛒 SALE – KHÁCH ĐẶT HÀNG / HỎI HÀNG – K5\n👤 Chị Lan",
                  "🧭 Giao việc K5 cho 🔧 @VHKyThuatBot\n\n…", "📅 GHI LỊCH L1 – 📦 Kho", "⏰ CÒN 45 PHÚT – 📦 Kho",
                  "🔔 ĐẾN GIỜ – 📦 Kho", "🆕 KHÁCH MỚI: Anh Nam", "📇 THÔNG TIN KHÁCH HÀNG – 1 khách\n✅ STT 3: A"]
        green = ["📅 BÁO CÁO NGÀY 15/11/2026\n…", "✅ Bot Điều phối đã đọc lại được tin nhắn Zalo từ ZaloCRM.",
                 "👍 Đã xử lý tin K5", "📅 LỊCH HÔM NAY 16/11 – 📦 Kho", "🧭 Bot Điều phối: Bắt đầu HỌP CÔNG TY"]
        for text in red:
            self.assertEqual(alert_level(text), DO, text)
        for text in yellow:
            self.assertEqual(alert_level(text), VANG, text)
        for text in green:
            self.assertEqual(alert_level(text), XANH, text)

    def test_format(self):
        red = format_alert("⚠️ Khách <Lan> chờ\nchi tiết & thêm", DO)
        self.assertEqual(red, "🔴 <b>⚠️ Khách &lt;Lan&gt; chờ</b>\n<blockquote>chi tiết &amp; thêm</blockquote>")
        self.assertEqual(format_alert("🆕 KHÁCH MỚI\nAnh Nam", VANG), "🟡 <b>🆕 KHÁCH MỚI</b>\nAnh Nam")
        self.assertEqual(format_alert("👍 Đã xử lý tin K5", XANH), "🟢 👍 Đã xử lý tin K5")

    def test_send_uses_html_green_is_silent_and_plain_reply_unchanged(self):
        tg = RecordingTelegram()
        tg.send("1", "⚠️ Lỗi\nchi tiết", level=DO)
        tg.send("1", "👍 Xong", level=XANH)
        tg.send("1", "Gõ /help")
        red, green, plain = tg.payloads
        self.assertEqual(red["parse_mode"], "HTML")
        self.assertFalse(red["disable_notification"])
        self.assertTrue(green["disable_notification"])
        self.assertNotIn("parse_mode", plain)
        self.assertEqual(plain["text"], "Gõ /help")

    def test_falls_back_to_plain_text_when_telegram_rejects_html(self):
        tg = RecordingTelegram(fail_html=True)
        tg.send("1", "⚠️ Lỗi", level=DO)
        self.assertEqual(tg.payloads[0]["text"], "🔴 ⚠️ Lỗi")

    def test_bot_pushes_carry_levels(self):
        tg = LevelTG()
        bot = CRMBot(Store(":memory:"), FakeCRM(), "", "", telegram=tg, pair_code="482913")
        bot.handle_telegram("777", "/batdau 482913")
        tg.sent.clear()
        bot.handle_event(msg("message.received", "c-nam", "Anh ơi lấy em 2 tủ lavabo 80cm nhé"))
        self.assertEqual(tg.sent[-1][2], VANG)
        bot.report_problem("⚠️ Có lỗi")
        self.assertEqual(tg.sent[-1][2], DO)


class GluedCommandTest(unittest.TestCase):
    def test_command_and_code_typed_together(self):
        self.assertEqual(parse_command("/xongk6"), parse_command("/xong k6"))
        self.assertEqual(parse_command("/xongK6").args, "K6")
        self.assertEqual(parse_command("/xem12").args, "12")
        self.assertEqual(parse_command("/chuyenk5 kho").args, "k5 kho")
        self.assertIsNone(parse_command("/abc12"))
        self.assertEqual(parse_command("/thieu").name, "thieu")


if __name__ == "__main__":
    unittest.main()
