// Google Sheet ĐƠN HÀNG: Bot Điều phối ghi đơn đã duyệt (nhóm Zalo "CHỐT ĐƠN" -> nháp Telegram -> "ok").
// Cài: mở Sheet đơn hàng -> Tiện ích mở rộng -> Apps Script -> dán toàn bộ file này -> đổi TOKEN -> Lưu
//      -> Triển khai -> Tùy chọn triển khai mới -> Ứng dụng web (Thực thi: Tôi · Truy cập: Bất kỳ ai) -> Triển khai.
// Trang: KHÁCH HÀNG (1 dòng/khách) · ĐƠN HÀNG (1 dòng/đơn) · CHI TIẾT ĐƠN (1 dòng/món) · THU TIỀN (1 dòng/lần thu)
//        · KHO (danh mục + tồn). Trang nào chưa có thì tự tạo; muốn tạo ngay: chọn hàm caiDat -> Chạy.
// Link /exec này dùng được cho CẢ nhóm Zalo THÔNG TIN KHÁCH HÀNG (dán vào câu hỏi Sheet thông tin khách).
const TOKEN = 'DOI-THANH-MA-BI-MAT';  // mật khẩu do anh tự đặt, không dấu, không khoảng trắng, giữ kín

const HEADERS = {
  'KHÁCH HÀNG': ['STT', 'Ngày thêm', 'Tên khách hàng', 'SĐT', 'Địa chỉ', 'Ghi chú', 'Người gửi', 'Nguồn', 'Trạng thái',
                 'Link ảnh gốc', 'Mã tin Zalo', 'Mã đơn', 'Tổng tiền đơn', 'Đã cọc / đã thu', 'Ngày cọc',
                 'Còn phải thu', 'Trạng thái đơn'],
  'ĐƠN HÀNG': ['Mã đơn', 'Ngày lên đơn', 'Khách hàng', 'SĐT', 'Địa chỉ', 'Ngày giao dự kiến', 'Tổng trước giảm',
               'Giảm giá', 'Tổng chốt', 'Cọc / đã thu trước', 'Ngày cọc', 'Thu lần này', 'Đã thu', 'Còn phải thu',
               'Trạng thái', 'Hàng riêng chờ khảo sát/báo giá', 'Ghi chú', 'Người gửi', 'Link ảnh', 'Mã tin Zalo',
               'Lúc duyệt'],
  'CHI TIẾT ĐƠN': ['Mã đơn', 'STT', 'Mã SP', 'Tên sản phẩm', 'ĐVT', 'SL', 'Đơn giá', 'Thành tiền', 'Loại',
                   'Ghi chú', 'Khớp kho', 'Khách hàng'],
  'THU TIỀN': ['Ngày', 'Mã đơn', 'Khách hàng', 'SĐT', 'Số tiền', 'Nội dung', 'Ghi chú', 'Lúc ghi'],
  'KHO': ['Mã SP', 'Tên sản phẩm', 'ĐVT', 'Giá bán', 'Bảo hành', 'Phân loại hàng', 'Hàng riêng của khách',
          'Tồn', 'Tồn tối thiểu', 'Ghi chú', 'Khách đặt chưa giao', 'Cần nhập thêm'],
};

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  if (body.token !== TOKEN) return json({ ok: false, error: 'Sai mã bí mật' });
  if (body.action === 'products') return json({ ok: true, products: products() });
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    if (body.action === 'order') return json(saveOrder(body.order || {}));
    return json(saveCustomer(body));  // tin từ nhóm THÔNG TIN KHÁCH HÀNG
  } finally {
    lock.releaseLock();
  }
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
  const have = sh.getLastColumn();
  if (have < HEADERS[name].length) {  // trang cũ thiếu cột mới -> thêm tiêu đề cột
    sh.getRange(1, have + 1, 1, HEADERS[name].length - have).setValues([HEADERS[name].slice(have)]).setFontWeight('bold');
  }
  return sh;
}

function caiDat() { Object.keys(HEADERS).forEach(sheet); }  // chạy 1 lần: tạo đủ các trang

function cleanPhone(v) {
  let p = String(v || '').replace(/\D/g, '');
  if (p.startsWith('84') && p.length === 11) p = '0' + p.slice(2);
  return p;
}

function findCustomer(sh, phone) {
  const last = sh.getLastRow();
  if (!phone || last < 2) return -1;
  const phones = sh.getRange(2, 4, last - 1, 1).getDisplayValues().map(r => String(r[0]).replace(/\D/g, ''));
  const i = phones.indexOf(phone);
  return i < 0 ? -1 : i + 2;
}

