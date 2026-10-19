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


_PAGENO_RE = re.compile(r"^[-–—(\[]*\s*(trang|page|tr\.?)?\s*\d{1,4}(\s*[/]\s*\d{1,4})?\s*[-–—)\].]*$", re.I)


def _text_line_count(page, dpi=100):
    """Đếm số DÒNG CHỮ thật trên ảnh trang (bản scan).
    Bỏ qua: vết mực lem / chữ mặt sau in hằn (mờ), dấu đỏ / chữ ký màu, số trang, bụi, bóng mép giấy."""
    import cv2
    pm = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False, annots=True)
    rgb = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.stride)[:, :pm.width * 3] \
        .reshape(pm.height, pm.width, 3)
    h, w = rgb.shape[:2]
    y0, y1 = int(h * 0.09), int(h * 0.91)       # bỏ đầu / chân trang (số trang)
    x0, x1 = int(w * 0.05), int(w * 0.95)       # bỏ bóng mép giấy
    body = rgb[y0:y1, x0:x1].astype(np.int16)
    if body.size == 0:
        return 0
    gray = body.mean(axis=2)
    sat = body.max(axis=2) - body.min(axis=2)
    paper = float(np.percentile(gray, 90))
    if paper < 60:
        return 0
    norm = gray * (255.0 / paper)
    # mực ĐEN/ĐẬM, không có màu (dấu đỏ, chữ ký xanh, vết lem màu bị loại)
    ink = ((norm < 128) & (sat < 60)).astype(np.uint8)
    if ink.sum() < 20:
        return 0
    n, _, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    px = dpi / 72.0
    comps = []
    for i in range(1, n):
        cx, cy, cw, ch, area = st[i]
        # cỡ 1 chữ / 1 âm tiết (cỡ chữ ~7–30pt); loại bụi, vạch dài, vòng dấu, khối lớn
        if ch < 3.5 * px or ch > 30 * px or cw > 120 * px or area < 6:
            continue
        comps.append((cy + ch / 2.0, cx, cx + cw, ch))
    if not comps:
        return 0
    comps.sort()
    # gom các chữ cùng hàng thành dòng
    lines = []
    for c in comps:
        for L in lines:
            if abs(c[0] - L["y"]) < max(c[3], L["h"]) * 0.5:
                L["items"].append(c)
                L["y"] = (L["y"] * (len(L["items"]) - 1) + c[0]) / len(L["items"])
                L["h"] = max(L["h"], c[3])
                break
        else:
            lines.append({"y": c[0], "h": c[3], "items": [c]})
    count = 0
    for L in lines:
        it = sorted(L["items"], key=lambda c: c[1])
        # tách thành đoạn liền (khoảng cách giữa chữ < 3 lần chiều cao)
        segs, cur = [], [it[0]]
        for c in it[1:]:
            if c[1] - cur[-1][2] > L["h"] * 3:
                segs.append(cur)
                cur = [c]
            else:
                cur.append(c)
        segs.append(cur)
        for sg in segs:
            width = sg[-1][2] - sg[0][1]
            if len(sg) >= 3 and width >= 0.08 * w:
                count += 1
                break
    return count


