# -*- coding: utf-8 -*-
"""
PDF -> WORD "như Word gõ tay" mà vẫn giữ nguyên bố cục:
  * Chữ là ĐOẠN VĂN thường (không frame, không text box) – gõ thêm chữ tự xuống dòng như Word.
  * Bảng trong PDF -> BẢNG WORD thật: đúng độ rộng cột, chiều cao hàng, gộp ô, viền, màu nền.
  * Phần chữ nằm song song (Quốc hiệu | Tên cơ quan, Nơi nhận | Chữ ký...) -> bảng ẨN VIỀN,
    đúng cách soạn công văn trong Word.
  * Chữ ký, con dấu, logo -> ảnh nền trong suốt đặt nổi đúng toạ độ cũ.
  * Mỗi trang PDF = 1 trang Word (lề, khổ giấy, khoảng cách dòng tính từ toạ độ gốc).
"""
import io

import core
from core import fitz

TW = 20  # 1 pt = 20 twips


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _clean(s):
    return "".join(ch for ch in s if ch in "\t" or ord(ch) >= 32)


def tw(v):
    return int(round(v * TW))


# =============================================================================
#  DÒNG CHỮ
# =============================================================================
class Ln:
    __slots__ = ("x0", "x1", "top", "bot", "base", "size", "desc", "spans", "text")

    def __init__(self, d, rot):
        spans = d["spans"]
        b = d["bbox"]
        self.x0, self.x1, self.top, self.bot = b.x0, b.x1, b.y0, b.y1
        first = spans[0]
        self.base = (fitz.Point(first["origin"]) * rot).y
        big = max(spans, key=lambda s: s["size"])
        self.size = big["size"]
        self.desc = abs(big.get("descender", -0.216) or -0.216)
        self.spans = spans
        self.text = core.norm_text("".join(s["text"] for s in spans)).strip()

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def c(self):
        return (self.x0 + self.x1) / 2


_CTX = {}   # trong lúc dựng tài liệu: 'img' = hàm thêm ảnh -> rId, 'pid' = bộ đếm


