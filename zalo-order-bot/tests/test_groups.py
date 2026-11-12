import unittest
from datetime import datetime, timedelta, timezone

from bot.crm_main import CRMBot
from bot.db import Store
from test_room import BOSS, FakeTG


def iso(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat().replace("+00:00", "Z")


def grp(cid, thread, name, minutes_ago, contact_id=None):
    return {"id": cid, "threadType": "group", "externalThreadId": thread, "lastMessageAt": iso(minutes=minutes_ago),
            "contact": {"id": contact_id or f"ct-{thread}", "fullName": name, "phone": None}}


class ShopCRM:
    """ZaloCRM giả lập giống máy anh: nhóm ĐẶT HÀNG có cả 2 nick shop -> xuất hiện 2 lần."""

    def __init__(self):
        self.convs = [
            grp("a1", "g-dathang", "ĐẶT HÀNG – BẢO HÀNH SHOWROOM TẤN PHÁT", 1),
            grp("a2", "g-dathang", "ĐẶT HÀNG – BẢO HÀNH SHOWROOM TẤN PHÁT", 2),
            grp("b", "g-lan", "TBVS CHỊ HOÀNG LAN TRUNG SONG", 30),
            grp("c", "g-clb", "CLB kết nối Doanh Nghiệp NAU", 60),
            grp("d", "g-phi", "PHÍ GIAO NHẬN HÀNG SHOWROOM TẤN PHÁT ( check test nội bộ )", 90),
        ]
        self.created = {}  # contact_id -> createdAt
        self.sent = []

    def refresh_conversations(self):
        return list(self.convs)

    def conversation(self, cid):
        return next((c for c in self.convs if c["id"] == cid), None)

    def contact(self, contact_id):
        return {"id": contact_id, "createdAt": self.created.get(contact_id, iso(days=60))}

    def messages(self, cid, limit=30):
        return []

    def send(self, *a):
        self.sent.append(a)


def ev(i, conv, text, sender="Chị Lan", sent_at=None):
    return {"source": "hỏi định kỳ", "event": "message.received",
            "data": {"messageId": f"m{i}", "conversationId": conv, "content": text, "contentType": "text",
                     "senderName": sender, "sentAt": sent_at or iso(minutes=0)}}


class GroupsTest(unittest.TestCase):
    def setUp(self):
        self.crm, self.dp = ShopCRM(), FakeTG("VHDieuPhoiBot")
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.dp, pair_code="482913", scan_groups="0")
        self.bot.handle_telegram(BOSS, "/batdau 482913")
        self.dp.sent.clear()

    def test_listing_merges_duplicate_group_and_numbers_it(self):
        text = self.bot.handle_telegram(BOSS, "/nhom")
        self.assertEqual(text.count("ĐẶT HÀNG – BẢO HÀNH"), 1)
        self.assertIn(" 1. ❓ ĐẶT HÀNG", text)
        self.assertIn(" 4. ❓ PHÍ GIAO NHẬN", text)

    def test_classify_by_number_and_by_start_of_name(self):
        self.bot.handle_telegram(BOSS, "/nhom")
        r = self.bot.handle_telegram(BOSS, "/nhom noibo 1, PHÍ GIAO NHẬN HÀNG SHOWROOM")
        self.assertIn("✅ 👥 nội bộ", r)
        self.assertNotIn("Không tìm thấy", r)
        r = self.bot.handle_telegram(BOSS, "/nhom khách TBVS CHỊ HOÀNG LAN TRUNG SONG")
        self.assertIn("🏠 TBVS CHỊ HOÀNG LAN TRUNG SONG – khách hàng", r)
        r = self.bot.handle_telegram(BOSS, "/nhom bỏ qua 3, 99")
        self.assertIn("🔕 CLB kết nối Doanh Nghiệp NAU – bỏ qua", r)
        self.assertIn("Không tìm thấy: 99", r)
        r = self.bot.handle_telegram(BOSS, "/nhom xoa 3")
        self.assertIn("❓ CLB kết nối Doanh Nghiệp NAU – chưa xếp loại", r)

    def test_customer_group_tracked_internal_group_not(self):
        self.bot.handle_telegram(BOSS, "/nhom khach TBVS CHỊ HOÀNG LAN")
        self.bot.handle_telegram(BOSS, "/nhom noibo ĐẶT HÀNG – BẢO HÀNH")
        self.bot.handle_event(ev(1, "a1", "đặt 2 tủ lavabo 80 cho chị Lan", sender="Lê Tấn Phát"))
        self.assertEqual(self.dp.sent, [])                     # nhóm nội bộ: không đọc
        self.bot.handle_event(ev(2, "b", "em lấy thêm 2 vòi sen nhé"))
        self.assertIn("Chị Lan (nhóm TBVS CHỊ HOÀNG LAN TRUNG SONG)", self.dp.to(BOSS)[-1])  # SCAN_GROUPS=0 vẫn theo dõi
        self.assertIn("Chị Lan", self.bot.unanswered_text())

    def test_same_message_seen_from_two_shop_accounts_is_reported_once(self):
        self.bot.handle_telegram(BOSS, "/nhom khach ĐẶT HÀNG – BẢO HÀNH")
        t = iso(minutes=0)
        self.bot.handle_event(ev(1, "a1", "anh ơi bảo hành vòi sen giúp em", sender="Khách A", sent_at=t))
        self.bot.handle_event(ev(2, "a2", "anh ơi bảo hành vòi sen giúp em", sender="Khách A", sent_at=t))
        self.assertEqual(len(self.dp.to(BOSS)), 1)
        self.assertEqual(len(self.bot.waiting_rows()), 1)

    def test_new_group_and_new_customer_are_announced_once(self):
        self.bot.poll_once()                                   # lần đầu: ghi nhận nhóm đang có, không báo
        self.assertEqual(self.dp.sent, [])
        self.crm.convs.append(grp("n", "g-new", "TBVS ANH BÌNH CỬA LÒ", 0, contact_id="ct-new"))
        self.crm.created["ct-new"] = iso(hours=1)
        self.bot.handle_event(ev(5, "n", "chào shop", sender="Anh Bình"))
        self.assertIn("🆕 NHÓM MỚI: TBVS ANH BÌNH CỬA LÒ", self.dp.to(BOSS)[0])
        self.assertIn("/nhom khach TBVS ANH BÌNH CỬA LÒ", self.dp.to(BOSS)[0])
        self.crm.convs.append({"id": "p", "threadType": "user", "externalThreadId": "u-p", "lastMessageAt": iso(),
                               "contact": {"id": "ct-p", "fullName": "Chị Mai", "phone": "0911"}})
        self.crm.created["ct-p"] = iso(minutes=5)
        self.bot.handle_event(ev(6, "p", "shop ơi tủ lavabo 60 giá bao nhiêu", sender="Chị Mai"))
        self.assertTrue(any("🆕 KHÁCH MỚI: Chị Mai (0911)" in t for t in self.dp.to(BOSS)))
        n = len(self.dp.to(BOSS))
        self.bot.handle_event(ev(7, "p", "shop ơi", sender="Chị Mai"))
        self.assertFalse(any("KHÁCH MỚI" in t for t in self.dp.to(BOSS)[n:]))  # chỉ báo 1 lần

    def test_old_customer_coming_back_is_not_called_new(self):
        self.bot.poll_once()
        self.crm.convs.append({"id": "q", "threadType": "user", "externalThreadId": "u-q", "lastMessageAt": iso(),
                               "contact": {"id": "ct-q", "fullName": "Anh Cũ", "phone": ""}})
        self.bot.handle_event(ev(8, "q", "chào shop", sender="Anh Cũ"))
        self.assertFalse(any("KHÁCH MỚI" in t for t in self.dp.to(BOSS)))

    def test_new_group_already_classified_internal_is_not_announced(self):
        self.bot.poll_once()
        self.bot.handle_telegram(BOSS, "/nhom noibo NHÓM KHO MỚI")
        self.crm.convs.append(grp("k", "g-kho", "NHÓM KHO MỚI", 0, contact_id="ct-kho"))
        self.crm.created["ct-kho"] = iso(hours=1)
        self.dp.sent.clear()
        self.bot.handle_event(ev(9, "k", "nhập 20 vòi sen", sender="Phát"))
        self.assertEqual(self.dp.sent, [])


if __name__ == "__main__":
    unittest.main()
