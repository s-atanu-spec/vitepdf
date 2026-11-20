# -*- coding: utf-8 -*-
"""
VitePDF operations added in version 1.2: mixed merge, image output
(compress, convert, resize, black and white), hidden-data removal, repair,
PDF to JPG, split, rotate, password, organize pages, blank PDF, screen capture.

Every job has the same shape:  job(files, option, report, status).
Windows hand their answers over in PARAMS before the job starts.

Created by Atanu Sarkar. Made with Claude.
"""

import io
import json
import struct
import time
import traceback
from pathlib import Path

import vp_core as core
from vp_core import (KB, LADDER, LOW_LEVEL, OPT_LEVEL, PRESETS, SourceImage,
                     _encode_jpeg, _find_level, _finish, _lower_first, _opener,
                     _pikepdf, _pil, _reason, _release, compress_pdf, fmt_size,
                     images_to_pdf, log, unique_path, write_file)

PARAMS = {}                                 # filled by a window before its job runs

PAPER = {"A4": (595.276, 841.890), "Letter": (612.0, 792.0), "Legal": (612.0, 1008.0)}


def is_pdf(f):
    return Path(f).suffix.lower() == ".pdf"


def _steps(files, status, verb):
    """Yield each file, updating the progress text and honouring Cancel."""
    for i, f in enumerate(files, 1):
        if status.get("cancel"):
            return
        status["text"] = "%s %d of %d" % (verb, i, len(files))
        status["name"] = f.name
        yield f


def _fail(report, f, what, e):
    log("%s failed:\n%s" % (what, traceback.format_exc()))
    report.fail("%s: could not be %s (%s)." % (f.name, what, _reason(e)))


def _save(report, folder, stem, ext, data):
    out = write_file(unique_path(folder, stem, ext), data)
    report.outputs.append(out)
    return out


# --------------------------------------------------------------------------
# Settings: presets and recently used sizes
# --------------------------------------------------------------------------

def _settings_path():
    return core.data_dir() / "settings.json"


def load_settings():
    data = {"presets": [None, None], "recent": []}
    try:
        got = json.loads(_settings_path().read_text(encoding="utf-8"))
        if isinstance(got, dict):
            data.update(got)
    except Exception:
        pass
    presets = [p if isinstance(p, dict) else None for p in list(data.get("presets") or [])[:2]]
    data["presets"] = presets + [None] * (2 - len(presets))
    data["recent"] = [r for r in list(data.get("recent") or []) if isinstance(r, list) and len(r) == 2][:3]
    return data


def save_settings(data):
    tmp = _settings_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(_settings_path())


def remember_size(amount, unit):
    data = load_settings()
    entry = [float(amount), unit.upper()]
    data["recent"] = ([entry] + [r for r in data["recent"] if r != entry])[:3]
    save_settings(data)


def preset_label(i):
    p = load_settings()["presets"][i]
    return (p.get("name") or "Preset %d" % (i + 1)) if p else "Preset %d" % (i + 1)


# --------------------------------------------------------------------------
# Hidden data: lossless clean-up of JPG, PNG and PDF
# --------------------------------------------------------------------------

