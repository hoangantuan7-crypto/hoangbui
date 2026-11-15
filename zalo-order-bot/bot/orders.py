"""Nhóm Zalo "CHỐT ĐƠN": ảnh phiếu đơn / phiếu giao hàng / giấy ghi tay -> NHÁP ĐƠN trong Telegram
-> anh sửa nhanh bằng cách trả lời (reply) tin nháp -> "ok" -> ghi Google Sheet đơn hàng.

Sửa nháp (trả lời tin nháp, mỗi dòng 1 lệnh; hoặc gõ "N3 …" ở đầu):
  3 sl 2 · 3 gia 1.460.000 · 3 ma H-2200V · 3 ten Vòi lavabo · 3 dvt cái · xoa 4 · them H-B1639 1 850k
  rieng 9 (hàng riêng chờ khảo sát/báo giá) · tang 4 (hàng tặng, giá 0)
  khach Chị Hương · sdt 0362016908 · dc Chợ Bộng, Yên Thành · giao 20/11
  coc 5tr 06/10 · thu 16.600.000 (khách trả thêm lần này) · giam 2.120.000 · ghichu Thiếu 2 vòi xịt
  ok – lên Google Sheet · huy – bỏ nháp
"""
import base64
import json
import logging
import os
import re
import urllib.request
from datetime import datetime

from .customer_info import clean_phone
from .text import norm, strip_accents

log = logging.getLogger(__name__)
VISION_MODEL = os.environ.get("CLAUDE_VISION_MODEL", "claude-haiku-5-5")
ORDER_PREFIX = "chot don"  # nhóm Zalo tên "CHỐT ĐƠN…" tự là nhóm chốt đơn
KINDS = {"thuong": "", "tang": " 🎁 tặng", "rieng": " 🛠 hàng riêng"}


# ---------- tiền, mã sản phẩm ----------
def money(text) -> int | None:
    """"5tr" "5 triệu" "1tr2" "850k" "5.000.000" "5,000,000đ" -> số đồng."""
    if isinstance(text, (int, float)):
        return int(text)
    s = strip_accents(str(text or "")).lower().replace(" ", "").replace("d", "").replace("vnd", "")
    m = re.fullmatch(r"(\d+)(?:tr|trieu|m)(\d{0,3})", s)
    if m:
        frac = m.group(2)
        return int(m.group(1)) * 1_000_000 + (int(frac.ljust(3, "0")) * 1000 if frac else 0)
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)(?:k|nghin|ngan)", s)
    if m:
        return int(float(m.group(1).replace(",", ".")) * 1000)
    digits = re.sub(r"[.,]", "", s)
    return int(digits) if digits.isdigit() else None


def vnd(n) -> str:
    return f"{int(n or 0):,}".replace(",", ".")


