"""Đọc tin nhắn đơn hàng tiếng Việt (không cần AI).

Hiểu được các dạng:
    Đơn anh Nam 0912345678: 2 tủ lavabo 80cm; 5 vòi sen
    don chi Lan
    - tủ lavabo 60cm x1
    - gương LED 60x80 sl 2
"""
import re
from dataclasses import dataclass, field

from .text import norm

PHONE_RE = re.compile(r"(?:\+?84|0)\d{9,10}")
ORDER_PREFIX_RE = re.compile(r"^\s*/?(?:đơn|don|đơn hàng|don hang|order)\b[\s:.-]*", re.IGNORECASE)
NUM = r"(\d+(?:[.,]\d+)?)"
QTY_PATTERNS = [
    re.compile(rf"^{NUM}\s*(?:cái|cai|bộ|bo|chiếc|chiec|c|b)?\s+(.+)$", re.IGNORECASE),        # 2 tủ lavabo
    re.compile(rf"^(.+?)\s*(?:x|\*|×)\s*{NUM}\s*(?:cái|cai|bộ|bo|chiếc|chiec)?$", re.IGNORECASE),  # tủ lavabo x2
    re.compile(rf"^(.+?)\s+(?:sl|số lượng|so luong|sl:)\s*:?\s*{NUM}.*$", re.IGNORECASE),        # tủ lavabo sl 2
    re.compile(rf"^(.+?)\s*[:=-]\s*{NUM}\s*(?:cái|cai|bộ|bo|chiếc|chiec)?$", re.IGNORECASE),       # tủ lavabo: 2
]


@dataclass
class ParsedOrder:
    customer: str
    items: list[tuple[str, float]] = field(default_factory=list)
    phone: str = ""
    note: str = ""


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_item(text: str) -> tuple[str, float] | None:
    text = text.strip(" -•*+\t.")
    if not text:
        return None
    for i, pat in enumerate(QTY_PATTERNS):
        m = pat.match(text)
        if m:
            if i == 0:
                qty, product = _num(m.group(1)), m.group(2)
            else:
                product, qty = m.group(1), _num(m.group(2))
            product = product.strip(" -:")
            if product and qty > 0:
                return product, qty
    return text, 1.0


def split_items(body: str) -> list[str]:
    return [p for p in re.split(r"[\n;+]|,\s*(?=\d)", body) if p.strip()]


def parse_order(message: str, default_customer: str = "") -> ParsedOrder | None:
    """Trả về ParsedOrder nếu tin nhắn bắt đầu bằng 'Đơn ...', ngược lại None.

    default_customer: tên khách dùng khi tin nhắn không ghi tên (vd. gõ "Đơn: 2 tủ lavabo"
    ngay trong cuộc chat với khách)."""
    if not ORDER_PREFIX_RE.match(message):
        return None
    body = ORDER_PREFIX_RE.sub("", message, count=1)
    lines = body.split("\n", 1)
    head = lines[0]
    rest = lines[1] if len(lines) > 1 else ""
    if ":" in head:
        customer_part, first_items = head.split(":", 1)
    else:
        customer_part, first_items = head, ""
    if default_customer and re.match(r"^\s*\d", customer_part):  # "Đơn 2 tủ lavabo" -> chỉ có hàng
        customer_part, first_items = "", head
    note = ""
    note_m = re.search(r"(?:ghi chú|ghi chu|gc|note)\s*:\s*(.+)$", rest, re.IGNORECASE | re.MULTILINE)
    if note_m:
        note = note_m.group(1).strip()
        rest = rest[: note_m.start()] + rest[note_m.end():]
    phone_m = PHONE_RE.search(customer_part.replace(" ", "").replace(".", ""))
    phone = phone_m.group(0) if phone_m else ""
    customer = PHONE_RE.sub("", re.sub(r"(?<=\d)[ .](?=\d)", "", customer_part)).strip(" -,:")
    customer = customer or default_customer.strip()
    if not customer:
        return None
    items = [it for it in (parse_item(p) for p in split_items(first_items + "\n" + rest)) if it]
    if not items:
        return None
    return ParsedOrder(customer=customer, items=items, phone=phone, note=note)


@dataclass
class Command:
    name: str
    args: str


COMMAND_ALIASES = {
    "don": "don", "đơn": "don",
    "giao": "giao", "nhap": "nhap", "nhập": "nhap", "ton": "ton", "tồn": "ton",
    "toithieu": "toithieu", "min": "toithieu",
    "datxuong": "datxuong", "xuong": "datxuong",
    "huy": "huy", "hủy": "huy", "xem": "xem",
    "thieu": "thieu", "thiếu": "thieu", "lavabo": "lavabo", "nhac": "nhac", "nhắc": "nhac",
    "baocao": "baocao", "bc": "baocao", "donmo": "donmo",
    "xong": "xong", "choxuly": "choxuly", "cho": "choxuly",
    "chuyen": "chuyen", "chuyển": "chuyen", "bophan": "bophan", "bộphận": "bophan",
    "dangky": "dangky", "huydangky": "huydangky", "help": "help", "start": "help", "hd": "help",
}


def parse_command(message: str) -> Command | None:
    m = re.match(r"^\s*/(\S+)\s*(.*)$", message, re.DOTALL)
    if not m:
        return None
    raw = m.group(1).split("@")[0]
    name = COMMAND_ALIASES.get(raw.lower()) or COMMAND_ALIASES.get(norm(raw).replace(" ", ""))
    return Command(name, m.group(2).strip()) if name else None


def parse_product_qty(args: str) -> tuple[str, float] | None:
    """'vòi sen 10' / '10 vòi sen' / 'vòi sen x10'."""
    m = re.match(rf"^(.+?)\s+{NUM}$", args.strip())
    if m:
        return m.group(1).strip(), _num(m.group(2))
    if re.search(r"\d", args):
        return parse_item(args)
    return None


def looks_like_order(message: str) -> bool:
    """Gợi ý để gọi AI cho tin nhắn tự do."""
    key = norm(message)
    return bool(re.search(r"\b(dat|lay|chot|giao|order|can)\b", key)) and bool(re.search(r"\d", key))
