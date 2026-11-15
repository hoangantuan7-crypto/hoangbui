import unittest
from datetime import datetime, timedelta

from bot.crm_main import CRMBot
from bot.db import Store
from bot.meeting import COMPANY, build_meeting
from bot.schedule import parse_when, schedule_dept
from test_groups import ShopCRM, ev, grp
from test_room import BOSS, ROOM, FakeTG

SUN = datetime(2026, 11, 15, 10, 0)  # Chủ nhật 15/11, 10:00


class ParseWhenTest(unittest.TestCase):
    def at(self, text):
        r = parse_when(text, SUN)
        return r and (r[0].strftime("%d/%m %H:%M"), r[1])

    def test_vietnamese_dates_and_times(self):
        self.assertEqual(self.at("9h sáng mai giao tủ chị Hiền"), ("16/11 09:00", False))
        self.assertEqual(self.at("14h30 thứ 7 lắp gương nhà anh Tùng"), ("21/11 14:30", False))
        self.assertEqual(self.at("20/11 8h khảo sát"), ("20/11 08:00", False))
        self.assertEqual(self.at("chiều nay 3h qua kho lấy hàng"), ("15/11 15:00", False))
        self.assertEqual(self.at("3 giờ rưỡi chiều mai họp"), ("16/11 15:30", False))
        self.assertEqual(self.at("mốt 9g30 ship"), ("17/11 09:30", False))
        self.assertEqual(self.at("9h 20/11 giao hàng"), ("20/11 09:00", False))
        self.assertEqual(self.at("ngày 25 thu tiền công trình"), ("25/11 00:00", True))
        self.assertEqual(self.at("mai giao nhé"), ("16/11 00:00", True))

    def test_not_a_schedule(self):
        for text in ("chị Mai lấy 2 vòi", "mãi chưa giao", "hôm qua 3h giao rồi", "8h đã giao xong",
                     "tủ 80cm x 2", "giao 1/2 số hàng", "ok anh"):
            self.assertIsNone(parse_when(text, SUN), text)

    def test_department(self):
        self.assertEqual(schedule_dept("mai 9h giao tủ chị Hiền"), "kho")
        self.assertEqual(schedule_dept("thứ 7 lắp gương nhà anh Tùng"), "kythuat")
        self.assertEqual(schedule_dept("ngày 25 thu tiền công trình"), "ketoan")
        self.assertEqual(schedule_dept("mai 10h báo giá cho chị Lan"), "sale")
        self.assertIsNone(schedule_dept("mai 8h họp cả shop"))


