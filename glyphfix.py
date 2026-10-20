# -*- coding: utf-8 -*-
"""
SỬA MÃ CHỮ BỊ SAI TRONG PDF (vd "Trảng" đọc ra "Trdng").

Nhiều file PDF (in qua máy in ảo, xuất từ phần mềm cũ...) có bảng mã chữ (ToUnicode) khai báo sai
cho một số chữ có dấu: chữ HIỆN TRÊN TRANG đúng nhưng khi đọc ra lại thành chữ khác.
Cách sửa: so HÌNH DẠNG thật của chữ trên trang với hình chữ mẫu (Times New Roman / Arial...)
của mọi chữ tiếng Việt; nếu chữ đọc ra không giống hình mà có chữ khác giống hẳn -> thay.
Mỗi cặp (font, chữ) chỉ kiểm tra 1 lần cho cả tài liệu -> nhanh.
"""
import numpy as np

from core import fitz

_VN_LOWER = ("aàáảãạăằắẳẵặâầấẩẫậbcdđeèéẻẽẹêềếểễệghiìíỉĩịklmnoòóỏõọôồốổỗộơờớởỡợ"
             "pqrstuùúủũụưừứửữựvxyỳýỷỹỵfjwz")
CANDIDATES = _VN_LOWER + _VN_LOWER.upper() + "0123456789"
_CAND_SET = set(CANDIDATES)
PX = 44  # cỡ chữ (pixel) dùng để so hình


def _ref_family(fontname, fm):
    n = (fontname or "").lower()
    for key, fam in (("arial", "Arial"), ("helvet", "Arial"), ("tahoma", "Tahoma"), ("verdana", "Verdana"),
                     ("calibri", "Calibri"), ("sans", "Arial"), ("cour", "Courier New"),
                     ("roboto", "Arial"), ("segoe", "Arial"), ("open", "Arial"), ("lato", "Arial"),
                     ("montserrat", "Arial"), ("source", "Arial"), ("noto sans", "Arial")):
        if key in n and fam in fm.families:
            return fam
    for fam in ("Times New Roman", "Liberation Serif", "DejaVu Serif"):
        if fam in fm.families:
            return fam
    return fm.default_family()