def _is_blank(page, g):
    """Trang trống khi tách: KHÔNG có dòng chữ nào ở phần thân trang.
    Trang chỉ có số trang, chữ / dấu đỏ in lem từ trang khác, bụi, bóng mép giấy -> trống (bỏ).
    Trang có từ 1 dòng chữ trở lên -> giữ."""
    H = page.rect.height
    try:
        words = [w for w in page.get_text("words") if w[4].strip()]
    except Exception:
        words = []
    if words:
        body = []
        for w in words:
            r = fitz.Rect(w[:4]) * page.rotation_matrix
            cy = (r.y0 + r.y1) / 2
            if H * 0.09 <= cy <= H * 0.91:
                body.append(w[4])
        txt = " ".join(body).strip()
        if txt and not _PAGENO_RE.match(txt):
            return False, 1.0
        # có lớp chữ nhưng chỉ là số trang -> vẫn kiểm tra ảnh (bản scan đã OCR)
    try:
        n = _text_line_count(page)
    except Exception:
        n = None
    if n is None:          # không có OpenCV: cách cũ theo lượng mực
        h, w = g.shape
        body = g[int(h * 0.09):int(h * 0.91), int(w * 0.06):int(w * 0.94)]
        if body.size == 0:
            return True, 0.0
        paper = float(np.percentile(body, 90))
        dark = body < min(150, paper - 60)
        ratio = float(dark.mean())
        if ratio > 0.004:
            return False, ratio
        rows = (dark.sum(axis=1) >= 3).sum()
        return rows < max(4, int(body.shape[0] * 0.012)), ratio
    return n == 0, float(n)


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


# =============================================================================
#  ĐẶT TÊN FILE THEO TIÊU ĐỀ / TRÍCH YẾU + NGÀY VĂN BẢN (không dấu)
# =============================================================================
_DOC_TYPES = ["bao cao", "quyet dinh", "ke hoach", "to trinh", "thong bao", "cong van", "giay moi",
              "bien ban", "chi thi", "nghi quyet", "huong dan", "chuong trinh", "de an", "phuong an",
              "quy che", "quy dinh", "giay xac nhan", "giay gioi thieu", "giay de nghi", "giay uy quyen",
              "thong tu", "nghi dinh", "cong dien", "danh sach", "hop dong", "don", "phieu", "bang ke",
              "ban cam ket", "ban giao", "lenh", "tham luan", "dieu le", "loi khai", "tom tat",
              "giay chung nhan", "giay phep", "so lieu", "bao cao nhanh", "thu moi", "ket luan"]
_STOP_RE = re.compile(r"^(can cu|kinh gui|thuc hien|theo|xet|nham|ngay|so\s*:|noi nhan|thuc hien)")
_DATE_RE = re.compile(r"ngay\s*(\d{1,2})\s*thang\s*(\d{1,2})\s*nam\s*(\d{4})")
_DATE2_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*((?:19|20)\d\d)(?!\d)")


def no_accent(s):
    """Bỏ dấu tiếng Việt, giữ chữ hoa/thường."""
    s = s.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    return unicodedata.normalize("NFC", "".join(ch for ch in s if unicodedata.category(ch) != "Mn"))


def _page_rows(page, ocr=True):
    """Các dòng chữ của trang: list (x0, y0, x1, y1, text) theo thứ tự trên -> dưới.
    PDF scan không có lớp chữ thì nhận dạng chữ (OCR) nếu có dữ liệu tiếng Việt."""
    words = []
    try:
        words = _dict_words(page)
    except Exception:
        try:
            words = [w for w in page.get_text("words") if w[4].strip()]
        except Exception:
            pass
    if len(words) < 8 and ocr:
        try:
            import ocrpage
            if ocrpage.ocr_available():
                words = ocrpage.ocr_top_words(page)
                return _rows_from_words(words, fitz.Identity)
        except Exception:
            pass
    return _rows_from_words(words, page.rotation_matrix)


def _dict_words(page):
    """Như page.get_text('words') nhưng chữ font mã cũ (.VnTime TCVN3, VNI-Times) đã đổi sang Unicode."""
    import legacy
    raw = page.get_text("rawdict")
    legacy.fix_dict(raw)
    words = []
    for bi, b in enumerate(raw.get("blocks", [])):
        if b.get("type", 0) != 0:
            continue
        for li, ln in enumerate(b.get("lines", [])):
            wi, cur = 0, []
            chars = [c for sp in ln.get("spans", []) for c in sp.get("chars", [])]
            for c in chars + [None]:
                if c is None or not c["c"].strip():
                    if cur:
                        words.append((min(x["bbox"][0] for x in cur), min(x["bbox"][1] for x in cur),
                                      max(x["bbox"][2] for x in cur), max(x["bbox"][3] for x in cur),
                                      "".join(x["c"] for x in cur), bi, li, wi))
                        wi += 1
                        cur = []
                    continue
                cur.append(c)
    return words


