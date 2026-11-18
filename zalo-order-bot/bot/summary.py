"""Tổng hợp tin trong 1 nhóm Zalo: /tonghop 1 7 (nhóm số 1 trong /nhom, 7 ngày qua).

Có AI: Claude đọc lại tin và tóm tắt (tiền, việc, người phụ trách, việc còn dở).
Không có AI: liệt kê gọn từng tin theo ngày. Ảnh/tệp chỉ ghi là [ảnh]/[tệp], không đọc nội dung ảnh.
Lưu ý: nội dung tin trong nhóm được gửi tới Claude API để tóm tắt.
"""
import logging
import os
from datetime import datetime

from .customer_info import media_kind

log = logging.getLogger(__name__)
MODEL = os.environ.get("CLAUDE_VISION_MODEL", "claude-haiku-5-5")
MAX_CHARS = 60000  # cắt bớt tin cũ nếu nhóm quá nhiều tin

PROMPT = """Đây là tin nhắn trong nhóm Zalo "{group}" của cửa hàng thiết bị vệ sinh, nhà bếp Tấn Phát (Diễn Châu,
Nghệ An), từ {start} đến {end}. Tổng hợp NGẮN GỌN bằng tiếng Việt cho anh chủ shop đọc trên điện thoại:

1. 💰 Tiền: liệt kê từng khoản (phí giao nhận, chi phí, tiền thu/chi) – ngày, nội dung, số tiền, ai ghi; cuối cùng cộng tổng.
2. 📦 Việc đã làm: giao hàng, nhận hàng, lắp đặt… (ngày, khách, ai làm).
3. ⏳ Việc còn dở / cần anh quyết: hỏi chưa ai trả lời, hẹn chưa xong, số liệu không khớp.
4. 👥 Ai nhắn nhiều, ai phụ trách gì (1–2 dòng).

Chỉ dựa vào tin bên dưới, không bịa. Không có mục nào thì bỏ mục đó. Số tiền ghi dạng 350.000đ.
Dùng gạch đầu dòng, không dùng bảng, không dùng **.

TIN NHẮN:
{lines}"""


def message_lines(messages: list[dict]) -> list[str]:
    """Tin ZaloCRM (cũ trước) -> "18/11 09:15 Linh: nội dung"."""
    out = []
    for m in messages:
        at = m.get("sentAt") or ""
        try:
            when = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone().strftime("%d/%m %H:%M")
        except ValueError:
            when = at[:16]
        kind, fname = media_kind(m.get("contentType") or "text", m.get("content") or "")
        if kind == "text":
            body = " / ".join(x.strip() for x in str(m.get("content") or "").splitlines() if x.strip())
        elif kind == "image":
            body = "[ảnh]"
        elif kind == "file":
            body = f"[tệp {fname}]"
        else:
            body = f"[{m.get('contentType') or 'tin khác'}]"
        if body:
            out.append(f"{when} {m.get('senderName') or '?'}: {body}")
    return out


def summarize(group: str, lines: list[str], start: str, end: str) -> str | None:
    """Claude tóm tắt; None nếu không có AI hoặc AI lỗi (khi đó gửi danh sách tin)."""
    from .ai_parser import ai_available

    if not ai_available() or not lines:
        return None
    import anthropic

    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = "…(bớt tin cũ)\n" + text[-MAX_CHARS:]
    try:
        response = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=3000, output_config={"effort": "low"},
            messages=[{"role": "user", "content": PROMPT.format(group=group, start=start, end=end, lines=text)}],
        )
    except anthropic.APIConnectionError as e:
        log.warning("Không kết nối được Claude: %s", e)
        return None
    except anthropic.APIStatusError as e:
        log.warning("Claude trả lỗi %s: %s", e.status_code, e.message)
        return None
    if response.stop_reason == "refusal":
        return None
    return "".join(b.text for b in response.content if b.type == "text").strip() or None
