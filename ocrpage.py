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
    cands.append(os.path.join(os.getcwd(), "tessdata"))
    if os.environ.get("TESSDATA_PREFIX"):
        cands.append(os.environ["TESSDATA_PREFIX"])
        cands.append(os.path.join(os.environ["TESSDATA_PREFIX"], "tessdata"))
    for d in cands:
        f = os.path.join(d, "vie.traineddata") if d else ""
        # file hỏng/rỗng (vd. tải lỗi, con trỏ Git LFS) thì bỏ qua
        if f and os.path.isfile(f) and os.path.getsize(f) > 1000000:
            return d
    return None


def ocr_dir():
    """Thư mục dữ liệu dùng để NHẬN DẠNG: ưu tiên bản 'fast' (nhanh gấp ~3-4 lần, độ chính xác tương đương
    với văn bản hành chính); không có thì dùng bản 'best'."""
    d = tessdata_dir()
    if d:
        f = os.path.join(d, "fast", "vie.traineddata")
        if os.path.isfile(f) and os.path.getsize(f) > 300000:
            return os.path.join(d, "fast")
    return d


def tessdata_report():
    """Mô tả các chỗ đã tìm vie.traineddata (để báo lỗi rõ ràng)."""
    out = []
    for d in [os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata"),
              os.path.join(os.getcwd(), "tessdata"), os.environ.get("TESSDATA_PREFIX", "")]:
        if not d:
            continue
        f = os.path.join(d, "vie.traineddata")
        out.append("%s=%s" % (f, os.path.getsize(f) if os.path.isfile(f) else "khong co"))
    return "; ".join(out)


def ocr_available():
    return tessdata_dir() is not None and hasattr(fitz.Page, "get_textpage_ocr")


# =============================================================================
#  NHẬN BIẾT TRANG SCAN
# =============================================================================
def _image_cover(page):
    area = page.rect.get_area()
    cover = 0.0
    try:
        for info in page.get_image_info():
            r = fitz.Rect(info["bbox"]) & page.rect
            cover += r.get_area()
    except Exception:
        return 0.0
    return cover / max(1.0, area)


def _textless(page):
    """Bản sao của trang đã xoá hết lớp chữ (giữ ảnh, nét vẽ) -> (doc_tạm, trang_tạm)."""
    tmp = fitz.open()
    tmp.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
    tp = tmp[0]
    tp.add_redact_annot(tp.rect, fill=False)
    try:
        tp.apply_redactions(images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
                            graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
                            text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0))
    except TypeError:
        tp.apply_redactions(images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0))
    return tmp, tp


def text_layer_over_scan(page, words=None):
    """Trang SCAN đã có sẵn lớp chữ (máy scan / phần mềm OCR tạo): chữ ẩn, hoặc chữ nằm dưới / trên
    ảnh chụp vốn đã chứa chính dòng chữ đó. Nếu giữ ảnh + chữ thì bên Word bị chữ chồng lên ảnh."""
    if _image_cover(page) < 0.4:
        return False
    if words is None:
        try:
            words = [w for w in page.get_text("words") if w[4].strip()]
        except Exception:
            return False
    if not words:
        return False
    # 1) phần lớn chữ là chữ ẩn (render mode 3 / trong suốt)
    try:
        tot = inv = 0
        for sp in page.get_texttrace():
            k = len(sp.get("chars", ()))
            tot += k
            if sp.get("type") == 3 or sp.get("opacity", 1) == 0:
                inv += k
        if tot and inv >= 0.6 * tot:
            return True
    except Exception:
        pass
    # 2) ảnh nền (đã bỏ lớp chữ) vẫn có nét chữ ngay tại vị trí các từ -> chữ bị trùng
    try:
        tmp, tp = _textless(page)
        dpi = 60
        pm = tp.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
        g = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.stride)[:, :pm.width]
        sc = dpi / 72.0
        hit = n = 0
        for w in words:
            r = fitz.Rect(w[:4])
            if r.is_empty or r.width < 4:
                continue
            x0, x1 = int(r.x0 * sc), int(r.x1 * sc) + 1
            y0, y1 = int((r.y0 + r.height * 0.2) * sc), int((r.y1 - r.height * 0.2) * sc) + 1
            sub = g[max(0, y0):y1, max(0, x0):x1]
            if sub.size == 0:
                continue
            n += 1
            if (sub < 140).mean() > 0.06:
                hit += 1
        return n >= 5 and hit >= 0.6 * n
    except Exception:
        return False


def is_scanned(page):
    """Trang scan: gần như không có lớp chữ nhưng có ảnh phủ phần lớn trang,
    hoặc có lớp chữ nhưng chữ đó chỉ là lớp OCR ẩn / trùng với chữ trong ảnh scan."""
    try:
        words = [w for w in page.get_text("words") if w[4].strip()]
    except Exception:
        words = []
    if len(words) >= 5:
        return text_layer_over_scan(page, words)
    return _image_cover(page) >= 0.5


