const test = require('node:test');
const assert = require('node:assert');
const C = require('../categorize.js');

const cat = (name, extra = {}) => C.categorize({ name, ...extra }).category;

test('phân loại theo tên tiếng Việt có dấu', () => {
  assert.strictEqual(cat('Mì Hảo Hảo tôm chua cay 75g'), 'Thực phẩm khô');
  assert.strictEqual(cat('Nước mắm Nam Ngư 500ml'), 'Gia vị');
  assert.strictEqual(cat('Sữa tươi Vinamilk 180ml'), 'Sữa & chế phẩm');
  assert.strictEqual(cat('Dầu gội Clear Men'), 'Chăm sóc cá nhân');
  assert.strictEqual(cat('Nước rửa chén Sunlight chanh'), 'Vệ sinh nhà cửa');
  assert.strictEqual(cat('Bút bi Thiên Long TL-027'), 'Văn phòng phẩm');
  assert.strictEqual(cat('Pin AA Energizer'), 'Điện tử & phụ kiện');
  assert.strictEqual(cat('Trà xanh C2 chanh'), 'Đồ uống');
  assert.strictEqual(cat('Bánh Chocopie Orion'), 'Bánh kẹo & snack');
  assert.strictEqual(cat('Kem đánh răng P/S'), 'Chăm sóc cá nhân');
});

test('cụm từ dài thắng từ ngắn', () => {
  assert.strictEqual(cat('Phô mai con bò cười'), 'Sữa & chế phẩm');
  assert.strictEqual(cat('Thước kẻ 20cm'), 'Văn phòng phẩm');
  assert.strictEqual(cat('Cà phê G7 hòa tan'), 'Đồ uống');
});

test('không khớp nửa từ', () => {
  assert.ok(!C.matchesKeyword(C.normalize('bong den'), 'bo'));
  assert.ok(C.matchesKeyword(C.normalize('Sữa bò'), 'bo'));
});

test('dùng danh mục Open Food Facts khi tên không rõ', () => {
  const r = C.categorize({ name: 'XYZ 123', offCategories: ['en:beverages', 'en:sodas'] });
  assert.strictEqual(r.category, 'Đồ uống');
  assert.strictEqual(r.source, 'openfoodfacts');
});

test('ưu tiên những gì đã học', () => {
  const learned = { barcodes: { '8934563138165': 'Khác' }, keywords: { 'hop qua': 'Đồ gia dụng' } };
  assert.strictEqual(C.categorize({ barcode: '8934563138165', name: 'Mì Hảo Hảo' }, { learned }).source, 'learned-barcode');
  assert.strictEqual(C.categorize({ name: 'Hộp quà Tết' }, { learned }).category, 'Đồ gia dụng');
});

test('không đoán được -> Chưa phân loại', () => {
  assert.strictEqual(cat('ABC-001'), C.UNCATEGORIZED);
  assert.strictEqual(cat(''), C.UNCATEGORIZED);
});

test('mã vạch: xuất xứ và check digit', () => {
  assert.strictEqual(C.originFromBarcode('8934563138165'), 'Việt Nam');
  assert.strictEqual(C.originFromBarcode('8851234567890'), 'Thái Lan');
  assert.strictEqual(C.originFromBarcode('abc'), null);
  assert.ok(C.isValidGtin('4006381333931'));
  assert.ok(!C.isValidGtin('4006381333932'));
  assert.ok(C.isValidGtin('96385074'));
});

test('học từ khóa từ tên', () => {
  assert.strictEqual(C.learnKeywordFromName('Hộp quà Tết 500g'), 'hop qua');
  assert.strictEqual(C.learnKeywordFromName('500g'), null);
});
