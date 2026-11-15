import unittest
from unittest import mock

from bot import crm_main
from bot.crm_main import CRMBot
from bot.db import Store
from bot.orders import Catalog, apply_edits, build_draft, money, render, sheet_payload, totals
from bot.telegram import VANG, XANH, alert_level
from test_groups import ShopCRM, ev, grp
from test_room import BOSS, ROOM

CATALOG = [
    {"code": "TCLUX01-VA-MSLK80 TD+TGLED-KB", "name": "Bộ tủ lavabo 80cm", "unit": "Bộ", "price": 8850000, "kind": "thuong"},
    {"code": "H-2200V", "name": "Vòi lavabo HUGE", "unit": "Cái", "price": 1460000, "kind": "thuong"},
    {"code": "G-XFN01", "name": "Xi phông GUCEN", "unit": "Bộ", "price": 130000, "kind": "thuong"},
    {"code": "H-B1639", "name": "Kệ kính HUGE", "unit": "Bộ", "price": 850000, "kind": "thuong"},
    {"code": "LFV-612S", "name": "Vòi lavabo INAX", "unit": "Bộ", "price": 2350000, "kind": "thuong"},
    {"code": "LFV-612SH-2", "name": "Vòi lavabo INAX thân cao", "unit": "Bộ", "price": 2860000, "kind": "thuong"},
    {"code": "VF-1862", "name": "Bồn cầu American Standard", "unit": "Bộ", "price": 5600000, "kind": "thuong"},
]
# Kết quả AI đọc "PHIẾU XUẤT KHO – NHÁP" chị Hương (rút gọn)
READ = {
    "is_order": True, "doc_type": "don_hang", "customer": "CHỊ HƯƠNG - CHỢ BỘNG", "phone": "0362 016 908",
    "address": "Chợ Bộng, Yên Thành", "order_date": "", "delivery_date": "03/11/2026",
    "items": [
        {"code": "TCLUX01-VA-MSLK80 TD+TGLED-KB", "name": "Tủ lavabo 80cm kem bóng", "unit": "Bộ", "qty": 1,
         "price": 8850000, "amount": 8850000, "kind": "thuong", "note": ""},
        {"code": "H-2200V", "name": "Vòi lavabo HUGE", "unit": "Cái", "qty": 2, "price": 1460000, "amount": 2920000,
         "kind": "thuong", "note": ""},
        {"code": "G-XFN01", "name": "Xi phông nhựa GUCEN - tặng kèm", "unit": "Bộ", "qty": 2, "price": 0, "amount": 0,
         "kind": "tang", "note": ""},
        {"code": "612S", "name": "Vòi LKB", "unit": "", "qty": 1, "price": 0, "amount": 0, "kind": "thuong", "note": ""},
        {"code": "TU LAVABO 80x53", "name": "Tủ LVB 80x53 kem bóng", "unit": "Bộ", "qty": 1, "price": 0, "amount": 0,
         "kind": "rieng", "note": "chờ khảo sát"},
    ],
    "subtotal": 0, "discount": 120000, "total": 14000000, "paid_before": 5000000, "paid_before_date": "06/10/2026",
    "pay_now": 0, "note": "Thiếu 2 vòi xịt CFV-102M", "unclear": "",
}


class MoneyAndCatalogTest(unittest.TestCase):
    def test_money(self):
        for text, want in [("5tr", 5_000_000), ("1tr2", 1_200_000), ("16tr6", 16_600_000), ("850k", 850_000),
                           ("5.000.000", 5_000_000), ("2,120,000đ", 2_120_000), ("1460000", 1_460_000),
                           ("5 triệu", 5_000_000)]:
            self.assertEqual(money(text), want, text)
        self.assertIsNone(money("abc"))

    def test_catalog_match(self):
        cat = Catalog(CATALOG)
        self.assertEqual(cat.match("h2200v"), (CATALOG[1], "dung"))
        self.assertEqual(cat.match("612S")[0]["code"], "LFV-612S")
        self.assertEqual(cat.match("612S")[1], "gan")
        self.assertEqual(cat.match("XYZ-1"), (None, ""))


