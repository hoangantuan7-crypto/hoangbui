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
                   'Ghi chú', 'Khớp kho', 'Khách hàng', 'Đã giao', 'Ngày giao'],
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
    if (body.action === 'deliver') return json(deliver(body));
    if (body.action === 'pay') return json(pay(body));
    if (body.action === 'restock') return json(restock(body));
    if (body.action === 'order_info') return json(orderInfo(body.code));
    if (body.action === 'interested') return json({ ok: true, orders: interested() });
    if (body.action === 'close') return json(closeOrder(body));
    if (body.action === 'set_status') return json(setStatus(body));
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

// Đơn -> cập nhật khách (chưa có thì thêm). Đơn đã chốt: cộng dồn tổng tiền, đã thu, còn phải thu.
// Đơn đang quan tâm: chỉ ghi "Đang quan tâm: <các mã>" vào Ghi chú, không cộng tiền.
function updateCustomerFromOrder(o, code, now, interest) {
  const sh = sheet('KHÁCH HÀNG');
  const phone = cleanPhone(o.phone);
  let row = findCustomer(sh, phone);
  const isNew = row < 0;
  const wants = 'Đang quan tâm: ' + (o.items || []).map(it => it.code || it.name).filter(String).join(', ');
  if (isNew) {
    sh.appendRow([nextStt(sh), now, txt(o.customer), phone ? "'" + phone : '', txt(o.address), interest ? txt(wants) : '',
                  txt(o.sender), 'Đơn hàng', 'Đủ thông tin', txt(o.image), txt(o.msgId)]);
    row = sh.getLastRow();
  }
  const cur = sh.getRange(row, 12, 1, 6).getValues()[0];
  const codes = String(cur[0] || '').split(',').map(c => c.trim()).filter(String);
  if (codes.indexOf(code) < 0) codes.push(code);
  const note = String(sh.getRange(row, 6).getValue());
  if (interest) {
    sh.getRange(row, 6).setValue(txt(wants));
    sh.getRange(row, 12).setValue(codes.join(', '));
    if (!num(cur[2])) sh.getRange(row, 17).setValue('Đang quan tâm');
  } else {
    if (/^Đang quan tâm/.test(note)) sh.getRange(row, 6).setValue('Đã chốt ' + code + ' (' + note + ')');
    const paid = num(cur[2]) + (o.paid || 0);
    sh.getRange(row, 12, 1, 6).setValues([[codes.join(', '), num(cur[1]) + (o.total || 0), paid,
                                            o.paidBeforeDate || cur[3] || '', num(cur[4]) + (o.left || 0),
                                            paid ? 'Đã chốt' : o.status]]);
  }
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

const INTEREST = 'Khách chưa chốt – đang quan tâm';

// Đơn đang quan tâm gần nhất của khách (theo SĐT) -> khi khách chốt thì cập nhật đơn đó, không tạo đơn trùng
function findInterestOrder(phone) {
  const sh = sheet('ĐƠN HÀNG');
  const last = sh.getLastRow();
  if (!phone || last < 2) return -1;
  const v = sh.getRange(2, 1, last - 1, 15).getDisplayValues();
  for (let i = v.length - 1; i >= 0; i--) {
    if (cleanPhone(v[i][3]) === phone && /quan tâm/i.test(v[i][14])) return i + 2;
  }
  return -1;
}

function saveOrder(o) {
  const orders = sheet('ĐƠN HÀNG');
  const now = Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'dd/MM/yyyy HH:mm');
  const phone = cleanPhone(o.phone);
  const interest = !!o.interest;
  let row = findInterestOrder(phone);
  const reuse = row > 0;
  const values = [o.orderDate, txt(o.customer), phone ? "'" + phone : '', txt(o.address), txt(o.deliveryDate),
                  o.subtotal, o.discount, o.total, interest ? 0 : o.paidBefore, interest ? '' : txt(o.paidBeforeDate),
                  interest ? 0 : o.payNow, interest ? 0 : o.paid, o.left, interest ? INTEREST : o.status,
                  txt(o.pending), txt(o.note), txt(o.sender), txt(o.image), txt(o.msgId), now];
  let code;
  if (reuse) {  // cập nhật đơn đang quan tâm của khách (khách chốt, hoặc gửi lại nhu cầu mới)
    code = String(orders.getRange(row, 1).getValue());
    orders.getRange(row, 2, 1, values.length).setValues([values]);
    const old = orderLines(code);
    for (let k = old.length - 1; k >= 0; k--) sheet('CHI TIẾT ĐƠN').deleteRow(old[k].row);
  } else {
    const last = orders.getLastRow();
    const nums = last < 2 ? [] : orders.getRange(2, 1, last - 1, 1).getValues().map(r => Number(String(r[0]).replace(/\D/g, '')) || 0);
    code = 'D' + ((nums.length ? Math.max(...nums) : 0) + 1);
    orders.appendRow([code].concat(values));
    row = orders.getLastRow();
  }
  const items = (o.items || []).map((it, i) => [code, i + 1, txt(it.code), txt(it.name), txt(it.unit), it.qty, it.price,
                                                it.amount, it.kind, txt(it.note), it.match, txt(o.customer), 0, '']);
  if (items.length) {
    const sh = sheet('CHI TIẾT ĐƠN');
    sh.getRange(sh.getLastRow() + 1, 1, items.length, items[0].length).setValues(items);
  }
  let payments = 0;
  if (!interest) {
    const pay = sheet('THU TIỀN');
    if (o.paidBefore) pay.appendRow([txt(o.paidBeforeDate || o.orderDate), code, txt(o.customer), phone ? "'" + phone : '',
                                     o.paidBefore, 'Cọc / đã thu trước', '', now]);
    if (o.payNow) pay.appendRow([Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'dd/MM/yyyy'), code,
                                 txt(o.customer), phone ? "'" + phone : '', o.payNow, 'Thanh toán', '', now]);
    payments = (o.paidBefore ? 1 : 0) + (o.payNow ? 1 : 0);
  }
  const customer = updateCustomerFromOrder(o, code, now, interest);
  const stock = interest ? [] : updateStock(o, code);  // đang quan tâm: chưa giữ hàng trong kho
  return { ok: true, code: code, row: row, items: items.length, customer: customer, stock: stock, payments: payments,
           interest: interest, converted: reuse && !interest, updated: reuse && interest };
}

