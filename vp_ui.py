# -*- coding: utf-8 -*-
"""
VitePDF windows: one clean look for every dialog.

Built with tkinter and customtkinter. Each function opens one window, waits
for the user and returns the answer (or None when the user cancels).

Created by Atanu Sarkar. Made with Claude.
"""

import gc
import os
import sys
import threading
import traceback
from pathlib import Path

import vp_core as core

BG, CARD, FOOT = "#F3F3F3", "#FFFFFF", "#FAFAFA"
LINE, TEXT, MUTED = "#E5E5E5", "#1B1B1B", "#5C5C5C"
ACCENT, ACCENT_DARK, TINT = "#B3262A", "#8F1D21", "#FBEDED"
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"

_ctk = None


def ctk():
    """customtkinter, loaded on first use (keeps one-click jobs fast)."""
    global _ctk
    if _ctk is None:
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass
        import customtkinter
        customtkinter.set_appearance_mode("light")
        _ctk = customtkinter
    return _ctk


def font(size=13, bold=False):
    return ctk().CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


def _icon_path():
    p = Path(__file__).resolve().parent / "vitepdf.ico"
    return p if p.exists() else None


def _logo():
    """The logo as a picture (the PNG copy: the icon format is not read on purpose)."""
    try:
        p = Path(__file__).resolve().parent / "vitepdf.png"
        im = core._pil().open(p)
        im.load()
        return im.convert("RGBA")
    except Exception:
        return None


# Automated tests attach observers here, from inside the test process. The
# application itself never fills this in and reads no setting that could: it
# holds no screenshot code and no automatic "accept".
HOOKS = {}


def _hook(name, **parts):
    fn = HOOKS.get(name)
    if fn:
        fn(**parts)


def _sharp_icon(root, ico):
    """Give Windows the icon in the exact sizes this screen needs. The simple
    way hands over one small picture, which Windows then stretches (blurry on
    a display scaled to 125 or 150 percent)."""
    try:
        import ctypes
        user = ctypes.windll.user32
        user.GetParent.restype = ctypes.c_void_p
        user.GetParent.argtypes = [ctypes.c_void_p]
        user.LoadImageW.restype = ctypes.c_void_p
        user.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_uint]
        user.SendMessageW.restype = ctypes.c_void_p
        user.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        hwnd = user.GetParent(root.winfo_id()) or root.winfo_id()
        try:
            user.GetDpiForWindow.argtypes = [ctypes.c_void_p]
            dpi = user.GetDpiForWindow(hwnd) or 96
        except Exception:
            dpi = 96
        # big: taskbar and Alt+Tab (shown at half of this, an exact step); small: title bar
        for which, base in ((1, 48), (0, 16)):
            size = int(round(base * dpi / 96.0))
            handle = user.LoadImageW(None, str(ico), 1, size, size, 0x0010)
            if handle:
                user.SendMessageW(hwnd, 0x0080, which, handle)
    except Exception:
        pass


