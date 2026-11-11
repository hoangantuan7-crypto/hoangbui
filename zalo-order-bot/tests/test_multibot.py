import unittest
from datetime import datetime, timedelta

from bot.crm_main import CRMBot
from bot.db import Store
from tests_helpers import FakeCRM, msg


class FakeTG:
    def __init__(self, name):
        self.name, self.sent = name, []

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))


class MultiBotTest(unittest.TestCase):
    """5 bot riêng: Điều phối + Sale + Kế toán + Kho + Kỹ thuật. Anh (chat 777) kết nối với cả 5."""

    def setUp(self):
        self.crm = FakeCRM()
        self.dp = FakeTG("dieuphoi")
        self.depts = {d: FakeTG(d) for d in ("sale", "ketoan", "kho", "kythuat")}
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913",
                          dept_bots=self.depts)
        self.assertIn("Chat TỔNG", self.bot.handle_telegram("777", "/batdau 482913"))
        for d in self.depts:
            reply = self.bot.handle_telegram("777", "/batdau 482913", botname=d)
            self.assertIn("Đã kết nối với", reply)

    def test_each_department_bot_reports_its_own_work_only(self):
        self.bot.handle_event(msg("message.received", "c-nam", "Vòi sen bị hỏng rồi em ơi, còn bảo hành không"))
        self.bot.handle_event(msg("message.received", "c-nam", "Em chuyển khoản rồi nhé"))
        self.assertEqual(self.crm.sent, [])  # không gửi gì qua Zalo
        self.assertEqual(len(self.depts["kythuat"].sent), 1)
        self.assertIn("KỸ THUẬT", self.depts["kythuat"].sent[0][1])
        self.assertEqual(self.depts["kythuat"].sent[0][0], "777")
        self.assertEqual(len(self.depts["ketoan"].sent), 1)
        self.assertEqual(self.depts["sale"].sent, [])
        self.assertEqual(self.depts["kho"].sent, [])
        self.assertEqual(self.dp.sent, [])  # Bot Điều phối không báo trùng

    def test_department_bot_has_its_own_commands(self):
        b = self.bot.handle_telegram
        self.assertIn("BOT KHO", b("777", "/help", botname="kho"))
        self.assertIn("/thieu", b("777", "/help", botname="kho"))
        self.assertNotIn("/thieu", b("777", "/help", botname="ketoan"))
        self.assertIn("không thuộc Bot Kế toán", b("777", "/thieu", botname="ketoan"))
        self.assertIn("Bot Kho", b("777", "/thieu", botname="ketoan"))  # chỉ đúng bot cần dùng
        self.assertIn("thiếu hàng", b("777", "/thieu", botname="kho"))
        self.assertIn("Đã ghi đơn #1", b("777", "Đơn chị Lan: 1 tủ lavabo 60cm", botname="sale"))
        self.assertIn("/help", b("777", "Đơn chị Lan: 1 tủ lavabo 60cm", botname="kythuat"))
        self.assertIn("Bot Kỹ thuật", b("777", "/bophan", botname="kythuat"))

    def test_pairing_is_per_bot(self):
        self.assertIn("Bot riêng", self.bot.handle_telegram("888", "/choxuly", botname="kho"))
        self.bot.handle_telegram("888", "/batdau 482913", botname="kho")
        self.assertIn("(Kho)", self.bot.handle_telegram("888", "/choxuly", botname="kho"))
        self.assertIn("Bot riêng", self.bot.handle_telegram("888", "/choxuly", botname="sale"))

    def test_chuyen_moves_work_to_other_bot(self):
        self.bot.handle_event(msg("message.received", "c-nam", "Bao giờ giao hàng cho anh"))  # Kho, K1
        self.assertIn("Đã chuyển K1", self.bot.handle_telegram("777", "/chuyen K1 kythuat", botname="kho"))
        self.assertIn("Việc chuyển sang", self.depts["kythuat"].sent[-1][1])
        self.assertIn("Không có tin khách", self.bot.handle_telegram("777", "/choxuly", botname="kho"))

    def test_reminder_and_daily_report_come_from_right_bot(self):
        self.bot.handle_event(msg("message.received", "c-nam", "Vòi sen bị hỏng rồi em ơi"))
        self.bot.remind_pending(30, datetime.now() + timedelta(minutes=31))
        self.assertIn("CÒN 1 TIN", self.depts["kythuat"].sent[-1][1])
        self.bot.send_daily(datetime.now())
        self.assertIn("BÁO CÁO NGÀY", self.dp.sent[-1][1])
        self.assertIn("KỸ THUẬT – 1", self.depts["kythuat"].sent[-1][1])

    def test_department_without_own_bot_falls_back_to_dispatcher(self):
        bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913",
                     dept_bots={"sale": self.depts["sale"]})
        bot.handle_telegram("777", "/batdau 482913")
        bot.handle_event(msg("message.received", "c-nam", "Vòi sen bị hỏng rồi em ơi"))
        self.assertIn("KỸ THUẬT", self.dp.sent[-1][1])

    def test_department_bot_nobody_paired_falls_back_to_main_chat(self):
        bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913",
                     dept_bots=self.depts)
        bot.handle_telegram("777", "/batdau 482913")  # chỉ kết nối Bot Điều phối
        bot.handle_event(msg("message.received", "c-nam", "Em chuyển khoản rồi nhé"))
        self.assertIn("KẾ TOÁN", self.dp.sent[-1][1])
        self.assertEqual(self.depts["ketoan"].sent, [])

    def test_old_single_bot_subscriptions_are_kept(self):
        store = Store(":memory:")
        store.subscribe("555", "anh", True)  # kiểu lưu của bản 1 bot
        bot = CRMBot(store, self.crm, "", "", telegram=self.dp, pair_code="482913")
        self.assertIn("Không có tin khách", bot.handle_telegram("555", "/choxuly"))


if __name__ == "__main__":
    unittest.main()


class ConcurrencyTest(unittest.TestCase):
    def test_many_threads_share_the_database(self):
        import threading
        store, errors = Store(":memory:"), []

        def work(n):
            try:
                for i in range(200):
                    store.set_setting(f"tg_offset_{n}", str(i))
                    store.add_lead(f"c{n}-{i}", "Khách", "", "sale", "lấy 2 tủ")
                    store.open_leads("sale")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(store.open_leads("sale")), 1600)
