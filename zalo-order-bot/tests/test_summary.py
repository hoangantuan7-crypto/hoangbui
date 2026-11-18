import json
import unittest
from unittest import mock

from bot import crm_main
from bot.crm_main import CRMBot
from bot.db import Store
from test_groups import ShopCRM, iso
from test_orders import IdTG
from test_room import BOSS


ONE_HOUR = iso(hours=1)


class SummaryCRM(ShopCRM):
    """Nhóm "d" = PHÍ GIAO NHẬN…; nhóm "a1"/"a2" là cùng 1 nhóm thấy qua 2 nick (tin trùng)."""

    def messages(self, cid, limit=30):
        if cid == "d":
            return [  # mới nhất trước
                {"sentAt": iso(hours=2), "senderName": "Linh", "contentType": "text", "content": "Phí ship chị Hương 350k"},
                {"sentAt": iso(hours=5), "senderName": "Hoàng", "contentType": "image",
                 "content": json.dumps({"href": "https://x/a.jpg"})},
                {"sentAt": iso(days=10), "senderName": "Linh", "contentType": "text", "content": "tin cũ quá 7 ngày"},
            ]
        if cid in ("a1", "a2"):
            return [{"sentAt": ONE_HOUR, "senderName": "Linh", "contentType": "text", "content": "Đặt hàng Dì Nhung"}]
        return []


class SummaryTest(unittest.TestCase):
    def setUp(self):
        self.tg = IdTG("VHDieuPhoiBot")
        self.bot = CRMBot(Store(":memory:"), SummaryCRM(), "", "", telegram=self.tg, pair_code="482913")
        self.bot.handle_telegram(BOSS, "/batdau 482913")
        self.bot.handle_telegram(BOSS, "/nhom")

    def test_resolve_by_number_or_name(self):
        self.assertEqual(self.bot.resolve_group("4 3"), ("PHÍ GIAO NHẬN HÀNG SHOWROOM TẤN PHÁT ( check test nội bộ )", 3))
        self.assertEqual(self.bot.resolve_group("PHÍ GIAO NHẬN")[1], 7)
        self.assertIn("Không tìm thấy", self.bot.resolve_group("ABCXYZ"))
        self.assertIn("Cú pháp", self.bot.resolve_group(""))

    def test_list_without_ai(self):
        with mock.patch("bot.ai_parser.ai_available", return_value=False):
            text = self.bot.group_summary("PHÍ GIAO NHẬN HÀNG SHOWROOM TẤN PHÁT ( check test nội bộ )", 7)
        self.assertIn("(2 tin)", text)
        self.assertIn("Linh: Phí ship chị Hương 350k", text)
        self.assertIn("Hoàng: [ảnh]", text)
        self.assertNotIn("tin cũ", text)
        self.assertLess(text.index("Hoàng"), text.index("Phí ship"))  # cũ trước, mới sau

    def test_duplicate_group_messages_merged_and_ai_summary_used(self):
        with mock.patch.object(crm_main, "summarize", return_value="💰 Tiền: …") as s:
            text = self.bot.group_summary("ĐẶT HÀNG – BẢO HÀNH SHOWROOM TẤN PHÁT", 7)
        self.assertIn("(1 tin)", text)
        self.assertIn("💰 Tiền: …", text)
        self.assertEqual(len(s.call_args[0][1]), 1)

    def test_command_runs_in_background(self):
        with mock.patch.object(CRMBot, "_summary_and_reply") as run:
            reply = self.bot.handle_telegram(BOSS, "/tonghop 4 3")
        self.assertIn("Đang đọc lại tin nhóm", reply)


if __name__ == "__main__":
    unittest.main()


class ImageReadingTest(unittest.TestCase):
    def test_summary_sends_recent_images_to_ai(self):
        from bot import summary
        entries = [("18/11 09:00 Hoàng: [ảnh]", ["https://x/1.jpg"]), ("18/11 09:05 Linh: ship 350k", []),
                   ("18/11 09:16 Hoàng: [ảnh]", ["https://x/2.jpg"])]
        fetched = []
        with mock.patch("bot.ai_parser.ai_available", return_value=True), \
                mock.patch.object(summary, "_call", return_value="tóm tắt") as call:
            out = summary.summarize("PHÍ GIAO NHẬN", entries, "18/11", "18/11",
                                    fetch=lambda links: fetched.append(links[0]) or (b"img", "image/jpeg"))
        self.assertEqual(out, "tóm tắt")
        self.assertEqual(fetched, ["https://x/1.jpg", "https://x/2.jpg"])
        content = call.call_args[0][0]
        self.assertEqual([b["type"] for b in content], ["text", "image", "text", "image"])

    def test_dept_group_image_is_described(self):
        from test_dept_group import DeptGroupTest
        t = DeptGroupTest("test_auto_names")
        t.setUp()
        e = __import__("test_groups").ev(5, "d", json.dumps({"href": "https://x/p.jpg"}), sender="Hoàng")
        e["data"]["contentType"] = "image"
        with mock.patch.object(crm_main, "ai_available", return_value=True), \
                mock.patch.object(CRMBot, "fetch_image", return_value=(b"img", "image/jpeg")), \
                mock.patch.object(crm_main, "describe_image", return_value="Phiếu giao hàng chị Hương, phí ship 350.000đ"):
            t.bot.handle_event(e)
        msg = t.d["kho"].to(BOSS)[0]
        self.assertIn("em đọc được:\nPhiếu giao hàng chị Hương, phí ship 350.000đ", msg)
        self.assertIn("🔗 https://x/p.jpg", msg)
