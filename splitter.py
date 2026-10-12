# -*- coding: utf-8 -*-
"""
TÁCH FILE PDF GỘP (scan nhiều văn bản vào 1 file) THÀNH TỪNG VĂN BẢN.

Nhận biết TRANG ĐẦU của mỗi văn bản hành chính:
  - PDF có chữ (bản số / đã OCR): đầu trang có "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM" / "Độc lập - Tự do - Hạnh phúc".
  - PDF scan (ảnh): đầu trang, nửa bên phải có ĐƯỜNG GẠCH NGẮN dưới Quốc hiệu
    ("Độc lập - Tự do - Hạnh phúc" luôn có gạch chân), phía trên có chữ.
Trang trống (trắng, chỉ có bụi / bóng mép giấy / số trang) được bỏ đi.
File gốc chỉ được ĐỌC. Ảnh scan được chép nguyên, không nén lại -> không giảm chất lượng.
"""
import os
import re
import unicodedata

import numpy as np

from core import fitz

DPI = 72  # độ phân giải phân tích (đủ để nhận biết, chạy nhanh với file nhiều trang)


def _plain(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.replace("đ", "d")


_HEADER_RE = re.compile(r"cong\s*hoa\s*xa\s*hoi\s*chu\s*nghia|doc\s*lap\s*[-–—]?\s*tu\s*do")


class PageInfo:
    __slots__ = ("blank", "header", "why", "ink")

    def __init__(self, blank, header, why, ink):
        self.blank, self.header, self.why, self.ink = blank, header, why, ink


def _gray(page, dpi=DPI):
    pm = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False, annots=True)
    return np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.stride)[:, :pm.width].copy()


def _is_blank(page, g):
    """Trang trống của bản scan: bỏ qua mép giấy (bóng máy scan) + đầu/chân trang (số trang),
    phần thân gần như không có mực. Trang có chữ thật (kể cả './.') luôn được giữ."""
    H = page.rect.height
    try:
        for w in page.get_text("words"):
            r = fitz.Rect(w[:4]) * page.rotation_matrix
            cy = (r.y0 + r.y1) / 2
            if w[4].strip() and H * 0.09 <= cy <= H * 0.91:
                return False, 1.0
    except Exception:
        pass
    h, w = g.shape
    body = g[int(h * 0.09):int(h * 0.91), int(w * 0.06):int(w * 0.94)]
    if body.size == 0:
        return True, 0.0
    # ngưỡng thích nghi theo màu giấy (giấy scan hơi xám)
    paper = float(np.percentile(body, 90))
    dark = body < min(150, paper - 60)
    ratio = float(dark.mean())
    if ratio > 0.004:
        return False, ratio
    # loại bụi lẻ tẻ: đếm hàng có mực đáng kể
    rows = (dark.sum(axis=1) >= 3).sum()
    return rows < max(4, int(body.shape[0] * 0.012)), ratio


def _hlines(region, min_len, max_len):
    """Các đoạn gạch ngang liền mạch (y, x0, x1) trong vùng ảnh nhị phân."""
    out = []
    H, W = region.shape
    for y in range(H):
        row = region[y]
        if row.sum() < min_len:
            continue
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        starts = np.where(d == 1)[0]
        ends = np.where(d == -1)[0]
        for a, b in zip(starts, ends):
            if min_len <= b - a <= max_len:
                out.append((y, a, b))
    return out


