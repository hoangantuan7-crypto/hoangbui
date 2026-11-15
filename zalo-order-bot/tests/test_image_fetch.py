import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bot.crm_main import CRMBot
from bot.customer_info import candidate_urls, image_links
from bot.db import Store

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


class ZaloCRMFiles(BaseHTTPRequestHandler):
    """Giống ZaloCRM tự lưu ảnh: /files/… chỉ trả ảnh khi có X-API-Key đúng."""
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/files/") and self.headers.get("X-API-Key") == "k":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(PNG)
        else:
            self.send_response(401)
            self.end_headers()


class StubCRM:
    def __init__(self, base):
        self.base, self.api_key = base, "k"


class ImageFetchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ZaloCRMFiles)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_candidate_urls(self):
        self.assertEqual(candidate_urls("http://localhost:3080/files/a.jpg", "http://app:3000"),
                         ["http://app:3000/files/a.jpg", "http://localhost:3080/files/a.jpg"])
        self.assertEqual(candidate_urls("/files/a.jpg?w=1", "http://app:3000"), ["http://app:3000/files/a.jpg?w=1"])
        self.assertEqual(candidate_urls("https://f.zdn.vn/a.jpg", "http://app:3000"), ["https://f.zdn.vn/a.jpg"])

    def test_image_links_order(self):
        content = json.dumps({"thumb": "https://t/x.jpg", "href": "http://localhost:3080/files/x.jpg", "title": ""})
        self.assertEqual(image_links(content), ["http://localhost:3080/files/x.jpg", "https://t/x.jpg"])

    def test_localhost_link_is_fetched_from_zalocrm_with_api_key(self):
        bot = CRMBot(Store(":memory:"), StubCRM(self.base), "", "")
        data, ctype = bot.fetch_image(["http://localhost:3080/files/khach.png"])
        self.assertEqual((data, ctype), (PNG, "image/png"))

    def test_falls_back_to_thumbnail_then_reports_last_error(self):
        bot = CRMBot(Store(":memory:"), StubCRM(self.base), "", "")
        data, _ = bot.fetch_image(["http://127.0.0.1:1/khong-co.jpg", "/files/thumb.png"])
        self.assertEqual(data, PNG)
        with self.assertRaises(Exception):
            bot.fetch_image(["http://127.0.0.1:1/khong-co.jpg"])


if __name__ == "__main__":
    unittest.main()
