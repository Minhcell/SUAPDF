# -*- coding: utf-8 -*-
"""ĐỔI CHỮ TIẾNG VIỆT MÃ CŨ (TCVN3 / ABC – font .VnTime, .VnArial...; VNI – font VNI-Times...)
SANG UNICODE.

Nhiều văn bản hành chính vẫn soạn bằng font .VnTime (bảng mã TCVN3) hoặc VNI-Times. Khi xuất ra PDF,
chữ đọc ra là mã cũ: "Céng hoµ x· héi chñ nghÜa ViÖt Nam" thay vì "Cộng hoà xã hội chủ nghĩa Việt Nam".
Module này đổi về Unicode để: sửa / thêm chữ hiện đúng tiếng Việt, chuyển Word / Excel đúng chữ,
tách văn bản đọc đúng tiêu đề.
"""
import re
import unicodedata

# ---------------------------------------------------------------------------- TCVN3 (ABC)
_TCVN3 = {
    0xB5: "à", 0xB6: "ả", 0xB7: "ã", 0xB8: "á", 0xB9: "ạ",
    0xA8: "ă", 0xBB: "ằ", 0xBC: "ẳ", 0xBD: "ẵ", 0xBE: "ắ", 0xC6: "ặ",
    0xA9: "â", 0xC7: "ầ", 0xC8: "ẩ", 0xC9: "ẫ", 0xCA: "ấ", 0xCB: "ậ",
    0xAE: "đ",
    0xCC: "è", 0xCE: "ẻ", 0xCF: "ẽ", 0xD0: "é", 0xD1: "ẹ",
    0xAA: "ê", 0xD2: "ề", 0xD3: "ể", 0xD4: "ễ", 0xD5: "ế", 0xD6: "ệ",
    0xD7: "ì", 0xD8: "ỉ", 0xDC: "ĩ", 0xDD: "í", 0xDE: "ị",
    0xDF: "ò", 0xE1: "ỏ", 0xE2: "õ", 0xE3: "ó", 0xE4: "ọ",
    0xAB: "ô", 0xE5: "ồ", 0xE6: "ổ", 0xE7: "ỗ", 0xE8: "ố", 0xE9: "ộ",
    0xAC: "ơ", 0xEA: "ờ", 0xEB: "ở", 0xEC: "ỡ", 0xED: "ớ", 0xEE: "ợ",
    0xEF: "ù", 0xF1: "ủ", 0xF2: "ũ", 0xF3: "ú", 0xF4: "ụ",
    0xAD: "ư", 0xF5: "ừ", 0xF6: "ử", 0xF7: "ữ", 0xF8: "ứ", 0xF9: "ự",
    0xFA: "ỳ", 0xFB: "ỷ", 0xFC: "ỹ", 0xFD: "ý", 0xFE: "ỵ",
    0xA1: "Ă", 0xA2: "Â", 0xA3: "Ê", 0xA4: "Ô", 0xA5: "Ơ", 0xA6: "Ư", 0xA7: "Đ",
}
_TCVN3_TR = {k: v for k, v in _TCVN3.items()}
# ký tự gần như chỉ xuất hiện khi là mã TCVN3 (không có trong chữ Việt Unicode)
_TCVN3_ONLY = set(chr(c) for c in _TCVN3) - set("àảãáạăâèéêìíòóôõùúýđ")


def tcvn3(s, upper=False):
    t = s.translate(_TCVN3_TR)
    return t.upper() if upper else t


