"""5 bot Telegram riêng: Điều phối + 4 bot bộ phận, mỗi bot có lệnh riêng.

Tất cả dùng chung 1 kho dữ liệu (khách, đơn, việc) – tách giao diện, không tách dữ liệu.
Bot bộ phận nào chưa có token thì Bot Điều phối báo thay, không sót việc.
"""
from .departments import DEPTS

DIEUPHOI = "dieuphoi"
BOT_NAMES = {DIEUPHOI: ("🧭", "Bot Điều phối"), **{d: (icon, f"Bot {name}") for d, (icon, name, _) in DEPTS.items()}}

# Lệnh có mặt ở mọi bot
COMMON = {"help", "choxuly", "xong", "chuyen", "bophan", "dangky", "huydangky"}

# Lệnh riêng của từng bot bộ phận (Bot Điều phối dùng được tất cả)
ALLOWED = {
    "sale": COMMON | {"don", "donmo", "xem", "huy", "nhac", "giao"},
    "ketoan": COMMON | {"donmo", "xem"},
    "kho": COMMON | {"thieu", "ton", "nhap", "toithieu", "giao", "lavabo", "datxuong", "donmo", "xem"},
    "kythuat": COMMON | {"lavabo", "xem"},
}
# Bot nào được ghi đơn bằng tin nhắn "Đơn ..." (không phải lệnh /)
FREE_TEXT_ORDERS = {DIEUPHOI, "sale"}

DESCRIPTIONS = {
    "choxuly": "/choxuly – việc khách đang chờ bộ phận này xử lý",
    "xong": "/xong K5 – báo đã xử lý xong việc K5",
    "chuyen": "/chuyen K5 kho – giao nhầm thì chuyển sang bộ phận khác (sale, ketoan, kho, kythuat)",
    "don": "Đơn anh Nam 0912…: 2 tủ lavabo 80cm; 5 vòi sen – ghi đơn mới",
    "donmo": "/donmo – các đơn đang mở",
    "xem": "/xem 12 – xem chi tiết đơn #12",
    "huy": "/huy 12 – hủy đơn #12",
    "nhac": "/nhac – khách quen đến kỳ đặt lại + hàng cần nhập",
    "giao": "/giao 12 · /giao 12 vòi sen 2 – ghi nhận đã giao hàng",
    "thieu": "/thieu – khách nào đang thiếu hàng",
    "ton": "/ton – xem tồn kho · /ton vòi sen 15 – đặt lại số tồn",
    "nhap": "/nhap vòi sen 20 – nhập kho",
    "toithieu": "/toithieu vòi sen 5 – mức tồn tối thiểu để bot nhắc nhập",
    "lavabo": "/lavabo – tủ lavabo cần lên đơn xưởng / đang chờ xưởng",
    "datxuong": "/datxuong 12 – đã đặt xưởng tủ lavabo cho đơn #12",
    "bophan": "/bophan – bot này thuộc bộ phận nào",
}
HELP_ORDER = ["choxuly", "xong", "chuyen", "don", "donmo", "xem", "huy", "giao", "nhac", "thieu", "ton", "nhap",
              "toithieu", "lavabo", "datxuong", "bophan"]


def dept_help(dept: str) -> str:
    icon, title = BOT_NAMES[dept]
    allowed = ALLOWED[dept]
    lines = [f"{icon} {title.upper()} – lệnh của bot này", ""]
    lines += [DESCRIPTIONS[c] for c in HELP_ORDER if c in allowed or (c == "don" and dept in FREE_TEXT_ORDERS)]
    lines += ["", "Bot tự báo vào đây khi có việc mới của bộ phận, và nhắc lại nếu quá 30 phút chưa xử lý."]
    return "\n".join(lines)


def not_allowed(dept: str, command: str) -> str:
    owners = [BOT_NAMES[d][1] for d, cmds in ALLOWED.items() if command in cmds]
    where = ", ".join(owners + [BOT_NAMES[DIEUPHOI][1]])
    return f"⛔ /{command} không thuộc {BOT_NAMES[dept][1]}. Dùng ở: {where}. Gõ /help để xem lệnh của bot này."
