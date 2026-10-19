# SỬA PDF OFFLINE – Hướng dẫn

*Sửa PDF offline (CopyRight@Minh-Đ1-06)*

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
- **Sửa đoạn dài như Word:** bấm vào 1 dòng là sửa **cả đoạn** (hoặc cả nội dung ô bảng); gõ dài thì chữ
  **tự xuống dòng** trong đúng bề rộng đoạn / ô. Vạch đỏ đứt nét = giới hạn dưới: nếu nhiều chữ hơn chỗ trống,
  phần mềm tự thu nhỏ cỡ chữ để **không đè lên dòng hoặc ô bên dưới** (thanh trạng thái báo cỡ chữ mới).
- **Chữ hiện sai khi bấm sửa** (vd "Trảng" thành "Trdng"): do font trong file PDF khai báo sai mã chữ.
  Phần mềm tự so hình chữ thật trên trang để sửa lại đúng (áp dụng cả khi chuyển sang Word / Excel).
- Ô *“Chỉ font có tiếng Việt”*: chỉ liệt kê font gõ được đủ dấu tiếng Việt.
- Ô *“Giữ font gốc của dòng khi sửa”*: bật nếu muốn dòng sửa dùng lại font của file gốc.
- **Ctrl+Z / Ctrl+Y**: hoàn tác / làm lại. **Ctrl + lăn chuột**: phóng to/thu nhỏ.
- Có thể kéo thả file PDF vào cửa sổ.

## Lưu (Ctrl+S) – chọn định dạng
| Định dạng | Ghi chú |
|---|---|
| **PDF** (khuyên dùng) | Giữ nguyên 100%: bảng, khung, chữ ký, con dấu không xê dịch |
| **Word – giữ nguyên bố cục, sửa được chữ** | Văn bản Word **bình thường** (không khung/text box): đoạn văn đúng vị trí, bảng Word thật (gộp ô, màu nền), chữ ký – con dấu là ảnh đặt đúng chỗ nằm dưới chữ |
| **Excel – giữ nguyên bố cục** | Mỗi trang = 1 trang tính; bảng thành ô Excel, chữ đúng vị trí, chữ ký – con dấu là ảnh đúng chỗ |
| Word – văn bản liền mạch | Chữ chảy tự do, bảng thành bảng Word; dễ sửa nhiều nhưng có thể lệch nhẹ |
| Word – ảnh trang | Giống hệt bản gốc nhưng không sửa được chữ |
| Ảnh PNG / JPG | Mỗi trang một ảnh, chọn độ nét 150/200/300 DPI |
| TXT | Chỉ lấy chữ |

## Chuyển đổi file (Ctrl+T) – PDF ↔ Word / Excel
Bấm nút **Chuyển đổi** → chọn kiểu → thêm file (chọn nhiều file hoặc kéo thả) → **▶ Chuyển đổi**.

| Kiểu | Cách làm | Giữ nguyên |
|---|---|---|
| PDF → Word | Văn bản Word bình thường, bảng Word thật | bảng, ô gộp, màu nền, chữ ký, con dấu tròn, vị trí chữ |
| PDF → Excel | Bảng thành ô Excel, mỗi trang 1 trang tính | bảng, ô gộp, viền, màu nền, chữ ký, con dấu |
| Word → PDF | Dùng **Microsoft Word** trên máy (hoặc WPS / LibreOffice) | 100% như khi in từ Word |
| Excel → PDF | Dùng **Microsoft Excel** trên máy (hoặc WPS / LibreOffice) | 100% như khi in từ Excel |

- 🔒 **File gốc chỉ được đọc, không bị sửa** (chuyển từ bản sao tạm). Kết quả luôn là file mới, trùng tên thì tự thêm (1), (2)...
- Word/Excel → PDF cần máy có cài Microsoft Office, WPS Office hoặc LibreOffice (phần mềm tự dò, báo ngay trong hộp thoại).
- PDF đang mở trong phần mềm sẽ được chuyển **kèm cả phần vừa sửa** chưa lưu.
- **Đề thi, tài liệu có công thức (toán, hoá, lý) → Word:** chữ là văn bản Word gõ sửa được; chỉ số trên/dưới
  (Pb²⁺, CH₃, 10⁻³¹) là chỉ số thật của Word; công thức xếp tầng (phân số, vectơ, căn, ngoặc lớn) là ảnh nét cao đặt
  đúng chỗ trong dòng; đáp án A/B/C/D dàn bằng phím Tab; mỗi dòng xuống hàng đúng như bản gốc (ngắt dòng mềm)
  nên **không chạy chữ, không tràn trang**; chữ đầu/chân trang (số trang, "Trang x/y") nằm trong Header/Footer.
- **PDF scan đã có sẵn lớp chữ** (máy scan tự nhận dạng): phần mềm nhận ra đây là bản scan, chỉ đưa **chữ gõ được**
  vào Word, không giữ ảnh chụp chứa chữ → hết cảnh chữ chồng lên nhau, không cần xoá khung/ảnh.
- **PDF scan (file ảnh) → Word:** phần mềm tự **nhận dạng chữ tiếng Việt (OCR)** ngay trên máy, không cần mạng
  (khoảng 5 giây/trang). Kết quả là văn bản Word **gõ sửa được như bình thường** – không có khung text box:
  đoạn văn, bảng Word thật dựng lại từ đường kẻ trên ảnh, trang nghiêng được tự chỉnh thẳng;
  con dấu đỏ, chữ ký, logo giữ nguyên là ảnh đặt đúng chỗ. Nên dò lại chữ vì OCR có thể sai vài chữ
  (nhất là chỗ con dấu đè lên chữ hoặc bản scan mờ).
