"""Theo dõi khách chờ trả lời – không cần AI.

- Khách nhắn mà shop chưa trả lời quá N phút (trong giờ làm việc) -> Bot Điều phối nhắn riêng anh.
- Khách nhắn kiểu "không phải ý em", "em hỏi cái khác mà", "???" sau khi shop đã trả lời
  -> báo "khách có vẻ chưa được giải đáp đúng".

Tin do nick shop gửi từ điện thoại có thể bị ZaloCRM ghi nhầm là tin khách: nhận ra bằng tên/mã nick shop.
"""
import re
from datetime import datetime, timezone

from .text import norm

# Tin khách chỉ để "chốt" câu chuyện, không cần trả lời
CLOSERS = re.compile(
    r"^(ok+|oke+|okay|okie|uh+|u+|um+|vang|da|da vang|vang a|da a|ok a|ok em|ok anh|ok chi|ok c|ok e|ok a nhe"
    r"|cam on|cam on a|cam on anh|cam on em|cam on chi|cam on nhieu|thanks|thank you|thank|tks|thanks a"
    r"|dc|duoc|duoc roi|ok duoc|ok roi|roi|xong|nhe|nha|vay nhe|the nhe|hihi|hehe|haha|ha ha)"
    r"(\s+(nhe|nha|a|nhieu|lam|nhe a|nha a|roi|nhe anh|nhe em|nhe chi))*[ .!]*$")

# Khách tỏ ý chưa được giải đáp đúng (viết không dấu)
DISSATISFIED = [
    "khong phai", "ko phai", "k phai", "y em la", "y chi la", "y anh la", "y minh la", "y toi la",
    "em hoi la", "em hoi cai", "chi hoi cai", "anh hoi cai", "em dang hoi", "chi dang hoi", "anh dang hoi",
    "chua tra loi", "chua rep", "sao khong tra loi", "sao ko tra loi", "tra loi sai", "nham roi", "sai roi",
    "khong dung", "ko dung", "chua hieu y", "van chua", "hoi lai", "noi lai", "em can cai", "chi can cai",
    "khong lien quan", "ko lien quan", "lac de",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str | None) -> datetime:
    """Giờ ZaloCRM ("2026-11-11T16:35:23.379Z") -> datetime UTC; thiếu thì lấy giờ hiện tại."""
    if not value:
        return utc_now()
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def needs_reply(text: str) -> bool:
    return not CLOSERS.match(norm(text)) and bool(norm(text) or "?" in text)


def dissatisfied(text: str) -> bool:
    if re.search(r"\?\s*\?", text):
        return True
    key = f" {norm(text)} "
    return any(f" {p} " in key or key.strip().startswith(p) for p in DISSATISFIED)


def in_work_hours(now_local: datetime, hours: str) -> bool:
    """hours dạng "07:00-21:00"; để trống = lúc nào cũng nhắc."""
    if not hours:
        return True
    start, _, end = hours.partition("-")
    t = f"{now_local:%H:%M}"
    return start.strip() <= t < end.strip()


def wait_text(minutes: float) -> str:
    minutes = int(minutes)
    if minutes < 60:
        return f"{minutes} phút"
    if minutes < 1440:
        return f"{minutes // 60} giờ" + (f" {minutes % 60} phút" if minutes % 60 and minutes < 600 else "")
    return f"{minutes // 1440} ngày"


def short(text: str, limit: int = 90) -> str:
    text = " / ".join(line.strip() for line in (text or "").splitlines() if line.strip())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def waiting_lines(rows, now: datetime) -> list[str]:
    out = []
    for r in rows:
        mins = (now - parse_ts(r["wait_since"])).total_seconds() / 60
        who = r["customer"] + (f" ({r['phone']})" if r["phone"] else "")
        out.append(f"  • {who} – chờ {wait_text(mins)}: “{short(r['last_customer_text'])}”")
    return out
