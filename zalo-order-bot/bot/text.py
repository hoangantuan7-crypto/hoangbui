"""Tiện ích xử lý chữ tiếng Việt."""
import re
import unicodedata


def strip_accents(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def norm(text: str) -> str:
    """Bỏ dấu, chữ thường, gọn khoảng trắng -> dùng làm khóa so khớp."""
    text = strip_accents(text or "").lower()
    text = re.sub(r"[^a-z0-9.x/ ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Từ khóa nhận diện tủ lavabo (hàng phải đặt xưởng làm).
LAVABO_KEYWORDS = ("tu lavabo", "tu lavabô", "tu chau", "tu ban da", "tu ban lavabo", "tu go lavabo", "lavabo tu")


def is_lavabo_cabinet(product: str) -> bool:
    key = norm(product)
    return any(k in key for k in LAVABO_KEYWORDS) or (key.startswith("tu ") and "lavabo" in key)
