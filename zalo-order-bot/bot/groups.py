"""Xếp loại nhóm Zalo để Bot Điều phối biết nhóm nào làm gì.

Loại nhóm:
  khach  – nhóm khách hàng / công trình: luôn theo dõi (báo việc, nhắc trả lời)
  noibo  – nhóm nội bộ của shop: KHÔNG đọc
  chotdon – nhóm "CHỐT ĐƠN": ảnh phiếu đơn -> nháp đơn trong Telegram -> anh duyệt -> Google Sheet đơn hàng
  congviec – nhóm nội bộ làm việc: Bot Điều phối đọc lịch hẹn (ngày/giờ), giao bộ phận, nhắc trước giờ hẹn
  boqua  – nhóm không liên quan (CLB, gia đình…): KHÔNG đọc
  bp:kho,ketoan – nhóm làm việc của bộ phận: mọi tin chuyển cho bot bộ phận đó trên Telegram (/nhom kho+ketoan Tên)
                  Tên nhóm bắt đầu bằng KHO / KẾ TOÁN / KỸ THUẬT / SALE -> tự nhận (vd "KHO TEST")
Nhóm chưa xếp loại: theo chế độ SCAN_GROUPS; nhóm mới -> Bot Điều phối hỏi anh xếp loại.

Lệnh Telegram (Bot Điều phối):
  /nhom                         danh sách nhóm + loại, có số thứ tự
  /nhom khach 7, 8, Tên nhóm    xếp loại (dùng số trong danh sách hoặc tên nhóm, gõ đầu tên cũng được)
  /nhom noibo 1, 4 · /nhom boqua 3 · /nhom xoa 5 (bỏ xếp loại)
"""
import json
import re

from .departments import DEPTS, parse_dept
from .text import norm

CLASSES = {
    "khach": ("🏠", "khách hàng – theo dõi"),
    "noibo": ("👥", "nội bộ – không đọc"),
    "congviec": ("📋", "nội bộ – theo dõi lịch & nhắc việc"),
    "boqua": ("🔕", "bỏ qua – không đọc"),
    "thongtin": ("📇", "thông tin khách – ghi vào Google Sheet"),
    "chotdon": ("🧾", "chốt đơn – đọc phiếu, tạo nháp đơn"),
}
INFO_PREFIX = "thong tin khach hang"  # nhóm tên "THÔNG TIN KHÁCH HÀNG…" tự là nhóm thông tin khách
ORDER_PREFIX = "chot don"              # nhóm tên "CHỐT ĐƠN…" tự là nhóm chốt đơn
AUTO = ((INFO_PREFIX, "thongtin"), (ORDER_PREFIX, "chotdon"), ("kho", "bp:kho"), ("ke toan", "bp:ketoan"),
        ("ky thuat", "bp:kythuat"), ("sale", "bp:sale"), ("dieu phoi", "congviec"))


def auto_class(key: str) -> str | None:
    """Loại nhóm theo chữ đầu tên (nguyên từ: "KHO TEST" là kho, "Khoa học" thì không)."""
    return next((cls for prefix, cls in AUTO if key == prefix or key.startswith(prefix + " ")), None)


def dept_codes(cls: str | None) -> list[str]:
    return [d for d in (cls or "")[3:].split(",") if d in DEPTS] if (cls or "").startswith("bp:") else []


def info(cls: str | None) -> tuple[str, str]:
    """(biểu tượng, mô tả) của 1 loại nhóm, kể cả nhóm bộ phận "bp:kho,ketoan"."""
    depts = dept_codes(cls)
    if depts:
        return ("".join(DEPTS[d][0] for d in depts),
                "bộ phận " + " + ".join(DEPTS[d][1] for d in depts) + " – chuyển tin cho bot bộ phận")
    return CLASSES.get(cls, ("❓", "chưa xếp loại"))
CLASS_WORDS = [("khach hang", "khach"), ("khach", "khach"), ("noi bo", "noibo"), ("noibo", "noibo"),
               ("cong viec", "congviec"), ("congviec", "congviec"), ("nhac lich", "congviec"), ("lich", "congviec"),
               ("bo qua", "boqua"), ("boqua", "boqua"), ("thong tin", "thongtin"), ("thongtin", "thongtin"),
               ("chot don", "chotdon"), ("chotdon", "chotdon"),
               ("xoa", "xoa"), ("bo xep", "xoa")]


def load(store) -> dict[str, str]:
    try:
        return json.loads(store.get_setting("group_class") or "{}")
    except ValueError:
        return {}


def save(store, mapping: dict[str, str]):
    store.set_setting("group_class", json.dumps(mapping, ensure_ascii=False))


def class_of(store, group_name: str) -> str | None:
    key = norm(group_name or "")
    return load(store).get(key) or auto_class(key)


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
    """"khach 7, 8, Nhà anh Tùng" -> ("khach", ["7", "8", "Nhà anh Tùng"]).
    "kho+ketoan Tên nhóm" -> ("bp:kho,ketoan", ["Tên nhóm"])."""
    words = re.sub(r"\s*\+\s*", "+", args).split()
    if words:
        depts = [parse_dept(p) for p in words[0].split("+") if p]
        if depts and all(d in DEPTS for d in depts):
            rest = " ".join(words[1:])
            return "bp:" + ",".join(dict.fromkeys(depts)), [t.strip() for t in rest.split(",") if t.strip()]
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
        cls = mapping.get(norm(name)) or auto_class(norm(name))
        icon, label = info(cls)
        lines.append(f"{i:>2}. {icon} {name} – {label}")
    lines += ["", "Xếp loại: /nhom khach 7, 8 · /nhom congviec 3 · /nhom kho+ketoan 9 · /nhom noibo 1, 4 · "
              "/nhom boqua 3 · /nhom thongtin 6 · /nhom xoa 5",
              "(dùng số ở trên hoặc tên nhóm)"]
    return "\n".join(lines), names
