# -*- coding: utf-8 -*-
"""
Lõi xử lý PDF cho phần mềm Sửa PDF Offline.
- Sửa chữ tại chỗ: xoá đúng chữ cũ (giữ nguyên khung bảng, đường kẻ, hình ảnh, chữ ký)
  rồi ghi chữ mới vào đúng vị trí cũ -> văn bản không bị nhảy.
- Xuất PDF / Word (giữ bố cục) / Word (dạng chảy) / Word (ảnh trang) / PNG / JPG / TXT.
"""
import os
import re
import sys
import json
import hashlib

try:
    import pymupdf as fitz
except ImportError:  # bản PyMuPDF cũ
    import fitz

# ----------------------------------------------------------------------------
#  FONT
# ----------------------------------------------------------------------------
DEFAULT_FAMILY = "Times New Roman"
FALLBACK_FAMILIES = ["Times New Roman", "Liberation Serif", "DejaVu Serif", "Arial"]


def app_data_dir():
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.join(os.path.expanduser("~"), ".cache")
    d = os.path.join(base, "SuaPDF")
    os.makedirs(d, exist_ok=True)
    return d


def font_dirs():
    if sys.platform.startswith("win"):
        win = os.environ.get("WINDIR", r"C:\Windows")
        dirs = [os.path.join(win, "Fonts")]
        la = os.environ.get("LOCALAPPDATA")
        if la:
            dirs.append(os.path.join(la, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        dirs = ["/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    else:
        dirs = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
                os.path.expanduser("~/.local/share/fonts")]
    # thư mục fonts đặt cạnh file exe (người dùng có thể tự chép thêm font .ttf vào)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    dirs.append(os.path.join(exe_dir, "fonts"))
    return [d for d in dirs if os.path.isdir(d)]


def _name(tt, ids):
    nt = tt["name"]
    for nid in ids:
        for rec in nt.names:
            if rec.nameID == nid and rec.platformID == 3 and rec.langID == 0x409:
                try:
                    return rec.toUnicode()
                except Exception:
                    pass
        for rec in nt.names:
            if rec.nameID == nid:
                try:
                    return rec.toUnicode()
                except Exception:
                    pass
    return None


def scan_fonts(progress=None):
    """Trả về dict: family -> {'regular','bold','italic','bolditalic','vn'}"""
    from fontTools.ttLib import TTFont
    cache_path = os.path.join(app_data_dir(), "fonts_cache.json")
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    files = []
    for d in font_dirs():
        for root, _, names in os.walk(d):
            for n in names:
                if n.lower().endswith((".ttf", ".otf")):
                    files.append(os.path.join(root, n))
    new_cache = {}
    for i, path in enumerate(files):
        try:
            st = os.stat(path)
            key = "%s|%d|%d" % (path, st.st_size, int(st.st_mtime))
        except OSError:
            continue
        info = cache.get(key)
        if info is None:
            try:
                tt = TTFont(path, lazy=True, fontNumber=0)
                fam = _name(tt, [1])
                sub = (_name(tt, [2]) or "Regular").lower()
                cmap = tt.getBestCmap() or {}
                vn = all(c in cmap for c in (0x1EC7, 0x01A1, 0x01B0, 0x0111, 0x1EA0))
                mac = tt["head"].macStyle if "head" in tt else 0
                bold = bool(mac & 1) or "bold" in sub
                italic = bool(mac & 2) or "italic" in sub or "oblique" in sub
                tt.close()
                info = {"family": fam, "bold": bold, "italic": italic, "vn": vn}
            except Exception:
                info = {"family": None}
        new_cache[key] = info
        if progress and i % 25 == 0:
            progress(i, len(files))
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(new_cache, f)
    except Exception:
        pass
    fams = {}
    for key, info in new_cache.items():
        fam = info.get("family")
        if not fam:
            continue
        path = key.split("|")[0]
        style = ("bold" if info["bold"] else "") + ("italic" if info["italic"] else "")
        style = style or "regular"
        e = fams.setdefault(fam, {"vn": False})
        e["vn"] = e["vn"] or info.get("vn", False)
        if style not in e:
            e[style] = path
    # family phải có ít nhất 1 file dùng được
    out = {}
    for fam, e in fams.items():
        if any(k in e for k in ("regular", "bold", "italic", "bolditalic")):
            if "regular" not in e:
                e["regular"] = e.get("bold") or e.get("italic") or e.get("bolditalic")
            out[fam] = e
    return out


class FontManager:
    def __init__(self, families):
        self.families = families
        self._fonts = {}

    def default_family(self):
        for f in FALLBACK_FAMILIES:
            if f in self.families:
                return f
        return sorted(self.families)[0] if self.families else None

    def resolve(self, family, bold=False, italic=False):
        """-> (path, fake_bold)"""
        e = self.families.get(family) or self.families.get(self.default_family())
        if e is None:
            return None, False
        want = ("bold" if bold else "") + ("italic" if italic else "") or "regular"
        if want in e:
            return e[want], False
        if bold and italic and "bold" in e:
            return e["bold"], False
        if italic and "italic" in e:
            return e["italic"], bold
        return e["regular"], bold

    def font(self, path):
        f = self._fonts.get(path)
        if f is None:
            f = fitz.Font(fontfile=path)
            self._fonts[path] = f
        return f


def font_tag(path, session=""):
    """Tên font ghi vào PDF. Mỗi lần mở file dùng một mã phiên riêng, để KHÔNG BAO GIỜ
    dùng lại font đã bị rút gọn (subset) trong file đã lưu trước đó – font rút gọn chỉ
    còn các chữ cái cũ, gõ chữ mới sẽ hiện ô vuông."""
    return "S" + session + hashlib.md5(path.encode("utf-8")).hexdigest()[:6]


# ----------------------------------------------------------------------------
#  DỮ LIỆU DÒNG CHỮ
# ----------------------------------------------------------------------------
class Line:
    __slots__ = ("bbox", "text", "spans", "size", "color", "bold", "italic",
                 "origin", "font", "ascender", "horizontal", "invisible")

    def __init__(self, ln, rot=None):
        spans = [s for s in ln["spans"] if s["text"].strip() or len(ln["spans"]) == 1]
        if not spans:
            spans = ln["spans"]
        self.spans = spans
        self.bbox = fitz.Rect(ln["bbox"])
        self.text = norm_text("".join(s["text"] for s in ln["spans"])).rstrip()
        s0 = max(spans, key=lambda s: len(s["text"].strip()))
        self.size = round(s0["size"] * 2) / 2
        c = s0.get("color", 0)
        self.color = ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)
        fl = s0.get("flags", 0)
        fname = s0.get("font", "")
        self.bold = bool(fl & 16) or "bold" in fname.lower()
        self.italic = bool(fl & 2) or "italic" in fname.lower()
        # toạ độ HIỂN THỊ (đã tính góc xoay của trang)
        rot = rot or fitz.Identity
        self.origin = fitz.Point(ln["spans"][0]["origin"]) * rot
        self.bbox = fitz.Rect(ln["bbox"]) * rot
        self.font = fname
        self.ascender = s0.get("ascender", 0.89) or 0.89
        d = fitz.Point(ln.get("dir", (1, 0))) * fitz.Matrix(rot.a, rot.b, rot.c, rot.d, 0, 0)
        self.horizontal = abs(d.x - 1) < 1e-3 and abs(d.y) < 1e-3
        # chữ ẩn (lớp OCR của bản scan): chữ thấy được thực ra là ảnh
        self.invisible = all(s.get("alpha", 255) == 0 for s in spans)


# Một số font (vd Times New Roman của Windows) dùng chung 1 hình chữ cho "-" và
# gạch mềm U+00AD, nên khi đọc lại PDF dấu "-" bị trả về ký tự lạ (ẩn, không hiện).
_NORM = {0x00AD: "-", 0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2212: "-",
         0x00A0: " ", 0x2007: " ", 0x202F: " ", 0xFEFF: None, 0x200B: None,
         0x0000: None, 0xFFFD: None}  # ký tự hỏng (ô vuông) -> bỏ, để gõ lại


def norm_text(s):
    return s.translate(_NORM)


def clean_font_name(name):
    """'ABCDEF+TimesNewRomanPS-BoldMT' -> 'Times New Roman'"""
    n = name.split("+")[-1]
    n = re.split(r"[-,]", n)[0]
    n = re.sub(r"(PSMT|PS|MT)$", "", n)
    known = {"TimesNewRoman": "Times New Roman", "Times": "Times New Roman",
             "LiberationSerif": "Times New Roman", "ArialMT": "Arial",
             "CourierNew": "Courier New", "Helvetica": "Arial", "Tahoma": "Tahoma",
             "Calibri": "Calibri", "Cambria": "Cambria", "Verdana": "Verdana"}
    if n in known:
        return known[n]
    if " " not in n:
        n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n)
    return n or DEFAULT_FAMILY