def code_key(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", strip_accents(code or "").upper())


class Catalog:
    """Danh mục sản phẩm (trang KHO của Sheet đơn hàng): mã -> tên, ĐVT, giá bán, phân loại."""

    def __init__(self, rows: list[dict] | None = None):
        self.rows = [r for r in (rows or []) if r.get("code")]
        self.by_key = {}
        for r in self.rows:
            self.by_key.setdefault(code_key(r["code"]), r)

    def __len__(self):
        return len(self.rows)

    def match(self, code: str) -> tuple[dict | None, str]:
        """(sản phẩm, mức khớp): "dung" đúng mã · "gan" gần đúng (mã ghi tắt) · "" không có."""
        key = code_key(code)
        if len(key) < 3:
            return None, ""
        if key in self.by_key:
            return self.by_key[key], "dung"
        near = [r for r in self.rows if key in code_key(r["code"])]
        if near:  # "612S" -> "LFV-612S": chọn mã ngắn nhất chứa mã ghi tắt
            return min(near, key=lambda r: len(code_key(r["code"]))), "gan"
        return None, ""


# ---------- đọc phiếu bằng AI ----------
ITEM = {
    "type": "object",
    "properties": {
        "code": {"type": "string"}, "name": {"type": "string"}, "unit": {"type": "string"},
        "qty": {"type": "number"}, "price": {"type": "integer"}, "amount": {"type": "integer"},
        "kind": {"type": "string", "enum": ["thuong", "tang", "rieng"]}, "note": {"type": "string"},
    },
    "required": ["code", "name", "unit", "qty", "price", "amount", "kind", "note"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "is_order": {"type": "boolean"},
        "doc_type": {"type": "string", "enum": ["don_hang", "giao_hang_cong_no", "ghi_tay", "khac"]},
        "customer": {"type": "string"}, "phone": {"type": "string"}, "address": {"type": "string"},
        "order_date": {"type": "string"}, "delivery_date": {"type": "string"},
        "items": {"type": "array", "items": ITEM},
        "subtotal": {"type": "integer"}, "discount": {"type": "integer"}, "total": {"type": "integer"},
        "paid_before": {"type": "integer"}, "paid_before_date": {"type": "string"},
        "pay_now": {"type": "integer"}, "note": {"type": "string"}, "unclear": {"type": "string"},
    },
    "required": ["is_order", "doc_type", "customer", "phone", "address", "order_date", "delivery_date", "items",
                 "subtotal", "discount", "total", "paid_before", "paid_before_date", "pay_now", "note", "unclear"],
    "additionalProperties": False,
}
PROMPT = """Ảnh/tin này là đơn hàng của cửa hàng thiết bị vệ sinh, nhà bếp Tấn Phát (Diễn Châu, Nghệ An): phiếu in
(phiếu xuất kho, phiếu giao hàng & đối chiếu công nợ) hoặc giấy ghi tay tiếng Việt. Đọc thành dữ liệu đơn hàng.

Quy tắc:
- Số tiền là đồng, số nguyên (8.850.000 -> 8850000). Không có thì 0.
- Giá bị gạch/sửa (vd "8.800.000: 8.500.000" hoặc số bị gạch): lấy GIÁ CUỐI CÙNG còn hiệu lực.
- Mã sản phẩm ghi đúng như trên phiếu; nếu gần giống 1 mã trong danh mục bên dưới thì ghi mã của danh mục.
- kind: "tang" nếu hàng tặng kèm/giá 0; "rieng" nếu hàng riêng/đặt làm riêng (tủ lavabo theo kích thước, hàng
  chờ khảo sát, chờ báo giá lại); còn lại "thuong". Hàng riêng chưa có giá thì price=0.
- Giấy ghi tay kiểu "Tủ LVB: TCLux VA80: 2 bộ - Tổng: 16.500.000": SL lấy theo chữ "2 bộ"; nếu chỉ có tổng thì
  price = tổng / SL.
- paid_before = tiền đã cọc / đã thu trước (kèm ngày nếu có, dd/mm/yyyy). pay_now = số tiền khách thanh toán
  lần này (thường viết tay ở cuối phiếu giao hàng). total = tổng chốt sau giảm giá nếu phiếu có ghi.
- note: ghi chú viết tay / nội dung giao hàng quan trọng (vd "Thiếu 2 vòi xịt CFV-102M", "tặng kèm … trừ 760.000").
- unclear: liệt kê ngắn những chỗ đọc không chắc (chữ mờ, số khó đọc). Không đoán bừa.
- is_order=false nếu ảnh không phải đơn hàng.
"""


def _client():
    import anthropic

    return anthropic


def ai_read_order(image: bytes | None, media_type: str = "image/jpeg", text: str = "",
                  codes: list[str] | None = None) -> dict | None:
    """Claude đọc phiếu -> dict theo SCHEMA. None nếu không gọi được AI."""
    anthropic = _client()
    content = []
    if image:
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                     "data": base64.standard_b64encode(image).decode()}})
    hint = ("\nDanh mục mã sản phẩm của cửa hàng: " + ", ".join(codes)) if codes else ""
    content.append({"type": "text", "text": PROMPT + hint + (f"\n\nNội dung tin nhắn: {text}" if text else "")})
    try:
        response = anthropic.Anthropic().messages.create(
            model=VISION_MODEL, max_tokens=8000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIConnectionError as e:
        log.warning("Không kết nối được Claude: %s", e)
        return None
    except anthropic.APIStatusError as e:
        log.warning("Claude trả lỗi %s: %s", e.status_code, e.message)
        return None
    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    return json.loads(next((b.text for b in response.content if b.type == "text"), "{}"))


# ---------- nháp đơn ----------
def build_draft(read: dict, catalog: Catalog) -> dict:
    """Kết quả AI -> nháp: khớp mã kho, bổ sung tên/ĐVT/giá từ kho khi phiếu thiếu."""
    draft = {k: read.get(k) for k in ("doc_type", "customer", "address", "order_date", "delivery_date",
                                       "subtotal", "discount", "total", "paid_before", "paid_before_date",
                                       "pay_now", "note", "unclear")}
    draft["phone"] = clean_phone(read.get("phone", ""))
    draft["items"] = []
    for it in read.get("items") or []:
        draft["items"].append(match_item(dict(it), catalog))
    for k in ("subtotal", "discount", "total", "paid_before", "pay_now"):
        draft[k] = int(draft.get(k) or 0)
    return draft


def match_item(it: dict, catalog: Catalog) -> dict:
    prod, level = catalog.match(it.get("code", ""))
    it["match"] = level
    it["qty"] = float(it.get("qty") or 0) or 1
    it["price"] = int(it.get("price") or 0)
    it.setdefault("kind", "thuong")
    if prod:
        it["code"] = prod["code"]
        it["name"] = it.get("name") or prod.get("name", "")
        it["unit"] = it.get("unit") or prod.get("unit", "")
        if not it["price"] and it["kind"] == "thuong" and prod.get("price"):
            it["price"], it["price_from_stock"] = int(prod["price"]), True
        if prod.get("kind") == "rieng" and it["kind"] == "thuong":
            it["kind"] = "rieng"
    return it


def totals(draft: dict) -> tuple[int, int, int, int]:
    """(tổng trước giảm, tổng chốt, đã thu, còn lại)."""
    sub = int(sum(round(it["qty"] * it["price"]) for it in draft["items"]))
    total = sub - int(draft.get("discount") or 0)
    paid = int(draft.get("paid_before") or 0) + int(draft.get("pay_now") or 0)
    return sub, total, paid, total - paid


def pending_items(draft: dict) -> list[tuple[int, dict]]:
    """Hàng riêng chưa có giá -> chờ khảo sát / báo giá lại (chưa tính vào tổng, có lịch nhắc)."""
    return [(i, it) for i, it in enumerate(draft["items"], 1) if it["kind"] == "rieng" and not it["price"]]


def checks(draft: dict) -> list[str]:
    """Những chỗ cần anh kiểm tra trước khi lên Sheet."""
    out = []
    for i, it in enumerate(draft["items"], 1):
        if not it.get("match") and it["kind"] != "rieng":
            out.append(f"dòng {i}: mã {it.get('code') or '(trống)'} không có trong kho")
        elif it.get("match") == "gan":
            out.append(f"dòng {i}: mã ghi tắt, em đoán là {it['code']}")
        if it.get("price_from_stock"):
            out.append(f"dòng {i}: phiếu không ghi giá, em lấy giá kho {vnd(it['price'])}")
        if not it["price"] and it["kind"] == "thuong":
            out.append(f"dòng {i}: chưa có giá")
    sub, total, _, _ = totals(draft)
    if draft.get("total") and draft["total"] != total:
        out.append(f"tổng trên phiếu {vnd(draft['total'])} ≠ tổng em tính {vnd(total)}")
    if not draft.get("phone"):
        out.append("chưa có số điện thoại khách")
    if draft.get("unclear"):
        out.append("đọc chưa chắc: " + draft["unclear"])
    return out


def sheet_preview(draft: dict, catalog: Catalog | None = None) -> list[str]:
    """Những gì sẽ ghi vào 5 trang của Sheet khi anh trả lời "ok" (để anh xem trước trên Telegram)."""
    sub, total, paid, left = totals(draft)
    who = (draft.get("customer") or "(chưa có tên)") + (f" · {draft['phone']}" if draft.get("phone") else "")
    pays = []
    if draft.get("paid_before"):
        pays.append(f"cọc {vnd(draft['paid_before'])}"
                    + (f" ({draft['paid_before_date']})" if draft.get("paid_before_date") else ""))
    if draft.get("pay_now"):
        pays.append(f"thanh toán {vnd(draft['pay_now'])}")
    stock = []
    for it in draft["items"]:
        if it["kind"] == "rieng" or not it.get("code"):
            continue
        prod = catalog.match(it["code"])[0] if catalog else None
        if prod is None:
            stock.append(f"{it['code']} (mã mới, thêm vào KHO)")
            continue
        have = int(prod.get("stock") or 0)
        need = max(0, round(it["qty"]) - have)
        stock.append(f"{prod['code']} đặt {it['qty']:g}, tồn {have}" + (f" → cần nhập {need}" if need else " ✅ đủ"))
    return ["📋 Khi anh trả lời \"ok\", em ghi vào Sheet:",
            f"• KHÁCH HÀNG: {who} (chưa có thì thêm mới, có rồi thì cập nhật theo SĐT)",
            f"• ĐƠN HÀNG: 1 đơn mới – tổng chốt {vnd(total)} – {'Đã chốt' if paid else 'Chưa cọc'}",
            f"• CHI TIẾT ĐƠN: {len(draft['items'])} dòng",
            "• THU TIỀN: " + (" + ".join(pays) if pays else "chưa có tiền thu"),
            "• KHO: " + ("; ".join(stock) if stock else "không có mã cần theo dõi")]


def render(draft_id: int, draft: dict, sender: str = "", title: str = "NHÁP ĐƠN",
           catalog: Catalog | None = None) -> str:
    sub, total, paid, left = totals(draft)
    lines = [f"🛒 SALE – {title} – N{draft_id}",
             f"👤 {draft.get('customer') or '(chưa có tên)'}" + (f" · {draft['phone']}" if draft.get("phone") else "")]
    where = " · ".join(p for p in (f"📍 {draft['address']}" if draft.get("address") else "",
                                   f"🚚 giao {draft['delivery_date']}" if draft.get("delivery_date") else "") if p)
    if where:
        lines.append(where)
    for i, it in enumerate(draft["items"], 1):
        mark = {"dung": "", "gan": " ❓", "": " ⚠️"}[it.get("match") or ""] if it["kind"] != "rieng" else ""
        price = f"{vnd(it['price'])}" if it["price"] or it["kind"] == "tang" else "chưa có giá"
        lines.append(f"{i}. {it.get('code') or '?'} – {it.get('name') or ''} – {it['qty']:g} {it.get('unit') or ''} × "
                     f"{price} = {vnd(round(it['qty'] * it['price']))}{KINDS.get(it['kind'], '')}{mark}")
    money_line = f"💵 Tổng {vnd(sub)}"
    if draft.get("discount"):
        money_line += f" · Giảm {vnd(draft['discount'])} · Chốt {vnd(total)}"
    lines.append(money_line)
    if paid:
        parts = []
        if draft.get("paid_before"):
            parts.append(f"cọc/đã thu {vnd(draft['paid_before'])}"
                         + (f" ({draft['paid_before_date']})" if draft.get("paid_before_date") else ""))
        if draft.get("pay_now"):
            parts.append(f"thu lần này {vnd(draft['pay_now'])}")
        lines.append("💰 " + " + ".join(parts) + f" · Còn lại {vnd(left)}")
    else:
        lines.append("💰 Chưa cọc")
    for i, it in pending_items(draft):
        lines.append(f"🛠 Dòng {i} hàng riêng chờ khảo sát/báo giá – lên Sheet xong Bot Sale sẽ nhắc anh")
    if draft.get("note"):
        lines.append(f"📝 {draft['note']}")
    todo = checks(draft)
    if todo:
        lines.append("❓ Cần kiểm tra: " + "; ".join(todo))
    if sender:
        lines.append(f"👤 Gửi: {sender}")
    if title == "NHÁP ĐƠN":
        lines += [""] + sheet_preview(draft, catalog)
        lines += ["", "✏️ Sửa: TRẢ LỜI (reply) tin này, mỗi dòng 1 lệnh:",
                  "3 sl 2 · 3 gia 1460000 · 3 ma H-2200V · xoa 4 · them H-B1639 1 850k · rieng 9 · tang 4",
                  "khach … · sdt … · dc … · giao 20/11 · coc 5tr 06/10 · thu 16tr6 · giam 2120000 · ghichu …",
                  "✅ Đúng hết: trả lời \"ok\" để lên Google Sheet · ❌ \"huy\" để bỏ"]
    return "\n".join(lines)


FIELDS = {"khach": "customer", "ten khach": "customer", "sdt": "phone", "dt": "phone", "dien thoai": "phone",
          "dc": "address", "dia chi": "address", "giao": "delivery_date", "ngay giao": "delivery_date",
          "ghichu": "note", "ghi chu": "note", "gc": "note"}
ITEM_FIELDS = {"sl": "qty", "so luong": "qty", "gia": "price", "dg": "price", "don gia": "price",
               "ma": "code", "ten": "name", "dvt": "unit"}


def apply_edits(draft: dict, text: str, catalog: Catalog) -> tuple[str | None, list[str]]:
    """Áp lệnh sửa vào nháp. Trả về (hành động "ok"/"huy"/None, các dòng không hiểu)."""
    bad = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        key = norm(line)
        if key in ("ok", "oke", "okie", "dung", "duyet", "len sheet", "chot", "luu", "xong"):
            return "ok", bad
        if key in ("huy", "bo", "xoa nhap", "huy nhap"):
            return "huy", bad
        if not _apply_line(draft, line, key, catalog):
            bad.append(line)
    return None, bad


def _apply_line(draft: dict, line: str, key: str, catalog: Catalog) -> bool:
    words = line.split()
    items = draft["items"]
    m = re.match(r"^(\d+)\s+(\S+(?:\s+(?:luong|gia))?)\s+(.+)$", line)
    if m and norm(m.group(2)) in ITEM_FIELDS:
        i, field, value = int(m.group(1)), ITEM_FIELDS[norm(m.group(2))], m.group(3).strip()
        if not 1 <= i <= len(items):
            return False
        it = items[i - 1]
        if field == "qty":
            qty = money(value) if not re.fullmatch(r"\d+(?:[.,]\d+)?", value) else float(value.replace(",", "."))
            if not qty:
                return False
            it["qty"] = float(qty)
        elif field == "price":
            price = money(value)
            if price is None:
                return False
            it["price"], it["price_from_stock"] = price, False
        elif field == "code":
            it.update({"code": value, "name": "", "unit": "", "price_from_stock": False})
            old_price = it["price"]
            match_item(it, catalog)
            it["price"] = old_price or it["price"]
        else:
            it[field] = value
        return True
    head = norm(words[0]) if words else ""
    if head in ("xoa", "bo") and len(words) == 2 and words[1].isdigit():
        i = int(words[1])
        if not 1 <= i <= len(items):
            return False
        items.pop(i - 1)
        return True
    if head in ("rieng", "tang") and len(words) == 2 and words[1].isdigit():
        i = int(words[1])
        if not 1 <= i <= len(items):
            return False
        items[i - 1]["kind"] = "rieng" if head == "rieng" else "tang"
        if head == "tang":
            items[i - 1]["price"] = 0
        return True
    if head == "them" and len(words) >= 2:
        it = {"code": words[1], "name": "", "unit": "", "qty": 1, "price": 0, "kind": "thuong", "note": ""}
        if len(words) >= 3:
            it["qty"] = float(words[2].replace(",", ".")) if re.fullmatch(r"\d+(?:[.,]\d+)?", words[2]) else 1
        if len(words) >= 4:
            it["price"] = money(words[3]) or 0
        items.append(match_item(it, catalog))
        return True
    if head in ("coc", "thu", "giam"):
        amount = money(words[1]) if len(words) > 1 else None
        if amount is None:
            return False
        if head == "giam":
            draft["discount"] = amount
        elif head == "thu":
            draft["pay_now"] = amount
        else:
            draft["paid_before"] = amount
            draft["paid_before_date"] = words[2] if len(words) > 2 else datetime.now().strftime("%d/%m/%Y")
        return True
    for phrase in sorted(FIELDS, key=len, reverse=True):
        n = len(phrase.split())
        if norm(" ".join(words[:n])) == phrase and len(words) > n:
            value = line.split(None, n)[n].strip()
            draft[FIELDS[phrase]] = clean_phone(value) if FIELDS[phrase] == "phone" else value
            return True
    return False


def sheet_payload(draft: dict, sender: str, image: str, msg_id: str) -> dict:
    sub, total, paid, left = totals(draft)
    return {
        "customer": draft.get("customer", ""), "phone": draft.get("phone", ""), "address": draft.get("address", ""),
        "orderDate": draft.get("order_date") or datetime.now().strftime("%d/%m/%Y"),
        "deliveryDate": draft.get("delivery_date", ""), "subtotal": sub, "discount": int(draft.get("discount") or 0),
        "total": total, "paidBefore": int(draft.get("paid_before") or 0),
        "paidBeforeDate": draft.get("paid_before_date", ""), "payNow": int(draft.get("pay_now") or 0),
        "paid": paid, "left": left, "status": "Đã chốt" if paid else "Chưa cọc",
        "pending": "; ".join(f"{it.get('code')} {it.get('name')}".strip() for _, it in pending_items(draft)),
        "note": draft.get("note", ""), "sender": sender, "image": image, "msgId": msg_id,
        "items": [{"code": it.get("code", ""), "name": it.get("name", ""), "unit": it.get("unit", ""),
                   "qty": it["qty"], "price": it["price"], "amount": round(it["qty"] * it["price"]),
                   "kind": {"thuong": "Hàng sẵn", "tang": "Tặng", "rieng": "Hàng riêng"}[it["kind"]],
                   "note": it.get("note", ""),
                   "match": {"dung": "Đúng mã", "gan": "Mã gần đúng", "": "Không có trong kho"}[it.get("match") or ""]}
                  for it in draft["items"]],
    }


class OrderSheet:
    """Google Sheet đơn hàng (Apps Script google-sheet/DonHang.gs): lấy danh mục kho, ghi đơn."""

    def __init__(self, url: str, token: str):
        self.url, self.token = url, token

    def _post(self, payload: dict) -> dict:
        body = json.dumps({**payload, "token": self.token}, ensure_ascii=False).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode() or "{}")

    def products(self) -> list[dict]:
        res = self._post({"action": "products"})
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or "Sheet đơn hàng từ chối")
        return res.get("products", [])

    def save_order(self, order: dict) -> dict:
        return self._post({"action": "order", "order": order})