def _rows_from_words(words, rot):
    if not words:
        return []
    rows = {}
    for w in words:
        r = fitz.Rect(w[:4]) * rot
        rows.setdefault((w[5], w[6]), []).append((r, w[4]))
    out = []
    for ws in rows.values():
        ws.sort(key=lambda t: t[0].x0)
        # tách 2 cột nằm chung 1 dòng (khối cơ quan bên trái / Quốc hiệu bên phải)
        cur = [ws[0]]
        for t in ws[1:]:
            h = max(1.0, cur[-1][0].height)
            if t[0].x0 - cur[-1][0].x1 > h * 2.5:
                out.append(cur); cur = [t]
            else:
                cur.append(t)
        out.append(cur)
    res = []
    for ch in out:
        x0 = min(t[0].x0 for t in ch); y0 = min(t[0].y0 for t in ch)
        x1 = max(t[0].x1 for t in ch); y1 = max(t[0].y1 for t in ch)
        res.append((x0, y0, x1, y1, " ".join(t[1] for t in ch)))
    res.sort(key=lambda r: (round(r[1] / 3), r[0]))
    return res


_VV_RE = re.compile(r"^\s*(v\s*[/.]\s*v|ve\s+viec)\s*[:.]?\s*", re.I)


def _date_of(rows, H):
    """Ngày văn bản: dòng '..., ngày .. tháng .. năm ....' dưới Quốc hiệu -> 'dd.mm.yyyy'."""
    for top_only in (True, False):
        for r in rows:
            if top_only and r[1] > H * 0.4:
                continue
            m = _DATE_RE.search(_plain(r[4]))
            if m:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 1 <= d <= 31 and 1 <= mo <= 12:
                    return "%02d.%02d.%04d" % (d, mo, y)
    for r in rows:
        if r[1] > H * 0.4:
            continue
        m = _DATE2_RE.search(r[4])
        if m and 1 <= int(m.group(1)) <= 31 and 1 <= int(m.group(2)) <= 12:
            return "%02d.%02d.%s" % (int(m.group(1)), int(m.group(2)), m.group(3))
    return None


def _cap(s):
    s = s.strip(" .,;:-–")
    return s[:1].upper() + s[1:] if s else s


def _low1(s):
    """Viết thường chữ đầu ('Công tác số hóa' -> 'công tác số hóa'); giữ nguyên từ viết tắt / IN HOA."""
    s = s.strip(" .,;:-–")
    w = s.split(" ", 1)[0]
    if len(w) > 1 and w.isupper():
        return s
    return s[:1].lower() + s[1:]


