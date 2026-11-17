#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VitePDF engine: image and PDF conversion, compression and merging.

VitePDF: right-click image and PDF tools for Windows.

  Images (JPG, JPEG, JFIF, PNG, HEIC, HEIF, WEBP, BMP)
      Convert each to PDF / Merge into one PDF
      presets: Original, Optimized, Under 1 MB
  PDFs
      Compress PDF / Merge PDFs
      presets: Optimized, Under 1 MB, Under 350 KB

Everything runs offline on this computer. Original files are never changed.

Created by Atanu Sarkar. Made with Claude.
"""

import io
import math
import os
import re
import struct
import sys
import threading
import time
import traceback
from pathlib import Path

APP_NAME = "VitePDF"
VERSION = "1.3.2"
# The author's signing key. A signed copy must carry this key or setup stops.
AUTHOR_KEY = "A88B A544 E686 3A3C 1877 0B0C 3C40 DEBC"
AUTHOR = "Atanu Sarkar"
CREDIT = "Created by Atanu Sarkar. Made with Claude."

KB = 1024

IMAGE_EXTS = (".jpg", ".jpeg", ".jfif", ".png", ".heic", ".heif", ".webp", ".bmp")
PDF_EXTS = (".pdf",)

# "limit" is the largest file we accept for a size preset. It sits a little
# under the advertised size so the result passes websites that count 1 MB as
# 1,000,000 bytes and 350 KB as 350,000 bytes.
PRESETS = {
    "original": {"label": "Original", "suffix": "", "limit": None},
    "optimized": {"label": "Optimized", "suffix": "_optimized", "limit": None},
    "under1mb": {"label": "Under 1 MB", "suffix": "_under1MB", "limit": 950 * KB},
    "under350kb": {"label": "Under 350 KB", "suffix": "_under350KB", "limit": 335 * KB},
    "under200kb": {"label": "Under 200 KB", "suffix": "_under200KB", "limit": 192 * KB},
}

# Set for one job: every picture is turned to grayscale ("black and white").
FORCE_GRAY = False


def set_custom_preset(amount, unit="KB", gray=False, key="custom"):
    """Register a size the user typed, e.g. 500 KB. Returns the preset key.

    The real limit sits 1% under amount x 1000 bytes, so the result also
    passes an upload form that counts 1 KB as 1000 bytes."""
    global FORCE_GRAY
    amount = float(amount)
    mult = 1000 * 1000 if unit.upper() == "MB" else 1000
    text = ("%g" % amount) + " " + unit.upper()
    PRESETS[key] = {"label": "Under " + text, "limit": int(amount * mult * 0.99),
                    "suffix": "_under" + text.replace(" ", "").replace(".", "_")}
    FORCE_GRAY = bool(gray)
    return key

A4_PT = (595.276, 841.890)
DEFAULT_DPI = 96.0

# A lossless result this small is kept as it is: there is nothing to gain.
SMALL_ENOUGH = 500 * KB

# Quality ladder, best first: (longest side in pixels, JPEG quality, grayscale).
# Size presets walk down this list until the file fits. For documents, text
# stays readable longer when resolution is kept and quality is lowered, so
# the ladder gives up quality before it gives up pixels.
LADDER = [
    (None, 95, False), (None, 92, False), (None, 89, False),
    (4200, 87, False), (3600, 86, False), (3300, 85, False),
    (3000, 85, False),                      # the "Optimized" setting
    (3000, 80, False), (2800, 77, False), (2600, 74, False), (2500, 70, False),
    (2400, 66, False), (2300, 62, False), (2200, 58, False), (2100, 54, False),
    (2000, 50, False), (2000, 45, False), (1900, 41, False), (1800, 37, False),
    (1800, 33, False), (1700, 30, False), (1600, 27, False), (1600, 23, False),
    (1600, 20, False), (1500, 18, False), (1400, 16, False),
    (1300, 15, True),                       # from here on: low quality, warn
    (1200, 15, True), (1100, 15, True), (1000, 15, True), (900, 15, True),
]
OPT_LEVEL = LADDER.index((3000, 85, False))
LOW_LEVEL = LADDER.index((1300, 15, True))

# Largest picture we are willing to decode (guards against "decompression bombs").
MAX_PIXELS = 400_000_000

# The only decoders that are ever used, whatever a file claims to be.
ALLOWED_FORMATS = ("JPEG", "MPO", "PNG", "WEBP", "BMP")

# Decoded pixels kept in memory between passes (bytes).
PIXEL_CACHE_BUDGET = 350 * 1024 * 1024


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


_PRIVATE = set()


def private(*texts):
    """Register folder and file names that must never be written to the log."""
    for t in texts:
        t = str(t)
        if len(t) >= 3:
            _PRIVATE.add(t)


def _scrub(msg):
    msg = str(msg)
    for t in sorted(_PRIVATE, key=len, reverse=True):
        msg = msg.replace(t, "<file>").replace(t.replace("\\", "/"), "<file>")
        msg = msg.replace(t.replace("\\", "\\\\"), "<file>")
    try:
        msg = msg.replace(str(Path.home()), "~")
    except Exception:
        pass
    return msg


def log(msg):
    msg = _scrub(msg)
    try:
        p = data_dir() / "vitepdf.log"
        if p.exists() and p.stat().st_size > 1024 * 1024:
            p.replace(p.with_suffix(".old.log"))
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s [%d] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(), msg))
    except Exception:
        pass


def fmt_size(n):
    if n < 1000 * KB:
        return "%d KB" % max(1, round(n / KB))
    return "%.2f MB" % (n / (KB * KB))


def _lower_first(text):
    return text[:1].lower() + text[1:]


def natural_key(p):
    # By name without the ending first, the way Explorer lists files:
    # "form.pdf" comes before "form2.pdf".
    p = Path(p)
    parts = [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", p.stem.lower())]
    return (parts, p.suffix.lower())


def unique_path(folder, stem, ext=".pdf"):
    """A file name in folder that is free right now. write_file() makes the
    final choice, so two jobs running together can never share a name."""
    n = 1
    while True:
        p = Path(folder) / (stem + ext if n == 1 else "%s (%d)%s" % (stem, n, ext))
        if not p.exists():
            return p
        n += 1


PROTECT = None      # password to put on every PDF saved while this is set


def protect_bytes(data, password):
    """The same PDF, opening only with the password (AES-256)."""
    pikepdf = _pikepdf()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        buf = io.BytesIO()
        pdf.save(buf, encryption=pikepdf.Encryption(user=password, owner=password, R=6),
                 compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    return buf.getvalue()


def write_file(path, data):
    """Save data under a new name and return the path really used.

    The file is written completely under a temporary name of this job first
    and only then given its final name, without ever replacing a file. So a
    result never shows up half-written or empty, and when another job took the
    name in the meantime the next free name is used.
    A PDF made from a locked source is encrypted before it touches the disk."""
    path = Path(path)
    if PROTECT and path.suffix.lower() == ".pdf":
        data = protect_bytes(data, PROTECT)
    tmp = path.with_name(".%s.%d-%s.vitepdf-tmp" % (path.name[:40], os.getpid(), os.urandom(4).hex()))
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        stem, ext = path.stem, path.suffix
        m = re.match(r"^(.*) \((\d+)\)$", stem)
        base, n = (m.group(1), int(m.group(2))) if m else (stem, 1)
        while True:
            final = path.with_name(base + ext if n == 1 else "%s (%d)%s" % (base, n, ext))
            try:
                if os.name == "nt":
                    os.rename(tmp, final)           # fails if the name exists
                else:
                    os.link(tmp, final)             # fails if the name exists
                    os.unlink(tmp)
                return final
            except FileExistsError:
                n += 1
                if n > 9999:
                    raise
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


class Report:
    """Collects what the user needs to hear about at the end of a job."""

    def __init__(self):
        self.lines = []
        self.warn = False
        self.failed = 0
        self.outputs = []

    def info(self, msg):
        self.lines.append(msg)

    def warning(self, msg):
        self.lines.append(msg)
        self.warn = True

    def fail(self, msg):
        """A file that could not be processed. Counts toward the exit code."""
        self.warning(msg)
        self.failed += 1


class Skip(Exception):
    """An image inside a PDF that we leave untouched."""


class TooBig(Exception):
    """An input over the size, pixel or page budget."""


MAX_FILE_BYTES = 600 * 1000 * 1000      # one input file
MAX_PAGES = 3000                        # one PDF


def check_size(path):
    try:
        size = Path(path).stat().st_size
    except OSError:
        return
    if size > MAX_FILE_BYTES:
        raise TooBig("the file is larger than %s" % fmt_size(MAX_FILE_BYTES))


# --------------------------------------------------------------------------
# Opening PDFs: passwords, signatures, forms
# --------------------------------------------------------------------------

PASSWORDS = {}      # locked PDFs the user unlocked in this run: path key -> password


def path_key(path):
    return os.path.normcase(os.path.abspath(str(path)))


def password_for(path):
    return PASSWORDS.get(path_key(path))


def open_pdf(source, password=None):
    """Open a PDF from a path or from bytes, fully in memory (no handle stays
    on the file). A password given for this path earlier is used by itself."""
    pikepdf = _pikepdf()
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        check_size(source)
        data = Path(source).read_bytes()
        password = password or password_for(source)
    pdf = pikepdf.open(io.BytesIO(data), **({"password": password} if password else {}))
    if len(pdf.pages) > MAX_PAGES:
        raise TooBig("the PDF has more than %d pages" % MAX_PAGES)
    return pdf


def pdf_facts(path, password=None):
    """-> {"locked", "signed", "form"} for one PDF. Never raises."""
    facts = {"locked": False, "signed": False, "form": False, "broken": False}
    pikepdf = _pikepdf()
    try:
        pdf = open_pdf(path, password)
    except pikepdf.PasswordError:
        facts["locked"] = True
        return facts
    except Exception:
        facts["broken"] = True
        return facts
    try:
        acro = pdf.Root.get("/AcroForm")
        if acro is not None:
            fields = list(pdf.acroform.fields)
            facts["form"] = bool(fields)
            for f in fields:
                obj = getattr(f, "obj", f)
                try:
                    if str(obj.get("/FT")) == "/Sig" and obj.get("/V") is not None:
                        facts["signed"] = True
                except Exception:
                    pass
            try:
                if int(acro.get("/SigFlags", 0)) & 1 and not facts["signed"]:
                    facts["signed"] = any("/ByteRange" in str(o.keys()) for o in pdf.objects
                                          if isinstance(o, pikepdf.Dictionary))
            except Exception:
                pass
        if pdf.Root.get("/Perms") is not None:
            facts["signed"] = True
    except Exception:
        pass
    return facts


# --------------------------------------------------------------------------
# Lazy imports (keeps start-up fast for the multi-select helpers)
# --------------------------------------------------------------------------

_HEIF_READY = False


def _pil():
    global _HEIF_READY
    from PIL import Image
    if not _HEIF_READY:
        _HEIF_READY = True
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        # Pillow only warns between the limit and twice the limit. Make the
        # limit hard: anything above it is refused.
        import warnings
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        # Security: switch off every Pillow decoder we do not need (EPS, PSD,
        # TIFF, ...). A renamed or booby-trapped file can then only reach the
        # few well-tested decoders listed above, plus HEIF.
        Image.init()
        Image.ID[:] = [name for name in Image.ID if name in ALLOWED_FORMATS]
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception as e:  # HEIC stays unsupported, everything else works
            log("pillow-heif not available: %r" % (e,))
    return Image


def _pikepdf():
    import pikepdf
    return pikepdf


# --------------------------------------------------------------------------
# Image payloads: plain descriptions of an image stream for a PDF
# --------------------------------------------------------------------------

class Payload:
    __slots__ = ("data", "kind", "w", "h", "bpc", "cs", "palette", "icc",
                 "invert", "orientation", "lossless")

    def __init__(self, data, kind, w, h, cs, bpc=8, palette=None, icc=None,
                 invert=False, orientation=1, lossless=False):
        self.data = data            # encoded stream bytes
        self.kind = kind            # "dct" or "flate"
        self.w, self.h = w, h
        self.cs = cs                # "gray", "rgb", "cmyk", "indexed"
        self.bpc = bpc
        self.palette = palette
        self.icc = icc
        self.invert = invert        # Adobe CMYK JPEGs store inverted values
        self.orientation = orientation
        self.lossless = lossless

    @property
    def size(self):
        return len(self.data) + (len(self.icc) if self.icc else 0)


_ICC_SPACE = {"gray": b"GRAY", "rgb": b"RGB ", "cmyk": b"CMYK"}
_NCOMP = {"gray": 1, "rgb": 3, "cmyk": 4, "indexed": 1}


def _icc_for(icc, cs):
    """Keep an ICC profile only when it matches the colour model."""
    base = "rgb" if cs == "indexed" else cs
    if icc and len(icc) > 132 and icc[16:20] == _ICC_SPACE.get(base):
        return bytes(icc)
    return None


def _png_payload(data, icc=None, orientation=1):
    """Reuse the compressed pixel data of a PNG as a PDF image stream."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos = 8
    ihdr = None
    palette = None
    idat = []
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif ctype == b"PLTE":
            palette = bytes(body)
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
    if not ihdr or not idat:
        raise ValueError("incomplete PNG")
    w, h, depth, ctype, _comp, _filt, interlace = ihdr
    if interlace or depth > 8 or ctype not in (0, 2, 3):
        raise ValueError("PNG variant needs re-encoding")
    cs = {0: "gray", 2: "rgb", 3: "indexed"}[ctype]
    if cs == "indexed" and not palette:
        raise ValueError("palette missing")
    return Payload(b"".join(idat), "flate", w, h, cs, bpc=depth, palette=palette,
                   icc=_icc_for(icc, cs), orientation=orientation, lossless=True)


