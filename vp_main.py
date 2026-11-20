# -*- coding: utf-8 -*-
"""
VitePDF command handling: reads what the right-click menu asked for, opens a
window when one is needed, runs the job and reports.

Created by Atanu Sarkar. Made with Claude.
"""

import os
import sys
import time
import traceback
from pathlib import Path

import vp_core as core
from vp_core import APP_NAME, IMAGE_EXTS, PDF_EXTS, PRESETS, VERSION, data_dir, log

USAGE = """VitePDF %s
Usage:
  vitepdf.py [--now] <action> <option> <file> [<file> ...]

  pictures   img-each      original | optimized | under1mb | custom      (to PDF)
             img-compress  optimized | under1mb | under200kb | custom
             img-convert   jpg | png
             img-resize | img-bw | img-clean | img-repair        (option: x)
  PDFs       pdf-compress  optimized | under1mb | under350kb | custom
             pdf-tojpg     best | optimized | under1mb | custom
             pdf-rotate    right | left
             pdf-split | pdf-organize | pdf-bw | pdf-clean | pdf-password | pdf-repair
  both       merge         original | optimized | under1mb | under350kb | custom
             preset        1 | 2
  folder     capture x <folder> | scroll x <folder> | blank x <folder>

  --now      run at once: no multi-select queue and no windows. Extra values:
             --limit 500KB   --bw   --mode add|remove   --size 600x600  --fit crop|fit
             --password TEXT   (new password, or the password of a locked PDF)
             --keep-password   (results of a locked PDF keep its password)
             Exit code: 0 done, 2 wrong command, 3 one or more files failed.

  vitepdf.py --setup | --installer <folder> | --uninstall | --selftest | --about | --version
""" % VERSION

# action: (which files, verb for the Custom size window)
ACTIONS = {
    "img-each": ("image", "Convert"), "img-compress": ("image", "Compress"),
    "img-convert": ("image", ""), "img-resize": ("image", ""), "img-bw": ("image", ""),
    "img-clean": ("image", ""), "img-repair": ("image", ""),
    "pdf-compress": ("pdf", "Compress"), "pdf-tojpg": ("pdf", "Convert"),
    "pdf-rotate": ("pdf", ""), "pdf-split": ("pdf", ""), "pdf-organize": ("pdf", ""),
    "pdf-bw": ("pdf", ""), "pdf-clean": ("pdf", ""), "pdf-password": ("pdf", ""),
    "pdf-repair": ("pdf", ""),
    "merge": ("both", "Merge"), "preset": ("both", ""), "presets": ("both", ""),
    "tools": ("both", ""),
}
ALIASES = {"img-merge": "merge", "pdf-merge": "merge"}


def _jobs():
    import vp_ops as ops
    return {
        "img-each": core.job_img_each, "img-compress": ops.job_img_compress,
        "img-convert": ops.job_img_convert, "img-resize": ops.job_img_resize,
        "img-bw": ops.job_img_bw, "img-clean": ops.job_img_clean,
        "img-repair": ops.job_img_repair, "pdf-compress": core.job_pdf_compress,
        "pdf-tojpg": ops.job_pdf_tojpg, "pdf-rotate": ops.job_pdf_rotate,
        "pdf-split": ops.job_pdf_split, "pdf-organize": ops.job_pdf_organize,
        "pdf-bw": ops.job_pdf_bw, "pdf-clean": ops.job_pdf_clean,
        "pdf-password": ops.job_pdf_password, "pdf-repair": ops.job_pdf_repair,
        "merge": ops.job_merge,
    }


