"""Tổng hợp báo cáo: thiếu hàng, tủ lavabo cần đặt xưởng, nhắc đặt hàng."""
from collections import defaultdict
from datetime import datetime

from .db import Store, fmt_qty


def _date(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d/%m")


def _days_since(iso_or_dt, now: datetime) -> int:
    dt = datetime.fromisoformat(iso_or_dt) if isinstance(iso_or_dt, str) else iso_or_dt
    return (now - dt).days


def compute_shortages(store: Store):
    """Chia tồn kho cho đơn cũ trước. Trả về {khách: [(mã đơn, sản phẩm, thiếu, cần)]} và nhu cầu theo sản phẩm."""
    stock = {k: r["qty"] for k, r in store.stock_map().items()}
    short = defaultdict(list)
    demand = defaultdict(float)
    names = {}
    for it in store.open_items():
        if it["is_lavabo"]:
            continue
        need = it["qty"] - it["delivered"]
        key = it["product_key"]
        names[key] = it["product"]
        demand[key] += need
        have = stock.get(key, 0)
        take = min(have, need)
        stock[key] = have - take
        if need - take > 0:
            short[(it["customer"], it["phone"])].append((it["oid"], it["product"], need - take, need, it["created_at"]))
    return short, demand, names


def report_shortage(store: Store) -> str:
    short, _, _ = compute_shortages(store)
    if not short:
        return "✅ Không khách nào bị thiếu hàng (kho đủ cho tất cả đơn đang mở)."
    lines = [f"⚠️ THIẾU HÀNG – {len(short)} khách"]
    for (customer, phone), rows in sorted(short.items(), key=lambda kv: min(r[4] for r in kv[1])):
        lines.append(f"\n👤 {customer}" + (f" ({phone})" if phone else ""))
        for oid, product, missing, need, created in rows:
            lines.append(f"  • #{oid} {product}: thiếu {fmt_qty(missing)}/{fmt_qty(need)} (đơn {_date(created)})")
    return "\n".join(lines)


def report_lavabo(store: Store, now: datetime | None = None, wait_warn_days: int = 10) -> str:
    now = now or datetime.now()
    todo, waiting = defaultdict(list), []
    for it in store.open_items():
        if not it["is_lavabo"]:
            continue
        need = it["qty"] - it["delivered"]
        if it["factory_ordered_at"] is None:
            todo[(it["customer"], it["phone"], it["oid"], it["created_at"])].append(f"{fmt_qty(need)} {it['product']}")
        else:
            waiting.append((it, need))
    lines = []
    if todo:
        lines.append(f"🛁 CẦN LÊN ĐƠN TỦ LAVABO – {len(todo)} đơn")
        for (customer, phone, oid, created), products in sorted(todo.items(), key=lambda kv: kv[0][3]):
            days = _days_since(created, now)
            lines.append(f"  • #{oid} {customer}" + (f" ({phone})" if phone else "")
                         + f" – {', '.join(products)} – chờ {days} ngày")
        lines.append("  → Đặt xưởng xong gõ: /datxuong <mã đơn>")
    else:
        lines.append("✅ Không còn tủ lavabo nào chưa lên đơn xưởng.")
    late = [(it, n) for it, n in waiting if _days_since(it["factory_ordered_at"], now) >= wait_warn_days]
    if waiting:
        lines.append(f"\n⏳ Đang chờ xưởng: {len(waiting)} dòng" + (f", {len(late)} dòng quá {wait_warn_days} ngày:" if late else ""))
        for it, n in late:
            lines.append(f"  • #{it['oid']} {it['customer']} – {fmt_qty(n)} {it['product']} "
                         f"(đặt {_date(it['factory_ordered_at'])}, {_days_since(it['factory_ordered_at'], now)} ngày)")
    return "\n".join(lines)


def report_reorder(store: Store, now: datetime | None = None, idle_days: int = 45) -> str:
    now = now or datetime.now()
    lines = []

    # 1) Nhập hàng từ nhà cung cấp: nhu cầu đơn mở + tồn tối thiểu - tồn hiện có
    _, demand, names = compute_shortages(store)
    stock = store.stock_map()
    to_buy = []
    for key in set(demand) | set(stock):
        have = stock[key]["qty"] if key in stock else 0
        min_qty = stock[key]["min_qty"] if key in stock else 0
        need = demand.get(key, 0) + min_qty - have
        if need > 0:
            to_buy.append((names.get(key) or stock[key]["product"], need, have, demand.get(key, 0)))
    if to_buy:
        lines.append("📦 CẦN ĐẶT HÀNG NHÀ CUNG CẤP")
        for product, need, have, dem in sorted(to_buy, key=lambda r: -r[1]):
            lines.append(f"  • {product}: đặt thêm {fmt_qty(need)} (tồn {fmt_qty(have)}, khách đang chờ {fmt_qty(dem)})")
    else:
        lines.append("✅ Tồn kho đủ, chưa cần nhập thêm.")

    # 2) Khách quen đến kỳ đặt lại
    due = []
    for name, info in store.customer_order_dates().items():
        dates = info["dates"]
        since = (now - dates[-1]).days
        if len(dates) >= 2:
            gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
            cycle = max(sum(gaps) / len(gaps), 3)
            if since >= cycle:
                due.append((name, info["phone"], since, f"thường {round(cycle)} ngày đặt 1 lần"))
        elif since >= idle_days:
            due.append((name, info["phone"], since, "mới đặt 1 lần"))
    if due:
        lines.append("\n📞 NHẮC GỌI KHÁCH ĐẶT LẠI")
        for name, phone, since, why in sorted(due, key=lambda r: -r[2]):
            lines.append(f"  • {name}" + (f" ({phone})" if phone else "") + f": {since} ngày chưa đặt – {why}")
    return "\n".join(lines)


def report_open_orders(store: Store) -> str:
    orders = store.open_orders()
    if not orders:
        return "Không có đơn nào đang mở."
    lines = [f"📋 ĐƠN ĐANG MỞ – {len(orders)}"]
    for o in orders:
        _, items = store.get_order(o["id"])
        parts = [f"{fmt_qty(i['delivered'])}/{fmt_qty(i['qty'])} {i['product']}" for i in items]
        lines.append(f"  • #{o['id']} {o['customer']} ({_date(o['created_at'])}): " + "; ".join(parts))
    return "\n".join(lines)


def full_report(store: Store, now: datetime | None = None) -> str:
    now = now or datetime.now()
    return "\n\n".join([
        f"🗓 BÁO CÁO NGÀY {now.strftime('%d/%m/%Y')}",
        report_lavabo(store, now),
        report_shortage(store),
        report_reorder(store, now),
    ])
