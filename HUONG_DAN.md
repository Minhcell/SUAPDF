# SỬA PDF OFFLINE – Hướng dẫn

Phần mềm chạy hoàn toàn **offline** trên Windows 10/11 (64-bit), chỉ 1 file `SuaPDF.exe`, không cần cài đặt.
Lần chạy đầu phần mềm đọc danh sách font của máy (vài giây), các lần sau mở nhanh.

## Sửa văn bản
| Chế độ | Phím | Cách dùng |
|---|---|---|
| **Sửa chữ** | F2 | Rê chuột lên dòng chữ (hiện khung xanh) → bấm → gõ sửa như Word |
| **Thêm chữ** | F3 | Bấm vào chỗ trống trên trang → gõ chữ mới |
| **Tẩy** | F4 | Kéo chuột khoanh vùng → *Xoá chữ (giữ khung bảng, chữ ký)* hoặc *Phủ trắng* |

- Trong ô soạn: **Enter** = xuống dòng, **Ctrl+Enter** hoặc bấm ra ngoài = ghi, **Esc** = huỷ.
- Xoá hết chữ trong ô rồi bấm ra ngoài = xoá dòng đó.
- **Font** mặc định *Times New Roman*; chọn font khác và **cỡ chữ** trên thanh định dạng
  (đổi khi đang sửa thì áp dụng ngay). Có nút **B** (đậm), **I** (nghiêng), **Màu chữ**.
- Ô *“Chỉ font có tiếng Việt”*: chỉ liệt kê font gõ được đủ dấu tiếng Việt.
- Ô *“Giữ font gốc của dòng khi sửa”*: bật nếu muốn dòng sửa dùng lại font của file gốc.
- **Ctrl+Z / Ctrl+Y**: hoàn tác / làm lại. **Ctrl + lăn chuột**: phóng to/thu nhỏ.
- Có thể kéo thả file PDF vào cửa sổ.

## Lưu (Ctrl+S) – chọn định dạng
| Định dạng | Ghi chú |
|---|---|
| **PDF** (khuyên dùng) | Giữ nguyên 100%: bảng, khung, chữ ký, con dấu không xê dịch |
| **Word – giữ nguyên bố cục, sửa được chữ** | Khung bảng/chữ ký/con dấu làm nền cố định, từng dòng chữ đặt đúng toạ độ cũ → không nhảy văn bản, vẫn sửa được chữ trong Word |
| Word – văn bản liền mạch | Chữ chảy tự do, bảng thành bảng Word; dễ sửa nhiều nhưng có thể lệch nhẹ |
| Word – ảnh trang | Giống hệt bản gốc nhưng không sửa được chữ |
| Ảnh PNG / JPG | Mỗi trang một ảnh, chọn độ nét 150/200/300 DPI |
| TXT | Chỉ lấy chữ |

## Vì sao không bị nhảy văn bản?
Phần mềm **không chuyển cả trang sang dạng khác** mà chỉ xoá đúng chữ của dòng được sửa
(không đụng tới đường kẻ bảng, hình ảnh, chữ ký) rồi ghi chữ mới vào đúng vị trí cũ.

## Lưu ý
- **File scan** (ảnh chụp): không có chữ để sửa trực tiếp → dùng *Tẩy → Phủ trắng*, rồi *Thêm chữ*.
- **File có chữ ký số**: hình chữ ký giữ nguyên, nhưng sửa nội dung thì chữ ký số mất hiệu lực xác thực (đúng quy định PDF).
- Dòng chữ sửa dài hơn bản gốc sẽ kéo dài sang phải (không tự đẩy các dòng khác) – hãy dùng Enter để xuống dòng nếu cần.

## Build lại file exe
Đẩy toàn bộ thư mục lên GitHub → tab **Actions** → *Build SuaPDF.exe* tự chạy →
tải **SuaPDF-Windows** ở mục *Artifacts*. (Hoặc chạy `build_local.bat` trên máy Windows có Python.)