// Danh sách khách đang quan tâm (để nhắc gọi lại)
function interested() {
  const sh = sheet('ĐƠN HÀNG');
  const last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, 21).getDisplayValues()
    .filter(r => /quan tâm/i.test(r[14]))
    .map(r => ({ code: r[0], customer: r[2], phone: cleanPhone(r[3]), total: num(r[8]), since: r[20] || r[1],
                 codes: orderLines(r[0]).map(l => l.code || l.name) }));
}

// Khách đang quan tâm chốt + cọc: ghi tiền cọc, giữ hàng trong kho, cộng tiền cho khách
function closeOrder(b) {
  const row = findOrder(b.code);
  if (row < 0) return { ok: false, error: 'Không có đơn ' + b.code };
  const orders = sheet('ĐƠN HÀNG');
  const v = orders.getRange(row, 1, 1, 15).getValues()[0];
  if (!/quan tâm/i.test(String(v[14]))) return { ok: false, error: 'Đơn ' + v[0] + ' đã chốt rồi (' + v[14] + ')' };
  const amount = Number(b.amount) || 0;
  const now = Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'dd/MM/yyyy HH:mm');
  const date = b.date || now.slice(0, 10);
  const total = num(v[8]), left = total - amount;
  orders.getRange(row, 10, 1, 6).setValues([[amount, date, 0, amount, left, amount ? 'Đã chốt' : 'Chưa cọc']]);
  const lines = orderLines(v[0]);
  const o = { customer: v[2], phone: cleanPhone(v[3]), total: total, paid: amount, left: left, paidBeforeDate: date,
              status: amount ? 'Đã chốt' : 'Chưa cọc',
              items: lines.map(l => ({ code: l.code, name: l.name, qty: l.qty, kind: l.kind, price: 0 })) };
  if (amount) sheet('THU TIỀN').appendRow([date, String(v[0]), txt(v[2]), o.phone ? "'" + o.phone : '', amount,
                                           'Cọc / đã thu trước', 'Chốt đơn đang quan tâm', now]);
  updateCustomerFromOrder(o, String(v[0]), now, false);
  const stock = updateStock(o, String(v[0]));
  orders.getRange(row, 15).setValue(orderStatus(row));
  return { ok: true, code: String(v[0]), customer: String(v[2]), phone: o.phone, total: total, paid: amount, left: left,
           stock: stock };
}