def _flatten(im, keep_cmyk=False):
    """Return an 8-bit grey or RGB image; transparency goes onto white."""
    Image = _pil()
    if keep_cmyk and im.mode == "CMYK":
        return im
    if im.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in im.info:
        grey = im.mode in ("LA", "La")
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg.convert("L") if grey else bg
    if im.mode in ("RGB", "L"):
        return im
    if im.mode == "1":
        return im.convert("L")
    if im.mode.startswith("I;16") or im.mode == "I":
        return im.convert("I").point(lambda v: v * (1.0 / 256.0)).convert("L")
    return im.convert("RGB")


def _encode_source(im, cap):
    """im scaled so its longest side is cap pixels."""
    Image = _pil()
    w, h = im.size
    s = cap / float(max(w, h))
    return im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS, reducing_gap=3.0)


def _encode_jpeg(base, cap, quality, gray, fast=False, icc=None):
    Image = _pil()
    gray = gray or FORCE_GRAY
    im = base
    w, h = im.size
    if cap and max(w, h) > cap:
        s = cap / float(max(w, h))
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))),
                       Image.LANCZOS, reducing_gap=3.0)
    if gray and im.mode != "L":
        im = im.convert("L")
    buf = io.BytesIO()
    extra = {"icc_profile": icc} if (icc and not gray and im.mode == "RGB") else {}
    im.save(buf, "JPEG", quality=quality, optimize=not fast, **extra)
    return buf.getvalue(), im.size, im.mode