def _inline_img(it):
    """Ảnh công thức nằm TRONG dòng chữ, hạ xuống đúng chân chữ."""
    E = 12700
    r = it["rect"]
    rid = _CTX["img"](it["png"])
    pid = _CTX["pid"][0]
    _CTX["pid"][0] += 1
    cx, cy = int(r.width * E), int(r.height * E)
    lower = max(0.0, r.y1 - it["base"])          # phần nằm dưới chân chữ
    if _CTX.get("in_table"):
        lower = 0.0          # trong ô bảng: ảnh đứng trên chân chữ, dòng tự cao vừa ảnh (không bị cắt)
    return ('<w:r><w:rPr><w:position w:val="%d"/></w:rPr><w:drawing>'
            '<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="%d" cy="%d"/>'
            '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="%d" name="Cong thuc %d"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:nvPicPr><pic:cNvPr id="%d" name="CongThuc%d.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            '</wp:inline></w:drawing></w:r>') % (-int(round(lower * 2)), cx, cy, pid, pid, pid, pid, rid, cx, cy)


_BLANK_PNG = None


def _blank_png():
    global _BLANK_PNG
    if _BLANK_PNG is None:
        from PIL import Image
        bio = io.BytesIO()
        Image.new("RGBA", (4, 1), (255, 255, 255, 0)).save(bio, "PNG")
        _BLANK_PNG = bio.getvalue()
    return _BLANK_PNG


def _math_runs(it):
    """Công thức: 1 khoảng trống trong dòng (đúng bề rộng, giữ chỗ cho chữ chảy đúng)
    + ảnh công thức NỔI đặt đúng toạ độ gốc -> không làm dòng cao lên, không đẩy chữ."""
    E = 12700
    r = it["rect"]
    rid_b = _CTX["img"](_blank_png())
    pid = _CTX["pid"][0]
    _CTX["pid"][0] += 2
    cx = int(r.width * E)
    spacer = ('<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="%d" cy="%d"/>'
              '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="%d" name="Cho cong thuc %d"/>'
              '<wp:cNvGraphicFramePr/>'
              '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
              '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
              '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
              '<pic:nvPicPr><pic:cNvPr id="%d" name="trong.png"/><pic:cNvPicPr/></pic:nvPicPr>'
              '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
              '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
              '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
              '</wp:inline></w:drawing></w:r>') % (cx, E // 2, pid, pid, pid, rid_b, cx, E // 2)
    rid = _CTX["img"](it["png"])
    return spacer + anchor_xml(rid, r, pid + 1, behind=False)


def _runs(lines):
    """Các dòng của 1 đoạn -> XML các run (giữ font, cỡ, đậm, nghiêng, màu).
    Giữa các dòng của đoạn: NGẮT DÒNG MỀM (như Shift+Enter) đúng chỗ xuống dòng của bản gốc
    -> Word không tự ngắt dòng khác đi, chữ không bị chạy / tràn trang."""
    out = []
    for li, ln in enumerate(lines):
        if li > 0:
            out.append("<w:r><w:br/></w:r>")
        if getattr(ln, "items", None) is not None:
            for k, it in enumerate(ln.items):
                if it.get("math"):
                    if "img" in _CTX:
                        out.append(_inline_img(it) if _CTX.get("in_table") else _math_runs(it))
                    continue
                t = it["text"]
                if k == 0:
                    t = t.lstrip()
                if k == len(ln.items) - 1:
                    t = t.rstrip()
                if not t:
                    continue
                out.append(_run(t, it, it.get("va")))
            continue
        spans = [s for s in ln.spans if s["text"] != ""]
        for k, s in enumerate(spans):
            t = core.norm_text(s["text"])
            if k == 0:
                t = t.lstrip()
            if k == len(spans) - 1:
                t = t.rstrip()
            if not t:
                continue
            out.append(_run(t, s))
    return "".join(out)


def _rpr(s):
    fname = s.get("font", "")
    fam = _esc(core.clean_font_name(fname))
    fl = s.get("flags", 0)
    sz = int(round(s["size"] * 2))
    x = '<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s" w:eastAsia="%s"/>' % (fam, fam, fam, fam)
    if fl & 16 or "bold" in fname.lower():
        x += "<w:b/><w:bCs/>"
    if fl & 2 or "italic" in fname.lower():
        x += "<w:i/><w:iCs/>"
    c = s.get("color", 0) & 0xFFFFFF
    if c:
        x += '<w:color w:val="%06X"/>' % c
    x += '<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (sz, sz)
    return x


def _run(text, s, va=None):
    rp = _rpr(s)
    if va:
        rp += '<w:vertAlign w:val="%s"/>' % va
    return '<w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t></w:r>' % (rp, _esc(_clean(text)))


# =============================================================================
#  GHÉP DÒNG -> ĐOẠN VĂN
# =============================================================================
class Para:
    def __init__(self, lines):
        self.lines = lines

    @property
    def first(self):
        return self.lines[0]

    @property
    def last(self):
        return self.lines[-1]

    @property
    def has_math(self):
        return any(getattr(l, "has_math", False) for l in self.lines)

    def pitch(self):
        if len(self.lines) > 1:
            p = (self.last.base - self.first.base) / (len(self.lines) - 1)
        else:
            p = round(self.first.size * 1.17, 2)
        if self._cell_math():
            # công thức trong ô bảng: ảnh đứng trên chân chữ -> dòng cao = ảnh + phần chân chữ
            l = self.first
            hs = [it["rect"].height for it in l.items if it.get("math")]
            p = max([p] + [h + l.desc * l.size for h in hs])
        return p

    def _cell_math(self):
        return bool(_CTX.get("in_table") and self.has_math and len(self.lines) == 1)

    def _base0(self):
        l = self.first
        if self._cell_math():
            return max([l.base] + [it["rect"].y1 for it in l.items if it.get("math")])
        return l.base

    def box_top(self):
        L = self.pitch()
        return self._base0() - L + self.first.desc * self.first.size

    def box_bot(self):
        if self._cell_math():
            return self._base0() + self.last.desc * self.last.size
        return self.last.base + self.last.desc * self.last.size


def group_paras(lines, regL, regR):
    lines = sorted(lines, key=lambda l: (round(l.base, 1), l.x0))
    paras = []
    full = regR - max(6.0, 0.035 * (regR - regL))
    for ln in lines:
        if paras:
            p = paras[-1]
            last = p.last
            gap = ln.base - last.base
            ok = (abs(ln.size - last.size) < 0.6 and 0.95 * last.size <= gap <= 1.75 * last.size
                  and last.x1 >= full)
            if ok and len(p.lines) >= 2:
                ok = abs(gap - p.pitch()) < 1.2 and abs(ln.x0 - p.lines[1].x0) < 1.5
            elif ok:
                ok = ln.x0 <= p.first.x0 + 1.0 and ln.x0 >= regL - 1.0
            if ok:
                p.lines.append(ln)
                continue
        paras.append(Para([ln]))
    return paras


def para_xml(p, regL, regR, space_before, anchors="", keep_with_next=False, col=None):
    """regL/regR: mép trái/phải vùng chứa chữ (lề trang hoặc ô bảng).
    col: (trái, phải, cho_phep_can_giua) – vùng dùng để nhận biết chữ căn giữa."""
    ls = p.lines
    n = len(ls)
    left = ls[1].x0 if n > 1 else ls[0].x0
    first = ls[0].x0 - left
    maxx1 = max(l.x1 for l in ls)
    regC = (regL + regR) / 2
    cenC = (col[0] + col[1]) / 2 if col else regC
    can_center = col[2] if col else True
    jc = "left"
    ind_l, ind_r = left - regL, 0.0
    if n > 1:
        if all(abs(l.x1 - maxx1) < 2.0 for l in ls[:-1]) and maxx1 >= regR - 8:
            jc = "both"
            ind_r = max(0.0, regR - maxx1 - 1.0)
        elif can_center and all(abs(l.c - ls[0].c) < 2.0 for l in ls) and abs(ls[0].c - cenC) < 3.0:
            jc = "center"
            off = ls[0].c - regC
            ind_l, ind_r = max(0.0, 2 * off), max(0.0, -2 * off)
            first = 0.0
        else:
            ind_r = 0.0          # căn trái nhiều dòng: đã ngắt dòng mềm, để rộng tránh tự xuống dòng
    else:
        l0 = ls[0]
        if can_center and abs(l0.c - cenC) < 3.0 and (col is not None or l0.x0 - regL > 4):
            jc = "center"
            off = l0.c - regC
            ind_l, ind_r = max(0.0, 2 * off), max(0.0, -2 * off)
        elif abs(l0.x1 - (col[1] if col else regR)) < 2.0 and l0.x0 - regL > 25:
            jc = "right"
            ind_l, ind_r = 0.0, max(0.0, regR - l0.x1)
        first = 0.0
    # tránh vùng chữ hẹp hơn chữ (sẽ bị xuống dòng sai)
    avail = (regR - regL) - ind_l - ind_r - max(first, 0)
    need = maxx1 - min(l.x0 for l in ls) + 3
    if jc != "both" and avail < need:
        cut = need - avail
        if jc == "center":
            k = min(cut, ind_l + ind_r)
            tot = ind_l + ind_r
            if tot > 0:
                ind_l -= k * ind_l / tot
                ind_r -= k * ind_r / tot
        else:
            ind_r = max(0.0, ind_r - cut)
    L = p.pitch()
    rule = "atLeast" if p._cell_math() else "exact"
    ppr = '<w:pPr>%s<w:spacing w:before="%d" w:after="0" w:line="%d" w:lineRule="%s"/>' \
          '<w:ind w:left="%d" w:right="%d" %s/><w:jc w:val="%s"/><w:rPr>%s</w:rPr></w:pPr>' % (
              "<w:keepNext/>" if keep_with_next else "",
              max(0, tw(space_before)), tw(L), rule, tw(ind_l), tw(ind_r),
              ('w:firstLine="%d"' % tw(first)) if first >= 0 else ('w:hanging="%d"' % tw(-first)),
              jc, _rpr(ls[0].spans[0]))
    return "<w:p>%s%s%s</w:p>" % (ppr, anchors, _runs(ls))


def tabpara_xml(lines, pp, regL, space_before, anchors=""):
    """1 hàng các cột (đáp án A/B/C/D) -> 1 đoạn: thụt lề tới cột đầu, TAB tới các cột sau."""
    tabs = "".join('<w:tab w:val="left" w:pos="%d"/>' % tw(l.x0 - regL) for l in lines[1:])
    L = pp.pitch()
    ppr = ('<w:pPr><w:tabs>%s</w:tabs><w:spacing w:before="%d" w:after="0" w:line="%d" w:lineRule="exact"/>'
           '<w:ind w:left="%d" w:right="0" w:firstLine="0"/><w:jc w:val="left"/><w:rPr>%s</w:rPr></w:pPr>') % (
        tabs, max(0, tw(space_before)), tw(L), tw(lines[0].x0 - regL), _rpr(lines[0].spans[0]))
    runs = '<w:r><w:tab/></w:r>'.join(_runs([l]) for l in lines)
    return "<w:p>%s%s%s</w:p>" % (ppr, anchors, runs)


def spacer_xml(h, anchors=""):
    h = max(1.0, h)
    return ('<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="%d" w:lineRule="exact"/>'
            '<w:rPr><w:sz w:val="2"/><w:szCs w:val="2"/></w:rPr></w:pPr>%s</w:p>' % (tw(h), anchors))


def stack_xml(lines, regL, regR, top, col=None):
    """Xếp các đoạn trong 1 vùng (ô bảng) từ toạ độ 'top'. Trả về XML (luôn có >= 1 đoạn)."""
    if not lines:
        return spacer_xml(1)
    xml = []
    cur = top
    for p in group_paras(lines, regL, regR):
        xml.append(para_xml(p, regL, regR, p.box_top() - cur, col=col))
        cur = max(cur, p.box_bot())
    return "".join(xml)


# =============================================================================
#  BẢNG
# =============================================================================
def _snap(vals, tol=1.2):
    out = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _idx(arr, v):
    return min(range(len(arr)), key=lambda i: abs(arr[i] - v))


def _segments(page, rot):
    """Các đoạn kẻ (ngang/dọc) trên trang – để biết cạnh ô nào có viền."""
    hs, vs = [], []
    try:
        drs = page.get_drawings()
    except Exception:
        return hs, vs
    for d in drs:
        wdt = d.get("width") or 0.5
        for it in d["items"]:
            if it[0] == "l":
                p1, p2 = it[1] * rot, it[2] * rot
                if abs(p1.y - p2.y) < 1.0:
                    hs.append((min(p1.x, p2.x), max(p1.x, p2.x), (p1.y + p2.y) / 2, wdt))
                elif abs(p1.x - p2.x) < 1.0:
                    vs.append((min(p1.y, p2.y), max(p1.y, p2.y), (p1.x + p2.x) / 2, wdt))
            elif it[0] == "re":
                r = fitz.Rect(it[1]) * rot
                if r.height < 2.5 and r.width > 2:
                    hs.append((r.x0, r.x1, (r.y0 + r.y1) / 2, max(r.height, 0.5)))
                elif r.width < 2.5 and r.height > 2:
                    vs.append((r.y0, r.y1, (r.x0 + r.x1) / 2, max(r.width, 0.5)))
                elif d.get("color") is not None and d.get("type") in ("s", "fs"):
                    hs += [(r.x0, r.x1, r.y0, wdt), (r.x0, r.x1, r.y1, wdt)]
                    vs += [(r.y0, r.y1, r.x0, wdt), (r.y0, r.y1, r.x1, wdt)]
            elif it[0] == "qu":
                r = it[1].rect * rot
                hs += [(r.x0, r.x1, r.y0, wdt), (r.x0, r.x1, r.y1, wdt)]
                vs += [(r.y0, r.y1, r.x0, wdt), (r.y0, r.y1, r.x1, wdt)]
    return hs, vs


def _edge(segs, a0, a1, pos, tol=1.8):
    """Cạnh [a0,a1] tại toạ độ pos có được kẻ >= 60% không -> trả về độ dày (pt) hoặc 0."""
    L = a1 - a0
    if L <= 0:
        return 0
    cov, wmax = [], 0
    for s0, s1, p, w in segs:
        if abs(p - pos) <= tol and s1 > a0 and s0 < a1:
            cov.append((max(s0, a0), min(s1, a1)))
            wmax = max(wmax, w)
    if not cov:
        return 0
    cov.sort()
    tot, cs, ce = 0, cov[0][0], cov[0][1]
    for s, e in cov[1:]:
        if s > ce:
            tot += ce - cs
            cs, ce = s, e
        else:
            ce = max(ce, e)
    tot += ce - cs
    return wmax if tot >= 0.6 * L else 0


def _border(tag, w):
    if not w:
        return '<w:%s w:val="nil"/>' % tag
    sz = max(2, min(96, int(round(w * 8))))
    return '<w:%s w:val="single" w:sz="%d" w:space="0" w:color="000000"/>' % (tag, sz)


def table_xml(cells, area_left, segs=None, fills=None, borderless=False):
    """cells: list of (rect, lines[, col_hint]). Trả về XML bảng Word."""
    cols_hint = [c[2] if len(c) > 2 else None for c in cells]
    cells = [(c[0], c[1]) for c in cells]
    xs = _snap([v for r, _ in cells for v in (r.x0, r.x1)])
    ys = _snap([v for r, _ in cells for v in (r.y0, r.y1)])
    nC, nR = len(xs) - 1, len(ys) - 1
    grid = {}  # (row, col) -> (cell index, r0, r1, c0, c1)
    info = []
    for i, (r, lines) in enumerate(cells):
        r0, r1 = _idx(ys, r.y0), _idx(ys, r.y1)
        c0, c1 = _idx(xs, r.x0), _idx(xs, r.x1)
        r1, c1 = max(r1, r0 + 1), max(c1, c0 + 1)
        info.append((r0, r1, c0, c1))
        for rr in range(r0, r1):
            for cc in range(c0, c1):
                grid.setdefault((rr, cc), i)
    hs, vs = segs or ([], [])
    tblw = xs[-1] - xs[0]
    borders = "".join('<w:%s w:val="nil"/>' % t for t in ("top", "left", "bottom", "right", "insideH", "insideV"))
    out = ['<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblInd w:w="%d" w:type="dxa"/>'
           '<w:tblBorders>%s</w:tblBorders><w:tblLayout w:type="fixed"/>'
           '<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
           '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar>'
           '<w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" '
           'w:noHBand="1" w:noVBand="1"/></w:tblPr><w:tblGrid>' % (tw(tblw), tw(xs[0] - area_left), borders)]
    out += ['<w:gridCol w:w="%d"/>' % tw(xs[c + 1] - xs[c]) for c in range(nC)]
    out.append("</w:tblGrid>")
    for rr in range(nR):
        out.append('<w:tr><w:trPr><w:trHeight w:val="%d" w:hRule="atLeast"/></w:trPr>' % tw(ys[rr + 1] - ys[rr]))
        cc = 0
        while cc < nC:
            i = grid.get((rr, cc))
            if i is None:  # lỗ trống trong lưới
                out.append('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/></w:tcPr>%s</w:tc>'
                           % (tw(xs[cc + 1] - xs[cc]), spacer_xml(1)))
                cc += 1
                continue
            r0, r1, c0, c1 = info[i]
            if c0 != cc:  # ô gộp bắt đầu ở cột khác (chồng lấn) – bỏ qua cột
                cc += 1
                continue
            rect, lines = cells[i]
            span = c1 - c0
            wdt = xs[c1] - xs[c0]
            tcpr = '<w:tcW w:w="%d" w:type="dxa"/>' % tw(wdt)
            if span > 1:
                tcpr += '<w:gridSpan w:val="%d"/>' % span
            if r1 - r0 > 1:
                tcpr += '<w:vMerge w:val="restart"/>' if rr == r0 else "<w:vMerge/>"
            if not borderless:
                X0, X1, Y0, Y1 = xs[c0], xs[c1], ys[r0], ys[r1]
                tcpr += "<w:tcBorders>%s%s%s%s</w:tcBorders>" % (
                    _border("top", _edge(hs, X0, X1, Y0)), _border("left", _edge(vs, Y0, Y1, X0)),
                    _border("bottom", _edge(hs, X0, X1, Y1)), _border("right", _edge(vs, Y0, Y1, X1)))
            fill = None
            for fr, col in (fills or []):
                if fr.contains((rect.tl + rect.br) / 2) and fr.width <= tblw * 1.01 + 2:
                    fill = col
                    break
            if fill:
                tcpr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill
            tcpr += '<w:vAlign w:val="top"/>'
            if rr == r0:
                _CTX["in_table"] = True
                try:
                    body = stack_xml(lines, xs[c0], xs[c1], ys[r0], cols_hint[i])
                finally:
                    _CTX["in_table"] = False
            else:
                body = spacer_xml(1)
            out.append("<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>" % (tcpr, body))
            cc = c1
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


# =============================================================================
#  NHÓM CHỮ SONG SONG (quốc hiệu | cơ quan, nơi nhận | chữ ký) -> bảng ẩn viền
# =============================================================================
def _bands(lines):
    lines = sorted(lines, key=lambda l: l.top)
    bands = []
    for ln in lines:
        if bands:
            b = bands[-1]
            btop, bbot = min(l.top for l in b), max(l.bot for l in b)
            ov = min(bbot, ln.bot) - max(btop, ln.top)
            if ov > 0.45 * min(ln.bot - ln.top, bbot - btop):
                b.append(ln)
                continue
        bands.append([ln])
    return [sorted(b, key=lambda l: l.x0) for b in bands]


def _is_multi(band, gapmin=18):
    return len(band) >= 2 and any(band[i + 1].x0 - band[i].x1 > gapmin for i in range(len(band) - 1))


def _columns(lines):
    iv = sorted((l.x0, l.x1) for l in lines)
    cols = []
    for a, b in iv:
        if cols and a <= cols[-1][1] + 6:
            cols[-1][1] = max(cols[-1][1], b)
        else:
            cols.append([a, b])
    return cols


def layout_groups(free_lines):
    """Trả về (groups, others). Mỗi group: dict(lines, cols)."""
    bands = _bands(free_lines)
    groups, others = [], []
    i = 0
    while i < len(bands):
        b = bands[i]
        if not _is_multi(b):
            others += b
            i += 1
            continue
        g = list(b)
        cols = _columns(g)
        j = i + 1
        while j < len(bands):
            nb = bands[j]
            gap = min(l.top for l in nb) - max(l.bot for l in g)
            size = max(l.size for l in nb)
            if gap > 8 * size:
                break
            trial = _columns(g + nb)
            # dòng mới không được nối liền các cột cũ (nếu nối -> là đoạn văn thường)
            # và không được tạo thêm cột mới (vd tiêu đề căn giữa nằm giữa 2 cột)
            if len(trial) != len(cols):
                break
            if not _is_multi(nb):
                # dòng đơn: chỉ nhận nếu thuộc hẳn 1 cột (thẳng lề trái / phải hoặc cùng tâm với cột)
                l0 = nb[0]
                if not any(c[0] - 2 <= l0.x0 and l0.x1 <= c[1] + 2 and
                           (abs(l0.x0 - c[0]) < 1.5 or abs(l0.x1 - c[1]) < 1.5 or
                            abs(l0.c - (c[0] + c[1]) / 2) < 3) for c in cols):
                    break
            g += nb
            cols = trial
            j += 1
        if len(cols) >= 2:
            groups.append({"lines": g, "cols": cols})
        else:
            others += g
        i = j
    return groups, others


# =============================================================================
#  ẢNH (chữ ký, con dấu, logo...)
# =============================================================================
def anchor_xml(rid, rect, pid, behind=True):
    E = 12700
    return ('<w:r><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            'relativeHeight="%d" behindDoc="%d" locked="0" layoutInCell="0" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/>'
            '<wp:positionH relativeFrom="page"><wp:posOffset>%d</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="page"><wp:posOffset>%d</wp:posOffset></wp:positionV>'
            '<wp:extent cx="%d" cy="%d"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
            '<wp:docPr id="%d" name="Hinh %d"/><wp:cNvGraphicFramePr>'
            '<a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/>'
            '</wp:cNvGraphicFramePr>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:nvPicPr><pic:cNvPr id="%d" name="Hinh%d.png"/><pic:cNvPicPr/></pic:nvPicPr>'
            '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            '</wp:anchor></w:drawing></w:r>') % (
        251659264 + pid, 1 if behind else 0, int(rect.x0 * E), int(rect.y0 * E), int(rect.width * E), int(rect.height * E),
        pid, pid, pid, pid, rid, int(rect.width * E), int(rect.height * E))


# =============================================================================
#  XÂY DỰNG TÀI LIỆU
# =============================================================================
def pdf_to_docx(doc, out, dpi=200, progress=None, ocr=True):
    from docx import Document
    from docx.shared import Pt
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls, qn
    import convert

    d = Document()
    # font mặc định Times New Roman 13
    st = d.styles["Normal"]
    st.font.name = core.DEFAULT_FAMILY
    st.font.size = Pt(13)
    rpr = st.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = parse_xml('<w:rFonts %s/>' % nsdecls("w"))
        rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), core.DEFAULT_FAMILY)
    st.paragraph_format.space_before = Pt(0)
    st.paragraph_format.space_after = Pt(0)
    # chế độ Word 2013+ (vị trí bảng tính theo mép viền)
    for cs in d.settings.element.iter(qn("w:compatSetting")):
        if cs.get(qn("w:name")) == "compatibilityMode":
            cs.set(qn("w:val"), "15")

    body = d.element.body
    for p in list(body):
        if p.tag != qn("w:sectPr"):
            body.remove(p)
    final_sect = body.find(qn("w:sectPr"))
    ns = nsdecls("w", "r", "wp")
    pid = [1]

    def add(xml):
        final_sect.addprevious(parse_xml(xml.replace("<w:p>", "<w:p %s>" % ns, 1) if xml.startswith("<w:p>")
                                         else xml.replace("<w:tbl>", "<w:tbl %s>" % ns, 1)))

    hf_pages = []
    _CTX["img"] = lambda png: d.part.get_or_add_image(io.BytesIO(png))[0]
    _CTX["pid"] = pid
    n = doc.page_count
    for pno in range(n):
        page = doc[pno]
        W, H = page.rect.width, page.rect.height
        rot = page.rotation_matrix
        # ---- trang SCAN (ảnh): nhận dạng chữ tiếng Việt offline -> văn bản Word gõ được
        scan = None
        if ocr:
            try:
                import ocrpage
                if ocrpage.ocr_available() and ocrpage.is_scanned(page):
                    scan = ocrpage.analyze(page)
            except Exception:
                scan = None
        if scan is not None:
            rot = fitz.Identity          # toạ độ OCR đã là toạ độ hiển thị
            raw_lines = scan["lines"]
        else:
            raw_lines = convert._page_lines(page)
        if scan is not None:
            tables = scan["tables"]
        else:
            try:
                tables = [t for t in page.find_tables().tables if t.row_count and t.col_count]
            except Exception:
                tables = []
        math_rects = []
        if scan is None:
            # dòng nhìn thấy: gộp mảnh công thức, chỉ số trên/dưới; công thức xếp tầng -> ảnh trong dòng
            try:
                import vlines
                tcells = [fitz.Rect(c) * rot for t in tables for c in t.cells if c]
                lines, math_rects = vlines.build(page, raw_lines, rot, tcells)
            except Exception:
                lines = [Ln(x, rot) for x in raw_lines]
        else:
            lines = [Ln(x, rot) for x in raw_lines]
        lines = [l for l in lines if l.text]
        segs = scan["segs"] if scan is not None else _segments(page, rot)
        fills = []
        try:
            for dr in (page.get_drawings() if scan is None else []):
                f = dr.get("fill")
                if f and len(f) == 3 and tuple(f) != (1, 1, 1) and dr.get("rect") is not None:
                    fills.append((fitz.Rect(dr["rect"]) * rot,
                                  "%02X%02X%02X" % tuple(int(round(v * 255)) for v in f)))
        except Exception:
            pass

        # ---- phân chữ vào ô bảng
        elems = []  # (top, bottom, kind, data)
        used = set()
        for t in tables:
            tcells = []
            for c in t.cells:
                if not c:
                    continue
                r = fitz.Rect(c) * rot
                inside = []
                for k, l in enumerate(lines):
                    if k in used:
                        continue
                    cx, cy = l.c, (l.top + l.bot) / 2
                    if r.x0 - 0.5 <= cx <= r.x1 + 0.5 and r.y0 - 0.5 <= cy <= r.y1 + 0.5:
                        inside.append(l)
                        used.add(k)
                tcells.append((r, inside))
            if tcells:
                tb = fitz.Rect(t.bbox) * rot
                elems.append((tb.y0, tb.y1, "table", tcells))
        free = [l for k, l in enumerate(lines) if k not in used]

        # ---- nhóm chữ song song -> bảng ẩn viền
        groups, others = layout_groups(free)
        for g in groups:
            gl = g["lines"]
            cols = g["cols"]
            # Dòng đáp án "A. ...  B. ...  C. ...  D. ..." (mỗi cột thẳng lề trái, mỗi hàng 1 dòng / cột)
            # -> đoạn văn có điểm dừng TAB như người soạn đề trong Word (dễ sửa, công thức không lệch)
            bands_g = _bands(gl)
            tabbable = True
            for ci, c in enumerate(cols):
                cl = [l for l in gl if c[0] - 1 <= l.c <= c[1] + 1]
                if cl and max(l.x0 for l in cl) - min(l.x0 for l in cl) > 2.0:
                    tabbable = False
            for bd in bands_g:
                for c in cols:
                    if sum(1 for l in bd if c[0] - 1 <= l.c <= c[1] + 1) > 1:
                        tabbable = False
            if tabbable and any(len(bd) > 1 for bd in bands_g):
                for bd in bands_g:
                    bd = sorted(bd, key=lambda l: l.x0)
                    mainl = max(bd, key=lambda l: l.size)
                    pp = Para([mainl])
                    elems.append((pp.box_top(), pp.box_bot(), "tabs", (bd, pp)))
                continue
            top = min(l.top for l in gl)
            bot = max(l.bot for l in gl)
            # ranh giới cột: giữa các khoảng trống
            edges = [cols[0][0]]
            for a, b in zip(cols, cols[1:]):
                edges.append((a[1] + b[0]) / 2)
            edges.append(min(W - 2, cols[-1][1] + 6))
            cells = []
            for ci in range(len(cols)):
                cl = [l for l in gl if edges[ci] <= l.c <= edges[ci + 1]]
                # vùng nhận biết căn giữa = phạm vi chữ của cột; cột mà mọi dòng thẳng lề trái -> căn trái
                same_left = len(cl) > 1 and max(l.x0 for l in cl) - min(l.x0 for l in cl) < 1.5
                cells.append((fitz.Rect(edges[ci], top, edges[ci + 1], bot), cl,
                              (cols[ci][0], cols[ci][1], not same_left)))
            elems.append((top, bot, "layout", cells))

        # ---- đoạn văn thường
        area_l = min([l.x0 for l in lines] + [e[3][0][0].x0 for e in elems if e[2] == "table"] +
                     [e[3][0][0].x0 for e in elems if e[2] == "layout"] + [W * 0.1])
        area_r = max([l.x1 for l in lines] + [max(c[0].x1 for c in e[3]) for e in elems if e[2] == "table"]
                     + [W * 0.5])
        area_r = min(area_r, W - 1)
        for p in group_paras(others, area_l, area_r):
            elems.append((p.box_top(), p.box_bot(), "para", p))
        elems.sort(key=lambda e: e[0])

        # ---- chữ đầu trang / chân trang (tiêu đề, "Trang x/y", số trang) -> Header / Footer của Word
        #      (không bị đẩy sang trang sau khi phần thân dài thêm vài pt)
        def _no_math(e):
            if e[2] == "para":
                return not e[3].has_math
            if e[2] == "tabs":
                return not any(getattr(l, "has_math", False) for l in e[3][0])
            if e[2] == "layout":
                return not any(getattr(l, "has_math", False) for c in e[3] for l in c[1])
            return False

        def _hf_xml(sub, start):
            parts, cur, prev = [], start, None
            for top, bot, kind, data in sub:
                gap = top - cur
                if kind == "para":
                    parts.append(para_xml(data, area_l, area_r, gap))
                elif kind == "tabs":
                    parts.append(tabpara_xml(data[0], data[1], area_l, gap))
                else:
                    if prev == "layout" or gap > 0.5:
                        parts.append(spacer_xml(gap if gap > 0.5 else 1))
                    parts.append(table_xml(data, area_l, borderless=True))
                cur, prev = max(cur, bot), kind
            if prev == "layout":
                parts.append(spacer_xml(1))
            return "".join(parts)

        hdr_el = [e for e in elems if e[1] <= H * 0.075 and _no_math(e)]
        ftr_el = [e for e in elems if e[0] >= H * 0.925 and _no_math(e)]
        if len(hdr_el) == len(elems):
            hdr_el = []
        if len(ftr_el) + len(hdr_el) >= len(elems):
            ftr_el = []
        hdr_dist = min(e[0] for e in hdr_el) if hdr_el else 0.0
        ftr_dist = (H - max(e[1] for e in ftr_el)) if ftr_el else 0.0
        hf_pages.append((_hf_xml(hdr_el, hdr_dist) if hdr_el else "",
                         _hf_xml(ftr_el, min(e[0] for e in ftr_el)) if ftr_el else ""))
        hdr_bot = max((e[1] for e in hdr_el), default=0.0)
        ftr_top = min((e[0] for e in ftr_el), default=H)
        elems = [e for e in elems if e not in hdr_el and e not in ftr_el]

        # ---- ảnh chữ ký / con dấu
        anchors = ""
        try:
            pieces = scan["pieces"] if scan is not None else convert._graphics_layer(doc, pno, raw_lines, tables, dpi,
                                                                                    keep_inner=True)
        except Exception:
            pieces = []
        # bỏ mảnh hình nằm trong vùng công thức (gạch phân số, dấu căn... đã có trong ảnh công thức)
        if math_rects:
            def _inside(r):
                for m in math_rects:
                    ix = fitz.Rect(r) & m
                    if not ix.is_empty and ix.get_area() >= 0.6 * max(0.01, fitz.Rect(r).get_area()):
                        return True
                return False
            pieces = [pc for pc in pieces if not _inside(pc[0])]
        for rect, png in pieces:
            rid, _ = d.part.get_or_add_image(io.BytesIO(png))
            anchors += anchor_xml(rid, rect, pid[0])
            pid[0] += 1

        # ---- lề trang
        top_m = max(0.0, min([e[0] for e in elems] + [H]) if elems else 36.0)
        if not elems:
            top_m = 36.0
        last_bot = max([e[1] for e in elems] + [top_m])
        bot_m = max(0.0, min(H - last_bot - 4, (H - last_bot) * 0.5))
        if hdr_el:
            top_m = max(top_m, hdr_bot + 0.5)
        if ftr_el:
            bot_m = max(bot_m, min(H - ftr_top + 1, H - last_bot - 1))
        sect = ('<w:sectPr %s><w:type w:val="nextPage"/><w:pgSz w:w="%d" w:h="%d"%s/>'
                '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" w:header="%d" w:footer="%d" w:gutter="0"/>'
                '<w:cols w:space="720"/></w:sectPr>') % (
            nsdecls("w"), tw(W), tw(H), ' w:orient="landscape"' if W > H else "",
            tw(top_m), tw(max(0, W - area_r - 1)), tw(bot_m), tw(area_l), tw(hdr_dist), tw(ftr_dist))

        # ---- ghi nội dung
        cur = top_m
        prev_kind = None
        first_anchor_done = False
        for top, bot, kind, data in elems:
            gap = top - cur
            if kind in ("para", "tabs"):
                a = ""
                if not first_anchor_done:
                    a, first_anchor_done = anchors, True
                if kind == "para":
                    add(para_xml(data, area_l, area_r, gap, a))
                else:
                    add(tabpara_xml(data[0], data[1], area_l, gap, a))
            else:
                if prev_kind in ("table", "layout") or gap > 0.5:
                    a = ""
                    if not first_anchor_done:
                        a, first_anchor_done = anchors, True
                    add(spacer_xml(gap if gap > 0.5 else 1, a))
                if kind == "table":
                    add(table_xml(data, area_l, segs, fills))
                else:
                    add(table_xml(data, area_l, borderless=True))
            cur = max(cur, bot) if kind != "para" else max(cur, bot)
            prev_kind = kind

        # đoạn cuối trang mang ngắt trang (section) + neo ảnh nếu chưa có
        a = "" if first_anchor_done else anchors
        endp = ('<w:p %s><w:pPr><w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/>'
                '<w:rPr><w:sz w:val="2"/><w:szCs w:val="2"/></w:rPr>%s</w:pPr>%s</w:p>')
        if pno < n - 1:
            final_sect.addprevious(parse_xml(endp % (ns, sect, a)))
        else:
            final_sect.addprevious(parse_xml(endp % (ns, "", a)))
            new = parse_xml(sect)
            body.replace(final_sect, new)
            final_sect = new
        if progress:
            progress(pno + 1, n)
    # ---- gắn Header / Footer riêng cho từng trang (mỗi trang PDF = 1 section)
    try:
        secs = d.sections
        for i, sec in enumerate(secs):
            hx, fx = hf_pages[i] if i < len(hf_pages) else ("", "")
            for part, xml in ((sec.header, hx), (sec.footer, fx)):
                part.is_linked_to_previous = False
                el = part._element
                for ch in list(el):
                    el.remove(ch)
                root = parse_xml('<w:hdr %s>%s</w:hdr>' % (nsdecls("w", "r", "wp"), xml or spacer_xml(1)))
                for ch in list(root):
                    el.append(ch)
    except Exception:
        pass
    d.save(out)
    return out
