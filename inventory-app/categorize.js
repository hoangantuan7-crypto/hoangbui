/*
 * Tự động phân loại sản phẩm.
 * Dùng được cả trong trình duyệt (window.Categorize) và Node (require).
 *
 * Thứ tự ưu tiên:
 *   1. Mã vạch đã được người dùng phân loại trước đó (learned.barcodes)
 *   2. Từ khóa người dùng đã "dạy" (learned.keywords)
 *   3. Danh mục từ Open Food Facts (categories_tags)
 *   4. Bộ từ khóa có sẵn (tiếng Việt + tiếng Anh) trên tên/thương hiệu
 *   5. "Chưa phân loại"
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Categorize = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const UNCATEGORIZED = 'Chưa phân loại';

  // Danh mục mặc định kèm từ khóa (viết không dấu, chữ thường).
  const DEFAULT_CATEGORIES = [
    { name: 'Đồ uống', icon: '🥤', keywords: ['nuoc ngot', 'nuoc suoi', 'nuoc khoang', 'tra xanh', 'tra sua', 'ca phe', 'cafe', 'coffee', 'bia', 'beer', 'ruou', 'wine', 'nuoc ep', 'juice', 'soda', 'cola', 'pepsi', 'coca', 'sting', 'redbull', 'red bull', 'nuoc tang luc', 'energy drink', 'tea', 'water', 'beverage', 'drink', 'lavie', 'aquafina', 'c2', 'revive', '7up', 'mirinda', 'fanta', 'sprite'] },
    { name: 'Sữa & chế phẩm', icon: '🥛', keywords: ['sua', 'milk', 'yaourt', 'yogurt', 'sua chua', 'pho mai', 'cheese', 'bo ', 'butter', 'vinamilk', 'th true', 'dutch lady', 'co gai ha lan', 'nutifood', 'milo', 'ovaltine', 'kem', 'ice cream', 'dairy'] },
    { name: 'Bánh kẹo & snack', icon: '🍪', keywords: ['banh', 'keo', 'snack', 'chocolate', 'socola', 'biscuit', 'cookie', 'cracker', 'candy', 'oishi', 'poca', 'orion', 'chocopie', 'kinh do', 'lays', 'pringles', 'kitkat', 'oreo', 'mentos', 'singum', 'gum', 'thach', 'jelly', 'wafer'] },
    { name: 'Thực phẩm khô', icon: '🍜', keywords: ['mi goi', 'mi tom', 'mi an lien', 'pho', 'bun', 'mien', 'chao', 'gao', 'rice', 'noodle', 'pasta', 'hao hao', 'omachi', 'kokomi', 'acecook', 'dau an', 'oil', 'ngu coc', 'cereal', 'yen mach', 'oat', 'dong hop', 'do hop', 'canned', 'ca hop', 'pate', 'xuc xich', 'sausage', 'lap xuong', 'bot mi', 'flour'] },
    { name: 'Gia vị', icon: '🧂', keywords: ['nuoc mam', 'nuoc tuong', 'xi dau', 'tuong ot', 'tuong ca', 'muoi', 'salt', 'duong', 'sugar', 'tieu', 'pepper', 'bot ngot', 'mi chinh', 'hat nem', 'knorr', 'ajinomoto', 'chin su', 'nam ngu', 'maggi', 'sauce', 'ketchup', 'mayonnaise', 'giam', 'vinegar', 'gia vi', 'spice', 'seasoning'] },
    { name: 'Chăm sóc cá nhân', icon: '🧴', keywords: ['dau goi', 'shampoo', 'dau xa', 'conditioner', 'sua tam', 'shower', 'body wash', 'xa phong', 'soap', 'kem danh rang', 'toothpaste', 'ban chai', 'toothbrush', 'lan khu mui', 'deodorant', 'sua rua mat', 'cleanser', 'kem duong', 'lotion', 'son', 'lipstick', 'my pham', 'cosmetic', 'nuoc hoa', 'perfume', 'dao cao', 'razor', 'bang ve sinh', 'ta ', 'diaper', 'giay ve sinh', 'khan giay', 'tissue', 'colgate', 'p/s', 'closeup', 'sunsilk', 'clear', 'dove', 'lifebuoy', 'head & shoulders', 'pantene', 'nivea', 'romano', 'x-men', 'gillette', 'kotex', 'diana', 'bobby', 'huggies', 'pampers'] },
    { name: 'Vệ sinh nhà cửa', icon: '🧽', keywords: ['nuoc rua chen', 'nuoc rua bat', 'dishwash', 'bot giat', 'nuoc giat', 'detergent', 'laundry', 'nuoc xa vai', 'softener', 'lau san', 'floor', 'tay rua', 'cleaner', 'thuoc diet con trung', 'xit muoi', 'insect', 'sunlight', 'omo', 'ariel', 'tide', 'comfort', 'downy', 'vim', 'javel', 'tui rac', 'trash bag'] },
    { name: 'Thuốc & y tế', icon: '💊', keywords: ['thuoc', 'medicine', 'vitamin', 'vien uong', 'supplement', 'khau trang', 'mask', 'bang gac', 'bandage', 'urgo', 'cao dan', 'dau gio', 'nhiet ke', 'thermometer', 'panadol', 'efferalgan', 'paracetamol', 'nuoc muoi sinh ly', 'con y te', 'alcohol', 'sat khuan', 'antiseptic'] },
    { name: 'Điện tử & phụ kiện', icon: '🔌', keywords: ['pin', 'battery', 'sac', 'charger', 'cap', 'cable', 'usb', 'tai nghe', 'headphone', 'earphone', 'chuot', 'mouse', 'ban phim', 'keyboard', 'loa', 'speaker', 'bong den', 'den led', 'led', 'bulb', 'o cam', 'adapter', 'the nho', 'memory card', 'sd card', 'dien thoai', 'phone', 'energizer', 'duracell', 'panasonic', 'samsung', 'xiaomi', 'anker'] },
    { name: 'Văn phòng phẩm', icon: '✏️', keywords: ['but', 'pen', 'pencil', 'but chi', 'tay', 'eraser', 'vo', 'notebook', 'so tay', 'giay a4', 'paper', 'kep', 'clip', 'bang keo', 'tape', 'keo dan', 'glue', 'thuoc ke', 'ruler', 'phong bi', 'envelope', 'ghim', 'stapler', 'thien long', 'hong ha', 'deli', 'stabilo', 'casio'] },
    { name: 'Đồ gia dụng', icon: '🍳', keywords: ['noi com', 'xoong', 'chao chong dinh', 'pan', 'pot', 'bat', 'dia', 'bowl', 'plate', 'coc', 'ly', 'cup', 'glass', 'dua', 'thia', 'muong', 'spoon', 'fork', 'dao', 'knife', 'hop dung', 'container', 'binh', 'bottle', 'mang boc', 'wrap', 'giay bac', 'foil', 'lock&lock', 'lock & lock', 'khan', 'towel', 'moc ao', 'hanger'] },
    { name: 'Thực phẩm tươi & đông lạnh', icon: '🥩', keywords: ['thit', 'meat', 'ca ', 'fish', 'tom', 'shrimp', 'trung', 'egg', 'rau', 'vegetable', 'trai cay', 'fruit', 'dong lanh', 'frozen', 'cha gio', 'ha cao', 'xa xiu', 'ga ', 'chicken', 'heo', 'pork', 'bo uc', 'beef'] },
    { name: 'Khác', icon: '📦', keywords: [] },
  ];

  // Ánh xạ tag danh mục của Open Food Facts -> danh mục của app.
  const OFF_TAG_MAP = [
    [/beverages|drinks|waters|sodas|juices|teas|coffees|beers|wines|alcoholic/, 'Đồ uống'],
    [/dairies|milks|yogurts|cheeses|butters|ice-creams|dairy/, 'Sữa & chế phẩm'],
    [/snacks|sweets|biscuits|cookies|chocolates|confectioneries|candies|crackers|chips|cakes/, 'Bánh kẹo & snack'],
    [/condiments|sauces|spices|salts|sugars|seasonings|vinegars|fish-sauces|soy-sauces/, 'Gia vị'],
    [/noodles|instant-noodles|pastas|rices|cereals|breakfasts|flours|canned|oils|legumes|groceries/, 'Thực phẩm khô'],
    [/meats|fishes|seafood|eggs|fruits|vegetables|frozen/, 'Thực phẩm tươi & đông lạnh'],
  ];

  // Tiền tố GS1 phổ biến -> nước đăng ký mã vạch (chỉ để tham khảo).
  const GS1_PREFIXES = [
    [893, 893, 'Việt Nam'], [885, 885, 'Thái Lan'], [880, 880, 'Hàn Quốc'],
    [690, 699, 'Trung Quốc'], [450, 459, 'Nhật Bản'], [490, 499, 'Nhật Bản'],
    [888, 888, 'Singapore'], [899, 899, 'Indonesia'], [955, 955, 'Malaysia'],
    [480, 480, 'Philippines'], [471, 471, 'Đài Loan'], [489, 489, 'Hồng Kông'],
    [0, 19, 'Mỹ/Canada'], [30, 39, 'Mỹ/Canada'], [60, 139, 'Mỹ/Canada'],
    [300, 379, 'Pháp'], [400, 440, 'Đức'], [500, 509, 'Anh'], [800, 839, 'Ý'],
    [840, 849, 'Tây Ban Nha'], [870, 879, 'Hà Lan'], [930, 939, 'Úc'],
    [890, 890, 'Ấn Độ'], [460, 469, 'Nga'],
  ];

  /** Bỏ dấu tiếng Việt, chữ thường, gọn khoảng trắng. */
  function normalize(text) {
    return String(text || '')
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .replace(/đ/g, 'd')
      .replace(/Đ/g, 'D')
      .toLowerCase()
      .replace(/\s+/g, ' ')
      .trim();
  }

  /** Khớp từ khóa theo ranh giới từ để "bo" không khớp với "bong". */
  function matchesKeyword(haystack, keyword) {
    const kw = normalize(keyword);
    if (!kw) return false;
    const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp('(^|[^a-z0-9])' + escaped + '($|[^a-z0-9])').test(haystack);
  }

  function originFromBarcode(code) {
    const digits = String(code || '').replace(/\D/g, '');
    if (digits.length !== 13 && digits.length !== 12) return null;
    const ean = digits.length === 12 ? '0' + digits : digits;
    const p3 = parseInt(ean.slice(0, 3), 10);
    for (const [lo, hi, country] of GS1_PREFIXES) {
      if (p3 >= lo && p3 <= hi) return country;
    }
    return null;
  }

  /** Kiểm tra số kiểm tra (check digit) của EAN-13 / EAN-8 / UPC-A. */
  function isValidGtin(code) {
    const d = String(code || '');
    if (!/^\d{8}$|^\d{12,14}$/.test(d)) return false;
    const digits = d.split('').map(Number);
    const check = digits.pop();
    let sum = 0;
    digits.reverse().forEach((n, i) => { sum += n * (i % 2 === 0 ? 3 : 1); });
    return (10 - (sum % 10)) % 10 === check;
  }

  /**
   * @param {object} product  { barcode, name, brand, offCategories: string[] }
   * @param {object} opts     { categories, learned: { barcodes: {}, keywords: {} } }
   * @returns {{ category: string, source: string, confidence: number }}
   */
  function categorize(product, opts) {
    opts = opts || {};
    const categories = opts.categories || DEFAULT_CATEGORIES;
    const learned = opts.learned || { barcodes: {}, keywords: {} };
    const names = new Set(categories.map((c) => c.name));

    if (product.barcode && learned.barcodes && learned.barcodes[product.barcode]) {
      const cat = learned.barcodes[product.barcode];
      if (names.has(cat)) return { category: cat, source: 'learned-barcode', confidence: 1 };
    }

    const text = normalize([product.name, product.brand].filter(Boolean).join(' '));

    if (text && learned.keywords) {
      // Từ khóa dài hơn được ưu tiên (cụ thể hơn).
      const entries = Object.entries(learned.keywords).sort((a, b) => b[0].length - a[0].length);
      for (const [kw, cat] of entries) {
        if (names.has(cat) && matchesKeyword(text, kw)) {
          return { category: cat, source: 'learned-keyword', confidence: 0.9 };
        }
      }
    }

    const tags = (product.offCategories || []).join(' ').toLowerCase();
    if (tags) {
      for (const [re, cat] of OFF_TAG_MAP) {
        if (re.test(tags) && names.has(cat)) {
          return { category: cat, source: 'openfoodfacts', confidence: 0.8 };
        }
      }
    }

    if (text) {
      let best = null;
      for (const cat of categories) {
        let score = 0;
        for (const kw of cat.keywords || []) {
          if (matchesKeyword(text, kw)) score += normalize(kw).length;
        }
        if (score > 0 && (!best || score > best.score)) best = { name: cat.name, score };
      }
      if (best) {
        return { category: best.name, source: 'keywords', confidence: Math.min(0.75, 0.4 + best.score / 40) };
      }
    }

    return { category: UNCATEGORIZED, source: 'none', confidence: 0 };
  }

  /** Lấy "từ khóa đặc trưng" từ tên sản phẩm để ghi nhớ khi người dùng sửa danh mục. */
  function learnKeywordFromName(name) {
    const words = normalize(name).split(' ').filter((w) => w.length > 1 && !/^\d+([.,]\d+)?(g|kg|ml|l|gr|goi|chai|lon|hop)?$/.test(w));
    if (words.length === 0) return null;
    return words.slice(0, 2).join(' ');
  }

  return {
    UNCATEGORIZED,
    DEFAULT_CATEGORIES,
    normalize,
    matchesKeyword,
    categorize,
    originFromBarcode,
    isValidGtin,
    learnKeywordFromName,
  };
});