function nextStt(sh) {
  const last = sh.getLastRow();
  return last < 2 ? 1 : Math.max(...sh.getRange(2, 1, last - 1, 1).getValues().map(r => Number(r[0]) || 0)) + 1;
}

function saveCustomer(b) {
  const sh = sheet('KHÁCH HÀNG');
  const phone = cleanPhone(b.phone);
  const row = findCustomer(sh, phone);
  if (row > 0) return { ok: true, duplicate: true, row: row, stt: sh.getRange(row, 1).getValue() };
  const stt = nextStt(sh);
  const now = Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'dd/MM/yyyy HH:mm');
  sh.appendRow([stt, b.date || now, txt(b.name), phone ? "'" + phone : '', txt(b.address), txt(b.note), txt(b.sender),
                txt(b.source), txt(b.status), txt(b.image), txt(b.msgId)]);
  return { ok: true, row: sh.getLastRow(), stt: stt };
}

// Đơn đã duyệt -> cập nhật khách (chưa có thì thêm): mã đơn, tổng tiền, đã cọc/đã thu, còn phải thu (cộng dồn)
function updateCustomerFromOrder(o, code, now) {
  const sh = sheet('KHÁCH HÀNG');
  const phone = cleanPhone(o.phone);
  let row = findCustomer(sh, phone);
  const isNew = row < 0;
  if (isNew) {
    sh.appendRow([nextStt(sh), now, txt(o.customer), phone ? "'" + phone : '', txt(o.address), '', txt(o.sender),
                  'Đơn hàng', 'Đủ thông tin', txt(o.image), txt(o.msgId)]);
    row = sh.getLastRow();
  }
  const cur = sh.getRange(row, 12, 1, 6).getValues()[0];
  const codes = String(cur[0] || '').split(',').map(c => c.trim()).filter(String);
  codes.push(code);
  const paid = num(cur[2]) + (o.paid || 0);
  sh.getRange(row, 12, 1, 6).setValues([[codes.join(', '), num(cur[1]) + (o.total || 0), paid,
                                          o.paidBeforeDate || cur[3] || '', num(cur[4]) + (o.left || 0),
                                          paid ? 'Đã chốt' : o.status]]);
  return { row: row, isNew: isNew, stt: sh.getRange(row, 1).getValue() };
}

function codeKey(c) { return String(c || '').toUpperCase().replace(/[^A-Z0-9]/g, ''); }

// Đơn đã duyệt -> KHO: cộng "Khách đặt chưa giao", tính "Cần nhập thêm" = đặt - tồn; mã chưa có thì thêm dòng mới
function updateStock(o, code) {
  const sh = sheet('KHO');
  const last = sh.getLastRow();
  const keys = last < 2 ? [] : sh.getRange(2, 1, last - 1, 1).getValues().map(r => codeKey(r[0]));
  const out = [];
  (o.items || []).forEach(it => {
    if (!it.code || it.kind === 'Hàng riêng') return;  // hàng riêng đặt làm theo khách: không theo dõi tồn
    let i = keys.indexOf(codeKey(it.code));
    const isNew = i < 0;
    if (isNew) {
      sh.appendRow([txt(it.code), txt(it.name), txt(it.unit), it.price, '', 'Hàng thông thường', '', 0, 0,
                    'Mã mới từ đơn ' + code + ' – cần kiểm tra', 0, 0]);
      keys.push(codeKey(it.code));
      i = keys.length - 1;
    }
    const r = i + 2;
    const v = sh.getRange(r, 8, 1, 5).getValues()[0];  // Tồn, Tồn tối thiểu, Ghi chú, Đặt chưa giao, Cần nhập
    const ordered = num(v[3]) + Number(it.qty || 0);
    const need = Math.max(0, ordered + num(v[1]) - num(v[0]));
    sh.getRange(r, 11, 1, 2).setValues([[ordered, need]]);
    out.push({ code: String(it.code), stock: num(v[0]), ordered: ordered, need: need, isNew: isNew });
  });
  return out;
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
  const row = orders.getLastRow();
  const customer = updateCustomerFromOrder(o, code, now);
  const stock = updateStock(o, code);
  return { ok: true, code: code, row: row, items: items.length, customer: customer, stock: stock,
           payments: (o.paidBefore ? 1 : 0) + (o.payNow ? 1 : 0) };
}

// Ô bắt đầu bằng = + - @ bị hiểu là công thức -> thêm dấu ' để giữ là chữ
function txt(v) { v = v == null ? '' : String(v); return /^[=+\-@]/.test(v) ? "'" + v : v; }
function num(v) { return typeof v === 'number' ? v : Number(String(v).replace(/[^\d]/g, '')) || 0; }
function doGet() { return json({ ok: true, message: 'Sheet đơn hàng + khách hàng sẵn sàng' }); }
function json(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
