import unittest
from datetime import datetime, timedelta

from bot import reports
from bot.db import Store
from bot.handlers import handle_message
from bot.parser import parse_command, parse_order, parse_product_qty
from bot.zalo import extract_message, split_text


class ParserTest(unittest.TestCase):
    def test_single_line_order(self):
        o = parse_order("Đơn anh Nam 0912 345 678: 2 tủ lavabo 80cm; 5 vòi sen")
        self.assertEqual(o.customer, "anh Nam")
        self.assertEqual(o.phone, "0912345678")
        self.assertEqual(o.items, [("tủ lavabo 80cm", 2.0), ("vòi sen", 5.0)])

    def test_multi_line_order_with_note(self):
        o = parse_order("don chi Lan\n- tủ lavabo 60cm x1\n- gương LED 60x80 sl 2\nvòi lavabo\nGhi chú: giao thứ 7")
        self.assertEqual(o.customer, "chi Lan")
        self.assertEqual(o.items, [("tủ lavabo 60cm", 1.0), ("gương LED 60x80", 2.0), ("vòi lavabo", 1.0)])
        self.assertEqual(o.note, "giao thứ 7")

    def test_not_an_order(self):
        self.assertIsNone(parse_order("Chào anh, mai em qua lấy hàng"))

    def test_commands(self):
        self.assertEqual(parse_command("/thiếu").name, "thieu")
        self.assertEqual(parse_command("/giao 12 vòi sen 2").args, "12 vòi sen 2")
        self.assertIsNone(parse_command("không phải lệnh"))
        self.assertEqual(parse_product_qty("vòi sen 10"), ("vòi sen", 10.0))


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")

    def test_shortage_allocates_oldest_first(self):
        t0 = datetime(2026, 11, 1)
        self.s.add_stock("vòi sen", 4)
        self.s.add_order("Anh Nam", [("vòi sen", 3)], created_at=t0.isoformat())
        self.s.add_order("Chị Lan", [("vòi sen", 3)], created_at=(t0 + timedelta(days=1)).isoformat())
        text = reports.report_shortage(self.s)
        self.assertIn("Chị Lan", text)
        self.assertNotIn("Anh Nam", text)
        self.assertIn("thiếu 2/3", text)

    def test_lavabo_flow(self):
        oid = self.s.add_order("Anh Hùng", [("tủ lavabo 80cm trắng", 1), ("vòi sen", 1)])
        self.assertIn("Anh Hùng", reports.report_lavabo(self.s))
        self.s.mark_factory_ordered(oid)
        self.assertIn("Không còn tủ lavabo", reports.report_lavabo(self.s))
        # tủ lavabo không tính vào thiếu hàng kho
        self.assertNotIn("tủ lavabo", reports.report_shortage(self.s))

    def test_reorder_supplier_and_customer_cycle(self):
        now = datetime(2026, 11, 30)
        for d in (1, 8, 15):
            oid = self.s.add_order("Đại lý Minh", [("gương LED", 1)], created_at=datetime(2026, 11, d).isoformat())
            self.s.deliver(oid)
        self.s.add_stock("xi phông", 1, min_qty=5)
        text = reports.report_reorder(self.s, now)
        self.assertIn("xi phông: đặt thêm 4", text)
        self.assertIn("Đại lý Minh: 15 ngày chưa đặt", text)

    def test_handle_message_end_to_end(self):
        reply = handle_message(self.s, "Đơn anh Tú: 1 tủ lavabo 60cm; 2 vòi sen", "c1", "Tú", use_ai=False)
        self.assertIn("#1", reply)
        self.assertIn("cần đặt xưởng", reply)
        self.assertIn("anh Tú", handle_message(self.s, "/thieu", "c1"))
        self.assertIn("đã ghi nhận", handle_message(self.s, "/datxuong 1", "c1"))
        self.assertIn("vòi sen", handle_message(self.s, "/giao 1 vòi sen 2", "c1"))
        self.assertIn("đã giao đủ", handle_message(self.s, "/giao 1", "c1"))
        self.assertIsNone(handle_message(self.s, "ok em", "c1", use_ai=False))
        self.assertIn("⚠️", handle_message(self.s, "/giao", "c1"))


class ZaloTest(unittest.TestCase):
    def test_extract_message(self):
        upd = {"message": {"from": {"id": "u1", "display_name": "Nam", "is_bot": False},
                           "chat": {"id": "g1", "chat_type": "GROUP"}, "text": "/thieu"},
               "event_name": "message.text.received"}
        self.assertEqual(extract_message(upd), ("g1", "/thieu", "Nam"))
        self.assertIsNone(extract_message({"message": {"from": {"is_bot": True}, "chat": {"id": 1}, "text": "x"}}))

    def test_split_text(self):
        chunks = split_text("\n".join(["a" * 900] * 5))
        self.assertTrue(all(len(c) <= 2000 for c in chunks))
        self.assertEqual(len(chunks), 3)


if __name__ == "__main__":
    unittest.main()