class GlyphFixer:
    def __init__(self, fm):
        self.fm = fm
        self.maps = {}      # (fontname, flags) -> {ký tự đọc ra: ký tự đúng}
        self._cands = {}    # (path, H, base) -> (stack bool[N,H,W], W)
        self._pil = {}

    # ---------------------------------------------------------------- mẫu chữ
    def _pilfont(self, path):
        f = self._pil.get(path)
        if f is None:
            from PIL import ImageFont
            f = ImageFont.truetype(path, PX)
            self._pil[path] = f
        return f

    def _candidates(self, path, H, base, W):
        key = (path, H, base, W)
        c = self._cands.get(key)
        if c is None:
            from PIL import Image, ImageDraw
            font = self._pilfont(path)
            stack = np.zeros((len(CANDIDATES), H, W), dtype=bool)
            for i, ch in enumerate(CANDIDATES):
                im = Image.new("L", (W, H), 0)
                ImageDraw.Draw(im).text((2, base), ch, font=font, fill=255, anchor="ls")
                stack[i] = np.asarray(im) > 110
            c = stack
            self._cands[key] = c
        return c

    # ---------------------------------------------------------------- so hình
    def _verify(self, page, ch, span):
        """Trả về ký tự đúng cho ký tự 'ch' (dựa trên hình của nó trên trang)."""
        c = ch["c"]
        size = span["size"] or 12
        zoom = PX / size
        bbox = fitz.Rect(ch["bbox"])
        org = fitz.Point(ch["origin"])
        # vùng cắt: từ trên đỉnh dấu (cao hơn bbox) tới dưới chân chữ
        top = org.y - size * 1.15
        bot = org.y + size * 0.32
        clip = fitz.Rect(bbox.x0 - size * 0.05, top, bbox.x1 + size * 0.05, bot)
        if clip.width <= 0 or clip.height <= 0:
            return c
        try:
            pm = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, colorspace=fitz.csGRAY,
                                 alpha=False, annots=False)
        except Exception:
            return c
        g = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.stride)[:, :pm.width]
        orig = g < 128
        if orig.sum() < 6:
            return c
        H = pm.height
        base = int(round((org.y - top) * zoom))
        W = pm.width + 6
        o = np.zeros((H, W), dtype=bool)
        o[:, 2:2 + pm.width] = orig
        fl = span.get("flags", 0)
        bold = bool(fl & 16) or "bold" in span.get("font", "").lower()
        ital = bool(fl & 2) or "italic" in span.get("font", "").lower()
        fam = _ref_family(span.get("font", ""), self.fm)
        path, _ = self.fm.resolve(fam, bold, ital)
        if not path:
            return c
        cand = self._candidates(path, H, base, W)
        best = np.zeros(len(CANDIDATES))
        osum = o.sum()
        csum = cand.sum(axis=(1, 2))
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-3, -2, -1, 0, 1, 2, 3):
                sh = np.roll(np.roll(o, dy, axis=0), dx, axis=1)
                inter = (cand & sh).sum(axis=(1, 2))
                iou = inter / np.maximum(1, csum + osum - inter)
                best = np.maximum(best, iou)
        bi = int(best.argmax())
        if c in _CAND_SET:
            sc = best[CANDIDATES.index(c)]
            # chữ đọc ra vẫn khá giống -> giữ nguyên (tránh sửa nhầm khi font khác mẫu)
            if sc >= best[bi] * 0.80 or best[bi] < 0.45:
                return c
            # chỉ thay khi chữ đúng khác hẳn (dấu / hình) và giống hơn rõ rệt
            if best[bi] - sc < 0.12:
                return c
            # không bao giờ đổi chữ số <-> chữ cái (số trang, số liệu) – dễ nhầm khi font khác mẫu
            if c.isdigit() != CANDIDATES[bi].isdigit():
                return c
            # chữ / số không dấu: chỉ đổi khi hình đọc ra RẤT không giống (lỗi mã thật, vd 'd' thay cho 'ả')
            if c.isascii() and (best[bi] < 0.6 or sc > best[bi] * 0.72):
                return c
            r = CANDIDATES[bi]
            # chỉ sửa kiểu lỗi mã thật: chữ KHÔNG DẤU bị đọc thay cho chữ CÓ DẤU (vd 'd' -> 'ả').
            # Không bao giờ: đổi chữ có dấu sang chữ khác, đổi hoa <-> thường, đổi sang chữ không dấu.
            if not c.isascii() or r.isascii() or c.isupper() != r.isupper():
                return c
            return r
        return c

    # ---------------------------------------------------------------- dùng chung
    def fix_page_spans(self, page, raw):
        """raw: kết quả page.get_text('rawdict'). Gán span['text'] đã sửa cho mọi span.
        Phân biệt theo MÃ HÌNH CHỮ (glyph): 2 hình khác nhau có thể cùng bị đọc ra 1 chữ (vd 'd' và 'ả')."""
        gmap = {}
        try:
            for sp in page.get_texttrace():
                for t in sp["chars"]:
                    gmap[(round(t[2][0], 1), round(t[2][1], 1))] = t[1]
        except Exception:
            pass
        for b in raw.get("blocks", []):
            if b.get("type", 0) != 0:
                continue
            for ln in b["lines"]:
                for s in ln["spans"]:
                    chars = s.get("chars")
                    if chars is None:
                        continue
                    if s.get("alpha", 255) == 0 or s.get("legacy"):   # chữ ẩn (OCR) / đã đổi từ mã cũ -> không kiểm
                        s["text"] = "".join(ch["c"] for ch in chars)
                        continue
                    key = (s.get("font", ""), s.get("flags", 0) & 18)
                    m = self.maps.setdefault(key, {})
                    out = []
                    for ch in chars:
                        c = ch["c"]
                        if c.isspace() or not c:
                            out.append(c)
                            continue
                        o = ch.get("origin", (0, 0))
                        k = (c, gmap.get((round(o[0], 1), round(o[1], 1)), -1))
                        r = m.get(k)
                        if r is None:
                            try:
                                r = self._verify(page, ch, s)
                            except Exception:
                                r = c
                            m[k] = r
                        out.append(r)
                    # an toàn: nếu "sửa" quá nhiều chữ trong 1 đoạn -> nhiều khả năng so hình sai, giữ nguyên chữ gốc
                    orig = [ch["c"] for ch in chars]
                    nchg = sum(1 for a, b in zip(orig, out) if a != b)
                    nlet = sum(1 for a in orig if a.isalpha())
                    if nchg > max(2, 0.25 * nlet):
                        out = orig
                    s["text"] = "".join(out)
        return raw


_FIXERS = {}


def get_fixer(fm, doc_id):
    """1 bộ sửa cho mỗi tài liệu (bảng sửa mã theo font dùng chung các trang)."""
    f = _FIXERS.get(doc_id)
    if f is None or f.fm is not fm:
        f = GlyphFixer(fm)
        _FIXERS[doc_id] = f
    return f


def page_dict(page, fm=None, flags=None, doc_id=None):
    """Như page.get_text('dict') nhưng chữ đã được kiểm tra / sửa mã sai.
    fm=None -> tự nạp danh sách font (dùng khi gọi từ chức năng chuyển đổi)."""
    if flags is None:
        flags = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES
    raw = page.get_text("rawdict", flags=flags)
    try:
        import legacy
        legacy.fix_dict(raw)
    except Exception:
        pass
    if fm is None:
        fm = _default_fm()
    if fm is None or not fm.families:
        for b in raw.get("blocks", []):
            for ln in b.get("lines", []):
                for s in ln["spans"]:
                    s["text"] = "".join(ch["c"] for ch in s.get("chars", []))
        return raw
    fx = get_fixer(fm, doc_id if doc_id is not None else id(page.parent))
    return fx.fix_page_spans(page, raw)


_FM = [None]


def _default_fm():
    if _FM[0] is None:
        try:
            import core
            _FM[0] = core.FontManager(core.scan_fonts())
        except Exception:
            _FM[0] = False
    return _FM[0] or None
