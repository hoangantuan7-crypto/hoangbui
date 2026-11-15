// Bot Điều phối ghi khách hàng mới vào Google Sheet này.
// Cài: mở Sheet -> Tiện ích mở rộng -> Apps Script -> dán toàn bộ file này -> đổi TOKEN -> Lưu
//      -> Triển khai -> Tùy chọn triển khai mới -> Ứng dụng web (Thực thi: Tôi · Truy cập: Bất kỳ ai) -> Triển khai.
// Cột Sheet: STT · Ngày thêm · Tên khách hàng · Số điện thoại · Địa chỉ · Ghi chú · Người gửi · Nguồn · Trạng thái
//            · Link ảnh gốc · Mã tin Zalo
const TOKEN = 'DOI-THANH-MA-BI-MAT';  // mật khẩu do anh tự đặt, không dấu, không khoảng trắng, giữ kín

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  if (body.token !== TOKEN) return json({ ok: false, error: 'Sai mã bí mật' });
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    let phone = String(body.phone || '').replace(/\D/g, '');
    if (phone.startsWith('84') && phone.length === 11) phone = '0' + phone.slice(2);
    const last = sh.getLastRow();
    if (phone && last > 1) {   // trùng số điện thoại -> không thêm, báo dòng cũ
      const phones = sh.getRange(2, 4, last - 1, 1).getDisplayValues().map(r => String(r[0]).replace(/\D/g, ''));
      const i = phones.indexOf(phone);
      if (i >= 0) return json({ ok: true, duplicate: true, row: i + 2, stt: sh.getRange(i + 2, 1).getValue() });
    }
    const stt = last < 2 ? 1 : Math.max(...sh.getRange(2, 1, last - 1, 1).getValues().map(r => Number(r[0]) || 0)) + 1;
    const now = Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'dd/MM/yyyy HH:mm');
    sh.appendRow([stt, body.date || now, body.name || '', phone ? "'" + phone : '', body.address || '',
                  body.note || '', body.sender || '', body.source || '', body.status || '',
                  body.image || '', body.msgId || '']);
    return json({ ok: true, row: sh.getLastRow(), stt: stt });
  } finally {
    lock.releaseLock();
  }
}

function doGet() { return json({ ok: true, message: 'Sheet khách hàng sẵn sàng' }); }
function json(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