def doc_info(page, ocr=True):
    """Đọc trang đầu văn bản -> dict(trich_yeu, tieu_de, ngay):
       trich_yeu: phần sau 'V/v' / 'Về việc' (vd 'Số hóa hồ sơ')
       tieu_de  : tên loại + tên văn bản (vd 'Báo cáo công tác số hóa năm 2026')
       ngay     : ngày ban hành dưới Quốc hiệu (vd '19.10.2026')."""
    W, H = page.rect.width, page.rect.height
    rows = _page_rows(page, ocr)
    info = {"trich_yeu": None, "tieu_de": None, "ngay": None}
    if not rows:
        return info
    info["ngay"] = _date_of(rows, H)

    def follow(i, cond, maxn=3):
        """Các dòng nối tiếp ngay dưới dòng i (cùng cột) thỏa cond."""
        out, prev = [], rows[i]
        for q in rows[i + 1:]:
            lh = max(6.0, prev[3] - prev[1])
            if q[1] - prev[3] > lh * 1.6 or len(out) >= maxn:
                break
            if q[1] < prev[3] - lh * 0.3:      # cùng hàng (cột khác)
                continue
            if not cond(q):
                if q[1] - prev[3] > -1 and abs(((q[1] + q[3]) / 2) - ((prev[1] + prev[3]) / 2)) < lh * 0.5:
                    continue
                break
            out.append(q)
            prev = q
        return out

    # ---- 1) trích yếu "V/v ..." (công văn: cột trái dưới số ký hiệu; hoặc dòng 'Về việc ...' dưới tên loại VB)
    for i, r in enumerate(rows):
        if r[1] > H * 0.6:
            break
        p = _plain(r[4])
        m = _VV_RE.match(p)
        if not m:
            continue
        # cắt đúng số ký tự của phần 'V/v' trên chuỗi gốc (cùng độ dài sau khi bỏ dấu)
        first = r[4].strip()
        first = first[len(first) - len(first.lstrip()):]
        pl = _plain(first)
        mm = _VV_RE.match(pl)
        text = first[mm.end():] if mm else first
        if abs((r[0] + r[2]) / 2 - W / 2) > W * 0.15:
            more = follow(i, lambda q: q[0] < W * 0.5 and q[2] < W * 0.6 and not _STOP_RE.match(_plain(q[4]).strip()))
        else:
            more = follow(i, lambda q: abs((q[0] + q[2]) / 2 - W / 2) < W * 0.06 and (q[2] - q[0]) < W * 0.72
                          and not _STOP_RE.match(_plain(q[4]).strip()))
        text = " ".join([text] + [q[4].strip() for q in more])
        if len([c for c in text if c.isalpha()]) >= 3:
            info["trich_yeu"] = _cap(text)
            break

    # ---- 2) tên loại văn bản (dòng IN HOA ở giữa, dưới Quốc hiệu) + tên văn bản ngay dưới
    hdr_bot = 0.0
    for r in rows:
        if r[1] < H * 0.35 and (_is_qh(r[4]) or re.search(r"ngay\s*\d|so\s*:", _plain(r[4]))):
            hdr_bot = max(hdr_bot, r[3])

    # lề trái của thân văn bản (các dòng dài) -> dòng bắt đầu ở lề đó là nội dung, không phải tên văn bản
    longs = sorted(round(r[0]) for r in rows if (r[2] - r[0]) > W * 0.45)
    body_x = longs[len(longs) // 2] if longs else None

    def is_body(q):
        return body_x is not None and abs(q[0] - body_x) < 6 and (q[2] - q[0]) > W * 0.45

    def cand(i, r, strict):
        if r[1] < hdr_bot - 1 or r[1] > H * 0.6:
            return False
        txt = r[4].strip()
        if _is_qh(txt):
            return False
        letters = [c for c in txt if c.isalpha()]
        if len(letters) < 2:
            return False
        upper = sum(c.isupper() for c in letters) / len(letters)
        cx = (r[0] + r[2]) / 2
        p = re.sub(r"\s+", " ", _plain(txt)).strip(" .:")
        if re.search(r"uy\s*ban|ubnd|nhan\s*dan$|^so\s*:", p):
            return False
        known = any(p == t or p.startswith(t + " ") for t in _DOC_TYPES)
        if strict:      # lượt 1: đúng tên loại văn bản (BÁO CÁO, QUYẾT ĐỊNH, KẾ HOẠCH...)
            return known and (upper >= 0.6 or p in _DOC_TYPES) and abs(cx - W / 2) < W * 0.2
        return upper >= 0.8 and abs(cx - W / 2) < W * 0.15 and len(letters) <= 40

    hit = None
    for strict in (True, False):
        for i, r in enumerate(rows):
            if cand(i, r, strict):
                hit = i
                break
        if hit is not None:
            break
    if hit is not None:
        txt = rows[hit][4].strip()
        sub = follow(hit, lambda q: abs((q[0] + q[2]) / 2 - W / 2) < W * 0.06 and (q[2] - q[0]) < W * 0.72
                     and not _is_qh(q[4]) and not is_body(q)
                     and not _STOP_RE.match(_plain(q[4]).strip()) and not _plain(q[4]).strip().endswith(":")
                     and not set(_plain(q[4]).strip()) <= set("-_. "))
        sub_txt = " ".join(q[4].strip() for q in sub)
        if sub_txt and _VV_RE.match(_plain(sub_txt)) and not info["trich_yeu"]:
            # QUYẾT ĐỊNH / Về việc ... -> đó là trích yếu
            info["trich_yeu"] = _cap(sub_txt[_VV_RE.match(_plain(sub_txt)).end():])
        typ = _cap(txt.lower())
        info["tieu_de"] = typ + (" " + _low1(sub_txt) if sub_txt and not _VV_RE.match(_plain(sub_txt)) else "")
    return info


_QH_KEYS = ("conghoaxahoi", "xahoichunghia", "chunghiavietnam", "doclaptudo", "tudohanhphuc", "hanhphuc")
_QH_TOKS = {"cong", "hoa", "xa", "hoi", "chu", "nghia", "viet", "nam", "doc", "lap", "tu", "do", "hanh", "phuc"}


def _is_qh(txt):
    """Dòng Quốc hiệu / Tiêu ngữ (kể cả khi chữ giãn cách 'C Ộ N G  H Ò A' hoặc nhận dạng sai 1-2 chữ)."""
    p = _plain(txt)
    flat = re.sub(r"[^a-z]", "", p)
    if any(k in flat for k in _QH_KEYS):
        return True
    toks = set(re.findall(r"[a-z]+", p))
    anchor = {"cong", "hoa"} <= toks or {"doc", "lap"} <= toks or {"hanh", "phuc"} <= toks
    return anchor and len(toks & _QH_TOKS) >= 4


def safe_name(s, limit=120):
    s = unicodedata.normalize("NFC", s)
    s = s.replace("/", "-")
    s = re.sub(r'[\\:*?"<>|\r\n\t]+', " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-_")
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0]
    return s


