"""Bot điều phối: phân loại tin khách theo bộ phận.

Mỗi bộ phận có 1 nhóm Telegram riêng (ghép nối bằng "/batdau <mã> <bộ phận>").
Chat ghép nối không kèm bộ phận = TỔNG: nhận mọi tin và báo cáo tổng hợp.
Thêm bộ phận mới: thêm 1 dòng vào DEPTS và từ khóa vào KEYWORDS.
"""
from .detect import is_order_message
from .text import norm

TONG = "tong"

# mã -> (biểu tượng, tên hiển thị, tiêu đề tin báo)
DEPTS = {
    "sale": ("🛒", "Sale", "KHÁCH ĐẶT HÀNG / HỎI HÀNG"),
    "ketoan": ("💰", "Kế toán", "KHÁCH BÁO CHUYỂN KHOẢN / THANH TOÁN"),
    "kho": ("📦", "Kho", "GIAO HÀNG / ĐỔI TRẢ"),
    "kythuat": ("🔧", "Kỹ thuật", "LẮP ĐẶT / BẢO HÀNH / SỬA CHỮA"),
}

# Từ khóa viết không dấu. Thứ tự ưu tiên: kỹ thuật > kế toán > kho > sale
# (vd "tủ lavabo mới lắp đã bị rỉ nước" là việc kỹ thuật dù có nhắc tên sản phẩm).
KEYWORDS = {
    "kythuat": ["bao hanh", "lap dat", "lap giup", "lap cho", "lap tu", "lap guong", "tho lap", "qua lap",
                "sua giup", "sua chua", "sua lai", "bi hong", "bi hu", "hong roi", "hu roi", "ro ri", "ri nuoc",
                "chay nuoc", "bi tac", "tac nghen", "nghet", "bi nut", "bi bong", "bong troc", "ban le",
                "khong len nuoc", "yeu nuoc", "bi ket", "bi lech", "ky thuat", "kiem tra giup", "bi mop"],
    "ketoan": ["chuyen khoan", "da ck", "ck roi", "ck xong", "dat coc", "coc truoc", "da coc", "thanh toan",
               "bill", "hoa don", "xuat vat", "hoa don vat", "cong no", "so tai khoan", "stk", "tra no",
               "con no", "quyet toan", "uy nhiem chi"],
    "kho": ["giao hang", "bao gio giao", "khi nao giao", "may gio giao", "chua nhan duoc hang", "chua thay hang",
            "nhan duoc hang", "van chuyen", "nha xe", "gui xe", "doi hang", "tra hang", "doi tra", "giao thieu",
            "giao nham", "giao sai", "thieu hang", "hang bi vo", "hang vo", "kiem hang"],
}
ORDER = ["kythuat", "ketoan", "kho"]
ALIASES = {"sale": "sale", "sales": "sale", "banhang": "sale", "kinhdoanh": "sale",
           "ketoan": "ketoan", "kt": "ketoan", "taichinh": "ketoan",
           "kho": "kho", "khovan": "kho", "giaohang": "kho",
           "kythuat": "kythuat", "kithuat": "kythuat", "tho": "kythuat", "baohanh": "kythuat",
           "tong": TONG, "all": TONG, "chu": TONG, "admin": TONG}

LEGACY = {"order": "sale", "payment": "ketoan"}  # loại tin cũ trước khi có bộ phận


def route(text: str) -> str | None:
    """Bộ phận xử lý tin khách, hoặc None nếu chỉ là tin trò chuyện bình thường."""
    key = f" {norm(text)} "
    for dept in ORDER:
        if any(f" {k}" in key for k in KEYWORDS[dept]):
            return dept
    return "sale" if is_order_message(text) else None


def parse_dept(word: str) -> str | None:
    return ALIASES.get(norm(word).replace(" ", "")) if word else None


def dept_icon(dept: str) -> str:
    return DEPTS.get(LEGACY.get(dept, dept), ("•",))[0]


def dept_name(dept: str) -> str:
    dept = LEGACY.get(dept, dept)
    return "Tổng" if dept == TONG else DEPTS.get(dept, ("", dept))[1]


def dept_list() -> str:
    return ", ".join(f"{code} ({name})" for code, (_, name, _) in DEPTS.items())
