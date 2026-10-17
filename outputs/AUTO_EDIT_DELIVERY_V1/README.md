# BẢN RÁP TỰ ĐỘNG TẤN PHÁT — V1

HOANG_TAN_PHAT_AUTO_EDIT.mp4 đã có chữ động và SFX tự đặt theo mốc. Mở CapCut → Create Project → Import MP4 này → kéo vào timeline tại 00:00. Không thêm lại SFX_TIMELINE, SRT hoặc CUE MOV từ pack cũ: chúng đã có trong hình/tiếng, thêm nữa sẽ trùng. Bản MP4 là các lớp gộp; không chỉnh riêng từng chữ như project native.

Bản này được dựng từ proxy nén, dùng để xem và chỉnh nhịp. Không phải bản master chất lượng gốc. Proxy có kích thước lưu 720×480 nhưng SAR 3:8, hiển thị 9:16; đã chuyển sang pixel vuông 540×960 để tránh méo hình. 24 fps. Toàn bộ video được giữ, không tăng tốc. SFX giảm âm lượng và tự duck theo âm thanh gốc. Phụ đề có sẵn trong hình được giữ nguyên; lỗi nhận dạng trong phụ đề này chưa được thay thế.

Callout dựa trên timestamp brief/SRT, không phải căn chỉnh từng từ bằng nhận dạng giọng nói. Kiểm tra khi xem lần cuối. Tên hãng/model, thông số lực hút và tuyên bố sản phẩm chưa được chứng minh. Chữ ở dải phía trên; HUD chỉ trang trí, không phải theo dõi cảm biến thật.

## Xuất lại với MOV gốc trên Mac

Thư mục AUTO_RENDER_MAC chứa mã nguồn và RENDER_ON_MAC.command. Cần Python 3.12+ và FFmpeg/FFprobe (nếu có Homebrew: brew install ffmpeg). Script tạo venv, cài NumPy/SciPy/Pillow theo requirements rồi chạy cùng lịch hiệu ứng trên MOV gốc, xuất chiều rộng 1080 theo tỷ lệ hiển thị nguồn. Chỉ dùng MOV cùng nội dung, bắt đầu và thời gian như proxy, không dùng clip đã cắt/đổi tốc độ.

Mở Terminal, gõ bash và một dấu cách, kéo RENDER_ON_MAC.command vào Terminal rồi nhấn Enter. Khi được hỏi, kéo MOV gốc vào và Enter; tiếp theo kéo thư mục CAPCUT_PREMIUM_EDIT_PACK đã giải nén trước đó vào và Enter. Các đường dẫn phải là thư mục/tệp thật trên ổ đĩa. Script không ghi đè file gốc và tạo thư mục kết quả có timestamp. Nếu macOS hỏi quyền truy cập thư mục, cấp quyền cho Terminal theo nhu cầu.

Sau khi xuất xong, nhập MP4 kết quả vào CapCut. Đây vẫn là bản gộp chữ/hiệu ứng, không phải project nhiều lớp native. Giữ MOV gốc và pack cũ để có thể render lại.
