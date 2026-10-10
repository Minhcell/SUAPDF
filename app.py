# -*- coding: utf-8 -*-
"""
SỬA PDF OFFLINE – mở PDF, sửa / đánh thêm chữ như Word, chọn font + cỡ chữ,
lưu ra PDF / Word / ảnh / TXT mà không làm xô lệch bảng, khung, chữ ký.
"""
import os
import sys
import traceback

from PyQt5.QtCore import Qt, QRectF, QPointF, QTimer, QThread, pyqtSignal, QSize
from PyQt5.QtGui import (QImage, QPixmap, QPen, QColor, QBrush, QFont, QFontMetricsF,
                         QKeySequence, QIcon, QPainter)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsRectItem, QPlainTextEdit, QGraphicsProxyWidget, QFileDialog, QMessageBox,
    QToolBar, QAction, QActionGroup, QComboBox, QLabel, QSpinBox, QToolButton,
    QColorDialog, QListWidget, QListWidgetItem, QDockWidget, QDialog, QVBoxLayout,
    QHBoxLayout, QRadioButton, QButtonGroup, QDialogButtonBox, QCheckBox, QProgressDialog,
    QInputDialog, QMenu, QFrame, QWidget, QCompleter, QStyle, QScrollArea, QGridLayout)

# bản exe không có cửa sổ console: tránh lỗi khi thư viện ghi log ra stdout
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import core
from core import fitz

APP_TITLE = "Sửa PDF Offline"
VERSION = "1.0"


def pix_to_qimage(pm):
    img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888)
    return img.copy()


# =============================================================================
#  Ô SOẠN CHỮ NỔI TRÊN TRANG
# =============================================================================
SUPER = 4.0  # widget vẽ to gấp 4 rồi thu nhỏ -> cỡ chữ chính xác đến 0.25pt


class InlineEditor(QPlainTextEdit):
    commit = pyqtSignal()
    cancel = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.document().setDocumentMargin(0)
        self.setStyleSheet("QPlainTextEdit{background:rgba(255,255,230,245);"
                           "border:%dpx dashed #1e6fd9;}" % int(SUPER))
        self.textChanged.connect(self.fit)
        self.min_w = 40

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancel.emit()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier:
            self.commit.emit()
            return
        super().keyPressEvent(e)

    def set_style(self, family, size_pt, bold, italic, color):
        f = QFont(family)
        f.setPixelSize(max(1, int(round(size_pt * SUPER))))
        f.setBold(bold)
        f.setItalic(italic)
        self.setFont(f)
        c = QColor.fromRgbF(*color)
        pal = self.palette()
        pal.setColor(pal.Text, c)
        self.setPalette(pal)
        self.fit()

    def fit(self):
        fm = QFontMetricsF(self.font())
        lines = self.toPlainText().split("\n") or [""]
        w = max([fm.horizontalAdvance(t) for t in lines] + [self.min_w]) + fm.averageCharWidth() * 2 + 4 * SUPER
        h = fm.lineSpacing() * max(1, len(lines)) + 4 * SUPER
        self.resize(int(w), int(h))


# =============================================================================
#  KHUNG XEM TRANG
# =============================================================================
MODE_EDIT, MODE_ADD, MODE_ERASE = range(3)