class Window:
    """A dialog: heading, body, and a footer with buttons on the right."""

    def __init__(self, title, width, height, heading=None, sub=None, name="window"):
        c = ctk()
        self.name = name
        self.result = None
        self.root = root = c.CTk(fg_color=BG)
        root.title(title)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry("%dx%d+%d+%d" % (width, height, max(0, (sw - width) // 2),
                                       max(0, (sh - height) // 3)))
        root.resizable(False, False)
        ico = _icon_path()
        if ico and os.name == "nt":
            try:
                root.iconbitmap(str(ico))
            except Exception:
                pass
            root.after(350, lambda: _sharp_icon(root, ico))
        self.foot = c.CTkFrame(root, fg_color=FOOT, height=68, corner_radius=0,
                               border_width=0)
        self.foot.pack(side="bottom", fill="x")
        self.foot.pack_propagate(False)
        c.CTkFrame(root, fg_color=LINE, height=1, corner_radius=0).pack(side="bottom", fill="x")
        self.body = c.CTkFrame(root, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=24, pady=(18, 12))
        if heading:
            c.CTkLabel(self.body, text=heading, font=font(20, True), text_color=TEXT,
                       anchor="w").pack(fill="x")
        if sub:
            c.CTkLabel(self.body, text=sub, font=font(13), text_color=MUTED, anchor="w",
                       justify="left", wraplength=width - 48).pack(fill="x", pady=(2, 0))
        root.protocol("WM_DELETE_WINDOW", self.cancel)
        root.bind("<Escape>", lambda e: self.cancel())

    # -- building blocks ---------------------------------------------------

    def button(self, text, command, primary=False, parent=None, width=96, side="right"):
        c = ctk()
        if primary:
            b = c.CTkButton(parent or self.foot, text=text, command=command, width=max(width, 112),
                            height=38, corner_radius=6, font=font(13, True), fg_color=ACCENT,
                            hover_color=ACCENT_DARK, text_color="#FFFFFF")
        else:
            b = c.CTkButton(parent or self.foot, text=text, command=command, width=width,
                            height=38, corner_radius=6, font=font(13), fg_color=CARD,
                            hover_color="#F0F0F0", text_color=TEXT, border_width=1,
                            border_color="#D1D1D1")
        if parent is None:
            b.pack(side=side, padx=(0, 24) if not self.foot.pack_slaves()[:-1] and side == "right"
                   else (0, 10), pady=15)
        return b

    def foot_text(self, text):
        lab = ctk().CTkLabel(self.foot, text=text, font=font(12), text_color=MUTED, anchor="w",
                             justify="left")
        lab.pack(side="left", padx=24)
        return lab

    def card(self, parent=None, **pack):
        f = ctk().CTkFrame(parent or self.body, fg_color=CARD, corner_radius=8, border_width=1,
                           border_color=LINE)
        f.pack(**(pack or {"fill": "x", "pady": (14, 0)}))
        return f

    def label(self, parent, text, muted=False, bold=False, size=13, **pack):
        lab = ctk().CTkLabel(parent, text=text, font=font(size, bold), anchor="w", justify="left",
                             text_color=MUTED if muted else TEXT)
        lab.pack(**(pack or {"fill": "x"}))
        return lab

    def entry(self, parent, value="", width=140, show=None):
        e = ctk().CTkEntry(parent, width=width, height=38, corner_radius=6, font=font(14),
                           fg_color=CARD, border_color="#C4C4C4", border_width=1,
                           text_color=TEXT, show=show)
        if value != "":
            e.insert(0, str(value))
        return e

    def check(self, parent, text, value=False):
        c = ctk()
        var = c.BooleanVar(value=value)
        box = c.CTkCheckBox(parent, text=text, variable=var, font=font(13), text_color=TEXT,
                            fg_color=ACCENT, hover_color=ACCENT_DARK, border_color="#8A8A8A",
                            checkbox_width=20, checkbox_height=20, corner_radius=4,
                            border_width=2)
        return box, var

    def radio(self, parent, text, var, value):
        return ctk().CTkRadioButton(parent, text=text, variable=var, value=value, font=font(13),
                                    text_color=TEXT, fg_color=ACCENT, hover_color=ACCENT_DARK,
                                    border_color="#8A8A8A", radiobutton_width=20,
                                    radiobutton_height=20)

    def segmented(self, parent, values, value):
        """A row of radio buttons for a small either-or choice. -> (row, variable)"""
        c = ctk()
        var = c.StringVar(value=value)
        row = c.CTkFrame(parent, fg_color="transparent")
        for v in values:
            self.radio(row, v, var, v).pack(side="left", padx=(0, 22))
        return row, var

    def chip(self, parent, text, command):
        return ctk().CTkButton(parent, text=text, command=command, height=30, width=20,
                               corner_radius=15, font=font(12), fg_color=CARD,
                               hover_color="#F0F0F0", text_color=TEXT, border_width=1,
                               border_color="#D1D1D1")

    def error(self, text):
        if not hasattr(self, "_err"):
            self._err = ctk().CTkLabel(self.foot, text="", font=font(12), text_color=ACCENT,
                                       anchor="w")
            self._err.pack(side="left", padx=24)
        self._err.configure(text=text)

    # -- life cycle --------------------------------------------------------

    def close(self, result=None):
        self.result = result
        try:
            self.root.quit()
        except Exception:
            pass

    def cancel(self):
        self.close(None)

    def run(self, auto=None):
        root = self.root
        try:
            root.lift()
            root.attributes("-topmost", True)
            root.after(500, lambda: root.attributes("-topmost", False))
            root.focus_force()
        except Exception:
            pass
        _hook("window", window=self, auto=auto)
        root.mainloop()
        try:
            root.withdraw()
            root.update()
            root.destroy()
        except Exception:
            pass
        # Window parts must be cleared away here, on the main thread. Left to
        # the automatic clean-up they could be released from a worker thread,
        # which makes the window system wait forever.
        gc.collect()
        return self.result


def _number(text, low, high, whole=False):
    try:
        v = float(str(text).strip().replace(",", "."))
    except ValueError:
        return None
    if not low <= v <= high:
        return None
    return int(round(v)) if whole else v


def _thumb(path, box=(40, 52)):
    """A small preview of a picture or of a PDF's first page."""
    try:
        Image = core._pil()
        if str(path).lower().endswith(".pdf"):
            import vp_ops as ops
            im = ops.render_page(ops.open_for_render(path), 0, dpi=24, max_side=160)
        else:
            from PIL import ImageOps
            im = Image.open(path)
            im.draft("RGB", (box[0] * 4, box[1] * 4))
            im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        im.thumbnail((box[0] * 2, box[1] * 2))
        return im
    except Exception:
        return None


# --------------------------------------------------------------------------
# Messages, About
# --------------------------------------------------------------------------

def _mark(parent, tone):
    """A round status mark drawn on a small canvas."""
    import tkinter as tk
    cv = tk.Canvas(parent, width=30, height=30, bg=BG, highlightthickness=0)
    if tone == "warn":
        cv.create_polygon(15, 2, 29, 27, 1, 27, fill="#F2B233", outline="#8A5A00")
        cv.create_line(15, 11, 15, 19, fill="#3D2800", width=2)
        cv.create_oval(14, 22, 16, 24, fill="#3D2800", outline="#3D2800")
    else:
        cv.create_oval(2, 2, 28, 28, fill="#0F5FA8", outline="#0F5FA8")
        if tone == "done":
            cv.create_line(9, 15, 13, 20, 21, 10, fill="#FFFFFF", width=2, capstyle="round")
        else:
            cv.create_line(15, 13, 15, 21, fill="#FFFFFF", width=2)
            cv.create_oval(14, 8, 16, 10, fill="#FFFFFF", outline="#FFFFFF")
    return cv


def message_window(title, text, tone="info", outputs=None, name="message", extra=None):
    """extra: (button text, function) for one more button on the left."""
    outputs = [Path(p) for p in (outputs or [])]
    lines = text.count("\n") + len(text) // 58 + 1
    win = Window(core.APP_NAME, 500, min(520, 190 + 19 * lines), name=name)
    row = ctk().CTkFrame(win.body, fg_color="transparent")
    row.pack(fill="both", expand=True)
    _mark(row, tone).pack(side="left", anchor="n", padx=(0, 14), pady=4)
    col = ctk().CTkFrame(row, fg_color="transparent")
    col.pack(side="left", fill="both", expand=True)
    ctk().CTkLabel(col, text=title, font=font(16, True), text_color=TEXT, anchor="w",
                   justify="left", wraplength=400).pack(fill="x")
    ctk().CTkLabel(col, text=text, font=font(13), text_color=MUTED, anchor="nw", justify="left",
                   wraplength=400).pack(fill="both", expand=True, pady=(6, 0))
    win.button("OK", lambda: win.close(True), primary=True)
    if outputs:
        def reveal():
            try:
                if len(outputs) == 1 and os.name == "nt":
                    import subprocess
                    import vp_shell
                    subprocess.Popen([vp_shell._system("explorer.exe"), "/select,", str(outputs[0])])
                elif os.name == "nt":
                    os.startfile(str(outputs[0].parent))
            except Exception:
                pass
            win.close(True)
        win.button("Open folder" if len(outputs) > 1 else "Show file", reveal, width=110)
    if extra:
        def other():
            win.close("extra")
        win.button(extra[0], other, side="left", width=130).pack_configure(padx=(24, 0))
    win.root.bind("<Return>", lambda e: win.close(True))
    got = win.run()
    if got == "extra" and extra:
        extra[1]()
    return got


def capture_folder_window(current=None, first=False):
    """Where captures made with the shortcut are saved.
    -> "downloads", "desktop", a folder path, or None."""
    c = ctk()
    win = Window(core.APP_NAME, 480, 320, "Where to save captures",
                 "Asked once. You can change it later from the \"Capture saved\" message."
                 if first else "Used for captures made with the shortcut or its keys.",
                 name="capfolder")
    start = current if current in ("downloads", "desktop") else ("other" if current else "downloads")
    var = c.StringVar(value=start)
    other = {"path": current if start == "other" else ""}
    win.radio(win.body, "Downloads folder", var, "downloads").pack(anchor="w", pady=(18, 0))
    win.radio(win.body, "Desktop", var, "desktop").pack(anchor="w", pady=(10, 0))
    row = c.CTkFrame(win.body, fg_color="transparent")
    row.pack(fill="x", pady=(10, 0))
    win.radio(row, "Another folder", var, "other").pack(side="left")
    shown = c.CTkLabel(win.body, text=other["path"], font=font(12), text_color=MUTED, anchor="w",
                       wraplength=420, justify="left")

    def browse():
        from tkinter import filedialog
        got = filedialog.askdirectory(parent=win.root, title="Folder for captures",
                                      initialdir=other["path"] or str(Path.home()))
        if got:
            other["path"] = str(Path(got))
            shown.configure(text=other["path"])
            var.set("other")

    win.button("Choose", browse, parent=row, width=80).pack(side="left", padx=(12, 0))
    shown.pack(fill="x", pady=(6, 0))

    def go():
        if var.get() == "other":
            if not other["path"] or not Path(other["path"]).is_dir():
                win.error("Choose a folder first")
                return
            win.close(other["path"])
        else:
            win.close(var.get())

    win.button("Save", go, primary=True)
    win.button("Cancel", win.cancel)
    win.root.bind("<Return>", lambda e: go())
    return win.run(auto=go)


def show_report(report):
    """Tell the user what needs telling. Silent when all went as asked."""
    if not report.lines:
        return
    text = "\n\n".join(report.lines[:8])
    if len(report.lines) > 8:
        text += "\n\n... and %d more." % (len(report.lines) - 8)
    if report.warn:
        title, tone = "Please check the result", "warn"
    elif report.outputs:
        title, tone = "Done, with a note", "info"
    else:
        title, tone = "Nothing to do", "info"
    message_window(title, text, tone, report.outputs)


def about_window():
    message_window("%s %s" % (core.APP_NAME, core.VERSION),
                   "Right-click image and PDF tools.\nRuns offline on this computer. Collects "
                   "nothing. Never changes your original files.\n\n%s\nFree to use and share "
                   "(MIT licence). No warranty." % core.CREDIT, "info", name="about")


# --------------------------------------------------------------------------
# Progress
# --------------------------------------------------------------------------

def run_job(fn, status, heading="Working"):
    """Run fn on a worker thread. A progress window appears if it takes long."""
    error = []

    def work():
        try:
            fn()
        except BaseException:
            error.append(traceback.format_exc())

    gc.collect()
    gc.disable()                  # no automatic clean-up on the worker thread (see Window.run)
    try:
        _run_job(work, status, heading)
    finally:
        gc.enable()
        gc.collect()
    if error:
        raise RuntimeError(error[0])


def _run_job(work, status, heading):
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(1.2)
    if t.is_alive():
        try:
            win = Window(core.APP_NAME, 460, 210, name="progress")
            head = ctk().CTkLabel(win.body, text=status.get("text", heading), font=font(17, True),
                                  text_color=TEXT, anchor="w")
            head.pack(fill="x")
            bar = ctk().CTkProgressBar(win.body, height=5, corner_radius=3, fg_color="#E3C4C5",
                                       progress_color=ACCENT, mode="indeterminate")
            bar.pack(fill="x", pady=(14, 10))
            bar.start()
            name = ctk().CTkLabel(win.body, text=status.get("name", ""), font=font(13),
                                  text_color=MUTED, anchor="w")
            name.pack(fill="x")

            def cancel():
                status["cancel"] = True
                head.configure(text="Stopping after this file")

            win.cancel = cancel
            win.root.protocol("WM_DELETE_WINDOW", cancel)
            win.button("Cancel", cancel)

            def poll():
                if t.is_alive():
                    if not status.get("cancel"):
                        head.configure(text=status.get("text", heading))
                    name.configure(text=status.get("name", ""))
                    win.root.after(120, poll)
                else:
                    win.close()

            win.root.after(120, poll)
            win.run(auto=lambda: None if t.is_alive() else win.close())
        except Exception:
            core.log("progress window failed:\n" + traceback.format_exc())
        t.join()


# --------------------------------------------------------------------------
# Merge: page order
# --------------------------------------------------------------------------

def order_window(files, summary="", sizes=None, size=None, caution=False):
    """Returns the files in the order the user chose, or None.
    With sizes [(key, label)] the result size is chosen here too:
    -> {"files": [...], "size": key}"""
    c = ctk()
    order = [Path(f) for f in files]
    sel = [0]
    win = Window(core.APP_NAME, 700, 600, "Merge into one PDF",
                 "Drag to set the page order. The top file becomes page 1.", name="order")
    listing = c.CTkScrollableFrame(win.body, fg_color=CARD, corner_radius=8, border_width=1,
                                   border_color=LINE)
    pick = None
    if sizes:
        line = c.CTkFrame(win.body, fg_color="transparent")
        line.pack(side="bottom", fill="x", pady=(12, 0))
        win.label(line, "Result size", bold=True, side="left")
        labels = [lab for _k, lab in sizes]
        start = dict(sizes).get(size) or labels[0]
        pick = c.StringVar(value=start)
        for lab in labels:
            win.radio(line, lab, pick, lab).pack(side="left", padx=(16, 0))
    if caution:
        note = c.CTkFrame(win.body, fg_color="#FFF4CE", corner_radius=6)
        note.pack(fill="x", pady=(12, 0))
        c.CTkLabel(note, text="These files arrived in two groups, so they may come from two selections. "
                              "Check the list and remove what does not belong.",
                   font=font(12), text_color="#5C4400", anchor="w", justify="left",
                   wraplength=620).pack(fill="x", padx=12, pady=8)
    listing.pack(fill="both", expand=True, pady=(14, 0))
    thumbs, rows = {}, []
    info = win.foot_text("")

    def result():
        if not sizes:
            return list(order)
        return {"files": list(order), "size": [k for k, lab in sizes if lab == pick.get()][0]}

    def size_text(f):
        try:
            return core.fmt_size(f.stat().st_size)
        except OSError:
            return ""

    def render():
        for r in rows:
            r.destroy()
        del rows[:]
        for i, f in enumerate(order):
            on = i == sel[0]
            row = c.CTkFrame(listing, fg_color=TINT if on else CARD, corner_radius=6, height=58)
            row.pack(fill="x", pady=1, padx=2)
            row.pack_propagate(False)
            parts = [row]
            parts.append(c.CTkLabel(row, text="::", width=18, font=font(13, True), text_color="#8A8A8A"))
            parts[-1].pack(side="left", padx=(8, 0))
            parts.append(c.CTkLabel(row, text=str(i + 1), width=28, font=font(13, on),
                                    text_color=TEXT if on else MUTED, anchor="e"))
            parts[-1].pack(side="left", padx=(2, 10))
            pic = thumbs.get(f)
            parts.append(c.CTkLabel(row, text="", width=40, height=50, image=pic, fg_color="#F3F3F3"
                                    if pic is None else "transparent", corner_radius=3))
            parts[-1].pack(side="left", padx=(0, 12))
            col = c.CTkFrame(row, fg_color="transparent")
            col.pack(side="left", fill="both", expand=True, pady=8)
            parts.append(col)
            parts.append(c.CTkLabel(col, text=f.name, font=font(13, on), text_color=TEXT, anchor="w"))
            parts[-1].pack(fill="x")
            parts.append(c.CTkLabel(col, text=size_text(f), font=font(11), text_color=MUTED,
                                    anchor="w", height=16))
            parts[-1].pack(fill="x")
            if on:
                for text, step in (("Remove", 0), ("Down", 1), ("Up", -1)):
                    b = win.button(text, (lambda s=step: move(s) if s else remove()), parent=row,
                                   width=58)
                    b.configure(height=32)
                    b.pack(side="right", padx=(0, 6))
            for p in parts:
                p.bind("<ButtonPress-1>", lambda e, k=i: press(k))
                p.bind("<B1-Motion>", drag)
            rows.append(row)
        folders = sorted({f.parent.name or str(f.parent) for f in order})
        where = folders[0] if len(folders) == 1 else "%d folders" % len(folders)
        info.configure(text="%d files from %s. %s" % (len(order), where, summary))

    def press(k):
        if k != sel[0]:
            sel[0] = k
            render()

    def drag(event):
        if not rows:
            return
        y = event.y_root - rows[0].winfo_rooty()
        k = max(0, min(len(order) - 1, int(y // 60)))
        if k != sel[0]:
            order.insert(k, order.pop(sel[0]))
            sel[0] = k
            render()

    def move(step):
        j = sel[0] + step
        if 0 <= j < len(order):
            order[sel[0]], order[j] = order[j], order[sel[0]]
            sel[0] = j
            render()

    def remove():
        if len(order) > 1:
            del order[sel[0]]
            sel[0] = min(sel[0], len(order) - 1)
            render()

    def by_name():
        current = order[sel[0]]
        order.sort(key=core.natural_key)
        sel[0] = order.index(current)
        render()

    def load_thumbs(todo):
        if not todo:
            return
        f = todo.pop(0)
        im = _thumb(f)
        if im is not None:
            thumbs[f] = c.CTkImage(light_image=im, size=(im.width // 2, im.height // 2))
            if f in order:
                render()
        win.root.after(10, lambda: load_thumbs(todo))

    win.button("Merge", lambda: win.close(result()), primary=True)
    win.button("Cancel", win.cancel)
    win.button("Sort by name", by_name, width=110)
    win.root.bind("<Return>", lambda e: win.close(result()))
    win.root.bind("<Alt-Up>", lambda e: move(-1))
    win.root.bind("<Alt-Down>", lambda e: move(1))
    render()
    win.root.after(60, lambda: load_thumbs(list(order)[:60]))
    return win.run(auto=lambda: win.close(result()))


# --------------------------------------------------------------------------
# More tools, simple choice
# --------------------------------------------------------------------------

IMAGE_TOOLS = [
    ("img-convert:png", "Convert to PNG", "A lossless copy", False),
    ("img-resize:x", "Resize photo", "Exact width and height, with an optional size limit", False),
    ("img-bw:x", "Black and white copy", "A grey copy", False),
    ("img-clean:x", "Remove hidden data", "Camera data, location, comments, attached scripts", False),
    ("img-repair:x", "Repair image", "Rebuilds a picture a website refuses to read", False),
]
PDF_TOOLS = [
    ("pdf-split:x", "Split into single pages", "One PDF per page", False),
    ("pdf-rotate:right", "Rotate all pages right", "", False),
    ("pdf-rotate:left", "Rotate all pages left", "", False),
    ("pdf-bw:x", "Black and white copy", "A grey copy", False),
    ("pdf-clean:x", "Remove hidden data", "Author data, scripts, attachments", False),
    ("pdf-repair:x", "Repair PDF", "Rebuilds a damaged PDF", False),
]


class Tip:
    """A small hint that appears next to a control while the mouse rests on it."""

    def __init__(self, widget, text):
        self.widget, self.text, self.top, self.job = widget, text, None, None
        widget.bind("<Enter>", self.enter, add="+")
        widget.bind("<Leave>", self.leave, add="+")
        widget.bind("<ButtonPress>", self.leave, add="+")

    def enter(self, _e=None):
        self.leave()
        self.job = self.widget.after(450, self.show)

    def show(self):
        import tkinter as tk
        self.job = None
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
            self.top = tk.Toplevel(self.widget)
            self.top.overrideredirect(True)
            self.top.attributes("-topmost", True)
            tk.Label(self.top, text=self.text, bg="#2B2B2B", fg="#FFFFFF", padx=8, pady=4,
                     font=(FONT, 9)).pack()
            self.top.geometry("+%d+%d" % (x, y))
        except Exception:
            self.top = None

    def leave(self, _e=None):
        if self.job:
            try:
                self.widget.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        if self.top is not None:
            try:
                self.top.destroy()
            except Exception:
                pass
            self.top = None


def tools_window(kind, count, name=""):
    """The other tools as a compact grid. -> "action:option", "presets", "about" or None."""
    import vp_ops as ops
    c = ctk()
    tools = [t for t in (PDF_TOOLS if kind == "pdf" else IMAGE_TOOLS) if count == 1 or not t[3]]
    for i, p in enumerate(ops.load_settings()["presets"]):
        if p:
            tools.append(("preset:%d" % (i + 1), ops.preset_label(i),
                          "Your preset: " + preset_summary(p).split(".")[0], False))
    what = name if count == 1 else "%d %s selected" % (count, "PDFs" if kind == "pdf" else "pictures")
    rows = (len(tools) + 1) // 2
    win = Window(core.APP_NAME, 440, 176 + 44 * rows, "More tools", what, name="tools")
    grid = c.CTkFrame(win.body, fg_color="transparent")
    grid.pack(fill="x", pady=(12, 0))
    grid.grid_columnconfigure((0, 1), weight=1, uniform="tools")
    win.tips = []
    for n, (key, title, hint, _single) in enumerate(tools):
        b = c.CTkButton(grid, text=" " + title, anchor="w", height=36, corner_radius=6, font=font(13),
                        fg_color=CARD, hover_color=TINT, text_color=TEXT, border_width=1,
                        border_color=LINE, command=lambda k=key: win.close(k))
        b.grid(row=n // 2, column=n % 2, sticky="ew", padx=(0, 4) if n % 2 == 0 else (4, 0), pady=4)
        if hint:
            win.tips.append(Tip(b, hint))
    win.button("Close", win.cancel)
    for text, key in (("Presets", "presets"), ("About", "about")):
        link = c.CTkButton(win.foot, text=text, width=20, height=28, font=font(12),
                           fg_color="transparent", hover_color="#EDEDED", text_color=MUTED,
                           command=lambda k=key: win.close(k))
        link.pack(side="left", padx=(18 if key == "presets" else 2, 0))
    return win.run()


def unlock_window(name, keep_choice=True, error=""):
    """Ask for the password of a locked PDF. -> {"password", "keep"} or None."""
    win = Window(core.APP_NAME, 460, 345 if keep_choice else 310, "This PDF is locked", name,
                 name="unlock")
    win.label(win.body, "Password", bold=True, fill="x", pady=(16, 4))
    p1 = win.entry(win.body, show="*", width=412)
    p1.pack(fill="x")
    wrong = ctk().CTkLabel(win.body, text=error, font=font(12), text_color=ACCENT, anchor="w",
                           height=18)
    wrong.pack(fill="x", pady=(4, 0))
    var = None
    if keep_choice:
        box, var = win.check(win.body, "Keep this password on the result", True)
        box.pack(anchor="w", pady=(8, 0))
        note = "Untick to save a result that opens without a password. Your original stays locked."
    else:
        note = "The JPG pictures will not be protected: a picture cannot carry a password."
    win.label(win.body, note, muted=True, size=12, fill="x", pady=(10, 0)).configure(wraplength=410)
    def go():
        if not p1.get():
            wrong.configure(text="Type the password.")
            return
        win.close({"password": p1.get(), "keep": bool(var.get()) if var is not None else False})

    win.button("Unlock", go, primary=True)
    win.button("Skip this file", win.cancel, width=120)
    win.root.bind("<Return>", lambda e: go())
    p1.focus_set()
    return win.run()


def choice_window(title, sub, options, value=None, ok="OK", name="choice"):
    """Pick one of [(key, label)]. -> key or None."""
    c = ctk()
    win = Window(core.APP_NAME, 420, 190 + 34 * len(options), title, sub, name=name)
    var = c.StringVar(value=value or options[0][0])
    first = True
    for key, label in options:
        win.radio(win.body, label, var, key).pack(anchor="w", pady=(18 if first else 10, 0))
        first = False
    win.button(ok, lambda: win.close(var.get()), primary=True)
    win.button("Cancel", win.cancel)
    win.root.bind("<Return>", lambda e: win.close(var.get()))
    return win.run(auto=lambda: win.close(var.get()))


# --------------------------------------------------------------------------
# Custom size, password, resize, blank PDF
# --------------------------------------------------------------------------

def custom_size_window(count, verb="Compress"):
    """-> {"amount", "unit", "bw", "slot"} or None."""
    import vp_ops as ops
    c = ctk()
    settings = ops.load_settings()
    win = Window(core.APP_NAME, 460, 470, "Custom size",
                 "%s %d file%s to fit a size you choose." % (verb, count, "" if count == 1 else "s"),
                 name="custom")
    win.label(win.body, "Largest file size", bold=True, fill="x", pady=(16, 4))
    row = c.CTkFrame(win.body, fg_color="transparent")
    row.pack(fill="x")
    last = settings["recent"][0] if settings["recent"] else [500, "KB"]
    amount = win.entry(row, "%g" % last[0], width=130)
    amount.pack(side="left")
    seg, unit = win.segmented(row, ["KB", "MB"], last[1])
    seg.pack(side="left", padx=10)
    if settings["recent"]:
        win.label(win.body, "Used recently", muted=True, size=12, fill="x", pady=(14, 4))
        chips = c.CTkFrame(win.body, fg_color="transparent")
        chips.pack(fill="x")

        def use(a, u):
            amount.delete(0, "end")
            amount.insert(0, "%g" % a)
            unit.set(u)

        for a, u in settings["recent"]:
            win.chip(chips, "%g %s" % (a, u), lambda a=a, u=u: use(a, u)).pack(side="left", padx=(0, 8))
    bw_box, bw = win.check(win.body, "Black and white (smaller, keeps text sharper)")
    bw_box.pack(anchor="w", pady=(18, 0))
    save_box, save = win.check(win.body, "Save this as a preset")
    save_box.pack(anchor="w", pady=(12, 0))

    def go():
        top = 2000 if unit.get() == "MB" else 2000000
        v = _number(amount.get(), 5 if unit.get() == "KB" else 0.01, top)
        if v is None:
            win.error("Type a size, for example 500")
            return
        slot = None
        if save.get():
            slot = 0 if settings["presets"][0] is None or settings["presets"][1] is not None else 1
        win.close({"amount": v, "unit": unit.get(), "bw": bool(bw.get()), "slot": slot})

    win.button(verb, go, primary=True)
    win.button("Cancel", win.cancel)
    win.root.bind("<Return>", lambda e: go())
    amount.focus_set()
    return win.run(auto=go)


def password_window(name):
    """-> {"mode": "add" | "remove", "password"} or None."""
    c = ctk()
    win = Window(core.APP_NAME, 460, 470, "Password", name, name="password")
    seg, mode = win.segmented(win.body, ["Add a password", "Remove the password"], "Add a password")
    seg.pack(fill="x", pady=(16, 0))
    l1 = win.label(win.body, "New password", bold=True, fill="x", pady=(16, 4))
    p1 = win.entry(win.body, show="*", width=412)
    p1.pack(fill="x")
    l2 = win.label(win.body, "Repeat password", bold=True, fill="x", pady=(12, 4))
    p2 = win.entry(win.body, show="*", width=412)
    p2.pack(fill="x")
    note = c.CTkLabel(win.body, text="", font=font(12), text_color=MUTED, anchor="w",
                      justify="left", wraplength=410)
    note.pack(fill="x", pady=(14, 0))

    def refresh(*_):
        add = mode.get().startswith("Add")
        l1.configure(text="New password" if add else "Current password")
        if add:
            l2.pack(fill="x", pady=(12, 4), before=note)
            p2.pack(fill="x", before=note)
            note.configure(text="Saves a protected copy. Your original stays as it is. Keep the "
                                "password safe: a forgotten password cannot be recovered.")
        else:
            l2.pack_forget()
            p2.pack_forget()
            note.configure(text="Saves a copy that opens without asking. You must know the "
                                "current password. Your original stays as it is.")

    mode.trace_add("write", refresh)
    refresh()

    def go():
        add = mode.get().startswith("Add")
        if add and len(p1.get()) < 4:
            win.error("Use at least 4 characters")
        elif add and p1.get() != p2.get():
            win.error("The two passwords are different")
        else:
            win.close({"mode": "add" if add else "remove", "password": p1.get()})

    win.button("Save copy", go, primary=True)
    win.button("Cancel", win.cancel)
    win.root.bind("<Return>", lambda e: go())
    p1.focus_set()
    return win.run()


def resize_window(name, size):
    """-> {"width", "height", "mode", "limit"} or None."""
    c = ctk()
    win = Window(core.APP_NAME, 460, 500, "Resize photo",
                 "%s, now %d x %d" % (name, size[0], size[1]), name="resize")
    row = c.CTkFrame(win.body, fg_color="transparent")
    row.pack(fill="x", pady=(16, 0))
    cols = []
    for text, value in (("Width", 600), ("Height", 600)):
        col = c.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", padx=(0, 12))
        win.label(col, text, bold=True, fill="x", pady=(0, 4))
        e = win.entry(col, value, width=110)
        e.pack()
        cols.append(e)
    win.label(row, "pixels", muted=True, side="left", pady=(26, 0))
    chips = c.CTkFrame(win.body, fg_color="transparent")
    chips.pack(fill="x", pady=(12, 0))

    def use(w, h):
        for e, v in zip(cols, (w, h)):
            e.delete(0, "end")
            e.insert(0, str(v))

    for w, h in ((600, 600), (413, 531), (1200, 1600)):
        win.chip(chips, "%d x %d" % (w, h), lambda w=w, h=h: use(w, h)).pack(side="left", padx=(0, 8))
    win.label(win.body, "If the shape is different", bold=True, fill="x", pady=(18, 6))
    mode = c.StringVar(value="crop")
    win.radio(win.body, "Crop the edges, keep the centre", mode, "crop").pack(anchor="w")
    win.radio(win.body, "Fit inside, add white edges", mode, "fit").pack(anchor="w", pady=(10, 0))
    lim = c.CTkFrame(win.body, fg_color="transparent")
    lim.pack(fill="x", pady=(18, 0))
    win.label(lim, "Also keep the file under", side="left")
    limit = win.entry(lim, "", width=80)
    limit.pack(side="left", padx=8)
    win.label(lim, "KB (optional)", muted=True, side="left")

    def go():
        w = _number(cols[0].get(), 16, 12000, True)
        h = _number(cols[1].get(), 16, 12000, True)
        if w is None or h is None:
            win.error("Width and height: 16 to 12000")
            return
        kb = None
        if limit.get().strip():
            kb = _number(limit.get(), 5, 100000)
            if kb is None:
                win.error("Size limit: 5 KB or more")
                return
        win.close({"width": w, "height": h, "mode": mode.get(),
                   "limit": int(kb * 1000 * 0.99) if kb else None})

    win.button("Resize", go, primary=True)
    win.button("Cancel", win.cancel)
    win.root.bind("<Return>", lambda e: go())
    return win.run(auto=go)


def blank_window():
    """-> {"size", "landscape", "pages"} or None."""
    c = ctk()
    win = Window(core.APP_NAME, 420, 400, "New blank PDF",
                 "Creates an empty PDF in this folder.", name="blank")
    win.label(win.body, "Paper size", bold=True, fill="x", pady=(16, 4))
    seg, size = win.segmented(win.body, ["A4", "Letter", "Legal"], "A4")
    seg.pack(fill="x")
    win.label(win.body, "Direction", bold=True, fill="x", pady=(16, 4))
    seg2, way = win.segmented(win.body, ["Portrait", "Landscape"], "Portrait")
    seg2.pack(fill="x")
    row = c.CTkFrame(win.body, fg_color="transparent")
    row.pack(fill="x", pady=(18, 0))
    win.label(row, "Pages", bold=True, side="left")
    pages = win.entry(row, 1, width=70)
    pages.pack(side="left", padx=10)

    def go():
        n = _number(pages.get(), 1, 500, True)
        if n is None:
            win.error("Pages: 1 to 500")
            return
        win.close({"size": size.get(), "landscape": way.get() == "Landscape", "pages": n})

    win.button("Create", go, primary=True)
    win.button("Cancel", win.cancel)
    win.root.bind("<Return>", lambda e: go())
    return win.run(auto=go)


# --------------------------------------------------------------------------
# Presets
# --------------------------------------------------------------------------

def preset_summary(p):
    if not p:
        return "Not set up yet"
    text = "Under %g %s" % (p.get("amount", 0), p.get("unit", "KB"))
    if p.get("bw"):
        text += ", black and white"
    text += ". Pictures become %s." % ("PDFs" if p.get("images", "pdf") == "pdf" else "smaller pictures")
    return text


def presets_window(edit=None, on_change=None):
    """Create, change or delete the two presets. edit: slot to open at once."""
    import vp_ops as ops
    c = ctk()
    settings = ops.load_settings()
    state = {"slot": edit}
    win = Window(core.APP_NAME, 600, 560, "Presets",
                 "Two shortcuts that appear in the VitePDF menu under My presets.", name="presets")
    card = win.card()
    form = win.card()
    summary = [None, None]
    names = [None, None]

    def changed():
        ops.save_settings(settings)
        if on_change:
            try:
                on_change()
            except Exception:
                core.log("menu update failed:\n" + traceback.format_exc())
        for i in range(2):
            p = settings["presets"][i]
            names[i].configure(text=(p or {}).get("name") or "Preset %d" % (i + 1))
            summary[i].configure(text=preset_summary(p))

    def delete(i):
        settings["presets"][i] = None
        if state["slot"] == i:
            open_form(None)
        changed()

    for i in range(2):
        row = c.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(10, 10 if i else 0))
        col = c.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", fill="x", expand=True)
        names[i] = win.label(col, "", bold=True, fill="x")
        summary[i] = win.label(col, "", muted=True, size=12, fill="x")
        win.button("Delete", lambda i=i: delete(i), parent=row, width=70).pack(side="right")
        win.button("Edit", lambda i=i: open_form(i), parent=row, width=70).pack(side="right", padx=8)
        if i == 0:
            c.CTkFrame(card, fg_color=LINE, height=1).pack(fill="x", padx=14)

    top = c.CTkFrame(form, fg_color="transparent")
    top.pack(fill="x", padx=14, pady=(12, 0))
    left = c.CTkFrame(top, fg_color="transparent")
    left.pack(side="left", fill="x", expand=True)
    win.label(left, "Name", bold=True, fill="x", pady=(0, 4))
    name = win.entry(left, "", width=260)
    name.pack(anchor="w")
    right = c.CTkFrame(top, fg_color="transparent")
    right.pack(side="left", padx=(12, 0))
    win.label(right, "Under", bold=True, fill="x", pady=(0, 4))
    rr = c.CTkFrame(right, fg_color="transparent")
    rr.pack()
    amount = win.entry(rr, "", width=80)
    amount.pack(side="left")
    seg, unit = win.segmented(rr, ["KB", "MB"], "KB")
    seg.pack(side="left", padx=(8, 0))
    bw_box, bw = win.check(form, "Black and white")
    bw_box.pack(anchor="w", padx=14, pady=(14, 0))
    kind = c.StringVar(value="pdf")
    line = c.CTkFrame(form, fg_color="transparent")
    line.pack(fill="x", padx=14, pady=(12, 14))
    win.label(line, "Pictures:", side="left")
    win.radio(line, "make a PDF", kind, "pdf").pack(side="left", padx=(12, 0))
    win.radio(line, "keep as a picture", kind, "image").pack(side="left", padx=(16, 0))
    status = win.foot_text("")

    def open_form(i):
        state["slot"] = i
        p = (settings["presets"][i] or {}) if i is not None else {}
        for e, v in ((name, p.get("name", "")), (amount, "%g" % p["amount"] if p.get("amount") else "")):
            e.delete(0, "end")
            e.insert(0, v)
        unit.set(p.get("unit", "KB"))
        bw.set(bool(p.get("bw")))
        kind.set(p.get("images", "pdf"))
        status.configure(text="Editing: Preset %d" % (i + 1) if i is not None
                         else "Choose Edit to set up a preset.")
        save.configure(state="normal" if i is not None else "disabled")

    def store():
        i = state["slot"]
        v = _number(amount.get(), 5 if unit.get() == "KB" else 0.01, 2000000)
        if i is None:
            return
        if v is None:
            status.configure(text="Type a size, for example 350")
            return
        label = " ".join(name.get().split())[:40] or "Preset %d" % (i + 1)
        settings["presets"][i] = {"name": label, "amount": v, "unit": unit.get(),
                                  "bw": bool(bw.get()), "images": kind.get()}
        changed()
        status.configure(text="Saved: %s" % label)

    save = win.button("Save preset", store, primary=True)
    win.button("Close", win.cancel)
    changed_once = on_change
    on_change = None
    changed()
    on_change = changed_once
    open_form(edit)
    return win.run()


# --------------------------------------------------------------------------
# Organize pages
# --------------------------------------------------------------------------

def crop_window(parent_win, image, current=None):
    """Drag a rectangle on the page. -> (u0, v0, u1, v1) fractions, "clear" or None."""
    import tkinter as tk
    from PIL import ImageTk
    c = ctk()
    top = c.CTkToplevel(parent_win.root, fg_color=BG)
    top.title("Crop page")
    scale = min(640.0 / image.width, 620.0 / image.height, 1.0)
    w, h = int(image.width * scale), int(image.height * scale)
    top.geometry("%dx%d" % (w + 48, h + 150))
    top.resizable(False, False)
    c.CTkLabel(top, text="Drag over the part to keep. Crop hides the rest; it does not delete it.", font=font(13), text_color=MUTED,
               anchor="w").pack(fill="x", padx=24, pady=(14, 8))
    photo = ImageTk.PhotoImage(image.resize((w, h)))
    cv = tk.Canvas(top, width=w, height=h, highlightthickness=1, highlightbackground="#C4C4C4",
                   cursor="crosshair")
    cv.pack(padx=24)
    cv.create_image(0, 0, image=photo, anchor="nw")
    cv.image = photo
    box = {"r": None, "start": None, "out": None}
    if current:
        box["r"] = (current[0] * w, current[1] * h, current[2] * w, current[3] * h)

    def draw():
        cv.delete("sel")
        if box["r"]:
            cv.create_rectangle(*box["r"], outline=ACCENT, width=2, tags="sel")

    def press(e):
        box["start"] = (e.x, e.y)

    def motion(e):
        x0, y0 = box["start"]
        x1, y1 = max(0, min(w, e.x)), max(0, min(h, e.y))
        box["r"] = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        draw()

    cv.bind("<ButtonPress-1>", press)
    cv.bind("<B1-Motion>", motion)
    draw()
    foot = c.CTkFrame(top, fg_color="transparent")
    foot.pack(fill="x", padx=24, pady=14)

    def done(value):
        box["out"] = value
        top.destroy()

    def apply():
        r = box["r"]
        if not r or r[2] - r[0] < 8 or r[3] - r[1] < 8:
            return
        done((r[0] / w, r[1] / h, r[2] / w, r[3] / h))

    parent_win.button("Apply", apply, primary=True, parent=foot).pack(side="right")
    parent_win.button("Cancel", lambda: done(None), parent=foot).pack(side="right", padx=10)
    parent_win.button("No crop", lambda: done("clear"), parent=foot).pack(side="left")
    top.transient(parent_win.root)
    top.grab_set()
    _hook("crop", top=top, box=box, size=(w, h), draw=draw, apply=apply)
    parent_win.root.wait_window(top)
    return box["out"]


def organize_window(path, password=None):
    """-> {"pages": [...], "mode": "one" | "selected" | "each"} or None."""
    import vp_ops as ops
    from PIL import ImageDraw
    c = ctk()
    path = Path(path)
    doc = ops.open_for_render(path, password)
    count = len(doc)
    pages = [{"index": i, "rotate": 0, "crop": None, "removed": False, "selected": False}
             for i in range(count)]
    undo, base, tiles = [], {}, []
    win = Window(core.APP_NAME, 980, 720, "Organize pages",
                 "%s, %d page%s. Click to select, Ctrl + click for several. Drag a page onto "
                 "another to move it." % (path.name, count, "" if count == 1 else "s"),
                 name="organize")
    bar = c.CTkFrame(win.body, fg_color="transparent")
    bar.pack(fill="x", pady=(12, 0))
    grid = c.CTkScrollableFrame(win.body, fg_color=CARD, corner_radius=8, border_width=1,
                                border_color=LINE)
    grid.pack(fill="both", expand=True, pady=(10, 0))
    out = c.CTkFrame(win.body, fg_color="transparent")
    out.pack(fill="x", pady=(10, 0))
    mode = c.StringVar(value="one")
    for text, value in (("Save all kept pages as one PDF", "one"),
                        ("Save only the selected pages", "selected"),
                        ("Save each page as its own PDF", "each")):
        win.radio(out, text, mode, value).pack(side="left", padx=(0, 22))
    info = win.foot_text("")
    COLS = 6

    def snapshot():
        undo.append([dict(p) for p in pages])
        del undo[:-30]

    def picture(p):
        im = base.get(p["index"])
        if im is None:
            return None
        if p["rotate"] % 360:
            im = im.rotate(-p["rotate"], expand=True)
        if p["crop"]:
            im = im.copy()
            d = ImageDraw.Draw(im)
            u0, v0, u1, v1 = p["crop"]
            d.rectangle([u0 * im.width, v0 * im.height, u1 * im.width - 1, v1 * im.height - 1],
                        outline=ACCENT, width=3)
        if p["removed"]:
            im = im.point(lambda v: 255 - (255 - v) // 4)
        s = min(108.0 / im.width, 132.0 / im.height)
        return c.CTkImage(light_image=im, size=(max(1, int(im.width * s)), max(1, int(im.height * s))))

    def render():
        for t in tiles:
            t.destroy()
        del tiles[:]
        for n, p in enumerate(pages):
            tile = c.CTkFrame(grid, fg_color=TINT if p["selected"] else CARD, corner_radius=8,
                              width=142, height=176, border_width=2 if p["selected"] else 0,
                              border_color=ACCENT)
            tile.grid(row=n // COLS, column=n % COLS, padx=5, pady=5)
            tile.pack_propagate(False)
            pic = picture(p)
            a = c.CTkLabel(tile, text="" if pic else "...", image=pic, width=110, height=134)
            a.pack(pady=(8, 0))
            tag = "%d" % (n + 1) + ("   removed" if p["removed"] else "")
            b = c.CTkLabel(tile, text=tag, font=font(12, p["selected"]),
                           text_color=MUTED if p["removed"] else TEXT, height=20)
            b.pack()
            for wdg in (tile, a, b):
                wdg.bind("<ButtonPress-1>", lambda e, k=n: press(e, k))
                wdg.bind("<ButtonRelease-1>", lambda e, k=n: release(e, k))
            tiles.append(tile)
        kept = sum(1 for p in pages if not p["removed"])
        chosen = sum(1 for p in pages if p["selected"])
        info.configure(text="%d kept, %d removed, %d selected" % (kept, len(pages) - kept, chosen))

    def press(event, k):
        ctrl = bool(event.state & 0x0004)
        if ctrl:
            pages[k]["selected"] = not pages[k]["selected"]
        elif not pages[k]["selected"] or sum(1 for p in pages if p["selected"]) > 1:
            for p in pages:
                p["selected"] = False
            pages[k]["selected"] = True
        render()

    def release(event, k):
        x, y = event.x_root, event.y_root
        for j, t in enumerate(tiles):
            if j != k and t.winfo_rootx() <= x <= t.winfo_rootx() + t.winfo_width() and \
                    t.winfo_rooty() <= y <= t.winfo_rooty() + t.winfo_height():
                snapshot()
                pages.insert(j, pages.pop(k))
                render()
                return

    def chosen():
        return [p for p in pages if p["selected"]]

    def rotate(deg):
        if chosen():
            snapshot()
            for p in chosen():
                p["rotate"] = (p["rotate"] + deg) % 360
                p["crop"] = None
            render()

    def remove():
        if chosen():
            snapshot()
            state = not all(p["removed"] for p in chosen())
            for p in chosen():
                p["removed"] = state
            render()

    def crop():
        sel = chosen()
        if not sel:
            return
        p = sel[0]
        big = ops.render_page(doc, p["index"], dpi=90, max_side=1400)
        if p["rotate"] % 360:
            big = big.rotate(-p["rotate"], expand=True)
        got = crop_window(win, big, p["crop"])
        if got is None:
            return
        snapshot()
        for q in sel:
            q["crop"] = None if got == "clear" else got
        render()

    def select_all():
        state = not all(p["selected"] for p in pages)
        for p in pages:
            p["selected"] = state
        render()

    def undo_last():
        if undo:
            pages[:] = undo.pop()
            render()

    for text, cmd in (("Rotate left", lambda: rotate(-90)), ("Rotate right", lambda: rotate(90)),
                      ("Remove", remove), ("Crop", crop)):
        win.button(text, cmd, parent=bar, width=100).pack(side="left", padx=(0, 8))
    win.button("Undo", undo_last, parent=bar, width=80).pack(side="right")
    win.button("Select all", select_all, parent=bar, width=90).pack(side="right", padx=8)

    def load(i):
        if i >= count:
            return
        try:
            base[i] = ops.render_page(doc, i, dpi=40, max_side=320)
        except Exception:
            pass
        if i % 6 == 5 or i == count - 1:
            render()
        win.root.after(5, lambda: load(i + 1))

    def go():
        kept = [p for p in pages if not p["removed"]]
        if mode.get() == "selected" and not any(p["selected"] for p in kept):
            win.error("Select the pages to save first")
            return
        if not kept:
            win.error("Every page is removed")
            return
        win.close({"pages": [{"index": p["index"], "rotate": p["rotate"], "crop": p["crop"],
                              "selected": p["selected"]} for p in kept],
                   "mode": mode.get(), "password": password})

    win.button("Save copy", go, primary=True)
    win.button("Cancel", win.cancel)
    render()
    win.root.after(50, lambda: load(0))

    _hook("organize", window=win, pages=pages, render=render, crop=crop, go=go)
    return win.run(auto=lambda: None)


# --------------------------------------------------------------------------
# Capture an area of the screen
# --------------------------------------------------------------------------

def capture_area():
    """Dim the screen, let the user drag a box. -> PIL image or None."""
    import tkinter as tk
    from PIL import ImageEnhance, ImageGrab, ImageTk
    x0 = y0 = 0
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            gm = ctypes.windll.user32.GetSystemMetrics
            x0, y0 = gm(76), gm(77)
        except Exception:
            pass
    try:
        shot = ImageGrab.grab(all_screens=True) if os.name == "nt" else ImageGrab.grab()
    except Exception:
        shot = ImageGrab.grab()
    shot = shot.convert("RGB")
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry("%dx%d+%d+%d" % (shot.width, shot.height, x0, y0))
    root.attributes("-topmost", True)
    cv = tk.Canvas(root, width=shot.width, height=shot.height, highlightthickness=0,
                   cursor="crosshair")
    cv.pack()
    dark = ImageTk.PhotoImage(ImageEnhance.Brightness(shot).enhance(0.55))
    cv.create_image(0, 0, image=dark, anchor="nw")
    cv.create_text(shot.width // 2, 36, fill="#FFFFFF", font=(FONT, 14),
                   text="Drag over the area to capture. Esc cancels.")
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
        cv.create_rectangle(box[0], box[1], box[2] - 1, box[3] - 1, outline="#FFFFFF", tags="sel")

    def release(_e):
        box = state["box"]
        if box and box[2] - box[0] >= 8 and box[3] - box[1] >= 8:
            state["out"] = shot.crop(box)
        root.quit()

    cv.bind("<ButtonPress-1>", press)
    cv.bind("<B1-Motion>", motion)
    cv.bind("<ButtonRelease-1>", release)
    root.bind("<Escape>", lambda e: root.quit())
    root.focus_force()
    _hook("capture", root=root, press=press, motion=motion, release=release)
    root.mainloop()
    root.destroy()
    return state["out"]


# --------------------------------------------------------------------------
# Installer and uninstaller
# --------------------------------------------------------------------------

def terms_window(parent, text):
    c = ctk()
    top = c.CTkToplevel(parent.root, fg_color=BG)
    top.title("VitePDF terms")
    top.geometry("640x620")
    box = c.CTkTextbox(top, font=font(12), fg_color=CARD, text_color=TEXT, border_width=1,
                       border_color=LINE, corner_radius=8, wrap="word")
    box.pack(fill="both", expand=True, padx=20, pady=(20, 10))
    import re
    tk_text = getattr(box, "_textbox", box)
    scale = 1.0
    try:
        scale = box._apply_widget_scaling(1.0)
    except Exception:
        pass
    px = lambda v: int(v * scale)
    # One left edge for plain text, one for list items; wrapped lines of an
    # item start under its first word, not under the bullet.
    tk_text.tag_configure("plain", lmargin1=px(4), lmargin2=px(4))
    tk_text.tag_configure("head", lmargin1=px(4), lmargin2=px(4), font=font(12, True))
    tk_text.tag_configure("item", lmargin1=px(18), lmargin2=px(40), tabs=(px(40),))
    tk_text.tag_configure("more", lmargin1=px(40), lmargin2=px(40))
    for line in text.splitlines():
        m = re.match(r"^(\s*)((?:-|\d+\.)\s+)?(.*)$", line)
        lead, mark, rest = len(m.group(1)), (m.group(2) or "").strip(), m.group(3)
        if mark:
            box.insert("end", mark + "\t" + rest + "\n", "item")
        elif lead >= 4:
            box.insert("end", rest + "\n", "more")
        elif lead:
            box.insert("end", "\u2022\t" + rest + "\n", "item")
        elif rest and rest == rest.upper() and len(rest) > 3:
            box.insert("end", rest + "\n", "head")
        else:
            box.insert("end", rest + "\n", "plain")
    box.configure(state="disabled")
    parent.button("Close", top.destroy, parent=top).pack(pady=(0, 16))
    top.transient(parent.root)
    top.grab_set()


def installer_window(terms_text, steps, work, windows11=False, signer=""):
    """work(step_cb, options) does the install. -> True when it finished."""
    import tkinter as tk
    c = ctk()
    win = Window("VitePDF Setup", 700, 620, name="installer")
    state = {"page": "welcome", "ok": False}
    page = c.CTkFrame(win.body, fg_color="transparent")
    page.pack(fill="both", expand=True)

    def clear():
        for w in page.winfo_children():
            w.destroy()
        for w in win.foot.winfo_children():
            w.destroy()

    def welcome():
        clear()
        head = c.CTkFrame(page, fg_color="transparent")
        head.pack(fill="x")
        logo = _logo()
        if logo is not None:
            c.CTkLabel(head, text="", image=c.CTkImage(light_image=logo, size=(52, 52))).pack(
                side="left", padx=(0, 14))
        col = c.CTkFrame(head, fg_color="transparent")
        col.pack(side="left", fill="x", expand=True)
        win.label(col, "Install VitePDF", bold=True, size=24, fill="x")
        win.label(col, "Right-click image and PDF tools. Version %s" % core.VERSION, muted=True,
                  fill="x")
        card = win.card(page, fill="x", pady=(18, 0))
        rows = (("What it does", "Adds VitePDF to the right-click menu of pictures and PDFs: "
                 "convert, compress, merge, split and more, with size presets."),
                ("What gets installed", "One folder in your user profile, a Start menu shortcut "
                 "and the menu entries. No administrator rights. Remove it any time under "
                 "Settings > Apps."),
                ("Privacy", "Runs offline. Collects nothing. Never changes your original files."))
        for i, (title, text) in enumerate(rows):
            if i:
                c.CTkFrame(card, fg_color=LINE, height=1).pack(fill="x", padx=16)
            win.label(card, title, bold=True, fill="x", padx=16, pady=(12, 0))
            c.CTkLabel(card, text=text, font=font(13), text_color=MUTED, anchor="w",
                       justify="left", wraplength=610).pack(fill="x", padx=16, pady=(0, 12))
        line = c.CTkFrame(page, fg_color="transparent")
        line.pack(fill="x", pady=(14, 0))
        win.label(line, "Free to use and share under the MIT licence. Provided as is, without "
                        "warranty.", muted=True, side="left")
        link = c.CTkButton(line, text="Read the full terms", width=20, height=24, font=font(13),
                           fg_color="transparent", hover_color="#EAEAEA", text_color=ACCENT,
                           command=lambda: terms_window(win, terms_text))
        link.pack(side="left", padx=6)
        win.label(page, core.CREDIT + ((" " + signer) if signer else ""), muted=True, size=12,
                  fill="x", pady=(6, 0))
        classic = None
        if windows11:
            box, classic = win.check(page, "Show VitePDF at the top of the right-click menu "
                                           "(switches Windows to its classic full menu)", True)
            box.pack(anchor="w", pady=(12, 0))
        accept_box, accept = win.check(win.foot, "I accept the terms")
        accept_box.pack(side="left", padx=24)
        install = win.button("Install", lambda: start(bool(classic.get()) if classic else False),
                             primary=True)
        install.configure(state="disabled")
        accept_box.configure(command=lambda: install.configure(
            state="normal" if accept.get() else "disabled"))
        win.button("Cancel", win.cancel)
        _hook("installer_welcome", window=win, accept=accept, install=install, start=start)

    marks = []

    def start(classic):
        clear()
        state["page"] = "busy"
        win.label(page, "Installing VitePDF", bold=True, size=24, fill="x")
        win.label(page, "This takes less than a minute.", muted=True, fill="x")
        card = win.card(page, fill="x", pady=(18, 0))
        del marks[:]
        for i, text in enumerate(steps):
            if i:
                c.CTkFrame(card, fg_color=LINE, height=1).pack(fill="x", padx=16)
            row = c.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=10)
            cv = tk.Canvas(row, width=22, height=22, bg=CARD, highlightthickness=0)
            cv.pack(side="left", padx=(0, 12))
            lab = c.CTkLabel(row, text=text, font=font(13), text_color=MUTED, anchor="w")
            lab.pack(side="left", fill="x", expand=True)
            marks.append((cv, lab))
            paint(i, "wait")
        bar = c.CTkProgressBar(page, height=5, corner_radius=3, fg_color="#E3C4C5",
                               progress_color=ACCENT)
        bar.pack(fill="x", pady=(18, 0))
        bar.set(0)
        note = win.foot_text("")
        result = {}

        def step(i):
            result["step"] = i

        def worker():
            try:
                work(step, {"classic": classic})
                result["done"] = True
            except BaseException as e:
                core.log("install failed:\n" + traceback.format_exc())
                result["error"] = str(e) or type(e).__name__

        gc.collect()
        gc.disable()              # see Window.run: no clean-up from the worker thread
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        seen = {"i": -1}

        def poll():
            i = result.get("step", -1)
            if i != seen["i"]:
                for k in range(len(marks)):
                    paint(k, "done" if k < i else ("now" if k == i else "wait"))
                seen["i"] = i
                bar.set(max(0.0, (i + 0.5) / len(marks)))
                note.configure(text="Step %d of %d" % (i + 1, len(marks)))
            if t.is_alive():
                win.root.after(100, poll)
            elif result.get("done"):
                finish()
            else:
                failed(result.get("error", "unknown problem"))

        _hook("installer_progress", window=win)
        win.root.after(100, poll)

    def paint(i, how):
        cv, lab = marks[i]
        cv.delete("all")
        if how == "done":
            cv.create_oval(2, 2, 20, 20, fill=TEXT, outline=TEXT)
            cv.create_line(6, 11, 10, 15, 16, 7, fill="#FFFFFF", width=2)
            lab.configure(text_color=TEXT, font=font(13))
        elif how == "now":
            cv.create_oval(3, 3, 19, 19, outline=ACCENT, width=3)
            lab.configure(text_color=TEXT, font=font(13, True))
        else:
            cv.create_oval(3, 3, 19, 19, outline="#B8B8B8", width=1)
            lab.configure(text_color=MUTED, font=font(13))

    def finish():
        clear()
        state["ok"] = True
        win.label(page, "VitePDF is installed", bold=True, size=24, fill="x")
        win.label(page, "Right-click a picture or a PDF and choose VitePDF.\nRight-click empty "
                        "space in a folder for New blank PDF and Capture area to PDF.",
                  muted=True, fill="x", pady=(6, 0))
        win.button("Close", lambda: win.close(True), primary=True)
        _hook("installer_done", window=win)

    def failed(reason):
        clear()
        win.label(page, "VitePDF could not be installed", bold=True, size=24, fill="x")
        c.CTkLabel(page, text="%s\n\nDetails are in the log: %s" % (reason, core.data_dir() /
                   "vitepdf.log"), font=font(13), text_color=MUTED, anchor="w", justify="left",
                   wraplength=640).pack(fill="x", pady=(8, 0))
        win.button("Close", win.cancel, primary=True)

    def on_close():
        if state["page"] != "busy" or state["ok"]:
            win.close(state["ok"])

    win.cancel = on_close
    win.root.protocol("WM_DELETE_WINDOW", on_close)
    welcome()
    win.root.mainloop()
    try:
        win.root.destroy()
    except Exception:
        pass
    return bool(win.result)


def confirm_window(title, text, yes="OK", no="Cancel", extra=None, name="confirm"):
    """-> None (cancelled) or {"extra": bool}."""
    win = Window(core.APP_NAME, 480, 280 if extra else 240, title, text, name=name)
    var = None
    if extra:
        box, var = win.check(win.body, extra, True)
        box.pack(anchor="w", pady=(18, 0))
    win.button(yes, lambda: win.close({"extra": bool(var.get()) if var else False}), primary=True)
    win.button(no, win.cancel)
    return win.run()