function setStatus(b) {
  const row = findOrder(b.code);
  if (row < 0) return { ok: false, error: 'Không có đơn ' + b.code };
  const orders = sheet('ĐƠN HÀNG');
  orders.getRange(row, 15).setValue(txt(b.status));
  const cs = sheet('KHÁCH HÀNG');
  const crow = findCustomer(cs, cleanPhone(orders.getRange(row, 4).getValue()));
  if (crow > 0) cs.getRange(crow, 17).setValue(txt(b.status));
  return { ok: true, code: String(orders.getRange(row, 1).getValue()), customer: String(orders.getRange(row, 3).getValue()) };
}

// ---------- Sau khi chốt: giao hàng (trừ kho), thu tiền thêm, nhập kho, xem đơn ----------
function findOrder(code) {
  const sh = sheet('ĐƠN HÀNG');
  const last = sh.getLastRow();
  if (last < 2) return -1;
  const codes = sh.getRange(2, 1, last - 1, 1).getValues().map(r => String(r[0]).trim().toUpperCase());
  const i = codes.lastIndexOf(String(code || '').trim().toUpperCase());
  return i < 0 ? -1 : i + 2;
}

function orderLines(code) {  // [{row, code, name, unit, qty, delivered}]
  const sh = sheet('CHI TIẾT ĐƠN');
  const last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, 14).getValues()
    .map((r, i) => ({ row: i + 2, order: String(r[0]).toUpperCase(), code: String(r[2]), name: String(r[3]),
                      unit: String(r[4]), qty: num(r[5]), kind: String(r[8]), delivered: num(r[12]) }))
    .filter(l => l.order === String(code).toUpperCase());
}

function stockRow(code) {
  const sh = sheet('KHO');
  const last = sh.getLastRow();
  if (last < 2) return -1;
  const i = sh.getRange(2, 1, last - 1, 1).getValues().map(r => codeKey(r[0])).indexOf(codeKey(code));
  return i < 0 ? -1 : i + 2;
}

function setStock(r, dStock, dOrdered) {  // đổi Tồn / Khách đặt chưa giao, tính lại Cần nhập thêm
  const sh = sheet('KHO');
  const v = sh.getRange(r, 8, 1, 5).getValues()[0];
  const stock = num(v[0]) + dStock, ordered = Math.max(0, num(v[3]) + dOrdered);
  const need = Math.max(0, ordered + num(v[1]) - stock);
  sh.getRange(r, 8).setValue(stock);
  sh.getRange(r, 11, 1, 2).setValues([[ordered, need]]);
  return { code: String(sh.getRange(r, 1).getValue()), stock: stock, ordered: ordered, need: need };
}

// Giao hàng: items rỗng = giao hết phần còn lại; items = [{code, qty}] giao một phần
function deliver(b) {
  const row = findOrder(b.code);
  if (row < 0) return { ok: false, error: 'Không có đơn ' + b.code };
  const lines = orderLines(b.code);
  const today = Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'dd/MM/yyyy');
  const want = (b.items || []).map(it => ({ key: codeKey(it.code), qty: Number(it.qty) || 0 }));
  const done = [], missing = [];
  want.forEach(w => { if (!lines.some(l => codeKey(l.code) === w.key)) missing.push(w.key); });
  lines.forEach(l => {
    const left = l.qty - l.delivered;
    if (left <= 0) return;
    let q = left;
    if (want.length) {
      const w = want.find(x => x.key === codeKey(l.code));
      if (!w) return;
      q = Math.min(left, w.qty || left);
    }
    sheet('CHI TIẾT ĐƠN').getRange(l.row, 13, 1, 2).setValues([[l.delivered + q, today]]);
    const r = l.kind === 'Hàng riêng' ? -1 : stockRow(l.code);
    const st = r > 0 ? setStock(r, -q, -q) : null;
    done.push({ code: l.code, name: l.name, qty: q, left: left - q, stock: st ? st.stock : null });
  });
  const all = orderLines(b.code);
  const full = all.every(l => l.delivered >= l.qty);
  const orders = sheet('ĐƠN HÀNG');
  orders.getRange(row, 15).setValue(orderStatus(row));
  return { ok: true, code: String(orders.getRange(row, 1).getValue()), delivered: done, missing: missing, full: full,
           customer: String(orders.getRange(row, 3).getValue()),
           remaining: all.filter(l => l.delivered < l.qty).map(l => ({ code: l.code, qty: l.qty - l.delivered })) };
}

