"""Xử lý một tin nhắn -> câu trả lời (không phụ thuộc Zalo, dễ kiểm thử)."""
import re

from . import reports
from .ai_parser import ai_available, ai_parse_order
from .db import Store, fmt_qty
from .departments import TONG, dept_icon, dept_list, dept_name, parse_dept
from .text import norm
from .parser import looks_like_order, parse_command, parse_order, parse_product_qty

HELP = """🤖 BOT ĐƠN HÀNG – hướng dẫn

📝 Ghi đơn (gõ tin bắt đầu bằng "Đơn"):
  Đơn anh Nam 0912345678: 2 tủ lavabo 80cm; 5 vòi sen
  hoặc xuống dòng từng sản phẩm, thêm "Ghi chú: ..." nếu cần.

🚚 /giao <mã> – giao hết đơn | /giao <mã> vòi sen 2 – giao 1 phần
🏭 /datxuong <mã> – đã lên đơn tủ lavabo cho xưởng
❌ /huy <mã> | 🔎 /xem <mã>
📦 /nhap vòi sen 20 – nhập kho | /ton vòi sen 15 – đặt lại tồn | /ton – xem kho
📉 /toithieu vòi sen 5 – tồn tối thiểu để bot nhắc nhập

🔔 Tin khách: /choxuly – việc chưa xử lý | /xong K5 – đã xử lý
↪️ /chuyen K5 kho – chuyển việc sang bộ phận khác (sale, ketoan, kho, kythuat) | /bophan – chat này thuộc bộ phận nào

📊 Báo cáo:
  /thieu – khách nào đang thiếu hàng
  /lavabo – cần lên đơn tủ lavabo cho ai
  /nhac – nhắc đặt hàng NCC + gọi khách quen
  /donmo – các đơn đang mở
  /baocao – báo cáo tổng hợp
🔔 /dangky – nhóm này nhận báo cáo tự động mỗi ngày | /huydangky"""


def _order_id(args: str) -> tuple[int, str]:
    m = re.match(r"^#?(\d+)\s*(.*)$", args.strip(), re.DOTALL)
    if not m:
        raise ValueError("Thiếu mã đơn, ví dụ: /giao 12")
    return int(m.group(1)), m.group(2).strip()


def _confirm_order(store: Store, oid: int) -> str:
    order, items = store.get_order(oid)
    lines = [f"✅ Đã ghi đơn #{oid} – {order['customer']}" + (f" ({order['phone']})" if order["phone"] else "")]
    for it in items:
        tag = " 🛁 (cần đặt xưởng)" if it["is_lavabo"] else ""
        lines.append(f"  • {fmt_qty(it['qty'])} {it['product']}{tag}")
    if order["note"]:
        lines.append(f"  📝 {order['note']}")
    return "\n".join(lines)


def handle_message(store: Store, text: str, chat_id: str = "", sender: str = "", use_ai: bool = True,
                   default_customer: str = "", phone: str = "") -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        cmd = parse_command(text)
        if cmd:
            return _handle_command(store, cmd.name, cmd.args, chat_id, sender, text)
        order = parse_order(text, default_customer)
        if order is None and use_ai and looks_like_order(text) and ai_available():
            order = ai_parse_order(text, default_customer or sender)
        if order:
            order.phone = order.phone or phone
            oid = store.add_order(order.customer, order.items, order.phone, order.note, chat_id, text)
            return _confirm_order(store, oid)
    except ValueError as e:
        return f"⚠️ {e}"
    return None  # tin nhắn thường: bot im lặng


