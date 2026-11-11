"""(Tùy chọn) Dùng Claude để đọc tin nhắn đơn hàng viết tự do.

Chỉ bật khi đã `pip install anthropic` và đặt ANTHROPIC_API_KEY.
"""
import json
import logging
import os

from .parser import ParsedOrder

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

SCHEMA = {
    "type": "object",
    "properties": {
        "is_order": {"type": "boolean", "description": "Tin nhắn có phải là khách đặt hàng không"},
        "customer": {"type": "string"},
        "phone": {"type": "string"},
        "note": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"product": {"type": "string"}, "qty": {"type": "number"}},
                "required": ["product", "qty"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["is_order", "customer", "phone", "note", "items"],
    "additionalProperties": False,
}

SYSTEM = (
    "Bạn đọc tin nhắn Zalo của một cửa hàng thiết bị vệ sinh (tủ lavabo, gương, vòi, sen...). "
    "Nếu tin nhắn là một đơn đặt hàng của khách, trích tên khách, số điện thoại (nếu có), ghi chú "
    "(kích thước, màu, địa chỉ giao...) và danh sách sản phẩm kèm số lượng; giữ nguyên tên sản phẩm "
    "tiếng Việt kèm quy cách. Nếu không phải đơn hàng, đặt is_order=false và để các trường còn lại rỗng."
)


def ai_available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def ai_parse_order(message: str, sender: str = "") -> ParsedOrder | None:
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": f"Người gửi: {sender}\nTin nhắn:\n{message}"}],
        )
    except anthropic.APIConnectionError as e:
        log.warning("Không kết nối được Claude: %s", e)
        return None
    except anthropic.APIStatusError as e:
        log.warning("Claude trả lỗi %s: %s", e.status_code, e.message)
        return None
    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    text = next((b.text for b in response.content if b.type == "text"), "")
    data = json.loads(text)
    if not data["is_order"] or not data["items"]:
        return None
    customer = data["customer"].strip() or sender or "Khách lẻ"
    items = [(i["product"], float(i["qty"])) for i in data["items"] if i["product"] and i["qty"] > 0]
    return ParsedOrder(customer=customer, items=items, phone=data["phone"], note=data["note"]) if items else None
