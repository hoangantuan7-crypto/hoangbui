"""Xếp loại nhóm Zalo để Bot Điều phối biết nhóm nào làm gì.

Loại nhóm:
  khach  – nhóm khách hàng / công trình: luôn theo dõi (báo việc, nhắc trả lời)
  noibo  – nhóm nội bộ của shop: KHÔNG đọc
  boqua  – nhóm không liên quan (CLB, gia đình…): KHÔNG đọc
Nhóm chưa xếp loại: theo chế độ SCAN_GROUPS; nhóm mới -> Bot Điều phối hỏi anh xếp loại.

Lệnh Telegram (Bot Điều phối):
  /nhom                         danh sách nhóm + loại, có số thứ tự
  /nhom khach 7, 8, Tên nhóm    xếp loại (dùng số trong danh sách hoặc tên nhóm, gõ đầu tên cũng được)
  /nhom noibo 1, 4 · /nhom boqua 3 · /nhom xoa 5 (bỏ xếp loại)
"""
import json

from .text import norm

CLASSES = {
    "khach": ("🏠", "khách hàng – theo dõi"),
    "noibo": ("👥", "nội bộ – không đọc"),
    "boqua": ("🔕", "bỏ qua – không đọc"),
}
CLASS_WORDS = [("khach hang", "khach"), ("khach", "khach"), ("noi bo", "noibo"), ("noibo", "noibo"),
               ("bo qua", "boqua"), ("boqua", "boqua"), ("xoa", "xoa"), ("bo xep", "xoa")]


def load(store) -> dict[str, str]:
    try:
        return json.loads(store.get_setting("group_class") or "{}")
    except ValueError:
        return {}


def save(store, mapping: dict[str, str]):
    store.set_setting("group_class", json.dumps(mapping, ensure_ascii=False))


def class_of(store, group_name: str) -> str | None:
    return load(store).get(norm(group_name or ""))


def group_name_from_customer(customer: str) -> str:
    """"Anh Tuấn (nhóm Nhà anh Tuấn)" -> "Nhà anh Tuấn"."""
    if "(nhóm " in customer and customer.endswith(")"):
        return customer.rsplit("(nhóm ", 1)[1][:-1]
    return ""


def unique_groups(convs: list[dict]) -> list[dict]:
    """Danh sách nhóm, gộp nhóm trùng (cùng 1 nhóm Zalo thấy từ 2 nick shop), mới nhắn trước."""
    seen, out = set(), []
    for c in sorted((c for c in convs if c.get("threadType") == "group"),
                    key=lambda c: c.get("lastMessageAt") or "", reverse=True):
        key = c.get("externalThreadId") or c["id"]
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def parse_args(args: str) -> tuple[str | None, list[str]]:
    """"khach 7, 8, Nhà anh Tùng" -> ("khach", ["7", "8", "Nhà anh Tùng"])."""
    words = args.split()
    for phrase, cls in CLASS_WORDS:
        n = len(phrase.split())
        if norm(" ".join(words[:n])) == phrase:
            rest = " ".join(words[n:])
            return cls, [t.strip() for t in rest.split(",") if t.strip()]
    return None, []


def resolve(tokens: list[str], numbered: list[str], all_names: list[str]) -> tuple[list[str], list[str]]:
    """Số thứ tự hoặc tên (đủ hoặc phần đầu tên) -> tên nhóm thật. Trả về (tìm được, không tìm được)."""
    found, missing = [], []
    for tok in tokens:
        if tok.isdigit():
            i = int(tok)
            if 1 <= i <= len(numbered):
                found.append(numbered[i - 1])
            else:
                missing.append(tok)
            continue
        key = norm(tok)
        exact = [n for n in all_names if norm(n) == key]
        prefix = [n for n in all_names if norm(n).startswith(key)] if len(key) >= 6 else []
        match = exact or (prefix if len(prefix) == 1 else [])
        (found if match else missing).append(match[0] if match else tok)
    return found, missing


def listing(store, groups: list[dict]) -> tuple[str, list[str]]:
    mapping = load(store)
    names = [(g.get("contact") or {}).get("fullName") or "?" for g in groups]
    lines = ["📂 CÁC NHÓM ZALO (mới nhắn trước):"]
    for i, name in enumerate(names, 1):
        cls = mapping.get(norm(name))
        icon, label = CLASSES.get(cls, ("❓", "chưa xếp loại"))
        lines.append(f"{i:>2}. {icon} {name} – {label}")
    lines += ["", "Xếp loại: /nhom khach 7, 8 · /nhom noibo 1, 4 · /nhom boqua 3 · /nhom xoa 5",
              "(dùng số ở trên hoặc tên nhóm)"]
    return "\n".join(lines), names
