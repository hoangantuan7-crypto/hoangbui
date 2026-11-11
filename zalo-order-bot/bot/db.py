"""Lưu trữ đơn hàng, tồn kho bằng SQLite."""
import sqlite3
from datetime import datetime

from .text import is_lavabo_cabinet, norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,
    phone TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',      -- open | done | cancelled
    note TEXT DEFAULT '',
    source_chat TEXT DEFAULT '',
    raw_text TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product TEXT NOT NULL,
    product_key TEXT NOT NULL,
    qty REAL NOT NULL,
    delivered REAL NOT NULL DEFAULT 0,
    is_lavabo INTEGER NOT NULL DEFAULT 0,
    factory_ordered_at TEXT                     -- ngày đã lên đơn xưởng (tủ lavabo)
);
CREATE TABLE IF NOT EXISTS stock (
    product_key TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    qty REAL NOT NULL DEFAULT 0,
    min_qty REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chats (
    chat_id TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    subscribed INTEGER NOT NULL DEFAULT 0
);
"""


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path: str = "orders.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- khách hàng ----------
    def get_or_create_customer(self, name: str, phone: str = "") -> int:
        key = norm(name)
        row = self.conn.execute("SELECT id, phone FROM customers WHERE key=?", (key,)).fetchone()
        if row:
            if phone and not row["phone"]:
                self.conn.execute("UPDATE customers SET phone=? WHERE id=?", (phone, row["id"]))
            return row["id"]
        cur = self.conn.execute("INSERT INTO customers(name, key, phone) VALUES (?,?,?)", (name.strip(), key, phone))
        return cur.lastrowid

    # ---------- đơn hàng ----------
    def add_order(self, customer: str, items, phone="", note="", chat_id="", raw="", created_at=None) -> int:
        cid = self.get_or_create_customer(customer, phone)
        cur = self.conn.execute(
            "INSERT INTO orders(customer_id, created_at, note, source_chat, raw_text) VALUES (?,?,?,?,?)",
            (cid, created_at or now_iso(), note, str(chat_id), raw),
        )
        oid = cur.lastrowid
        for product, qty in items:
            self.conn.execute(
                "INSERT INTO order_items(order_id, product, product_key, qty, is_lavabo) VALUES (?,?,?,?,?)",
                (oid, product.strip(), norm(product), float(qty), int(is_lavabo_cabinet(product))),
            )
        self.conn.commit()
        return oid

    def get_order(self, oid: int):
        order = self.conn.execute(
            "SELECT o.*, c.name AS customer, c.phone FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.id=?",
            (oid,),
        ).fetchone()
        if not order:
            return None, []
        items = self.conn.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY id", (oid,)).fetchall()
        return order, items

    def open_items(self):
        """Các dòng hàng chưa giao đủ, đơn cũ trước (để chia tồn kho theo thứ tự)."""
        return self.conn.execute(
            """SELECT i.*, o.created_at, o.id AS oid, c.name AS customer, c.phone
               FROM order_items i JOIN orders o ON o.id=i.order_id JOIN customers c ON c.id=o.customer_id
               WHERE o.status='open' AND i.delivered < i.qty
               ORDER BY o.created_at, i.id"""
        ).fetchall()

    def open_orders(self):
        return self.conn.execute(
            """SELECT o.id, o.created_at, c.name AS customer FROM orders o JOIN customers c ON c.id=o.customer_id
               WHERE o.status='open' ORDER BY o.created_at"""
        ).fetchall()

    def deliver(self, oid: int, product: str | None = None, qty: float | None = None) -> list[str]:
        """Ghi nhận giao hàng; trừ tồn kho. Không chỉ định sản phẩm = giao hết phần còn lại."""
        order, items = self.get_order(oid)
        if not order:
            raise ValueError(f"Không có đơn #{oid}")
        done = []
        key = norm(product) if product else None
        for it in items:
            remaining = it["qty"] - it["delivered"]
            if remaining <= 0 or (key and key not in it["product_key"]):
                continue
            amount = remaining if qty is None else min(qty, remaining)
            self.conn.execute("UPDATE order_items SET delivered=delivered+? WHERE id=?", (amount, it["id"]))
            if not it["is_lavabo"]:  # tủ lavabo làm theo đơn, không lấy từ kho
                self.conn.execute("UPDATE stock SET qty=MAX(qty-?,0) WHERE product_key=?", (amount, it["product_key"]))
            done.append(f"{fmt_qty(amount)} {it['product']}")
            if qty is not None:
                break
        if not done:
            raise ValueError("Không tìm thấy dòng hàng cần giao trong đơn")
        self._close_if_complete(oid)
        self.conn.commit()
        return done

    def _close_if_complete(self, oid: int):
        left = self.conn.execute("SELECT COUNT(*) FROM order_items WHERE order_id=? AND delivered<qty", (oid,)).fetchone()[0]
        if left == 0:
            self.conn.execute("UPDATE orders SET status='done' WHERE id=?", (oid,))

    def cancel(self, oid: int):
        cur = self.conn.execute("UPDATE orders SET status='cancelled' WHERE id=? AND status='open'", (oid,))
        self.conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"Đơn #{oid} không tồn tại hoặc đã đóng")

    def mark_factory_ordered(self, oid: int) -> int:
        cur = self.conn.execute(
            "UPDATE order_items SET factory_ordered_at=? WHERE order_id=? AND is_lavabo=1 AND factory_ordered_at IS NULL",
            (now_iso(), oid),
        )
        self.conn.commit()
        return cur.rowcount

    def customer_order_dates(self):
        rows = self.conn.execute(
            """SELECT c.name, c.phone, o.created_at FROM orders o JOIN customers c ON c.id=o.customer_id
               WHERE o.status!='cancelled' ORDER BY c.id, o.created_at"""
        ).fetchall()
        result: dict[str, dict] = {}
        for r in rows:
            entry = result.setdefault(r["name"], {"phone": r["phone"], "dates": []})
            entry["dates"].append(datetime.fromisoformat(r["created_at"]))
        return result

    # ---------- tồn kho ----------
    def add_stock(self, product: str, qty: float, set_exact: bool = False, min_qty: float | None = None):
        key = norm(product)
        row = self.conn.execute("SELECT qty FROM stock WHERE product_key=?", (key,)).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO stock(product_key, product, qty, min_qty) VALUES (?,?,?,?)",
                (key, product.strip(), qty, min_qty or 0),
            )
        else:
            new_qty = qty if set_exact else row["qty"] + qty
            self.conn.execute("UPDATE stock SET qty=? WHERE product_key=?", (new_qty, key))
            if min_qty is not None:
                self.conn.execute("UPDATE stock SET min_qty=? WHERE product_key=?", (min_qty, key))
        self.conn.commit()

    def stock_map(self) -> dict[str, sqlite3.Row]:
        return {r["product_key"]: r for r in self.conn.execute("SELECT * FROM stock ORDER BY product")}

    # ---------- nhóm chat nhận báo cáo ----------
    def subscribe(self, chat_id: str, name: str = "", on: bool = True):
        self.conn.execute(
            "INSERT INTO chats(chat_id, name, subscribed) VALUES (?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET subscribed=excluded.subscribed",
            (str(chat_id), name, int(on)),
        )
        self.conn.commit()

    def subscribed_chats(self) -> list[str]:
        return [r["chat_id"] for r in self.conn.execute("SELECT chat_id FROM chats WHERE subscribed=1")]


def fmt_qty(q: float) -> str:
    return str(int(q)) if float(q).is_integer() else f"{q:g}"