def _sane_dpi(dpi):
    try:
        dx, dy = float(dpi[0]), float(dpi[1])
        if 40 <= dx <= 2400 and 40 <= dy <= 2400:
            return dx, dy
    except Exception:
        pass
    return DEFAULT_DPI, DEFAULT_DPI


_pixel_cache_used = 0


def _release(objs):
    """Free decoded pixels once a file is finished."""
    global _pixel_cache_used
    for o in objs:
        im = o._base
        if im is not None:
            _pixel_cache_used -= im.size[0] * im.size[1] * len(im.getbands())
            o._base = None
        o._enc = {}
        if hasattr(o, "_mid"):
            o._mid = None


class SourceImage:
    """One image file on disk."""

    def __init__(self, path):
        self.path = Path(path)
        self._base = None
        self._mid = None
        self._lossless = None
        self._enc = {}
        Image = _pil()
        check_size(self.path)
        with Image.open(self.path) as im:
            self.format = im.format or ""
            self.mode = im.mode
            self.size = im.size
            if self.size[0] * self.size[1] > MAX_PIXELS:
                raise TooBig("the picture has more than %d megapixels" % (MAX_PIXELS // 10 ** 6))
            self.dpi = _sane_dpi(im.info.get("dpi"))
            self.icc = im.info.get("icc_profile")
            self.adobe = "adobe" in im.info
            self.interlace = bool(im.info.get("interlace"))
            self.has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
            try:
                self.orientation = int(im.getexif().get(0x0112, 1) or 1)
            except Exception:
                self.orientation = 1
            if not 1 <= self.orientation <= 8:
                self.orientation = 1
            self.jpeg_len = None
            if self.format == "MPO":
                try:
                    first = im.mpinfo[0xB002][0]
                    if first.get("DataOffset", 0) == 0 and first.get("Size", 0) > 0:
                        self.jpeg_len = int(first["Size"])
                except Exception:
                    pass
        self.file_len = self.path.stat().st_size
        if self.format in ("JPEG", "MPO") and self.mode in ("L", "RGB", "CMYK"):
            self.kind = "jpeg"
        elif (self.format == "PNG" and not self.interlace and not self.has_alpha
              and self.mode in ("1", "L", "P", "RGB")):
            self.kind = "png"
        else:
            self.kind = "pixels"
        # HEIC and WEBP are lossy formats: storing their pixels losslessly is
        # always far bigger than the source, so it is only done for "Original".
        self.lossless_is_cheap = self.kind != "pixels" or self.format in ("PNG", "BMP", "GIF", "TIFF")

    # -- geometry ----------------------------------------------------------

    def display_size(self):
        w, h = self.size
        return (h, w) if self.orientation >= 5 else (w, h)

    def page_size(self):
        """Page that matches the image exactly, never larger than A4."""
        w, h = self.display_size()
        dx, dy = self.dpi
        pw, ph = w * 72.0 / dx, h * 72.0 / dy
        box = A4_PT if ph >= pw else (A4_PT[1], A4_PT[0])
        s = min(1.0, box[0] / pw, box[1] / ph)
        return pw * s, ph * s

    # -- pixels ------------------------------------------------------------

    def base(self):
        """Decoded pixels, upright, without transparency."""
        global _pixel_cache_used
        if self._base is not None:
            return self._base
        Image = _pil()
        from PIL import ImageOps
        # Read through memory so no handle stays open on the user's file.
        im = Image.open(io.BytesIO(self.path.read_bytes()))
        im.load()
        im = ImageOps.exif_transpose(im)
        im = _flatten(im, keep_cmyk=(self.kind == "jpeg"))
        cost = im.size[0] * im.size[1] * len(im.getbands())
        if _pixel_cache_used + cost <= PIXEL_CACHE_BUDGET:
            _pixel_cache_used += cost
            self._base = im
        return im

    # -- candidates --------------------------------------------------------

    def lossless(self):
        """The image exactly as it is: no pixel is changed."""
        if self._lossless is not None:
            return self._lossless
        p = None
        if self.kind == "jpeg":
            with open(self.path, "rb") as f:
                data = f.read()
            if self.jpeg_len and self.jpeg_len <= len(data):
                data = data[:self.jpeg_len]
            cs = {"L": "gray", "RGB": "rgb", "CMYK": "cmyk"}[self.mode]
            p = Payload(data, "dct", self.size[0], self.size[1], cs,
                        icc=_icc_for(self.icc, cs),
                        invert=(cs == "cmyk" and self.adobe),
                        orientation=self.orientation, lossless=True)
        elif self.kind == "png":
            try:
                with open(self.path, "rb") as f:
                    p = _png_payload(f.read(), icc=self.icc, orientation=self.orientation)
            except ValueError:
                p = None
        if p is None:
            im = self.base()
            buf = io.BytesIO()
            im.save(buf, "PNG", compress_level=5)
            cs = "gray" if im.mode == "L" else "rgb"
            p = _png_payload(buf.getvalue(), icc=_icc_for(self.icc, cs))
        self._lossless = p
        return p

    def lossless_len(self):
        if not self.lossless_is_cheap:
            return None
        if FORCE_GRAY and self.mode not in ("L", "1"):
            return None                     # a colour original cannot be kept as it is
        if self.kind == "jpeg" and self._lossless is None:
            return self.jpeg_len or self.file_len
        return self.lossless().size

    def encoded(self, cap, quality, gray, fast=False):
        key = (cap, quality, gray)
        if key not in self._enc:
            src = self.base()
            if cap and cap <= 3000 and max(src.size) > 3000:
                # shrink once to 3000 pixels and reuse that for every smaller try
                if self._mid is None:
                    self._mid = _encode_source(src, 3000)
                src = self._mid
            data, (w, h), mode = _encode_jpeg(src, cap, quality, gray, fast=fast)
            cs = {"L": "gray", "CMYK": "cmyk"}.get(mode, "rgb")
            invert = False
            if cs == "cmyk":                # same test as for an untouched CMYK JPEG
                with _pil().open(io.BytesIO(data)) as chk:
                    invert = "adobe" in chk.info
            self._enc = {key: Payload(data, "dct", w, h, cs, icc=_icc_for(self.icc, cs),
                                      invert=invert)}
        return self._enc[key]

    def optimized(self):
        """Visually identical, much smaller when there is something to gain."""
        cap, q, gray = LADDER[OPT_LEVEL]
        length = self.lossless_len()
        if length is not None and length <= SMALL_ENOUGH:
            return self.lossless()
        enc = self.encoded(cap, q, gray)
        if length is not None and length <= 1.2 * enc.size:
            return self.lossless()
        return enc

    def at_level(self, k):
        cap, q, gray = LADDER[k]
        enc = self.encoded(cap, q, gray, fast=True)
        length = self.lossless_len()
        if length is not None and length <= enc.size:
            return self.lossless()
        return enc


# --------------------------------------------------------------------------
# Writing image PDFs
# --------------------------------------------------------------------------

def _orientation_matrix(o, w, h):
    """PDF matrix that places the unit image square upright on a w x h page."""
    return {
        1: (w, 0, 0, h, 0, 0),
        2: (-w, 0, 0, h, w, 0),
        3: (-w, 0, 0, -h, w, h),
        4: (w, 0, 0, -h, 0, h),
        5: (0, -h, -w, 0, w, h),
        6: (0, -h, w, 0, 0, h),
        7: (0, h, w, 0, 0, 0),
        8: (0, h, -w, 0, w, 0),
    }[o]


def _make_xobject(pdf, p, icc_cache):
    pikepdf = _pikepdf()
    Name, Array, Dictionary = pikepdf.Name, pikepdf.Array, pikepdf.Dictionary
    st = pdf.make_stream(b"")
    ncomp = _NCOMP[p.cs]
    if p.kind == "dct":
        st.write(p.data, filter=Name.DCTDecode)
    else:
        st.write(p.data, filter=Name.FlateDecode,
                 decode_parms=Dictionary(Predictor=15, Colors=ncomp,
                                         BitsPerComponent=p.bpc, Columns=p.w))
    st.Type = Name.XObject
    st.Subtype = Name.Image
    st.Width = p.w
    st.Height = p.h
    st.BitsPerComponent = p.bpc
    base_cs = {"gray": Name.DeviceGray, "rgb": Name.DeviceRGB, "cmyk": Name.DeviceCMYK,
               "indexed": Name.DeviceRGB}[p.cs]
    if p.icc:
        key = hash(p.icc)
        if key not in icc_cache:
            prof = pdf.make_stream(p.icc)
            prof.N = 3 if p.cs == "indexed" else ncomp
            prof.Alternate = base_cs
            icc_cache[key] = pdf.make_indirect(Array([Name.ICCBased, prof]))
        base_cs = icc_cache[key]
    if p.cs == "indexed":
        hival = len(p.palette) // 3 - 1
        st.ColorSpace = Array([Name.Indexed, base_cs, hival, pikepdf.String(p.palette)])
    else:
        st.ColorSpace = base_cs
    if p.invert:
        st.Decode = Array([1, 0] * ncomp)
    return st


def build_image_pdf(pages):
    """pages: list of (payload, (page_w, page_h)) -> PDF bytes."""
    pikepdf = _pikepdf()
    pdf = pikepdf.new()
    icc_cache = {}
    for p, (pw, ph) in pages:
        xobj = _make_xobject(pdf, p, icc_cache)
        page = pdf.add_blank_page(page_size=(pw, ph))
        m = _orientation_matrix(p.orientation, pw, ph)
        content = "q %s cm /Im0 Do Q\n" % " ".join("%.4f" % v for v in m)
        page.Contents = pdf.make_stream(content.encode("ascii"))
        page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=xobj))
    pdf.docinfo["/Producer"] = "%s %s" % (APP_NAME, VERSION)
    return _save(pdf)


