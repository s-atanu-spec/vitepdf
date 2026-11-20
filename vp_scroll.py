#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VitePDF Scroll: capture something taller than the screen, for example a long email.

  1. drag a box over the visible part,
  2. the page scrolls by itself (or you scroll by hand); everything that passes
     above the red END line is captured,
  3. press Finish, trim the top and bottom, save.

The parts are joined at the exact row where they overlap. No pixel is resized
or blended. The result is cut into A4 pages and saved as a lossless PDF.

What this part of VitePDF does on the computer: it looks at the screen inside
the box, and it may turn the mouse wheel so the page scrolls. That is the only
input it ever sends: no clicks, no typing, and it never moves the pointer.
No network, no clipboard.

Created by Atanu Sarkar. Made with Claude.
"""

import io
import os
import struct
import sys
import time
import zlib
from pathlib import Path

A4_W, A4_H = 595.276, 841.890          # points
MARGIN = 20.0                          # the thin margin, in points
RED = "#E0262B"
LANDSCAPE_FROM = 1100                  # captures wider than this many pixels go on landscape pages


# --------------------------------------------------------------------------
# Joining: pure logic, no screen access. Tested on its own.
# --------------------------------------------------------------------------

def split_rows(data, width, height, bpp=3):
    step = width * bpp
    return [data[i * step:(i + 1) * step] for i in range(height)]


def is_blank(row, bpp=3):
    """A row in one flat colour: the gap between lines or paragraphs."""
    return row == row[:bpp] * (len(row) // bpp)


class Stitcher:
    """Builds one tall strip from pictures of the same area taken while the
    content scrolls. Rows are matched exactly; nothing is ever guessed."""

    MIN_MATCH = 12          # distinctive rows that must agree before a join is trusted
    MIN_RATIO = 0.80        # share of comparable rows that must agree
    MAX_BYTES = 300 * 1000 * 1000    # the strip never grows past this much memory

    def __init__(self, width, height):
        self.width, self.height = width, height
        self.rows = []               # the strip, one bytes object per pixel row
        self.blank = []              # per strip row: is it part of an even, flat gap?
        self.index = {}              # row hash -> strip positions (distinctive rows only)
        self.pos = 0                 # strip position of the top row of the latest frame
        self.bottom_skip = 0         # rows at the bottom of the box that never move
        self.top_static = 0          # rows at the top of the box that never move
        self.last_frame = None
        self.last_pos = 0
        self.lost = False
        self.full = False
        self.frozen = False          # follow the page but add no new rows
        self.expect = None           # where the top of the box should be after a wheel turn we sent
        self.max_rows = max(height * 2, self.MAX_BYTES // max(1, width * 3))
        self.stats = {"frames": 0, "appended": 0, "lost": 0, "resynced": 0, "moved_up": 0,
                      "mismatch_rows": 0, "ambiguous": 0}

    # -- helpers
    def _add(self, row):
        p = len(self.rows)
        # "Plain" means a flat colour AND the same as the row above: part of an
        # even gap. A flat row whose colour differs from its neighbour (the edge
        # of a band, a step of a gradient) still tells us where we are.
        b = is_blank(row) and (p == 0 or row == self.rows[p - 1])
        self.rows.append(row)
        self.blank.append(b)
        if not b:
            self.index.setdefault(hash(row), []).append(p)

    def _locate(self, frame):
        """Where does this frame sit on the strip? -> strip position of its top row, or None."""
        usable = self.height - self.bottom_skip
        votes = {}
        probes = 0
        for i in range(0, usable, 2):
            row = frame[i]
            if is_blank(row) and i and row == frame[i - 1]:
                continue
            hits = self.index.get(hash(row))
            if not hits or len(hits) > 12:      # too common to say anything
                continue
            probes += 1
            for sp in hits:
                votes[sp - i] = votes.get(sp - i, 0) + 1
        if not votes:
            return None, probes
        # Several places can look alike when a page repeats itself (table rows, a thread of
        # similar messages), so more than a few candidates are looked at.
        best = sorted(votes.items(), key=lambda kv: (-kv[1], abs(kv[0] - self.pos)))[:16]
        good = []
        for cand, _v in best:
            ok, same, total = self._verify(frame, cand)
            if ok:
                good.append((same, cand, total))
        if not good:
            # No place fits outright. Try once more allowing for a bar that has appeared at the
            # top of the box; this is only trusted when exactly one place fits that way.
            for cand, _v in best:
                ok, same, total = self._verify(frame, cand, relaxed=True)
                if ok:
                    good.append((same, cand, total))
            if len(good) != 1:
                return None, probes
            self.stats["bar_seen"] = self.stats.get("bar_seen", 0) + 1
        # The place that fits best wins: the smallest share of rows that differ. A place where
        # everything agrees beats one where most agrees, however many rows that one covers.
        # Places that fit equally well are told apart by where the page was expected to be
        # (after a wheel turn the tool sent), or else by the nearest one.
        def miss(g):
            return (g[2] - g[0]) / float(max(1, g[2]))
        least = min(miss(g) for g in good)
        level = [g for g in good if miss(g) <= least + 0.02]
        if len(level) > 1:
            self.stats["ambiguous"] += 1
        want = self.expect if self.expect is not None else self.pos
        level.sort(key=lambda g: (abs(g[1] - want), -g[0]))
        return level[0][1], probes

    def _verify(self, frame, cand, relaxed=False):
        usable = self.height - self.bottom_skip
        same = total = 0
        n = len(self.rows)
        flags = []
        for i in range(usable):
            sp = cand + i
            if sp < 0 or sp >= n or self.blank[sp]:
                continue
            total += 1
            hit = self.rows[sp] == frame[i]
            flags.append((i, hit))
            if hit:
                same += 1
        if same >= self.MIN_MATCH and same >= self.MIN_RATIO * total:
            return True, same, total
        if not relaxed:
            return False, same, total
        # A bar may have appeared at the top of the box (a header that pins itself once the page
        # scrolls). Then the rows under it differ, but everything below still fits. Accept that
        # when the part below the bar fits almost perfectly and is large enough.
        limit = int(0.45 * usable)
        tail_same = same
        tail_total = total
        for i, hit in flags:
            if i > limit:
                break
            tail_total -= 1
            tail_same -= 1 if hit else 0
            if not hit and tail_total and tail_same >= 2 * self.MIN_MATCH and tail_same >= 0.95 * tail_total:
                return True, same, total
        return False, same, total

    # -- the one entry point
    def feed(self, frame, stable=True):
        """frame: list of row bytes for the box. stable: the picture did not
        change between two looks, so it is safe to take new rows from it.
        -> "start", "same", "added", "tracked", "lost", "bad" """
        self.stats["frames"] += 1
        step = self.width * 3
        if len(frame) != self.height or any(len(r) != step for r in frame):
            return "bad"                         # not a picture of the box: ignore it
        if not self.rows:
            for row in frame:
                self._add(row)
            self.pos, self.last_frame, self.last_pos = 0, frame, 0
            return "start"
        if frame == self.last_frame and not self.lost:
            return "same"
        cand, _probes = self._locate(frame)
        if cand is None:
            if all(is_blank(r) for r in frame) and self.last_frame is not None and \
                    all(is_blank(r) for r in self.last_frame):
                return "same"
            if not self.lost:
                self.stats["lost"] += 1
            self.lost = True
            return "lost"
        if self.lost:
            self.stats["resynced"] += 1
            self.lost = False
        shift = cand - self.last_pos
        if shift and self.last_frame is not None:
            self._find_static(frame, self.last_frame)
        if shift < 0:
            self.stats["moved_up"] += 1
        self.pos = cand
        result = "tracked"
        if stable:
            usable = self.height - self.bottom_skip
            first_new = len(self.rows) - cand            # frame row of the first unseen row
            if 0 <= first_new < usable and not self.frozen:
                room = self.max_rows - len(self.rows)
                last = min(usable, first_new + max(0, room))
                for i in range(first_new, last):
                    self._add(frame[i])
                self.stats["appended"] += last - first_new
                self.full = last < usable
                result = "added"
            _ok, same, total = self._verify(frame, cand)
            self.stats["mismatch_rows"] += max(0, total - same - self.top_static)
            self.last_frame, self.last_pos = frame, cand
        return result

    def _find_static(self, frame, prev):
        """Rows that stay put while the rest moves: a fixed bar inside the box."""
        h = self.height
        top = 0
        while top < h and frame[top] == prev[top]:
            top += 1
        solid = sum(1 for r in frame[:top] if not is_blank(r))
        self.top_static = top if solid >= 4 else 0
        if self.bottom_skip:
            return
        bottom = 0
        while bottom < h - top and frame[h - 1 - bottom] == prev[h - 1 - bottom]:
            bottom += 1
        solid = sum(1 for r in frame[h - bottom:] if not is_blank(r)) if bottom else 0
        if bottom and solid >= 4:
            # The first picture stored these rows as if they were content. Take
            # them out again, as long as nothing was added after them.
            if len(self.rows) == self.last_pos + h:
                for _ in range(bottom):
                    p = len(self.rows) - 1
                    row = self.rows.pop()
                    if not self.blank.pop():
                        lst = self.index.get(hash(row))
                        if lst and lst[-1] == p:
                            lst.pop()
            self.bottom_skip = bottom

    # -- what the red line needs
    def boundary_in_frame(self):
        """Frame row where the captured part ends (may be beyond the box)."""
        return len(self.rows) - self.pos

    def total(self):
        return len(self.rows)

    def view_end(self):
        """Strip row just below what the box shows right now. This is where
        the capture should end if the user stops here, also after scrolling
        further down and coming back up."""
        if self.lost:
            return len(self.rows)
        return max(0, min(len(self.rows), self.pos + self.height - self.bottom_skip))

    def snap(self, row, reach=14):
        """The nearest row inside an even gap, if one is close."""
        n = len(self.rows)
        row = max(0, min(n, row))
        for d in range(reach + 1):
            for r in (row - d, row + d):
                if 0 < r < n and self.blank[r - 1] and self.blank[r]:
                    return r
        return row


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def page_size(width_px, mode="auto"):
    """-> (page width, page height) in points. mode: auto, portrait, landscape."""
    mode = (mode or "auto").lower()
    if mode == "landscape" or (mode == "auto" and width_px > LANDSCAPE_FROM):
        return (A4_H, A4_W)
    return (A4_W, A4_H)


def rows_per_page(width_px, margin=MARGIN, page=None):
    pw, ph = page or (A4_W, A4_H)
    scale = (pw - 2 * margin) / float(width_px)            # points per pixel
    return max(50, int((ph - 2 * margin) / scale))


def _busy(row):
    """How much happens along one row of pixels: 0 for a plain row, small for a row
    that only crosses a few borders, large for a row through a line of text."""
    return sum(1 for a, b in zip(row[3:], row[:-3]) if a != b)


def paginate(blank, start, end, per_page, window=0.14, min_gap=2, rows=None):
    """Cut rows [start, end) into pages of at most per_page rows. A cut is
    moved up to the nearest gap between lines. Where a page has no such gap
    (tables, coloured panels), it is moved to the quietest row nearby, such as
    a border between two table rows, when rows (the pixel rows) are given.
    -> ([(a, b), ...], [page numbers that had to be cut through content])"""
    pages, hard = [], []
    a = start
    while a < end:
        ideal = a + per_page
        if ideal >= end:
            pages.append((a, end))
            break
        lowest = max(a + 1, int(ideal - window * per_page))
        cut = None
        i = ideal
        while i > lowest:
            if blank[i - 1]:
                j = i
                while j > lowest and blank[j - 1]:
                    j -= 1
                if i - j >= min_gap:
                    cut = (i + j) // 2
                    break
                i = j
            else:
                i -= 1
        if cut is None and rows is not None:
            # No empty gap. Look for the quietest row; the latest one wins a tie.
            best, best_cost = None, None
            limit = max(8 * 3, int(0.02 * len(rows[0])))
            for i in range(ideal, lowest, -1):
                cost = _busy(rows[i]) + _busy(rows[i - 1])
                if best_cost is None or cost < best_cost:
                    best, best_cost = i, cost
                    if cost == 0:
                        break
            if best is not None and best_cost <= limit:
                cut = best
        if cut is None:
            cut = ideal
            hard.append(len(pages) + 1)
        pages.append((a, cut))
        a = cut
    return pages, hard


# --------------------------------------------------------------------------
# Lossless PDF
# --------------------------------------------------------------------------

def _png_stream(im):
    """The compressed pixel data of a picture, in the form a PDF can hold as it is."""
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    out, i = [], 8
    while i < len(data):
        n, kind = struct.unpack(">I4s", data[i:i + 8])
        if kind == b"IDAT":
            out.append(data[i + 8:i + 8 + n])
        i += 12 + n
    return b"".join(out)


def build_pdf(strip, pages, long_page=False, margin=MARGIN, page=None):
    """strip: PIL RGB image. pages: [(a, b)] row ranges. -> PDF bytes.
    Each page holds its rows as one lossless picture, at the same scale."""
    import pikepdf
    from pikepdf import Array, Dictionary, Name
    w = strip.width
    pw, ph = page or (A4_W, A4_H)
    scale = (pw - 2 * margin) / float(w)
    pdf = pikepdf.new()
    if long_page:
        pages = [(pages[0][0], pages[-1][1])]
    for a, b in pages:
        part = strip.crop((0, a, w, b))
        idat = _png_stream(part)
        img = pdf.make_stream(idat)
        img.Type = Name.XObject
        img.Subtype = Name.Image
        img.Width = w
        img.Height = b - a
        img.ColorSpace = Name.DeviceRGB
        img.BitsPerComponent = 8
        img.Filter = Name.FlateDecode
        img.DecodeParms = Dictionary(Predictor=15, Colors=3, BitsPerComponent=8, Columns=w)
        draw_w, draw_h = w * scale, (b - a) * scale
        page_h = draw_h + 2 * margin if long_page else ph
        y = page_h - margin - draw_h
        content = "q %.4f 0 0 %.4f %.4f %.4f cm /Im0 Do Q" % (draw_w, draw_h, margin, y)
        pg = Dictionary(Type=Name.Page, MediaBox=Array([0, 0, round(pw, 3), round(page_h, 3)]),
                        Resources=Dictionary(XObject=Dictionary(Im0=img)),
                        Contents=pdf.make_stream(content.encode("ascii")))
        pdf.pages.append(pikepdf.Page(pdf.make_indirect(pg)))
    try:
        import vp_core
        pdf.docinfo["/Producer"] = "%s %s" % (vp_core.APP_NAME, vp_core.VERSION)
    except Exception:
        pass
    buf = io.BytesIO()
    pdf.save(buf, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    return buf.getvalue()



# --------------------------------------------------------------------------
# Windows helpers
# --------------------------------------------------------------------------

def _win():
    if os.name != "nt":
        return None
    import ctypes
    return ctypes


def pointer_pos():
    """Where the mouse pointer is, in screen pixels, or None."""
    c = _win()
    if not c:
        return None
    try:
        from ctypes import wintypes
        pt = wintypes.POINT()
        if c.windll.user32.GetCursorPos(c.byref(pt)):
            return (pt.x, pt.y)
    except Exception:
        pass
    return None


def send_wheel(delta):
    """Turn the mouse wheel: +120 is one notch up. The only input this tool ever sends."""
    c = _win()
    if not c:
        return False
    try:
        c.windll.user32.mouse_event(0x0800, 0, 0, c.c_ulong(int(delta) & 0xFFFFFFFF), 0)
        return True
    except Exception:
        return False


def esc_pressed():
    c = _win()
    if not c:
        return False
    try:
        return bool(c.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
    except Exception:
        return False


def dpi_aware():
    c = _win()
    if c:
        try:
            c.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                c.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def virtual_origin():
    c = _win()
    if c:
        try:
            gm = c.windll.user32.GetSystemMetrics
            return gm(76), gm(77)
        except Exception:
            pass
    return 0, 0


def grab(box=None):
    """Picture of the screen, or of box (left, top, right, bottom) in screen pixels."""
    from PIL import ImageGrab
    if os.name == "nt":
        im = ImageGrab.grab(bbox=box, all_screens=True)
    else:
        im = ImageGrab.grab(bbox=box)
    return im.convert("RGB")


def _hwnd(win):
    """The real top-level window handle of a Tk window."""
    c = _win()
    win.update_idletasks()
    try:
        return int(win.wm_frame(), 16)
    except Exception:
        c.windll.user32.GetParent.restype = c.c_void_p
        c.windll.user32.GetParent.argtypes = [c.c_void_p]
        return c.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()


def _layered(win, alpha):
    """Slightly see-through. Besides the look, Windows then draws the window
    on a separate layer, which the screen pictures taken here do not include."""
    try:
        win.attributes("-alpha", alpha)
    except Exception:
        pass


def hide_from_capture(win):
    """Ask Windows to leave this window out of screen pictures. -> True if accepted."""
    c = _win()
    if not c:
        return False
    try:
        c.windll.user32.SetWindowDisplayAffinity.argtypes = [c.c_void_p, c.c_uint]
        return bool(c.windll.user32.SetWindowDisplayAffinity(_hwnd(win), 0x11))
    except Exception:
        return False


def pass_clicks(win, also_no_focus=True):
    """Mouse clicks and the wheel go through this window to what is under it."""
    c = _win()
    if not c:
        return
    try:
        u = c.windll.user32
        get = getattr(u, "GetWindowLongPtrW", None) or u.GetWindowLongW
        put = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
        get.restype = c.c_void_p
        get.argtypes = [c.c_void_p, c.c_int]
        put.restype = c.c_void_p
        put.argtypes = [c.c_void_p, c.c_int, c.c_void_p]
        h = _hwnd(win)
        style = get(h, -20) or 0
        style |= 0x00080000 | 0x00000020 | 0x00000080          # layered, transparent, tool window
        if also_no_focus:
            style |= 0x08000000
        put(h, -20, style)
    except Exception:
        pass


def no_focus(win):
    """The window can be clicked but never takes the keyboard from the browser."""
    c = _win()
    if not c:
        return
    try:
        u = c.windll.user32
        get = getattr(u, "GetWindowLongPtrW", None) or u.GetWindowLongW
        put = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
        get.restype = c.c_void_p
        get.argtypes = [c.c_void_p, c.c_int]
        put.restype = c.c_void_p
        put.argtypes = [c.c_void_p, c.c_int, c.c_void_p]
        h = _hwnd(win)
        put(h, -20, (get(h, -20) or 0) | 0x08000000 | 0x00000080)
    except Exception:
        pass


FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"


# --------------------------------------------------------------------------
# Step 1: choose the area
# --------------------------------------------------------------------------

def choose_area(hooks=None):
    """Dim the screen and let the user drag a box. -> (left, top, right, bottom) or None."""
    import tkinter as tk
    from PIL import ImageEnhance, ImageTk
    x0, y0 = virtual_origin()
    shot = grab()
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry("%dx%d+%d+%d" % (shot.width, shot.height, x0, y0))
    root.attributes("-topmost", True)
    cv = tk.Canvas(root, width=shot.width, height=shot.height, highlightthickness=0, cursor="crosshair")
    cv.pack()
    dark = ImageTk.PhotoImage(ImageEnhance.Brightness(shot).enhance(0.55))
    cv.create_image(0, 0, image=dark, anchor="nw")
    cv.create_text(shot.width // 2, 40, fill="#FFFFFF", font=(FONT, 14),
                   text="Drag a box over the visible part of the email. Leave out any bar "
                        "that stays fixed. Esc cancels.")
    state = {"start": None, "box": None, "img": None, "out": None}

    def press(e):
        state["start"] = (e.x, e.y)

    def motion(e):
        if not state["start"]:
            return
        sx, sy = state["start"]
        box = (min(sx, e.x), min(sy, e.y), max(sx, e.x), max(sy, e.y))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            return
        state["box"] = box
        state["img"] = ImageTk.PhotoImage(shot.crop(box))
        cv.delete("sel")
        cv.create_image(box[0], box[1], image=state["img"], anchor="nw", tags="sel")
        cv.create_rectangle(box[0], box[1], box[2] - 1, box[3] - 1, outline=RED, width=2, tags="sel")

    def release(_e):
        box = state["box"]
        if box and box[2] - box[0] >= 120 and box[3] - box[1] >= 120:
            state["out"] = (box[0] + x0, box[1] + y0, box[2] + x0, box[3] + y0)
        root.quit()

    cv.bind("<ButtonPress-1>", press)
    cv.bind("<B1-Motion>", motion)
    cv.bind("<ButtonRelease-1>", release)
    root.bind("<Escape>", lambda e: root.quit())
    root.focus_force()
    if hooks and hooks.get("area"):
        hooks["area"](root, press, motion, release)
    root.mainloop()
    root.destroy()
    return state["out"]


# --------------------------------------------------------------------------
# Step 2: follow the scrolling
# --------------------------------------------------------------------------

class Session:
    TICK = 90           # milliseconds between looks at the screen

    def __init__(self, box, hooks=None):
        import tkinter as tk
        self.tk = tk
        self.box = box
        self.w, self.h = box[2] - box[0], box[3] - box[1]
        self.st = Stitcher(self.w, self.h)
        self.mode = "place"              # place, autocap, capture, done
        self.placed_at = time.time()
        self.place_min = 2.0             # seconds before anything may start by itself
        self.last_frame = None
        self.count_win = None
        self.auto = {}                   # working values of the automatic scrolling
        self.hooks = hooks or {}
        self.result = None
        self.prev_data = None
        self.note = ""
        self.end_at = None
        self.log = ["box %dx%d" % (self.w, self.h)]
        self.t0 = time.time()

        self.root = tk.Tk()
        self.root.title("VitePDF Scroll Capture")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#202124")
        _layered(self.root, 0.97)
        self._build_bar()
        self.frame_parts = self._build_frame()
        self.line = self._build_line()
        self.marks = self._build_marks()
        self.root.update()

        # Our own windows must not end up in the pictures.
        self.hidden_ok = all([hide_from_capture(self.root), hide_from_capture(self.line)])
        for win in [self.line] + self.marks + self.frame_parts:
            if win is self.end_tag and self.hidden_ok:
                # The END label can be dragged up, but only when Windows keeps it out of the
                # pictures: then it may sit inside the box without being captured.
                hide_from_capture(win)
                no_focus(win)
                self.end_label.configure(text="END OF CAPTURE  \u2195 drag", cursor="sb_v_double_arrow")
                for wdg in (win, self.end_label):
                    wdg.bind("<ButtonPress-1>", self._end_grab)
                    wdg.bind("<B1-Motion>", self._end_move)
                continue
            pass_clicks(win)
            hide_from_capture(win)
        no_focus(self.root)
        self.line_safe = self.hidden_ok and self._check_hidden()
        self._build_count()
        self.log.append("windows left out of pictures: %s, line inside box: %s"
                        % (self.hidden_ok, self.line_safe))
        # The moving line and side marks of earlier versions are gone: one marker only, the END line.
        self.line.withdraw()
        for m in self.marks:
            m.withdraw()
        self._place_bar()

    # -- small windows
    def _build_bar(self):
        tk = self.tk
        r = self.root
        r.configure(highlightthickness=1, highlightbackground="#3C4043", highlightcolor="#3C4043")
        tk.Frame(r, bg=RED, width=5).pack(side="left", fill="y")          # the red edge of the bar
        grip = tk.Label(r, text="\u22ee\u22ee", fg="#9AA0A6", bg="#202124", font=(FONT, 12, "bold"), cursor="fleur")
        grip.pack(side="left", padx=(8, 0), pady=8)
        col = tk.Frame(r, bg="#202124", cursor="fleur")
        col.pack(side="left", padx=(10, 12), pady=(7, 8))
        name = tk.Label(col, text="VITEPDF SCROLL", fg="#F28B82", bg="#202124", font=(FONT, 8, "bold"),
                        anchor="w", cursor="fleur")
        name.pack(fill="x")
        self.status = tk.Label(col, text="Starting", fg="#FFFFFF", bg="#202124", font=(FONT, 10),
                               anchor="w", justify="left", width=50, wraplength=390, cursor="fleur")
        self.status.pack(fill="x")
        self.btn_main = tk.Button(r, text="Scroll by hand", command=self.manual, bg=RED, fg="#FFFFFF", relief="flat",
                                  bd=0, activebackground="#B3262A", activeforeground="#FFFFFF",
                                  font=(FONT, 10, "bold"), padx=18, pady=7, cursor="hand2")
        self.btn_main.pack(side="left", padx=(0, 8), pady=10)
        self.btn_other = tk.Button(r, text="Cancel", command=self.cancel, bg="#303134", fg="#E8EAED",
                                   relief="flat", bd=0, activebackground="#5F6368", activeforeground="#FFFFFF",
                                   font=(FONT, 10), padx=14, pady=7, cursor="hand2")
        self.btn_other.pack(side="left", padx=(0, 12), pady=10)
        # The bar can be dragged out of the way by its left part or its text.
        for wdg in (grip, col, name, self.status):
            wdg.bind("<ButtonPress-1>", self._drag_start)
            wdg.bind("<B1-Motion>", self._drag_move)

    def _build_count(self):
        """A large countdown in the middle of the box. Windows keeps it out of the pictures."""
        try:
            tk = self.tk
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#174EA6")
            first = 2 if self.mode != "place" else max(1, int(round(self.place_min)))
            self.count_num = tk.Label(win, text=str(first), fg="#FFFFFF", bg="#174EA6",
                                      font=(FONT, 40, "bold"))
            self.count_num.pack(padx=30, pady=(10, 0))
            self.count_txt = tk.Label(win, text="Move the mouse pointer into this box", fg="#FFFFFF",
                                      bg="#174EA6", font=(FONT, 11))
            self.count_txt.pack(padx=22, pady=(0, 14))
            win.update_idletasks()
            w, h = win.winfo_reqwidth(), win.winfo_reqheight()
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            l, t, r, b = self.box
            inside = self.hidden_ok and w + 20 <= self.w and h + 20 <= self.h
            if inside:
                x, y = l + (self.w - w) // 2, t + (self.h - h) // 2
            else:
                # The box is too small for it (or it cannot be kept out of the pictures):
                # show it beside the box instead, where it is always visible.
                self.count_txt.configure(text="Move the mouse pointer into the red box")
                win.update_idletasks()
                w, h = win.winfo_reqwidth(), win.winfo_reqheight()
                x = max(0, min(sw - w, l + (self.w - w) // 2))
                if t - h - 12 >= 0:
                    y = t - h - 12                       # above the box
                elif r + 12 + w <= sw:
                    x, y = r + 12, max(0, min(sh - h, t))
                elif l - 12 - w >= 0:
                    x, y = l - 12 - w, max(0, min(sh - h, t))
                else:
                    win.destroy()                        # no room anywhere: the bar shows the count
                    return
            win.geometry("+%d+%d" % (x, y))
            win.update()
            hide_from_capture(win)
            pass_clicks(win)
            self.count_win = win
        except Exception:
            self.count_win = None

    def _count(self, text):
        """Show a number in the countdown window, or take the window away (None)."""
        win = self.count_win
        if win is None:
            return
        try:
            if text is None:
                win.destroy()
                self.count_win = None
            else:
                self.count_num.configure(text=text)
        except Exception:
            self.count_win = None

    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        dx, dy = getattr(self, "_drag", (0, 0))
        x, y = max(0, e.x_root - dx), max(0, e.y_root - dy)
        self.root.geometry("+%d+%d" % (x, y))
        l, t, r, b = self.box
        bw, bh = self.root.winfo_width(), self.root.winfo_height()
        self.bar_inside = (l < x + bw and x < r and t < y + bh and y < b)

    def _thin(self, color):
        t = self.tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=color)
        _layered(t, 0.92)
        return t

    def _build_frame(self):
        l, t, r, b = self.box
        parts = []
        # A red box just outside the captured area. Its bottom edge is thicker: the END line.
        for (x, y, w, h) in ((l - 2, t - 2, self.w + 4, 2), (l - 2, b, self.w + 4, 5),
                             (l - 2, t, 2, self.h), (r, t, 2, self.h)):
            win = self._thin(RED)
            win.geometry("%dx%d+%d+%d" % (w, h, x, y))
            parts.append(win)
        tag = self.tk.Toplevel(self.root)
        tag.overrideredirect(True)
        tag.attributes("-topmost", True)
        tag.configure(bg=RED)
        self.end_label = self.tk.Label(tag, text="END OF CAPTURE", fg="#FFFFFF", bg=RED,
                                       font=(FONT, 8, "bold"))
        self.end_label.pack(padx=6, pady=1)
        tag.update_idletasks()
        self.end_tag, self.end_bar = tag, parts[1]
        self.end_tag_x = max(l, r - tag.winfo_reqwidth())
        tag.geometry("+%d+%d" % (self.end_tag_x, b + 5))
        self.end_y = b                    # screen row of the END line; the box bottom unless dragged up
        self.end_drag = False
        parts.append(tag)
        return parts

    def _end_grab(self, e):
        self._end_off = e.y_root - self.end_y

    def _end_move(self, e):
        self.set_end_y(e.y_root - getattr(self, "_end_off", 0))

    def set_end_y(self, y):
        """Move the END line up inside the box (or back down to its bottom edge). The capture
        then ends at that line, and nothing more is added to the picture."""
        if self.mode not in ("place", "autocap", "capture") or not self.st.rows:
            return
        l, t, r, b = self.box
        y = int(max(t + 30, min(b, y)))
        if y >= b - 3:
            y = b
        if self.mode in ("place", "autocap"):
            self.manual("the END line was moved")
        self.end_y = y
        self.end_drag = y < b
        self.st.frozen = self.end_drag
        try:
            self.end_bar.geometry("%dx5+%d+%d" % (self.w + 4, l - 2, y))
            self.end_tag.geometry("+%d+%d" % (self.end_tag_x, y + 5))
        except Exception:
            pass
        self.note = ""

    def _build_line(self):
        win = self._thin(RED)
        win.geometry("%dx3+%d+%d" % (self.w, self.box[0], self.box[3] - 3))
        return win

    def _build_marks(self):
        """Two red tabs just outside the box, at the height of the line. They
        are outside the pictures by position, whatever Windows supports."""
        out = []
        for _side in (0, 1):
            win = self._thin(RED)
            win.geometry("12x5+0+0")
            out.append(win)
        return out

    def _place_bar(self):
        self.root.update_idletasks()
        bw, bh = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        l, t, r, b = self.box
        if b + 32 + bh <= sh - 48:
            x, y = l, b + 32                     # below the END line and its label
        elif t - 8 - bh >= 0:
            x, y = l, t - 8 - bh
        elif r + 8 + bw <= sw:
            x, y = r + 8, t
        elif l - 8 - bw >= 0:
            x, y = l - 8 - bw, t
        else:
            x, y = max(0, r - bw - 8), max(0, b - bh - 8)       # inside: only safe when hidden
            if not self.hidden_ok:
                self.note = "Make the box a little smaller so this bar fits outside it."
        self.root.geometry("+%d+%d" % (max(0, min(x, sw - bw)), max(0, y)))
        self.bar_inside = (l < x + bw and x < r and t < y + bh and y < b)

    def _check_hidden(self):
        """Show the line and take a picture. If the picture has the line's own
        red across the box at that place, Windows did not hide it and the
        line must stay outside. Tried a few times, since hiding can lag."""
        want = bytes(int(RED[k:k + 2], 16) for k in (1, 3, 5))
        y = self.h // 2
        ok = False
        try:
            self.line.geometry("%dx3+%d+%d" % (self.w, self.box[0], self.box[1] + y))
            self.line.deiconify()
            for _ in range(4):
                self.root.update()
                time.sleep(0.15)
                row = grab((self.box[0], self.box[1] + y + 1, self.box[2], self.box[1] + y + 2)).tobytes()
                reds = sum(1 for k in range(0, len(row), 3) if row[k:k + 3] == want)
                if reds * 3 < len(row) * 0.5:          # less than half the row is the line's red
                    ok = True
                    break
        except Exception:
            ok = False
        return ok

    # -- the loop
    def run(self):
        self.root.after(250, self.tick)
        if self.hooks.get("session"):
            self.hooks["session"](self)
        self.root.mainloop()
        try:
            self.root.after_cancel(getattr(self, "_after", ""))
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        return self.result

    def tick(self):
        state = "start"
        try:
            im = grab(self.box)
            data = im.tobytes()
            stable = data == self.prev_data
            self.prev_data = data
            frame = split_rows(data, self.w, self.h)
            if stable:
                self.last_frame = frame
            if not self.st.rows:
                if stable:
                    self.st.feed(frame, True)
            else:
                state = self.st.feed(frame, stable)
            if self.mode == "place":
                self._place()
            elif self.mode == "autocap":
                self._autocap(data, stable)
            if self.result is None and self.mode != "done":
                self._show(state)
        except Exception as e:
            self.log.append("tick error: %r" % (e,))
        if self.mode == "done":
            return
        self._after = self.root.after(self.TICK, self.tick)

    # -- start: wait for the pointer, then scroll and capture by itself
    def _pointer(self):
        return (self.hooks.get("pointer") or pointer_pos)()

    def _place(self):
        waited = time.time() - self.placed_at
        left = max(1, int(self.place_min - waited + 0.999))        # 2, 1 for a wait of two seconds
        self._count(str(left) if waited < self.place_min else "\u2193")
        p = self._pointer()
        if self.st.rows and (self.st.pos != 0 or self.st.lost or self.st.total() > self.h):
            return self.manual("you scrolled by hand")
        if self.st.rows and waited >= self.place_min and self._in_box(p) and not self._on_bar(p):
            self._count(None)
            self.auto = {"t0": time.time(), "home": p, "next": time.time() + 0.2, "px120": 100.0,
                         "step": "move", "down": 0, "lost": 0, "moves": 0}
            self.mode = "autocap"
            self.btn_main.configure(text="Finish", command=self.finish)
            self.log.append("automatic capture started")

    # -- setting the end before the capture starts
    def _on_bar(self, p):
        """Is the pointer on the dark bar or on the END label? A wheel turn there would not reach the page."""
        try:
            for win in (self.root, self.end_tag):
                x, y = win.winfo_x(), win.winfo_y()
                if x <= p[0] < x + win.winfo_width() and y <= p[1] < y + win.winfo_height():
                    return True
        except Exception:
            pass
        return False

    def manual(self, why="chosen"):
        """Go on by hand: the user scrolls, the tool only captures."""
        if self.mode not in ("place", "autocap"):
            return
        self._count(None)
        self.st.frozen = False
        self.st.expect = None
        self.log.append("capture by hand: %s" % why)
        paused = why not in ("chosen", "you scrolled by hand")
        self.note = ("Paused. Drag the red END line up to the last line you want, or scroll by hand. "
                     "Then press Finish.") if paused else ""
        self.note_until = time.time() + 8
        self.mode = "capture"
        self.btn_main.configure(text="Finish", command=self.finish)

    def _autocap(self, data, stable):
        a, st, now = self.auto, self.st, time.time()
        p = self._pointer()
        if (self.hooks.get("esc") or esc_pressed)():
            return self.manual("Esc was pressed")
        if not self._in_box(p) or abs(p[0] - a["home"][0]) > 12 or abs(p[1] - a["home"][1]) > 12:
            return self.manual("the mouse was moved")
        if now - a["t0"] > 600:
            return self.manual("it took too long")
        usable = self.h - st.bottom_skip
        if st.lost:
            # went further than one box in a step: come back up a little until the place is found
            a["lost"] += 1
            if a["lost"] > 120:
                return self.manual("the place on the page was lost")
            if stable and now >= a["next"]:
                self._wheel(+36)
                a["next"] = now + 0.35
                a["px120"] = min(400.0, a["px120"] * 1.15)      # one wheel turn moves more than assumed
            return
        a["lost"] = 0
        if not stable or now < a["next"]:
            return
        if a["step"] == "move":
            if st.full:
                return self.finish()
            want = max(40, int(0.5 * usable))
            delta = 120 if a["moves"] == 0 else max(24, int(120.0 * want / a["px120"]))
            a["from"], a["last"] = st.pos, delta
            a["moves"] += 1
            st.expect = st.pos + int(delta * a["px120"] / 120.0)
            self._wheel(-delta)
            a["next"] = now + 0.3
            a["step"] = "settle"
            return
        if a["step"] == "settle":
            moved = st.pos - a["from"]
            if moved <= 1:
                a["down"] += 1
                if a["down"] >= 3:
                    self.log.append("automatic capture: the page does not scroll further")
                    return self.finish()
                a["step"] = "move"
                return
            a["down"] = 0
            st.expect = None
            a["px120"] = max(20.0, min(400.0, moved * 120.0 / a["last"]))
            a["step"] = "move"

    def _in_box(self, p):
        return p is not None and self.box[0] <= p[0] < self.box[2] and self.box[1] <= p[1] < self.box[3]

    def _wheel(self, delta):
        self.auto["wheels"] = self.auto.get("wheels", 0) + 1
        fn = self.hooks.get("wheel") or send_wheel
        fn(delta)

    def _show(self, state):
        st = self.st
        total = st.total()
        pages = total / float(rows_per_page(self.w)) if total else 0
        if state == "lost":
            text = "Scrolled too far. Scroll back up until the red mark shows again."
        elif st.full:
            text = "Maximum length reached. Press Finish."
        elif st.bottom_skip:
            text = "A fixed bar at the bottom of the box is left out.  %d px, %.1f pages" % (total, pages)
        elif self.end_drag:
            text = ("The capture will end at the red END line where you put it. Press Finish. "
                    "Drag the line again to adjust.")
        elif total and st.view_end() < total - 2:
            text = "You scrolled back up. The capture will end at the red END line. Press Finish when it is right."
        elif total and self.w < 1000 and total < self.h + 4:
            text = "Tip: for sharper text, cancel, zoom the browser to 150%, and start again."
        else:
            text = ("Everything above the red END line is captured: %.1f pages. To end earlier, drag the "
                    "END line up to the last line you want. Then press Finish." % pages)
        if self.mode == "capture" and total and total < self.h + 4 and not st.bottom_skip:
            text = ("Scroll down. Everything that passes above the red END line is captured. "
                    "Press Finish when the last line you want sits just above it.")
        if self.mode == "place":
            gone = time.time() - self.placed_at
            left = max(1, int(self.place_min - gone + 0.999))
            lead = "Starting in %d.  " % left if gone < self.place_min else ""
            text = (lead + "Keep the pointer inside the red box, hands off: the page scrolls by itself. "
                    "Or simply scroll by hand. The capture ends at the red END line.")
        elif self.mode == "autocap":
            text = ("Capturing by itself: %.1f pages. Touch the mouse to take over and set the end. "
                    "The capture ends at the red END line." % pages)
        if self.note and time.time() < getattr(self, "note_until", 1e18):
            text = self.note
        if self.mode not in ("capture", "autocap"):
            state = "tracked"
        self.status.configure(text=text, fg="#FFB4AB" if state == "lost" else "#FFFFFF")
        # one marker: the red box, whose bottom edge is the END line (amber when the place is lost)
        color = "#F9AB00" if state == "lost" else RED
        if color != getattr(self, "_frame_color", RED):
            self._frame_color = color
            for win in self.frame_parts:
                try:
                    win.configure(bg=color)
                except Exception:
                    pass
            try:
                self.end_label.configure(bg=color)
            except Exception:
                pass

    def _end_at_line(self):
        """The strip row at the red END line. Rows at the bottom of the box that looked like a
        fixed bar were kept out of the picture while scrolling; in the last view they are what
        the user sees just above the END line, so they belong to the capture."""
        st = self.st
        if st.lost or not st.rows:
            return st.view_end()
        if self.end_drag:
            self.log.append("END line dragged up by %d rows" % (self.box[3] - self.end_y))
            return max(0, min(st.total(), st.pos + (self.end_y - self.box[1])))
        skip = st.bottom_skip
        if skip and self.last_frame is not None and st.pos + self.h - skip == st.total():
            for row in self.last_frame[self.h - skip:]:
                st._add(row)
            self.log.append("the last %d rows above the END line were added" % skip)
        return max(0, min(st.total(), st.pos + self.h))

    def bar_inside_now(self):
        return bool(getattr(self, "bar_inside", False))

    def finish(self):
        """Finish was pressed: the picture is complete."""
        if self.mode not in ("capture", "autocap", "place"):
            return
        self._count(None)
        self.note = ""
        self.st.frozen = True
        self.end_at = self._end_at_line()
        self._finish_now()

    def _finish_now(self):
        self._count(None)
        self.mode = "done"
        self.log.append("finish after %.1f s" % (time.time() - self.t0))
        if self.end_at is None:
            self.end_at = self.st.view_end()
        self.log.append("view ended at row %d of %d" % (self.end_at, self.st.total()))
        self.result = self.st
        self.root.quit()

    def cancel(self):
        self._count(None)
        self.mode = "done"
        self.result = None
        self.root.quit()


# --------------------------------------------------------------------------
# Step 3: trim and save
# --------------------------------------------------------------------------

def trim_window(st, hooks=None, end_at=None):
    """Preview with a top and a bottom handle and the page breaks.
    -> {"start", "end", "long"} or None"""
    import tkinter as tk
    from PIL import Image, ImageTk
    w, total = st.width, st.total()
    strip = Image.frombytes("RGB", (w, total), b"".join(st.rows))
    view_w = min(620, w)
    k = view_w / float(w)
    view_h = max(1, int(total * k))
    small = strip.resize((view_w, view_h), Image.LANCZOS)

    root = tk.Tk()
    root.title("VitePDF Scroll Capture: trim and save")
    root.configure(bg="#F3F3F3")
    sh = root.winfo_screenheight()
    win_h = min(sh - 140, max(420, view_h + 150))
    root.geometry("%dx%d+%d+%d" % (view_w + 60, win_h, 80, 40))
    root.attributes("-topmost", True)
    head = tk.Frame(root, bg="#F3F3F3")
    head.pack(fill="x", padx=16, pady=(12, 0))
    count = tk.Label(head, text="", bg="#174EA6", fg="#FFFFFF", font=(FONT, 11, "bold"), padx=12, pady=3)
    count.pack(side="right")
    tk.Label(head, text="Drag the red handles to the first and last line you want.",
             bg="#F3F3F3", fg="#1B1B1F", font=(FONT, 11, "bold"), anchor="w").pack(side="left")
    info = tk.Label(root, text="", bg="#F3F3F3", fg="#5C5F66", font=(FONT, 10), anchor="w",
                    justify="left", wraplength=view_w + 20)
    info.pack(fill="x", padx=16, pady=(2, 8))

    foot = tk.Frame(root, bg="#FAFAFA")
    foot.pack(side="bottom", fill="x")
    long_var = tk.BooleanVar(value=False)
    tk.Checkbutton(foot, text="One long page", variable=long_var, bg="#FAFAFA", font=(FONT, 10),
                   command=lambda: redraw()).pack(side="left", padx=14, pady=10)
    orient_var = tk.StringVar(value="Auto")
    tk.Label(foot, text="Page:", bg="#FAFAFA", font=(FONT, 10)).pack(side="left", padx=(6, 2))
    om = tk.OptionMenu(foot, orient_var, "Auto", "Portrait", "Landscape", command=lambda _v: redraw())
    om.configure(bg="#FAFAFA", relief="flat", font=(FONT, 10), highlightthickness=0)
    om.pack(side="left", pady=10)
    out = {"v": None}

    body = tk.Frame(root, bg="#F3F3F3")
    body.pack(fill="both", expand=True, padx=16)
    sb = tk.Scrollbar(body, orient="vertical")
    sb.pack(side="right", fill="y")
    cv = tk.Canvas(body, bg="#D0D0D0", highlightthickness=0, yscrollcommand=sb.set,
                   scrollregion=(0, 0, view_w, view_h + 20), width=view_w)
    cv.pack(side="left", fill="both", expand=True)
    sb.config(command=cv.yview)
    photo = ImageTk.PhotoImage(small)
    cv.create_image(0, 10, image=photo, anchor="nw")
    end0 = total if end_at is None else max(40, min(total, end_at))
    cut = {"a": 0, "b": end0, "drag": None}          # exactly where the END line was

    def redraw():
        cv.delete("ov")
        page = page_size(w, orient_var.get())
        per_page = rows_per_page(w, page=page)
        ya, yb = 10 + cut["a"] * k, 10 + cut["b"] * k
        cv.create_rectangle(0, 10, view_w, ya, fill="#000000", stipple="gray50", outline="", tags="ov")
        cv.create_rectangle(0, yb, view_w, view_h + 10, fill="#000000", stipple="gray50", outline="", tags="ov")
        pages, hard = paginate(st.blank, cut["a"], cut["b"], per_page, rows=st.rows)
        if not long_var.get():
            for (_a, b) in pages[:-1]:
                y = 10 + b * k
                cv.create_line(0, y, view_w, y, fill="#1A73E8", dash=(6, 4), tags="ov")
            for i, (a, _b) in enumerate(pages):
                y = 10 + a * k + 14                      # a small label at the top of each page
                cv.create_rectangle(4, y - 9, 66, y + 9, fill="#1A73E8", outline="", tags="ov")
                cv.create_text(35, y, text="Page %d" % (i + 1), fill="#FFFFFF", font=(FONT, 9, "bold"), tags="ov")
        for name, y in (("a", ya), ("b", yb)):
            cv.create_line(0, y, view_w, y, fill=RED, width=3, tags="ov")
            cv.create_rectangle(view_w - 64, y - 9, view_w, y + 9, fill=RED, outline="", tags="ov")
            cv.create_text(view_w - 32, y, text="start" if name == "a" else "end", fill="#FFFFFF",
                           font=(FONT, 9, "bold"), tags="ov")
        n = 1 if long_var.get() else len(pages)
        count.configure(text="1 long page" if long_var.get() else "%d page%s" % (n, "" if n == 1 else "s"))
        text = "%s, A4. Blue lines show where each page ends." % ("Landscape" if page[0] > page[1] else "Portrait")
        if long_var.get():
            text = "Everything on one long page."
        if hard and not long_var.get():
            text += "  Page %s had no gap to cut at." % ", ".join(str(h) for h in hard)
        info.configure(text=text)

    def row_at(e):
        return int(round((cv.canvasy(e.y) - 10) / k))

    def press(e):
        r = row_at(e)
        da, db = abs(r - cut["a"]), abs(r - cut["b"])
        if min(da, db) * k <= 14:
            cut["drag"] = "a" if da <= db else "b"

    def motion(e):
        if not cut["drag"]:
            return
        r = max(0, min(total, row_at(e)))
        if cut["drag"] == "a":
            cut["a"] = min(r, cut["b"] - 40)
        else:
            cut["b"] = max(r, cut["a"] + 40)
        redraw()

    cv.bind("<ButtonPress-1>", press)
    cv.bind("<B1-Motion>", motion)
    def release(_e):
        which = cut["drag"]
        cut["drag"] = None
        if which:                                # settle on the nearest gap between lines
            r = st.snap(cut[which])
            if which == "a":
                cut["a"] = max(0, min(r, cut["b"] - 40))
            else:
                cut["b"] = min(total, max(r, cut["a"] + 40))
            redraw()

    cv.bind("<ButtonRelease-1>", release)
    cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))

    def save():
        out["v"] = {"start": cut["a"], "end": cut["b"], "long": bool(long_var.get()), "strip": strip,
                    "orient": orient_var.get().lower()}
        root.quit()

    tk.Button(foot, text="Save PDF", command=save, bg="#B3262A", fg="#FFFFFF", relief="flat",
              font=(FONT, 10, "bold"), padx=18, pady=5, cursor="hand2").pack(side="right", padx=14, pady=10)
    tk.Button(foot, text="Cancel", command=root.quit, relief="flat", bg="#E4E4E7", font=(FONT, 10),
              padx=14, pady=5, cursor="hand2").pack(side="right", pady=10)
    redraw()
    if cut["b"] < total:
        # Open the preview where the capture ends, so the end is easy to check.
        root.update_idletasks()
        cv.yview_moveto(max(0.0, (10 + cut["b"] * k - cv.winfo_height() * 0.7) / float(view_h + 20)))
        info.configure(text=info.cget("text") + "  The end is set to where you stopped; "
                                               "drag it down to keep more.")
    _icon(root)
    if hooks and hooks.get("trim"):
        hooks["trim"](root, cut, redraw, save)
    root.protocol("WM_DELETE_WINDOW", root.quit)       # the X closes like Cancel
    root.mainloop()
    try:
        root.destroy()
    except Exception:
        pass
    return out["v"]


def _icon(root):
    try:
        ico = Path(__file__).resolve().parent / "vitepdf_scroll.ico"
        if os.name == "nt" and ico.is_file():
            root.iconbitmap(str(ico))
    except Exception:
        pass


def run(folder, hooks=None):
    """The whole flow: choose the area, capture while the page scrolls, trim, save.
    -> (path of the saved PDF or None, [numbers for the log])"""
    import vp_core as core
    dpi_aware()
    box = choose_area(hooks)
    if not box:
        return None, []
    time.sleep(0.25)
    session = Session(box, hooks)
    st = session.run()
    if st is None or st.total() < 20:
        return None, session.log
    choice = trim_window(st, hooks, session.end_at)
    if not choice:
        return None, session.log
    a, b = choice["start"], choice["end"]
    page = page_size(st.width, choice.get("orient", "auto"))
    per_page = rows_per_page(st.width, page=page)
    pages, hard = paginate(st.blank, a, b, per_page, rows=st.rows)
    while len(pages) > 1 and all(st.blank[r] for r in range(pages[-1][0], pages[-1][1])):
        pages.pop()                              # nothing but empty space: no page for it
    long_page = choice["long"]
    if long_page and (b - a) * (page[0] - 2 * MARGIN) / st.width + 2 * MARGIN > 14000:
        long_page = False
    pdf = build_pdf(choice["strip"], pages, long_page, page=page)
    # A plain name; a second capture in the same folder becomes "vitepdf-scroll (2).pdf".
    out = core.write_file(Path(folder) / "vitepdf-scroll.pdf", pdf)
    s = st.stats
    notes = session.log + [
        "strip %d x %d, kept rows %d to %d" % (st.width, st.total(), a, b),
        "pages %d %s, breaks through content on pages: %s" % (
            len(pages), "landscape" if page[0] > page[1] else "portrait", hard or "none"),
        "pictures %d, rows added %d, lost %d, found again %d" % (
            s["frames"], s["appended"], s["lost"], s["resynced"]),
        "fixed rows at top %d, at bottom %d, pdf %.1f KB" % (st.top_static, st.bottom_skip, len(pdf) / 1024.0),
    ]
    return out, notes