def _orientation_exif(o):
    tiff = (struct.pack("<2sHI", b"II", 42, 8) + struct.pack("<H", 1) +
            struct.pack("<HHIHH", 0x0112, 3, 1, o, 0) + struct.pack("<I", 0))
    body = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def strip_jpeg(data, orientation=None):
    """Remove comments, EXIF, XMP and anything after the picture, without
    touching a single pixel. Colour profile and orientation are kept."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    out = [b"\xff\xd8"]
    if orientation and orientation != 1:
        out.append(_orientation_exif(orientation))
    pos, n = 2, len(data)
    while pos + 4 <= n:
        if data[pos] != 0xFF:
            raise ValueError("damaged JPEG")
        marker = data[pos + 1]
        if marker == 0xFF:                  # padding
            pos += 1
            continue
        if marker == 0xD9:                  # end of picture: drop whatever follows
            out.append(b"\xff\xd9")
            return b"".join(out)
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            out.append(data[pos:pos + 2])
            pos += 2
            continue
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        seg = data[pos:pos + 2 + length]
        keep = True
        if 0xE1 <= marker <= 0xEF or marker == 0xFE:
            keep = ((marker == 0xE2 and seg[4:16] == b"ICC_PROFILE\x00") or
                    (marker == 0xEE and seg[4:9] == b"Adobe"))
        elif marker == 0xE0 and seg[4:9] == b"JFXX\x00":
            keep = False                    # embedded thumbnail
        if keep:
            out.append(seg)
        pos += 2 + length
        if marker == 0xDA:                  # scan data runs up to the next real marker
            start = pos
            while True:
                pos = data.find(b"\xff", pos)
                if pos < 0 or pos + 1 >= n:
                    out.append(data[start:])
                    return b"".join(out)
                nxt = data[pos + 1]
                if nxt == 0x00 or nxt == 0xFF or 0xD0 <= nxt <= 0xD7:
                    pos += 2 if nxt != 0xFF else 1
                    continue
                break
            out.append(data[start:pos])
    out.append(data[pos:])
    return b"".join(out)


_PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB",
             b"iCCP", b"sBIT", b"bKGD", b"pHYs", b"acTL", b"fcTL", b"fdAT"}


def strip_png(data):
    """Remove text notes, EXIF, time stamps and anything after the picture."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    out = [data[:8]]
    pos = 8
    while pos + 12 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos:pos + 12 + length]
        pos += 12 + length
        if ctype in _PNG_KEEP:
            out.append(chunk)
        if ctype == b"IEND":
            break
    return b"".join(out)


_RISKY_ACTIONS = ("/JavaScript", "/Launch", "/ImportData", "/SubmitForm", "/GoToR", "/GoToE", "/Rendition")


def clean_pdf(pdf):
    """Remove document information, scripts, attachments and private
    application data. Returns how many things were removed."""
    pikepdf = _pikepdf()
    count = [0]

    def drop(obj, key):
        try:
            if obj is not None and key in obj:
                del obj[key]
                count[0] += 1
        except Exception:
            pass

    def risky(action):
        try:
            return action is not None and str(action.get("/S")) in _RISKY_ACTIONS
        except Exception:
            return False

    # The library's own sweeps first: they walk the whole document, including
    # attachments fixed to a page and scripts on form fields.
    try:
        from pikepdf import sanitize
        for name in ("remove_attachments", "remove_javascript", "remove_private_app_data",
                     "remove_thumbnails", "remove_collection"):
            try:
                getattr(sanitize, name)(pdf)
            except Exception:
                log("clean-up step %s failed:\n%s" % (name, traceback.format_exc()))
    except ImportError:
        pass
    root = pdf.Root
    for key in ("/Metadata", "/PieceInfo", "/AA", "/Collection"):
        drop(root, key)
    if str(root.get("/PageMode")) == "/UseAttachments":
        drop(root, "/PageMode")
    if risky(root.get("/OpenAction")):
        drop(root, "/OpenAction")
    names = root.get("/Names")
    for key in ("/JavaScript", "/EmbeddedFiles"):
        drop(names, key)
    try:
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
            count[0] += 1
    except Exception:
        pass
    acro = root.get("/AcroForm")
    drop(acro, "/XFA")
    seen, images = set(), []
    for page in pdf.pages:
        obj = page.obj
        for key in ("/AA", "/PieceInfo", "/Metadata", "/Thumb"):
            drop(obj, key)
        try:
            # A file fixed to the page with a paper-clip note.
            annots = obj.get("/Annots")
            if annots is not None:
                def attached(a):
                    if str(a.get("/Subtype")) == "/FileAttachment":
                        return True
                    parent = a.get("/Parent")       # the pop-up note of such a paper clip
                    return parent is not None and str(parent.get("/Subtype")) == "/FileAttachment"
                kept = [a for a in annots if not attached(a)]
                if len(kept) != len(annots):
                    count[0] += len(annots) - len(kept)
                    obj.Annots = pikepdf.Array(kept)
        except Exception:
            log("page attachments could not be removed:\n" + traceback.format_exc())
        try:
            for annot in (obj.get("/Annots") or []):
                drop(annot, "/AA")
                if risky(annot.get("/A")):
                    drop(annot, "/A")
        except Exception:
            pass
        core._walk_images(core._page_resources(obj), seen, images)
    for img in images:
        drop(img, "/Metadata")
        try:
            if core._filters(img) == ["/DCTDecode"]:
                raw = img.read_raw_bytes()
                new = strip_jpeg(raw)
                if len(new) < len(raw):
                    img.write(new, filter=pikepdf.Name.DCTDecode)
                    count[0] += 1
        except Exception:
            pass
    return count[0]