class DraftTest(unittest.TestCase):
    def setUp(self):
        self.cat = Catalog(CATALOG)
        self.draft = build_draft(READ, self.cat)

    def test_build_and_render(self):
        d = self.draft
        self.assertEqual(d["phone"], "0362016908")
        self.assertEqual(d["items"][3]["code"], "LFV-612S")           # mã ghi tắt -> mã kho
        self.assertEqual(d["items"][3]["price"], 2350000)             # thiếu giá -> giá kho
        self.assertEqual(totals(d), (14_120_000, 14_000_000, 5_000_000, 9_000_000))
        text = render(3, d, "Linh")
        self.assertTrue(text.startswith("🛒 SALE – NHÁP ĐƠN – N3"))
        self.assertEqual(alert_level(text), VANG)
        self.assertIn("🎁 tặng", text)
        self.assertIn("🛠 Dòng 5 hàng riêng chờ khảo sát", text)
        self.assertIn("em lấy giá kho 2.350.000", text)
        self.assertIn("Còn lại 9.000.000", text)

    def test_edits(self):
        action, bad = apply_edits(self.draft, "2 sl 1\n4 gia 2.400.000\nxoa 3\nthem H-B1639 1 850k\n"
                                              "coc 6tr 07/10\ngiam 0\nsdt 0912 345 678\nghichu giao chiều\nabc xyz",
                                  self.cat)
        d = self.draft
        self.assertIsNone(action)
        self.assertEqual(bad, ["abc xyz"])
        self.assertEqual(d["items"][1]["qty"], 1)
        self.assertEqual(d["items"][2]["price"], 2_400_000)           # dòng 4 cũ (đã xóa dòng 3)
        self.assertEqual(d["items"][-1]["code"], "H-B1639")
        self.assertEqual((d["paid_before"], d["paid_before_date"], d["phone"]), (6_000_000, "07/10", "0912345678"))
        self.assertEqual(apply_edits(d, "ok", self.cat)[0], "ok")
        self.assertEqual(apply_edits(d, "Huỷ", self.cat)[0], "huy")

    def test_payload(self):
        p = sheet_payload(self.draft, "Linh", "http://img", "m1")
        self.assertEqual((p["total"], p["paid"], p["left"], p["status"]), (14_000_000, 5_000_000, 9_000_000, "Đã chốt"))
        self.assertEqual([it["kind"] for it in p["items"]], ["Hàng sẵn", "Hàng sẵn", "Tặng", "Hàng sẵn", "Hàng riêng"])
        self.assertEqual(p["items"][3]["match"], "Mã gần đúng")
        self.assertIn("TU LAVABO 80x53", p["pending"])


class IdTG:
    """Bot Telegram giả: trả về mã tin như Telegram thật."""
    counter = 100

    def __init__(self, username):
        self.username, self.sent = username, []

    def send(self, chat_id, text, level=None):
        IdTG.counter += 1
        self.sent.append((str(chat_id), text, level, IdTG.counter))
        return [IdTG.counter]

    def get_me(self):
        return {"username": self.username}

    def to(self, chat_id):
        return [t for c, t, _, _ in self.sent if c == chat_id]


class FakeOrderSheet:
    def __init__(self):
        self.saved = []

    def products(self):
        return CATALOG

    def save_order(self, order):
        self.saved.append(order)
        return {"ok": True, "code": f"D{len(self.saved)}"}


