"""Nhận diện tin nhắn khách có ý đặt hàng / hỏi hàng (không cần AI).

Chấm điểm theo từ khóa (viết không dấu). Cố tránh các từ dễ nhầm khi bỏ dấu:
"tu" (từ/tủ), "voi" (với/vòi), "chau" (cháu/chậu), "mua" (mua/mưa).
"""
import re

from .text import norm

ORDER_VERBS = [
    "dat hang", "dat them", "dat lam", "dat cho", "dat em", "dat anh", "dat chi", "dat mua", "muon dat",
    "len don", "chot don", "chot", "lay them", "lay cho", "lay em", "lay anh", "lay chi", "cho lay", "lay ",
    "mua them", "muon mua", "can mua", "order", "ship", "giao hang", "giao cho", "gui cho", "gui hang",
    "lam cho", "lam giup", "dong cho", "dong tu",
]
PRICE_ASK = ["bao gia", "gia bao nhieu", "bao nhieu tien", "gia sao", "het bao nhieu", "gia the nao",
             "con hang", "co hang", "co san", "con khong", "con ko", "con k "]
PRODUCTS = [
    "lavabo", "tu chau", "tu guong", "tu ban", "tu treo", "tu go", "tu nhom", "tu nhua", "tu 60", "tu 70", "tu 80",
    "tu 90", "tu 100", "tu 120", "guong", "voi sen", "voi lavabo", "voi rua", "voi nuoc", "voi xit", "sen tam",
    "bo sen", "sen cay", "bon cau", "bon tam", "chau rua", "chau lavabo", "xi phong", "ke kinh", "ke guong",
    "phu kien", "thoat san", "ban da", "mat da", "vach kinh", "bon tieu", "may say tay",
]
QTY_RE = re.compile(r"\b\d+\s*(?:cai|bo|chiec|c|b|tam|met|m)\b|\b\d{2,3}\s*(?:cm|x\s*\d{2,3})\b|\bx\s*\d+\b|\bsl\s*\d+")


def order_intent(text: str) -> int:
    """Điểm 0..5. >=3 coi là tin đặt hàng / hỏi hàng cần báo."""
    key = f" {norm(text)} "
    score = 0
    if any(f" {v}" in key for v in ORDER_VERBS):
        score += 2
    if any(p in key for p in PRICE_ASK):
        score += 1
    if any(p in key for p in PRODUCTS):
        score += 2
    if QTY_RE.search(key):
        score += 1
    return min(score, 5)


def is_order_message(text: str, threshold: int = 3) -> bool:
    return order_intent(text) >= threshold


PAYMENT = ["chuyen khoan", "da ck", "ck roi", "ck xong", "dat coc", "coc truoc", "da coc", "thanh toan", "bill"]


def classify(text: str) -> str | None:
    """'order' (đặt/hỏi hàng), 'payment' (báo chuyển khoản/cọc) hoặc None."""
    key = f" {norm(text)} "
    if any(f" {p}" in key for p in PAYMENT):
        return "payment"
    return "order" if is_order_message(text) else None