# =============================================================================
#  XỬ LÝ ẢNH
# =============================================================================
def _render(page, dpi, keep_text=False):
    tmp = None
    try:
        if not keep_text and page.get_text("words"):
            tmp, page = _textless(page)      # chỉ lấy ảnh scan, bỏ lớp chữ có sẵn (tránh chữ đúp)
    except Exception:
        pass
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

        # đường kẻ chạy gần hết bề ngang / bề dọc bảng -> coi là kẻ suốt (bản scan hay đứt nét ở ô hẹp)
        full_h = {yy: sub_h[max(0, yy - 3):yy + 4, cols[0]:cols[-1]].any(axis=0).mean() > 0.8 for yy in rows}
        full_v = {xx: sub_v[rows[0]:rows[-1], max(0, xx - 3):xx + 4].any(axis=1).mean() > 0.8 for xx in cols}

        def has_h(yy, x0, x1):   # đường ngang tại yy trên đoạn [x0,x1]
            band = sub_h[max(0, yy - 3):yy + 4, x0:x1].any(axis=0)
            return band.mean() > (0.3 if full_h.get(yy) else 0.6) if band.size else False

        def has_v(xx, y0, y1):
            band = sub_v[y0:y1, max(0, xx - 3):xx + 4].any(axis=1)
            return band.mean() > (0.3 if full_v.get(xx) else 0.6) if band.size else False

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
def _ocr_words(page_rect, img_gray, dpi=None):
    """OCR ảnh (đã xoá kẻ bảng + phần màu). Trả về list từ (x0,y0,x1,y1,text,block,line,word)."""
    d = fitz.open()
    p = d.new_page(width=page_rect.width, height=page_rect.height)
    from PIL import Image
    bio = io.BytesIO()
    Image.fromarray(img_gray).save(bio, "PNG")
    p.insert_image(p.rect, stream=bio.getvalue())
    tp = p.get_textpage_ocr(language="vie", dpi=dpi or OCR_DPI, full=True, tessdata=ocr_dir())
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


_NARROW_OK = set("1lIi|!.,:;'`-()[]/\\")


def _min_width(text, h):
    """Bề rộng tối thiểu hợp lý của 1 từ cao h (chữ hẹp như l, i, 1 tính ít hơn)."""
    return h * sum(0.08 if c in _NARROW_OK else 0.2 for c in text if not c.isspace())


def _baseline(mask, b, scale):
    """Đường chân chữ thật của 1 dòng (đo trên ảnh: hàng cuối còn đậm mực, bỏ qua phần đuôi g, p, y)."""
    y0, y1 = int(b.y0 / scale), int(b.y1 / scale) + 1
    x0, x1 = int(b.x0 / scale), int(b.x1 / scale) + 1
    sub = mask[max(0, y0):y1, max(0, x0):x1]
    if sub.size == 0:
        return None
    prof = sub.sum(axis=1)
    if prof.max() <= 0:
        return None
    on = prof >= prof.max() * 0.35
    runs, st = [], None
    for i, v in enumerate(on):
        if v and st is None:
            st = i
        elif not v and st is not None:
            runs.append((st, i))
            st = None
    if st is not None:
        runs.append((st, len(on)))
    if not runs:
        return None
    # khung dòng của bộ nhận dạng có khi cao gấp đôi, lấn sang dòng kề -> bỏ dải mực bị cắt ở mép khung,
    # lấy dải mực chính (dày nhất) của chính dòng này
    inner = [r for r in runs if r[0] > 0 and r[1] < len(on)] or runs
    a, b2 = max(inner, key=lambda r: (r[1] - r[0], prof[r[0]:r[1]].sum()))
    return (max(0, y0) + b2) * scale