def _visual_header(page):
    """Ảnh scan: đầu trang, nửa phải có đường gạch ngắn (gạch chân Quốc hiệu), phía trên có chữ,
    ngay dưới là khoảng trắng. Chịu được giấy nghiêng nhẹ; loại đường kẻ bảng (dài, sát chữ)."""
    r = page.rect
    clip = fitz.Rect(r.x0, r.y0, r.x1, r.y0 + r.height * 0.30)
    pm = page.get_pixmap(dpi=120, colorspace=fitz.csGRAY, alpha=False, clip=clip)
    g = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.stride)[:, :pm.width]
    h, w = g.shape
    Hpage = h / 0.30
    paper = float(np.percentile(g, 85))
    bw = g < (paper - 40)
    # chịu nghiêng: gộp 3 hàng liền nhau (đường gạch nghiêng thành bậc thang vẫn liền mạch)
    pool = bw.copy()
    pool[1:] |= bw[:-1]
    pool[:-1] |= bw[1:]
    # nối chỗ đứt 1-2 px theo chiều ngang
    p2 = pool.copy()
    p2[:, 1:] |= pool[:, :-1]
    p2[:, 2:] |= pool[:, :-2]
    cands = _hlines(p2, int(w * 0.10), int(w * 0.40))
    if not cands:
        return False, ""
    cands.sort()
    groups = []
    for y, a, b in cands:
        for gr in groups:
            if y - gr["y1"] <= 2 and min(b, gr["b"]) - max(a, gr["a"]) > 0.5 * (b - a):
                gr["y1"] = y
                gr["a"], gr["b"] = min(a, gr["a"]), max(b, gr["b"])
                break
        else:
            groups.append({"y0": y, "y1": y, "a": a, "b": b})
    lh = max(3, int(Hpage * 0.012))          # ~ 1 dòng chữ
    for gr in groups:
        a, b, y0, y1 = int(gr["a"]), int(gr["b"]), gr["y0"], gr["y1"]
        if y1 - y0 + 1 > max(7, int(Hpage * 0.008)):
            continue                          # quá dày -> không phải gạch chân
        cx = (a + b) / 2
        if not (0.40 * w <= cx <= 0.93 * w) or y0 < Hpage * 0.03:
            continue
        # đường kẻ bảng: kéo dài quá 45% bề ngang trang trên cùng độ cao
        band = p2[max(0, y0 - 1):y1 + 2]
        row = band.any(axis=0).astype(np.int8)
        d = np.diff(np.concatenate(([0], row, [0])))
        st, en = np.where(d == 1)[0], np.where(d == -1)[0]
        longest = max((e - s_ for s_, e in zip(st, en) if s_ <= cx <= e), default=0)
        if longest > 0.45 * w:
            continue
        # phía trên có chữ (2 dòng Quốc hiệu)
        above = bw[max(0, y0 - 3 * lh):max(0, y0 - 2), a:b]
        if above.size == 0 or above.mean() < 0.04:
            continue
        # ngay dưới là khoảng trắng (bảng / đoạn văn gạch chân thì sát chữ)
        below = bw[y1 + 3:min(h, y1 + 3 + lh), a:b]
        if below.size and below.mean() > 0.06:
            continue
        # có vạch đứng cắt ngang (khung bảng) -> loại
        # khung bảng: có vạch đứng chạy xuống ngay dưới đường kẻ
        below_v = pool[min(h - 1, y1 + 2):min(h, y1 + 2 + lh), a:b]
        if below_v.size and (below_v.mean(axis=0) > 0.75).any():
            continue
        # phía trên phải có 2 dòng chữ (Quốc hiệu: "CỘNG HÒA..." + "Độc lập - Tự do...")
        rows = bw[max(0, y0 - 4 * lh):max(0, y0 - 2), max(0, a - int(0.08 * w)):min(w, b + int(0.08 * w))]
        prof = rows.mean(axis=1) > 0.02 if rows.size else np.zeros(0, bool)
        nb, prev = 0, False
        for v in prof:
            if v and not prev:
                nb += 1
            prev = bool(v)
        if nb < 2:
            continue
        centered_page = 0.40 * w <= cx <= 0.60 * w and y0 < Hpage * 0.16
        # Quốc hiệu bên phải luôn đi cặp với TÊN CƠ QUAN bên trái (cùng độ cao)
        left = bw[max(0, y0 - 4 * lh):min(h, y1 + lh), int(0.05 * w):int(0.46 * w)]
        has_left = left.size and left.mean() > 0.012
        if not (has_left or centered_page):
            continue
        return True, "gạch chân Quốc hiệu (ảnh scan)"
    return False, ""


def _page_number_top(page, words):
    """Có SỐ TRANG ở giữa phía trên (từ trang 2 trở đi theo thể thức văn bản) -> không phải trang đầu."""
    W, H = page.rect.width, page.rect.height
    if words:
        top = [w for w in words if w[3] <= H * 0.085 and w[4].strip()]
        if top:
            return all(re.fullmatch(r"[-–\s]*\d{1,3}[-–\s]*", w[4]) for w in top) and \
                all(abs((w[0] + w[2]) / 2 - W / 2) < W * 0.12 for w in top)
        return False
    clip = fitz.Rect(0, H * 0.015, W, H * 0.068)
    pm = page.get_pixmap(dpi=100, colorspace=fitz.csGRAY, alpha=False, clip=clip)
    g = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.stride)[:, :pm.width]
    gw = g.shape[1]
    g = g[:, int(gw * 0.08):int(gw * 0.92)]
    paper = float(np.percentile(g, 85))
    bw = g < (paper - 50)
    # bỏ chấm bụi lẻ
    cols = np.where(bw.sum(axis=0) >= 2)[0]
    rows = np.where(bw.sum(axis=1) >= 2)[0]
    if len(cols) < 2 or len(rows) < 2:
        return False
    x0, x1 = cols.min(), cols.max()
    cw = g.shape[1]
    cxr = (x0 + x1) / 2 / cw
    return (x1 - x0) < cw * 0.07 and 0.40 <= cxr <= 0.60 and (rows.max() - rows.min()) < g.shape[0] * 0.8


