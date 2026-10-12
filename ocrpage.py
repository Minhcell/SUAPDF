# -*- coding: utf-8 -*-
"""
TRANG PDF SCAN (ẢNH) -> DỮ LIỆU ĐỂ DỰNG VĂN BẢN WORD GÕ ĐƯỢC.

  1. Tách lớp màu (con dấu đỏ, chữ ký mực xanh) -> giữ làm ẢNH, không đưa vào nhận dạng chữ.
  2. Tìm đường kẻ bảng trên ảnh -> dựng lại BẢNG WORD thật (gộp ô theo đường kẻ có / không có).
  3. Xoá đường kẻ + phần màu rồi NHẬN DẠNG CHỮ (OCR tiếng Việt, chạy offline – Tesseract có sẵn
     trong thư viện PyMuPDF, dữ liệu tiếng Việt đi kèm phần mềm).
  4. Phần còn lại không phải chữ (logo, con dấu, chữ ký, gạch trang trí) -> ảnh trong suốt đặt đúng chỗ.
Kết quả có cùng dạng với trang PDF có chữ, để wordnative dựng văn bản Word bình thường.
"""
import io
import os
import sys

import re

import numpy as np

from core import fitz

OCR_DPI = 400


# =============================================================================
#  DỮ LIỆU TIẾNG VIỆT CHO OCR
# =============================================================================
def tessdata_dir():
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), "tessdata"))
        cands.append(os.path.join(os.path.dirname(sys.executable), "tessdata"))
    cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata"))
    if os.environ.get("TESSDATA_PREFIX"):
        cands.append(os.environ["TESSDATA_PREFIX"])
    for d in cands:
        if d and os.path.isfile(os.path.join(d, "vie.traineddata")):
            return d
    return None


def ocr_available():
    return tessdata_dir() is not None and hasattr(fitz.Page, "get_textpage_ocr")


# =============================================================================
#  NHẬN BIẾT TRANG SCAN
# =============================================================================
def is_scanned(page):
    """Trang gần như không có lớp chữ nhưng có ảnh phủ phần lớn trang."""
    try:
        words = [w for w in page.get_text("words") if w[4].strip()]
    except Exception:
        words = []
    if len(words) >= 5:
        return False
    area = page.rect.get_area()
    cover = 0.0
    try:
        for info in page.get_image_info():
            r = fitz.Rect(info["bbox"]) & page.rect
            cover += r.get_area()
    except Exception:
        return False
    return cover >= 0.5 * area


# =============================================================================
#  XỬ LÝ ẢNH
# =============================================================================
def _render(page, dpi):
    pm = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    return np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.stride)[:, :pm.width * 3] \
        .reshape(pm.height, pm.width, 3).copy()


def _deskew(rgb):
    """Chỉnh thẳng trang scan bị nghiêng (tìm góc làm các dòng chữ thẳng hàng nhất)."""
    import cv2
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(g, (g.shape[1] // 4, g.shape[0] // 4), interpolation=cv2.INTER_AREA)
    bw = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 15)
    h, w = bw.shape
    best, best_a = -1.0, 0.0
    for a in np.arange(-3.0, 3.01, 0.1):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        r = cv2.warpAffine(bw, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        prof = r.sum(axis=1).astype(np.float64)
        sc = float(((prof[1:] - prof[:-1]) ** 2).sum())
        if sc > best:
            best, best_a = sc, a
    if abs(best_a) < 0.05:
        return rgb, 0.0
    H, W = rgb.shape[:2]
    M = cv2.getRotationMatrix2D((W / 2, H / 2), best_a, 1.0)
    out = cv2.warpAffine(rgb, M, (W, H), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    return out, best_a


def _masks(rgb):
    import cv2
    r, g, b = rgb[..., 0].astype(np.int16), rgb[..., 1].astype(np.int16), rgb[..., 2].astype(np.int16)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # mực màu: con dấu đỏ, chữ ký xanh (độ bão hoà cao, không quá sáng)
    color = ((mx - mn) > 55) & (mn < 200)
    # mực đen / xám: nhị phân thích nghi theo nền giấy
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    # ngưỡng thích nghi theo vùng: nền ô bảng tô màu nhạt không bị coi là mực
    bs = (int(OCR_DPI / 6) // 2) * 2 + 1
    ad = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, bs, 18)
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    dark = (ad > 0) & (otsu > 0) & ~color
    return gray, dark, color


def _lines(dark, dpi):
    """Đường kẻ ngang / dọc (mặt nạ) bằng phép hình thái học."""
    import cv2
    h, w = dark.shape
    m = dark.astype(np.uint8) * 255
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, int(dpi * 0.45)), 1))   # >= ~3.2 cm? -> 0.45 inch
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, int(dpi * 0.30))))
    hor = cv2.morphologyEx(m, cv2.MORPH_OPEN, kh)
    ver = cv2.morphologyEx(m, cv2.MORPH_OPEN, kv)
    # nối chỗ đứt do scan
    hor = cv2.dilate(hor, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)))
    ver = cv2.dilate(ver, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 5)))
    return hor > 0, ver > 0


