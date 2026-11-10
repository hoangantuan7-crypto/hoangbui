# 📦 Kiểm Kho – kiểm kho bằng điện thoại

Ứng dụng web (PWA) chạy ngay trên trình duyệt điện thoại, có thể "Thêm vào màn hình chính" để dùng như app thật. Không cần cài từ App Store / CH Play, không cần server – dữ liệu lưu ngay trên máy.

## Tính năng

- **Quét mã vạch bằng camera** (EAN-13, EAN-8, UPC, Code 128, Code 39, ITF, QR). Cũng nhận **máy quét Bluetooth/USB** hoặc nhập tay.
- **3 chế độ:**
  - ➕ **Nhập kho** – quét là cộng số lượng; mã mới thì mở form thêm sản phẩm.
  - ➖ **Xuất kho** – quét là trừ số lượng (không cho âm).
  - 📋 **Kiểm kê** – đếm thực tế, so sánh với tồn trên app, báo lệch và cập nhật một lần.
- **Tự phân loại sản phẩm:**
  1. Tra cứu tên/ảnh/danh mục trên Open Food Facts (miễn phí, khi có mạng).
  2. Đoán danh mục theo tên/thương hiệu bằng bộ từ khóa tiếng Việt + tiếng Anh (không cần dấu).
  3. **Tự học**: khi bạn sửa danh mục, app nhớ mã vạch đó và từ khóa trong tên → lần sau sản phẩm tương tự tự vào đúng danh mục.
  4. Hiển thị nước đăng ký mã vạch (893 = Việt Nam, 885 = Thái Lan…).
- Danh sách kho nhóm theo danh mục, tìm kiếm, lọc; giá, đơn vị, vị trí kệ.
- Tùy chỉnh danh mục, **xuất Excel (CSV)**, sao lưu/khôi phục JSON, chạy offline.

## Đưa lên điện thoại

Camera trên điện thoại chỉ hoạt động qua **HTTPS**. Cách đơn giản nhất là GitHub Pages:

1. Merge nhánh này vào `main`.
2. Trên GitHub: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Workflow `.github/workflows/inventory-pages.yml` sẽ tự deploy. Địa chỉ dạng
   `https://<tên-tài-khoản>.github.io/hoangbui/`.
4. Mở link trên điện thoại → cho phép camera →
   - iPhone (Safari): nút Chia sẻ → **Thêm vào MH chính**.
   - Android (Chrome): menu ⋮ → **Cài đặt ứng dụng / Thêm vào màn hình chính**.

Chạy thử trên máy tính:

```sh
cd inventory-app
python3 -m http.server 8000   # mở http://localhost:8000
```

## Kiểm thử

```sh
node --test inventory-app/tests/categorize.test.js
```

## Cấu trúc

| File | Vai trò |
|---|---|
| `index.html`, `styles.css` | Giao diện (tối ưu cho điện thoại, có chế độ tối) |
| `app.js` | Quét, nhập/xuất/kiểm kê, lưu trữ, xuất file |
| `categorize.js` | Bộ tự phân loại (từ khóa, Open Food Facts, học từ người dùng) |
| `sw.js`, `manifest.webmanifest` | PWA: cài lên màn hình chính, chạy offline |
| `vendor/html5-qrcode.min.js` | Thư viện quét mã vạch html5-qrcode 2.3.8 (Apache-2.0) |

Lưu ý: dữ liệu nằm trong bộ nhớ trình duyệt của từng điện thoại. Hãy dùng **Sao lưu (JSON)** định kỳ, hoặc để chuyển dữ liệu sang máy khác.