def clean_leftovers(data):
    """Open a cleaned PDF again and name anything that is still inside."""
    pikepdf = _pikepdf()
    left = set()
    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            try:
                if len(pdf.attachments):
                    left.add("attachments")
            except Exception:
                pass
            names = pdf.Root.get("/Names")
            if names is not None:
                if "/EmbeddedFiles" in names:
                    left.add("attachments")
                if "/JavaScript" in names:
                    left.add("scripts")
            try:
                if len(pdf.docinfo.keys()):
                    left.add("document information")
            except Exception:
                pass
            if "/Metadata" in pdf.Root:
                left.add("document information")
            for obj in pdf.objects:
                try:
                    if not isinstance(obj, pikepdf.Dictionary):
                        continue
                    if str(obj.get("/Subtype")) == "/FileAttachment" or \
                            str(obj.get("/Type")) == "/Filespec" and "/EF" in obj:
                        left.add("attachments")
                    if str(obj.get("/S")) == "/JavaScript" or "/JS" in obj:
                        left.add("scripts")
                except Exception:
                    pass
    except Exception:
        log("the cleaned copy could not be re-checked:\n" + traceback.format_exc())
        left.add("the copy could not be re-checked")
    return sorted(left)


# --------------------------------------------------------------------------
# Merge: pictures and PDFs together
# --------------------------------------------------------------------------

def job_merge(files, preset, report, status):
    pikepdf = _pikepdf()
    status["text"] = "Merging %d files" % len(files)
    blobs, used = [], []
    for f in files:
        if status.get("cancel"):
            return
        status["name"] = f.name
        try:
            if is_pdf(f):
                core.check_size(f)
                data = (f.read_bytes(), core.password_for(f))
                core.open_pdf(data[0], data[1]).close()
            else:
                item = SourceImage(f)
                data = images_to_pdf([item], "original")[0]
                _release([item])
            blobs.append(data)
            used.append(f)
        except Exception as e:
            log("merge failed for one file:\n%s" % traceback.format_exc())
            report.fail("%s: skipped (%s)." % (f.name, _reason(e)))
    if not blobs:
        return
    status["name"] = ""
    data, fits, low = compress_pdf(_opener(blobs), preset)
    _finish(report, data, fits, low, preset, used[0].parent, used[0].stem + "_merged",
            "Merged PDF (%d files)" % len(used))


# --------------------------------------------------------------------------
# Pictures that stay pictures
# --------------------------------------------------------------------------

def _jpeg(item, cap, quality, gray=False, fast=False):
    return _encode_jpeg(item.base(), cap, quality, gray, fast=fast, icc=item.icc)[0]


def _open_plain(path):
    """The picture upright, with its transparency kept."""
    Image = _pil()
    from PIL import ImageOps
    im = Image.open(io.BytesIO(Path(path).read_bytes()))
    im.load()
    im = ImageOps.exif_transpose(im)
    if im.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
        im = im.convert("RGB")
    return im


def _png_bytes(im, level=6):
    buf = io.BytesIO()
    im.save(buf, "PNG", compress_level=level)
    return buf.getvalue()


