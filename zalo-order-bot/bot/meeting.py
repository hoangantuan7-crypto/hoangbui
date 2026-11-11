"""Họp với các bot: họp công ty (cả 5 bot) hoặc họp bộ phận (1 bot báo cáo chi tiết).

Gọi họp bằng lời tự do: "họp công ty", "họp toàn bộ", "họp bộ phận kho", "họp sale", "/hop", "/hop kho".
Họp tự động hằng ngày (mặc định 18:00) = họp công ty.
"""
import re
from datetime import datetime

from .db import Store, fmt_qty
from .departments import DEPTS, parse_dept
from .dept_bots import BOT_NAMES, DIEUPHOI
from .followup import parse_ts, short, utc_now, wait_text
from .reports import _ago, _short, compute_shortages
from .text import norm

COMPANY = "congty"
COMPANY_WORDS = ("cong ty", "toan bo", "toan cong ty", "chung", "tong", "tat ca", "ca nha", "giao ban")
# Câu mở đầu bằng 1 trong các cụm này mới coi là gọi họp (tránh nhầm "hộp" trong "hộp gỗ…")
STARTERS = ("hop", "bat dau hop", "mo hop", "mo cuoc hop", "to chuc hop", "cho hop", "goi hop", "hop nhanh")


def parse_meeting(text: str, default_dept: str | None = None) -> tuple[str, str | None] | None:
    """('congty', None) / ('bophan', 'kho') nếu là lời gọi họp, ngược lại None.
    default_dept: đang chat riêng với bot bộ phận nào thì "họp" = họp bộ phận đó."""
    key = norm(re.sub(r"@\w+", " ", text or "")).lstrip("/").strip()
    starter = next((s for s in sorted(STARTERS, key=len, reverse=True)
                    if key == s or key.startswith(s + " ")), None)
    if not starter:
        return None
    rest = key[len(starter):].strip()
    rest = re.sub(r"^(bo phan|phong|nhom|voi|cung|ben)\s+", "", rest)
    rest = re.sub(r"\s+(oi|nhe|nha|nao|ngay|luon|di)$", "", rest).strip()
    if not rest:
        return ("bophan", default_dept) if default_dept else (COMPANY, None)
    if any(rest == w or rest.startswith(w + " ") for w in COMPANY_WORDS):
        return COMPANY, None
    first_two = " ".join(rest.split()[:2])
    for cand in (first_two.replace(" ", ""), rest.split()[0]):
        dept = parse_dept(cand)
        if dept in DEPTS:
            return "bophan", dept
    if len(rest.split()) > 4:
        return None  # câu dài không nhắc bộ phận nào: chắc là câu thường, không phải gọi họp
    return COMPANY, None


def _dept_numbers(store: Store, dept: str, since: datetime, now: datetime, overdue_min: int):
    new, done = store.leads_since(since, dept)
    waiting = store.open_leads(dept)
    late = [lead for lead in waiting
            if (now - datetime.fromisoformat(lead["created_at"])).total_seconds() >= overdue_min * 60]
    return new, done, waiting, late


def _extra(store: Store, dept: str, now: datetime) -> list[str]:
    """Thông tin riêng của từng bộ phận ngoài số việc."""
    lines = []
    if dept == "sale":
        n = len(store.open_orders())
        if n:
            lines.append(f"   Đơn hàng đang mở: {n}")
    if dept == "kho":
        missing, _, _ = compute_shortages(store)
        if missing:
            prods = sorted({p for rows in missing.values() for _, p, *_ in rows})
            lines.append(f"   Thiếu hàng: {len(missing)} khách chờ – {', '.join(prods[:5])}")
    if dept in ("kho", "kythuat"):
        todo = waiting = late = 0
        for it in store.open_items():
            if not it["is_lavabo"]:
                continue
            if it["factory_ordered_at"] is None:
                todo += 1
            else:
                waiting += 1
                late += (now - datetime.fromisoformat(it["factory_ordered_at"])).days >= 10
        if todo or waiting:
            lines.append(f"   Tủ lavabo: {todo} chưa đặt xưởng, {waiting} đang chờ xưởng"
                         + (f" ({late} quá 10 ngày)" if late else ""))
    return lines


