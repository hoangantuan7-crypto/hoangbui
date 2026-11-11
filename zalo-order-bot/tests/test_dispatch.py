import unittest
from datetime import datetime, timedelta

from bot.crm_main import CRMBot
from bot.db import Store
from bot.departments import route
from tests_helpers import FakeCRM, msg


class FakeTG:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))

    def to(self, chat_id):
        return [t for c, t in self.sent if c == chat_id]


class RouteTest(unittest.TestCase):
    def test_route(self):
        cases = {
            "Anh ơi lấy em 2 tủ lavabo 80cm nhé": "sale",
            "Tủ chậu 60 giá bao nhiêu ạ": "sale",
            "Em chuyển khoản rồi nhé": "ketoan",
            "Anh xuất hóa đơn VAT giúp em": "ketoan",
            "Bao giờ giao hàng cho chị vậy em": "kho",
            "Hàng bị vỡ một góc rồi anh": "kho",
            "Tủ lavabo mới lắp đã bị rỉ nước": "kythuat",
            "Vòi sen bị hỏng rồi, còn bảo hành không": "kythuat",
            "Ok em cảm ơn anh": None,
            "Cháu đi học từ sáng": None,
            "Em đi lập kế hoạch": None,
        }
        for text, dept in cases.items():
            self.assertEqual(route(text), dept, text)


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.crm, self.tg = FakeCRM(), FakeTG()
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "acc-1", telegram=self.tg, pair_code="482913")
        b = self.bot.handle_telegram
        self.assertIn("Chat TỔNG", b("boss", "/batdau 482913"))
        self.assertIn("Kỹ thuật", b("g-kt", "/batdau 482913 kythuat"))
        self.assertIn("Kho", b("g-kho", "/batdau 482913 kho"))
        self.assertIn("Kế toán", b("g-ketoan", "/batdau 482913 ketoan"))
        self.assertIn("Không rõ bộ phận", b("g-x", "/batdau 482913 marketing"))
        self.tg.sent.clear()

    def test_message_goes_to_right_department_and_boss(self):
        self.bot.handle_event(msg("message.received", "c-nam", "Vòi sen bị hỏng rồi em ơi, còn bảo hành không"))
        self.assertEqual(self.crm.sent, [])  # không gửi gì qua Zalo
        self.assertEqual(len(self.tg.to("g-kt")), 1)
        self.assertIn("KỸ THUẬT", self.tg.to("g-kt")[0])
        self.assertEqual(len(self.tg.to("boss")), 1)
        self.assertEqual(self.tg.to("g-kho"), [])
        self.assertEqual(self.tg.to("g-ketoan"), [])

    def test_department_sees_only_its_own_pending_work(self):
        self.bot.handle_event(msg("message.received", "c-nam", "Vòi sen bị hỏng rồi em ơi"))
        self.bot.handle_event(msg("message.received", "c-nam", "Em chuyển khoản rồi nhé"))
        kho = self.bot.handle_telegram("g-kho", "/choxuly")
        self.assertIn("Không có tin khách", kho)
        kt = self.bot.handle_telegram("g-kt", "/choxuly")
        self.assertIn("KỸ THUẬT – 1", kt)
        boss = self.bot.handle_telegram("boss", "/choxuly")
        self.assertIn("Kỹ thuật (1)", boss)
        self.assertIn("Kế toán (1)", boss)

    def test_reassign_with_chuyen(self):
        self.bot.handle_event(msg("message.received", "c-nam", "Bao giờ giao hàng cho anh"))  # -> kho, K1
        self.tg.sent.clear()
        self.assertIn("Đã chuyển K1 sang 🔧 Kỹ thuật", self.bot.handle_telegram("g-kho", "/chuyen K1 kythuat"))
        self.assertEqual(len(self.tg.to("g-kt")), 1)  # kỹ thuật được báo
        self.assertIn("KỸ THUẬT – 1", self.bot.handle_telegram("g-kt", "/choxuly"))
        self.assertIn("Cú pháp", self.bot.handle_telegram("g-kho", "/chuyen K1 marketing"))

    def test_reminders_go_to_each_department(self):
        self.bot.handle_event(msg("message.received", "c-nam", "Vòi sen bị hỏng rồi em ơi"))
        self.tg.sent.clear()
        self.assertTrue(self.bot.remind_pending(30, datetime.now() + timedelta(minutes=31)))
        self.assertEqual(len(self.tg.to("g-kt")), 1)
        self.assertIn("KỸ THUẬT: CÒN 1 TIN", self.tg.to("g-kt")[0])
        self.assertEqual(self.tg.to("g-kho"), [])

    def test_daily_report(self):
        self.bot.handle_event(msg("message.received", "c-nam", "Vòi sen bị hỏng rồi em ơi"))
        self.tg.sent.clear()
        self.bot.send_daily(datetime.now())
        self.assertIn("BÁO CÁO NGÀY", self.tg.to("boss")[0])
        self.assertIn("KỸ THUẬT – 1", self.tg.to("g-kt")[0])
        self.assertIn("Không có tin khách", self.tg.to("g-kho")[0])

    def test_old_database_is_migrated(self):
        store = Store(":memory:")
        store.conn.execute("INSERT INTO leads(conv_id, customer, kind, text, created_at, updated_at) "
                           "VALUES ('c','A','payment','ck','2026-11-11T10:00:00','2026-11-11T10:00:00')")
        store._migrate()
        self.assertEqual(store.open_leads("ketoan")[0]["customer"], "A")


if __name__ == "__main__":
    unittest.main()
