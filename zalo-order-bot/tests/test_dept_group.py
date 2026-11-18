import unittest

from bot import groups
from bot.crm_main import CRMBot
from bot.db import Store
from test_groups import ShopCRM, ev
from test_orders import IdTG
from test_room import BOSS, ROOM

PHI = "PHÍ GIAO NHẬN HÀNG SHOWROOM TẤN PHÁT ( check test nội bộ )"


class DeptGroupTest(unittest.TestCase):
    def setUp(self):
        self.crm = ShopCRM()  # nhóm "d" là PHÍ GIAO NHẬN…
        self.dp = IdTG("VHDieuPhoiBot")
        self.d = {n: IdTG(f"VH{n}Bot") for n in ("sale", "ketoan", "kho", "kythuat")}
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913", dept_bots=self.d,
                          scan_groups="1")
        self.bot.load_usernames()
        h = self.bot.handle_telegram
        h(BOSS, "/batdau 482913")
        for n in ("kho", "ketoan"):
            h(BOSS, "/batdau 482913", botname=n)
        h(BOSS, "/nhom")
        self.reply = h(BOSS, "/nhom kho + ketoan PHÍ GIAO NHẬN HÀNG SHOWROOM")
        for t in [self.dp, *self.d.values()]:
            t.sent.clear()

    def test_classify_and_listing(self):
        self.assertIn("📦💰 bộ phận Kho + Kế toán", self.reply)
        self.assertEqual(groups.class_of(self.bot.store, PHI), "bp:kho,ketoan")

    def test_messages_go_to_kho_and_ketoan_bots_silently(self):
        self.bot.handle_event(ev(1, "d", "Phí ship đơn chị Hương 350k, đã chuyển cho nhà xe", sender="Linh"))
        kho, ketoan = self.d["kho"].to(BOSS), self.d["ketoan"].to(BOSS)
        self.assertEqual(len(kho), 1)
        self.assertEqual(len(ketoan), 1)
        self.assertIn("KHO + KẾ TOÁN – TIN NHÓM PHÍ GIAO NHẬN", kho[0])
        self.assertIn("Linh: 💬 “Phí ship đơn chị Hương 350k", kho[0])
        self.assertEqual(self.d["kho"].sent[0][2], "xanh")            # không rung, không chuông
        self.assertEqual(self.bot.store.open_leads(), [])              # không coi là tin khách
        self.assertEqual(self.bot.store.waiting_convs(include_groups=True), [])

    def test_room_gets_one_message_and_schedule_is_recorded(self):
        self.bot.handle_telegram(ROOM, "/batdau 482913 phong")
        self.bot.handle_event(ev(2, "d", "Mai 9h giao tủ cho chị Hiền nhé", sender="Linh"))
        room = self.d["kho"].to(ROOM)
        self.assertTrue(room[0].startswith("📦 💰 KHO + KẾ TOÁN – TIN NHÓM"))
        self.assertTrue(any("GHI LỊCH L1 – 📦 Kho" in t for t in room))
        self.assertEqual(self.d["ketoan"].to(ROOM), [])

    def test_auto_names(self):
        self.assertEqual(groups.auto_class("kho test"), "bp:kho")
        self.assertEqual(groups.auto_class("ke toan test"), "bp:ketoan")
        self.assertEqual(groups.auto_class("dieu phoi test"), "congviec")
        self.assertIsNone(groups.auto_class("khoa kinh te"))


if __name__ == "__main__":
    unittest.main()