def job_img_compress(files, preset, report, status):
    info = PRESETS[preset]
    limit = info["limit"]
    for f in _steps(files, status, "Compressing"):
        try:
            item = SourceImage(f)
            if limit is None:
                if item.format == "PNG" and not core.FORCE_GRAY:
                    data = _png_bytes(_open_plain(f), 9)
                    ext, enough = ".png", len(data) <= 0.95 * item.file_len
                else:
                    cap, q, _g = LADDER[OPT_LEVEL]
                    data = _jpeg(item, cap, q)
                    ext = ".jpg"
                    enough = item.kind != "jpeg" or core.FORCE_GRAY or len(data) <= 0.8 * item.file_len
                _release([item])
                if not enough:
                    report.info("%s: already optimized. No smaller version is possible "
                                "without visible loss." % f.name)
                    continue
                _finish(report, data, True, False, preset, f.parent, f.stem, f.name, ext=ext)
                continue
            if item.file_len <= limit and not core.FORCE_GRAY:
                report.info("%s: already %s (%s). No new file needed."
                            % (f.name, _lower_first(info["label"]), fmt_size(item.file_len)))
                continue
            if item.format == "PNG" and not core.FORCE_GRAY:
                data = _png_bytes(_open_plain(f), 9)
                if len(data) <= limit:
                    _release([item])
                    _finish(report, data, True, False, preset, f.parent, f.stem, f.name, ext=".png")
                    continue

            def evaluate(k):
                cap, q, gray = LADDER[k]
                d = _jpeg(item, cap, q, gray, fast=True)
                return len(d), d

            levels = list(range(len(LADDER)))
            pos, data, fits = _find_level(levels, evaluate, limit, first=OPT_LEVEL)
            _release([item])
            _finish(report, data, fits, fits and pos >= LOW_LEVEL, preset, f.parent, f.stem,
                    f.name, ext=".jpg")
        except Exception as e:
            _fail(report, f, "compressed", e)


def job_img_convert(files, target, report, status):
    for f in _steps(files, status, "Converting"):
        try:
            item = SourceImage(f)
            if target == "jpg":
                if item.format in ("JPEG", "MPO"):
                    report.info("%s: is already a JPG." % f.name)
                    continue
                data = _jpeg(item, None, 92)
                _release([item])
            else:
                if item.format == "PNG":
                    report.info("%s: is already a PNG." % f.name)
                    continue
                data = _png_bytes(_open_plain(f))
            _save(report, f.parent, f.stem, "." + target, data)
        except Exception as e:
            _fail(report, f, "converted", e)


def job_img_bw(files, _option, report, status):
    for f in _steps(files, status, "Converting"):
        try:
            item = SourceImage(f)
            if item.format == "PNG":
                im = _open_plain(f)
                data = _png_bytes(im.convert("LA" if "A" in im.getbands() or "transparency" in im.info else "L"))
                ext = ".png"
            else:
                data = _encode_jpeg(item.base(), None, 90, True)[0]
                ext = ".jpg"
                _release([item])
            _save(report, f.parent, f.stem + "_bw", ext, data)
        except Exception as e:
            _fail(report, f, "converted", e)


def job_img_clean(files, _option, report, status):
    for f in _steps(files, status, "Cleaning"):
        try:
            item = SourceImage(f)
            raw = f.read_bytes()
            if item.format in ("JPEG", "MPO"):
                if item.jpeg_len:
                    raw = raw[:item.jpeg_len]
                data, ext = strip_jpeg(raw, item.orientation), ".jpg"
            elif item.format == "PNG":
                data, ext = strip_png(raw), ".png"
            else:
                report.fail("%s: hidden data can be removed from JPG and PNG. Use "
                               "Convert to JPG for this file; that removes it as well." % f.name)
                continue
            if data == f.read_bytes():
                report.info("%s: has no hidden data. No new file needed." % f.name)
                continue
            _save(report, f.parent, f.stem + "_clean", ext, data)
        except Exception as e:
            _fail(report, f, "cleaned", e)


def job_img_repair(files, _option, report, status):
    Image = _pil()
    from PIL import ImageFile
    for f in _steps(files, status, "Repairing"):
        raw = f.read_bytes()
        try:
            im = Image.open(io.BytesIO(raw))
            im.load()
            report.info("%s: opens without errors. No repair needed." % f.name)
            continue
        except Exception:
            pass
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            im = Image.open(io.BytesIO(raw))
            fmt = im.format
            im.load()
            if fmt == "PNG":
                data, ext = _png_bytes(im), ".png"
            else:
                buf = io.BytesIO()
                core._flatten(im).save(buf, "JPEG", quality=95)
                data, ext = buf.getvalue(), ".jpg"
            out = _save(report, f.parent, f.stem + "_repaired", ext, data)
            report.warning("%s: repaired as %s. Part of the picture was missing and shows as a "
                           "plain area. Check the result." % (f.name, out.name))
        except Exception as e:
            _fail(report, f, "repaired", e)
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = False