class OrderGroupFlowTest(unittest.TestCase):
    def setUp(self):
        self.crm = ShopCRM()
        self.crm.convs.append(grp("o", "g-order", "CHỐT ĐƠN TẤN PHÁT", 1))
        self.dp = IdTG("VHDieuPhoiBot")
        self.d = {n: IdTG(f"VH{n}Bot") for n in ("sale", "ketoan", "kho", "kythuat")}
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913", dept_bots=self.d)
        self.bot.order_sheet = FakeOrderSheet()
        self.bot.load_usernames()
        self.bot.handle_telegram(BOSS, "/batdau 482913")
        self.bot.handle_telegram(ROOM, "/batdau 482913 phong")
        patches = [mock.patch.object(crm_main, "ai_available", return_value=True),
                   mock.patch.object(crm_main, "ai_read_order", return_value=READ),
                   mock.patch.object(CRMBot, "fetch_image", return_value=(b"img", "image/jpeg"))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def photo(self, i=1):
        e = ev(i, "o", '{"href":"http://localhost:3080/files/media/a.jpg"}', sender="Linh")
        e["data"]["contentType"] = "image"
        self.bot.handle_event(e)

    def test_photo_becomes_draft_then_edit_then_approve(self):
        self.photo()
        drafts = [(t, mid) for c, t, lvl, mid in self.d["sale"].sent if c == ROOM]
        self.assertEqual(len(drafts), 1)
        text, mid = drafts[0]
        self.assertIn("NHÁP ĐƠN – N1", text)
        self.assertEqual(self.bot.store.open_leads(), [])             # không coi là tin khách

        # Anh trả lời tin nháp trong phòng điều phối: Bot Điều phối nhận, Bot Sale hiện lại nháp đã sửa
        self.assertIsNone(self.bot.handle_telegram(ROOM, "coc 6tr\n4 gia 2400000", "Anh", "dieuphoi", "sale", mid))
        new_text, new_mid = [(t, m) for c, t, _, m in self.d["sale"].sent if c == ROOM][-1]
        self.assertIn("cọc/đã thu 6.000.000", new_text)

        self.assertIsNone(self.bot.handle_telegram(ROOM, "ok", "Anh", "dieuphoi", "sale", new_mid))
        order = self.bot.order_sheet.saved[0]
        self.assertEqual((order["paidBefore"], order["status"], order["customer"]), (6_000_000, "Đã chốt",
                                                                                   "CHỊ HƯƠNG - CHỢ BỘNG"))
        sale_msg = next(t for t in self.d["sale"].to(ROOM) if "ĐÃ LÊN ĐƠN" in t)
        self.assertIn("ĐÃ LÊN ĐƠN D1", sale_msg)
        self.assertEqual(alert_level(sale_msg), XANH)
        self.assertIn("KẾ TOÁN – ĐÃ THU – D1", self.d["ketoan"].to(ROOM)[0])
        self.assertTrue(any("GHI LỊCH" in t and "Hàng riêng đơn D1" in t for t in self.d["sale"].to(ROOM)))
        self.assertIn("đã lên Sheet thành đơn D1", self.bot.handle_telegram(ROOM, "N1 ok", "Anh"))

    def test_cancel_and_list_and_typed_prefix(self):
        self.photo()
        self.assertIn("N1 CHỊ HƯƠNG", self.bot.handle_telegram(BOSS, "/nhapdon"))
        self.assertIn("ĐÃ BỎ NHÁP N1", self.bot.handle_telegram(BOSS, "N1 huy"))
        self.assertIn("Không có nháp", self.bot.handle_telegram(BOSS, "/nhapdon"))
        self.assertEqual(self.bot.order_sheet.saved, [])

    def test_plain_chat_in_order_group_is_ignored(self):
        self.bot.handle_event(ev(1, "o", "ok em", sender="Linh"))
        self.assertEqual(self.d["sale"].sent, [])

    def test_without_sheet_draft_cannot_be_saved(self):
        self.bot.order_sheet = None
        self.photo()
        self.assertIn("Chưa cài Google Sheet đơn hàng", self.bot.handle_telegram(BOSS, "N1 ok"))


if __name__ == "__main__":
    unittest.main()
