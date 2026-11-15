"""Nhóm Zalo "THÔNG TIN KHÁCH HÀNG": anh chụp/gõ thông tin khách -> bot ghi vào Google Sheet.

Nguồn vào (đều được):
  • Ảnh chụp màn hình / phiếu in / giấy viết tay. Có ANTHROPIC_API_KEY -> Claude Haiku đọc ảnh (đọc được cả chữ
    viết tay); không có -> đọc chữ miễn phí bằng Tesseract (tốt với ảnh chụp màn hình, phiếu in).
  • Tin gõ tay: "KH: Chị Lan | 0912345678 | Diễn Châu | ghi chú" hoặc nhiều dòng "Tên: …", "SĐT: …", "Địa chỉ: …".
Một ảnh có danh sách nhiều khách (có cột STT) -> mỗi khách 1 dòng.

Google Sheet nhận dữ liệu qua Apps Script (web app) – xem google-sheet/AppsScript.gs.
"""
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request

from .text import norm

log = logging.getLogger(__name__)
VISION_MODEL = os.environ.get("CLAUDE_VISION_MODEL", "claude-haiku-5-5")  # rẻ nhất, đủ để đọc ảnh thông tin khách
MAX_IMAGE_BYTES = 10 * 1024 * 1024

PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){9}(?!\d)")
LABELS = {
    "name": ["ho ten", "ho va ten", "ten khach hang", "ten khach", "ten kh", "khach hang", "ten", "kh"],
    "phone": ["so dien thoai", "dien thoai", "sdt", "dt", "phone", "zalo", "so dt"],
    "address": ["dia chi", "dc", "d/c", "nha o", "o tai", "cong trinh"],
    "note": ["ghi chu", "gc", "note", "nhu cau", "can", "san pham"],
    "date": ["ngay them", "ngay", "date"],
}


def clean_phone(text: str) -> str:
    digits = re.sub(r"\D", "", text or "")
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if len(digits) == 10 and digits.startswith("0") else ""


def _label_of(key_part: str) -> str | None:
    k = norm(key_part).strip()
    for field, names in LABELS.items():
        if k in names:
            return field
    return None


def parse_text(text: str) -> list[dict]:
    """Đọc thông tin khách từ chữ (tin gõ tay hoặc chữ OCR). Trả về danh sách khách."""
    text = (text or "").strip()
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # 1) Mẫu "KH: Tên | SĐT | Địa chỉ | ghi chú" (mỗi dòng 1 khách)
    piped = []
    for ln in lines:
        body = re.sub(r"^(?:kh|khách|khach|khách hàng|khach hang)\s*[:\-]\s*", "", ln, flags=re.IGNORECASE)
        if "|" in body:
            parts = [p.strip() for p in body.split("|")]
            phone_i = next((i for i, p in enumerate(parts) if clean_phone(p)), None)
            name = parts[0] if phone_i != 0 else ""
            rest = [p for i, p in enumerate(parts) if i not in (0, phone_i)]
            piped.append({"name": name, "phone": clean_phone(parts[phone_i]) if phone_i is not None else "",
                          "address": rest[0] if rest else "", "note": " | ".join(rest[1:])})
    if piped:
        return piped
    # 2) Các dòng có nhãn "Tên: …", "SĐT: …", "Địa chỉ: …" (1 khách)
    fields: dict[str, str] = {}
    for ln in lines:
        m = re.match(r"^([^:：]{1,20})[:：]\s*(.+)$", ln)
        field = _label_of(m.group(1)) if m else None
        if field and field not in fields:
            fields[field] = m.group(2).strip()
    if fields.get("name") or fields.get("phone"):
        phone = clean_phone(fields.get("phone", "")) or next((clean_phone(p) for p in PHONE_RE.findall(text)), "")
        return [{"name": fields.get("name", ""), "phone": phone, "address": fields.get("address", ""),
                 "note": fields.get("note", ""), "date": fields.get("date", "")}]
    # 3) Danh sách/bảng: mỗi dòng có 1 SĐT -> 1 khách; tên ở trước SĐT, địa chỉ ở sau
    rows = []
    for ln in lines:
        m = PHONE_RE.search(ln)
        if not m:
            continue
        before = re.sub(r"^\s*\d{1,3}\s*[._)\-|:]*\s+", "", ln[:m.start()]).strip(" |,-–:\t")
        after = ln[m.end():].strip(" |,-–:\t")
        rows.append({"name": before, "phone": clean_phone(m.group(0)), "address": after, "note": ""})
    return rows


def is_complete(c: dict) -> bool:
    return bool(c.get("name")) and bool(c.get("phone"))


# ---------- ảnh ----------
def image_links(content: str) -> list[str]:
    """Mọi link ảnh có trong tin (ảnh gốc trước, ảnh thu nhỏ sau) – dùng khi link đầu tải không được."""
    try:
        data = json.loads(content or "")
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    keys = ("href", "hdUrl", "normalUrl", "url", "thumb", "thumbUrl")
    return [str(data[k]) for k in keys if isinstance(data.get(k), str)
            and str(data[k]).startswith(("http://", "https://", "/"))]


