"""Hỏi riêng từng bộ phận: "Kho ơi, tủ của anh Nam đến đâu rồi?".

Bot gom dữ liệu thật của bộ phận (việc đang chờ, đơn hàng, tồn kho, tủ lavabo…) rồi nhờ Claude trả lời
NGẮN, chỉ dựa trên dữ liệu đó. Cần ANTHROPIC_API_KEY; tính phí theo lượt hỏi.
Lưu ý: dữ liệu khách (tên, SĐT, nội dung tin) được gửi tới Claude API để trả lời.
"""
import logging
import os
import re
from datetime import datetime

from .db import Store, fmt_qty
from .departments import DEPTS
from .dept_bots import BOT_NAMES, DIEUPHOI
from .meeting import dept_report
from .reports import _ago, report_lavabo, report_reorder, report_shortage
from .text import norm

log = logging.getLogger(__name__)
MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

# Cách gọi tên bộ phận trong câu hỏi (không dấu)
CALL_NAMES = {
    "sale": ["sale", "sales", "ban hang", "kinh doanh"],
    "ketoan": ["ke toan", "ketoan"],
    "kho": ["kho"],
    "kythuat": ["ky thuat", "ki thuat", "kythuat"],
    DIEUPHOI: ["dieu phoi", "dieuphoi"],
}


def parse_address(text: str, usernames: dict[str, str]) -> tuple[str, str] | None:
    """Câu hỏi gửi cho bot nào. Nhận: "@VHKhoBot …", "Kho ơi …", "Kho, …", "Bot kế toán: …".
    Trả về (bot, câu hỏi) hoặc None nếu không gọi tên bot nào."""
    raw = (text or "").strip()
    for name, user in usernames.items():
        if user and re.search(rf"@{re.escape(user)}\b", raw, re.IGNORECASE):
            question = re.sub(rf"@{re.escape(user)}\b[\s,:]*", "", raw, flags=re.IGNORECASE).strip()
            return name, question or raw
    key, words = norm(raw), raw.split()
    for name, calls in CALL_NAMES.items():
        for call in calls:
            m = re.match(rf"^(bot\s+)?{call}(\s+oi)?(?=\s|$)", key)
            if not m:
                continue
            n = len(m.group(0).split())
            punct = n <= len(words) and words[n - 1].endswith((",", ":"))
            if m.group(1) or m.group(2) or punct:
                question = " ".join(words[n:]).lstrip(",: ").strip()
                return name, question or raw
    return None


def dept_snapshot(store: Store, dept: str, now: datetime | None = None) -> str:
    """Dữ liệu thật của bộ phận, dạng chữ, để AI đọc."""
    now = now or datetime.now()
    parts = [f"Thời điểm: {now:%H:%M %d/%m/%Y}"]
    depts = list(DEPTS) if dept == DIEUPHOI else [dept]
    for d in depts:
        parts.append(dept_report(store, d, now, detail=True))
    if dept in (DIEUPHOI, "sale", "kho", "kythuat", "ketoan"):
        lines = []
        for o in store.open_orders()[:40]:
            _, items = store.get_order(o["id"])
            lines.append(f"#{o['id']} {o['customer']} ({o['created_at'][:10]}): " + "; ".join(
                f"{fmt_qty(i['delivered'])}/{fmt_qty(i['qty'])} {i['product']}"
                + (" [tủ lavabo – đặt xưởng " + (i['factory_ordered_at'][:10] if i['factory_ordered_at'] else "CHƯA đặt")
                   + "]" if i["is_lavabo"] else "") for i in items))
        parts.append("ĐƠN HÀNG ĐANG MỞ (đã giao/đặt):\n" + ("\n".join(lines) or "(không có)"))
    if dept in (DIEUPHOI, "kho", "sale"):
        stock = store.stock_map()
        parts.append("TỒN KHO:\n" + ("\n".join(f"{r['product']}: {fmt_qty(r['qty'])}" for r in stock.values())
                                    or "(chưa nhập tồn kho)"))
        parts.append(report_shortage(store))
    if dept in (DIEUPHOI, "kho", "kythuat"):
        parts.append(report_lavabo(store, now))
    if dept in (DIEUPHOI, "sale"):
        parts.append(report_reorder(store, now))
    recent = store.conn.execute(
        "SELECT * FROM leads WHERE status='done' " + ("" if dept == DIEUPHOI else "AND kind=? ")
        + "ORDER BY closed_at DESC LIMIT 15", () if dept == DIEUPHOI else (dept,)).fetchall()
    if recent:
        parts.append("VIỆC ĐÃ XONG GẦN ĐÂY:\n" + "\n".join(
            f"K{r['id']} {r['customer']} – xong {_ago(r['closed_at'] or r['updated_at'], now)}: {r['text'][:100]}"
            for r in recent))
    return "\n\n".join(parts)


def system_prompt(bot: str) -> str:
    icon, title = BOT_NAMES[bot]
    scope = ("toàn bộ cửa hàng: điều phối việc giữa Sale, Kế toán, Kho, Kỹ thuật" if bot == DIEUPHOI
             else f"bộ phận {DEPTS[bot][1]}")
    return (
        f"Bạn là {title} của cửa hàng nội thất, thiết bị vệ sinh Việt Hoàng (tủ lavabo, gương, vòi, sen…), "
        f"phụ trách {scope}. Chủ cửa hàng (gọi là \"anh\") đang hỏi bạn trên Telegram. "
        "Xưng \"em\", trả lời tiếng Việt, ngắn gọn (tối đa khoảng 8 dòng), đi thẳng vào câu hỏi. "
        "CHỈ dựa vào DỮ LIỆU được cung cấp; nếu dữ liệu không có thông tin thì nói rõ là chưa có trong hệ thống "
        "và gợi ý cách kiểm tra (ví dụ hỏi nhân viên phụ trách), tuyệt đối không bịa. "
        "Nhắc mã việc (K5) hoặc mã đơn (#12) khi có. Không dùng định dạng markdown phức tạp."
    )


def ask_bot(bot: str, question: str, store: Store) -> str:
    """Trả lời câu hỏi cho 1 bot. Không có AI -> trả về báo cáo của bộ phận thay vì câu trả lời."""
    from .ai_parser import ai_available

    icon, title = BOT_NAMES[bot]
    if not ai_available():
        fallback = dept_snapshot(store, bot) if bot != DIEUPHOI else dept_report(store, "sale", datetime.now())
        return (f"{icon} {title}: Phần hỏi đáp tự do cần bật AI (thêm ANTHROPIC_API_KEY vào cấu hình). "
                f"Tạm thời em gửi số liệu hiện có:\n\n{fallback[:3500]}")
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system_prompt(bot),
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": f"DỮ LIỆU:\n{dept_snapshot(store, bot)}\n\nCÂU HỎI CỦA ANH: {question}"}],
        )
    except anthropic.APIConnectionError:
        return f"{icon} {title}: Em chưa kết nối được AI để trả lời, anh thử lại sau ít phút."
    except anthropic.APIStatusError as e:
        log.warning("Claude trả lỗi %s: %s", e.status_code, e.message)
        return f"{icon} {title}: AI đang lỗi ({e.status_code}), anh thử lại sau."
    if response.stop_reason == "refusal":
        return f"{icon} {title}: Em không trả lời được câu này."
    answer = "".join(b.text for b in response.content if b.type == "text").strip()
    return f"{icon} {title}: {answer}" if answer else f"{icon} {title}: Em chưa có câu trả lời."