def job_img_resize(files, _option, report, status):
    Image = _pil()
    from PIL import ImageOps
    w, h = int(PARAMS["width"]), int(PARAMS["height"])
    crop = PARAMS.get("mode", "crop") == "crop"
    limit = PARAMS.get("limit")             # bytes or None
    for f in _steps(files, status, "Resizing"):
        try:
            item = SourceImage(f)
            im = item.base()
            if im.mode == "CMYK":
                im = im.convert("RGB")
            if crop:
                out = ImageOps.fit(im, (w, h), Image.LANCZOS, centering=(0.5, 0.5))
            else:
                out = ImageOps.pad(im, (w, h), Image.LANCZOS,
                                   color=(255 if im.mode == "L" else (255, 255, 255)))
            _release([item])
            fits = True
            if limit:
                qualities = list(range(95, 14, -5))

                def evaluate(q):
                    d = _encode_jpeg(out, None, q, False, fast=True, icc=item.icc)[0]
                    return len(d), d

                _pos, data, fits = _find_level(qualities, evaluate, limit)
            else:
                data = _encode_jpeg(out, None, 92, False, icc=item.icc)[0]
            saved = _save(report, f.parent, "%s_%dx%d" % (f.stem, w, h), ".jpg", data)
            if not fits:
                report.warning("%s: resized, but could not get under %s. Saved at %s (%s)."
                               % (f.name, fmt_size(limit), fmt_size(len(data)), saved.name))
        except Exception as e:
            _fail(report, f, "resized", e)


# --------------------------------------------------------------------------
# PDF jobs
# --------------------------------------------------------------------------

def render_page(doc, index, dpi=200, max_side=6000):
    """One PDF page as an RGB picture."""
    page = doc[index]
    w, h = page.get_size()
    scale = dpi / 72.0
    longest = max(w, h) * scale
    if longest > max_side:
        scale *= max_side / longest
    return page.render(scale=scale).to_pil().convert("RGB")


def open_for_render(path_or_bytes, password=None):
    import pypdfium2 as pdfium
    if isinstance(path_or_bytes, bytes):
        data = path_or_bytes
    else:
        core.check_size(path_or_bytes)
        data = Path(path_or_bytes).read_bytes()
        password = password or core.password_for(path_or_bytes)
    doc = pdfium.PdfDocument(data, password=password)
    if len(doc) > core.MAX_PAGES:
        raise core.TooBig("the PDF has more than %d pages" % core.MAX_PAGES)
    try:
        doc.init_forms()          # without this, values typed into form fields are not drawn
    except Exception:
        log("form rendering is not available:\n" + traceback.format_exc())
    return doc


def job_pdf_tojpg(files, preset, report, status):
    info = PRESETS.get(preset, {"limit": None, "label": "Best quality", "suffix": ""})
    limit = info["limit"]
    for f in _steps(files, status, "Converting"):
        try:
            doc = open_for_render(f)
            n = len(doc)
            for i in range(n):
                if status.get("cancel"):
                    return
                status["name"] = "%s, page %d of %d" % (f.name, i + 1, n)
                im = render_page(doc, i, 300 if preset == "best" else 200)
                stem = f.stem if n == 1 else "%s_page%02d" % (f.stem, i + 1)
                if limit is None:
                    data = _encode_jpeg(im, None, 95 if preset == "best" else 85, False)[0]
                    _save(report, f.parent, stem + info["suffix"], ".jpg", data)
                    continue

                def evaluate(k, im=im):
                    cap, q, gray = LADDER[k]
                    d = _encode_jpeg(im, cap, q, gray, fast=True)[0]
                    return len(d), d

                levels = list(range(len(LADDER)))
                pos, data, fits = _find_level(levels, evaluate, limit, first=OPT_LEVEL)
                _finish(report, data, fits, fits and pos >= LOW_LEVEL, preset, f.parent, stem,
                        "%s page %d" % (f.name, i + 1), ext=".jpg")
        except Exception as e:
            _fail(report, f, "converted", e)


