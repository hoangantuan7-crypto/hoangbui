import json
import shutil
import unittest
from io import BytesIO
from unittest import mock

from bot import crm_main
from bot.crm_main import CRMBot
from bot.customer_info import clean_phone, image_url, parse_text
from bot.db import Store
from test_groups import ShopCRM, grp, iso
from test_room import BOSS, FakeTG


class FakeSheet:
    def __init__(self):
        self.rows = []

    def append(self, row):
        for i, r in enumerate(self.rows):
            if row["phone"] and r["phone"] == row["phone"]:
                return {"ok": True, "duplicate": True, "row": i + 2, "stt": i + 1}
        self.rows.append(row)
        return {"ok": True, "row": len(self.rows) + 1, "stt": len(self.rows)}


def make_image(lines):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    im = Image.new("RGB", (1100, 70 + 50 * len(lines)), "white")
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        d.text((30, 30 + 50 * i), ln, fill="black", font=font)
    b = BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def ev(i, text, ctype="text", sender="Viet Hoang"):
    return {"source": "hỏi định kỳ", "event": "message.received",
            "data": {"messageId": f"ci{i}", "conversationId": "info", "content": text, "contentType": ctype,
                     "senderName": sender, "sentAt": iso(minutes=0)}}


class ParseTest(unittest.TestCase):
    def test_phone_and_text(self):
        self.assertEqual(clean_phone("+84 912 345 678"), "0912345678")
        self.assertEqual(clean_phone("12345"), "")
        self.assertEqual(parse_text("KH: Chị Lan | 0912 345 678 | Diễn Châu | tủ 80")[0]["address"], "Diễn Châu")
        rows = parse_text("1. Chị Hoa 0901234567 Diễn Yên\n2_ Anh Bắc 0912111222 Lý Thành")
        self.assertEqual([r["name"] for r in rows], ["Chị Hoa", "Anh Bắc"])
        self.assertEqual(parse_text("ok mọi người nhé"), [])

    def test_image_url(self):
        url, cap = image_url(json.dumps({"href": "https://f.zdn.vn/a.jpg", "title": "khách mới"}))
        self.assertEqual((url, cap), ("https://f.zdn.vn/a.jpg", "khách mới"))
        self.assertEqual(image_url("không phải json")[0], "")


class InfoGroupTest(unittest.TestCase):
    def setUp(self):
        self.crm, self.dp = ShopCRM(), FakeTG("VHDieuPhoiBot")
        self.crm.convs.append(grp("info", "g-info", "THÔNG TIN KHÁCH HÀNG", 0))
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913", scan_groups="1")
        self.bot.staff_env = {"viet hoang"}
        self.bot.sheet = self.sheet = FakeSheet()
        self.bot.handle_telegram(BOSS, "/batdau 482913")
        self.dp.sent.clear()

    def test_typed_customer_goes_to_sheet(self):
        self.bot.handle_event(ev(1, "KH: Chị Lan | 0912345678 | Diễn Châu | tủ lavabo 80"))
        self.assertEqual(self.sheet.rows[0]["name"], "Chị Lan")
        self.assertEqual(self.sheet.rows[0]["source"], "Gõ tay")
        self.assertEqual(self.sheet.rows[0]["sender"], "Viet Hoang")
        self.assertIn("✅ STT 1: Chị Lan – 0912345678 – Diễn Châu", self.dp.to(BOSS)[-1])
        # cùng SĐT -> không thêm trùng
        self.bot.handle_event(ev(2, "KH: Lan | 0912 345 678 | Diễn Châu"))
        self.assertEqual(len(self.sheet.rows), 1)
        self.assertIn("đã có trong Sheet ở dòng 2", self.dp.to(BOSS)[-1])

    def test_chatter_in_info_group_is_ignored_and_not_a_customer_chat(self):
        self.bot.handle_event(ev(3, "mọi người ơi chiều nay họp nhé", sender="Khách lạ"))
        self.assertEqual(self.sheet.rows, [])
        self.assertEqual(self.dp.sent, [])
        self.assertEqual(self.bot.waiting_rows(), [])

    @unittest.skipUnless(shutil.which("tesseract"), "cần tesseract")
    def test_photo_list_read_by_free_ocr(self):
        image = make_image(["STT  Tên khách        SĐT           Địa chỉ",
                            "1    Chị Hoa Diễn Yên   0901234567   Diễn Yên",
                            "2    Anh Bắc            0912111222   Lý Thành"])
        content = json.dumps({"href": "https://f.zdn.vn/list.png", "title": ""})
        with mock.patch.object(crm_main, "download", return_value=(image, "image/png")), \
                mock.patch("bot.ai_parser.ai_available", return_value=False):
            self.bot.handle_event(ev(4, content, ctype="image"))
        self.assertEqual([r["phone"] for r in self.sheet.rows], ["0901234567", "0912111222"])
        self.assertEqual(self.sheet.rows[0]["source"], "Ảnh (OCR)")
        self.assertEqual(self.sheet.rows[0]["image"], "https://f.zdn.vn/list.png")
        self.assertIn("2 khách từ ảnh (ocr)", self.dp.to(BOSS)[-1])

    def test_handwritten_photo_uses_ai_when_available(self):
        content = json.dumps({"href": "https://f.zdn.vn/tay.jpg"})
        ai = [{"stt": "1", "name": "Chú Cửu", "phone": "0987654321", "address": "Sau Toà Án", "date": "12/11/2026",
               "note": "", "unclear": False},
              {"stt": "2", "name": "Anh Q", "phone": "", "address": "", "date": "", "note": "", "unclear": True}]
        with mock.patch.object(crm_main, "download", return_value=(b"jpg", "image/jpeg")), \
                mock.patch("bot.ai_parser.ai_available", return_value=True), \
                mock.patch("bot.customer_info.ai_read", return_value=ai):
            self.bot.handle_event(ev(5, content, ctype="image"))
        self.assertEqual(self.sheet.rows[0]["status"], "Đủ thông tin")
        self.assertEqual(self.sheet.rows[0]["date"], "12/11/2026")
        self.assertEqual(self.sheet.rows[1]["status"], "Cần kiểm tra")
        self.assertIn("⚠️ cần kiểm tra", self.dp.to(BOSS)[-1])

    def test_unreadable_photo_asks_boss_to_check(self):
        content = json.dumps({"href": "https://f.zdn.vn/mo.jpg"})
        with mock.patch.object(crm_main, "download", return_value=(b"x", "image/jpeg")), \
                mock.patch.object(crm_main, "read_image", return_value=([], "Ảnh (OCR)")):
            self.bot.handle_event(ev(6, content, ctype="image"))
        self.assertIn("không đọc được thông tin khách", self.dp.to(BOSS)[-1])
        self.assertIn("https://f.zdn.vn/mo.jpg", self.dp.to(BOSS)[-1])

    def test_without_sheet_configured(self):
        self.bot.sheet = None
        self.bot.handle_event(ev(7, "KH: Chị Mai | 0911222333 | Diễn Bình"))
        self.assertIn("chưa cài Google Sheet", self.dp.to(BOSS)[-1])

    def test_group_listing_shows_info_group(self):
        self.assertIn("📇 THÔNG TIN KHÁCH HÀNG – thông tin khách", self.bot.handle_telegram(BOSS, "/nhom"))


if __name__ == "__main__":
    unittest.main()
