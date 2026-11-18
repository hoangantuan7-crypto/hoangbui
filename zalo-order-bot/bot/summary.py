"""Tổng hợp tin trong 1 nhóm Zalo: /tonghop 1 7 (nhóm số 1 trong /nhom, 7 ngày qua).

Có AI: Claude đọc lại tin và tóm tắt (tiền, việc, người phụ trách, việc còn dở).
Có AI: đọc luôn nội dung ảnh (tối đa MAX_IMAGES ảnh mới nhất: phiếu, chuyển khoản, hàng hóa…).
Không có AI: liệt kê gọn từng tin theo ngày, ảnh/tệp chỉ ghi là [ảnh]/[tệp].
Lưu ý: nội dung tin trong nhóm được gửi tới Claude API để tóm tắt.
"""
import base64
import logging
import os
from datetime import datetime

from .customer_info import image_links, media_kind

log = logging.getLogger(__name__)
MODEL = os.environ.get("CLAUDE_VISION_MODEL", "claude-haiku-5-5")
MAX_CHARS = 60000  # cắt bớt tin cũ nếu nhóm quá nhiều tin
MAX_IMAGES = 15    # số ảnh mới nhất AI đọc khi tổng hợp (tốn phí theo ảnh)

PROMPT = """Đây là tin nhắn trong nhóm Zalo "{group}" của cửa hàng thiết bị vệ sinh, nhà bếp Tấn Phát (Diễn Châu,
Nghệ An), từ {start} đến {end}. Tổng hợp NGẮN GỌN bằng tiếng Việt cho anh chủ shop đọc trên điện thoại:

1. 💰 Tiền: liệt kê từng khoản (phí giao nhận, chi phí, tiền thu/chi) – ngày, nội dung, số tiền, ai ghi; cuối cùng cộng tổng.
2. 📦 Việc đã làm: giao hàng, nhận hàng, lắp đặt… (ngày, khách, ai làm).
3. ⏳ Việc còn dở / cần anh quyết: hỏi chưa ai trả lời, hẹn chưa xong, số liệu không khớp.
4. 👥 Ai nhắn nhiều, ai phụ trách gì (1–2 dòng).

Ảnh (phiếu xuất/nhập kho, phiếu giao hàng, chuyển khoản, hàng hóa…) được chèn ngay sau dòng [ảnh] tương ứng:
ĐỌC nội dung ảnh để tổng hợp (khách, số tiền, mã hàng, số lượng). Ảnh mờ, không đọc được thì nói rõ.
Xưng "em", gọi "anh". Chỉ dựa vào tin và ảnh bên dưới, không bịa. Không có mục nào thì bỏ mục đó. Số tiền ghi dạng 350.000đ.
Dùng gạch đầu dòng, không dùng bảng, không dùng **.

TIN NHẮN:
{lines}"""


def message_lines(messages: list[dict]) -> list[str]:
    """Tin ZaloCRM (cũ trước) -> "18/11 09:15 Linh: nội dung"."""
    return [line for line, _ in message_entries(messages)]


def message_entries(messages: list[dict]) -> list[tuple[str, list[str]]]:
    """Như message_lines, kèm link ảnh (để AI đọc ảnh) cho tin ảnh."""
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
            links = image_links(m.get("content") or "") if kind == "image" else []
            out.append((f"{when} {m.get('senderName') or '?'}: {body}", links))
    return out


def _call(content: list, max_tokens: int = 3000) -> str | None:
    import anthropic

    try:
        response = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=max_tokens, output_config={"effort": "low"},
            messages=[{"role": "user", "content": content}],
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


def _image_block(image: bytes, media: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media,
                                        "data": base64.standard_b64encode(image).decode()}}


DESCRIBE = """Ảnh này gửi trong nhóm Zalo làm việc của cửa hàng thiết bị vệ sinh, nhà bếp Tấn Phát. Đọc và tóm tắt
trong tối đa 4 dòng ngắn, tiếng Việt, không dùng **: loại ảnh (phiếu xuất kho, phiếu giao hàng, phiếu nhập hàng,
chuyển khoản, hóa đơn, ảnh hàng hóa…), khách/người nhận, mã hàng + số lượng, số tiền (cọc, đã trả, còn nợ, phí).
Không đọc được thì nói "Ảnh mờ, em không đọc được"."""


def describe_image(image: bytes, media: str, caption: str = "") -> str | None:
    """AI đọc nhanh 1 ảnh trong nhóm bộ phận. None nếu không có AI."""
    from .ai_parser import ai_available

    if not ai_available():
        return None
    return _call([_image_block(image, media),
                  {"type": "text", "text": DESCRIBE + (f"\nChú thích kèm ảnh: {caption}" if caption else "")}], 600)


def summarize(group: str, entries: list, start: str, end: str, fetch=None) -> str | None:
    """Claude tóm tắt (đọc cả ảnh nếu có fetch); None nếu không có AI hoặc AI lỗi (khi đó gửi danh sách tin).
    entries: [(dòng, [link ảnh])] hoặc [dòng]."""
    from .ai_parser import ai_available

    entries = [e if isinstance(e, tuple) else (e, []) for e in entries]
    if not ai_available() or not entries:
        return None
    total = 0
    keep = []  # bớt tin cũ nếu quá dài
    for line, links in reversed(entries):
        total += len(line) + 1
        if total > MAX_CHARS:
            break
        keep.append((line, links))
    keep.reverse()
    with_image = [i for i, (_, links) in enumerate(keep) if links][-MAX_IMAGES:] if fetch else []
    head = PROMPT.split("TIN NHẮN:")[0].format(group=group, start=start, end=end) + "TIN NHẮN:\n"
    content, buf = [], [head + ("…(bớt tin cũ)\n" if len(keep) < len(entries) else "")]
    for i, (line, links) in enumerate(keep):
        buf.append(line)
        if i in with_image:
            try:
                image, media = fetch(links)
            except Exception as e:  # noqa: BLE001 - ảnh tải lỗi: để nguyên [ảnh]
                log.info("Không tải được ảnh để tổng hợp: %s", e)
                continue
            content.append({"type": "text", "text": "\n".join(buf)})
            content.append(_image_block(image, media))
            buf = []
    if buf:
        content.append({"type": "text", "text": "\n".join(buf)})
    return _call(content)