def _handle_command(store: Store, name: str, args: str, chat_id: str, sender: str, raw: str) -> str:
    if name == "help":
        return HELP
    if name == "don":
        order = parse_order("Đơn " + args)
        if not order:
            raise ValueError("Không đọc được đơn. Ví dụ: /don anh Nam: 2 tủ lavabo 80cm; 5 vòi sen")
        return _confirm_order(store, store.add_order(order.customer, order.items, order.phone, order.note, chat_id, raw))
    if name == "giao":
        oid, rest = _order_id(args)
        product, qty = None, None
        if rest:
            pq = parse_product_qty(rest)
            product, qty = pq if pq else (rest, None)
        done = store.deliver(oid, product, qty)
        order, _ = store.get_order(oid)
        status = "đã giao đủ ✅" if order["status"] == "done" else "còn hàng chưa giao"
        return f"🚚 Đơn #{oid} ({order['customer']}): giao {', '.join(done)} – {status}"
    if name == "datxuong":
        oid, _ = _order_id(args)
        n = store.mark_factory_ordered(oid)
        return f"🏭 Đơn #{oid}: đã ghi nhận lên đơn xưởng {n} dòng tủ lavabo." if n else f"Đơn #{oid} không có tủ lavabo nào chờ đặt."
    if name == "huy":
        oid, _ = _order_id(args)
        store.cancel(oid)
        return f"❌ Đã hủy đơn #{oid}"
    if name == "xem":
        oid, _ = _order_id(args)
        order, items = store.get_order(oid)
        if not order:
            raise ValueError(f"Không có đơn #{oid}")
        lines = [f"🔎 Đơn #{oid} – {order['customer']} – {order['status']} – {order['created_at'][:10]}"]
        for it in items:
            extra = ""
            if it["is_lavabo"]:
                extra = f" 🏭 đặt xưởng {it['factory_ordered_at'][:10]}" if it["factory_ordered_at"] else " 🛁 chưa đặt xưởng"
            lines.append(f"  • {it['product']}: đã giao {fmt_qty(it['delivered'])}/{fmt_qty(it['qty'])}{extra}")
        return "\n".join(lines)
    if name in ("nhap", "ton", "toithieu"):
        if name == "ton" and not args:
            rows = store.stock_map().values()
            if not rows:
                return "Kho trống. Dùng /nhap <sản phẩm> <số lượng>."
            return "📦 TỒN KHO\n" + "\n".join(
                f"  • {r['product']}: {fmt_qty(r['qty'])}" + (f" (tối thiểu {fmt_qty(r['min_qty'])})" if r["min_qty"] else "")
                for r in rows)
        pq = parse_product_qty(args)
        if not pq:
            raise ValueError(f"Cú pháp: /{name} <sản phẩm> <số lượng>")
        product, qty = pq
        if name == "nhap":
            store.add_stock(product, qty)
            return f"📥 Nhập {fmt_qty(qty)} {product}. Tồn: {fmt_qty(store.stock_map()[norm(product)]['qty'])}"
        if name == "ton":
            store.add_stock(product, qty, set_exact=True)
            return f"📦 Tồn {product} = {fmt_qty(qty)}"
        store.add_stock(product, 0, min_qty=qty)
        return f"📉 Tồn tối thiểu {product} = {fmt_qty(qty)}"
    if name == "choxuly":
        return reports.report_leads(store)
    if name == "xong":
        m = re.match(r"^[kK#]?(\d+)$", args.strip())
        if not m:
            raise ValueError("Cú pháp: /xong K<mã>, ví dụ /xong K5")
        if not store.close_leads(int(m.group(1))):
            raise ValueError(f"Không có tin K{m.group(1)} đang chờ")
        return f"👍 Đã xử lý tin K{m.group(1)}"
    if name == "chuyen":
        parts = args.split()
        m = re.match(r"^[kK#]?(\d+)$", parts[0]) if parts else None
        dept = parse_dept(parts[1]) if len(parts) > 1 else None
        if not m or dept in (None, TONG):
            raise ValueError(f"Cú pháp: /chuyen K<mã> <bộ phận>. Bộ phận: {dept_list()}")
        if not store.set_lead_dept(int(m.group(1)), dept):
            raise ValueError(f"Không có tin K{m.group(1)} đang chờ")
        return f"↪️ Đã chuyển K{m.group(1)} sang {dept_icon(dept)} {dept_name(dept)}"
    if name == "bophan":
        return "Chat này nhận tất cả tin."
    if name == "thieu":
        return reports.report_shortage(store)
    if name == "lavabo":
        return reports.report_lavabo(store)
    if name == "nhac":
        return reports.report_reorder(store)
    if name == "donmo":
        return reports.report_open_orders(store)
    if name == "baocao":
        return reports.full_report(store)
    if name == "dangky":
        store.subscribe(chat_id, sender, True)
        return "🔔 Đã đăng ký: cuộc trò chuyện này sẽ nhận báo cáo tự động mỗi ngày."
    if name == "huydangky":
        store.subscribe(chat_id, sender, False)
        return "🔕 Đã hủy nhận báo cáo tự động."
    return HELP

