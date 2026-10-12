# -*- coding: utf-8 -*-
"""
DỰNG "DÒNG CHỮ NHÌN THẤY" CHO PDF -> WORD (văn bản có công thức toán / hoá).

Trong PDF, 1 dòng chữ có công thức bị tách thành nhiều mảnh: chỉ số trên/dưới, mũi tên vectơ,
dấu ngoặc phóng to, tử số / mẫu số phân số... Nếu coi mỗi mảnh là 1 dòng -> chữ chạy lung tung.
Ở đây:
  * Gộp mọi mảnh thuộc cùng 1 dòng nhìn thấy (chồng nhau theo chiều dọc, sát nhau theo chiều ngang).
  * Chỉ số trên/dưới đơn giản (Pb²⁺, 10⁻³¹, CH₃) -> chỉ số trên/dưới THẬT của Word (sửa được).
  * Phần công thức XẾP TẦNG (phân số, vectơ có mũi tên, căn, ký hiệu đặc biệt) -> ảnh nhỏ nét cao
    nằm TRONG dòng chữ, đúng vị trí; phần chữ còn lại vẫn gõ sửa bình thường.
"""
from core import fitz
import core

MATH_DPI = 300


class VLn:
    """Dòng chữ nhìn thấy – cùng thuộc tính với wordnative.Ln + danh sách mục (chữ / ảnh công thức)."""
    __slots__ = ("x0", "x1", "top", "bot", "base", "size", "desc", "spans", "text",
                 "items", "asc_ext", "desc_ext", "has_math")

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def c(self):
        return (self.x0 + self.x1) / 2


def _is_pua(t):
    return any(0xF000 <= ord(ch) <= 0xF8FF for ch in t)


def _is_math_font(name):
    n = (name or "").lower()
    return any(k in n for k in ("math", "symbol", "extra", "euclid", "mt extra", "mtextra"))


def _span_base(s):
    return s["origin"][1]


def _union_find(n):
    p = list(range(n))

    def f(a):
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    def u(a, b):
        ra, rb = f(a), f(b)
        if ra != rb:
            p[ra] = rb
    return f, u


def _render_clip(page, rect):
    pm = page.get_pixmap(dpi=MATH_DPI, clip=rect, alpha=False, annots=False)
    return pm.tobytes("png")


