/* Kiểm Kho – ứng dụng kiểm kho bằng điện thoại. */
(function () {
  'use strict';
  const C = window.Categorize;
  const STORAGE_KEY = 'kiemkho.v1';
  const $ = (sel) => document.querySelector(sel);

  // ---------- Lưu trữ ----------
  function defaultState() {
    return {
      items: {},
      categories: C.DEFAULT_CATEGORIES.map((c) => ({ ...c, keywords: [...c.keywords] })),
      learned: { barcodes: {}, keywords: {} },
      history: [],
      settings: { online: true, autosave: false, sound: true, scanArea: 'medium', speed: 'fast' },
      count: {},
    };
  }
  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return defaultState();
      const data = JSON.parse(raw);
      const def = defaultState();
      // Gộp cài đặt để bản cũ vẫn có các tùy chọn mới.
      return { ...def, ...data, settings: { ...def.settings, ...(data.settings || {}) } };
    } catch (e) {
      return defaultState();
    }
  }
  let state = load();
  function save() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
    catch (e) { toast('⚠️ Không lưu được dữ liệu (bộ nhớ đầy?)'); }
  }

  let mode = 'in';
  let editing = null; // { barcode, isNew, suggestion }

  // ---------- Tiện ích ----------
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  }
  let toastTimer;
  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2200);
  }
  let audioCtx;
  function feedback(ok) {
    if (!state.settings.sound) return;
    try {
      if (navigator.vibrate) navigator.vibrate(ok ? 60 : [60, 60, 60]);
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const o = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      o.frequency.value = ok ? 1200 : 300;
      g.gain.setValueAtTime(0.15, audioCtx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.15);
      o.connect(g).connect(audioCtx.destination);
      o.start();
      o.stop(audioCtx.currentTime + 0.15);
    } catch (e) { /* không hỗ trợ âm thanh */ }
  }
  function categoryIcon(name) {
    const c = state.categories.find((x) => x.name === name);
    return c ? c.icon : '❓';
  }
  function fmtMoney(n) { return n ? Number(n).toLocaleString('vi-VN') + 'đ' : ''; }
  function step() { return Math.max(1, parseInt($('#step').value, 10) || 1); }

  // ---------- Tra cứu online ----------
  async function lookupOnline(barcode) {
    if (!state.settings.online || !navigator.onLine) return null;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 5000);
    try {
      const url = 'https://world.openfoodfacts.org/api/v2/product/' + encodeURIComponent(barcode) +
        '.json?fields=product_name,product_name_vi,generic_name,brands,categories_tags,image_front_small_url,quantity';
      const res = await fetch(url, { signal: ctrl.signal });
      if (!res.ok) return null;
      const data = await res.json();
      if (data.status !== 1 || !data.product) return null;
      const p = data.product;
      const name = p.product_name_vi || p.product_name || p.generic_name || '';
      return {
        name: [name, p.quantity].filter(Boolean).join(' ').trim(),
        brand: (p.brands || '').split(',')[0].trim(),
        offCategories: p.categories_tags || [],
        image: p.image_front_small_url || '',
      };
    } catch (e) {
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  // ---------- Xử lý mã quét ----------
  async function handleCode(raw) {
    const barcode = String(raw || '').trim();
    if (!barcode) return;
    const item = state.items[barcode];

    if (mode === 'count') {
      state.count[barcode] = (state.count[barcode] || 0) + step();
      save();
      feedback(true);
      if (!item) {
        toast('Mã mới ' + barcode + ' – hãy thêm thông tin sản phẩm');
        await openNewItem(barcode, 0);
      } else {
        toast('📋 ' + item.name + ': đếm được ' + state.count[barcode]);
      }
      addRecent(barcode, step(), 'count');
      render();
      return;
    }

    if (item) {
      const delta = mode === 'out' ? -step() : step();
      if (item.quantity + delta < 0) {
        feedback(false);
        toast('⚠️ ' + item.name + ' chỉ còn ' + item.quantity);
        return;
      }
      item.quantity += delta;
      item.updatedAt = Date.now();
      addRecent(barcode, delta);
      save();
      feedback(true);
      toast((delta > 0 ? '➕ ' : '➖ ') + item.name + ' → còn ' + item.quantity);
      render();
      return;
    }

    if (mode === 'out') {
      feedback(false);
      toast('⚠️ Mã ' + barcode + ' chưa có trong kho');
      return;
    }
    feedback(true);
    await openNewItem(barcode, step());
  }

  function addRecent(barcode, delta, kind) {
    state.history.unshift({ barcode, delta, kind: kind || mode, at: Date.now() });
    state.history = state.history.slice(0, 200);
  }

  async function openNewItem(barcode, qty) {
    pauseScanner();
    const origin = C.originFromBarcode(barcode);
    editing = { barcode, isNew: true, suggestion: null };
    fillForm({ barcode, name: '', brand: '', category: C.UNCATEGORIZED, quantity: qty, unit: 'cái', price: '', location: '', image: '', origin });
    $('#sheet-title').textContent = 'Sản phẩm mới';
    $('#f-delete').classList.add('hidden');
    $('#f-lookup').textContent = state.settings.online ? '🔄 Đang tra cứu thông tin sản phẩm…' : '';
    showSheet(true);

    const info = await lookupOnline(barcode);
    if (!editing || editing.barcode !== barcode) return; // người dùng đã đóng
    const product = { barcode, name: info ? info.name : '', brand: info ? info.brand : '', offCategories: info ? info.offCategories : [] };
    if (info) {
      if (!$('#f-name').value) $('#f-name').value = info.name;
      if (!$('#f-brand').value) $('#f-brand').value = info.brand;
      if (info.image) { $('#f-image').src = info.image; $('#f-image').classList.remove('hidden'); }
      editing.image = info.image;
      editing.offCategories = info.offCategories;
      $('#f-lookup').textContent = '✅ Đã tìm thấy trên Open Food Facts';
    } else {
      $('#f-lookup').textContent = state.settings.online ? 'ℹ️ Không tìm thấy online – nhập tên, app sẽ tự gợi ý danh mục' : '';
    }
    applySuggestion(product);

    if (state.settings.autosave && info && info.name && editing.suggestion && editing.suggestion.source !== 'none') {
      $('#item-form').requestSubmit();
    } else {
      $('#f-name').focus();
    }
  }

  function applySuggestion(product) {
    const s = C.categorize(product, { categories: state.categories, learned: state.learned });
    editing.suggestion = s;
    if (s.source !== 'none') $('#f-category').value = s.category;
    const labels = {
      'learned-barcode': 'đã học',
      'learned-keyword': 'đã học từ khóa',
      openfoodfacts: 'theo dữ liệu online',
      keywords: 'theo tên',
      none: '',
    };
    const badge = $('#f-suggest');
    badge.textContent = s.source === 'none' ? 'chưa đoán được' : '🤖 tự phân loại ' + labels[s.source];
    badge.classList.toggle('auto', s.source !== 'none');
  }

  // Gợi ý lại danh mục khi người dùng gõ tên (nếu họ chưa tự chọn).
  let userPickedCategory = false;
  let typingTimer;
  function onNameInput() {
    if (!editing || !editing.isNew || userPickedCategory) return;
    clearTimeout(typingTimer);
    typingTimer = setTimeout(() => {
      applySuggestion({
        barcode: editing.barcode,
        name: $('#f-name').value,
        brand: $('#f-brand').value,
        offCategories: editing.offCategories || [],
      });
    }, 250);
  }

  // ---------- Form sản phẩm ----------
  function renderCategoryOptions() {
    const sel = $('#f-category');
    const names = state.categories.map((c) => c.name);
    if (!names.includes(C.UNCATEGORIZED)) names.push(C.UNCATEGORIZED);
    sel.innerHTML = names.map((n) => '<option value="' + esc(n) + '">' + esc(categoryIcon(n) + ' ' + n) + '</option>').join('');
  }
  function fillForm(it) {
    renderCategoryOptions();
    userPickedCategory = false;
    $('#f-barcode').textContent = it.barcode;
    $('#f-origin').textContent = [it.origin ? 'Mã đăng ký tại: ' + it.origin : '', C.isValidGtin(it.barcode) ? '' : (/^\d+$/.test(it.barcode) ? '' : 'Mã nội bộ / QR')].filter(Boolean).join(' · ');
    $('#f-name').value = it.name || '';
    $('#f-brand').value = it.brand || '';
    $('#f-category').value = it.category || C.UNCATEGORIZED;
    $('#f-qty').value = it.quantity != null ? it.quantity : 1;
    $('#f-unit').value = it.unit || 'cái';
    $('#f-price').value = it.price || '';
    $('#f-location').value = it.location || '';
    $('#f-suggest').textContent = '';
    $('#f-suggest').classList.remove('auto');
    $('#f-lookup').textContent = '';
    const img = $('#f-image');
    if (it.image) { img.src = it.image; img.classList.remove('hidden'); } else { img.removeAttribute('src'); img.classList.add('hidden'); }
  }
  function openEdit(barcode) {
    const it = state.items[barcode];
    if (!it) return;
    editing = { barcode, isNew: false, suggestion: null, previousCategory: it.category };
    fillForm(it);
    $('#sheet-title').textContent = 'Sửa sản phẩm';
    $('#f-delete').classList.remove('hidden');
    showSheet(true);
  }
  function showSheet(open) {
    $('#sheet').classList.toggle('hidden', !open);
    if (!open) { editing = null; resumeScanner(); }
  }

  function onSubmit(e) {
    e.preventDefault();
    if (!editing) return;
    const barcode = editing.barcode;
    const name = $('#f-name').value.trim();
    if (!name) { $('#f-name').focus(); return; }
    const category = $('#f-category').value;
    const prev = state.items[barcode];
    const qty = Math.max(0, parseInt($('#f-qty').value, 10) || 0);
    const it = {
      ...(prev || { createdAt: Date.now() }),
      barcode,
      name,
      brand: $('#f-brand').value.trim(),
      category,
      quantity: qty,
      unit: $('#f-unit').value.trim() || 'cái',
      price: Number($('#f-price').value) || 0,
      location: $('#f-location').value.trim(),
      image: (prev && prev.image) || editing.image || '',
      origin: C.originFromBarcode(barcode),
      updatedAt: Date.now(),
    };
    state.items[barcode] = it;

    // Học từ lựa chọn của người dùng.
    const suggested = editing.suggestion ? editing.suggestion.category : editing.previousCategory;
    if (category !== C.UNCATEGORIZED && category !== suggested) {
      state.learned.barcodes[barcode] = category;
      const kw = C.learnKeywordFromName(name);
      if (kw) state.learned.keywords[kw] = category;
      toast('🧠 Đã ghi nhớ: "' + name + '" thuộc ' + category);
    } else if (editing.isNew) {
      toast('✅ Đã thêm ' + name + ' vào ' + category);
    } else {
      toast('✅ Đã lưu');
    }
    if (editing.isNew && mode !== 'count') addRecent(barcode, qty);
    save();
    showSheet(false);
    render();
  }

  function onDelete() {
    if (!editing) return;
    const it = state.items[editing.barcode];
    if (!confirm('Xóa "' + it.name + '" khỏi kho?')) return;
    delete state.items[editing.barcode];
    delete state.count[editing.barcode];
    save();
    showSheet(false);
    render();
    toast('Đã xóa');
  }

  // ---------- Camera ----------
  let scanner = null;
  let scanning = false;
  let paused = false;
  let lastCode = '';
  let lastAt = 0;
  let torch = null; // tính năng đèn flash của camera đang chạy
  let torchOn = false;

  // Kích thước vùng quét theo tỉ lệ khung hình (rộng, cao). null = toàn khung.
  const SCAN_AREAS = { small: [0.6, 0.22], medium: [0.8, 0.4], large: [0.95, 0.6], full: null };
  // fps: số khung hình phân tích mỗi giây; dedupe: thời gian bỏ qua cùng một mã (ms).
  const SPEEDS = { normal: { fps: 10, dedupe: 2000 }, fast: { fps: 20, dedupe: 1500 }, max: { fps: 30, dedupe: 1000 } };
  const speed = () => SPEEDS[state.settings.speed] || SPEEDS.fast;

  function scanConfig() {
    const cfg = {
      fps: speed().fps,
      disableFlip: true, // mã vạch không bị lật gương → bỏ bước thử lật, quét nhanh hơn
      // Độ phân giải cao hơn giúp đọc mã nhỏ/xa; "ideal" để máy yếu vẫn chạy được.
      videoConstraints: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
    };
    const area = SCAN_AREAS[state.settings.scanArea];
    if (area) {
      cfg.qrbox = (w, h) => ({
        width: Math.max(80, Math.floor(w * area[0])),
        height: Math.max(60, Math.floor(Math.min(h, w) * area[1])),
      });
    }
    return cfg;
  }

  async function toggleCamera() {
    if (scanning) return stopCamera();
    await startCamera();
  }
  async function startCamera() {
    if (typeof Html5Qrcode === 'undefined') {
      toast('Không tải được thư viện quét. Kiểm tra kết nối mạng.');
      return;
    }
    try {
      const F = window.Html5QrcodeSupportedFormats;
      scanner = scanner || new Html5Qrcode('reader', {
        formatsToSupport: [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39, F.ITF, F.QR_CODE],
        experimentalFeatures: { useBarCodeDetectorIfSupported: true },
        verbose: false,
      });
      await scanner.start({ facingMode: 'environment' }, scanConfig(), onDecoded, () => {});
      scanning = true;
      paused = false;
      $('#scanner-placeholder').classList.add('hidden');
      $('#btn-camera').textContent = '⏹ Tắt camera';
      // Lấy nét liên tục (nếu camera hỗ trợ) để quét nhanh khi di chuyển.
      try { await scanner.applyVideoConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (e) { /* không hỗ trợ */ }
      setupTorch();
    } catch (err) {
      toast('Không mở được camera: hãy cho phép quyền camera (cần HTTPS).');
      console.error(err);
    }
  }
  async function stopCamera() {
    if (scanner && scanning) {
      try { await scanner.stop(); } catch (e) { /* bỏ qua */ }
    }
    scanning = false;
    torch = null;
    setTorchUi(false, false);
    $('#scanner-placeholder').classList.remove('hidden');
    $('#btn-camera').textContent = '📷 Bật camera';
  }
  async function restartCamera() {
    if (!scanning) return;
    await stopCamera();
    await startCamera();
  }

  // ---------- Đèn flash ----------
  function setupTorch() {
    torch = null;
    try {
      const t = scanner.getRunningTrackCameraCapabilities().torchFeature();
      if (t.isSupported()) torch = t;
    } catch (e) { /* trình duyệt không hỗ trợ */ }
    setTorchUi(!!torch, false);
  }
  function setTorchUi(visible, on) {
    torchOn = on;
    const b = $('#btn-torch');
    b.classList.toggle('hidden', !visible);
    b.setAttribute('aria-pressed', String(on));
    b.setAttribute('aria-label', on ? 'Tắt đèn flash' : 'Bật đèn flash');
  }
  async function toggleTorch() {
    if (!torch) return;
    try {
      await torch.apply(!torchOn);
      setTorchUi(true, !torchOn);
    } catch (e) {
      toast('Không bật được đèn flash trên máy này');
    }
  }
  function pauseScanner() {
    if (scanner && scanning && !paused) { try { scanner.pause(true); paused = true; } catch (e) { /* bỏ qua */ } }
  }
  function resumeScanner() {
    if (scanner && scanning && paused) { try { scanner.resume(); paused = false; } catch (e) { /* bỏ qua */ } }
  }
  function onDecoded(text) {
    const now = Date.now();
    if (text === lastCode && now - lastAt < speed().dedupe) return; // chống quét lặp
    lastCode = text;
    lastAt = now;
    const wrap = document.querySelector('.scanner-wrap');
    wrap.classList.remove('flash'); void wrap.offsetWidth; wrap.classList.add('flash');
    handleCode(text);
  }

  // ---------- Kiểm kê ----------
  function renderCount() {
    const panel = $('#count-panel');
    panel.classList.toggle('hidden', mode !== 'count');
    if (mode !== 'count') return;
    const codes = Object.keys(state.count);
    let mismatch = 0;
    const rows = codes.map((code) => {
      const it = state.items[code];
      const counted = state.count[code];
      const sys = it ? it.quantity : 0;
      const diff = counted - sys;
      if (diff !== 0) mismatch++;
      return '<li><span>' + esc(it ? it.name : code) + '</span><span class="' + (diff === 0 ? 'diff-ok' : 'diff-bad') + '">' +
        counted + ' / ' + sys + (diff === 0 ? ' ✓' : ' (' + (diff > 0 ? '+' : '') + diff + ')') + '</span></li>';
    });
    $('#count-list').innerHTML = rows.join('') || '<li class="muted">Quét từng sản phẩm để đếm. Hiển thị: đếm được / tồn trên app.</li>';
    $('#count-summary').textContent = codes.length + ' mã · ' + mismatch + ' lệch';
  }
  function applyCount() {
    const codes = Object.keys(state.count).filter((c) => state.items[c]);
    if (!codes.length) return toast('Chưa có số đếm nào');
    if (!confirm('Cập nhật tồn kho của ' + codes.length + ' sản phẩm theo số đã đếm?')) return;
    codes.forEach((c) => { state.items[c].quantity = state.count[c]; state.items[c].updatedAt = Date.now(); });
    state.count = {};
    save();
    render();
    toast('✅ Đã cập nhật tồn kho');
  }

  // ---------- Hiển thị ----------
  let filterCat = 'all';
  function render() {
    const items = Object.values(state.items);
    const units = items.reduce((s, i) => s + i.quantity, 0);
    $('#stats').textContent = items.length + ' sản phẩm · ' + units + ' đơn vị';

    $('#recent').innerHTML = state.history.slice(0, 15).map((h) => {
      const it = state.items[h.barcode];
      const sign = h.kind === 'count' ? '📋 ' + h.delta : (h.delta > 0 ? '+' + h.delta : String(h.delta));
      const cls = h.kind === 'count' ? '' : (h.delta > 0 ? 'plus' : 'minus');
      return '<li><div class="thumb">' + esc(it ? categoryIcon(it.category) : '❓') + '</div><div class="info"><div class="name">' +
        esc(it ? it.name : h.barcode) + '</div><div class="meta">' + esc(it ? it.category : 'chưa lưu') + ' · ' +
        new Date(h.at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }) + '</div></div><span class="delta ' + cls + '">' + esc(sign) + '</span></li>';
    }).join('') || '<li class="muted">Chưa quét sản phẩm nào.</li>';

    renderCount();
    renderStock();
    renderSettings();
  }

  function renderStock() {
    const q = C.normalize($('#search').value);
    const items = Object.values(state.items).filter((it) =>
      (filterCat === 'all' || it.category === filterCat) &&
      (!q || C.normalize(it.name + ' ' + it.brand + ' ' + it.barcode + ' ' + it.location).includes(q))
    );

    const counts = {};
    Object.values(state.items).forEach((it) => { counts[it.category] = (counts[it.category] || 0) + 1; });
    const cats = Object.keys(counts).sort();
    $('#chips').innerHTML = ['all', ...cats].map((c) =>
      '<button class="chip' + (filterCat === c ? ' active' : '') + '" data-cat="' + esc(c) + '">' +
      esc(c === 'all' ? 'Tất cả (' + Object.keys(state.items).length + ')' : categoryIcon(c) + ' ' + c + ' (' + counts[c] + ')') + '</button>'
    ).join('');

    if (!items.length) {
      $('#stock-list').innerHTML = '<div class="empty">' + (Object.keys(state.items).length ? 'Không tìm thấy sản phẩm phù hợp.' : 'Kho trống. Vào tab Quét để thêm sản phẩm.') + '</div>';
      return;
    }
    const groups = {};
    items.forEach((it) => { (groups[it.category] = groups[it.category] || []).push(it); });
    $('#stock-list').innerHTML = Object.keys(groups).sort().map((cat) => {
      const list = groups[cat].sort((a, b) => a.name.localeCompare(b.name, 'vi'));
      const total = list.reduce((s, i) => s + i.quantity, 0);
      return '<div class="group-head">' + esc(categoryIcon(cat) + ' ' + cat) + '<span>' + list.length + ' SP · ' + total + '</span></div>' +
        list.map((it) => '<div class="item" data-code="' + esc(it.barcode) + '">' +
          (it.image ? '<img class="thumb" src="' + esc(it.image) + '" alt="">' : '<div class="thumb">' + esc(categoryIcon(cat)) + '</div>') +
          '<div class="info"><div class="name">' + esc(it.name) + '</div><div class="meta">' +
          esc([it.brand, it.barcode, it.location, fmtMoney(it.price)].filter(Boolean).join(' · ')) + '</div></div>' +
          '<div class="qty' + (it.quantity <= 0 ? ' low' : '') + '">' + it.quantity + '</div></div>').join('');
    }).join('');
  }

  function renderSettings() {
    $('#cat-list').innerHTML = state.categories.map((c, i) =>
      '<li><span>' + esc(c.icon + ' ' + c.name) + '</span>' +
      (c.name === 'Khác' ? '' : '<button class="ghost" data-del-cat="' + i + '" aria-label="Xóa danh mục">🗑</button>') + '</li>'
    ).join('');
    $('#opt-online').checked = state.settings.online;
    $('#opt-autosave').checked = state.settings.autosave;
    $('#opt-sound').checked = state.settings.sound;
    $('#learned-info').textContent = 'App đã học ' + Object.keys(state.learned.barcodes).length + ' mã vạch và ' +
      Object.keys(state.learned.keywords).length + ' từ khóa từ các lần bạn sửa danh mục.';
  }

  // ---------- Xuất / nhập ----------
  function download(name, content, type) {
    const blob = new Blob([content], { type });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }
  function exportCsv() {
    const head = ['Mã vạch', 'Tên sản phẩm', 'Thương hiệu', 'Danh mục', 'Số lượng', 'Đơn vị', 'Giá', 'Thành tiền', 'Vị trí', 'Xuất xứ mã', 'Cập nhật'];
    const cell = (v) => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
    const rows = Object.values(state.items)
      .sort((a, b) => a.category.localeCompare(b.category, 'vi') || a.name.localeCompare(b.name, 'vi'))
      .map((it) => [
        '\t' + it.barcode, it.name, it.brand, it.category, it.quantity, it.unit, it.price, it.price * it.quantity,
        it.location, it.origin || '', new Date(it.updatedAt).toLocaleString('vi-VN'),
      ].map(cell).join(','));
    // BOM để Excel đọc đúng tiếng Việt.
    download('kiem-kho-' + new Date().toISOString().slice(0, 10) + '.csv', '﻿' + [head.map(cell).join(','), ...rows].join('\r\n'), 'text/csv;charset=utf-8');
  }
  function exportJson() {
    download('kiem-kho-backup-' + new Date().toISOString().slice(0, 10) + '.json', JSON.stringify(state, null, 2), 'application/json');
  }
  function importJson(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result);
        if (!data || typeof data.items !== 'object') throw new Error('bad');
        if (!confirm('Thay dữ liệu hiện tại bằng bản sao lưu (' + Object.keys(data.items).length + ' sản phẩm)?')) return;
        const def = defaultState();
        state = { ...def, ...data, settings: { ...def.settings, ...(data.settings || {}) } };
        $('#opt-area').value = state.settings.scanArea;
        $('#opt-speed').value = state.settings.speed;
        save();
        render();
        toast('✅ Đã khôi phục');
      } catch (e) {
        toast('⚠️ File sao lưu không hợp lệ');
      }
    };
    reader.readAsText(file);
  }

  // ---------- Sự kiện ----------
  function bind() {
    document.querySelectorAll('.tabbtn').forEach((b) => b.addEventListener('click', () => {
      document.querySelectorAll('.tabbtn').forEach((x) => x.classList.toggle('active', x === b));
      document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.id === 'tab-' + b.dataset.tab));
      if (b.dataset.tab !== 'scan' && scanning) stopCamera();
      window.scrollTo(0, 0);
    }));
    document.querySelectorAll('.mode').forEach((b) => b.addEventListener('click', () => {
      mode = b.dataset.mode;
      document.querySelectorAll('.mode').forEach((x) => {
        x.classList.toggle('active', x === b);
        x.setAttribute('aria-checked', String(x === b));
      });
      render();
    }));
    $('#btn-camera').addEventListener('click', toggleCamera);
    $('#btn-torch').addEventListener('click', toggleTorch);
    $('#opt-area').value = state.settings.scanArea;
    $('#opt-speed').value = state.settings.speed;
    [['#opt-area', 'scanArea'], ['#opt-speed', 'speed']].forEach(([sel, key]) => $(sel).addEventListener('change', (e) => {
      state.settings[key] = e.target.value;
      save();
      restartCamera(); // áp dụng ngay nếu camera đang bật
    }));
    $('#manual-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const v = $('#manual-code').value.trim();
      $('#manual-code').value = '';
      handleCode(v);
    });

    $('#item-form').addEventListener('submit', onSubmit);
    $('#sheet-close').addEventListener('click', () => showSheet(false));
    $('#sheet').addEventListener('click', (e) => { if (e.target.id === 'sheet') showSheet(false); });
    $('#f-delete').addEventListener('click', onDelete);
    $('#f-name').addEventListener('input', onNameInput);
    $('#f-brand').addEventListener('input', onNameInput);
    $('#f-category').addEventListener('change', () => { userPickedCategory = true; });
    document.querySelectorAll('.stepper button').forEach((b) => b.addEventListener('click', () => {
      const inp = $('#f-qty');
      inp.value = Math.max(0, (parseInt(inp.value, 10) || 0) + Number(b.dataset.delta));
    }));

    $('#search').addEventListener('input', renderStock);
    $('#chips').addEventListener('click', (e) => {
      const b = e.target.closest('[data-cat]');
      if (!b) return;
      filterCat = b.dataset.cat;
      renderStock();
    });
    $('#stock-list').addEventListener('click', (e) => {
      const el = e.target.closest('[data-code]');
      if (el) openEdit(el.dataset.code);
    });

    $('#cat-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const name = $('#cat-name').value.trim();
      if (!name) return;
      if (state.categories.some((c) => c.name.toLowerCase() === name.toLowerCase())) return toast('Danh mục đã tồn tại');
      // Tên danh mục cũng là từ khóa để tự phân loại.
      state.categories.splice(state.categories.length - 1, 0, { name, icon: $('#cat-icon').value.trim() || '🏷️', keywords: [C.normalize(name)] });
      $('#cat-name').value = '';
      $('#cat-icon').value = '';
      save();
      render();
    });
    $('#cat-list').addEventListener('click', (e) => {
      const b = e.target.closest('[data-del-cat]');
      if (!b) return;
      const cat = state.categories[Number(b.dataset.delCat)];
      const used = Object.values(state.items).filter((i) => i.category === cat.name).length;
      if (!confirm('Xóa danh mục "' + cat.name + '"?' + (used ? ' ' + used + ' sản phẩm sẽ chuyển sang "Khác".' : ''))) return;
      Object.values(state.items).forEach((i) => { if (i.category === cat.name) i.category = 'Khác'; });
      state.categories.splice(Number(b.dataset.delCat), 1);
      save();
      render();
    });
    ['online', 'autosave', 'sound'].forEach((k) => $('#opt-' + k).addEventListener('change', (e) => {
      state.settings[k] = e.target.checked;
      save();
    }));
    $('#btn-forget').addEventListener('click', () => {
      if (!confirm('Xóa toàn bộ dữ liệu đã học?')) return;
      state.learned = { barcodes: {}, keywords: {} };
      save();
      render();
    });
    $('#btn-count-apply').addEventListener('click', applyCount);
    $('#btn-count-reset').addEventListener('click', () => {
      if (!confirm('Xóa số đếm của phiên kiểm kê hiện tại?')) return;
      state.count = {};
      save();
      render();
    });
    $('#btn-export-csv').addEventListener('click', exportCsv);
    $('#btn-export-json').addEventListener('click', exportJson);
    $('#file-import').addEventListener('change', (e) => { if (e.target.files[0]) importJson(e.target.files[0]); e.target.value = ''; });
    $('#btn-clear').addEventListener('click', () => {
      if (!confirm('Xóa TOÀN BỘ sản phẩm, lịch sử và cài đặt? Không thể hoàn tác.')) return;
      state = defaultState();
      save();
      render();
    });
  }

  bind();
  render();
  if ('serviceWorker' in navigator && location.protocol === 'https:') {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
})();