# ---------------------------------------------------------------------------- VNI Windows
def _vni_table():
    two = {}
    groups = [
        ("a", "ù", "á"), ("a", "ø", "à"), ("a", "û", "ả"), ("a", "õ", "ã"), ("a", "ï", "ạ"),
        ("a", "ê", "ă"), ("a", "é", "ắ"), ("a", "è", "ằ"), ("a", "ú", "ẳ"), ("a", "ü", "ẵ"), ("a", "ë", "ặ"),
        ("a", "â", "â"), ("a", "á", "ấ"), ("a", "à", "ầ"), ("a", "å", "ẩ"), ("a", "ã", "ẫ"), ("a", "ä", "ậ"),
        ("e", "ù", "é"), ("e", "ø", "è"), ("e", "û", "ẻ"), ("e", "õ", "ẽ"), ("e", "ï", "ẹ"),
        ("e", "â", "ê"), ("e", "á", "ế"), ("e", "à", "ề"), ("e", "å", "ể"), ("e", "ã", "ễ"), ("e", "ä", "ệ"),
        ("o", "ù", "ó"), ("o", "ø", "ò"), ("o", "û", "ỏ"), ("o", "õ", "õ"), ("o", "ï", "ọ"),
        ("o", "â", "ô"), ("o", "á", "ố"), ("o", "à", "ồ"), ("o", "å", "ổ"), ("o", "ã", "ỗ"), ("o", "ä", "ộ"),
        ("ô", "ù", "ớ"), ("ô", "ø", "ờ"), ("ô", "û", "ở"), ("ô", "õ", "ỡ"), ("ô", "ï", "ợ"),
        ("u", "ù", "ú"), ("u", "ø", "ù"), ("u", "û", "ủ"), ("u", "õ", "ũ"), ("u", "ï", "ụ"),
        ("ö", "ù", "ứ"), ("ö", "ø", "ừ"), ("ö", "û", "ử"), ("ö", "õ", "ữ"), ("ö", "ï", "ự"),
        ("y", "ù", "ý"), ("y", "ø", "ỳ"), ("y", "û", "ỷ"), ("y", "õ", "ỹ"),
    ]
    for b, m, r in groups:
        two[b + m] = r
        two[b.upper() + m.upper()] = r.upper()
    one = {"ô": "ơ", "Ô": "Ơ", "ö": "ư", "Ö": "Ư", "ñ": "đ", "Ñ": "Đ", "î": "ỵ", "Î": "Ỵ",
           "æ": "ỉ", "Æ": "Ỉ", "ó": "ĩ", "Ó": "Ĩ", "ò": "ị", "Ò": "Ị"}
    return two, one


_VNI2, _VNI1 = _vni_table()


def vni_groups(chars):
    """chars: list ký tự -> list (chỉ số bắt đầu, số ký tự gộp, chữ Unicode)."""
    out, i, n = [], 0, len(chars)
    while i < n:
        if i + 1 < n and (chars[i] + chars[i + 1]) in _VNI2:
            out.append((i, 2, _VNI2[chars[i] + chars[i + 1]]))
            i += 2
        else:
            out.append((i, 1, _VNI1.get(chars[i], chars[i])))
            i += 1
    return out


def vni(s):
    return "".join(t for _i, _n, t in vni_groups(list(s)))


# ---------------------------------------------------------------------------- nhận biết
def font_kind(fontname):
    """'tcvn3' | 'tcvn3h' (font chữ hoa .VnTimeH) | 'vni' | None."""
    n = (fontname or "").split("+")[-1].strip()
    n = n.replace("#2E", ".").replace("#2e", ".")
    low = n.lower().lstrip("._- ")
    if low.startswith("vni"):
        return "vni"
    if re.match(r"vn[a-z]", low):
        base = re.split(r"[-,]", n.lstrip("._- "))[0]
        return "tcvn3h" if base.endswith("H") else "tcvn3"
    return None


def looks_tcvn3(text, min_hits=2):
    """Chữ thuộc font không rõ tên nhưng có dạng mã TCVN3 (vd 'Céng hoµ x· héi').
    Chỉ tính ký tự mã TCVN3 đứng ngay sau 1 chữ cái (giữa từ) – tránh nhầm ký hiệu toán × ÷ µ ±..."""
    if not text or any(ord(c) > 0xFF for c in text):
        return False
    hits = sum(1 for i, c in enumerate(text) if c in _TCVN3_ONLY and i > 0 and text[i - 1].isalpha())
    return hits >= min_hits


def fix_text(text, fontname=""):
    kind = font_kind(fontname)
    if kind == "vni":
        return vni(text)
    if kind in ("tcvn3", "tcvn3h"):
        return tcvn3(text, kind == "tcvn3h")
    return text


def is_legacy_family(name):
    return font_kind(name) is not None


def unicode_family(name):
    """Font mã cũ -> font Unicode tương ứng để gõ chữ mới."""
    low = (name or "").lower()
    if any(k in low for k in ("arial", "helve", "univers", "tahoma", "verdana")):
        return "Arial"
    if "courier" in low:
        return "Courier New"
    return "Times New Roman"


