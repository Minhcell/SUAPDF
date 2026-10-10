# -*- coding: utf-8 -*-
"""Tự kiểm tra (chạy: SuaPDF.exe --selftest <thư_mục>) – dùng trong GitHub Actions."""
import os
import core
from core import fitz


def run(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    log = []
    fams = core.scan_fonts()
    fm = core.FontManager(fams)
    fam = fm.default_family()
    log.append("So font: %d | font mac dinh: %s" % (len(fams), fam))
    path, _ = fm.resolve(fam)
    # tạo PDF mẫu: chữ Việt + bảng + hình chữ ký
    src = os.path.join(out_dir, "mau.pdf")
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 80), "Họ và tên: Nguyễn Văn An", fontname="F0", fontfile=path, fontsize=13)
    p.insert_text((72, 95), "Ngày sinh: 01/01/1990", fontname="F0", fontfile=path, fontsize=13)
    for r in range(3):
        for c in range(3):
            rect = fitz.Rect(72 + c * 120, 150 + r * 22, 192 + c * 120, 172 + r * 22)
            p.draw_rect(rect, color=(0, 0, 0), width=0.8)
            p.insert_text((rect.x0 + 4, rect.y0 + 15), "Ô %d-%d" % (r, c), fontname="F0", fontfile=path, fontsize=12)
    p.draw_circle((400, 300), 30, color=(0.8, 0, 0))
    d.save(src)
    n_draw = len(p.get_drawings())

    doc = core.PdfDocument(src)
    ln = [l for l in doc.lines(0) if l.text.startswith("Ngày sinh")][0]
    doc.replace_line(0, ln, "Ngày sinh: 15/08/1985 – Hà Nội", fm, fam, ln.size, ln.color, False, False)
    ln = [l for l in doc.lines(0) if l.text == "Ô 1-1"][0]
    doc.replace_line(0, ln, "Đã sửa", fm, fam, ln.size, ln.color, True, False)
    doc.add_text(0, 72, 400, "Dòng thêm mới", fm, fam, 13, (0, 0, 0), False, True)
    texts = [l.text for l in doc.lines(0)]
    assert "Họ và tên: Nguyễn Văn An" in texts, texts
    assert "Ngày sinh: 15/08/1985 – Hà Nội" in texts, texts
    assert "Đã sửa" in texts and "Dòng thêm mới" in texts, texts
    assert len(doc.doc[0].get_drawings()) == n_draw, "mat duong ke bang!"
    log.append("Sua chu: OK, giu nguyen %d duong ke" % n_draw)

    doc.save_pdf(os.path.join(out_dir, "kq.pdf"))
    doc.save_docx_layout(os.path.join(out_dir, "kq_bocuc.docx"))
    doc.save_docx_image(os.path.join(out_dir, "kq_anh.docx"))
    doc.save_docx_flow(os.path.join(out_dir, "kq_lienmach.docx"))
    doc.save_images(os.path.join(out_dir, "kq.png"), 100, "png")
    doc.save_images(os.path.join(out_dir, "kq.jpg"), 100, "jpg")
    doc.save_txt(os.path.join(out_dir, "kq.txt"))
    for f in ("kq.pdf", "kq_bocuc.docx", "kq_anh.docx", "kq_lienmach.docx", "kq.png", "kq.jpg", "kq.txt"):
        sz = os.path.getsize(os.path.join(out_dir, f))
        assert sz > 0, f
        log.append("Xuat %s: %d bytes" % (f, sz))
    chk = fitz.open(os.path.join(out_dir, "kq.pdf"))
    assert "Đã sửa" in chk[0].get_text()
    log.append("SELFTEST OK")
    with open(os.path.join(out_dir, "selftest.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    return 0