def _ocr_missed(page_rect, ocr_img, keep, words, scale, dpi):
    import cv2
    H, W = keep.shape
    cov = np.zeros((H, W), np.uint8)
    for w in words:
        x0, y0, x1, y1 = [int(v / scale) for v in w[:4]]
        cov[max(0, y0):y1 + 1, max(0, x0):x1 + 1] = 1
    rest = (keep & (ocr_img < 200) & (cov == 0)).astype(np.uint8)
    if rest.sum() < dpi:
        return []
    kx, ky = max(3, int(dpi * 0.10)), max(1, int(dpi * 0.012))
    blob = cv2.dilate(rest, np.ones((ky, kx), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(blob, connectivity=8)
    bl = []
    for i in range(1, n):
        x, y, w, h, _a = st[i]
        if w < dpi * 0.12 or h < dpi * 0.05 or h > dpi * 0.45:
            continue
        if rest[y:y + h, x:x + w].sum() < dpi * 0.3:
            continue
        bl.append([x, y, x + w, y + h])
    # các mảnh chưa nhận dạng cùng 1 hàng, cách nhau không xa (phần giữa bị chữ rác che) -> 1 dòng
    bl.sort(key=lambda b: b[0])
    mergedb = []
    for b in bl:
        for m in mergedb:
            ov = min(m[3], b[3]) - max(m[1], b[1])
            if ov > 0.5 * min(m[3] - m[1], b[3] - b[1]) and b[0] - m[2] < dpi * 1.2:
                m[0], m[1], m[2], m[3] = min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3])
                break
        else:
            mergedb.append(list(b))
    out = []
    k = 0
    for (x, y, x2, y2) in mergedb:
        w, h = x2 - x, y2 - y
        if w < dpi * 0.25:
            continue
        # cắt cả dòng (mở rộng lên / xuống để lấy đủ chữ bị che một phần)
        my, mx = int(h * 0.45) + 2, int(dpi * 0.04)
        Y0, Y1 = max(0, y - my), min(H, y + h + my)
        X0, X1 = max(0, x - mx), min(W, x + w + mx)
        crop = np.full((Y1 - Y0 + 2 * mx, X1 - X0 + 2 * mx), 255, np.uint8)
        crop[mx:mx + Y1 - Y0, mx:mx + X1 - X0] = ocr_img[Y0:Y1, X0:X1]
        r = fitz.Rect(0, 0, crop.shape[1] * scale, crop.shape[0] * scale)
        got = [w for w in _ocr_words(r, crop, dpi) if w[4].strip() and _good_word(w[4])]
        ox, oy = (X0 - mx) * scale, (Y0 - mx) * scale
        for wd in got:
            out.append((wd[0] + ox, wd[1] + oy, wd[2] + ox, wd[3] + oy, wd[4], 1000 + k, wd[6], wd[7]))
        k += 1
        if k > 40:
            break
    return out


def _fix_digit_bars(words):
    """'|' / 'l' / 'I' đứng sát ngay trước chữ số (vd "| 0" của số "10") -> chữ số 1."""
    out = list(words)
    i = 0
    res = []
    while i < len(out):
        w = out[i]
        if w[4] in ("|", "l", "I", "!") and i + 1 < len(out):
            n = out[i + 1]
            if n[4][:1].isdigit() and (n[5], n[6]) == (w[5], w[6]) and 0 <= n[0] - w[2] < 0.35 * (n[3] - n[1]):
                res.append((w[0], min(w[1], n[1]), n[2], max(w[3], n[3]), "1" + n[4]) + tuple(n[5:]))
                i += 2
                continue
        res.append(w)
        i += 1
    return res


def _fix_numbering(lines, cells):
    """Cột số thứ tự trong bảng ("1.1", "2.3"...): số bị đọc mất dấu chấm ("11", "22", "42 —") -> "1.1"..."""
    if not cells:
        return lines
    cols = {}
    for ln in lines:
        c = ln["bbox"]
        cx = (c.x0 + c.x1) / 2
        cols.setdefault(round(cx / 25), []).append(ln)
    for group in cols.values():
        nums = [ln for ln in group if re.match(r"^\d{1,2}\.\d{1,2}\.?$", ln["text"].strip())]
        if len(nums) < 3:
            continue
        for ln in group:
            m = re.match(r"^(\d)(\d)\W*$", ln["text"].strip())
            if m:
                ln["text"] = "%s.%s" % (m.group(1), m.group(2))
    return lines