def _open_pdf(f, password=None):
    return core.open_pdf(f, password)


def _pdf_bytes(pdf, **kw):
    pikepdf = _pikepdf()
    buf = io.BytesIO()
    pdf.save(buf, compress_streams=True,
             object_stream_mode=pikepdf.ObjectStreamMode.generate, **kw)
    return buf.getvalue()


def job_pdf_split(files, _option, report, status):
    pikepdf = _pikepdf()
    for f in _steps(files, status, "Splitting"):
        try:
            src = _open_pdf(f)
            n = len(src.pages)
            if n < 2:
                report.info("%s: has only one page." % f.name)
                continue
            for i in range(n):
                dst = pikepdf.new()
                core.copy_pages(dst, src, [i])
                core.carry_form(dst, src)
                _save(report, f.parent, "%s_page%02d" % (f.stem, i + 1), ".pdf", _pdf_bytes(dst))
        except Exception as e:
            _fail(report, f, "split", e)


def job_pdf_rotate(files, direction, report, status):
    angle = 90 if direction == "right" else -90
    for f in _steps(files, status, "Rotating"):
        try:
            pdf = _open_pdf(f)
            for page in pdf.pages:
                page.rotate(angle, relative=True)
            _save(report, f.parent, f.stem + "_rotated", ".pdf", _pdf_bytes(pdf))
        except Exception as e:
            _fail(report, f, "rotated", e)


def job_pdf_bw(files, _option, report, status):
    core.FORCE_GRAY = True
    for f in _steps(files, status, "Converting"):
        try:
            if not core._pdf_images(_open_pdf(f)):
                report.info("%s: has no pictures to convert. Coloured text and drawings "
                            "are not changed." % f.name)
                continue
            data = compress_pdf(_opener([str(f)]), "optimized")[0]
            _save(report, f.parent, f.stem + "_bw", ".pdf", data)
        except Exception as e:
            _fail(report, f, "converted", e)


def job_pdf_clean(files, _option, report, status):
    for f in _steps(files, status, "Cleaning"):
        try:
            pdf = _open_pdf(f)
            clean_pdf(pdf)
            try:
                pdf.remove_unreferenced_resources()
            except Exception:
                pass
            data = _pdf_bytes(pdf)
            left = clean_leftovers(data)
            out = _save(report, f.parent, f.stem + "_clean", ".pdf", data)
            if left:
                report.warning("%s: saved, but some hidden data could not be removed (%s). "
                               "Check the copy before you share it." % (out.name, ", ".join(left)))
        except Exception as e:
            _fail(report, f, "cleaned", e)


def job_pdf_repair(files, _option, report, status):
    for f in _steps(files, status, "Repairing"):
        try:
            pdf = _open_pdf(f)
            try:
                problems = pdf.check_pdf_syntax()
            except Exception:
                problems = ["?"]
            if not problems:
                report.info("%s: opens without errors. No repair needed." % f.name)
                continue
            _save(report, f.parent, f.stem + "_repaired", ".pdf", _pdf_bytes(pdf))
        except Exception as e:
            _fail(report, f, "repaired", e)


def job_pdf_password(files, _option, report, status):
    pikepdf = _pikepdf()
    add = PARAMS.get("mode", "add") == "add"
    password = PARAMS.get("password") or ""
    if add and len(password) < 4:
        for f in files:
            report.fail("%s: no protected copy was made. A password needs at least 4 characters."
                        % f.name)
        return
    for f in _steps(files, status, "Protecting" if add else "Unlocking"):
        try:
            if add:
                pdf = _open_pdf(f)
                data = _pdf_bytes(pdf, encryption=pikepdf.Encryption(user=password, owner=password, R=6))
                _save(report, f.parent, f.stem + "_protected", ".pdf", data)
            else:
                try:
                    pdf = _open_pdf(f)          # restrictions only: opens without a password
                    if not pdf.is_encrypted:
                        report.info("%s: has no password." % f.name)
                        continue
                except pikepdf.PasswordError:
                    pdf = _open_pdf(f, password)
                _save(report, f.parent, f.stem + "_unlocked", ".pdf", _pdf_bytes(pdf))
        except pikepdf.PasswordError:
            report.fail("%s: that password is not correct." % f.name)
        except Exception as e:
            _fail(report, f, "saved", e)