class InternalGroupTest(unittest.TestCase):
    """Nhóm nội bộ loại "công việc": Bot Điều phối đọc lịch hẹn, bot bộ phận nhắc trong phòng điều phối."""

    def setUp(self):
        self.crm = ShopCRM()
        self.crm.convs.append(grp("w", "g-work", "TỦ LAVABO HÀNG RIÊNG KHÁCH SHOWROOM TẤN PHÁT", 1))
        self.dp = FakeTG("VHDieuPhoiBot")
        self.d = {"sale": FakeTG("VHSaleBot"), "ketoan": FakeTG("VHKeToanBot"),
                  "kho": FakeTG("VHKhoBot"), "kythuat": FakeTG("VHKyThuatBot")}
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913",
                          dept_bots=self.d, scan_groups="1")
        self.bot.load_usernames()
        h = self.bot.handle_telegram
        h(BOSS, "/batdau 482913")
        h(ROOM, "/batdau 482913 phong")
        h(BOSS, "/nhom")
        self.assertIn("📋 nội bộ – theo dõi lịch", h(BOSS, "/nhom congviec TỦ LAVABO HÀNG RIÊNG"))
        for t in [self.dp, *self.d.values()]:
            t.sent.clear()

    def test_schedule_from_group_is_assigned_and_reminded_by_the_department_bot(self):
        self.bot.handle_event(ev(1, "w", "Mai 9h giao tủ lavabo nhà chị Hiền nhé", sender="Linh"))
        confirm = self.d["kho"].to(ROOM)
        self.assertEqual(len(confirm), 1)
        self.assertIn("GHI LỊCH L1 – 📦 Kho", confirm[0])
        self.assertIn("09:00 Mai", confirm[0])
        self.assertEqual(self.bot.store.open_leads(), [])          # không coi là tin khách
        self.assertEqual(self.bot.store.waiting_convs(include_groups=True), [])

        at = datetime.combine(datetime.now().date() + timedelta(days=1), datetime.min.time()).replace(hour=9)
        self.assertEqual(self.bot.check_schedules(at - timedelta(minutes=90)), 0)
        self.assertEqual(self.bot.check_schedules(at - timedelta(minutes=45)), 1)
        self.assertIn("⏰ CÒN 45 PHÚT", self.d["kho"].to(ROOM)[-1])
        self.assertEqual(self.bot.check_schedules(at - timedelta(minutes=40)), 0)   # không nhắc lặp
        self.assertEqual(self.bot.check_schedules(at + timedelta(minutes=1)), 1)
        self.assertIn("🔔 ĐẾN GIỜ", self.d["kho"].to(ROOM)[-1])
        self.assertEqual(self.bot.check_schedules(at + timedelta(minutes=5)), 0)

    def test_same_message_seen_twice_is_one_schedule_and_chat_without_time_is_ignored(self):
        self.bot.handle_event(ev(1, "w", "Thứ 7 14h lắp tủ nhà anh Tùng", sender="Linh"))
        self.bot.handle_event(ev(2, "w", "Thứ 7 14h lắp tủ nhà anh Tùng", sender="Linh 2"))
        self.bot.handle_event(ev(3, "w", "ok em", sender="Linh"))
        self.assertEqual(len(self.d["kythuat"].to(ROOM)), 1)
        self.assertEqual(len(self.d["kho"].to(ROOM)), 0)

    def test_new_internal_group_offers_congviec(self):
        self.bot.bootstrap_known(self.crm.convs)
        self.crm.convs.append(grp("n", "g-new", "NHÓM MỚI", 0))
        self.crm.created["ct-g-new"] = datetime.now().isoformat()
        self.bot.handle_event(ev(1, "n", "chào cả nhà"))
        self.assertIn("/nhom congviec NHÓM MỚI", self.dp.to(BOSS)[-1])

    def test_lich_commands_and_morning_agenda(self):
        h = self.bot.handle_telegram
        r = h(BOSS, "/lich them kho mai 9h giao tủ chị Hiền")
        self.assertIn("GHI LỊCH L1 – 📦 Kho", self.d["kho"].to(ROOM)[-1])
        r = h(BOSS, "/lich them ngày mai họp")
        self.assertIn("GHI LỊCH", self.dp.to(ROOM)[-1])
        self.assertIn("chưa đọc được", h(BOSS, "/lich them giao hàng"))
        r = h(BOSS, "/lich")
        self.assertIn("L1", r)
        self.assertIn("L2", r)
        h(BOSS, "/batdau 482913", botname="kho")
        self.assertIn("L1", h(BOSS, "/lich", botname="kho"))
        self.assertNotIn("L2", h(BOSS, "/lich", botname="kho"))
        self.assertIn("Đã chuyển L1 sang 🔧 Kỹ thuật", h(BOSS, "/lich chuyen L1 kythuat"))
        tomorrow = datetime.now() + timedelta(days=1)
        meeting = "\n".join(t for _, t in build_meeting(self.bot.store, COMPANY, None, datetime.now()))
        self.assertIn("LỊCH NGÀY MAI", meeting)
        self.assertEqual(self.bot.send_agenda(tomorrow.replace(hour=7, minute=30)), 2)
        self.assertIn("LỊCH HÔM NAY", self.d["kythuat"].to(ROOM)[-1])
        self.assertIn("Đã xong lịch L1", h(BOSS, "/lich xong L1"))
        self.assertIn("Đã xóa lịch L2", h(BOSS, "/lich xoa 2"))
        self.assertIn("chưa có lịch", h(BOSS, "/lich"))


if __name__ == "__main__":
    unittest.main()