def _save(pdf):
    pikepdf = _pikepdf()
    buf = io.BytesIO()
    pdf.save(buf, compress_streams=True,
             object_stream_mode=pikepdf.ObjectStreamMode.generate)
    return buf.getvalue()


def _find_level(levels, evaluate, limit, first=None, good=0.90):
    """A level whose size fits the limit. evaluate(k) -> (size, payload).

    A guided binary search. One measured size tells roughly where the answer
    lies; two sizes on either side of the limit pin it down. The search stops
    as soon as a result uses at least 90% of the limit, because the next
    better level would not fit. Returns (position in levels, payload, fits)."""
    lo, hi = 0, len(levels) - 1
    best = fail = fit = None
    probe = first
    while lo <= hi:
        mid = (lo + hi) // 2 if probe is None else min(max(probe, lo), hi)
        size, payload = evaluate(levels[mid])
        if size <= limit:
            best, fit = (mid, payload), (mid, size)
            hi = mid - 1
            if size >= good * limit:
                break
        else:
            fail = (mid, size)
            lo = mid + 1
        probe = None
        if fail and fit and 0 < fit[1] < fail[1]:
            frac = math.log(limit / float(fail[1])) / math.log(fit[1] / float(fail[1]))
            probe = fail[0] + int(math.ceil(frac * (fit[0] - fail[0])))
        elif size > 0:
            est = mid + math.log(limit / float(size)) / math.log(0.86)
            probe = int(math.ceil(est)) if size > limit else int(math.floor(est))
    if best:
        return best[0], best[1], True
    last = len(levels) - 1
    return last, evaluate(levels[last])[1], False