def crop_box(mediabox, rotation, frac):
    """Turn a rectangle drawn on the upright page (fractions, origin top
    left) into PDF page coordinates."""
    x0, y0, x1, y1 = [float(v) for v in mediabox]
    w, h = x1 - x0, y1 - y0
    u0, v0, u1, v1 = frac
    pts = []
    for u, v in ((u0, v0), (u1, v1)):
        r = rotation % 360
        if r == 0:
            fx, fy = u, 1 - v
        elif r == 90:
            fx, fy = v, u
        elif r == 180:
            fx, fy = 1 - u, v
        else:
            fx, fy = 1 - v, 1 - u
        pts.append((x0 + fx * w, y0 + fy * h))
    xs, ys = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
    return [xs[0], ys[0], xs[1], ys[1]]


def job_pdf_organize(files, _option, report, status):
    """PARAMS: pages = [{index, rotate, crop, selected}], mode = one | selected | each."""
    pikepdf = _pikepdf()
    f = files[0]
    status["text"] = "Saving pages"
    status["name"] = f.name
    try:
        src = _open_pdf(f, PARAMS.get("password"))
        entries = PARAMS["pages"]
        mode = PARAMS.get("mode", "one")
        if mode == "selected":
            entries = [e for e in entries if e.get("selected")]
        if not entries:
            report.info("No pages to save.")
            return

        def build(part):
            dst = pikepdf.new()
            for e in part:
                page = core.copy_pages(dst, src, [e["index"]])[0]
                if e.get("rotate"):
                    page.rotate(int(e["rotate"]), relative=True)
                if e.get("crop"):
                    total = int(page.obj.get("/Rotate", 0))
                    box = crop_box(page.mediabox, total, e["crop"])
                    page.obj.MediaBox = box
                    page.obj.CropBox = box
            core.carry_form(dst, src)
            return _pdf_bytes(dst)

        if mode == "each":
            for n, e in enumerate(entries, 1):
                _save(report, f.parent, "%s_page%02d" % (f.stem, n), ".pdf", build([e]))
        else:
            stem = f.stem + ("_pages" if mode == "selected" else "_organized")
            _save(report, f.parent, stem, ".pdf", build(entries))
    except Exception as e:
        _fail(report, f, "saved", e)


# --------------------------------------------------------------------------
# No file selected: blank PDF and screen capture
# --------------------------------------------------------------------------

def make_blank(folder, size="A4", landscape=False, pages=1):
    pikepdf = _pikepdf()
    w, h = PAPER.get(size, PAPER["A4"])
    if landscape:
        w, h = h, w
    pdf = pikepdf.new()
    for _ in range(max(1, min(int(pages), 500))):
        pdf.add_blank_page(page_size=(w, h))
    pdf.docinfo["/Producer"] = "%s %s" % (core.APP_NAME, core.VERSION)
    out = write_file(unique_path(folder, "Blank %s%s" % (size, " landscape" if landscape else "")),
                     _pdf_bytes(pdf))
    return out


def picture_to_pdf(im):
    """Screen pixels as a lossless one-page PDF."""
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    payload = core._png_payload(_png_bytes(im))
    pw, ph = im.size[0] * 72.0 / 96.0, im.size[1] * 72.0 / 96.0
    box = core.A4_PT if ph >= pw else (core.A4_PT[1], core.A4_PT[0])
    s = min(1.0, box[0] / pw, box[1] / ph)
    return core.build_image_pdf([(payload, (pw * s, ph * s))])


def save_capture(folder, im):
    out = write_file(unique_path(folder, "vitepdf-capture"),
                     picture_to_pdf(im))
    return out
