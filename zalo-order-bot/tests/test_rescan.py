import json
import unittest
from unittest import mock

from bot import crm_main
from bot.crm_main import CRMBot
from bot.customer_info import media_kind
from bot.db import Store
from test_groups import ShopCRM, grp, iso
from test_room import BOSS, FakeTG

HD_PHOTO = json.dumps({"title": "IMG_2041.jpg", "href": "http://localhost:3080/files/media/a.jpg",
                       "params": json.dumps({"fileExt": "jpg", "fileSize": 2400000})})
PDF = json.dumps({"title": "bao-gia.pdf", "href": "https://f.zdn.vn/x.pdf", "params": json.dumps({"fileExt": "pdf"})})
PHOTO = json.dumps({"href": "https://photo.zdn.vn/b.jpg", "hdUrl": "https://photo.zdn.vn/b_hd.jpg"})


class MediaKindTest(unittest.TestCase):
    def test_hd_photo_sent_as_file_is_an_image(self):
        self.assertEqual(media_kind("file", HD_PHOTO), ("image", "IMG_2041.jpg"))
        self.assertEqual(media_kind("image", PHOTO)[0], "image")
        self.assertEqual(media_kind("file", PDF), ("file", "bao-gia.pdf"))
        self.assertEqual(media_kind("text", "chào"), ("text", ""))
        self.assertEqual(media_kind("sticker", "{}")[0], "skip")


class RescanCRM(ShopCRM):
    def __init__(self):
        super().__init__()
        self.convs.append(grp("i", "g-info", "Thông tin khách hàng  AI", 60 * 20))
        self.msgs = {"i": [  # mới nhất trước
            {"id": "m3", "content": "ok", "contentType": "text", "senderName": "Linh", "sentAt": iso(hours=19)},
            {"id": "m2", "content": HD_PHOTO, "contentType": "file", "senderName": "Lê Tấn Phát", "sentAt": iso(hours=20)},
            {"id": "m1", "content": PHOTO, "contentType": "image", "senderName": "Linh", "sentAt": iso(days=5)},
        ]}

    def messages(self, cid, limit=30):
        return self.msgs.get(cid, [])


class RescanTest(unittest.TestCase):
    def setUp(self):
        self.crm, self.tg = RescanCRM(), FakeTG("VHDieuPhoiBot")
        self.bot = CRMBot(Store(":memory:"), self.crm, "", "", telegram=self.tg, pair_code="482913")
        self.bot.handle_telegram(BOSS, "/batdau 482913")
        self.read = mock.patch.object(crm_main, "read_image",
                                      return_value=([{"name": "Anh Trường", "phone": "", "address": "Sau Toà Án",
                                                      "note": "Bồn cầu 989VN", "date": "", "stt": ""}], "Ảnh (AI)"))
        self.read.start()
        self.addCleanup(self.read.stop)
        self.fetch = mock.patch.object(CRMBot, "fetch_image", return_value=(b"img", "image/jpeg"))
        self.fetch.start()
        self.addCleanup(self.fetch.stop)
        self.tg.sent.clear()

    def test_missed_hd_photo_is_read_again_once(self):
        self.bot.store.mark_seen("m2")  # bản cũ đã "thấy" ảnh HD nhưng bỏ qua, không báo gì
        self.assertIn("Đã đọc lại 1 ảnh", self.bot.rescan_docs(2))
        self.assertTrue(any("Anh Trường" in t for _, t in self.tg.sent))
        self.assertIn("Không có ảnh nào bị sót", self.bot.rescan_docs(2))
        self.assertIn("đọc lại ảnh", self.bot.handle_telegram(BOSS, "/quetlai nhom 2"))

    def test_network_error_keeps_message_for_next_poll(self):
        cursor = iso(days=1)
        self.bot.store.set_setting("poll_cursor", cursor)
        self.bot.store.set_setting("known_bootstrap", "1")
        with mock.patch.object(CRMBot, "handle_customer_info", side_effect=TimeoutError("timed out")):
            self.bot.poll_once()
        self.assertFalse(self.bot.store.is_seen("m2"))          # chưa đánh dấu -> lần sau đọc lại
        self.assertEqual(self.bot.store.get_setting("poll_cursor"), cursor)  # giữ mốc đọc
        self.bot.poll_once()
        self.assertTrue(self.bot.store.is_seen("doc:m2"))
        self.assertTrue(any("Anh Trường" in t for _, t in self.tg.sent))

    def test_gives_up_after_five_failures_and_tells_boss(self):
        self.bot.store.set_setting("poll_cursor", iso(days=1))
        self.bot.store.set_setting("known_bootstrap", "1")
        with mock.patch.object(CRMBot, "handle_customer_info", side_effect=TimeoutError("timed out")):
            for _ in range(5):
                self.bot.poll_once()
        self.assertTrue(any("lỗi 5 lần" in t for _, t in self.tg.sent))

    def test_pdf_in_info_group_is_reported_not_ignored(self):
        self.bot.handle_customer_info({"senderName": "Linh", "contentType": "file", "messageId": "x"}, PDF)
        self.assertIn("bao-gia.pdf", self.tg.sent[-1][1])


if __name__ == "__main__":
    unittest.main()
