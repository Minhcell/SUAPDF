# -*- coding: utf-8 -*-
"""Tự kiểm tra (chạy: SuaPDF.exe --selftest <thư_mục>) – dùng trong GitHub Actions.
Ghi từng bước ra màn hình + file selftest.log để biết chính xác lỗi ở đâu."""
import os
import sys
import traceback

import core
from core import fitz


class Log:
    def __init__(self, out_dir):
        self.path = os.path.join(out_dir, "selftest.log")
        self.lines = []

    def __call__(self, msg):
        self.lines.append(msg)
        try:
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
        except Exception:
            pass
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.lines))
        except Exception:
            pass


def run(out_dir):
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    log = Log(out_dir)
    errors = []

    def step(name, fn, critical=True):
        try:
            r = fn()
            log("[OK]  " + name)
            return r
        except Exception:
            tb = traceback.format_exc()
            log(("[LOI] " if critical else "[CANH BAO] ") + name + "\n" + tb)
            if critical:
                errors.append(name)
            return None

    log("Python %s | PyMuPDF %s | %s" % (sys.version.split()[0], getattr(fitz, "VersionBind", "?"), sys.platform))
    log("Thu muc font: %s" % core.font_dirs())

    fams = step("Doc danh sach font", core.scan_fonts) or {}
    log("So font: %d" % len(fams))
    if not fams:
        log("SELFTEST FAIL: khong co font")
        return 1
    fm = core.FontManager(fams)
    fam = fm.default_family()
    path, _ = fm.resolve(fam)
    log("Font mac dinh: %s -> %s" % (fam, path))

    src = os.path.join(out_dir, "mau.pdf")
    state = {}

    def make_sample():
        d = fitz.open()
        p = d.new_page()
        p.insert_text((72, 80), "Họ và tên: Nguyễn Văn An", fontname="F0", fontfile=path, fontsize=13)
        p.insert_text((72, 95), "Ngày sinh: 01/01/1990", fontname="F0", fontfile=path, fontsize=13)
        for r in range(3):
            for c in range(3):
                rect = fitz.Rect(72 + c * 120, 150 + r * 22, 192 + c * 120, 172 + r * 22)
                p.draw_rect(rect, color=(0, 0, 0), width=0.8)
                p.insert_text((rect.x0 + 4, rect.y0 + 15), "O %d-%d" % (r, c), fontname="F0", fontfile=path, fontsize=12)
        p.draw_circle((400, 300), 30, color=(0.8, 0, 0))
        state["n_draw"] = len(p.get_drawings())
        d.save(src)

    step("Tao PDF mau", make_sample)
    if errors:
        log("SELFTEST FAIL: " + ", ".join(errors))
        return 1

    doc = step("Mo PDF", lambda: core.PdfDocument(src))
    if doc is None:
        log("SELFTEST FAIL: khong mo duoc PDF")
        return 1

    def edit():
        texts = [l.text for l in doc.lines(0)]
        log("    Chu doc duoc: %s" % ascii(texts))
        ln = [l for l in doc.lines(0) if "sinh" in l.text][0]
        doc.replace_line(0, ln, "Ngày sinh: 15/08/1985 – Hà Nội", fm, fam, ln.size, ln.color, False, False)
        cell = [l for l in doc.lines(0) if l.bbox.contains(fitz.Point(205, 183))]
        assert cell, "khong tim thay dong chu trong o bang giua"
        assert cell[0].text.strip() == "O 1-1", "doc sai chu trong o: %s" % ascii(cell[0].text)
        ln = cell[0]
        doc.replace_line(0, ln, "Đã sửa", fm, fam, ln.size, ln.color, True, False)
        doc.add_text(0, 72, 400, "Dòng thêm mới", fm, fam, 13, (0, 0, 0), False, True)
        texts = [l.text for l in doc.lines(0)]
        log("    Sau khi sua: %s" % ascii(texts))
        assert any("15/08/1985" in t for t in texts), "khong thay dong da sua"
        assert any("Nguy" in t for t in texts), "mat dong ben canh"
        n = len(doc.doc[0].get_drawings())
        assert n == state["n_draw"], "mat duong ke bang (%d -> %d)" % (state["n_draw"], n)

    step("Sua chu / them chu (giu duong ke bang)", edit)

    def out(name):
        return os.path.join(out_dir, name)

    step("Luu PDF", lambda: doc.save_pdf(out("kq.pdf")))
    step("Luu Word giu bo cuc", lambda: doc.save_docx_layout(out("kq_bocuc.docx")))
    step("Luu Word anh trang", lambda: doc.save_docx_image(out("kq_anh.docx")))
    step("Luu Word lien mach (pdf2docx)", lambda: doc.save_docx_flow(out("kq_lienmach.docx")), critical=False)
    step("Luu PNG", lambda: doc.save_images(out("kq.png"), 100, "png"))
    step("Luu JPG", lambda: doc.save_images(out("kq.jpg"), 100, "jpg"))
    step("Luu TXT", lambda: doc.save_txt(out("kq.txt")))

    def roundtrip():
        # mở lại file PDF đã lưu (font đã rút gọn) rồi sửa tiếp bằng chữ cái MỚI
        src2 = out("kq.pdf")
        for i, w in enumerate(["Minh", "Quỳnh Trâm Xuân", "Kỳ Duyên Phước Ẩu"]):
            d2 = core.PdfDocument(src2)
            ln2 = [l for l in d2.lines(0) if l.text.startswith("Họ và tên")][0]
            d2.replace_line(0, ln2, "Họ và tên: " + w, fm, fam, ln2.size, ln2.color, False, False)
            d2.add_text(0, 72, 450 + i * 16, "Lần %d: %s" % (i + 1, w), fm, fam, 13, (0, 0, 0), False, False)
            src2 = out("kq_lan%d.pdf" % (i + 2))
            d2.save_pdf(src2)
            t = fitz.open(src2)[0].get_text()
            bad = [c for c in t if c in "\x00\ufffd"]
            assert not bad, "lan %d: co %d ky tu o vuong" % (i + 2, len(bad))
            assert ("Họ và tên: " + w) in core.norm_text(t), "lan %d: khong thay chu moi" % (i + 2)

    step("Mo lai file da luu, sua tiep nhieu lan (khong o vuong)", roundtrip)

    def excel_check():
        import openpyxl
        doc.save_xlsx(out("kq.xlsx"))
        wb = openpyxl.load_workbook(out("kq.xlsx"))
        ws = wb.worksheets[0]
        vals = [str(c.value) for r in ws.iter_rows() for c in r if c.value]
        log("    Excel: %d o co chu, %d anh, %d vung gop o" % (len(vals), len(ws._images), len(ws.merged_cells.ranges)))
        assert any("Đã sửa" in v for v in vals), "Excel thieu chu da sua"
        assert any("Nguy" in v or "Họ và tên" in v for v in vals), "Excel thieu dong chu"
        assert len(ws._images) >= 1, "Excel thieu anh (con dau)"

    step("Luu Excel giu bo cuc (bang -> o, con dau -> anh)", excel_check)

    def word_normal_check():
        import zipfile
        x = zipfile.ZipFile(out("kq_bocuc.docx")).read("word/document.xml").decode("utf-8")
        assert "framePr" not in x, "Word van con khung (text box)"
        assert "<w:tbl>" in x or "<w:tbl " in x, "Word thieu bang"
        assert "wp:anchor" in x, "Word thieu anh con dau/chu ky"
        assert "Đã sửa" in x, "Word thieu chu da sua"

    step("Word la van ban binh thuong (khong khung, co bang that, co anh dau)", word_normal_check)

    def convert_check():
        import hashlib
        import convert
        src = out("kq.pdf")
        h0 = hashlib.md5(open(src, "rb").read()).hexdigest()
        cdir = out("chuyen")
        a, _ = convert.convert_file("pdf2word", src, cdir)
        b, _ = convert.convert_file("pdf2excel", src, cdir)
        c, _ = convert.convert_file("pdf2word", src, cdir)
        assert os.path.getsize(a) > 0 and os.path.getsize(b) > 0
        assert a != c, "ghi de file ket qua!"
        assert hashlib.md5(open(src, "rb").read()).hexdigest() == h0, "file goc bi thay doi!"
        log("    -> %s | %s | %s" % (os.path.basename(a), os.path.basename(b), os.path.basename(c)))
        for kind, f in (("word", a), ("excel", b)):
            eng = convert.detect_engines(kind)
            if not eng:
                log("    [BO QUA] %s -> PDF: may build khong co Office/LibreOffice" % kind)
                continue
            h1 = hashlib.md5(open(f, "rb").read()).hexdigest()
            p, used = convert.convert_file(kind + "2pdf", f, cdir)
            assert hashlib.md5(open(f, "rb").read()).hexdigest() == h1, "file %s goc bi thay doi" % kind
            log("    %s -> PDF bang %s: %s" % (kind, used, os.path.basename(p)))

    step("Chuyen doi PDF <-> Word/Excel (file goc khong doi, khong ghi de)", convert_check)

    def blank_check():
        import convert
        d = fitz.open()
        for txt in ("Trang A", None, "./.", None):
            p = d.new_page()
            if txt:
                p.insert_text((72, 300), txt, fontsize=13)
        d[1].insert_text((290, 815), "2", fontsize=10)  # trang trống chỉ có số trang ở chân
        src = out("co_trang_trong.pdf")
        d.save(src)
        cdir = out("chuyen_nhieu")
        res = []
        for m in ("pdf2word", "pdf2excel"):
            st = {}
            o, _ = convert.convert_file(m, src, cdir, stats=st)
            res.append((os.path.basename(o), st["blank"]))
            assert st["blank"] == 2, "%s: xoa %d trang trong (dung la 2)" % (m, st["blank"])
        assert fitz.open(src).page_count == 4, "file goc bi doi so trang!"
        log("    %s" % res)

    step("Tu xoa trang trong (giu trang chi co './.', file goc khong doi)", blank_check)

    for f in ("kq.pdf", "kq_bocuc.docx", "kq.xlsx", "kq_anh.docx", "kq_lienmach.docx", "kq.png", "kq.jpg", "kq.txt"):
        p = out(f)
        log("    %s: %s" % (f, ("%d bytes" % os.path.getsize(p)) if os.path.exists(p) else "KHONG CO"))

    if errors:
        log("SELFTEST FAIL: " + ", ".join(errors))
        return 1
    log("SELFTEST OK")
    return 0