def image_url(content: str) -> tuple[str, str]:
    """Link ảnh + chú thích từ nội dung tin ảnh của ZaloCRM ({"href": …, "title": …})."""
    try:
        data = json.loads(content or "")
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        return "", ""
    links = image_links(content)
    caption = data.get("title") or data.get("description") or ""
    return (links[0] if links else ""), str(caption or "")


LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "app", "zalo-crm-app"}


def candidate_urls(url: str, crm_base: str) -> list[str]:
    """ZaloCRM tự lưu ảnh (Kho ảnh) và đưa link kiểu http://localhost:3080/… hoặc /files/…:
    trong container bot, "localhost" là chính bot -> đổi sang địa chỉ ZaloCRM nội bộ (vd http://app:3000)."""
    p = urllib.parse.urlparse(url)
    if crm_base and (not p.netloc or (p.hostname or "") in LOCAL_HOSTS):
        local = crm_base.rstrip("/") + (p.path or "/") + (f"?{p.query}" if p.query else "")
        return [local] + ([url] if p.netloc else [])
    return [url]


def download(url: str, headers: dict | None = None) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read(MAX_IMAGE_BYTES + 1)
        ctype = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Ảnh quá lớn (trên 10MB)")
    if not ctype.startswith("image/"):
        ctype = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return data, ctype


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr(image: bytes) -> str:
    """Đọc chữ trong ảnh bằng Tesseract (tiếng Việt). Miễn phí, chạy trên máy."""
    with tempfile.NamedTemporaryFile(suffix=".img") as f:
        f.write(image)
        f.flush()
        out = subprocess.run(["tesseract", f.name, "stdout", "-l", "vie+eng", "--psm", "6"],
                             capture_output=True, timeout=120)
    return out.stdout.decode("utf-8", "ignore")


SCHEMA = {
    "type": "object",
    "properties": {
        "customers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "stt": {"type": "string"}, "name": {"type": "string"}, "phone": {"type": "string"},
                    "address": {"type": "string"}, "date": {"type": "string"}, "note": {"type": "string"},
                    "unclear": {"type": "boolean", "description": "true nếu có chữ đọc không chắc"},
                },
                "required": ["stt", "name", "phone", "address", "date", "note", "unclear"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["customers"],
    "additionalProperties": False,
}
PROMPT = (
    "Ảnh này là thông tin khách hàng của một cửa hàng thiết bị vệ sinh, nhà bếp (chụp màn hình, phiếu in hoặc "
    "giấy viết tay tiếng Việt). Đọc và trả về MỌI khách hàng có trong ảnh: số thứ tự (nếu có), họ tên, số điện "
    "thoại (chỉ chữ số), địa chỉ, ngày (nếu có, dạng dd/mm/yyyy), ghi chú (nhu cầu, sản phẩm…). Giữ nguyên dấu "
    "tiếng Việt. Không đoán bừa: phần không đọc được để trống và đặt unclear=true. Ảnh không có thông tin khách "
    "-> customers rỗng."
)


def ai_read(image: bytes, media_type: str, caption: str = "") -> list[dict] | None:
    """Claude đọc ảnh -> danh sách khách. None nếu không gọi được AI."""
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=VISION_MODEL,
            max_tokens=4000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                             "data": base64.standard_b64encode(image).decode()}},
                {"type": "text", "text": PROMPT + (f"\nChú thích kèm ảnh: {caption}" if caption else "")},
            ]}],
        )
    except anthropic.APIConnectionError as e:
        log.warning("Không kết nối được Claude: %s", e)
        return None
    except anthropic.APIStatusError as e:
        log.warning("Claude trả lỗi %s: %s", e.status_code, e.message)
        return None
    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    text = next((b.text for b in response.content if b.type == "text"), "")
    customers = json.loads(text).get("customers", [])
    for c in customers:
        c["phone"] = clean_phone(c.get("phone", ""))
    return customers


def read_image(image: bytes, media_type: str, caption: str = "") -> tuple[list[dict], str]:
    """Đọc ảnh: ưu tiên AI (đọc được chữ viết tay), không có thì OCR miễn phí. Trả về (khách, cách đọc)."""
    from .ai_parser import ai_available

    if ai_available():
        found = ai_read(image, media_type, caption)
        if found is not None:
            return found, "Ảnh (AI)"
    if ocr_available():
        return parse_text(ocr(image) + ("\n" + caption if caption else "")), "Ảnh (OCR)"
    return [], "Ảnh (chưa đọc được)"


# ---------- Google Sheet ----------
class SheetWriter:
    """Ghi 1 khách vào Google Sheet qua Apps Script web app (URL + mã bí mật)."""

    def __init__(self, url: str, token: str):
        self.url, self.token = url, token

    def append(self, row: dict) -> dict:
        body = json.dumps({**row, "token": self.token}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:  # Apps Script chuyển hướng 302 -> urllib tự theo
            return json.loads(resp.read().decode() or "{}")