def doc_name(src_doc, pages, default, ocr=True):
    """Tên file (chưa có .pdf) cho 1 văn bản:
       có trích yếu   -> 'So hoa ho so ngay 19.10.2026'
       không trích yếu -> 'Bao cao cong tac so hoa nam 2026 ngay 19.10.2026'   (không dấu)."""
    try:
        info = doc_info(src_doc[pages[0]], ocr)
    except Exception:
        info = {"trich_yeu": None, "tieu_de": None, "ngay": None}
    name = safe_name(no_accent(info["trich_yeu"] or info["tieu_de"] or "")) or default
    if info["ngay"]:
        name += " ngay " + info["ngay"]
    return name


def save_docs(src_doc, docs, out_dir, base, progress=None, smart_names=True):
    """Lưu từng văn bản thành 1 file PDF riêng. Không ghi đè file có sẵn.
    smart_names: đặt tên theo tiêu đề / trích yếu văn bản + ngày (không dấu)."""
    os.makedirs(out_dir, exist_ok=True)
    files = []
    width = max(2, len(str(len(docs))))
    used = set()
    for k, pages in enumerate(docs):
        nd = fitz.open()
        for p in pages:
            nd.insert_pdf(src_doc, from_page=p, to_page=p)
        default = "%s_VB%0*d" % (base, width, k + 1)
        stem = doc_name(src_doc, pages, default) if smart_names else default
        path = os.path.join(out_dir, stem + ".pdf")
        i = 1
        while os.path.exists(path) or path.lower() in used:
            path = os.path.join(out_dir, "%s (%d).pdf" % (stem, i))
            i += 1
        used.add(path.lower())
        nd.save(path, garbage=3, deflate=True)
        nd.close()
        files.append((path, pages))
        if progress:
            progress(k + 1, len(docs))
    return files