def message_box(text, warn=False):
    """Plain Windows message, used only when the normal windows cannot open."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, APP_NAME,
                                             (0x30 if warn else 0x40) | 0x10000 | 0x40000)
            return
        except Exception:
            pass
    try:
        sys.stderr.write(text + "\n")
    except Exception:
        pass


def emit(line):
    """Where notes go when no window is used (--now)."""
    try:
        sys.stderr.write(line + "\n")
    except Exception:
        pass


def _sort_files(files, kinds, report):
    exts = {"image": IMAGE_EXTS, "pdf": PDF_EXTS, "both": IMAGE_EXTS + PDF_EXTS}[kinds]
    what = {"image": "a picture", "pdf": "a PDF", "both": "a picture or PDF"}[kinds]
    good = []
    for f in files:
        f = Path(f)
        core.private(str(f), str(f.parent), f.name)
        if not f.is_file():
            report.fail("%s: file not found." % f.name)
            continue
        if f.suffix.lower() not in exts:
            report.fail("%s: skipped, not %s VitePDF can use here." % (f.name, what))
            continue
        try:
            core.check_size(f)
        except core.TooBig as e:
            report.fail("%s: skipped (%s)." % (f.name, e))
            continue
        good.append(f)
    good.sort(key=core.natural_key)
    return good


REWRITES = ("pdf-compress", "pdf-rotate", "pdf-split", "pdf-organize", "pdf-bw", "pdf-clean",
            "pdf-password", "pdf-repair", "merge", "preset")


def _gate_pdfs(files, action, ui, extra, report):
    """Look at every PDF once before work starts: ask for the password of a
    locked one, and say so when a digital signature will not survive.
    -> (files to process, {path key: password to put on the results})"""
    import vp_ops as ops
    keep, out = {}, []
    for f in files:
        if not ops.is_pdf(f):
            out.append(f)
            continue
        facts = core.pdf_facts(f)
        if facts["locked"] and action != "pdf-password":
            password, again = None, ""
            if ui:
                while True:
                    got = ui.unlock_window(f.name, keep_choice=action != "pdf-tojpg", error=again)
                    if not got:
                        break
                    if not core.pdf_facts(f, got["password"])["locked"]:
                        password = got["password"]
                        if got.get("keep"):
                            keep[core.path_key(f)] = password
                        break
                    again = "That password is not correct. Try again."
                if password is None:
                    report.info("%s: skipped. It is password protected." % f.name)
                    continue
            else:
                password = extra.get("password") or ""
                if not password:
                    report.fail("%s: is password protected. Give its password." % f.name)
                    continue
                if core.pdf_facts(f, password)["locked"]:
                    report.fail("%s: that password is not correct." % f.name)
                    continue
                if extra.get("keep"):
                    keep[core.path_key(f)] = password
            core.PASSWORDS[core.path_key(f)] = password
            facts = core.pdf_facts(f)
        if facts["signed"] and action in REWRITES:
            text = ("%s is digitally signed. A copy saved by VitePDF cannot keep a valid "
                    "signature. Your original is not changed and stays valid." % f.name)
            if ui:
                # Asked before anything is saved, not reported afterwards.
                if not ui.confirm_window("Signed PDF", text + "\n\nSave a copy anyway?",
                                         yes="Save a copy", no="Skip this file", name="signed"):
                    report.info("%s: skipped. It is digitally signed." % f.name)
                    continue
            else:
                emit(text)
        out.append(f)
    return out, keep


def _run_plan(plan, option, report, status, keep):
    """Run the jobs. Results made from a locked PDF get its password back
    when the user asked for that."""
    import vp_ops as ops
    jobs = _jobs()

    for act, part in plan:
        if not part or status.get("cancel"):
            continue
        locked = [f for f in part if core.path_key(f) in keep]
        try:
            if not locked:
                jobs[act](part, option, report, status)
            elif act == "merge":
                core.PROTECT = keep[core.path_key(locked[0])]
                jobs[act](part, option, report, status)
                if len(part) > 1 and report.outputs:
                    report.info("The merged PDF opens with the password of %s." % locked[0].name)
            else:
                for f in part:
                    if status.get("cancel"):
                        break
                    # The result is encrypted before it is written, so no
                    # unprotected copy ever exists, not even when saving fails.
                    core.PROTECT = keep.get(core.path_key(f))
                    jobs[act]([f], option, report, status)
        finally:
            core.PROTECT = None


def _parse_limit(text):
    text = text.strip().upper().replace(" ", "")
    unit = "MB" if text.endswith("MB") else "KB"
    return float(text.replace("MB", "").replace("KB", "")), unit


def _preset_plan(slot, files, extra):
    """Turn a saved preset into the jobs to run. -> [(action, files)] or None."""
    import vp_ops as ops
    p = ops.load_settings()["presets"][slot]
    if not p:
        return None
    core.set_custom_preset(p["amount"], p.get("unit", "KB"), gray=p.get("bw", False))
    pdfs = [f for f in files if ops.is_pdf(f)]
    images = [f for f in files if not ops.is_pdf(f)]
    plan = []
    if pdfs:
        plan.append(("pdf-compress", pdfs))
    if images:
        plan.append(("img-each" if p.get("images", "pdf") == "pdf" else "img-compress", images))
    return plan


def run(action, option, files, interactive, extra=None):
    """Run one right-click command. extra: values given with --now."""
    import vp_ops as ops
    extra = extra or {}
    report = core.Report()
    ui = None
    saved_preset = False
    if interactive:
        import vp_ui as ui

    if action == "presets":
        import vp_shell as shell
        ui.presets_window(on_change=shell.refresh_menu) if ui else None
        return 0

    files = _sort_files(files, ACTIONS[action][0], report)
    ordered = False
    if action == "tools":
        if not ui or not files:
            return 0
        pdfs = [f for f in files if ops.is_pdf(f)]
        if pdfs and len(pdfs) != len(files):
            ui.message_window("Nothing to do", "More tools works on pictures or on PDFs, not on "
                              "both together. To combine them, use Merge.")
            return 0
        got = ui.tools_window("pdf" if pdfs else "image", len(files), files[0].name)
        if got in ("presets", "about"):
            import vp_shell as shell
            ui.presets_window(on_change=shell.refresh_menu) if got == "presets" else ui.about_window()
            return 0
        if not got:
            return 0
        action, option = got.split(":")
        return run(action, option, files, interactive, extra)
    files, keep = _gate_pdfs(files, action, ui, extra, report)
    if action == "pdf-tojpg" and option == "ask":
        option = "optimized"
        if ui:
            option = ui.choice_window("To JPG", "One JPG per page.", [
                ("best", "Best quality"), ("optimized", "Optimized"),
                ("under1mb", "Under 1 MB each"), ("custom", "Custom size")], ok="Convert",
                name="tojpg")
            if not option:
                return 0
    if action == "merge" and option == "ask":
        option = "optimized"
        if ui:
            if len(files) < 2:
                ui.message_window("Nothing to do", "Select two or more files, then choose Merge.")
                return 0
            settings = ops.load_settings()
            got = ui.order_window(files, sizes=[
                ("original", "Original"), ("optimized", "Optimized"), ("under1mb", "Under 1 MB"),
                ("under350kb", "Under 350 KB"), ("custom", "Custom")],
                size=settings.get("merge_size", "optimized"),
                caution=core.BATCH_GAP > 0.3)
            if not got:
                return 0
            files, option, ordered = got["files"], got["size"], True
            settings["merge_size"] = option
            ops.save_settings(settings)
    plan = [(action, files)]
    if files:
        if action == "preset":
            slot = 0 if option == "1" else 1
            plan = _preset_plan(slot, files, extra)
            if plan is None:
                if ui:
                    import vp_shell as shell
                    ui.presets_window(edit=slot, on_change=shell.refresh_menu)
                return 0
            option = "custom"
        elif option == "custom":
            if ui:
                got = ui.custom_size_window(len(files), ACTIONS[action][1] or "Compress")
                if not got:
                    return 0
                ops.remember_size(got["amount"], got["unit"])
                if got.get("slot") is not None:
                    settings = ops.load_settings()
                    settings["presets"][got["slot"]] = {
                        "name": "", "amount": got["amount"], "unit": got["unit"], "bw": got["bw"],
                        "images": "image" if action == "img-compress" else "pdf"}
                    ops.save_settings(settings)
                    saved_preset = True
                amount, unit, bw = got["amount"], got["unit"], got["bw"]
            else:
                amount, unit = _parse_limit(extra.get("limit", "500KB"))
                bw = bool(extra.get("bw"))
            core.set_custom_preset(amount, unit, gray=bw)
        elif extra.get("bw"):
            core.FORCE_GRAY = True

        if action == "merge" and ui and len(files) > 1 and not ordered:
            files = ui.order_window(files, "Result: %s" % PRESETS[option]["label"])
            if not files:
                return 0
            plan = [(action, files)]
        elif action == "img-resize":
            if ui:
                got = ui.resize_window(files[0].name if len(files) == 1 else "%d pictures" % len(files),
                                       core.SourceImage(files[0]).display_size())
                if not got:
                    return 0
            else:
                w, h = extra.get("size", "600x600").lower().split("x")
                kb = extra.get("limit")
                got = {"width": int(w), "height": int(h), "mode": extra.get("fit", "crop"),
                       "limit": int(_parse_limit(kb)[0] * (1000000 if "MB" in kb.upper() else 1000) * 0.99)
                       if kb else None}
            ops.PARAMS.update(got)
        elif action == "pdf-password":
            if ui:
                got = ui.password_window(files[0].name if len(files) == 1 else "%d PDFs" % len(files))
                if not got:
                    return 0
            else:
                got = {"mode": extra.get("mode", "add"), "password": extra.get("password", "")}
            ops.PARAMS.update(got)
        elif action == "pdf-organize":
            if len(files) > 1:
                report.info("Organize pages works on one PDF at a time. Opened: %s" % files[0].name)
            files = files[:1]
            plan = [(action, files)]
            if ui:
                try:
                    got = ui.organize_window(files[0])
                except Exception as e:
                    log("organize failed:\n" + traceback.format_exc())
                    report.fail("%s: could not be opened (%s)." % (files[0].name, core._reason(e)))
                    got, plan = None, []
                if got is None and plan:
                    return 0
                if got:
                    ops.PARAMS.update(got)
            else:
                ops.PARAMS.update(extra.get("organize") or {})

        if plan and any(part for _a, part in plan):
            status = {"text": "Working", "name": ""}

            def work():
                _run_plan(plan, option, report, status, keep)

            if ui:
                ui.run_job(work, status)
            else:
                work()
    log("%s %s: %d file(s) in, %d out, %d note(s)"
        % (action, option, len(files), len(report.outputs), len(report.lines)))
    if ui:
        if saved_preset:
            try:
                import vp_shell as shell
                shell.refresh_menu()            # a new preset may have been saved
            except Exception:
                pass
        ui.show_report(report)
    else:
        for line in report.lines:
            emit(line)
    return 3 if report.failed else 0


def _folder_action(action, folder):
    import vp_ops as ops
    import vp_ui as ui
    anywhere = str(folder).lower() == "desktop"      # started from the shortcut or its keys
    folder = Path(folder)
    if action == "blank":
        if not folder.is_dir():
            folder = _known_folder("desktop")
        got = ui.blank_window()
        if got:
            ops.make_blank(folder, got["size"], got["landscape"], got["pages"])
            log("blank PDF saved")
        return 0
    if anywhere:
        folder = _capture_folder(ui, ask=True)
        if folder is None:
            return 0
    elif not folder.is_dir():
        folder = _known_folder("desktop")
    time.sleep(0.35)                        # let the menu or the taskbar click settle first
    if action == "scroll":
        return _scroll_capture(ui, folder, anywhere)
    im = ui.capture_area()
    if im is not None:
        out = ops.save_capture(folder, im)
        log("capture saved")
        if anywhere:
            ui.message_window("Capture saved", "%s\nSaved in: %s" % (out.name, folder.name or folder),
                              outputs=[out], name="captured",
                              extra=("Change folder", lambda: _capture_folder(ui, change=True)))
    return 0


def _scroll_capture(ui, folder, anywhere):
    """Capture a long page while it scrolls (VitePDF Scroll)."""
    import vp_scroll
    try:
        out, notes = vp_scroll.run(folder)
    except Exception as e:
        log("scroll capture failed: %s" % type(e).__name__)
        ui.message_window("Capture not saved", "Something went wrong while capturing the long page. "
                          "Nothing was saved. Please try again.", name="scroll-failed")
        return 1
    for line in notes:
        log("scroll: " + line)                 # numbers only, never page content
    if out is not None:
        log("scroll capture saved")
        if anywhere:
            ui.message_window("Capture saved", "%s\nSaved in: %s" % (out.name, folder.name or folder),
                              outputs=[out], name="captured",
                              extra=("Change folder", lambda: _capture_folder(ui, change=True)))
    return 0


def _capture_folder(ui, ask=False, change=False):
    """The folder for captures made with the shortcut. Asked once, then kept."""
    import vp_ops as ops
    settings = ops.load_settings()
    choice = settings.get("capture_folder")
    if change or (ask and not choice):
        got = ui.capture_folder_window(choice, first=not choice)
        if not got:
            if change or not choice:
                return None if not change else _resolve_capture(choice)
        else:
            choice = got
            settings["capture_folder"] = choice
            ops.save_settings(settings)
    return _resolve_capture(choice)


def _resolve_capture(choice):
    if choice in ("downloads", "desktop", None):
        return _known_folder(choice or "downloads")
    p = Path(str(choice))
    return p if p.is_dir() else _known_folder("downloads")


_FOLDER_IDS = {
    "desktop": (0xB4BFCC3A, 0xDB2C, 0x424C, (0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41)),
    "downloads": (0x374DE290, 0x123F, 0x4565, (0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B)),
}


def _known_folder(which):
    """The real Desktop or Downloads folder (either may live in OneDrive)."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD),
                            ("d", ctypes.c_ubyte * 8)]
            a, b, c, d = _FOLDER_IDS[which]
            guid = GUID(a, b, c, (ctypes.c_ubyte * 8)(*d))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                                         ctypes.byref(out)) == 0:
                path = Path(out.value)
                if path.is_dir():
                    return path
        except Exception:
            pass
    plain = Path.home() / ("Desktop" if which == "desktop" else "Downloads")
    return plain if plain.is_dir() else Path.home()