def images_to_pdf(items, preset):
    """Returns (pdf bytes, fits, low_quality)."""
    limit = PRESETS[preset]["limit"]
    sizes = [it.page_size() for it in items]

    def build(payloads):
        return build_image_pdf(list(zip(payloads, sizes)))

    if preset == "original":
        return build([it.lossless() for it in items]), True, False
    if preset == "optimized":
        return build([it.optimized() for it in items]), True, False

    overhead = 1200 + 500 * len(items)
    lengths = [it.lossless_len() for it in items]
    if all(n is not None for n in lengths) and sum(lengths) + overhead <= limit:
        data = build([it.lossless() for it in items])
        if len(data) <= limit:
            return data, True, False

    if sum(it.file_len for it in items) <= limit:
        data = build([it.optimized() for it in items])
        if len(data) <= limit:
            return data, True, False

    def evaluate(k):
        payloads = [it.at_level(k) for it in items]
        return sum(p.size for p in payloads) + overhead, payloads

    levels = list(range(len(LADDER)))
    pos, payloads, fits = _find_level(levels, evaluate, limit, first=OPT_LEVEL)
    data = build(payloads)
    while len(data) > limit and pos < len(levels) - 1:   # estimate was a little low
        pos += 1
        payloads = evaluate(levels[pos])[1]
        data = build(payloads)
    fits = len(data) <= limit
    low = levels[pos] >= LOW_LEVEL and any(not p.lossless for p in payloads)
    return data, fits, low


# --------------------------------------------------------------------------
# PDF compression
# --------------------------------------------------------------------------

def _page_resources(page_obj):
    node = page_obj
    for _ in range(50):
        res = node.get("/Resources")
        if res is not None:
            return res
        node = node.get("/Parent")
        if node is None:
            break
    return None


def _walk_images(resources, seen, out):
    if resources is None:
        return
    xobjs = resources.get("/XObject")
    if xobjs is None:
        return
    for _name, obj in xobjs.items():
        try:
            og = obj.objgen
            if og in seen:
                continue
            seen.add(og)
            sub = str(obj.get("/Subtype"))
            if sub == "/Image":
                out.append(obj)
            elif sub == "/Form":
                _walk_images(obj.get("/Resources"), seen, out)
        except Exception:
            continue