def build(page, raw_lines, rot, cells=None):
    """raw_lines: kết quả convert._page_lines(page); cells: các ô bảng (toạ độ hiển thị) –
    chữ của 2 ô khác nhau không bao giờ bị gộp chung 1 dòng.
    Trả về (list VLn, list vùng công thức)."""
    cells = [fitz.Rect(c) for c in (cells or [])]

    def cell_of(r):
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        best, area = -1, None
        for i, c in enumerate(cells):
            if c.x0 - 0.5 <= cx <= c.x1 + 0.5 and c.y0 - 0.5 <= cy <= c.y1 + 0.5:
                if area is None or c.get_area() < area:
                    best, area = i, c.get_area()
        return best

    # ---- tách dòng PyMuPDF theo ô bảng (1 dòng PDF có thể chạy qua nhiều ô)
    split_lines = []
    for rl in raw_lines:
        if not cells:
            split_lines.append(rl)
            continue
        byc = {}
        for s in rl["raw"]["spans"]:
            ci = cell_of(fitz.Rect(s["bbox"]) * rot)
            byc.setdefault(ci, []).append(s)
        if len(byc) <= 1:
            split_lines.append(rl)
        else:
            for ci, sp in byc.items():
                split_lines.append({"raw": {"spans": sp}})
    raw_lines = split_lines
    # ---- gom mọi mảnh chữ (kể cả dấu cách) theo toạ độ hiển thị
    pieces = []   # (rect, raw_line_index)
    spans_by_line = []
    for li, rl in enumerate(raw_lines):
        sp = []
        for s in rl["raw"]["spans"]:
            if s.get("alpha", 255) == 0:
                continue
            t = core.norm_text(s.get("text", ""))
            if t == "":
                continue
            s = dict(s)
            s["text"] = t
            s["bbox"] = tuple(fitz.Rect(s["bbox"]) * rot)
            s["origin"] = tuple(fitz.Point(s["origin"]) * rot)
            sp.append(s)
        if not any(x["text"].strip() for x in sp):
            sp = []
        spans_by_line.append(sp)
        if sp:
            r = fitz.Rect(sp[0]["bbox"])
            for x in sp[1:]:
                r = r.include_rect(fitz.Rect(x["bbox"]))
            pieces.append((r, li))
    if not pieces:
        return [], []
    # ---- gộp các dòng PyMuPDF thuộc cùng 1 dòng nhìn thấy
    n = len(pieces)
    find, union = _union_find(n)
    order = sorted(range(n), key=lambda i: pieces[i][0].y0)
    for a_i, a in enumerate(order):
        ra = pieces[a][0]
        for b in order[a_i + 1:]:
            rb = pieces[b][0]
            if rb.y0 > ra.y1:
                break
            ov = min(ra.y1, rb.y1) - max(ra.y0, rb.y0)
            hmin = max(1.0, min(ra.height, rb.height))
            sz = max(4.0, min(ra.height, rb.height))
            gap = max(ra.x0, rb.x0) - min(ra.x1, rb.x1)
            lim = (2.0 if ov > 0.45 * hmin else 1.2) * sz
            if ov > 0.2 * hmin and gap < lim and (not cells or cell_of(ra) == cell_of(rb)):
                union(a, b)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    # nối các đoạn kẻ thẳng hàng (đường kẻ bảng hay bị vẽ thành nhiều đoạn ngắn liền nhau)
    raw_r = sorted((fitz.Rect(d["rect"]) * rot for d in drawings), key=lambda r: (round(r.y0, 0), r.x0))
    joined = []
    for r in raw_r:
        if joined:
            q = joined[-1]
            if r.height < 2 and q.height < 2 and abs(r.y0 - q.y0) < 0.8 and r.x0 <= q.x1 + 1.5:
                joined[-1] = fitz.Rect(q).include_rect(r)
                continue
        joined.append(fitz.Rect(r))
    dr_rects = [r for r in joined if r.width < page.rect.width * 0.30]

    out, math_rects = [], []
    for g in groups.values():
        spans = [s for i in g for s in spans_by_line[pieces[i][1]]]
        if not spans:
            continue
        # đường chân chữ chính: mảnh có nhiều chữ nhất (ưu tiên cỡ lớn)
        textual = [s for s in spans if not _is_math_font(s.get("font", "")) and s["text"].strip()]
        mainspan = max(textual or spans, key=lambda s: len(s["text"].strip()) * s["size"])
        base, msize = _span_base(mainspan), mainspan["size"]
        kinds = []
        for s in spans:
            dy = _span_base(s) - base
            if _is_pua(s["text"]):
                k = "math"
            elif abs(dy) <= 0.22 * msize:
                k = "main"
            elif s["size"] <= 0.85 * msize and dy < 0:
                k = "sup"
            elif s["size"] <= 0.85 * msize and dy > 0:
                k = "sub"
            elif s.get("flags", 0) & 1:
                k = "sup"
            else:
                k = "math"
            kinds.append(k)
        # các mảnh lệch dòng chồng lên nhau theo chiều ngang (tử / mẫu số, giới hạn) -> công thức
        for i, si in enumerate(spans):
            if kinds[i] not in ("sup", "sub", "math"):
                continue
            ri = fitz.Rect(si["bbox"])
            for j, sj in enumerate(spans):
                if j == i or kinds[j] == "main":
                    continue
                rj = fitz.Rect(sj["bbox"])
                ovx = min(ri.x1, rj.x1) - max(ri.x0, rj.x0)
                if ovx > 0.4 * max(0.5, min(ri.width, rj.width)) and \
                        abs(_span_base(si) - _span_base(sj)) > 0.3 * msize:
                    kinds[i] = kinds[j] = "math"
        band = fitz.Rect(min(s["bbox"][0] for s in spans), base - 1.4 * msize,
                         max(s["bbox"][2] for s in spans), base + 0.7 * msize)
        clusters = []
        # gạch phân số / dấu căn / mũi tên vẽ bằng nét: có chữ cả trên và dưới, hoặc nằm trên chữ
        for r in dr_rects:
            if not (r.y0 >= band.y0 - 1 and r.y1 <= band.y1 + 1 and r.x0 >= band.x0 - 2 and r.x1 <= band.x1 + 2):
                continue
            if r.height > 1.6 * msize:
                continue
            # tử số / mẫu số phải nằm GỌN trong bề rộng gạch và sát gạch
            def _inside_x(sp):
                rr = fitz.Rect(sp["bbox"])
                cx = (rr.x0 + rr.x1) / 2
                return r.x0 - 2 <= cx <= r.x1 + 2 and rr.width <= r.width + 4 and sp["text"].strip()
            xs = [sp for sp in spans if _inside_x(sp)]
            above = any(fitz.Rect(sp["bbox"]).y1 <= r.y0 + 1.0 and fitz.Rect(sp["bbox"]).y1 >= r.y0 - 1.2 * msize
                        for sp in xs)
            below = any(fitz.Rect(sp["bbox"]).y0 >= r.y1 - 1.0 and fitz.Rect(sp["bbox"]).y0 <= r.y1 + 1.2 * msize
                        for sp in xs)
            mid_y = (r.y0 + r.y1) / 2
            # gạch phân số nằm khoảng giữa chiều cao chữ (không phải cạnh khung trên đỉnh / dưới chân chữ)
            frac = above and below and (base - 0.7 * msize <= mid_y <= base - 0.02 * msize)
            # mũi tên vectơ / gạch trên đầu chữ: ngắn (vài chữ), không phải cạnh khung dài cả dòng
            over = below and not above and mid_y < base - 0.55 * msize and r.width <= 5 * msize
            if frac or over:
                clusters.append(fitz.Rect(r))
        for s, k in zip(spans, kinds):
            if k == "math":
                clusters.append(fitz.Rect(s["bbox"]))
        # gộp vùng công thức + mảnh chữ chính nằm dưới / trong vùng (vd chữ 'u' dưới mũi tên)
        clusters.sort(key=lambda r: r.x0)
        merged = []
        for r in clusters:
            if merged and r.x0 <= merged[-1].x1 + 0.15 * msize:
                merged[-1] = fitz.Rect(merged[-1]).include_rect(r)
            else:
                merged.append(fitz.Rect(r))
        changed = True
        while changed:
            changed = False
            for mi in range(len(merged)):
                m = merged[mi]
                for s, k in zip(spans, kinds):
                    rs = fitz.Rect(s["bbox"])
                    ovx = min(rs.x1, m.x1) - max(rs.x0, m.x0)
                    if ovx > 0.5 * max(0.5, rs.width) or (k in ("sup", "sub") and ovx > 0):
                        if not m.contains(rs):
                            m = fitz.Rect(m).include_rect(rs)
                            changed = True
                merged[mi] = m
            # gộp lại nếu chạm nhau
            merged.sort(key=lambda r: r.x0)
            mm = []
            for r in merged:
                if mm and r.x0 <= mm[-1].x1 + 0.15 * msize:
                    mm[-1] = fitz.Rect(mm[-1]).include_rect(r)
                    changed = True
                else:
                    mm.append(r)
            merged = mm
        # dấu ngoặc lớn ( ) [ ] { } | bao công thức xếp tầng -> gom trọn từ ngoặc mở tới ngoặc đóng
        if merged:
            # ngoặc lớn ghép từ mảnh ký hiệu font Symbol: U+F0E6..F0EE (mở), U+F0F6..F0FE (đóng)
            def _br(sp):
                t = sp["text"].strip()
                if len(t) == 1 and 0xF0E6 <= ord(t) <= 0xF0EE:
                    return "open"
                if len(t) == 1 and 0xF0F6 <= ord(t) <= 0xF0FE:
                    return "close"
                if t in ("(", "[", "{", "|", ")", "]", "}") and \
                        (fitz.Rect(sp["bbox"]).height > 1.35 * msize or sp["size"] > 1.12 * msize):
                    return "open" if t in "([{" else ("close" if t in ")]}" else "bar")
                return None
            opens = sorted((sp for sp in spans if _br(sp) in ("open", "bar")), key=lambda sp: sp["bbox"][0])
            closes = sorted((sp for sp in spans if _br(sp) in ("close", "bar")), key=lambda sp: sp["bbox"][0])
            for o in opens:
                ro = fitz.Rect(o["bbox"])
                c = next((c for c in closes if c["bbox"][0] > ro.x1 and c is not o), None)
                if c is None:
                    continue
                rc = fitz.Rect(c["bbox"])
                pair = fitz.Rect(ro).include_rect(rc)
                if any(min(m.x1, pair.x1) - max(m.x0, pair.x0) > 0 for m in merged):
                    merged.append(pair)
        # công thức viết bằng font toán (Cambria Math, Symbol, MT Extra): gom các mảnh liền kề vào cùng ảnh
        if merged:
            grew = True
            while grew:
                grew = False
                for mi in range(len(merged)):
                    m = merged[mi]
                    for sp in spans:
                        if not _is_math_font(sp.get("font", "")) or not sp["text"].strip():
                            continue
                        rs = fitz.Rect(sp["bbox"])
                        if m.contains(rs):
                            continue
                        gap = max(rs.x0 - m.x1, m.x0 - rs.x1)
                        if gap < 0.5 * msize and rs.y1 > m.y0 - msize and rs.y0 < m.y1 + msize:
                            m = fitz.Rect(m).include_rect(rs)
                            grew = True
                    merged[mi] = m
                merged.sort(key=lambda r: r.x0)
                mm = []
                for r in merged:
                    if mm and r.x0 <= mm[-1].x1 + 0.15 * msize:
                        mm[-1] = fitz.Rect(mm[-1]).include_rect(r)
                    else:
                        mm.append(r)
                merged = mm
        merged.sort(key=lambda r: r.x0)
        mm = []
        for r in merged:
            if mm and r.x0 <= mm[-1].x1 + 0.15 * msize:
                mm[-1] = fitz.Rect(mm[-1]).include_rect(r)
            else:
                mm.append(fitz.Rect(r))
        merged = []
        for m in mm:
            for sp in spans:
                rs = fitz.Rect(sp["bbox"])
                ovx = min(rs.x1, m.x1) - max(rs.x0, m.x0)
                if ovx > 0.5 * max(0.5, rs.width):
                    m = fitz.Rect(m).include_rect(rs)
            merged.append(m)
        # ---- dựng các mục theo thứ tự trái -> phải
        items = []
        math_items = []
        for m in merged:
            rect = fitz.Rect(m.x0 - 0.6, m.y0 - 0.6, m.x1 + 0.6, m.y1 + 0.6)
            try:
                png = _render_clip(page, rect * page.derotation_matrix if rot != fitz.Identity else rect)
            except Exception:
                continue
            it = {"math": True, "rect": rect, "png": png, "x0": rect.x0, "base": base, "size": msize}
            items.append(it)
            math_items.append(it)
            math_rects.append(rect)
        for s, k in zip(spans, kinds):
            rs = fitz.Rect(s["bbox"])
            if any(min(rs.x1, m.x1) - max(rs.x0, m.x0) > 0.5 * max(0.5, rs.width) for m in merged):
                continue
            s2 = dict(s)
            s2["va"] = "superscript" if k == "sup" else ("subscript" if k == "sub" else None)
            if k in ("sup", "sub"):
                s2["size"] = max(s["size"] / 0.65, msize * 0.9)
            if k == "main" and s["size"] > 1.12 * msize and len(s["text"].strip()) <= 2:
                s2["size"] = msize     # ngoặc phóng to -> cỡ chữ thường
            s2["x0"] = rs.x0
            items.append(s2)
        items.sort(key=lambda it: it["x0"])
        # chèn dấu cách khi 2 mục cách nhau mà không có dấu cách
        fixed = []
        prev_x1, prev_txt = None, ""
        for it in items:
            x0 = it["rect"].x0 if it.get("math") else it["bbox"][0]
            x1 = it["rect"].x1 if it.get("math") else it["bbox"][2]
            txt = "" if it.get("math") else it["text"]
            if prev_x1 is not None and x0 - prev_x1 > 0.28 * msize and \
                    not prev_txt.endswith(" ") and not txt.startswith(" "):
                if it.get("math"):
                    sp = dict(mainspan)
                    sp.update(text=" ", va=None, x0=x0)
                    fixed.append(sp)
                else:
                    it = dict(it)
                    it["text"] = " " + it["text"]
            fixed.append(it)
            prev_x1, prev_txt = x1, (txt or "x")
        items = fixed
        texts = [it for it in items if not it.get("math")]
        if not texts and not math_items:
            continue
        v = VLn()
        allr = [fitz.Rect(it["rect"]) if it.get("math") else fitz.Rect(it["bbox"]) for it in items]
        v.x0 = min(r.x0 for r in allr)
        v.x1 = max(r.x1 for r in allr)
        main_r = [fitz.Rect(s["bbox"]) for s, k in zip(spans, kinds) if k == "main"] or allr
        v.top = min(r.y0 for r in main_r)
        v.bot = max(r.y1 for r in main_r)
        v.base = base
        v.size = msize
        v.desc = abs(mainspan.get("descender", -0.216) or -0.216)
        v.spans = texts or [dict(mainspan, text="", va=None)]
        v.items = items
        v.text = core.norm_text("".join(("■" if it.get("math") else it["text"]) for it in items)).strip()
        v.has_math = bool(math_items)
        v.asc_ext = max([base - r.y0 for r in allr] + [msize * 0.9])
        v.desc_ext = max([r.y1 - base for r in allr] + [v.desc * msize])
        out.append(v)
    return out, math_rects
