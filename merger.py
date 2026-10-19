# -*- coding: utf-8 -*-
"""GỘP NHIỀU FILE PDF THÀNH 1 FILE.
Các file nguồn chỉ được ĐỌC (đọc vào bộ nhớ), không bị sửa / ghi đè.
Trang được chép nguyên (ảnh scan không nén lại, chữ / chữ ký / con dấu giữ nguyên)."""
import os
import tempfile

from core import fitz


def page_count(path):
    try:
        with open(path, "rb") as f:
            d = fitz.open(stream=f.read(), filetype="pdf")
        if d.needs_pass:
            return None
        return d.page_count
    except Exception:
        return None


def merge(paths, out_path, bookmarks=True, progress=None):
    """Gộp paths (theo thứ tự) -> out_path. Trả về (số file đã gộp, tổng số trang, [(file lỗi, lý do)])."""
    out_n = os.path.normcase(os.path.abspath(out_path))
    for p in paths:
        if os.path.normcase(os.path.abspath(p)) == out_n:
            raise ValueError("File kết quả trùng với file nguồn: %s" % p)
    dst = fitz.open()
    toc = []
    ok, errors = 0, []
    for i, p in enumerate(paths):
        try:
            with open(p, "rb") as f:
                src = fitz.open(stream=f.read(), filetype="pdf")
            if src.needs_pass:
                errors.append((p, "có mật khẩu"))
                continue
            if src.page_count == 0:
                errors.append((p, "không có trang"))
                continue
            start = dst.page_count
            dst.insert_pdf(src)
            if bookmarks:
                toc.append([1, os.path.splitext(os.path.basename(p))[0], start + 1])
                try:
                    for lv, title, pg in src.get_toc(simple=True):
                        if pg >= 1:
                            toc.append([lv + 1, title, start + pg])
                except Exception:
                    pass
            ok += 1
            src.close()
        except Exception as ex:
            errors.append((p, str(ex)))
        if progress:
            progress(i + 1, len(paths))
    if dst.page_count == 0:
        raise ValueError("Không có trang nào để gộp.")
    if toc:
        try:
            dst.set_toc(toc)
        except Exception:
            pass
    total = dst.page_count
    # ghi ra file tạm rồi đổi tên -> không bao giờ để lại file kết quả hỏng dở dang
    d = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=d)
    os.close(fd)
    try:
        dst.save(tmp, garbage=3, deflate=True)
        dst.close()
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return ok, total, errors


def unique_path(path):
    """Không ghi đè file có sẵn: thêm (1), (2)..."""
    if not os.path.exists(path):
        return path
    b, e = os.path.splitext(path)
    i = 1
    while os.path.exists("%s (%d)%s" % (b, i, e)):
        i += 1
    return "%s (%d)%s" % (b, i, e)