def _installer(src):
    import vp_shell as shell
    import vp_ui as ui
    src = Path(src)
    terms = ""
    try:
        terms = (src / "app" / "TERMS.txt").read_text(encoding="utf-8")
    except OSError:
        pass
    done = ui.installer_window(terms, shell.INSTALL_STEPS,
                               lambda step, options: shell.install_bundle(src, step, options),
                               windows11=shell.is_windows11() and not shell.classic_menu_enabled())
    return 0 if done else 2


def _uninstall(console):
    import vp_shell as shell
    marker = (data_dir() / "classic-menu-set").exists()
    if console:
        shell.uninstall(restore_menu=marker and shell.classic_menu_enabled() and shell._ask(
            "Also switch back to the standard Windows 11 right-click menu?"), remove_folder=False)
        print("VitePDF was removed from the right-click menu.")
        return 0
    import vp_ui as ui
    extra = None
    if marker and os.name == "nt" and shell.classic_menu_enabled():
        extra = "Also switch back to the standard Windows 11 right-click menu"
    got = ui.confirm_window("Remove VitePDF?", "This removes the right-click menus, the Start "
                            "menu shortcut and the VitePDF folder. Your own files are not touched.",
                            yes="Remove", extra=extra, name="uninstall")
    if got:
        shell.uninstall(restore_menu=got["extra"])
    return 0