# ----------------------------------------------------------------------------
#  TÀI LIỆU
# ----------------------------------------------------------------------------
REDACT_KW = dict(images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
                 graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
                 text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0))


def apply_text_only_redactions(page):
    """Chỉ xoá CHỮ trong vùng đánh dấu – giữ hình, chữ ký, đường kẻ bảng."""
    try:
        page.apply_redactions(**REDACT_KW)
    except TypeError:  # PyMuPDF cũ không có tham số text/graphics
        page.apply_redactions(images=REDACT_KW["images"])


class PdfDocument:
    MAX_UNDO = 30

    def __init__(self, path, password=None):
        self.path = path
        with open(path, "rb") as f:
            data = f.read()
        self.doc = fitz.open(stream=data, filetype="pdf")
        self.undo_stack, self.redo_stack = [], []
        self.modified = False
        self._lines = {}
        self.session = os.urandom(3).hex()

    # ---- trạng thái
    def needs_pass(self):
        return self.doc.needs_pass

    def authenticate(self, pw):
        return self.doc.authenticate(pw)

    def page_count(self):
        return self.doc.page_count

    def has_digital_signature(self):
        try:
            for page in self.doc:
                for w in page.widgets() or []:
                    if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                        return True
        except Exception:
            pass
        return False

    def snapshot(self):
        self.undo_stack.append(self.doc.tobytes())
        if len(self.undo_stack) > self.MAX_UNDO:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.modified = True

    def _reload(self, data):
        self.doc = fitz.open(stream=data, filetype="pdf")
        self._lines.clear()

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.doc.tobytes())
        self._reload(self.undo_stack.pop())
        self.modified = True
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.doc.tobytes())
        self._reload(self.redo_stack.pop())
        self.modified = True
        return True

    # ---- đọc
    def lines(self, pno):
        if pno not in self._lines:
            page = self.doc[pno]
            flags = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES | getattr(fitz, "TEXT_MEDIABOX_CLIP", 0)
            d = page.get_text("dict", flags=flags)
            out = []
            for b in d["blocks"]:
                if b.get("type", 0) != 0:
                    continue
                for ln in b["lines"]:
                    if not "".join(s["text"] for s in ln["spans"]).strip():
                        continue
                    out.append(Line(ln, page.rotation_matrix))
            self._lines[pno] = out
        return self._lines[pno]

    def line_at(self, pno, x, y, pad=1.5):
        best = None
        for ln in self.lines(pno):
            r = fitz.Rect(ln.bbox)
            r.x0 -= pad; r.y0 -= pad; r.x1 += pad; r.y1 += pad
            if r.contains(fitz.Point(x, y)):
                if best is None or ln.bbox.get_area() < best.bbox.get_area():
                    best = ln
        return best

    def render(self, pno, scale):
        page = self.doc[pno]
        return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, annots=True)

    # ---- sửa
    @staticmethod
    def _shrunk(r, page, k=0.28):
        r = fitz.Rect(r) * page.rotation_matrix      # sang toạ độ hiển thị
        h = r.height
        r = fitz.Rect(r.x0 + 0.2, r.y0 + h * k, r.x1 - 0.2, r.y1 - h * k)
        return r * page.derotation_matrix             # trả về toạ độ gốc

    def _erase_line(self, page, line):
        for s in line.spans:
            page.add_redact_annot(self._shrunk(s["bbox"], page), fill=False)
        apply_text_only_redactions(page)

    def write_text(self, page, fm, x, baseline, text, family, size, color, bold, italic, line_gap=1.2):
        path, fake_bold = fm.resolve(family, bold, italic)
        if path is None:
            raise RuntimeError("Không tìm thấy font: %s" % family)
        tag = font_tag(path, self.session)
        kw = dict(fontsize=size, fontname=tag, fontfile=path, color=color)
        if fake_bold:
            kw.update(render_mode=2, border_width=size * 0.035)
        for i, t in enumerate(text.split("\n")):
            if t == "":
                continue
            # x, baseline là toạ độ hiển thị -> đổi về toạ độ gốc của trang
            p = fitz.Point(x, baseline + i * size * line_gap) * page.derotation_matrix
            page.insert_text(p, t, rotate=page.rotation, **kw)

    def replace_line(self, pno, line, new_text, fm, family, size, color, bold, italic):
        self.snapshot()
        page = self.doc[pno]
        self._erase_line(page, line)
        if line.invisible:
            # bản scan có OCR: phủ trắng chữ ảnh cũ rồi mới ghi chữ mới
            r = fitz.Rect(line.bbox)
            r = fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1) * page.derotation_matrix
            page.draw_rect(r, color=None, fill=(1, 1, 1), overlay=True, width=0)
        if new_text.strip():
            self.write_text(page, fm, line.origin.x, line.origin.y, new_text,
                            family, size, color, bold, italic)
        self._lines.pop(pno, None)

    def add_text(self, pno, x, top, new_text, fm, family, size, color, bold, italic):
        if not new_text.strip():
            return
        self.snapshot()
        page = self.doc[pno]
        path, _ = fm.resolve(family, bold, italic)
        asc = fm.font(path).ascender if path else 0.89
        self.write_text(page, fm, x, top + asc * size, new_text, family, size, color, bold, italic)
        self._lines.pop(pno, None)

    def erase_text_in_rect(self, pno, rect):
        """Xoá chữ trong vùng – giữ khung bảng, hình, chữ ký."""
        self.snapshot()
        page = self.doc[pno]
        page.add_redact_annot(fitz.Rect(rect) * page.derotation_matrix, fill=False)
        apply_text_only_redactions(page)
        self._lines.pop(pno, None)

    def whiteout_rect(self, pno, rect, color=(1, 1, 1)):
        """Phủ màu trắng toàn bộ vùng (dùng cho PDF scan)."""
        self.snapshot()
        page = self.doc[pno]
        page.draw_rect(fitz.Rect(rect) * page.derotation_matrix, color=None, fill=color, overlay=True, width=0)
        self._lines.pop(pno, None)

    # ------------------------------------------------------------------------
    #  XUẤT FILE
    # ------------------------------------------------------------------------
    def final_bytes(self):
        """PDF cuối cùng, font đã thu gọn (subset) cho nhẹ."""
        data = self.doc.tobytes()
        try:
            tmp = fitz.open(stream=data, filetype="pdf")
            tmp.subset_fonts()
            data2 = tmp.tobytes(garbage=3, deflate=True)
            # kiểm tra file mới mở lại được và số trang khớp
            chk = fitz.open(stream=data2, filetype="pdf")
            if chk.page_count == self.doc.page_count:
                return data2
        except Exception:
            pass
        return self.doc.tobytes(garbage=3, deflate=True)

    def save_pdf(self, out):
        data = self.final_bytes()
        tmp = out + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, out)

    def save_images(self, out, dpi=200, fmt="png", progress=None):
        base, _ = os.path.splitext(out)
        n = self.doc.page_count
        files = []
        for i, page in enumerate(self.doc):
            pm = page.get_pixmap(dpi=dpi, alpha=False)
            p = out if n == 1 else "%s_trang_%03d.%s" % (base, i + 1, fmt)
            if fmt == "jpg":
                pm.save(p, jpg_quality=92) if "jpg_quality" in pm.save.__code__.co_varnames else pm.save(p)
            else:
                pm.save(p)
            files.append(p)
            if progress:
                progress(i + 1, n)
        return files

    def save_txt(self, out):
        with open(out, "w", encoding="utf-8-sig") as f:
            for i, page in enumerate(self.doc):
                if i:
                    f.write("\n\n")
                f.write(page.get_text("text", sort=True))

    def save_docx_flow(self, out, progress=None):
        """Word dạng chảy (pdf2docx): sửa thoải mái, bảng thành bảng Word, có thể lệch nhẹ."""
        from pdf2docx import Converter
        tmp_pdf = os.path.join(app_data_dir(), "_tmp_convert.pdf")
        with open(tmp_pdf, "wb") as f:
            f.write(self.doc.tobytes())
        cv = Converter(tmp_pdf)
        try:
            cv.convert(out, multi_processing=False)
        finally:
            cv.close()
            try:
                os.remove(tmp_pdf)
            except OSError:
                pass

    def save_docx_image(self, out, dpi=200, progress=None):
        """Word: mỗi trang là 1 ảnh nét cao – giống bản PDF 100%, không sửa được chữ."""
        return _docx_build(self.doc, out, dpi, with_text=False, progress=progress)

    def save_docx_layout(self, out, dpi=200, progress=None):
        """Word giữ nguyên bố cục + sửa được chữ:
        nền trang (khung bảng, đường kẻ, hình, chữ ký) là ảnh nằm dưới chữ,
        từng dòng chữ đặt đúng toạ độ cũ bằng khung (frame) -> không nhảy."""
        return _docx_build(self.doc, out, dpi, with_text=True, progress=progress)