- **Chuyển nhiều file cùng lúc:** thêm bao nhiêu file cũng được → mỗi file gốc ra **1 file kết quả riêng, cùng tên**.
  Xong sẽ báo: *"Đã chuyển thành công X/Y file"*, số trang trống đã xoá và file nào bị lỗi (nếu có).
- **Tự xoá trang trống** (bật sẵn, bỏ chọn nếu không muốn): Word/Excel → PDF xoá trang trắng trong PDF tạo ra;
  PDF → Word/Excel bỏ qua trang trắng của PDF. Trang chỉ còn số trang ở chân trang cũng tính là trống;
  trang còn bất kỳ chữ nào (kể cả "./.") hoặc hình, chữ ký, con dấu thì **luôn được giữ**.
- Bản Word: phần chữ nằm song song (Tên cơ quan | Quốc hiệu, Nơi nhận | Chữ ký) được đặt trong **bảng ẩn viền**
  giống cách soạn công văn trong Word; chữ ký, con dấu nằm dưới chữ nên bấm vào chữ để sửa không bị vướng ảnh.
- Sau khi chuyển sang PDF có nút **"Mở PDF vừa tạo để sửa"**.

## Văn bản soạn bằng font cũ .VnTime (TCVN3) / VNI-Times
PDF xuất từ văn bản dùng font .VnTime, .VnTimeH, .VnArial (bảng mã TCVN3/ABC) hoặc VNI-Times: phần mềm tự đổi chữ
sang Unicode → khi bấm sửa hiện đúng tiếng Việt (không còn kiểu "Céng hoµ x· héi"), chữ mới viết bằng
Times New Roman (Unicode); chuyển Word / Excel / TXT và tách văn bản cũng đọc đúng chữ.
Gõ bằng Unikey để bảng mã TCVN3 hoặc "Unicode tổ hợp" cũng tự đổi về Unicode chuẩn.
(Nên để Unikey bảng mã **Unicode** khi dùng phần mềm này.)

## Gộp PDF (Ctrl+G) – gộp nhiều file PDF thành 1 file
Bấm **Gộp PDF** → **Thêm file...** (hoặc kéo thả nhiều file vào) → sắp thứ tự bằng **▲ Lên / ▼ Xuống**,
kéo thả trong danh sách hoặc **Sắp xếp theo tên** → **Gộp & lưu...** → chọn tên file kết quả.
- Các file gốc chỉ được đọc, **không bị thay đổi**; không cho lưu đè lên file gốc; trùng tên tự thêm (1), (2)...
- Trang được chép nguyên (chữ, bảng, chữ ký, con dấu, ảnh scan không bị nén lại).
- Có mục lục (bookmark) theo tên từng file để nhảy nhanh; file có mật khẩu / hỏng sẽ được bỏ qua và báo lại.

## Tách văn bản (Ctrl+L) – file PDF scan gộp nhiều văn bản
Bấm **Tách văn bản** → chọn file PDF gộp (hoặc dùng file đang mở) → phần mềm tự phân tích từng trang:
- **Trang đầu mỗi văn bản** (ô xanh "▶ VĂN BẢN n"): nhận biết theo **Quốc hiệu** ở đầu trang
  (PDF có chữ: đọc chữ "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"; PDF scan: nhận ra gạch chân dưới
  "Độc lập - Tự do - Hạnh phúc"). Văn bản 1 trang, 2 trang hay nhiều trang đều tách đúng.
- **Trang trống** (ô xám): tự bỏ. Chỉ trang có **từ 1 dòng chữ trở lên** mới được giữ; trang không có chữ,
  chỉ có số trang, chữ hoặc dấu đỏ **in lem / hằn từ trang khác** sang, bụi, bóng mép giấy → bỏ.
- Trang có **số trang ở giữa phía trên** (trang 2, 3...) luôn được coi là trang tiếp theo – không bị tách nhầm;
  Quốc hiệu phải đi cặp với tên cơ quan bên trái (hoặc căn giữa trang như đơn từ). Rê chuột lên trang để xem lý do.
- Máy nhận sai? **Bấm vào trang** để đặt / bỏ chỗ bắt đầu văn bản; **chuột phải** để đánh dấu trang trống / giữ trang.
- Cách khác: *Theo trang trống* (trang trắng ngăn cách văn bản) hoặc *Cố định N trang mỗi văn bản*.
- **✂ Tách & lưu** → mỗi văn bản 1 file, **tự đặt tên theo nội dung văn bản**:
  - Có trích yếu "V/v ..." (hoặc "Về việc ...") → lấy trích yếu + ngày dưới Quốc hiệu, **không dấu, chữ thường**,
    vd `V/v số hóa hồ sơ` → **`so hoa ho so ngay 19.10.2026.pdf`**
  - Không có trích yếu → lấy tên văn bản (BÁO CÁO, TỜ TRÌNH, KẾ HOẠCH...) + dòng ngay dưới + ngày, vd
    BÁO CÁO / Công tác số hóa năm 2026 → **`bao cao cong tac so hoa nam 2026 ngay 19.10.2026.pdf`**
  - Dòng Quốc hiệu "Cộng hòa xã hội chủ nghĩa Việt Nam" không bao giờ bị lấy làm tên.
  - Bản scan: tự nhận dạng chữ phần đầu trang. Không đọc được tiêu đề thì đặt `TênGốc_VB01.pdf`...
  Lưu trong thư mục `TênGốc_tach`,
  rồi báo: *"Đã tách thành công N văn bản (tổng X trang), đã bỏ Y trang trống"*.
- File gốc không bị sửa; ảnh scan được chép nguyên, không giảm chất lượng.

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