class PageView(QGraphicsView):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QColor("#5f6b7a"))
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.page_item = None
        self.hover = None
        self.band = None
        self.band_start = None
        self.proxy = None
        self.editor = None
        self.edit_ctx = None  # ('line', Line) | ('add', x, top)
        self.opened_style = None
        self.cover = None

    # ---- hiển thị
    def show_page(self, pixmap, page_rect, scale_px):
        self.close_editor(commit=False)
        sc = self.scene()
        sc.clear()
        self.hover = self.band = None
        border = sc.addRect(QRectF(2, 2, page_rect.width, page_rect.height), QPen(Qt.NoPen), QBrush(QColor(0, 0, 0, 70)))
        border.setZValue(-1)
        self.page_item = QGraphicsPixmapItem(pixmap)
        self.page_item.setTransformationMode(Qt.SmoothTransformation)
        self.page_item.setScale(1.0 / scale_px)
        sc.addItem(self.page_item)
        sc.setSceneRect(QRectF(-20, -20, page_rect.width + 40, page_rect.height + 40))

    def set_zoom(self, z):
        self.resetTransform()
        self.scale(z, z)

    # ---- chuột
    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.win.zoom_step(1 if e.angleDelta().y() > 0 else -1)
            return
        sb = self.verticalScrollBar()
        before = sb.value()
        super().wheelEvent(e)
        if self.editor is None and sb.value() == before:
            if e.angleDelta().y() < 0 and before >= sb.maximum():
                if self.win.go_page(self.win.cur + 1):
                    self.verticalScrollBar().setValue(0)
            elif e.angleDelta().y() > 0 and before <= sb.minimum():
                if self.win.go_page(self.win.cur - 1):
                    self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def mouseMoveEvent(self, e):
        p = self.mapToScene(e.pos())
        if self.band_start is not None and self.band is not None:
            self.band.setRect(QRectF(self.band_start, p).normalized())
            return
        if self.win.mode == MODE_EDIT and self.win.pdf and self.editor is None:
            ln = self.win.pdf.line_at(self.win.cur, p.x(), p.y())
            if ln:
                r = QRectF(ln.bbox.x0 - 1, ln.bbox.y0 - 1, ln.bbox.width + 2, ln.bbox.height + 2)
                if self.hover is None:
                    self.hover = self.scene().addRect(r, QPen(QColor("#1e6fd9"), 0), QBrush(QColor(30, 111, 217, 35)))
                    self.hover.setZValue(5)
                else:
                    self.hover.setRect(r)
                    self.hover.show()
                self.viewport().setCursor(Qt.IBeamCursor)
            else:
                if self.hover:
                    self.hover.hide()
                self.viewport().setCursor(Qt.ArrowCursor)
        elif self.win.mode == MODE_ADD:
            self.viewport().setCursor(Qt.IBeamCursor)
        elif self.win.mode == MODE_ERASE:
            self.viewport().setCursor(Qt.CrossCursor)
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if self.editor is not None:
            item = self.itemAt(e.pos())
            if item is self.proxy:
                super().mousePressEvent(e)
                return
            self.close_editor(commit=True)
            return
        if not self.win.pdf or e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        p = self.mapToScene(e.pos())
        pr = self.win.page_rect()
        if not (0 <= p.x() <= pr.width and 0 <= p.y() <= pr.height):
            return
        if self.win.mode == MODE_EDIT:
            ln = self.win.pdf.line_at(self.win.cur, p.x(), p.y())
            if ln:
                if not ln.horizontal:
                    self.win.status("Dòng chữ này bị xoay dọc – chưa hỗ trợ sửa trực tiếp. Hãy dùng Tẩy + Thêm chữ.")
                    return
                self.open_editor_line(ln)
            else:
                self.win.status("Không có chữ ở đây. Bấm nút 'Thêm chữ' (F3) để gõ chữ mới vào chỗ trống.")
        elif self.win.mode == MODE_ADD:
            self.open_editor_add(p.x(), p.y() - self.win.cur_size() * 0.5)
        elif self.win.mode == MODE_ERASE:
            self.band_start = p
            self.band = self.scene().addRect(QRectF(p, p), QPen(QColor("#d93025"), 0, Qt.DashLine),
                                             QBrush(QColor(217, 48, 37, 40)))
            self.band.setZValue(6)

    def mouseReleaseEvent(self, e):
        if self.band_start is not None and self.band is not None:
            r = self.band.rect()
            self.scene().removeItem(self.band)
            self.band = None
            self.band_start = None
            if r.width() > 2 and r.height() > 2:
                self.win.erase_area(r, self.mapToGlobal(e.pos()))
            return
        super().mouseReleaseEvent(e)

    # ---- ô soạn
    def _make_editor(self, x, top, text, family, size, bold, italic, color, min_w):
        ed = InlineEditor()
        ed.min_w = min_w * SUPER
        ed.set_style(family, size, bold, italic, color)
        ed.setPlainText(text)
        ed.commit.connect(lambda: self.close_editor(True))
        ed.cancel.connect(lambda: self.close_editor(False))
        self.proxy = self.scene().addWidget(ed)
        self.proxy.setScale(1.0 / SUPER)
        self.proxy.setZValue(10)
        pad = 2 * SUPER / SUPER
        self.proxy.setPos(x - pad, top - pad)
        self.editor = ed
        ed.fit()
        ed.setFocus()
        cur = ed.textCursor()
        cur.movePosition(cur.End)
        ed.setTextCursor(cur)
        if self.hover:
            self.hover.hide()
        self.win.editing_changed(True)

    def open_editor_line(self, ln):
        w = self.win
        # font mặc định Times New Roman, giữ cỡ chữ / đậm / nghiêng / màu của chữ gốc
        w.load_style_from_line(ln)
        self.edit_ctx = ("line", ln)
        self.opened_style = w.cur_style()
        fam = w.cur_family()
        top = ln.origin.y - ln.ascender * ln.size
        self._make_editor(ln.origin.x, top, ln.text, fam, w.cur_size(), w.cur_bold(), w.cur_italic(),
                          w.cur_color, ln.bbox.width)
        # che chữ cũ trong lúc sửa
        r = QRectF(ln.bbox.x0, ln.bbox.y0, ln.bbox.width, ln.bbox.height)
        self.cover = self.scene().addRect(r, QPen(Qt.NoPen), QBrush(QColor(255, 255, 255)))
        self.cover.setZValue(4)
        w.status(("[Bản scan: vùng chữ cũ sẽ được phủ trắng] " if ln.invisible else "") + "Đang sửa dòng. Gõ chữ như Word – Enter: xuống dòng | Ctrl+Enter hoặc bấm ra ngoài: xong | Esc: huỷ")

    def open_editor_add(self, x, top):
        w = self.win
        self.edit_ctx = ("add", x, top)
        self.cover = None
        self._make_editor(x, top, "", w.cur_family(), w.cur_size(), w.cur_bold(), w.cur_italic(), w.cur_color, 60)
        w.status("Gõ chữ mới – Enter: xuống dòng | Ctrl+Enter hoặc bấm ra ngoài: xong | Esc: huỷ")

    def restyle_editor(self):
        if self.editor:
            w = self.win
            self.editor.set_style(w.cur_family(), w.cur_size(), w.cur_bold(), w.cur_italic(), w.cur_color)

    def close_editor(self, commit=True):
        if self.editor is None:
            return
        ed, ctx = self.editor, self.edit_ctx
        text = ed.toPlainText()
        self.editor = None
        self.edit_ctx = None
        try:
            self.scene().removeItem(self.proxy)
        except Exception:
            pass
        self.proxy = None
        if getattr(self, "cover", None) is not None:
            try:
                self.scene().removeItem(self.cover)
            except Exception:
                pass
            self.cover = None
        try:
            ed.deleteLater()
        except RuntimeError:
            pass
        self.win.editing_changed(False)
        if commit:
            self.win.apply_edit(ctx, text)


# =============================================================================
#  HỘP THOẠI LƯU
# =============================================================================
SAVE_OPTIONS = [
    ("pdf", "PDF (.pdf) – giữ nguyên 100% như bản gốc (khuyên dùng)",
     "Bảng, khung, đường kẻ, hình ảnh, chữ ký giữ nguyên vị trí. Chỉ những dòng bạn sửa được thay chữ.", ".pdf"),
    ("docx_layout", "Word (.docx) – giữ nguyên bố cục, sửa được chữ",
     "Văn bản Word BÌNH THƯỜNG (không khung/text box): đoạn văn đặt đúng vị trí cũ, bảng thành bảng Word thật "
     "(gộp ô, màu nền, viền), chữ ký và con dấu là ảnh đặt đúng chỗ, nằm dưới chữ. Gõ thêm chữ chảy như Word.", ".docx"),
    ("docx_flow", "Word (.docx) – văn bản liền mạch (chuyển đổi tự động)",
     "Chữ chảy tự do như Word gõ tay, bảng thành bảng Word. Dễ sửa nhiều nhưng CÓ THỂ lệch nhẹ "
     "so với PDF gốc (nhất là khung chữ ký, con dấu).", ".docx"),
    ("docx_image", "Word (.docx) – ảnh trang (giống hệt, không sửa chữ)",
     "Mỗi trang là một ảnh nét cao đặt vào Word. Giống bản gốc tuyệt đối nhưng không sửa được chữ.", ".docx"),
    ("xlsx", "Excel (.xlsx) – giữ nguyên bố cục",
     "Mỗi trang PDF là 1 trang tính. Bảng thành ô Excel (gộp ô, viền, màu nền), chữ đặt đúng vị trí, "
     "chữ ký / con dấu tròn là ảnh đặt đúng chỗ. In ra vừa 1 trang như bản gốc.", ".xlsx"),
    ("png", "Ảnh PNG (mỗi trang 1 ảnh)", "Ảnh nét, phù hợp đính kèm/gửi Zalo.", ".png"),
    ("jpg", "Ảnh JPG (mỗi trang 1 ảnh)", "Ảnh nhẹ hơn PNG.", ".jpg"),
    ("txt", "Văn bản thuần (.txt)", "Chỉ lấy chữ, không giữ định dạng.", ".txt"),
]


class SaveDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Lưu file – chọn định dạng")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        t = QLabel("<b>Chọn định dạng muốn lưu:</b>")
        lay.addWidget(t)
        self.group = QButtonGroup(self)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setMinimumHeight(64)
        self.desc.setStyleSheet("QLabel{background:#eef4ff;border:1px solid #c5d6f5;padding:8px;border-radius:4px;}")
        for i, (key, label, desc, ext) in enumerate(SAVE_OPTIONS):
            rb = QRadioButton(label)
            rb.setProperty("key", key)
            if i == 0:
                rb.setChecked(True)
                f = rb.font(); f.setBold(True); rb.setFont(f)
            self.group.addButton(rb, i)
            lay.addWidget(rb)
        lay.addSpacing(6)
        lay.addWidget(self.desc)
        row = QHBoxLayout()
        row.addWidget(QLabel("Độ nét ảnh (DPI):"))
        self.dpi = QComboBox()
        self.dpi.addItems(["150", "200", "300"])
        self.dpi.setCurrentText("200")
        row.addWidget(self.dpi)
        row.addStretch(1)
        lay.addLayout(row)
        self.open_after = QCheckBox("Mở file sau khi lưu")
        self.open_after.setChecked(True)
        lay.addWidget(self.open_after)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Lưu...")
        bb.button(QDialogButtonBox.Cancel).setText("Huỷ")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.group.buttonClicked.connect(self.update_desc)
        self.update_desc()

    def update_desc(self, *_):
        i = self.group.checkedId()
        key, label, desc, ext = SAVE_OPTIONS[i]
        self.desc.setText(desc)
        self.dpi.setEnabled(key in ("docx_layout", "docx_image", "xlsx", "png", "jpg"))

    def choice(self):
        return SAVE_OPTIONS[self.group.checkedId()], int(self.dpi.currentText()), self.open_after.isChecked()


class Worker(QThread):
    done = pyqtSignal(object, str)
    prog = pyqtSignal(int, int)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            r = self.fn(lambda a, b: self.prog.emit(a, b))
            self.done.emit(r, "")
        except Exception:
            self.done.emit(None, traceback.format_exc())



# =============================================================================
#  HỘP THOẠI CHUYỂN ĐỔI  PDF <-> WORD / EXCEL
# =============================================================================
class ConvertWorker(QThread):
    line = pyqtSignal(str)
    prog = pyqtSignal(int, int)
    result = pyqtSignal(list)

    def __init__(self, mode, items, out_dir, word_style, dpi, remove_blank=True):
        super().__init__()
        self.mode, self.items, self.out_dir = mode, items, out_dir
        self.word_style, self.dpi = word_style, dpi
        self.remove_blank = remove_blank
        self.n_fail = 0
        self.n_blank = 0

    def run(self):
        import convert
        outs = []
        n = len(self.items)
        for i, (src, doc) in enumerate(self.items):
            self.prog.emit(i, n)
            self.line.emit("⏳ %s ..." % os.path.basename(src))
            try:
                st = {}
                out, engine = convert.convert_file(self.mode, src, self.out_dir, self.word_style,
                                                   self.dpi, doc=doc, remove_blank=self.remove_blank,
                                                   stats=st)
                outs.append(out)
                nb = st.get("blank", 0)
                self.n_blank += nb
                self.line.emit("✔ [%d/%d] Xong: %s   (dùng %s%s)" % (
                    i + 1, n, out, engine, (", đã xoá %d trang trống" % nb) if nb else ""))
            except Exception as ex:
                self.n_fail += 1
                msg = str(ex).strip() or type(ex).__name__
                self.line.emit("✖ [%d/%d] LỖI %s:\n   %s" % (i + 1, n, os.path.basename(src), msg.replace("\n", "\n   ")))
        self.prog.emit(n, n)
        self.result.emit(outs)


class ConvertDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        import convert
        self.convert = convert
        self.win = win
        self.outs = []
        self.setWindowTitle("Chuyển đổi file – PDF ↔ Word / Excel")
        self.setAcceptDrops(True)
        # Khung gọn: phần nội dung cuộn được, hàng nút chức năng luôn nằm cố định ở đáy
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(4)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        self.scroll = scroll

        lay.addWidget(QLabel("<b>1. Chọn kiểu chuyển đổi:</b>"))
        row = QGridLayout()
        row.setHorizontalSpacing(16)
        row.setVerticalSpacing(2)
        self.mode_group = QButtonGroup(self)
        for i, (key, label, exts, out_ext) in enumerate(convert.MODES):
            rb = QRadioButton(label)
            rb.setProperty("key", key)
            self.mode_group.addButton(rb, i)
            row.addWidget(rb, i // 2, i % 2)
        row.setColumnStretch(2, 1)
        lay.addLayout(row)
        self.word_row = QHBoxLayout()
        self.word_row.addWidget(QLabel("   Kiểu Word:"))
        self.word_style = QComboBox()
        self.word_style.addItem("Giữ nguyên bố cục – văn bản Word bình thường (khuyên dùng)", "layout")
        self.word_style.addItem("Liền mạch – chuyển đổi tự động (có thể lệch nhẹ)", "flow")
        self.word_row.addWidget(self.word_style, 1)
        lay.addLayout(self.word_row)
        self.engine_lbl = QLabel()
        self.engine_lbl.setWordWrap(True)
        lay.addWidget(self.engine_lbl)

        lay.addWidget(QLabel("<b>2. Chọn file</b> (có thể chọn nhiều file, hoặc kéo thả file vào đây):"))
        self.files = QListWidget()
        self.files.setSelectionMode(QListWidget.ExtendedSelection)
        self.files.setMinimumHeight(52)
        self.files.setMaximumHeight(90)
        lay.addWidget(self.files)
        fr = QHBoxLayout()
        b_add = QToolButton(); b_add.setText(" Thêm file... "); b_add.clicked.connect(self.add_files)
        b_rm = QToolButton(); b_rm.setText(" Bỏ file đã chọn "); b_rm.clicked.connect(self.remove_sel)
        b_clr = QToolButton(); b_clr.setText(" Xoá danh sách "); b_clr.clicked.connect(self.files.clear)
        for b in (b_add, b_rm, b_clr):
            fr.addWidget(b)
        fr.addStretch(1)
        lay.addLayout(fr)

        lay.addWidget(QLabel("<b>3. Nơi lưu file kết quả:</b>"))
        orow = QHBoxLayout()
        self.same_dir = QCheckBox("Cùng thư mục với file gốc")
        self.same_dir.setChecked(True)
        self.out_lbl = QLabel("")
        b_dir = QToolButton(); b_dir.setText(" Chọn thư mục khác... "); b_dir.clicked.connect(self.pick_dir)
        self.same_dir.toggled.connect(lambda on: self.out_lbl.setText("" if on else self.out_dir))
        orow.addWidget(self.same_dir)
        orow.addWidget(b_dir)
        orow.addWidget(self.out_lbl, 1)
        lay.addLayout(orow)
        self.out_dir = win.last_dir
        self.remove_blank = QCheckBox("Tự xoá trang trống trong file kết quả")
        self.remove_blank.setChecked(True)
        self.remove_blank.setToolTip("Word/Excel → PDF: xoá trang trắng trong PDF tạo ra.\n"
                                     "PDF → Word/Excel: bỏ qua trang trắng của PDF (file gốc không đổi).")
        lay.addWidget(self.remove_blank)
        note = QLabel("🔒 File gốc chỉ được đọc, KHÔNG bị sửa. Kết quả luôn là file mới "
                      "(trùng tên thì tự thêm (1), (2)...).")
        note.setStyleSheet("QLabel{background:#eef8ee;border:1px solid #b9dfb9;padding:6px;border-radius:4px;}")
        note.setWordWrap(True)
        lay.addWidget(note)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(50)
        self.log.setMaximumHeight(90)
        lay.addWidget(self.log)
        lay.addStretch(1)
        bb = QHBoxLayout()
        self.b_go = QToolButton(); self.b_go.setText("  ▶ Chuyển đổi  ")
        f = self.b_go.font(); f.setBold(True); self.b_go.setFont(f)
        self.b_go.clicked.connect(self.start)
        self.b_folder = QToolButton(); self.b_folder.setText(" Mở thư mục kết quả ")
        self.b_folder.clicked.connect(self.open_folder)
        self.b_edit = QToolButton(); self.b_edit.setText(" Mở PDF vừa tạo để sửa ")
        self.b_edit.clicked.connect(self.edit_result)
        b_close = QToolButton(); b_close.setText(" Đóng "); b_close.clicked.connect(self.reject)
        for b in (self.b_go, self.b_folder, self.b_edit):
            bb.addWidget(b)
        bb.addStretch(1)
        bb.addWidget(b_close)
        outer.addLayout(bb)  # hàng nút ngoài vùng cuộn -> luôn nhìn thấy
        self.b_folder.setEnabled(False)
        self.b_edit.setEnabled(False)

        self.mode_group.buttonClicked.connect(lambda *_: self.mode_changed())
        self.mode_group.button(0).setChecked(True)
        self.mode_changed()
        self._fit_screen()

    def _fit_screen(self):
        """Kích thước gọn và luôn nằm trọn trong màn hình (kể cả màn hình nhỏ / phóng to 125-150%)."""
        w, h = 620, 500
        try:
            scr = (self.parent().screen() if self.parent() is not None and hasattr(self.parent(), "screen")
                   else QApplication.primaryScreen())
            ag = scr.availableGeometry()
            w = min(w, ag.width() - 40)
            h = min(h, ag.height() - 80)
            self.resize(max(420, w), max(300, h))
            g = self.frameGeometry()
            g.moveCenter(ag.center())
            self.move(max(ag.left(), g.left()), max(ag.top(), g.top()))
        except Exception:
            self.resize(w, h)

    def mode(self):
        return self.convert.MODES[self.mode_group.checkedId()]

    def mode_changed(self):
        key, label, exts, out_ext = self.mode()
        is_word = key == "pdf2word"
        for i in range(self.word_row.count()):
            w = self.word_row.itemAt(i).widget()
            if w:
                w.setVisible(is_word)
        if key in ("word2pdf", "excel2pdf"):
            kind = "word" if key == "word2pdf" else "excel"
            eng = self.convert.detect_engines(kind)
            if eng:
                self.engine_lbl.setText("Sẽ dùng: <b>%s</b> trên máy để chuyển → giữ đúng 100%% bố cục "
                                        "như khi in từ %s." % (eng[0], "Word" if kind == "word" else "Excel"))
                self.engine_lbl.setStyleSheet("color:#1a6b1a")
            else:
                self.engine_lbl.setText("⚠ Máy chưa thấy Microsoft Office / WPS / LibreOffice. Cần cài một trong các "
                                        "chương trình này để chuyển %s sang PDF đúng bố cục."
                                        % ("Word" if kind == "word" else "Excel"))
                self.engine_lbl.setStyleSheet("color:#b3261e")
        elif key == "pdf2excel":
            self.engine_lbl.setText("Bảng → ô Excel (gộp ô, viền, màu nền); chữ đặt đúng vị trí; "
                                    "chữ ký, con dấu tròn → ảnh đặt đúng chỗ. Mỗi trang PDF = 1 trang tính.")
            self.engine_lbl.setStyleSheet("color:#333")
        else:
            self.engine_lbl.setText("Văn bản Word bình thường: đoạn văn đúng vị trí, bảng Word thật, "
                                    "chữ ký / con dấu là ảnh đặt đúng chỗ (nằm dưới chữ).")
            self.engine_lbl.setStyleSheet("color:#333")
        # giữ lại các file hợp lệ với kiểu mới
        keep = []
        for i in range(self.files.count()):
            it = self.files.item(i)
            if os.path.splitext(it.data(Qt.UserRole))[1].lower() in exts:
                keep.append((it.text(), it.data(Qt.UserRole), it.data(Qt.UserRole + 1)))
        self.files.clear()
        for t, p, cur in keep:
            self._add_item(p, cur)
        if not keep and key in ("pdf2word", "pdf2excel") and self.win.pdf:
            self._add_item(self.win.pdf.path, True)

    def _add_item(self, path, current=False):
        for i in range(self.files.count()):
            if self.files.item(i).data(Qt.UserRole) == path:
                return
        it = QListWidgetItem(path + ("   (đang mở – gồm cả phần đã sửa)" if current else ""))
        it.setData(Qt.UserRole, path)
        it.setData(Qt.UserRole + 1, bool(current))
        self.files.addItem(it)

    def add_files(self):
        key, label, exts, out_ext = self.mode()
        pat = " ".join("*" + e for e in exts)
        name = {"pdf2word": "PDF", "pdf2excel": "PDF", "word2pdf": "Word", "excel2pdf": "Excel"}[key]
        paths, _ = QFileDialog.getOpenFileNames(self, "Chọn file %s" % name, self.win.last_dir,
                                                "%s (%s)" % (name, pat))
        for p in paths:
            self._add_item(os.path.normpath(p))
        if paths:
            self.win.last_dir = os.path.dirname(paths[0])

    def remove_sel(self):
        for it in self.files.selectedItems():
            self.files.takeItem(self.files.row(it))

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu kết quả", self.out_dir)
        if d:
            self.out_dir = d
            self.same_dir.setChecked(False)
            self.out_lbl.setText(d)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        key, label, exts, out_ext = self.mode()
        bad = 0
        for u in e.mimeData().urls():
            p = os.path.normpath(u.toLocalFile())
            if os.path.splitext(p)[1].lower() in exts:
                self._add_item(p)
            else:
                bad += 1
        if bad:
            self.log.appendPlainText("Bỏ qua %d file không đúng loại cho kiểu '%s'." % (bad, label))

    def start(self):
        if self.files.count() == 0:
            QMessageBox.information(self, APP_TITLE, "Hãy thêm ít nhất 1 file.")
            return
        key = self.mode()[0]
        items = []
        for i in range(self.files.count()):
            it = self.files.item(i)
            p = it.data(Qt.UserRole)
            doc = None
            if it.data(Qt.UserRole + 1) and self.win.pdf:
                self.win.view.close_editor(True)
                doc = core.fitz.open(stream=self.win.pdf.doc.tobytes(), filetype="pdf")
            items.append((p, doc))
        out_dir = None if self.same_dir.isChecked() else self.out_dir
        self.b_go.setEnabled(False)
        self.log.appendPlainText("— Bắt đầu chuyển %d file —" % len(items))
        self.scroll.ensureWidgetVisible(self.log)
        self.prog = QProgressDialog("Đang chuyển đổi...", None, 0, len(items), self)
        self.prog.setWindowTitle(APP_TITLE)
        self.prog.setWindowModality(Qt.WindowModal)
        self.prog.setMinimumDuration(0)
        self.worker = ConvertWorker(key, items, out_dir, self.word_style.currentData(), 200,
                                    self.remove_blank.isChecked())
        self.worker.line.connect(self.log.appendPlainText)
        self.worker.prog.connect(lambda a, b: (self.prog.setMaximum(b), self.prog.setValue(a)))
        self.worker.result.connect(self.done)
        self.worker.start()

    def done(self, outs):
        self.prog.close()
        self.b_go.setEnabled(True)
        self.outs = outs
        total = len(self.worker.items)
        nfail = total - len(outs)
        nblank = self.worker.n_blank
        self.log.appendPlainText("— Hoàn tất: %d/%d file —" % (len(outs), total))
        self.b_folder.setEnabled(bool(outs))
        self.b_edit.setEnabled(any(o.lower().endswith(".pdf") for o in outs))
        # báo kết quả tổng
        msg = "Đã chuyển thành công <b>%d/%d</b> file." % (len(outs), total)
        msg += "<br>Mỗi file gốc → 1 file kết quả riêng, cùng tên."
        if nblank:
            msg += "<br>Đã tự xoá <b>%d</b> trang trống." % nblank
        if nfail:
            msg += "<br><span style='color:#b3261e'>Lỗi: <b>%d</b> file – xem chi tiết trong ô nhật ký.</span>" % nfail
        box = QMessageBox(QMessageBox.Information if not nfail else QMessageBox.Warning,
                          "Kết quả chuyển đổi", msg, QMessageBox.Ok, self)
        box.setTextFormat(Qt.RichText)
        box.exec_()

    def open_folder(self):
        if not self.outs:
            return
        p = self.outs[-1]
        try:
            if sys.platform.startswith("win"):
                import subprocess
                subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", os.path.dirname(p)])
        except Exception:
            pass

    def edit_result(self):
        pdfs = [o for o in self.outs if o.lower().endswith(".pdf")]
        if pdfs and self.win.confirm_discard():
            self.accept()
            self.win.open_file(pdfs[-1])

# =============================================================================
#  CỬA SỔ CHÍNH
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self, fonts):
        super().__init__()
        self.fm = core.FontManager(fonts)
        self.pdf = None
        self.cur = 0
        self.zoom = 1.0
        self.mode = MODE_EDIT
        self.cur_color = (0, 0, 0)
        self.last_dir = os.path.expanduser("~")
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 860)

        self.view = PageView(self)
        self.setCentralWidget(self.view)
        self._build_toolbars()
        self._build_thumbs()
        self.statusBar().showMessage("Mở file PDF (Ctrl+O) hoặc kéo thả file vào cửa sổ.")
        self.page_lbl = QLabel()
        self.statusBar().addPermanentWidget(self.page_lbl)
        self.setAcceptDrops(True)
        self._rerender = QTimer(self, singleShot=True, interval=120, timeout=self.render_page)
        self.update_actions()

    # ------------------------------------------------------------------ UI
    def _act(self, text, slot, shortcut=None, tip=None, icon=None, checkable=False):
        a = QAction(text, self)
        if icon is not None:
            a.setIcon(self.style().standardIcon(icon))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setToolTip((tip or text) + (" (%s)" % shortcut if shortcut else ""))
        a.setCheckable(checkable)
        if slot:
            a.triggered.connect(slot)
        return a

    def _build_toolbars(self):
        tb = QToolBar("Tệp")
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setMovable(False)
        self.addToolBar(tb)
        self.a_open = self._act("Mở PDF", self.open_dialog, "Ctrl+O", icon=QStyle.SP_DialogOpenButton)
        self.a_save = self._act("Lưu", self.save_dialog, "Ctrl+S", "Lưu – chọn định dạng PDF, Word, ảnh...",
                                icon=QStyle.SP_DialogSaveButton)
        self.a_undo = self._act("Hoàn tác", self.undo, "Ctrl+Z", icon=QStyle.SP_ArrowBack)
        self.a_redo = self._act("Làm lại", self.redo, "Ctrl+Y", icon=QStyle.SP_ArrowForward)
        self.a_convert = self._act("Chuyển đổi", self.convert_dialog, "Ctrl+T",
                                   "Chuyển PDF ↔ Word / Excel, giữ nguyên bảng, chữ ký, con dấu",
                                   icon=QStyle.SP_BrowserReload)
        for a in (self.a_open, self.a_save, self.a_convert):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addAction(self.a_redo)
        tb.addSeparator()

        grp = QActionGroup(self)
        self.a_mode_edit = self._act("Sửa chữ", lambda: self.set_mode(MODE_EDIT), "F2",
                                     "Bấm vào dòng chữ có sẵn để sửa", checkable=True)
        self.a_mode_add = self._act("Thêm chữ", lambda: self.set_mode(MODE_ADD), "F3",
                                    "Bấm vào chỗ trống để gõ thêm chữ mới", checkable=True)
        self.a_mode_erase = self._act("Tẩy", lambda: self.set_mode(MODE_ERASE), "F4",
                                      "Kéo chuột khoanh vùng để xoá chữ / phủ trắng", checkable=True)
        for a in (self.a_mode_edit, self.a_mode_add, self.a_mode_erase):
            grp.addAction(a)
            tb.addAction(a)
        self.a_mode_edit.setChecked(True)
        tb.addSeparator()

        tb.addWidget(QLabel(" Trang "))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.valueChanged.connect(lambda v: self.go_page(v - 1))
        tb.addWidget(self.page_spin)
        self.page_total = QLabel(" / 0 ")
        tb.addWidget(self.page_total)
        tb.addSeparator()
        tb.addWidget(QLabel(" Thu phóng "))
        self.zoom_box = QComboBox()
        self.zoom_box.setEditable(True)
        self.zoom_box.addItems(["50%", "75%", "100%", "125%", "150%", "200%", "300%", "Vừa khung"])
        self.zoom_box.setCurrentText("100%")
        self.zoom_box.activated.connect(lambda _: self.zoom_from_box())
        self.zoom_box.lineEdit().returnPressed.connect(self.zoom_from_box)
        tb.addWidget(self.zoom_box)

        # ---- thanh định dạng
        self.addToolBarBreak()
        fb = QToolBar("Định dạng")
        fb.setMovable(False)
        self.addToolBar(fb)
        fb.addWidget(QLabel(" Font: "))
        self.font_box = QComboBox()
        self.font_box.setEditable(True)
        self.font_box.setInsertPolicy(QComboBox.NoInsert)
        self.font_box.setMinimumWidth(230)
        self.font_box.setMaxVisibleItems(25)
        fb.addWidget(self.font_box)
        self.vn_only = QCheckBox("Chỉ font có tiếng Việt")
        self.vn_only.setChecked(True)
        self.vn_only.toggled.connect(self.fill_fonts)
        fb.addWidget(self.vn_only)
        fb.addSeparator()
        fb.addWidget(QLabel(" Cỡ chữ: "))
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems([str(s) for s in (8, 9, 10, 10.5, 11, 12, 13, 14, 15, 16, 18, 20, 22, 24, 26, 28, 32, 36, 40, 48, 60, 72)])
        self.size_box.setCurrentText("13")
        self.size_box.setMinimumWidth(70)
        fb.addWidget(self.size_box)
        fb.addSeparator()
        self.b_bold = QToolButton(); self.b_bold.setText("B"); self.b_bold.setCheckable(True)
        f = self.b_bold.font(); f.setBold(True); self.b_bold.setFont(f)
        self.b_bold.setShortcut(QKeySequence("Ctrl+B")); self.b_bold.setToolTip("Đậm (Ctrl+B)")
        self.b_ital = QToolButton(); self.b_ital.setText("I"); self.b_ital.setCheckable(True)
        f = self.b_ital.font(); f.setItalic(True); self.b_ital.setFont(f)
        self.b_ital.setShortcut(QKeySequence("Ctrl+I")); self.b_ital.setToolTip("Nghiêng (Ctrl+I)")
        self.b_color = QToolButton(); self.b_color.setText(" Màu chữ "); self.b_color.clicked.connect(self.pick_color)
        for b in (self.b_bold, self.b_ital, self.b_color):
            fb.addWidget(b)
        self.keep_orig = QCheckBox("Giữ font gốc của dòng khi sửa")
        self.keep_orig.setToolTip("Bỏ chọn: dòng được sửa sẽ dùng font đang chọn (mặc định Times New Roman)")
        self.keep_orig.setChecked(False)
        fb.addSeparator()
        fb.addWidget(self.keep_orig)
        fb.addSeparator()
        self.a_apply = self._act("✔ Xong", lambda: self.view.close_editor(True), None, "Ghi chữ vào trang (Ctrl+Enter)")
        self.a_cancel = self._act("✖ Huỷ", lambda: self.view.close_editor(False), None, "Huỷ sửa (Esc)")
        fb.addAction(self.a_apply)
        fb.addAction(self.a_cancel)

        self.fill_fonts()
        self.font_box.currentTextChanged.connect(lambda _: self.view.restyle_editor())
        self.size_box.currentTextChanged.connect(lambda _: self.view.restyle_editor())
        self.b_bold.toggled.connect(lambda _: self.view.restyle_editor())
        self.b_ital.toggled.connect(lambda _: self.view.restyle_editor())

        # menu chuột phải
        m = self.menuBar()
        fm_ = m.addMenu("&Tệp")
        fm_.addAction(self.a_open)
        fm_.addAction(self.a_save)
        fm_.addAction(self.a_convert)
        fm_.addSeparator()
        fm_.addAction(self._act("Thoát", self.close, "Ctrl+Q"))
        em = m.addMenu("&Sửa")
        for a in (self.a_undo, self.a_redo, None, self.a_mode_edit, self.a_mode_add, self.a_mode_erase):
            em.addSeparator() if a is None else em.addAction(a)
        vm = m.addMenu("&Xem")
        vm.addAction(self._act("Phóng to", lambda: self.zoom_step(1), "Ctrl++"))
        vm.addAction(self._act("Thu nhỏ", lambda: self.zoom_step(-1), "Ctrl+-"))
        vm.addAction(self._act("Trang trước", lambda: self.go_page(self.cur - 1), "PgUp"))
        vm.addAction(self._act("Trang sau", lambda: self.go_page(self.cur + 1), "PgDown"))
        hm = m.addMenu("&Trợ giúp")
        hm.addAction(self._act("Hướng dẫn", self.show_help, "F1"))

    def _build_thumbs(self):
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setFlow(QListWidget.TopToBottom)
        self.thumbs.setWrapping(False)
        self.thumbs.setIconSize(QSize(120, 170))
        self.thumbs.setSpacing(6)
        self.thumbs.setMovement(QListWidget.Static)
        self.thumbs.setFixedWidth(165)
        self.thumbs.currentRowChanged.connect(lambda r: r >= 0 and self.go_page(r))
        dock = QDockWidget("Các trang", self)
        dock.setWidget(self.thumbs)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self._thumb_queue = []
        self._thumb_timer = QTimer(self, interval=0, timeout=self._thumb_tick)

    def fill_fonts(self, *_):
        cur = self.font_box.currentText() or self.fm.default_family()
        fams = sorted(f for f, e in self.fm.families.items() if e.get("vn") or not self.vn_only.isChecked())
        self.font_box.blockSignals(True)
        self.font_box.clear()
        self.font_box.addItems(fams)
        comp = QCompleter(fams, self.font_box)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.font_box.setCompleter(comp)
        i = self.font_box.findText(cur)
        if i < 0:
            i = self.font_box.findText(self.fm.default_family() or "")
        self.font_box.setCurrentIndex(max(i, 0))
        self.font_box.blockSignals(False)

    # ------------------------------------------------------------------ style
    def cur_family(self):
        t = self.font_box.currentText().strip()
        return t if t in self.fm.families else self.fm.default_family()

    def cur_size(self):
        try:
            v = float(self.size_box.currentText().replace(",", ".").strip())
            return min(max(v, 2), 400)
        except ValueError:
            return 13.0

    def cur_bold(self):
        return self.b_bold.isChecked()

    def cur_italic(self):
        return self.b_ital.isChecked()

    def set_color_btn(self):
        c = QColor.fromRgbF(*self.cur_color)
        self.b_color.setStyleSheet("QToolButton{border-bottom:4px solid %s;}" % c.name())

    def pick_color(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self.cur_color), self, "Chọn màu chữ")
        if c.isValid():
            self.cur_color = (c.redF(), c.greenF(), c.blueF())
            self.set_color_btn()
            self.view.restyle_editor()

    def load_style_from_line(self, ln):
        widgets = (self.font_box, self.size_box, self.b_bold, self.b_ital)
        for w in widgets:
            w.blockSignals(True)
        if self.keep_orig.isChecked():
            fam = core.clean_font_name(ln.font)
            if fam in self.fm.families:
                self.font_box.setCurrentText(fam)
        else:
            # mặc định Times New Roman
            d = core.DEFAULT_FAMILY if core.DEFAULT_FAMILY in self.fm.families else self.fm.default_family()
            if self.font_box.findText(d) >= 0:
                self.font_box.setCurrentText(d)
        s = ln.size
        self.size_box.setCurrentText(str(int(s)) if s == int(s) else str(s))
        self.b_bold.setChecked(ln.bold)
        self.b_ital.setChecked(ln.italic)
        self.cur_color = ln.color
        self.set_color_btn()
        for w in widgets:
            w.blockSignals(False)

    # ------------------------------------------------------------------ file
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(".pdf"):
                self.open_file(p)
                break

    def open_dialog(self):
        if not self.confirm_discard():
            return
        p, _ = QFileDialog.getOpenFileName(self, "Mở file PDF", self.last_dir, "PDF (*.pdf)")
        if p:
            self.open_file(p)

    def open_file(self, path):
        try:
            pdf = core.PdfDocument(path)
            if pdf.needs_pass():
                pw, ok = QInputDialog.getText(self, "Mật khẩu", "File PDF có mật khẩu. Nhập mật khẩu:", echo=2)
                if not ok or not pdf.authenticate(pw):
                    QMessageBox.warning(self, APP_TITLE, "Sai mật khẩu hoặc đã huỷ.")
                    return
        except Exception as ex:
            QMessageBox.critical(self, APP_TITLE, "Không mở được file:\n%s" % ex)
            return
        self.view.close_editor(False)
        self.pdf = pdf
        self.last_dir = os.path.dirname(path)
        self.cur = 0
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(pdf.page_count())
        self.page_spin.setValue(1)
        self.page_spin.blockSignals(False)
        self.page_total.setText(" / %d " % pdf.page_count())
        self.fit_width(render=False)
        self.render_page()
        self.build_thumbs()
        self.update_title()
        self.update_actions()
        no_text = all(not pdf.lines(i) for i in range(min(3, pdf.page_count())))
        msg = "Đã mở: %s – bấm vào dòng chữ để sửa." % os.path.basename(path)
        if no_text:
            msg = ("File này có vẻ là bản SCAN (ảnh) – không có lớp chữ để sửa trực tiếp. "
                   "Dùng 'Tẩy' để phủ trắng chữ cũ, rồi 'Thêm chữ' để gõ chữ mới.")
            QMessageBox.information(self, APP_TITLE, msg)
        if pdf.has_digital_signature():
            QMessageBox.information(self, APP_TITLE,
                                    "File có CHỮ KÝ SỐ. Hình chữ ký / con dấu vẫn giữ nguyên vị trí, "
                                    "nhưng sau khi sửa nội dung thì chữ ký số sẽ không còn hiệu lực xác thực.")
        self.status(msg)

    def confirm_discard(self):
        if self.view.editor is not None:
            self.view.close_editor(True)
        if self.pdf and self.pdf.modified:
            r = QMessageBox.question(self, APP_TITLE, "File đã được sửa nhưng chưa lưu. Lưu lại không?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save:
                return self.save_dialog()
        return True

    def closeEvent(self, e):
        if self.confirm_discard():
            e.accept()
        else:
            e.ignore()

    def save_dialog(self):
        if not self.pdf:
            return False
        self.view.close_editor(True)
        dlg = SaveDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return False
        (key, label, desc, ext), dpi, open_after = dlg.choice()
        base = os.path.splitext(os.path.basename(self.pdf.path))[0]
        sugg = os.path.join(self.last_dir, base + "_da_sua" + ext)
        filt = {".pdf": "PDF (*.pdf)", ".docx": "Word (*.docx)", ".xlsx": "Excel (*.xlsx)", ".png": "Ảnh PNG (*.png)",
                ".jpg": "Ảnh JPG (*.jpg)", ".txt": "Văn bản (*.txt)"}[ext]
        out, _ = QFileDialog.getSaveFileName(self, "Lưu thành", sugg, filt)
        if not out:
            return False
        if not out.lower().endswith(ext):
            out += ext
        pdf = self.pdf

        def job(progress):
            if key == "pdf":
                pdf.save_pdf(out)
                return [out]
            if key == "docx_layout":
                return [pdf.save_docx_layout(out, dpi, progress)]
            if key == "docx_image":
                return [pdf.save_docx_image(out, dpi, progress)]
            if key == "xlsx":
                return [pdf.save_xlsx(out, dpi, progress)]
            if key == "docx_flow":
                pdf.save_docx_flow(out, progress)
                return [out]
            if key in ("png", "jpg"):
                return pdf.save_images(out, dpi, key, progress)
            if key == "txt":
                pdf.save_txt(out)
                return [out]

        prog = QProgressDialog("Đang lưu: %s ..." % label, None, 0, 0, self)
        prog.setWindowTitle(APP_TITLE)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(300)
        result = {}

        def on_prog(a, b):
            prog.setMaximum(b)
            prog.setValue(a)

        def on_done(r, err):
            result["r"], result["err"] = r, err
            prog.close()

        w = Worker(job)
        w.prog.connect(on_prog)
        w.done.connect(on_done)
        w.start()
        while w.isRunning():
            QApplication.processEvents()
            w.wait(30)
        QApplication.processEvents()
        if result.get("err"):
            QMessageBox.critical(self, APP_TITLE, "Lưu thất bại:\n" + result["err"][-1500:])
            return False
        files = result.get("r") or [out]
        if key == "pdf":
            pdf.modified = False
            self.update_title()
        self.last_dir = os.path.dirname(out)
        self.status("Đã lưu: %s%s" % (files[0], (" (+%d file)" % (len(files) - 1)) if len(files) > 1 else ""))
        if open_after:
            try:
                if sys.platform.startswith("win"):
                    os.startfile(files[0])
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", files[0]])
            except Exception:
                pass
        if key != "pdf":
            pdf.modified = False
            self.update_title()
        return True

    def convert_dialog(self):
        ConvertDialog(self).exec_()

    # ------------------------------------------------------------------ trang
    def page_rect(self):
        return self.pdf.doc[self.cur].rect

    def render_page(self):
        if not self.pdf:
            return
        dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        scale_px = max(0.5, min(self.zoom * dpr, 6))
        pm = self.pdf.render(self.cur, scale_px)
        self.view.show_page(QPixmap.fromImage(pix_to_qimage(pm)), self.page_rect(), scale_px)
        self.view.set_zoom(self.zoom)
        self.page_lbl.setText("Trang %d/%d  |  %d%%" % (self.cur + 1, self.pdf.page_count(), round(self.zoom / (96 / 72) * 100)))

    def go_page(self, i):
        if not self.pdf or not (0 <= i < self.pdf.page_count()) or i == self.cur and self.view.page_item:
            return False
        self.view.close_editor(True)
        self.cur = i
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(i + 1)
        self.page_spin.blockSignals(False)
        self.thumbs.blockSignals(True)
        self.thumbs.setCurrentRow(i)
        self.thumbs.blockSignals(False)
        self.render_page()
        return True

    def fit_width(self, render=True):
        if not self.pdf:
            return
        vw = max(200, self.view.viewport().width() - 40)
        self.zoom = min(vw / self.page_rect().width, 96 / 72 * 1.5)
        self.zoom_box.setCurrentText("%d%%" % round(self.zoom / (96 / 72) * 100))
        if render:
            self.render_page()

    def zoom_from_box(self):
        t = self.zoom_box.currentText().strip()
        if t.startswith("Vừa"):
            return self.fit_width()
        try:
            v = float(t.replace("%", "").replace(",", "."))
        except ValueError:
            return
        self.set_zoom_pct(v)

    def set_zoom_pct(self, v):
        v = min(max(v, 20), 500)
        self.zoom = v / 100 * 96 / 72
        self.zoom_box.setCurrentText("%d%%" % round(v))
        self.view.set_zoom(self.zoom)
        self._rerender.start()

    def zoom_step(self, d):
        pct = self.zoom / (96 / 72) * 100
        self.set_zoom_pct(pct * (1.15 if d > 0 else 1 / 1.15))

    def build_thumbs(self):
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        for i in range(self.pdf.page_count()):
            it = QListWidgetItem("Trang %d" % (i + 1))
            it.setTextAlignment(Qt.AlignHCenter)
            self.thumbs.addItem(it)
        self.thumbs.setCurrentRow(0)
        self.thumbs.blockSignals(False)
        self._thumb_queue = list(range(self.pdf.page_count()))
        self._thumb_timer.start()

    def _thumb_tick(self):
        if not self._thumb_queue or not self.pdf:
            self._thumb_timer.stop()
            return
        i = self._thumb_queue.pop(0)
        self.update_thumb(i)

    def update_thumb(self, i):
        if not self.pdf or i >= self.thumbs.count():
            return
        page = self.pdf.doc[i]
        s = 120 / max(page.rect.width, 1)
        pm = page.get_pixmap(matrix=fitz.Matrix(s, s), alpha=False)
        self.thumbs.item(i).setIcon(QIcon(QPixmap.fromImage(pix_to_qimage(pm))))

    # ------------------------------------------------------------------ sửa
    def set_mode(self, m):
        self.view.close_editor(True)
        self.mode = m
        tips = {MODE_EDIT: "SỬA CHỮ: rê chuột lên dòng chữ (hiện khung xanh) rồi bấm để sửa.",
                MODE_ADD: "THÊM CHỮ: bấm vào chỗ trống trên trang để gõ chữ mới (font/cỡ chữ theo thanh định dạng).",
                MODE_ERASE: "TẨY: kéo chuột khoanh vùng → chọn 'Xoá chữ (giữ khung bảng)' hoặc 'Phủ trắng'."}
        self.status(tips[m])

    def editing_changed(self, on):
        self.a_apply.setEnabled(on)
        self.a_cancel.setEnabled(on)

    def apply_edit(self, ctx, text):
        if not ctx or not self.pdf:
            return
        try:
            text = text.replace("\r", "").rstrip("\n")
            args = (self.fm, self.cur_family(), self.cur_size(), self.cur_color, self.cur_bold(), self.cur_italic())
            if ctx[0] == "line":
                ln = ctx[1]
                # bấm vào rồi bấm ra mà không đổi gì -> không ghi lại (giữ nguyên chữ gốc)
                if text == ln.text and self.cur_style() == self.view.opened_style:
                    return
                self.pdf.replace_line(self.cur, ln, text, *args)
            else:
                _, x, top = ctx
                if not text.strip():
                    return
                self.pdf.add_text(self.cur, x, top, text, *args)
        except Exception as ex:
            QMessageBox.critical(self, APP_TITLE, "Không ghi được chữ:\n%s" % ex)
            return
        self.after_change()

    def cur_style(self):
        return (self.cur_family(), self.cur_size(), self.cur_bold(), self.cur_italic(), tuple(self.cur_color))

    def erase_area(self, r, gpos):
        m = QMenu(self)
        a1 = m.addAction("Xoá CHỮ trong vùng (giữ nguyên khung bảng, đường kẻ, chữ ký)")
        a2 = m.addAction("Phủ trắng toàn bộ vùng (dùng cho file scan)")
        m.addSeparator()
        m.addAction("Huỷ")
        a = m.exec_(gpos)
        rect = (r.left(), r.top(), r.right(), r.bottom())
        if a is a1:
            self.pdf.erase_text_in_rect(self.cur, rect)
        elif a is a2:
            self.pdf.whiteout_rect(self.cur, rect)
        else:
            return
        self.after_change()

    def after_change(self):
        self.render_page()
        self.update_thumb(self.cur)
        self.update_title()
        self.update_actions()

    def undo(self):
        self.view.close_editor(False)
        if self.pdf and self.pdf.undo():
            self.after_change()
            self.status("Đã hoàn tác.")

    def redo(self):
        self.view.close_editor(False)
        if self.pdf and self.pdf.redo():
            self.after_change()
            self.status("Đã làm lại.")

    # ------------------------------------------------------------------ khác
    def update_actions(self):
        has = self.pdf is not None
        self.a_save.setEnabled(has)
        self.a_undo.setEnabled(has and bool(self.pdf.undo_stack))
        self.a_redo.setEnabled(has and bool(self.pdf.redo_stack))
        self.editing_changed(self.view.editor is not None)

    def update_title(self):
        if self.pdf:
            self.setWindowTitle("%s%s – %s" % ("* " if self.pdf.modified else "",
                                               os.path.basename(self.pdf.path), APP_TITLE))
        else:
            self.setWindowTitle(APP_TITLE)

    def status(self, msg):
        self.statusBar().showMessage(msg)

    def show_help(self):
        QMessageBox.information(self, "Hướng dẫn", (
            "<b>%s %s</b> – chạy hoàn toàn offline.<br><br>"
            "<b>1. Sửa chữ có sẵn (F2):</b> rê chuột lên dòng chữ (khung xanh) → bấm → gõ như Word. "
            "Enter để xuống dòng, <b>Ctrl+Enter</b> hoặc bấm ra ngoài để ghi, Esc để huỷ. "
            "Xoá hết chữ trong ô rồi bấm ra ngoài = xoá dòng.<br>"
            "<b>2. Thêm chữ (F3):</b> bấm vào chỗ trống để gõ chữ mới.<br>"
            "<b>3. Tẩy (F4):</b> kéo chuột khoanh vùng → xoá chữ (giữ khung bảng) hoặc phủ trắng.<br>"
            "<b>4. Font / cỡ chữ:</b> chọn trên thanh định dạng – mặc định Times New Roman. "
            "Đổi font/cỡ khi ô soạn đang mở sẽ áp dụng ngay cho dòng đó.<br>"
            "<b>5. Lưu (Ctrl+S):</b> chọn định dạng PDF, Word, ảnh hoặc TXT.<br><br>"
            "Phần mềm chỉ thay đúng dòng chữ được sửa nên bảng, khung, chữ ký, con dấu "
            "giữ nguyên vị trí như file gốc." % (APP_TITLE, VERSION)))


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        try:
            import selftest
            return selftest.run(sys.argv[2])
        except BaseException:
            msg = "SELFTEST FAIL\n" + traceback.format_exc()
            try:
                print(msg)
            except Exception:
                pass
            os.makedirs(sys.argv[2], exist_ok=True)
            with open(os.path.join(sys.argv[2], "selftest.log"), "a", encoding="utf-8") as f:
                f.write("\n" + msg)
            return 1
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setStyle("Fusion")
    f = app.font()
    f.setPointSize(10)
    app.setFont(f)
    splash = QProgressDialog("Đang nạp danh sách font (chỉ lâu ở lần chạy đầu)...", None, 0, 0)
    splash.setWindowTitle(APP_TITLE)
    splash.setMinimumDuration(0)
    splash.show()
    app.processEvents()

    def prog(i, n):
        splash.setMaximum(n)
        splash.setValue(i)
        app.processEvents()

    try:
        fonts = core.scan_fonts(prog)
    except Exception:
        fonts = {}
    splash.close()
    if not fonts:
        QMessageBox.critical(None, APP_TITLE, "Không tìm thấy font nào trên máy (thư mục Windows\\Fonts).")
        return 1
    w = MainWindow(fonts)
    w.show()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        w.open_file(sys.argv[1])
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