def _filters(obj):
    pikepdf = _pikepdf()
    f = obj.get("/Filter")
    if f is None:
        return []
    if isinstance(f, pikepdf.Array):
        return [str(x) for x in f]
    return [str(f)]


_OK_FILTERS = {"/DCTDecode", "/FlateDecode", "/LZWDecode", "/RunLengthDecode",
               "/ASCII85Decode", "/ASCIIHexDecode"}


def _colour_info(obj):
    """(components, colour space to keep, is_indexed) for images we can recompress."""
    pikepdf = _pikepdf()
    cs = obj.get("/ColorSpace")

    def comps(c):
        if isinstance(c, pikepdf.Name):
            return {"/DeviceGray": 1, "/DeviceRGB": 3}.get(str(c))
        if isinstance(c, pikepdf.Array) and len(c) >= 2:
            kind = str(c[0])
            if kind == "/ICCBased":
                n = int(c[1].get("/N", 0))
                return n if n in (1, 3) else None
            if kind == "/CalRGB":
                return 3
            if kind == "/CalGray":
                return 1
        return None

    if cs is None:
        return None
    if isinstance(cs, pikepdf.Array) and len(cs) == 4 and str(cs[0]) == "/Indexed":
        return (3, cs[1], True) if comps(cs[1]) == 3 else None
    n = comps(cs)
    return (n, cs, False) if n else None


class PdfImageRef:
    """One image inside a PDF that may be recompressed."""

    def __init__(self, obj):
        pikepdf = _pikepdf()
        if obj.get("/ImageMask"):
            raise Skip("mask")
        if isinstance(obj.get("/Mask"), pikepdf.Array):
            raise Skip("colour key mask")
        if obj.get("/Decode") is not None:
            raise Skip("custom decode")
        if int(obj.get("/BitsPerComponent", 0)) != 8:
            raise Skip("bit depth")
        fl = _filters(obj)
        if any(f not in _OK_FILTERS for f in fl):
            raise Skip("filter")
        info = _colour_info(obj)
        if not info:
            raise Skip("colour space")
        self.ncomp, self.keep_cs, self.indexed = info
        self.obj = obj
        self.filters = fl
        self.w, self.h = int(obj.Width), int(obj.Height)
        if self.w * self.h < (64 if FORCE_GRAY else 10000):
            raise Skip("tiny")
        if self.w * self.h > MAX_PIXELS:
            raise Skip("too large")
        # Size this image takes in the saved file if we leave it alone.
        if fl and fl[-1] in ("/FlateDecode", "/DCTDecode"):
            self.orig_len = len(obj.read_raw_bytes())
        else:                               # stored uncompressed: saving deflates it
            import zlib
            self.orig_len = len(zlib.compress(obj.read_bytes(), 6))
        if self.orig_len < 8 * KB and not FORCE_GRAY:   # too small to be worth compressing
            raise Skip("small")
        self._base = None
        self._enc = {}

    def base(self):
        global _pixel_cache_used
        if self._base is not None:
            return self._base
        pikepdf = _pikepdf()
        Image = _pil()
        obj = self.obj
        im = None
        if self.filters == ["/DCTDecode"]:
            im = Image.open(io.BytesIO(obj.read_raw_bytes()))
            im.load()
        elif "/DCTDecode" not in self.filters and not self.indexed:
            data = obj.read_bytes()
            need = self.w * self.h * self.ncomp
            if len(data) >= need:
                im = Image.frombytes("L" if self.ncomp == 1 else "RGB", (self.w, self.h),
                                     bytes(data[:need]))
        if im is None:
            im = pikepdf.PdfImage(obj).as_pil_image()
            im.load()
        if im.mode in ("P", "RGBA"):        # a soft mask stays attached to the object
            im = im.convert("RGB")
        elif im.mode == "LA":
            im = im.convert("L")
        if im.mode not in ("L", "RGB") or len(im.getbands()) != self.ncomp:
            raise Skip("mode %s" % im.mode)
        cost = im.size[0] * im.size[1] * self.ncomp
        if _pixel_cache_used + cost <= PIXEL_CACHE_BUDGET:
            _pixel_cache_used += cost
            self._base = im
        return im

    def at_level(self, k):
        """(bytes, (w, h), mode) or None when the original should stay."""
        if k not in self._enc:
            cap, q, gray = LADDER[k]
            try:
                data, size, mode = _encode_jpeg(self.base(), cap, q, gray, fast=(k != OPT_LEVEL))
                keep = len(data) <= 0.9 * self.orig_len or (FORCE_GRAY and self.ncomp == 3)
                res = (data, size, mode) if keep else None
            except Skip:
                res = None
            except Exception as e:
                log("image left as it is: %r" % (e,))
                res = None
            self._enc = {k: res}
        return self._enc[k]

    def apply(self, enc):
        pikepdf = _pikepdf()
        data, (w, h), mode = enc
        obj = self.obj
        obj.write(data, filter=pikepdf.Name.DCTDecode)
        if "/DecodeParms" in obj:
            del obj["/DecodeParms"]
        obj.Width = w
        obj.Height = h
        obj.BitsPerComponent = 8
        obj.ColorSpace = pikepdf.Name.DeviceGray if (mode == "L" and self.ncomp == 3) else self.keep_cs


def _pdf_images(pdf):
    seen, objs, refs = set(), [], []
    for page in pdf.pages:
        _walk_images(_page_resources(page.obj), seen, objs)
    for obj in objs:
        try:
            refs.append(PdfImageRef(obj))
        except Skip:
            pass
        except Exception as e:
            log("image skipped: %r" % (e,))
    return refs


def _apply_level(pdf, refs, k):
    for r in refs:
        enc = r.at_level(k)
        if enc:
            r.apply(enc)
    try:
        pdf.remove_unreferenced_resources()
    except Exception:
        pass
    return _save(pdf)