def analyze(doc, progress=None, stop=None):
    infos = []
    n = doc.page_count
    for i in range(n):
        if stop and stop():
            break
        page = doc[i]
        g = _gray(page)
        blank, ink = _is_blank(page, g)
        header, why = False, ""
        if not blank:
            H = page.rect.height
            try:
                words = [w for w in page.get_text("words") if w[4].strip()]
                rot = page.rotation_matrix
                words = [tuple(fitz.Rect(w[:4]) * rot) + (w[4],) for w in words]
            except Exception:
                words = []
            if len(words) >= 8:
                # PDF có lớp chữ (bản số / đã OCR): chỉ tin vào chữ
                txt = " ".join(w[4] for w in words if w[3] <= H * 0.30)
                if _HEADER_RE.search(_plain(txt)):
                    header, why = True, "Quốc hiệu (chữ)"
            else:
                header, why = _visual_header(page)
            if header and _page_number_top(page, words if len(words) >= 8 else None):
                header, why = False, "có số trang ở đầu trang -> trang tiếp theo"
        infos.append(PageInfo(blank, header, why, ink))
        if progress:
            progress(i + 1, n)
    return infos


def plan(infos, mode="auto", every=2, drop_blank=True, starts=None, blanks=None):
    """Trả về list văn bản, mỗi văn bản = list chỉ số trang (0-based).
    mode: 'auto' (trang đầu có Quốc hiệu) | 'blank' (trang trống ngăn cách) | 'every' (mỗi N trang).
    starts / blanks: tập trang người dùng đã chỉnh tay (nếu có) – ghi đè kết quả tự động."""
    n = len(infos)
    blanks = set(i for i in range(n) if infos[i].blank) if blanks is None else set(blanks)
    if starts is None:
        starts = auto_starts(infos, mode, every, blanks)
    docs, cur = [], []
    for i in range(n):
        if i in blanks:
            if not drop_blank:
                cur.append(i)
            continue
        if i in starts and cur and any(p not in blanks for p in cur):
            docs.append(cur)
            cur = []
        cur.append(i)
    if cur and any(p not in blanks for p in cur):
        docs.append(cur)
    return docs


def auto_starts(infos, mode="auto", every=2, blanks=None):
    n = len(infos)
    blanks = set(i for i in range(n) if infos[i].blank) if blanks is None else set(blanks)
    content = [i for i in range(n) if i not in blanks]
    starts = set()
    if not content:
        return starts
    starts.add(content[0])
    if mode == "auto":
        for i in content:
            if infos[i].header:
                starts.add(i)
    elif mode == "blank":
        prev_blank = False
        for i in range(n):
            if i in blanks:
                prev_blank = True
            elif prev_blank:
                starts.add(i)
                prev_blank = False
    elif mode == "every":
        every = max(1, int(every))
        for k, i in enumerate(content):
            if k % every == 0:
                starts.add(i)
    return starts


def save_docs(src_doc, docs, out_dir, base, progress=None):
    """Lưu từng văn bản thành 1 file PDF riêng. Không ghi đè file có sẵn."""
    os.makedirs(out_dir, exist_ok=True)
    files = []
    width = max(2, len(str(len(docs))))
    for k, pages in enumerate(docs):
        nd = fitz.open()
        for p in pages:
            nd.insert_pdf(src_doc, from_page=p, to_page=p)
        name = "%s_VB%0*d.pdf" % (base, width, k + 1)
        path = os.path.join(out_dir, name)
        i = 1
        while os.path.exists(path):
            path = os.path.join(out_dir, "%s_VB%0*d (%d).pdf" % (base, width, k + 1, i))
            i += 1
        nd.save(path, garbage=3, deflate=True)
        nd.close()
        files.append((path, pages))
        if progress:
            progress(k + 1, len(docs))
    return files