# ---------------------------------------------------------------------------- áp cho kết quả get_text
def _fix_span(sp, kind):
    sp["legacy"] = kind
    chars = sp.get("chars")
    if chars is not None:
        if kind == "vni":
            cs = [c["c"] for c in chars]
            new = []
            for i, n, t in vni_groups(cs):
                c = dict(chars[i])
                if n > 1:
                    b0, b1 = chars[i]["bbox"], chars[i + n - 1]["bbox"]
                    c["bbox"] = (min(b0[0], b1[0]), min(b0[1], b1[1]), max(b0[2], b1[2]), max(b0[3], b1[3]))
                c["c"] = t
                new.append(c)
            sp["chars"] = new
        else:
            for c in chars:
                c["c"] = tcvn3(c["c"], kind == "tcvn3h")
        if "text" in sp:
            sp["text"] = "".join(c["c"] for c in sp["chars"])
    elif "text" in sp:
        sp["text"] = vni(sp["text"]) if kind == "vni" else tcvn3(sp["text"], kind == "tcvn3h")


def _span_text(sp):
    if "text" in sp:
        return sp["text"]
    return "".join(c["c"] for c in sp.get("chars", []))


def fix_dict(dd):
    """Sửa tại chỗ kết quả page.get_text('dict' / 'rawdict'). Trả về số span đã đổi."""
    n = 0
    for b in dd.get("blocks", []):
        for ln in b.get("lines", []):
            unknown = []
            for sp in ln.get("spans", []):
                kind = font_kind(sp.get("font", ""))
                if kind:
                    _fix_span(sp, kind)
                    orig = sp.get("font", "")
                    lo = orig.lower()
                    suf = ("Bold" if "bold" in lo else "") + \
                          ("Italic" if "italic" in lo else "")
                    sp["font"] = unicode_family(orig) + ("-" + suf if suf else "")
                    sp["font_legacy"] = orig
                    n += 1
                else:
                    unknown.append(sp)
            if unknown and looks_tcvn3("".join(_span_text(s) for s in unknown)):
                for sp in unknown:
                    _fix_span(sp, "tcvn3")
                    n += 1
    return n


def fix_words(words):
    """Danh sách từ (page.get_text('words')) không có tên font: đổi khi có dạng TCVN3."""
    out = []
    line_txt = {}
    for w in words:
        line_txt.setdefault((w[5], w[6]), []).append(w[4])
    bad = {k for k, v in line_txt.items() if looks_tcvn3(" ".join(v))}
    for w in words:
        if (w[5], w[6]) in bad:
            w = tuple(w[:4]) + (tcvn3(w[4]),) + tuple(w[5:])
        out.append(w)
    return out


def nfc(s):
    return unicodedata.normalize("NFC", s)


# ---------------------------------------------------------------------------- lớp chữ hỏng
def bad_text(t):
    """Chữ đọc ra từ PDF bị hỏng (font thiếu bảng mã ToUnicode): ký tự điều khiển / ô vuông,
    hoặc toàn ký hiệu không thành chữ (vd ' !"# $%&&')."""
    if not t:
        return False
    s = [c for c in t if not c.isspace()]
    if not s:
        return any(ord(c) < 32 and c not in "\t\n\r" for c in t)
    bad = sum(1 for c in s if ord(c) < 32 or c == "�")
    if bad / len(s) > 0.2:
        return True
    # dấu chấm / gạch điền chỗ trống ("......", "-----"), ký hiệu toán (vùng PUA) -> trung tính
    core = [c for c in s if c not in _FILL and not (0xE000 <= ord(c) <= 0xF8FF)]
    alnum = sum(1 for c in core if c.isalnum())
    if len(core) >= 4 and alnum / len(core) < 0.4:
        return True
    # chữ hoa / thường lẫn lộn vô lý giữa từ (vd 'ceNG HoA ngI cHU vIET') -> bảng mã font sai
    words = re.findall(r"[^\W\d_]{2,}", t)
    weird = [w for w in words if len(w) >= 3 and any(a.islower() and b.isupper() for a, b in zip(w, w[1:]))]
    return len(weird) >= 3 and len(weird) >= 0.5 * len(words)


_FILL = set(".-_…·•=,:;()[]/\\|*+~–—'\"?!«»“”‘’<>%")


def page_text_broken(texts):
    """texts: các dòng chữ của 1 trang -> True nếu phần lớn là chữ hỏng."""
    cand = [t for t in texts if len(t.strip()) >= 4 or any(ord(c) < 32 and c not in "\t\n\r" for c in t)]
    if len(cand) < 2:
        return False
    nb = sum(1 for t in cand if bad_text(t))
    return nb >= 2 and nb >= 0.5 * len(cand)
