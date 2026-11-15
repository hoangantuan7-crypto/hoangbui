// Google Sheet ĐƠN HÀNG: Bot Điều phối ghi đơn đã duyệt (nhóm Zalo "CHỐT ĐƠN" -> nháp Telegram -> "ok").
// Cài: mở Sheet đơn hàng -> Tiện ích mở rộng -> Apps Script -> dán toàn bộ file này -> đổi TOKEN -> Lưu
//      -> Triển khai -> Tùy chọn triển khai mới -> Ứng dụng web (Thực thi: Tôi · Truy cập: Bất kỳ ai) -> Triển khai.
// Trang: ĐƠN HÀNG (1 dòng/đơn) · CHI TIẾT ĐƠN (1 dòng/món) · THU TIỀN (1 dòng/lần thu) · KHO (danh mục + tồn)
const TOKEN = 'DOI-THANH-MA-BI-MAT';  // mật khẩu do anh tự đặt, không dấu, không khoảng trắng, giữ kín

const HEADERS = {
  'ĐƠN HÀNG': ['Mã đơn', 'Ngày lên đơn', 'Khách hàng', 'SĐT', 'Địa chỉ', 'Ngày giao dự kiến', 'Tổng trước giảm',
               'Giảm giá', 'Tổng chốt', 'Cọc / đã thu trước', 'Ngày cọc', 'Thu lần này', 'Đã thu', 'Còn phải thu',
               'Trạng thái', 'Hàng riêng chờ khảo sát/báo giá', 'Ghi chú', 'Người gửi', 'Link ảnh', 'Mã tin Zalo',
               'Lúc duyệt'],
  'CHI TIẾT ĐƠN': ['Mã đơn', 'STT', 'Mã SP', 'Tên sản phẩm', 'ĐVT', 'SL', 'Đơn giá', 'Thành tiền', 'Loại',
                   'Ghi chú', 'Khớp kho', 'Khách hàng'],
  'THU TIỀN': ['Ngày', 'Mã đơn', 'Khách hàng', 'SĐT', 'Số tiền', 'Nội dung', 'Ghi chú', 'Lúc ghi'],
  'KHO': ['Mã SP', 'Tên sản phẩm', 'ĐVT', 'Giá bán', 'Bảo hành', 'Phân loại hàng', 'Hàng riêng của khách',
          'Tồn', 'Tồn tối thiểu', 'Ghi chú'],
};

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  if (body.token !== TOKEN) return json({ ok: false, error: 'Sai mã bí mật' });
  if (body.action === 'products') return json({ ok: true, products: products() });
  if (body.action === 'order') {
    const lock = LockService.getScriptLock();
    lock.waitLock(20000);
    try { return json(saveOrder(body.order || {})); } finally { lock.releaseLock(); }
  }
  return json({ ok: false, error: 'Không rõ việc cần làm' });
}

function sheet(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    sh.appendRow(HEADERS[name]);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, HEADERS[name].length).setFontWeight('bold');
  }
  return sh;
}

function products() {
  const values = sheet('KHO').getDataRange().getValues().slice(1);
  return values.filter(r => String(r[0]).trim()).map(r => ({
    code: String(r[0]).trim(), name: String(r[1]), unit: String(r[2]), price: num(r[3]),
    kind: /riêng/i.test(String(r[5])) ? 'rieng' : 'thuong', stock: num(r[7]),
  }));
}

function saveOrder(o) {
  const orders = sheet('ĐƠN HÀNG');
  const last = orders.getLastRow();
  const nums = last < 2 ? [] : orders.getRange(2, 1, last - 1, 1).getValues().map(r => Number(String(r[0]).replace(/\D/g, '')) || 0);
  const code = 'D' + ((nums.length ? Math.max(...nums) : 0) + 1);
  const now = Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'dd/MM/yyyy HH:mm');
  const phone = String(o.phone || '').replace(/\D/g, '');
  orders.appendRow([code, o.orderDate, txt(o.customer), phone ? "'" + phone : '', txt(o.address), txt(o.deliveryDate),
                    o.subtotal, o.discount, o.total, o.paidBefore, txt(o.paidBeforeDate), o.payNow, o.paid, o.left,
                    o.status, txt(o.pending), txt(o.note), txt(o.sender), txt(o.image), txt(o.msgId), now]);
  const items = (o.items || []).map((it, i) => [code, i + 1, txt(it.code), txt(it.name), txt(it.unit), it.qty, it.price,
                                                it.amount, it.kind, txt(it.note), it.match, txt(o.customer)]);
  if (items.length) {
    const sh = sheet('CHI TIẾT ĐƠN');
    sh.getRange(sh.getLastRow() + 1, 1, items.length, items[0].length).setValues(items);
  }
  const pay = sheet('THU TIỀN');
  if (o.paidBefore) pay.appendRow([txt(o.paidBeforeDate || o.orderDate), code, txt(o.customer), phone ? "'" + phone : '',
                                   o.paidBefore, 'Cọc / đã thu trước', '', now]);
  if (o.payNow) pay.appendRow([Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'dd/MM/yyyy'), code,
                               txt(o.customer), phone ? "'" + phone : '', o.payNow, 'Thanh toán', '', now]);
  return { ok: true, code: code, row: orders.getLastRow() };
}

// Ô bắt đầu bằng = + - @ bị hiểu là công thức -> thêm dấu ' để giữ là chữ
function txt(v) { v = v == null ? '' : String(v); return /^[=+\-@]/.test(v) ? "'" + v : v; }
function num(v) { return typeof v === 'number' ? v : Number(String(v).replace(/[^\d]/g, '')) || 0; }
function doGet() { return json({ ok: true, message: 'Sheet đơn hàng sẵn sàng' }); }
function json(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
