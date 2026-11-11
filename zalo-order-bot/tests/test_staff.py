import unittest
from datetime import datetime, timedelta

from bot.crm_main import CRMBot
from bot.db import Store
from tests_helpers import CONVS, FakeCRM
from test_followup import T0, zmsg
from test_room import BOSS, FakeTG

STAFF = ["Viet Hoang", "Lê Tấn Phát", "Phát", "Tấn Phát Cs"]


class StaffTest(unittest.TestCase):
    """Nhóm Zalo có khách + nhân viên shop (Lê Tấn Phát, Phát, Tấn Phát Cs, anh, nick shop)."""

    def setUp(self):
        CONVS["c-dutoan"] = {"id": "c-dutoan", "threadType": "group", "externalThreadId": "g7",
                             "contact": {"fullName": "Nhà anh Tuấn – tủ bếp"}}
        CONVS["c-clb"] = {"id": "c-clb", "threadType": "group", "externalThreadId": "g8",
                          "contact": {"fullName": "CLB Pickleball"}}
        self.crm, self.dp = FakeCRM(), FakeTG("VHDieuPhoiBot")
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913",
                          scan_groups="auto")
        self.bot.shop_names = {"viet hoang noi that"}
        self.bot.handle_telegram(BOSS, "/batdau 482913")
        self.assertIn("Phát", self.bot.handle_telegram(BOSS, "/nhanvien them " + ", ".join(STAFF)))
        self.dp.sent.clear()
        self.nine = datetime(2026, 11, 12, 9, 0)

    def tearDown(self):
        CONVS.pop("c-dutoan"), CONVS.pop("c-clb")

    def test_staff_messages_are_never_treated_as_customers(self):
        self.bot.handle_event(zmsg(1, "c-dutoan", "Dạ chiều mai bên em giao hàng và lắp đặt cho anh nhé", 0,
                                   sender="Lê Tấn Phát"))
        self.bot.handle_event(zmsg(2, "c-dutoan", "anh ơi bao giờ giao hàng vậy", 1, sender="Anh Tuấn"))
        # Tin của nhân viên không thành việc Kho/Kỹ thuật; tin khách thì có
        alerts = [t for t in self.dp.to(BOSS)]
        self.assertEqual(len(alerts), 1)
        self.assertIn("Anh Tuấn (nhóm Nhà anh Tuấn – tủ bếp)", alerts[0])

    def test_staff_reply_in_group_stops_reminder(self):
        self.bot.handle_event(zmsg(1, "c-dutoan", "Dạ em chào anh", 0, sender="Tấn Phát Cs"))  # nhóm làm việc
        self.bot.handle_event(zmsg(2, "c-dutoan", "tủ bếp màu trắng còn không em?", 1, sender="Anh Tuấn"))
        self.bot.handle_event(zmsg(3, "c-dutoan", "dạ còn anh ạ", 4, sender="Phát"))
        self.assertFalse(self.bot.check_unanswered(T0 + timedelta(minutes=30), self.nine))

    def test_customer_waiting_in_work_group_is_reminded(self):
        self.bot.handle_event(zmsg(1, "c-dutoan", "Dạ em chào anh", 0, sender="Phát"))
        self.bot.handle_event(zmsg(2, "c-dutoan", "tủ bếp màu trắng còn không em?", 1, sender="Anh Tuấn"))
        self.assertTrue(self.bot.check_unanswered(T0 + timedelta(minutes=20), self.nine))
        self.assertIn("Anh Tuấn (nhóm Nhà anh Tuấn – tủ bếp)", self.dp.to(BOSS)[-1])

    def test_community_group_without_staff_is_ignored(self):
        self.bot.handle_event(zmsg(1, "c-clb", "ai lấy 2 áo size M ship tận nhà không", 0, sender="Duy Minh"))
        self.assertFalse(self.bot.check_unanswered(T0 + timedelta(minutes=60), self.nine))
        self.assertEqual(self.dp.to(BOSS), [])

    def test_staff_order_in_group_is_recorded_under_group_name(self):
        self.bot.handle_event(zmsg(1, "c-dutoan", "Đơn: 1 tủ lavabo 80cm", 0, sender="Lê Tấn Phát"))
        self.assertIn("Nhà anh Tuấn – tủ bếp", self.dp.to(BOSS)[-1])
        self.assertIn("Đã ghi đơn #1", self.dp.to(BOSS)[-1])

    def test_nhanvien_command(self):
        h = self.bot.handle_telegram
        self.assertIn("Tấn Phát Cs", h(BOSS, "/nhanvien"))
        self.assertNotIn("• Phát\n", h(BOSS, "/nhanvien xoa Phát"))
        self.assertTrue(self.bot.is_shop_person("lê tấn phát"))
        self.assertFalse(self.bot.is_shop_person("Phát"))
        self.assertIn("Cú pháp", h(BOSS, "/nhanvien sua Phát"))

    def test_env_staff_names(self):
        self.bot.staff_env = {"nhan vien a"}
        self.assertTrue(self.bot.is_shop_person("Nhân Viên A"))


if __name__ == "__main__":
    unittest.main()