def main(argv):
    args = list(argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    first = args[0]
    if first == "--version":
        print(VERSION)
        return 0
    if first == "--about":
        import vp_ui as ui
        ui.about_window()
        return 0
    if first in ("--setup", "--selftest", "--dump-reg", "--installer", "--uninstall",
                 "--uninstall-console"):
        import vp_shell as shell
        here = Path(__file__).resolve().parent
        if first == "--setup":
            return shell.setup(args[1] if len(args) > 1 else here)
        if first == "--selftest":
            return shell.selftest()
        if first == "--dump-reg":
            print(shell.dump_reg(*args[1:3]))
            return 0
        if first == "--installer":
            return _installer(args[1] if len(args) > 1 else here.parent)
        return _uninstall(console=(first == "--uninstall-console"))

    now = False
    extra = {}
    if first == "--now":
        now = True
        args = args[1:]
        for flag in ("--limit", "--password", "--mode", "--size", "--fit"):
            if flag in args:
                i = args.index(flag)
                extra[flag[2:]] = args[i + 1]
                del args[i:i + 2]
        for flag, name in (("--bw", "bw"), ("--keep-password", "keep")):
            if flag in args:
                args.remove(flag)
                extra[name] = True
    if len(args) < 3:
        print(USAGE)
        return 2
    action, option = ALIASES.get(args[0], args[0]), args[1]
    if action in ("capture", "scroll", "blank"):
        return _folder_action(action, args[2])
    if action not in ACTIONS:
        print(USAGE)
        return 2
    files = [os.path.abspath(f) for f in args[2:]]
    # Security: never work from the folder that holds the user's (possibly
    # untrusted) files. Windows may load program parts from the current folder.
    try:
        os.chdir(str(data_dir()))
    except OSError:
        pass
    if not now and action != "presets":
        quiet = 0.5 if action in ("merge", "pdf-organize", "tools") else 0.2
        # One queue per folder: two actions started close together in different
        # folders can never end up in one job.
        import hashlib
        folder = core.path_key(os.path.dirname(files[0])).encode("utf-8", "surrogatepass")
        key = "%s.%s.%s" % (action, option, hashlib.sha256(folder).hexdigest()[:16])
        files = core.collect_batch(key, files[0], quiet)
        if files is None:
            return 0
    return run(action, option, files, interactive=not now, extra=extra)


def entry():
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except BaseException:
        log("fatal:\n" + traceback.format_exc())
        if sys.argv[1:2] and sys.argv[1] in ("--setup", "--uninstall-console", "--selftest", "--now"):
            traceback.print_exc()
        else:
            message_box("VitePDF hit an unexpected problem and could not finish.\n\n"
                        "Details are in:\n%s" % (data_dir() / "vitepdf.log"), warn=True)
        sys.exit(1)
