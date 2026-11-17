import json
import unittest
from datetime import datetime, timedelta
from unittest import mock

from bot import crm_main
from bot.crm_main import CRMBot
from bot.db import Store
from bot.telegram import VANG, alert_level
from test_groups import ev, grp
from test_orders import CATALOG, READ, IdTG
from test_rescan import RescanCRM

INTEREST = {**READ, "paid_before": 0, "paid_before_date": "", "pay_now": 0, "customer": "Anh Duy",
            "phone": "0912345678", "discount": 0, "total": 0}


class InterestSheet:
    def __init__(self):
        self.saved, self.closed, self.status = [], [], []
        self.list = []

    def products(self):
        return CATALOG

    def save_order(self, order):
        self.saved.append(order)
        return {"ok": True, "code": "D7", "items": len(order["items"]), "payments": 0 if order["interest"] else 1,
                "customer": {"isNew": True, "stt": 3}, "stock": [], "updated": False,
                "converted": not order["interest"]}

    def interested(self):
        return self.list

    def close(self, code, amount, date=""):
        self.closed.append((code, amount, date))
        return {"ok": True, "code": code, "customer": "Anh Duy", "phone": "0912345678", "total": 14_000_000,
                "paid": amount, "left": 14_000_000 - amount,
                "stock": [{"code": "H-2200V", "stock": 0, "ordered": 2, "need": 2}]}

    def set_status(self, code, status):
        self.status.append((code, status))
        return {"ok": True, "code": code, "customer": "Anh Duy"}


class InterestTest(unittest.TestCase):
    def setUp(self):
        self.crm = RescanCRM()
        self.tg = IdTG("VHDieuPhoiBot")
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.tg, pair_code="482913")
        self.sheet = InterestSheet()
        self.bot.order_sheet = self.sheet
        self.bot.handle_telegram("777", "/batdau 482913")
        self.read = mock.patch.object(crm_main, "ai_read_order", return_value=INTEREST)
        for p in (self.read, mock.patch.object(crm_main, "ai_available", return_value=True),
                  mock.patch.object(CRMBot, "fetch_image", return_value=(b"img", "image/jpeg"))):
            p.start()
            self.addCleanup(p.stop)
        self.tg.sent.clear()

    def photo(self):
        e = ev(9, "i", json.dumps({"href": "https://photo.zdn.vn/a.jpg"}), sender="Lê Tấn Phát")
        e["data"]["contentType"] = "image"
        self.bot.handle_event(e)

    def last(self):
        return self.tg.sent[-1][1]

    def test_photo_without_deposit_is_saved_as_interested(self):
        self.photo()
        order = self.sheet.saved[0]
        self.assertTrue(order["interest"])
        self.assertIn("giá tham khảo", order["items"][3]["note"])  # dòng thiếu giá lấy giá kho
        msg = self.last()
        self.assertIn("KHÁCH ĐANG QUAN TÂM – D7", msg)
        self.assertEqual(alert_level(msg), VANG)
        self.assertIn("/chot D7 coc 5tr", msg)
        self.assertEqual(self.bot.store.open_drafts(), [])

    def test_photo_with_deposit_becomes_draft_for_approval(self):
        self.read.stop()
        with mock.patch.object(crm_main, "ai_read_order", return_value=READ):
            self.photo()
        self.read.start()
        self.assertEqual(self.sheet.saved, [])
        self.assertIn("NHÁP ĐƠN – N1", self.last())

    def test_close_and_drop_commands(self):
        h = self.bot.handle_telegram
        self.assertIsNone(h("777", "/chot D7 coc 5tr 06/10"))
        self.assertEqual(self.sheet.closed, [("D7", 5_000_000, "06/10")])
        texts = [t for _, t, _, _ in self.tg.sent]
        self.assertTrue(any("ĐÃ LÊN ĐƠN D7" in t for t in texts))
        self.assertTrue(any("KẾ TOÁN – ĐÃ THU – D7" in t for t in texts))
        self.assertTrue(any("CẦN NHẬP HÀNG" in t for t in texts))
        self.assertIn("thôi nhắc gọi", h("777", "/khongmua d7"))
        self.assertIn("Cú pháp", h("777", "/chot"))

    def test_call_back_every_three_days(self):
        today = datetime(2026, 11, 20, 9, 0)
        self.sheet.list = [
            {"code": "D7", "customer": "Anh Duy", "phone": "0912345678", "total": 8_520_000,
             "since": (today - timedelta(days=3)).strftime("%d/%m/%Y %H:%M"), "codes": ["H-2200V"]},
            {"code": "D8", "customer": "Chị Lan", "phone": "", "total": 0,
             "since": (today - timedelta(days=4)).strftime("%d/%m/%Y %H:%M"), "codes": ["VF-1862"]},
            {"code": "D9", "customer": "Anh Tú", "phone": "", "total": 0,
             "since": (today - timedelta(days=6)).strftime("%d/%m/%Y"), "codes": []},
        ]
        self.assertEqual(self.bot.remind_interested(today), 2)
        msg = self.last()
        self.assertIn("GỌI LẠI KHÁCH ĐANG QUAN TÂM (2 khách)", msg)
        self.assertIn("D9 Anh Tú", msg)
        self.assertNotIn("D8", msg)
        self.assertIn("3 KHÁCH ĐANG QUAN TÂM", self.bot.handle_telegram("777", "/quantam"))


if __name__ == "__main__":
    unittest.main()
