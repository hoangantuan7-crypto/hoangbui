"""Lưu trữ đơn hàng, tồn kho bằng SQLite."""
import sqlite3
import threading
from datetime import datetime, timedelta

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
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY,
    conv_id TEXT NOT NULL,
    customer TEXT NOT NULL,
    phone TEXT DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'order',        -- order | payment
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',       -- open | done
    reminded_at TEXT
);
CREATE TABLE IF NOT EXISTS seen_messages (
    id TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conv_state (       -- theo dõi khách chờ shop trả lời
    conv_id TEXT PRIMARY KEY,
    customer TEXT NOT NULL DEFAULT '',
    phone TEXT DEFAULT '',
    thread_type TEXT DEFAULT 'user',
    waiting INTEGER NOT NULL DEFAULT 0,        -- 1 = khách đang chờ shop trả lời
    wait_since TEXT,                           -- giờ (UTC) tin đầu tiên chưa được trả lời
    last_customer_at TEXT,
    last_customer_text TEXT DEFAULT '',
    last_shop_at TEXT,
    remind_level INTEGER NOT NULL DEFAULT 0    -- đã nhắc mấy lần cho lượt chờ này
);
CREATE TABLE IF NOT EXISTS known_convs (       -- cuộc trò chuyện bot đã biết (để nhận ra khách mới / nhóm mới)
    conv_key TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
    chat_id TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    subscribed INTEGER NOT NULL DEFAULT 0
);
"""


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class _Result:
    """Kết quả truy vấn đã đọc hết trong lúc giữ khóa (an toàn khi nhiều luồng dùng chung)."""

    def __init__(self, cur):
        self._rows = cur.fetchall() if cur.description else []
        self.rowcount, self.lastrowid = cur.rowcount, cur.lastrowid

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _LockedConnection:
    """Kết nối SQLite dùng chung cho 5 bot + vòng đọc Zalo + lịch báo cáo: mỗi lệnh chạy trọn trong khóa."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn, self._lock = conn, threading.RLock()

    def execute(self, sql, params=()):
        with self._lock:
            return _Result(self._conn.execute(sql, params))

    def executemany(self, sql, seq):
        with self._lock:
            return _Result(self._conn.executemany(sql, seq))

    def executescript(self, sql):
        with self._lock:
            self._conn.executescript(sql)

    def commit(self):
        with self._lock:
            self._conn.commit()


class Store:
    def __init__(self, path: str = "orders.db"):
        raw = sqlite3.connect(path, check_same_thread=False)
        raw.row_factory = sqlite3.Row
        self.conn = _LockedConnection(raw)
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Nâng cấp CSDL cũ: thêm bộ phận cho chat, đổi loại tin cũ sang bộ phận."""
        try:
            self.conn.execute("ALTER TABLE chats ADD COLUMN dept TEXT NOT NULL DEFAULT 'tong'")
        except sqlite3.OperationalError:
            pass  # đã có cột
        try:
            self.conn.execute("ALTER TABLE leads ADD COLUMN closed_at TEXT")  # lúc xử lý xong (để báo cáo họp)
        except sqlite3.OperationalError:
            pass
        self.conn.execute("UPDATE leads SET kind='sale' WHERE kind='order'")
        self.conn.execute("UPDATE leads SET kind='ketoan' WHERE kind='payment'")

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

    # ---------- tin khách cần xử lý (không để trượt đơn) ----------
    def add_lead(self, conv_id: str, customer: str, phone: str, kind: str, text: str,
                 merge_minutes: int = 120, now: datetime | None = None) -> tuple[int, bool]:
        """Ghi tin khách. Tin cùng khách trong merge_minutes được gộp vào tin đang mở.
        Trả về (mã, là_tin_mới)."""
        ts = (now or datetime.now()).replace(microsecond=0)
        row = self.conn.execute(
            "SELECT id, text, updated_at FROM leads WHERE conv_id=? AND status='open' AND kind=? ORDER BY id DESC LIMIT 1",
            (conv_id, kind),
        ).fetchone()
        if row and (ts - datetime.fromisoformat(row["updated_at"])).total_seconds() <= merge_minutes * 60:
            self.conn.execute("UPDATE leads SET text=?, updated_at=? WHERE id=?",
                              (row["text"] + "\n" + text, ts.isoformat(), row["id"]))
            self.conn.commit()
            return row["id"], False
        cur = self.conn.execute(
            "INSERT INTO leads(conv_id, customer, phone, kind, text, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (conv_id, customer, phone, kind, text, ts.isoformat(), ts.isoformat()),
        )
        self.conn.commit()
        return cur.lastrowid, True

    def close_leads(self, lead_id: int | None = None, conv_id: str | None = None) -> int:
        if lead_id is not None:
            cur = self.conn.execute("UPDATE leads SET status='done', closed_at=? WHERE id=? AND status='open'",
                                    (now_iso(), lead_id))
        else:
            cur = self.conn.execute("UPDATE leads SET status='done', closed_at=? WHERE conv_id=? AND status='open'",
                                    (now_iso(), conv_id))
        self.conn.commit()
        return cur.rowcount

    def open_leads(self, dept: str | None = None):
        if dept:
            return self.conn.execute("SELECT * FROM leads WHERE status='open' AND kind=? ORDER BY created_at",
                                     (dept,)).fetchall()
        return self.conn.execute("SELECT * FROM leads WHERE status='open' ORDER BY created_at").fetchall()

    def leads_since(self, since: datetime, dept: str | None = None):
        """Việc nhận mới và việc đã xong kể từ `since` (cho báo cáo họp)."""
        ts = since.replace(microsecond=0).isoformat()
        where, args = ("AND kind=?", (dept,)) if dept else ("", ())
        new = self.conn.execute(f"SELECT * FROM leads WHERE created_at>=? {where} ORDER BY id", (ts, *args)).fetchall()
        done = self.conn.execute(f"SELECT * FROM leads WHERE closed_at>=? {where} ORDER BY id", (ts, *args)).fetchall()
        return new, done

    def get_lead(self, lead_id: int):
        return self.conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()

    def set_lead_dept(self, lead_id: int, dept: str) -> bool:
        cur = self.conn.execute("UPDATE leads SET kind=?, reminded_at=NULL WHERE id=? AND status='open'",
                                (dept, lead_id))
        self.conn.commit()
        return cur.rowcount == 1

    def leads_to_remind(self, minutes: int, now: datetime | None = None):
        cutoff = ((now or datetime.now()) - timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
        return self.conn.execute(
            "SELECT * FROM leads WHERE status='open' AND created_at<=? AND reminded_at IS NULL ORDER BY created_at",
            (cutoff,),
        ).fetchall()

    def mark_conv_replied(self, conv_id: str):
        self.conn.execute("UPDATE leads SET reminded_at=? WHERE conv_id=? AND status='open' AND reminded_at IS NULL",
                          (now_iso(), conv_id))
        self.conn.commit()

    def mark_reminded(self, ids: list[int]):
        self.conn.executemany("UPDATE leads SET reminded_at=? WHERE id=?", [(now_iso(), i) for i in ids])
        self.conn.commit()

    # ---------- tin đã xử lý (chống xử lý trùng khi vừa webhook vừa hỏi định kỳ) ----------
    def mark_seen(self, message_id: str) -> bool:
        """Đánh dấu đã xử lý. Trả về False nếu tin này đã xử lý trước đó."""
        cur = self.conn.execute("INSERT OR IGNORE INTO seen_messages(id, seen_at) VALUES (?,?)", (message_id, now_iso()))
        self.conn.commit()
        return cur.rowcount == 1

    def prune_seen(self, days: int = 3):
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        self.conn.execute("DELETE FROM seen_messages WHERE seen_at < ?", (cutoff,))
        self.conn.commit()

    # ---------- khách chờ shop trả lời ----------
    def get_conv_state(self, conv_id: str):
        return self.conn.execute("SELECT * FROM conv_state WHERE conv_id=?", (conv_id,)).fetchone()

    def customer_said(self, conv_id: str, customer: str, phone: str, thread: str, at: str, text: str,
                      needs_reply: bool):
        """Ghi tin khách. Trả về trạng thái TRƯỚC tin này (để biết shop đã trả lời chưa)."""
        prev = self.get_conv_state(conv_id)
        if prev is None:
            self.conn.execute("INSERT INTO conv_state(conv_id, customer, phone, thread_type) VALUES (?,?,?,?)",
                              (conv_id, customer, phone, thread))
        waiting = bool(prev and prev["waiting"])
        if waiting:  # khách nhắn thêm khi đang chờ: gộp nội dung, giữ giờ bắt đầu chờ
            lines = (prev["last_customer_text"] or "").splitlines()[-2:] + [text]
            self.conn.execute("UPDATE conv_state SET customer=?, phone=?, last_customer_at=?, last_customer_text=? "
                              "WHERE conv_id=?", (customer, phone, at, "\n".join(lines), conv_id))
        elif needs_reply:
            self.conn.execute("UPDATE conv_state SET customer=?, phone=?, thread_type=?, waiting=1, wait_since=?, "
                              "last_customer_at=?, last_customer_text=?, remind_level=0 WHERE conv_id=?",
                              (customer, phone, thread, at, at, text, conv_id))
        else:
            self.conn.execute("UPDATE conv_state SET last_customer_at=? WHERE conv_id=?", (at, conv_id))
        self.conn.commit()
        return prev

    def shop_said(self, conv_id: str, at: str):
        """Shop đã trả lời: hết chờ."""
        self.conn.execute("INSERT INTO conv_state(conv_id, last_shop_at) VALUES (?,?) ON CONFLICT(conv_id) DO "
                          "UPDATE SET waiting=0, remind_level=0, last_shop_at=excluded.last_shop_at", (conv_id, at))
        self.conn.commit()

    def waiting_convs(self, include_groups: bool = False):
        where = "" if include_groups else " AND thread_type='user'"
        return self.conn.execute(f"SELECT * FROM conv_state WHERE waiting=1{where} ORDER BY wait_since").fetchall()

    def set_remind_level(self, conv_ids: list[str], level: int):
        self.conn.executemany("UPDATE conv_state SET remind_level=? WHERE conv_id=?", [(level, c) for c in conv_ids])
        self.conn.commit()

    # ---------- cuộc trò chuyện đã biết ----------
    def mark_known(self, keys: list[str]) -> int:
        """Ghi nhận; trả về số cuộc trò chuyện MỚI được ghi."""
        before = self.conn.execute("SELECT COUNT(*) n FROM known_convs").fetchone()["n"]
        self.conn.executemany("INSERT OR IGNORE INTO known_convs(conv_key, first_seen) VALUES (?,?)",
                              [(k, now_iso()) for k in keys])
        self.conn.commit()
        return self.conn.execute("SELECT COUNT(*) n FROM known_convs").fetchone()["n"] - before

    # ---------- cài đặt ----------
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        self.conn.execute("INSERT INTO settings(key, value) VALUES (?,?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    # ---------- nhóm chat nhận báo cáo ----------
    def subscribe(self, chat_id: str, name: str = "", on: bool = True, dept: str | None = None):
        """Bật/tắt nhận tin cho 1 chat. dept: bộ phận của chat ('tong' = nhận tất cả)."""
        self.conn.execute(
            "INSERT INTO chats(chat_id, name, subscribed, dept) VALUES (?,?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET subscribed=excluded.subscribed, "
            "dept=COALESCE(?, chats.dept)",
            (str(chat_id), name, int(on), dept or "tong", dept),
        )
        self.conn.commit()

    def chat_dept(self, chat_id: str) -> str:
        row = self.conn.execute("SELECT dept FROM chats WHERE chat_id=?", (str(chat_id),)).fetchone()
        return row["dept"] if row else "tong"

    def is_subscribed(self, chat_id: str) -> bool:
        row = self.conn.execute("SELECT subscribed FROM chats WHERE chat_id=?", (str(chat_id),)).fetchone()
        return bool(row and row["subscribed"])

    def subscribed_chats(self, dept: str | None = None) -> list[str]:
        """Các chat đang nhận tin. Có dept: chat của bộ phận đó + chat tổng."""
        if dept:
            rows = self.conn.execute("SELECT chat_id FROM chats WHERE subscribed=1 AND dept IN (?, 'tong')", (dept,))
        else:
            rows = self.conn.execute("SELECT chat_id FROM chats WHERE subscribed=1")
        return [r["chat_id"] for r in rows]

    def subscribed_rows(self) -> list[tuple[str, str]]:
        """(chat_id, bộ phận) của mọi chat đang nhận tin."""
        return [(r["chat_id"], r["dept"]) for r in
                self.conn.execute("SELECT chat_id, dept FROM chats WHERE subscribed=1 ORDER BY rowid")]

    def chats_by_dept(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT dept, COUNT(*) n FROM chats WHERE subscribed=1 GROUP BY dept")
        return {r["dept"]: r["n"] for r in rows}


def fmt_qty(q: float) -> str:
    return str(int(q)) if float(q).is_integer() else f"{q:g}"
