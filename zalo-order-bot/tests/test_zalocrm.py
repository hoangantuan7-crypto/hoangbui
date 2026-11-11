import hashlib
import hmac
import unittest

from bot.crm_main import CRMBot
from bot.db import Store
from bot.zalocrm import verify_signature

from tests_helpers import CONVS, FakeCRM, msg


class CRMBotTest(unittest.TestCase):
    def setUp(self):
        self.crm = FakeCRM()
        self.bot = CRMBot(Store(":memory:"), self.crm, "Bot đơn hàng")
        self.bot.handle_event({"event": "zalo.connected", "data": {"accountId": "acc-1"}})

    def test_command_in_report_group_replies_there(self):
        self.bot.handle_event(msg("message.received", "c-group", "Đơn chị Lan: 2 tủ lavabo 60cm"))
        self.bot.handle_event(msg("message.received", "c-group", "/lavabo"))
        self.assertEqual(len(self.crm.sent), 2)
        acc, thread, text = self.crm.sent[1]
        self.assertEqual((acc, thread), ("acc-1", "g99"))
        self.assertIn("chị Lan", text)

    def test_order_typed_in_customer_chat_uses_contact_and_never_messages_customer(self):
        self.bot.handle_event(msg("message.sent", "c-nam", "Đơn 1 tủ lavabo 80cm; 2 vòi sen"))
        self.assertEqual(len(self.crm.sent), 1)
        _, thread, text = self.crm.sent[0]
        self.assertEqual(thread, "g99")
        self.assertIn("Anh Nam (0912345678)", text)

    def test_customer_cannot_run_commands_and_echo_is_ignored(self):
        self.bot.handle_event(msg("message.received", "c-nam", "/baocao"))
        self.assertEqual(self.crm.sent, [])
        self.bot.handle_event(msg("message.received", "c-group", "/thieu"))
        echoed = self.crm.sent[0][2]
        self.bot.handle_event(msg("message.sent", "c-group", echoed))
        self.assertEqual(len(self.crm.sent), 1)

    def test_customer_order_message_alerts_once_and_reminds(self):
        from datetime import datetime, timedelta
        self.bot.handle_event(msg("message.received", "c-nam", "Anh ơi lấy em 2 tủ lavabo 80cm nhé"))
        self.bot.handle_event(msg("message.received", "c-nam", "màu trắng nha anh"))  # gộp, không báo trùng
        self.bot.handle_event(msg("message.received", "c-nam", "Ok cảm ơn anh"))
        self.assertEqual(len(self.crm.sent), 1)
        _, thread, alert = self.crm.sent[0]
        self.assertEqual(thread, "g99")  # báo vào nhóm, không nhắn cho khách
        self.assertIn("KHÁCH ĐẶT HÀNG", alert)
        self.assertIn("Anh Nam (0912345678)", alert)
        self.assertIn("K1", alert)
        # quá 30 phút chưa xử lý -> nhắc lại 1 lần
        later = datetime.now() + timedelta(minutes=31)
        self.assertTrue(self.bot.remind_pending(30, later))
        self.assertIn("CHƯA XỬ LÝ", self.crm.sent[-1][2])
        self.assertFalse(self.bot.remind_pending(30, later))
        # /xong trong nhóm -> hết trong danh sách chờ
        self.bot.handle_event(msg("message.received", "c-group", "/xong K1"))
        self.bot.handle_event(msg("message.received", "c-group", "/choxuly"))
        self.assertIn("Không có tin khách", self.crm.sent[-1][2])

    def test_payment_message_and_owner_reply_stops_reminder(self):
        from datetime import datetime, timedelta
        self.bot.handle_event(msg("message.received", "c-nam", "Em chuyển khoản rồi nhé anh"))
        self.assertIn("CHUYỂN KHOẢN", self.crm.sent[0][2])
        self.bot.handle_event(msg("message.sent", "c-nam", "Dạ em nhận được rồi ạ"))
        self.assertFalse(self.bot.remind_pending(30, datetime.now() + timedelta(minutes=31)))

    def test_polling_picks_up_new_messages_once_and_ignores_history(self):
        CONVS["c-nam"]["lastMessageAt"] = "2026-11-11T14:00:00.000Z"
        CONVS["c-group"]["lastMessageAt"] = "2026-11-11T14:00:00.000Z"
        self.crm.msgs["c-nam"] = [{"id": "m0", "senderType": "contact", "content": "lấy 2 tủ lavabo cũ",
                                   "contentType": "text", "sentAt": "2026-11-11T14:00:00.000Z"}]
        self.assertEqual(self.bot.poll_once(), 0)  # lần đầu: không quét lịch sử
        self.crm.msgs["c-nam"].append({"id": "m1", "senderType": "contact", "content": "Anh ơi lấy em 2 tủ lavabo 80 nhé",
                                       "contentType": "text", "sentAt": "2026-11-11T14:05:00.000Z"})
        self.crm.msgs["c-group"] = [{"id": "g1", "senderType": "contact", "content": "/help",
                                     "contentType": "text", "sentAt": "2026-11-11T14:06:00.000Z"}]
        CONVS["c-nam"]["lastMessageAt"] = "2026-11-11T14:05:00.000Z"
        CONVS["c-group"]["lastMessageAt"] = "2026-11-11T14:06:00.000Z"
        self.assertEqual(self.bot.poll_once(), 2)
        texts = [t for _, _, t in self.crm.sent]
        self.assertEqual(len(texts), 2)
        self.assertTrue(any("KHÁCH ĐẶT HÀNG" in t for t in texts))
        self.assertTrue(any("BOT ĐƠN HÀNG" in t for t in texts))
        self.assertEqual(self.bot.poll_once(), 0)  # không xử lý lại
        # cùng tin đến lại qua webhook -> bỏ qua
        self.bot.handle_event({"event": "message.received", "data": {"messageId": "m1", "conversationId": "c-nam",
                               "content": "Anh ơi lấy em 2 tủ lavabo 80 nhé", "contentType": "text"}})
        self.assertEqual(len(self.crm.sent), 2)

    def test_community_groups_are_not_scanned_by_default(self):
        CONVS["c-clb"] = {"id": "c-clb", "threadType": "group", "externalThreadId": "g5",
                          "contact": {"fullName": "CLB Pickleball"}}
        try:
            self.bot.handle_event(msg("message.received", "c-clb", "lấy em 2 áo size M ship nhé"))
            self.assertEqual(self.crm.sent, [])
        finally:
            del CONVS["c-clb"]

    def test_signature(self):
        body = b'{"event":"x"}'
        sig = hmac.new(b"secret123", body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature("secret123", body, sig))
        self.assertFalse(verify_signature("secret123", body, "bad"))


if __name__ == "__main__":
    unittest.main()