def _runs(mask1d, min_len):
    d = np.diff(np.concatenate(([0], mask1d.astype(np.int8), [0])))
    s, e = np.where(d == 1)[0], np.where(d == -1)[0]
    return [(a, b) for a, b in zip(s, e) if b - a >= min_len]


class ScanTable:
    def __init__(self, bbox, cells, nr, nc):
        self.bbox = bbox
        self.cells = cells
        self.row_count, self.col_count = nr, nc


def _tables(hor, ver, scale, dpi):
    """Dựng bảng từ đường kẻ: lưới hàng/cột, gộp ô khi thiếu đường kẻ bên trong."""
    import cv2
    both = (hor | ver).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(both, connectivity=8)
    tables, tmask = [], np.zeros_like(both, dtype=bool)
    hs_all, vs_all = [], []
    minw = dpi * 0.8
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < minw or h < dpi * 0.25:
            continue
        sub_h = hor[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == i)
        sub_v = ver[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == i)
        # vị trí đường ngang (theo hàng) và đường dọc (theo cột)
        rows = [((a + b) // 2) for a, b in _runs(sub_h.sum(axis=1) > w * 0.25, 1)]
        cols = [((a + b) // 2) for a, b in _runs(sub_v.sum(axis=0) > h * 0.25, 1)]
        if len(rows) < 2 or len(cols) < 2:
            continue
        nr, nc = len(rows) - 1, len(cols) - 1

        def has_h(yy, x0, x1):   # đường ngang tại yy trên đoạn [x0,x1]
            band = sub_h[max(0, yy - 3):yy + 4, x0:x1].any(axis=0)
            return band.mean() > 0.6 if band.size else False

        def has_v(xx, y0, y1):
            band = sub_v[y0:y1, max(0, xx - 3):xx + 4].any(axis=1)
            return band.mean() > 0.6 if band.size else False

        # gộp ô: union-find trên lưới
        parent = list(range(nr * nc))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for r in range(nr):
            for c in range(nc):
                if c + 1 < nc and not has_v(cols[c + 1], rows[r] + 2, rows[r + 1] - 2):
                    parent[find(r * nc + c)] = find(r * nc + c + 1)
                if r + 1 < nr and not has_h(rows[r + 1], cols[c] + 2, cols[c + 1] - 2):
                    parent[find(r * nc + c)] = find((r + 1) * nc + c)
        groups = {}
        for r in range(nr):
            for c in range(nc):
                groups.setdefault(find(r * nc + c), []).append((r, c))
        cells = []
        for g in groups.values():
            r0 = min(r for r, _ in g); r1 = max(r for r, _ in g) + 1
            c0 = min(c for _, c in g); c1 = max(c for _, c in g) + 1
            cells.append(((x + cols[c0]) * scale, (y + rows[r0]) * scale,
                          (x + cols[c1]) * scale, (y + rows[r1]) * scale))
        bbox = ((x + cols[0]) * scale, (y + rows[0]) * scale, (x + cols[-1]) * scale, (y + rows[-1]) * scale)
        tables.append(ScanTable(bbox, cells, nr, nc))
        tmask[y:y + h, x:x + w] |= (lab[y:y + h, x:x + w] == i)
        # đoạn kẻ để biết cạnh ô nào có viền
        for yy in rows:
            for a, b in _runs(sub_h[max(0, yy - 3):yy + 4].any(axis=0), 5):
                hs_all.append(((x + a) * scale, (x + b) * scale, (y + yy) * scale, 0.5))
        for xx in cols:
            for a, b in _runs(sub_v[:, max(0, xx - 3):xx + 4].any(axis=1), 5):
                vs_all.append(((y + a) * scale, (y + b) * scale, (x + xx) * scale, 0.5))
    return tables, tmask, (hs_all, vs_all)


# =============================================================================
#  OCR
# =============================================================================
def _ocr_words(page_rect, img_gray):
    """OCR ảnh (đã xoá kẻ bảng + phần màu). Trả về list từ (x0,y0,x1,y1,text,block,line,word)."""
    d = fitz.open()
    p = d.new_page(width=page_rect.width, height=page_rect.height)
    from PIL import Image
    bio = io.BytesIO()
    Image.fromarray(img_gray).save(bio, "PNG")
    p.insert_image(p.rect, stream=bio.getvalue())
    tp = p.get_textpage_ocr(language="vie", dpi=OCR_DPI, full=True, tessdata=tessdata_dir())
    # Tự tách từ theo khoảng trống THẬT giữa các chữ (thư viện hay bỏ sót dấu cách sau chữ có dấu,
    # vd "Kếhoạch", "Sốlượng")
    raw = p.get_text("rawdict", textpage=tp)
    words = []
    for bi, b in enumerate(raw.get("blocks", [])):
        for li, ln in enumerate(b.get("lines", [])):
            chars = [c for sp in ln["spans"] for c in sp.get("chars", [])]
            if not chars:
                continue
            lh = max(1.0, ln["bbox"][3] - ln["bbox"][1])
            cur, wi, prev = [], 0, None
            for c in chars:
                gap = (c["bbox"][0] - prev["bbox"][2]) if prev is not None else 0
                # trong 1 từ, thư viện chia đều khung chữ (khe = 0) -> khe dương là ranh giới từ
                if c["c"].isspace() or (prev is not None and gap > max(0.6, lh * 0.04)):
                    if cur:
                        words.append(_mkword(cur, bi, li, wi))
                        wi += 1
                        cur = []
                if not c["c"].isspace():
                    cur.append(c)
                prev = c
            if cur:
                words.append(_mkword(cur, bi, li, wi))
    return words


def _mkword(chars, bi, li, wi):
    return (min(c["bbox"][0] for c in chars), min(c["bbox"][1] for c in chars),
            max(c["bbox"][2] for c in chars), max(c["bbox"][3] for c in chars),
            "".join(c["c"] for c in chars), bi, li, wi)


_PUNCT = set("-–—.,;:/()+*%\"'“”‘’…!?")


def _good_word(t):
    if t and all(ch in _PUNCT for ch in t) and len(t) <= 3:
        return True                      # dấu gạch, chấm, phẩy... đứng riêng
    al = sum(ch.isalnum() for ch in t)
    return al >= 1 and al >= len(t) * 0.5


_LOW = "a-zàáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ"
_UP = _LOW.upper()


def _fix_tokens(t):
    """Sửa lỗi dính chữ hay gặp của OCR (an toàn): 'cứKế' -> 'cứ Kế', 'số45' -> 'số 45'."""
    t = re.sub(r"([%s])([%s])" % (_LOW, _UP), r"\1 \2", t)
    t = re.sub(r"(\b[%s]{2,})(\d)" % _LOW, r"\1 \2", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


_FONTS = {}


def _ref_fonts():
    """Font Times New Roman (thường / đậm) để đo cỡ chữ theo bề rộng."""
    if not _FONTS:
        try:
            import glyphfix
            fm = glyphfix._default_fm()
            fam = next((f for f in ("Times New Roman", "Liberation Serif") if fm and f in fm.families), None)
            if fam:
                _FONTS["regular"] = fitz.Font(fontfile=fm.resolve(fam, False, False)[0])
                _FONTS["bold"] = fitz.Font(fontfile=fm.resolve(fam, True, False)[0])
        except Exception:
            pass
        if not _FONTS:
            _FONTS["regular"] = fitz.Font("tiro")
            _FONTS["bold"] = fitz.Font("tibo")
    return _FONTS


def analyze(page, dpi=OCR_DPI):
    """-> dict(lines=[...như convert._page_lines...], tables=[ScanTable], segs=(hs,vs), pieces=[(rect,png)])"""
    import cv2
    from PIL import Image
    rgb, _angle = _deskew(_render(page, dpi))
    H, W = rgb.shape[:2]
    scale = page.rect.width / W
    gray, dark, color = _masks(rgb)
    hor, ver = _lines(dark, dpi)
    tables, tmask, segs = _tables(hor, ver, scale, dpi)
    # ảnh cho OCR: xoá kẻ bảng + mực màu
    # ảnh đưa vào OCR: chữ đen trên nền trắng sạch (đã bỏ nền ô màu, kẻ bảng, dấu đỏ, chữ ký)
    k = max(3, int(dpi * 0.012)) | 1
    tm_big = cv2.dilate(tmask.astype(np.uint8), np.ones((k, k), np.uint8)) > 0   # xoá cả vết kẻ bảng
    keep = dark & ~tm_big & ~(cv2.dilate(color.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
    ocr_img = np.full(gray.shape, 255, np.uint8)
    ocr_img[keep] = np.minimum(gray[keep], 90)
    words = _ocr_words(page.rect, ocr_img)
    words = [w for w in words if w[4].strip() and _good_word(w[4])]
    # bỏ "chữ" 1 ký tự nằm sát đường kẻ dọc của bảng (vết kẻ bị đọc thành i, l, |)
    vxs = [x for (_a, _b, x, _w) in segs[1]]
    words = [w for w in words if not (len(w[4]) <= 2 and w[4] in ("i", "l", "I", "|", "!", "1", "ỉ", "ì", "í", "ii", "li", "il")
                                      and any(abs((w[0] + w[2]) / 2 - x) < 4 for x in vxs))]
    # ---- ghép từ thành dòng
    from collections import OrderedDict
    groups = OrderedDict()
    for w in words:
        groups.setdefault((w[5], w[6]), []).append(w)
    lines = []
    sizes = []
    for ws in groups.values():
        ws.sort(key=lambda w: w[0])
        # tách dòng nếu 2 từ cách nhau quá xa (2 cột khác nhau bị OCR gộp)
        chunks, cur = [], [ws[0]]
        for w in ws[1:]:
            hgt = max(1.0, cur[-1][3] - cur[-1][1])
            if w[0] - cur[-1][2] > hgt * 2.2:
                chunks.append(cur)
                cur = [w]
            else:
                cur.append(w)
        chunks.append(cur)
        for ch in chunks:
            x0 = min(w[0] for w in ch); y0 = min(w[1] for w in ch)
            x1 = max(w[2] for w in ch); y1 = max(w[3] for w in ch)
            text = " ".join(w[4] for w in ch)
            lines.append({"bbox": fitz.Rect(x0, y0, x1, y1), "text": text, "words": ch})
            sizes.append((y1 - y0) / 1.13)
    # ---- cỡ chữ: đo chiều cao phần thân chữ (x-height / chiều cao chữ hoa) trên ảnh
    def measure(ln):
        b = ln["bbox"]
        y0, y1 = int(b.y0 / scale), int(b.y1 / scale) + 1
        x0, x1 = int(b.x0 / scale), int(b.x1 / scale) + 1
        sub = keep[y0:y1, x0:x1]
        if sub.size == 0 or sub.sum() < 10:
            return None, None
        prof = sub.sum(axis=1).astype(np.float64)
        core_rows = np.where(prof >= prof.max() * 0.45)[0]
        band = (core_rows.max() - core_rows.min() + 1) if len(core_rows) else sub.shape[0]
        letters = [ch for ch in ln["text"] if ch.isalpha()]
        upper = sum(ch.isupper() for ch in letters) / max(1, len(letters))
        k = 0.662 if upper > 0.6 else 0.448            # Times New Roman: chữ hoa / x-height
        size_pt = band * scale / k
        # độ dày nét: trung bình độ dài các đoạn mực theo hàng ngang trong phần thân chữ
        rows = sub[core_rows.min():core_rows.max() + 1] if len(core_rows) else sub
        r8 = rows.astype(np.int8)
        d = np.diff(np.concatenate([np.zeros((r8.shape[0], 1), np.int8), r8,
                                    np.zeros((r8.shape[0], 1), np.int8)], axis=1), axis=1)
        nruns = max(1, int((d == 1).sum()))
        stroke = rows.sum() / nruns * scale / max(size_pt, 1)
        return size_pt, stroke

    meas = [measure(ln) for ln in lines]
    # cỡ chữ chính xác hơn: so BỀ RỘNG từng từ trên ảnh với bề rộng của chính từ đó
    # khi viết bằng Times New Roman 1pt (không phụ thuộc chữ hoa / chữ thường / chữ số)
    fonts = _ref_fonts()
    strokes0 = [m[1] for m in meas if m[1]]
    smed0 = float(np.median(strokes0)) if strokes0 else 0.0
    new = []
    for ln, (sz, st) in zip(lines, meas):
        isbold = bool(st and smed0 and st > max(smed0 * 1.30, 0.105))
        f = fonts.get("bold" if isbold else "regular") if fonts else None
        if f is not None:
            wpx = sum(w[2] - w[0] for w in ln["words"])
            wun = sum(f.text_length(w[4], 1.0) for w in ln["words"])
            if wun > 0 and sum(len(w[4]) for w in ln["words"]) >= 3:
                sz = wpx / wun
            else:
                sz = None      # quá ngắn (vd số "12") -> dùng cỡ chữ phổ biến của trang
        new.append((sz, st))
    meas = new
    vals = [m[0] for m in meas if m[0]]
    med = float(np.median(vals)) if vals else 13.0
    strokes = [m[1] for m in meas if m[1]]
    smed = float(np.median(strokes)) if strokes else 0.0
    std = [10, 10.5, 11, 12, 13, 14, 15, 16, 18, 20, 22, 24, 26, 28]

    def norm_size(v):
        if v is None:
            v = med
        if abs(v - med) < 1.3:
            v = med
        return min(std, key=lambda x: abs(x - v))

    out = []
    for ln, (sz, st) in zip(lines, meas):
        b = ln["bbox"]
        size = norm_size(sz)
        bold = bool(st and smed and st > max(smed * 1.30, 0.105))
        base = b.y1 - 0.20 * size
        span = {"text": _fix_tokens(ln["text"]), "bbox": tuple(b), "origin": (b.x0, base), "size": size,
                "font": "Times New Roman" + ("-Bold" if bold else ""), "flags": 16 if bold else 0,
                "color": 0, "ascender": 0.891, "descender": -0.216, "alpha": 255}
        raw = {"bbox": tuple(b), "spans": [span], "dir": (1, 0), "wmode": 0}
        out.append({"bbox": fitz.Rect(b), "spans": [span], "raw": raw, "ocr": True})
    # ---- phần không phải chữ -> ảnh trong suốt (con dấu, chữ ký, logo, gạch trang trí)
    ink = (dark | color) & ~tmask
    textmask = np.zeros_like(ink)
    for w in words:
        x0, y0, x1, y1 = [int(v / scale) for v in w[:4]]
        textmask[max(0, y0 - 2):y1 + 3, max(0, x0 - 2):x1 + 3] = True
    ink &= ~(textmask & ~color)          # bỏ chữ đen đã nhận dạng, giữ mực màu (dấu đỏ đè lên chữ)
    ink_u8 = ink.astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(
        cv2.dilate(ink_u8, np.ones((int(dpi * 0.04) or 3,) * 2, np.uint8)), connectivity=8)
    pieces = []
    min_area = (dpi * 0.06) ** 2
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        sub = ink[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == i)
        cnt = int(sub.sum())
        if cnt < min_area * 0.35 or (w < dpi * 0.05 and h < dpi * 0.05):
            continue                   # bụi, mảnh chữ vụn
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[..., :3] = rgb[y:y + h, x:x + w]
        rgba[..., 3] = np.where(sub, 255, 0).astype(np.uint8)
        bio = io.BytesIO()
        Image.fromarray(rgba, "RGBA").save(bio, "PNG")
        pieces.append((fitz.Rect(x * scale, y * scale, (x + w) * scale, (y + h) * scale), bio.getvalue()))
    return {"lines": out, "tables": tables, "segs": segs, "pieces": pieces}