// Khách trả thêm tiền cho đơn cũ: THU TIỀN + cập nhật Đã thu / Còn phải thu ở ĐƠN HÀNG và KHÁCH HÀNG
function pay(b) {
  const row = findOrder(b.code);
  if (row < 0) return { ok: false, error: 'Không có đơn ' + b.code };
  const amount = Number(b.amount) || 0;
  if (!amount) return { ok: false, error: 'Thiếu số tiền' };
  const orders = sheet('ĐƠN HÀNG');
  const v = orders.getRange(row, 1, 1, 15).getValues()[0];
  const paid = num(v[12]) + amount, left = num(v[8]) - paid;
  orders.getRange(row, 13, 1, 2).setValues([[paid, left]]);
  orders.getRange(row, 15).setValue(orderStatus(row));
  const now = Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'dd/MM/yyyy HH:mm');
  sheet('THU TIỀN').appendRow([b.date || now.slice(0, 10), b.code, txt(v[2]), v[3] ? "'" + cleanPhone(v[3]) : '', amount,
                               'Thanh toán thêm', txt(b.note), now]);
  const cs = sheet('KHÁCH HÀNG');
  const crow = findCustomer(cs, cleanPhone(v[3]));
  if (crow > 0) {
    const c = cs.getRange(crow, 14, 1, 3).getValues()[0];
    cs.getRange(crow, 14).setValue(num(c[0]) + amount);
    cs.getRange(crow, 16, 1, 2).setValues([[num(c[2]) - amount, num(c[2]) - amount <= 0 ? 'Đã thanh toán đủ' : 'Đã chốt']]);
  }
  return { ok: true, code: String(v[0]), customer: String(v[2]), total: num(v[8]), paid: paid, left: left };
}

// Trạng thái đơn = giao hàng · tiền, vd "Giao một phần · Đã cọc, còn nợ 9.000.000"
function orderStatus(row) {
  const v = sheet('ĐƠN HÀNG').getRange(row, 1, 1, 14).getValues()[0];
  const lines = orderLines(v[0]);
  const got = lines.reduce((a, l) => a + l.delivered, 0);
  const ship = !got ? 'Chưa giao' : lines.every(l => l.delivered >= l.qty) ? 'Đã giao đủ' : 'Giao một phần';
  const paid = num(v[12]), left = num(v[13]);
  const money = left <= 0 && paid > 0 ? 'Đã thanh toán đủ'
    : paid > 0 ? 'Đã cọc, còn nợ ' + left.toLocaleString('vi-VN') : 'Chưa cọc';
  return ship + ' · ' + money;
}

function restock(b) {
  let r = stockRow(b.code);
  if (r < 0) {
    sheet('KHO').appendRow([txt(b.code), txt(b.name || ''), '', 0, '', 'Hàng thông thường', '', 0, 0,
                            'Mã mới khi nhập kho – cần kiểm tra', 0, 0]);
    r = sheet('KHO').getLastRow();
  }
  const st = setStock(r, Number(b.qty) || 0, 0);
  return { ok: true, code: st.code, stock: st.stock, ordered: st.ordered, need: st.need };
}

function orderInfo(code) {
  const row = findOrder(code);
  if (row < 0) return { ok: false, error: 'Không có đơn ' + code };
  const v = sheet('ĐƠN HÀNG').getRange(row, 1, 1, 16).getValues()[0];
  return { ok: true, code: String(v[0]), customer: String(v[2]), phone: cleanPhone(v[3]), total: num(v[8]),
           paid: num(v[12]), left: num(v[13]), status: String(v[14]), pending: String(v[15]),
           lines: orderLines(code).map(l => ({ code: l.code, name: l.name, qty: l.qty, delivered: l.delivered })) };
}

// Ô bắt đầu bằng = + - @ bị hiểu là công thức -> thêm dấu ' để giữ là chữ
function txt(v) { v = v == null ? '' : String(v); return /^[=+\-@]/.test(v) ? "'" + v : v; }
function num(v) {
  if (typeof v === 'number') return v;
  const n = Number(String(v).replace(/[^\d]/g, '')) || 0;
  return /^\s*-/.test(String(v)) ? -n : n;
}
function doGet() { return json({ ok: true, message: 'Sheet đơn hàng + khách hàng sẵn sàng' }); }
function json(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