def compress_pdf(open_doc, preset):
    """open_doc() returns a fresh pikepdf document each time it is called.

    Returns (pdf bytes, fits, low_quality)."""
    limit = PRESETS[preset]["limit"]
    pdf = open_doc()
    plain = _save(pdf)                      # lossless clean-up only
    if preset == "original" and not FORCE_GRAY:
        return plain, True, False
    if limit is not None and len(plain) <= limit and not FORCE_GRAY:
        return plain, True, False

    refs = _pdf_images(pdf)
    if not refs:
        return plain, limit is None or len(plain) <= limit, False

    # First the "Optimized" setting: visually identical.
    sizes = []
    for r in refs:
        enc = r.at_level(OPT_LEVEL)
        sizes.append(len(enc[0]) if enc else r.orig_len)
    data = _apply_level(pdf, refs, OPT_LEVEL)
    _release(refs)
    fixed = max(0, len(data) - sum(sizes))  # everything that is not image data
    if len(data) > len(plain) and not FORCE_GRAY:
        data = plain
    if limit is None or len(data) <= limit:
        return data, True, False

    # Size preset: walk down the ladder, always starting from the untouched file.
    pdf = open_doc()
    refs = _pdf_images(pdf)

    def evaluate(k):
        total = fixed
        for r in refs:
            enc = r.at_level(k)
            total += len(enc[0]) if enc else r.orig_len
        return total, None

    levels = list(range(OPT_LEVEL + 1, len(LADDER)))
    pos, _unused, _fits = _find_level(levels, evaluate, limit)
    while True:
        data = _apply_level(pdf, refs, levels[pos])
        _release(refs)
        if len(data) <= limit or pos >= len(levels) - 1:
            break
        pos += 1                            # estimate was a little low
        pdf = open_doc()
        refs = _pdf_images(pdf)
    if len(data) > len(plain) and not FORCE_GRAY:
        data = plain
    return data, len(data) <= limit, levels[pos] >= LOW_LEVEL


def _opener(paths):
    pikepdf = _pikepdf()
    # Files are read into memory once, so no handle stays open on them.
    # An item is a path, the bytes of a PDF, or (bytes, password).
    blobs = []
    for p in paths:
        if isinstance(p, tuple):
            blobs.append(p)
        elif isinstance(p, bytes):
            blobs.append((p, None))
        else:
            check_size(p)
            blobs.append((Path(p).read_bytes(), password_for(p)))
    if len(blobs) == 1:
        return lambda: open_pdf(blobs[0][0], blobs[0][1])

    def merged():
        dst = pikepdf.new()
        keep = []
        for blob, password in blobs:
            src = open_pdf(blob, password)
            keep.append(src)
            copy_pages(dst, src, range(len(src.pages)))
            carry_form(dst, src)
        dst._vitepdf_sources = keep           # sources must stay open until saved
        return dst
    return merged


def copy_pages(dst, src, indexes):
    """Append pages of src to dst. Call carry_form(dst, src) once afterwards."""
    added = []
    for i in indexes:
        dst.pages.append(src.pages[i])
        added.append(dst.pages[-1])
    return added


def carry_form(dst, src):
    """Register the form fields of src in dst after pages were copied.

    Copying a page brings its boxes along but not the list that makes them a
    form. Every field is taken over once, as a whole: a question whose buttons
    sit on several pages stays ONE question. Parts on pages that were not
    copied are dropped, and a name already used in dst gets a number."""
    pikepdf = _pikepdf()
    try:
        acro = src.Root.get("/AcroForm")
        fields = list(acro.get("/Fields") or []) if acro is not None else []
        if not fields:
            return
        on_pages = set()
        for page in dst.pages:
            for a in (page.obj.get("/Annots") or []):
                on_pages.add(a.objgen)

        def prune(field, depth=0):
            """True when the field still has a box on a copied page."""
            kids = field.get("/Kids")
            if kids is None or depth > 40:
                return field.objgen in on_pages
            keep = [k for k in kids if prune(k, depth + 1)]
            if len(keep) != len(kids):
                field.Kids = pikepdf.Array(keep)
            return bool(keep)

        if "/AcroForm" not in dst.Root:
            dst.Root.AcroForm = dst.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array()))
        target = dst.Root.AcroForm
        if "/Fields" not in target:
            target.Fields = pikepdf.Array()
        used = set()
        for f in target.Fields:
            try:
                used.add(str(f.get("/T")))
            except Exception:
                pass
        for field in fields:
            copy = dst.copy_foreign(field)
            if copy.objgen in {f.objgen for f in target.Fields} or not prune(copy):
                continue
            name = str(copy.get("/T")) if copy.get("/T") is not None else "field"
            if name in used:
                n = 2
                while "%s_%d" % (name, n) in used:
                    n += 1
                name = "%s_%d" % (name, n)
                copy.T = pikepdf.String(name)
            used.add(name)
            target.Fields.append(copy)
        # Text settings the fields rely on. Each box also carries its own
        # finished picture, so what you see does not depend on these.
        for key in ("/DA", "/Q"):
            if key in acro and key not in target:
                target[key] = acro[key]
        if "/DR" in acro:
            dr = acro["/DR"]
            dr = dst.copy_foreign(dr if dr.is_indirect else src.make_indirect(dr))
            if "/DR" not in target:
                target.DR = dr
            else:
                for kind in dr.keys():
                    if kind not in target.DR:
                        target.DR[kind] = dr[kind]
                    else:
                        try:
                            for name in dr[kind].keys():
                                if name not in target.DR[kind]:
                                    target.DR[kind][name] = dr[kind][name]
                        except Exception:
                            pass
        if "/NeedAppearances" in target:
            del target["/NeedAppearances"]
    except Exception:
        log("form fields could not be carried over:\n" + traceback.format_exc())


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------