# ----------------------------------------------------------------------------
#  WORD
# ----------------------------------------------------------------------------
def _xml_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _clean_xml_text(s):
    return "".join(ch for ch in s if ch in "\t\n" or ord(ch) >= 32)


def _docx_build(doc, out, dpi, with_text, progress=None):
    import io
    from docx import Document
    from docx.shared import Pt, Emu
    from docx.enum.section import WD_SECTION
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls, qn

    d = Document()
    # font mặc định Times New Roman
    st = d.styles["Normal"]
    st.font.name = DEFAULT_FAMILY
    st.font.size = Pt(13)
    rpr = st.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = parse_xml('<w:rFonts %s/>' % nsdecls("w"))
        rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), DEFAULT_FAMILY)
    pf = st.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0

    body = d.element.body
    for p in list(body.findall(qn("w:p"))):
        body.remove(p)

    n = doc.page_count
    pic_id = 1
    for i in range(n):
        page = doc[i]
        W, H = page.rect.width, page.rect.height
        sec = d.sections[-1] if i == 0 else d.add_section(WD_SECTION.NEW_PAGE)
        sec.page_width, sec.page_height = Pt(W), Pt(H)
        sec.orientation = 1 if W > H else 0
        sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Pt(0)
        sec.header_distance = sec.footer_distance = Pt(0)
        sec.gutter = Pt(0)

        # ---- ảnh nền
        hlines = []
        if with_text:
            rot = page.rotation_matrix
            rot0 = fitz.Matrix(rot.a, rot.b, rot.c, rot.d, 0, 0)
            dd = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES)
            for b in dd["blocks"]:
                if b.get("type", 0) != 0:
                    continue
                for ln in b["lines"]:
                    dv = fitz.Point(ln.get("dir", (1, 0))) * rot0
                    if all(s.get("alpha", 255) == 0 for s in ln["spans"]):
                        continue  # chữ ẩn OCR: đã có trong ảnh nền
                    if abs(dv.x - 1) < 1e-3 and "".join(s["text"] for s in ln["spans"]).strip():
                        hlines.append(ln)
            tmp = fitz.open()
            tmp.insert_pdf(doc, from_page=i, to_page=i)
            tp = tmp[0]
            # chỉ xoá chữ ngang (sẽ đặt lại bằng chữ Word); chữ xoay dọc giữ trong ảnh nền
            for ln in hlines:
                for s_ in ln["spans"]:
                    if s_["text"].strip():
                        tp.add_redact_annot(PdfDocument._shrunk(s_["bbox"], tp, 0.15), fill=False)
            apply_text_only_redactions(tp)
            pm = tp.get_pixmap(dpi=dpi, alpha=False)
        else:
            pm = page.get_pixmap(dpi=dpi, alpha=False)
        img = io.BytesIO(pm.tobytes("png"))

        par = d.add_paragraph()
        par.paragraph_format.space_after = Pt(0)
        run = par.add_run()
        run.font.size = Pt(1)
        run.add_picture(img, width=Emu(int(W * 12700)), height=Emu(int(H * 12700)))
        inline = run._r.find(".//" + qn("wp:inline"))
        graphic = inline.find(qn("a:graphic"))
        cx, cy = int(W * 12700), int(H * 12700)
        anchor = parse_xml(
            '<wp:anchor %s distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            'relativeHeight="0" behindDoc="1" locked="1" layoutInCell="1" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/>'
            '<wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV>'
            '<wp:extent cx="%d" cy="%d"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
            '<wp:wrapNone/><wp:docPr id="%d" name="NenTrang%d"/>'
            '<wp:cNvGraphicFramePr/></wp:anchor>' % (nsdecls("wp", "a", "pic", "r"), cx, cy, pic_id, i + 1))
        pic_id += 1
        anchor.append(graphic)
        inline.getparent().replace(inline, anchor)

        # ---- chữ đặt đúng toạ độ
        if with_text:
            for ln in hlines:
                    spans = [s for s in ln["spans"] if s["text"] != ""]
                    # bỏ khoảng trắng đầu dòng để vị trí x đúng chữ đầu tiên
                    while spans and not spans[0]["text"].strip():
                        spans.pop(0)
                    first = spans[0]
                    x = (fitz.Rect(first["bbox"]) * rot).x0
                    smax = max(spans, key=lambda s: s["size"])
                    asc = smax.get("ascender", 0.89) or 0.89
                    base_y = (fitz.Point(first["origin"]) * rot).y
                    top = base_y - asc * smax["size"]
                    width = (fitz.Rect(ln["bbox"]) * rot).x1 - x
                    fw = max(width * 1.12 + 6, 12)
                    fw = min(fw, max(W - x, width + 2))
                    runs = []
                    for k, s in enumerate(spans):
                        t = norm_text(s["text"])
                        if k == 0:
                            t = t.lstrip()
                        if k == len(spans) - 1:
                            t = t.rstrip()
                        if not t:
                            continue
                        c = s.get("color", 0)
                        fl = s.get("flags", 0)
                        fname = s.get("font", "")
                        fam = _xml_escape(clean_font_name(fname))
                        sz = int(round(s["size"] * 2))
                        rp = '<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s" w:eastAsia="%s"/>' % (fam, fam, fam, fam)
                        if fl & 16 or "bold" in fname.lower():
                            rp += "<w:b/>"
                        if fl & 2 or "italic" in fname.lower():
                            rp += "<w:i/>"
                        rp += '<w:color w:val="%06X"/><w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (c & 0xFFFFFF, sz, sz)
                        runs.append('<w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
                                    % (rp, _xml_escape(_clean_xml_text(t))))
                    if not runs:
                        continue
                    p = parse_xml(
                        '<w:p %s><w:pPr>'
                        '<w:framePr w:w="%d" w:hRule="auto" w:wrap="around" w:vAnchor="page" w:hAnchor="page" w:x="%d" w:y="%d"/>'
                        '<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
                        '<w:ind w:left="0" w:right="0" w:firstLine="0"/><w:jc w:val="left"/>'
                        '</w:pPr>%s</w:p>' % (nsdecls("w"), int(fw * 20), int(round(x * 20)),
                                              int(round(top * 20)), "".join(runs)))
                    sect_p = body.find(qn("w:sectPr"))
                    sect_p.addprevious(p)
        if progress:
            progress(i + 1, n)
    d.save(out)
    return out