def _dot_leaders(mask, dpi):
    """Các dòng chấm ".........." trên ảnh: nhiều chấm nhỏ cùng hàng, đều nhau. -> list (x0,y0,x1,y1,[ô chấm])."""
    import cv2
    n, _lab, st, _c = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    dmax = max(3, int(dpi * 0.032))        # chấm cỡ <= ~2.3pt
    dots = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if w <= dmax and h <= dmax and a >= 2 and 0.4 <= (w / max(1, h)) <= 2.5:
            dots.append((x + w / 2.0, y + h / 2.0, x, y, x + w, y + h))
    dots.sort(key=lambda d: (round(d[1] / 4), d[0]))
    out, used = [], set()
    by_row = {}
    for d in dots:
        by_row.setdefault(int(d[1] // max(2, dmax)), []).append(d)
    rows = sorted(by_row)
    merged = []
    for r in rows:
        merged.extend(by_row[r])
    merged.sort(key=lambda d: (d[1], d[0]))
    # gom chấm cùng hàng (lệch tâm <= 1/2 cỡ chấm), liên tiếp cách đều
    groups = []
    for d in sorted(dots, key=lambda d: d[0]):
        for g in groups:
            if abs(g[-1][1] - d[1]) <= dmax * 0.6 and 0 < d[0] - g[-1][0] <= dmax * 6:
                g.append(d)
                break
        else:
            groups.append([d])
    for g in groups:
        if len(g) < 6:
            continue
        xs = [d[0] for d in g]
        gaps = np.diff(xs)
        if gaps.std() > max(2.0, gaps.mean() * 0.5):
            continue
        out.append((min(d[2] for d in g), min(d[3] for d in g), max(d[4] for d in g), max(d[5] for d in g),
                    [(int(d[2]) - 1, int(d[3]) - 1, int(d[4]) + 2, int(d[5]) + 2) for d in g]))
    return out


def _split_stacked(ch, ink):
    """1 cụm từ mà các từ trùng nhau theo chiều ngang = thực ra 2 dòng chồng nhau (vd khối ghi chú góc phải
    "BH theo QĐ số" / "4868/QĐ-BCA-V06" bị bộ nhận dạng gộp) -> tách thành 2 cụm, mỗi cụm 1 dòng."""
    if ink is None or len(ch) < 2:
        return [ch]
    ws_ = sorted(ch, key=lambda w: -(w[2] - w[0]))
    sets = [[], []]
    for w in ws_:
        clash0 = any(min(o[2], w[2]) - max(o[0], w[0]) > 0.3 * min(o[2] - o[0], w[2] - w[0]) for o in sets[0])
        (sets[1] if clash0 else sets[0]).append(w)
    if not sets[1]:
        return [ch]
    if any(min(o[2], w[2]) - max(o[0], w[0]) > 0.3 * min(o[2] - o[0], w[2] - w[0])
           for i, o in enumerate(sets[1]) for w in sets[1][i + 1:]):
        return [ch]                       # chồng 3 lớp trở lên -> không đoán
    y0, y1 = min(w[1] for w in ch), max(w[3] for w in ch)

    def own(st, other):
        xr = []
        for w in st:
            segs = [(w[0], w[2])]
            for o in other:
                nxt = []
                for a, b in segs:
                    if o[2] <= a or o[0] >= b:
                        nxt.append((a, b))
                    else:
                        if o[0] > a:
                            nxt.append((a, o[0]))
                        if o[2] < b:
                            nxt.append((o[2], b))
                segs = nxt
            xr += [(a, b) for a, b in segs if b - a > 1]
        return xr
    c0, c1 = ink(own(sets[0], sets[1]), y0, y1), ink(own(sets[1], sets[0]), y0, y1)
    if (c0 is None) != (c1 is None):
        # 1 nhóm nằm lọt trong bề ngang nhóm kia: suy ra từ tâm mực chung của cả vùng
        cm = ink([(min(w[0] for w in ch), max(w[2] for w in ch))], y0, y1)
        if cm is None:
            return [ch]
        known = c0 if c0 is not None else c1
        other = 2 * cm - known
        c0, c1 = (known, other) if c0 is not None else (other, known)
    if c0 is None or c1 is None or abs(c0 - c1) < 0.2 * (y1 - y0):
        return [ch]
    mid = (c0 + c1) / 2
    up, dn = (sets[0], sets[1]) if c0 < c1 else (sets[1], sets[0])
    fix = lambda st, a, b: sorted([(w[0], a, w[2], b) + tuple(w[4:]) for w in st], key=lambda w: w[0])
    return [fix(up, y0, mid), fix(dn, mid, y1)]


def _rows_from_ocr(words, cells=None, ink=None):
    """Từ nhận dạng -> các dòng chữ (dict bbox, text, words):
    - gom các từ cùng hàng theo toạ độ (1 dòng bị cắt thành nhiều mảnh -> ghép lại đúng thứ tự trái -> phải)
    - bỏ từ đọc TRÙNG (2 mảnh chồng lên nhau -> giữ mảnh thuộc dòng dài hơn)
    - bỏ "chữ rác": từ quá thấp (vết gạch chân), hẹp bất thường, hàng chữ lẻ tẻ kẹp giữa 2 dòng thật
    - chữ ở 2 ô bảng khác nhau không bao giờ chung 1 dòng; tách 2 cột chung 1 hàng khi cách nhau xa"""
    if not words:
        return []
    from collections import Counter
    src_len = Counter((w[5], w[6]) for w in words)
    hs = sorted(w[3] - w[1] for w in words)
    hmed = hs[len(hs) // 2]
    ws = [w for w in words if (w[3] - w[1]) >= 0.45 * hmed           # vết gạch chân / nét lẻ bị đọc thành chữ
          and (w[2] - w[0]) >= _min_width(w[4], min(w[3] - w[1], hmed))]   # "chữ" hẹp bất thường
    # bỏ từ đọc TRÙNG chỗ (chồng quá nửa theo cả 2 chiều, với cả 2 từ) -> giữ từ thuộc dòng dài hơn
    ws.sort(key=lambda w: -src_len[(w[5], w[6])])
    kept = []
    for w in ws:
        dup = False
        for k in kept:
            ox = min(k[2], w[2]) - max(k[0], w[0])
            oy = min(k[3], w[3]) - max(k[1], w[1])
            if ox > 0.5 * (w[2] - w[0]) and ox > 0.5 * (k[2] - k[0]) and oy > 0.5 * min(w[3] - w[1], k[3] - k[1]):
                dup = True
                break
        if not dup:
            kept.append(w)
    ws = kept
    cells = cells or []

    def cell_of(w):
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        best = -1
        for i, c in enumerate(cells):
            if c.x0 <= cx <= c.x1 and c.y0 <= cy <= c.y1 and (best < 0 or c.get_area() < cells[best].get_area()):
                best = i
        return best

    # gom hàng: cùng 1 dòng của bộ nhận dạng -> cùng hàng; các mảnh khác -> cùng hàng nếu tâm gần như trùng
    rows = []
    for w in sorted(ws, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        cy, h = (w[1] + w[3]) / 2, w[3] - w[1]
        ci = cell_of(w)
        best = None
        for r in rows:
            if r["cell"] != ci:
                continue
            if (w[5], w[6]) in r["src"] or abs(cy - r["cy"]) < 0.15 * max(h, r["y1"] - r["y0"]):
                best = r
                break
        if best is None:
            rows.append({"y0": w[1], "y1": w[3], "cy": cy, "w": [w], "cell": ci, "src": {(w[5], w[6])}})
        else:
            best["w"].append(w)
            best["src"].add((w[5], w[6]))
            best["y0"], best["y1"] = min(best["y0"], w[1]), max(best["y1"], w[3])
            n = len(best["w"])
            best["cy"] = (best["cy"] * (n - 1) + cy) / n
    # hàng chỉ toàn mảnh 1-3 ký tự, kẹp giữa 2 hàng chữ thật cùng ô (chồng lên cả trên lẫn dưới) -> rác
    def wl(w):         # số chữ / số trong 1 từ (bỏ dấu câu)
        return sum(1 for c in w[4] if c.isalnum())

    def real(r):       # hàng chữ thật: có từ dài, hoặc nhiều từ 2+ chữ
        return any(wl(w) >= 4 for w in r["w"]) or sum(1 for w in r["w"] if wl(w) >= 2) >= 3
    drop = set()
    for i, r in enumerate(rows):
        if real(r) or any(wl(w) > 3 for w in r["w"]):
            continue
        h = r["y1"] - r["y0"]
        up = any(o is not r and o["cell"] == r["cell"] and real(o) and o["y0"] < r["y0"]
                 and min(o["y1"], r["y1"]) - max(o["y0"], r["y0"]) > 0.25 * h for o in rows)
        dn = any(o is not r and o["cell"] == r["cell"] and real(o) and o["y1"] > r["y1"]
                 and min(o["y1"], r["y1"]) - max(o["y0"], r["y0"]) > 0.25 * h for o in rows)
        if up and dn:
            drop.add(i)
    out = []
    for i, r in enumerate(rows):
        if i in drop:
            continue
        rw = sorted(r["w"], key=lambda w: w[0])
        chunks, cur = [], [rw[0]]
        for w in rw[1:]:
            hgt = max(1.0, max(cur[-1][3] - cur[-1][1], w[3] - w[1]))
            if w[0] - cur[-1][2] > hgt * 2.2:
                chunks.append(cur)
                cur = [w]
            else:
                cur.append(w)
        chunks.append(cur)
        chunks = [c2 for c in chunks for c2 in _split_stacked(c, ink)]
        for ch in chunks:
            text = " ".join(w[4] for w in ch)
            core = [c for c in text if not c.isspace()]
            if not any(c.isalnum() for c in core) and not (len(core) >= 3 and set(core) <= set(".…")):
                continue
            x0 = min(w[0] for w in ch); y0 = min(w[1] for w in ch)
            x1 = max(w[2] for w in ch); y1 = max(w[3] for w in ch)
            out.append({"bbox": fitz.Rect(x0, y0, x1, y1), "text": text, "words": ch})
    out.sort(key=lambda l: (l["bbox"].y0, l["bbox"].x0))
    return out


def analyze(page, dpi=OCR_DPI, keep_text=False):
    """-> dict(lines=[...như convert._page_lines...], tables=[ScanTable], segs=(hs,vs), pieces=[(rect,png)])"""
    import cv2
    from PIL import Image
    rgb, _angle = _deskew(_render(page, dpi, keep_text))
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
    # gạch chân / gạch ngang ngoài bảng (dưới Quốc hiệu, dưới tên văn bản) làm bộ nhận dạng đọc sai cả dòng
    # -> bỏ khỏi ảnh nhận dạng (vẫn giữ trên trang dưới dạng hình)
    ul = cv2.dilate(hor.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    keep_ocr = keep & ~ul
    if os.environ.get("SUAPDF_PREP") == "gray":
        ocr_img = gray.copy()
        ocr_img[tm_big] = 255
    else:
        ocr_img = np.full(gray.shape, 255, np.uint8)
        ocr_img[keep_ocr] = np.minimum(gray[keep_ocr], 90)
    # dòng chấm "............" (chỗ điền) làm bộ nhận dạng đọc hỏng cả dòng -> xoá khỏi ảnh nhận dạng,
    # nhận dạng xong thì thêm lại thành chữ "....." đúng chỗ
    leaders = _dot_leaders(keep, dpi)
    for (x0, y0, x1, y1, comps) in leaders:
        for (cx0, cy0, cx1, cy1) in comps:
            ocr_img[cy0:cy1, cx0:cx1] = 255
    words = _ocr_words(page.rect, ocr_img)
    words = _fix_digit_bars(words)
    words = [w for w in words if w[4].strip() and _good_word(w[4])]
    # bộ nhận dạng đôi khi BỎ SÓT cả dòng (dòng sát nhau, có gạch chân...) -> tìm vùng mực chữ chưa được
    # nhận dạng, cắt riêng từng dòng đó ra nhận dạng lại
    try:
        if os.environ.get("SUAPDF_MISS") == "1":      # (thử nghiệm, mặc định tắt)
            words += _ocr_missed(page.rect, ocr_img, keep_ocr, words, scale, dpi)
    except Exception:
        pass
    if leaders:
        hs_ = sorted(w[3] - w[1] for w in words) or [12.0]
        hmed_ = hs_[len(hs_) // 2]
        for k, (x0, y0, x1, y1, comps) in enumerate(leaders):
            X0, X1, Y = x0 * scale, x1 * scale, y1 * scale
            n = max(3, int(round((X1 - X0) / (0.25 * hmed_ / 1.13))))
            words.append((X0, Y - hmed_ * 0.78, X1, Y + hmed_ * 0.22, "." * n, -1, k, 0))
    # bỏ "chữ" 1 ký tự nằm sát đường kẻ dọc của bảng (vết kẻ bị đọc thành i, l, |)
    vxs = [x for (_a, _b, x, _w) in segs[1]]
    words = [w for w in words if not (len(w[4]) <= 2 and w[4] in ("i", "l", "I", "|", "!", "1", "ỉ", "ì", "í", "ii", "li", "il")
                                      and any(abs((w[0] + w[2]) / 2 - x) < 2.5 for x in vxs))]
    # ---- ghép từ thành dòng THEO VỊ TRÍ THẬT trên trang (không theo cách chia dòng của bộ nhận dạng,
    #      vốn hay cắt 1 dòng thành nhiều mảnh / đọc trùng / sinh "chữ rác" giữa 2 dòng sát nhau)
    def ink_cy(xr, y0, y1):
        """Tâm theo chiều dọc của mực chữ trong các khoảng x (toạ độ trang), giữa y0..y1."""
        Y0, Y1 = max(0, int(y0 / scale)), int(y1 / scale) + 1
        tot = np.zeros(max(1, Y1 - Y0))
        for a, b in xr:
            sub = keep_ocr[Y0:Y1, max(0, int(a / scale)):int(b / scale) + 1]
            if sub.size:
                tot[:sub.shape[0]] += sub.sum(axis=1)
        if tot.sum() <= 0:
            return None
        return (Y0 + (np.arange(len(tot)) * tot).sum() / tot.sum()) * scale

    lines = _rows_from_ocr(words, [fitz.Rect(c) for t in tables for c in t.cells if c], ink_cy)
    lines = _fix_numbering(lines, [c for t in tables for c in t.cells if c])
    sizes = [(ln["bbox"].y1 - ln["bbox"].y0) / 1.13 for ln in lines]
    # ---- cỡ chữ: đo chiều cao phần thân chữ (x-height / chiều cao chữ hoa) trên ảnh
    def measure(ln):
        b = ln["bbox"]
        real_w = [w for w in ln["words"] if not set(w[4]) <= set(".…")]
        if real_w and len(real_w) < len(ln["words"]):      # bỏ dòng chấm "....." khi đo nét chữ
            b = fitz.Rect(min(w[0] for w in real_w), b.y0, max(w[2] for w in real_w), b.y1)
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
        isbold = bool(st and smed0 and st > max(smed0 * 1.15, 0.125))
        f = fonts.get("bold" if isbold else "regular") if fonts else None
        if f is not None:
            # bề rộng CẢ DÒNG so với bề rộng chữ mẫu (khung từng từ của bộ nhận dạng có thể sai, cả dòng thì đúng)
            wpx = ln["bbox"].width
            wun = f.text_length(" ".join(w[4] for w in ln["words"]), 1.0)
            if wun > 0 and sum(len(w[4]) for w in ln["words"]) >= 5:
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
        # làm tròn XUỐNG cỡ chuẩn gần nhất (tròn lên dễ làm dòng dài hơn bản gốc -> bị xuống dòng, chạy chữ)
        c = [x for x in std if x <= v + 0.2]
        return c[-1] if c else std[0]

    out = []
    for ln, (sz, st) in zip(lines, meas):
        b = ln["bbox"]
        size = norm_size(sz)
        bold = bool(st and smed and st > max(smed * 1.15, 0.125))
        base = _baseline(keep, b, scale)
        if base is None or not (b.y0 + 0.4 * (b.y1 - b.y0) <= base <= b.y1 + 1):
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


def ocr_top_words(page, frac=0.5, dpi=200, skip_body=True, keep_text=False):
    """Nhận dạng nhanh phần ĐẦU trang (tiêu đề, trích yếu, ngày tháng) -> list từ như page.get_text('words')."""
    clip = fitz.Rect(0, 0, page.rect.width, page.rect.height * frac)
    tmp = None
    src = page
    try:
        if not keep_text and page.get_text("words"):
            tmp, src = _textless(page)
    except Exception:
        pass
    pm = src.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False, clip=clip)
    g = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.stride)[:, :pm.width].copy()
    if skip_body:
        # bỏ các dòng nội dung dài hết khổ (thân văn bản) -> chỉ nhận dạng tiêu đề, trích yếu,
        # số / ngày tháng (nhanh hơn nhiều)
        try:
            import cv2
            bw = (g < min(150, int(np.percentile(g, 90)) - 60)).astype(np.uint8)
            k = max(3, int(dpi * 0.12))
            merged = cv2.dilate(bw, np.ones((max(1, int(dpi * 0.02)), k), np.uint8))
            n, _, st, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
            W = g.shape[1]
            boxes = sorted((int(st[i][1]), int(st[i][0]), int(st[i][2]), int(st[i][3])) for i in range(1, n)
                           if st[i][3] < dpi * 0.5 and st[i][2] > dpi * 0.3)
            # thân văn bản bắt đầu ở 2 dòng dài liền nhau cùng lề trái -> bỏ từ đó trở xuống
            for a, b in zip(boxes, boxes[1:]):
                if a[2] > 0.5 * W and b[2] > 0.5 * W and abs(a[1] - b[1]) < 0.015 * W \
                        and b[0] - a[0] < dpi * 0.6:
                    g[a[0]:, :] = 255
                    break
            for (y, x, w, h) in boxes:
                if w > 0.74 * W:
                    g[y:y + h, x:x + w] = 255
        except Exception:
            pass
    return [w for w in _ocr_words(clip, g, dpi) if w[4].strip()]


def page_text_broken(page):
    """Lớp chữ của trang bị hỏng (font thiếu bảng mã -> đọc ra ký tự lạ) dù chữ vẫn HIỆN trên trang."""
    try:
        import legacy
        dd = page.get_text("dict")
        texts = ["".join(s["text"] for s in l["spans"]) for b in dd["blocks"] if b.get("type", 0) == 0
                 for l in b["lines"]]
        return legacy.page_text_broken(texts)
    except Exception:
        return False


def ocr_page_words(page, dpi=300, keep_text=True):
    """Nhận dạng chữ cả trang như đang HIỆN (giữ lớp chữ hỏng để lấy hình chữ) -> list từ, toạ độ hiển thị."""
    clip = fitz.Rect(0, 0, page.rect.width, page.rect.height)
    tmp, src = None, page
    if not keep_text:      # bản scan: chỉ đọc ảnh, bỏ lớp chữ có sẵn của máy scan
        try:
            tmp, src = _textless(page)
        except Exception:
            pass
    pm = src.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
    g = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.stride)[:, :pm.width].copy()
    return [w for w in _ocr_words(clip, g, dpi) if w[4].strip() and _good_word(w[4])]


def ocr_line(page, rect, dpi=400):
    """Nhận dạng chữ trong 1 dòng (toạ độ hiển thị) -> chuỗi, hoặc '' nếu không đọc được."""
    clip = fitz.Rect(rect.x0 - 3, rect.y0 - 3, rect.x1 + 3, rect.y1 + 3) & page.rect
    if clip.is_empty:
        return ""
    pm = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False, clip=clip)
    g = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.stride)[:, :pm.width].copy()
    # thêm lề trắng để thư viện nhận dạng dòng chữ tốt hơn
    pad = int(dpi * 0.15)
    big = np.full((g.shape[0] + 2 * pad, g.shape[1] + 2 * pad), 255, np.uint8)
    big[pad:pad + g.shape[0], pad:pad + g.shape[1]] = g
    k = 72.0 / dpi
    ws = _ocr_words(fitz.Rect(0, 0, big.shape[1] * k, big.shape[0] * k), big, dpi)
    ws = sorted((w for w in ws if w[4].strip()), key=lambda w: (w[5], w[6], w[0]))
    return " ".join(w[4] for w in ws)


def overlay_text_rects(page):
    """Khung các chữ vẽ ĐÈ LÊN ảnh scan (tức chữ người dùng vừa sửa / thêm), toạ độ hiển thị."""
    try:
        log = page.get_bboxlog()
    except Exception:
        return []
    area = page.rect.get_area()
    last = -1
    for i, (k, r) in enumerate(log):
        if k == "fill-image" and (fitz.Rect(r) & page.rect).get_area() >= 0.4 * area:
            last = i
    rot = page.rotation_matrix
    return [fitz.Rect(r) * rot for k, r in log[last + 1:] if k in ("fill-text", "stroke-text")] if last >= 0 else []


def overlay_fill_rects(page):
    """Khung các vùng phủ (tẩy / phủ trắng) vẽ ĐÈ LÊN ảnh scan, toạ độ hiển thị."""
    try:
        log = page.get_bboxlog()
    except Exception:
        return []
    area = page.rect.get_area()
    last = -1
    for i, (k, r) in enumerate(log):
        if k == "fill-image" and (fitz.Rect(r) & page.rect).get_area() >= 0.4 * area:
            last = i
    rot = page.rotation_matrix
    return [fitz.Rect(r) * rot for k, r in log[last + 1:] if k == "fill-path"] if last >= 0 else []


def row_styles(page, rows, dpi=200):
    """rows: list (bbox hiển thị, list từ). -> list (cỡ chữ pt, đậm?) đo trên ảnh trang scan:
    cỡ chữ theo bề rộng từ so với Times New Roman, chữ đậm theo độ dày nét (so với cả trang)."""
    tmp, src = None, page
    try:
        if page.get_text("words"):
            tmp, src = _textless(page)
    except Exception:
        pass
    pm = src.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
    g = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.stride)[:, :pm.width]
    sc = dpi / 72.0
    paper = float(np.percentile(g, 90)) if g.size else 255.0
    ink = g < min(150, paper - 60)
    strokes = []
    for bb, _ws in rows:
        sub = ink[max(0, int(bb.y0 * sc)):int(bb.y1 * sc) + 1, max(0, int(bb.x0 * sc)):int(bb.x1 * sc) + 1]
        if sub.size == 0 or sub.sum() < 10:
            strokes.append(None)
            continue
        prof = sub.sum(axis=1)
        core_rows = np.where(prof >= prof.max() * 0.45)[0]
        rr = sub[core_rows.min():core_rows.max() + 1] if len(core_rows) else sub
        r8 = rr.astype(np.int8)
        d = np.diff(np.concatenate([np.zeros((r8.shape[0], 1), np.int8), r8,
                                    np.zeros((r8.shape[0], 1), np.int8)], axis=1), axis=1)
        strokes.append(rr.sum() / max(1, int((d == 1).sum())) / sc)     # độ dày nét (pt)
    fonts = _ref_fonts()
    out = []
    rel = [st / max(6.0, sorted(w[3] - w[1] for w in ws)[len(ws) // 2] / 1.1)
           for (bb, ws), st in zip(rows, strokes) if st]
    med = float(np.median(rel)) if rel else 0.0
    for (bb, ws), st in zip(rows, strokes):
        h = sorted(w[3] - w[1] for w in ws)[len(ws) // 2]
        size0 = max(6.0, h / 1.1)
        bold = bool(st and med and st / size0 > med * 1.25)
        f = fonts.get("bold" if bold else "regular")
        wpx = sum(w[2] - w[0] for w in ws)
        wun = sum(f.text_length(w[4], 1.0) for w in ws) if f else 0
        # khung từ do nhận dạng ôm sát nét chữ (hẹp hơn bề rộng chữ thật ~4%)
        size = wpx / wun * 1.04 if wun > 0 and sum(len(w[4]) for w in ws) >= 3 else size0
        if not (0.7 * size0 <= size <= 1.6 * size0):
            size = size0
        out.append((round(size * 2) / 2, bold))
    return out


# =============================================================================
#  NHẬN DẠNG NHIỀU TRANG SONG SONG (tận dụng nhiều nhân CPU -> chuyển file scan dài nhanh hơn nhiều)
# =============================================================================
_POOL_DOC = None


def _pool_init(data):
    global _POOL_DOC
    _POOL_DOC = fitz.open(stream=data, filetype="pdf")


def _pool_job(args):
    pno, keep = args
    try:
        return pno, analyze(_POOL_DOC[pno], keep_text=keep)
    except Exception:
        return pno, None


def analyze_many(doc, jobs, progress=None):
    """jobs: list (số trang, keep_text). -> {số trang: kết quả analyze}. Chạy song song nếu máy nhiều nhân."""
    res = {}
    if not jobs:
        return res
    ncpu = os.cpu_count() or 1
    workers = max(1, min(ncpu - 1, 6, len(jobs)))
    try:
        workers = int(os.environ.get("SUAPDF_WORKERS", workers))    # (dùng khi kiểm tra)
    except ValueError:
        pass
    done = 0
    if workers >= 2 and len(jobs) >= 3:
        try:
            import multiprocessing
            from concurrent.futures import ProcessPoolExecutor, as_completed
            ctx = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_pool_init,
                                     initargs=(doc.tobytes(),)) as ex:
                futs = [ex.submit(_pool_job, j) for j in jobs]
                for f in as_completed(futs):
                    pno, r = f.result()
                    res[pno] = r
                    done += 1
                    if progress:
                        progress(done, len(jobs))
            return res
        except Exception:
            res = {}
            done = 0
    for pno, keep in jobs:
        try:
            res[pno] = analyze(doc[pno], keep_text=keep)
        except Exception:
            res[pno] = None
        done += 1
        if progress:
            progress(done, len(jobs))
    return res