def _finish(report, data, fits, low, preset, folder, stem, source_name, ext=".pdf"):
    """Pick the file name, write the result and note anything unusual."""
    info = PRESETS[preset]
    limit = info["limit"]
    if limit is not None and not fits:
        out = write_file(unique_path(folder, stem + "_smallest", ext), data)
        report.outputs.append(out)
        report.warning("%s: could not get under %s with readable quality. "
                       "Smallest version saved: %s (%s)."
                       % (source_name, info["label"].replace("Under ", ""), fmt_size(len(data)), out.name))
        return
    out = write_file(unique_path(folder, stem + info["suffix"] + ("_bw" if FORCE_GRAY else ""), ext), data)
    report.outputs.append(out)
    if low:
        report.warning("%s: fits %s, but the quality had to drop a lot. "
                       "Check that the text is still readable (%s)."
                       % (source_name, _lower_first(info["label"]), out.name))


def job_img_each(files, preset, report, status):
    for i, f in enumerate(files, 1):
        if status.get("cancel"):
            break
        status["text"] = "Converting %d of %d" % (i, len(files))
        status["name"] = f.name
        try:
            item = SourceImage(f)
            data, fits, low = images_to_pdf([item], preset)
            _release([item])
            _finish(report, data, fits, low, preset, f.parent, f.stem, f.name)
        except Exception as e:
            log("img-each failed:\n%s" % traceback.format_exc())
            report.fail("%s: could not be converted (%s)." % (f.name, _reason(e)))


def job_pdf_compress(files, preset, report, status):
    info = PRESETS[preset]
    limit = info["limit"]
    for i, f in enumerate(files, 1):
        if status.get("cancel"):
            break
        status["text"] = "Compressing %d of %d" % (i, len(files))
        status["name"] = f.name
        try:
            size = f.stat().st_size
            opener = _opener([str(f)])
            opener().close()                  # refuse unreadable files before any shortcut
            if limit is not None and size <= limit and not FORCE_GRAY:
                report.info("%s: already %s (%s). No new file needed."
                            % (f.name, _lower_first(info["label"]), fmt_size(size)))
                continue
            data, fits, low = compress_pdf(opener, preset)
            if len(data) > 0.95 * size and (limit is None or not fits) and not FORCE_GRAY:
                if limit is None:
                    report.info("%s: already optimized. No smaller version is possible "
                                "without visible loss." % f.name)
                else:
                    report.warning("%s: could not be made smaller (%s). It has little or no "
                                   "image content to compress." % (f.name, fmt_size(size)))
                continue
            _finish(report, data, fits, low, preset, f.parent, f.stem, f.name)
        except Exception as e:
            log("pdf-compress failed:\n%s" % traceback.format_exc())
            report.fail("%s: could not be compressed (%s)." % (f.name, _reason(e)))


def _reason(e):
    name = type(e).__name__
    if name == "PasswordError" or "password" in str(e).lower():
        return "password protected"
    if isinstance(e, TooBig):
        return str(e)
    if name.startswith("DecompressionBomb"):
        return "the picture has more than %d megapixels" % (MAX_PIXELS // 10 ** 6)
    if isinstance(e, FileNotFoundError):
        return "file not found"
    if name == "UnidentifiedImageError":
        return "not a supported image"
    if name == "PdfError":
        return "damaged or unsupported PDF"
    if isinstance(e, PermissionError):
        return "file is open in another program or the folder is read-only"
    text = str(e).strip().splitlines()[0] if str(e).strip() else name
    return text[:120]


# --------------------------------------------------------------------------
# Multi-select: Explorer starts one process per selected file.
# The processes meet in a small queue folder; one of them takes the whole batch.
# --------------------------------------------------------------------------

def _try_lock(path):
    f = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


BATCH_GAP = 0.0     # longest pause between two files of the batch just collected


def _prune_queues(base):
    """Remove queue folders that have not been used for a day."""
    try:
        for d in base.iterdir():
            if d.is_dir() and time.time() - d.stat().st_mtime > 86400:
                for f in d.iterdir():
                    f.unlink()
                d.rmdir()
    except OSError:
        pass


def collect_batch(key, path, quiet):
    """Returns every path of this batch, or None when another process took it."""
    qdir = data_dir() / "queue" / key
    if not qdir.exists():
        _prune_queues(data_dir() / "queue")
    qdir.mkdir(parents=True, exist_ok=True)
    name = "%020d-%d" % (time.time_ns(), os.getpid())
    tmp = qdir / (name + ".tmp")
    entry = qdir / (name + ".item")
    tmp.write_text(str(path), encoding="utf-8")
    os.replace(tmp, entry)

    lock = None
    deadline = time.monotonic() + 120
    while lock is None:
        if not entry.exists():
            return None
        lock = _try_lock(qdir / "lock")
        if lock is None:
            if time.monotonic() > deadline:
                return [str(path)]
            time.sleep(0.04)
    try:
        if not entry.exists():
            return None
        count, changed = -1, time.monotonic()
        while True:
            items = sorted(qdir.glob("*.item"))
            now = time.monotonic()
            if len(items) != count:
                count, changed = len(items), now
            elif now - changed >= quiet:
                break
            time.sleep(0.03)
        paths, stamps = [], []
        for it in items:
            try:
                fresh = time.time() - it.stat().st_mtime < 60
                text = it.read_text(encoding="utf-8")
                it.unlink()
                if fresh and text not in paths:
                    paths.append(text)
                    stamps.append(int(it.name.split("-")[0]) / 1e9)
            except (OSError, ValueError):
                pass
        # Explorer hands over one selection in a single burst. A clear pause
        # inside the batch means two selections were started close together.
        global BATCH_GAP
        stamps.sort()
        BATCH_GAP = max([b - a for a, b in zip(stamps, stamps[1:])] or [0.0])
        return paths
    finally:
        lock.close()