def dept_report(store: Store, dept: str, now: datetime, detail: bool = False, overdue_min: int = 30) -> str:
    since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    new, done, waiting, late = _dept_numbers(store, dept, since, now, overdue_min)
    icon, title = BOT_NAMES[dept]
    line = f"{icon} {title}: Mới {len(new)} · Xong {len(done)} · Đang chờ {len(waiting)}"
    if late:
        line += f" · Quá hạn {len(late)}"
    lines = [line] + _extra(store, dept, now)
    if detail:
        if waiting:
            lines.append("   Việc đang chờ:")
            lines += [f"   • K{lead['id']} {lead['customer']} – {_ago(lead['created_at'], now)}: “{_short(lead['text'], 80)}”"
                      + (" ⚠️" if lead in late else "") for lead in waiting]
        if done:
            lines.append("   Đã xong hôm nay: " + ", ".join(f"K{lead['id']}" for lead in done))
    elif late:
        worst = late[0]
        lines.append(f"   Lâu nhất: K{worst['id']} {worst['customer']} – {_ago(worst['created_at'], now)}")
    if not (new or done or waiting) and len(lines) == 1:
        lines[0] = f"{icon} {title}: Hôm nay không có việc mới, không tồn việc. ✅"
    return "\n".join(lines)


def decisions(store: Store, now: datetime, dept: str | None = None, overdue_min: int = 30) -> list[str]:
    """Những việc cần anh quyết / để ý."""
    out = []
    if dept is None:  # khách chờ trả lời quá 1 giờ
        utc = utc_now()
        for r in store.waiting_convs():
            mins = (utc - parse_ts(r["wait_since"])).total_seconds() / 60
            if mins >= 60:
                out.append(f"{r['customer']} chờ anh trả lời {wait_text(mins)}: “{short(r['last_customer_text'], 60)}”")
    for d in ([dept] if dept else DEPTS):
        for lead in store.open_leads(d):
            if (now - datetime.fromisoformat(lead["created_at"])).total_seconds() >= overdue_min * 60:
                out.append(f"K{lead['id']} {lead['customer']} ({DEPTS[d][1]}) chờ {_ago(lead['created_at'], now)}: "
                           f"“{_short(lead['text'], 60)}”")
    if dept in (None, "kho"):
        _, demand, names = compute_shortages(store)
        stock = store.stock_map()
        for key, need in demand.items():
            have = stock[key]["qty"] if key in stock else 0
            if need > have:
                out.append(f"{names[key]} thiếu {fmt_qty(need - have)} – cần đặt nhà cung cấp")
    return out[:8]


def build_meeting(store: Store, scope: str, dept: str | None, now: datetime | None = None,
                  overdue_min: int = 30, auto: bool = False) -> list[tuple[str, str]]:
    """Danh sách (bot phát biểu, nội dung) theo thứ tự cuộc họp."""
    now = now or datetime.now()
    since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    kind = "tự động" if auto else ""
    if scope == COMPANY:
        new, done = store.leads_since(since)
        waiting = len(store.waiting_convs())
        msgs = [(DIEUPHOI, f"🧭 Bot Điều phối: Bắt đầu HỌP CÔNG TY {kind} – {now:%H:%M %d/%m}.".replace("  ", " ")
                 + f"\nHôm nay nhận {len(new)} việc từ tin khách, đã xong {len(done)}."
                 + (f"\n💬 Đang có {waiting} khách chờ anh trả lời." if waiting else "\n💬 Không có khách nào chờ trả lời.")
                 + "\nMời từng bộ phận báo cáo.")]
        msgs += [(d, dept_report(store, d, now, overdue_min=overdue_min)) for d in DEPTS]
    else:
        icon, title = BOT_NAMES[dept]
        msgs = [(DIEUPHOI, f"🧭 Bot Điều phối: Bắt đầu HỌP BỘ PHẬN {DEPTS[dept][1].upper()} – {now:%H:%M %d/%m}. "
                           f"Mời {title} báo cáo.")]
        msgs.append((dept, dept_report(store, dept, now, detail=True, overdue_min=overdue_min)))
    todo = decisions(store, now, None if scope == COMPANY else dept, overdue_min)
    closing = ("🧭 Bot Điều phối – CẦN ANH QUYẾT:\n" + "\n".join(f"   {i}. {t}" for i, t in enumerate(todo, 1))
               if todo else "🧭 Bot Điều phối: Không có việc nào cần anh quyết. ✅")
    closing += "\n\nHỏi riêng bộ phận: gõ \"Kho ơi, …\", \"Sale ơi, …\" hoặc nhắn thẳng cho bot đó. Kết thúc họp."
    msgs.append((DIEUPHOI, closing))
    return msgs


def flatten(msgs: list[tuple[str, str]]) -> str:
    """Gộp cuộc họp thành 1 tin (khi họp trong chat riêng: chỉ 1 bot nói được)."""
    return "\n\n".join(text for _, text in msgs)

