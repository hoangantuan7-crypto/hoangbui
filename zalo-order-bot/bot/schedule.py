"""Lịch hẹn trong nhóm Zalo nội bộ (loại "congviec"): Bot Điều phối đọc tin nhân viên nhắn,
thấy ngày/giờ thì ghi lịch, giao cho bộ phận phụ trách và nhắc trước giờ hẹn.

Hiểu được: "9h sáng mai giao tủ chị Hiền", "14h30 thứ 7 lắp gương nhà anh Tùng", "20/11 8h khảo sát",
"chiều nay 3h qua kho lấy hàng", "ngày 25 thu tiền công trình Yên Thành" (cả ngày -> báo trong lịch sáng).

Lệnh Telegram: /lich · /lich them kho mai 9h giao tủ chị Hiền · /lich xong L5 · /lich xoa L5
"""
import re
import unicodedata
from datetime import date, datetime, timedelta

from .departments import parse_dept, route
from .text import norm, strip_accents

WEEKDAYS = {"2": 0, "hai": 0, "3": 1, "ba": 1, "4": 2, "tu": 2, "5": 3, "nam": 3, "6": 4, "sau": 4,
            "7": 5, "bay": 5}
HONORIFICS = r"(?:chi|anh|em|co|ba|ong|ban|be|chu|bac|di|thim|a|c|e|mo|cau)"
AHEAD_DAYS = 60  # ngày hẹn xa hơn ngần này coi như không phải lịch (vd "1/2 số hàng")

# Việc nội bộ thường không có từ khóa như tin khách -> thêm từ khóa ngắn để chọn bộ phận
EXTRA = [("kythuat", ("lap", "sua", "bao hanh", "tho", "thao", "khao sat")),
         ("kho", ("giao", "xe", "lay hang", "nhan hang", "boc hang", "xuat kho", "nhap kho", "chuyen hang", "ship")),
         ("ketoan", ("thu tien", "ck", "chuyen khoan", "tien", "coc", "cong no", "hoa don")),
         ("sale", ("bao gia", "tu van", "gap khach", "hen khach", "khach", "chot", "don"))]


def _plain(text: str) -> str:
    """Chữ thường, bỏ dấu, GIỮ dấu ":" và "/" (giờ 14:30, ngày 20/11)."""
    return re.sub(r"\s+", " ", strip_accents(unicodedata.normalize("NFC", text or "")).lower())


def _time(plain: str) -> tuple[int, int] | None:
    m = (re.search(r"(?<![\d/.,:])(\d{1,2}):(\d{2})(?!\d)", plain)
         or re.search(r"(?<![\d/.,:])(\d{1,2})\s*(?:h|g|gio)(?:\s*(\d{2})(?![/\d-])|\s*(ruoi|kem)\b)?\s*(?:p|phut)?(?![a-z0-9])", plain))
    if not m:
        return None
    hour = int(m.group(1))
    word = m.group(3) if m.re.groups > 2 else None
    minute = int(m.group(2)) if m.group(2) else {"ruoi": 30}.get(word, 0)
    if hour > 23 or minute > 59:
        return None
    if re.search(r"\b(chieu|toi|dem)\b", plain) and hour < 12:
        hour += 12
    elif re.search(r"\btrua\b", plain) and hour <= 3:
        hour += 12
    elif not re.search(r"\bsang\b", plain) and 1 <= hour <= 6:
        hour += 12  # shop làm 7h-21h: "3h" không nói sáng/chiều là 3h chiều
    return hour, minute


def _date(plain: str, low: str, today: date) -> date | None:
    m = re.search(r"(?<![\d/.,])(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(?![\d/])", plain)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        year += 2000 if year < 100 else 0
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if not m.group(3) and d < today - timedelta(days=1):
            d = d.replace(year=d.year + 1)  # "5/1" nói vào tháng 12 = tháng 1 năm sau
        return d
    if re.search(r"\b(hom|sang|chieu|toi|trua|dem) nay\b", plain):
        return today
    if (re.search(r"\b(ngay|sang|chieu|toi|trua|dem) mai\b", plain)
            or (re.search(r"(?<!\w)mai(?!\w)", low) and not re.search(rf"\b{HONORIFICS} mai\b", plain))):
        return today + timedelta(days=1)
    if re.search(r"\bngay kia\b", plain) or re.search(r"(?<!\w)mốt(?!\w)", low):
        return today + timedelta(days=2)
    m = re.search(r"\bthu (2|3|4|5|6|7|hai|ba|tu|nam|sau|bay)\b|\b(chu nhat|cn)\b", plain)
    if m:
        target = WEEKDAYS[m.group(1)] if m.group(1) else 6
        ahead = (target - today.weekday()) % 7
        if re.search(r"\btuan (sau|toi)\b", plain):
            ahead += 7
        return today + timedelta(days=ahead)
    m = re.search(r"\bngay (\d{1,2})\b(?![/-])", plain)
    if m:
        day = int(m.group(1))
        for months in (0, 1):
            y, mo = today.year + (today.month - 1 + months) // 12, (today.month - 1 + months) % 12 + 1
            try:
                d = date(y, mo, day)
            except ValueError:
                continue
            if d >= today:
                return d
    return None


def parse_when(text: str, now: datetime) -> tuple[datetime, bool] | None:
    """(thời điểm hẹn, cả ngày?) hoặc None nếu tin không hẹn ngày/giờ nào sắp tới."""
    plain, low = _plain(text), unicodedata.normalize("NFC", text or "").lower()
    if re.search(r"\bhom qua\b", plain):
        return None
    hm, day = _time(plain), _date(plain, low, now.date())
    if day is None and hm is None:
        return None
    if day is None:  # chỉ có giờ: hôm nay; giờ đã qua thì là chuyện đã xong, không nhắc
        at = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
        return (at, False) if at > now else None
    if day < now.date() or (day - now.date()).days > AHEAD_DAYS:
        return None
    if hm is None:
        return datetime.combine(day, datetime.min.time()), True
    at = datetime.combine(day, datetime.min.time()).replace(hour=hm[0], minute=hm[1])
    return (at, False) if at > now else None


def schedule_dept(text: str) -> str | None:
    """Bộ phận phụ trách lịch (None = Bot Điều phối / chat tổng)."""
    dept = route(text)
    if dept and dept != "sale":
        return dept
    key = f" {norm(text)} "
    for d, words in EXTRA:
        if any(f" {w} " in key for w in words):
            return d
    return dept


def when_text(at: str | datetime, all_day: bool, now: datetime | None = None) -> str:
    at = datetime.fromisoformat(at) if isinstance(at, str) else at
    today = (now or datetime.now()).date()
    names = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"]
    rel = {0: "Hôm nay", 1: "Mai", 2: "Ngày kia"}.get((at.date() - today).days)
    day = f"{rel or names[at.weekday()]} {at:%d/%m}"
    return f"{day} (cả ngày)" if all_day else f"{at:%H:%M} {day}"


def parse_add(args: str, now: datetime) -> tuple[str | None, str, tuple[datetime, bool] | None]:
    """"/lich them kho mai 9h giao tủ chị Hiền" -> (bộ phận, nội dung, thời điểm)."""
    words = args.split()
    dept = parse_dept(words[0]) if words else None
    body = " ".join(words[1:]) if dept else args
    return dept, body.strip(), parse_when(body, now)
