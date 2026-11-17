# -*- coding: utf-8 -*-
"""
VitePDF and Windows: right-click menus, installing, removing, self-test.
Everything is registered for the current user only; no admin rights.

Two layouts are supported:
  bundle  (Setup.exe)   <root>\\runtime\\pythonw.exe, <root>\\app, <root>\\VitePDF.exe
  source  (install.bat) <root>\\venv\\Scripts\\pythonw.exe, <root>\\app, <root>\\VitePDF.exe

Created by Atanu Sarkar. Made with Claude.
"""

import io
import json
import os
import sys
import time
from pathlib import Path

import vp_core as core
from vp_core import APP_NAME, AUTHOR, IMAGE_EXTS, PDF_EXTS, PRESETS, VERSION, data_dir, log

MENU_KEY = r"Software\Classes\SystemFileAssociations\%s\shell\VitePDF"
OLD_MENU_KEY = r"Software\Classes\SystemFileAssociations\%s\shell\PDFit"      # version 1.0
FOLDER_KEY = r"Software\Classes\Directory\Background\shell\VitePDF"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\VitePDF"
CLASSIC_MENU_KEY = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}"

APP_FILES = ("vitepdf.py", "vp_core.py", "vp_ops.py", "vp_ui.py", "vp_shell.py", "vp_main.py",
             "vitepdf.ico", "vitepdf.png", "vitepdf_capture.ico", "README.md", "TERMS.txt",
             "LICENSE.txt")
SOURCE_ONLY = ("requirements.txt", "uninstall.bat", "launcher.cs")


# --------------------------------------------------------------------------
# The menu
# --------------------------------------------------------------------------

def menu_tree(launch, icon, kind):
    """kind: "image", "pdf" or "folder". launch: start of every command line."""
    import vp_ops as ops

    def leaf(label, action, option="x", single=False, target='"%1"'):
        return {"MUIVerb": label, "MultiSelectModel": "Single" if single else "Player",
                "command": "%s %s %s %s" % (launch, action, option, target)}

    def group(label, leaves):
        shell = {}
        for i, item in enumerate(leaves, 1):
            shell["%02d" % i] = item
        return {"MUIVerb": label, "MultiSelectModel": "Player", "SubCommands": "", "shell": shell}

    def sizes(action, presets, each=False):
        out = []
        for p in presets:
            label = "Best quality" if p == "best" else PRESETS[p]["label"]
            out.append(leaf(label + (" each" if each and PRESETS.get(p, {}).get("limit") else ""),
                            action, p))
        return out + [leaf("Custom size", action, "custom")]

    about = {"MUIVerb": "About VitePDF", "MultiSelectModel": "Single", "CommandFlags": 0x20,
             "command": "%s --about" % launch}
    if kind == "folder":
        shell = {
            "01_capture": {"MUIVerb": "Capture area to PDF", "command": '%s capture x "%%V"' % launch},
            "02_blank": {"MUIVerb": "New blank PDF", "command": '%s blank x "%%V"' % launch},
            "09_about": about,
        }
        return {"MUIVerb": APP_NAME, "Icon": str(icon), "SubCommands": "", "shell": shell}

    # Windows shows at most 16 entries (groups and their items together) in a
    # menu built this way and silently drops the rest. Keep every menu at 14
    # or fewer; everything else lives in the "More tools" window.
    common = {
        "03_merge": leaf("Merge into one PDF" if kind == "image" else "Merge", "merge", "ask"),
        "09_tools": leaf("More tools", "tools"),
    }
    if kind == "image":
        shell = {
            "01_topdf": group("To PDF", sizes("img-each", ("original", "optimized", "under1mb"))),
            "02_compress": group("Compress image", sizes("img-compress",
                                                         ("optimized", "under1mb", "under200kb"))),
            "04_tojpg": leaf("Convert to JPG", "img-convert", "jpg"),
        }
    else:
        shell = {
            "01_compress": group("Compress", sizes("pdf-compress",
                                                   ("optimized", "under1mb", "under350kb"))),
            "04_tojpg": leaf("To JPG", "pdf-tojpg", "ask"),
            "05_organize": leaf("Organize pages", "pdf-organize", single=True),
            "06_password": leaf("Password", "pdf-password"),
        }
    shell.update(common)
    shell = dict(sorted(shell.items()))
    return {"MUIVerb": APP_NAME, "Icon": str(icon), "MultiSelectModel": "Player",
            "SubCommands": "", "shell": shell}


def _reg_lines(path, spec, out):
    out.append("[HKEY_CURRENT_USER\\%s]" % path)
    for name, val in spec.items():
        if name in ("shell", "command"):
            continue
        if isinstance(val, int):
            out.append('"%s"=dword:%08x' % (name, val))
        else:
            out.append('"%s"="%s"' % (name, val.replace("\\", "\\\\").replace('"', '\\"')))
    out.append("")
    if "command" in spec:
        out.append("[HKEY_CURRENT_USER\\%s\\command]" % path)
        out.append('@="%s"' % spec["command"].replace("\\", "\\\\").replace('"', '\\"'))
        out.append("")
    for sub, subspec in spec.get("shell", {}).items():
        _reg_lines("%s\\shell\\%s" % (path, sub), subspec, out)


def dump_reg(launch, icon):
    """The whole menu as a .reg file, for inspection or manual repair."""
    out = ["Windows Registry Editor Version 5.00", ""]
    for ext in IMAGE_EXTS:
        _reg_lines(MENU_KEY % ext, menu_tree(launch, icon, "image"), out)
    for ext in PDF_EXTS:
        _reg_lines(MENU_KEY % ext, menu_tree(launch, icon, "pdf"), out)
    _reg_lines(FOLDER_KEY, menu_tree(launch, icon, "folder"), out)
    return "\r\n".join(out)


def _reg_write(winreg, path, spec):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE) as k:
        for name, val in spec.items():
            if name in ("shell", "command"):
                continue
            if isinstance(val, int):
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, val)
            else:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
    if "command" in spec:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path + "\\command", 0, winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, spec["command"])
    for sub, subspec in spec.get("shell", {}).items():
        _reg_write(winreg, "%s\\shell\\%s" % (path, sub), subspec)


def _reg_delete(winreg, path):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _reg_delete(winreg, path + "\\" + sub)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        return True
    except FileNotFoundError:
        return False


def _notify_shell():
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:
        pass


def install_menu(launch, icon):
    import winreg
    for ext in IMAGE_EXTS + PDF_EXTS:
        _reg_delete(winreg, OLD_MENU_KEY % ext)
        _reg_delete(winreg, MENU_KEY % ext)
        _reg_write(winreg, MENU_KEY % ext,
                   menu_tree(launch, icon, "pdf" if ext in PDF_EXTS else "image"))
    _reg_delete(winreg, FOLDER_KEY)
    _reg_write(winreg, FOLDER_KEY, menu_tree(launch, icon, "folder"))
    (data_dir() / "install.json").write_text(json.dumps({"launch": launch, "icon": str(icon)}),
                                             encoding="utf-8")
    _notify_shell()


def refresh_menu():
    """Write the menu again, for example after a preset was renamed."""
    if os.name != "nt":
        return
    info = json.loads((data_dir() / "install.json").read_text(encoding="utf-8"))
    install_menu(info["launch"], info["icon"])


def uninstall_menu():
    import winreg
    for ext in IMAGE_EXTS + PDF_EXTS:
        _reg_delete(winreg, MENU_KEY % ext)
        _reg_delete(winreg, OLD_MENU_KEY % ext)
    _reg_delete(winreg, FOLDER_KEY)
    _reg_delete(winreg, UNINSTALL_KEY)
    _notify_shell()


def register_program(root, icon, uninstall_command):
    """List VitePDF under Settings > Apps, with its logo and author."""
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_WRITE) as k:
        for name, val in (("DisplayName", APP_NAME), ("DisplayVersion", VERSION),
                          ("Publisher", AUTHOR), ("DisplayIcon", str(icon)),
                          ("InstallLocation", str(root)), ("UninstallString", uninstall_command)):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


def _system(name):
    """Full path of a Windows system program (never looked up on the PATH)."""
    windir = Path(os.environ.get("SystemRoot") or r"C:\Windows")
    if name == "explorer.exe":
        return str(windir / name)
    if name == "powershell.exe":
        return str(windir / "System32" / "WindowsPowerShell" / "v1.0" / name)
    return str(windir / "System32" / name)


def _quiet():
    import subprocess
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
            "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def _shortcut_path():
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "VitePDF.lnk"


CAPTURE_HOTKEY = "CTRL+ALT+SHIFT+P"


def _capture_shortcut_path():
    return _shortcut_path().with_name("VitePDF Capture area.lnk")


def make_shortcut(exe):
    """Start menu shortcuts: VitePDF, and "Capture area" with a keyboard
    shortcut that works in any program. Values travel in environment
    variables, so no path ever becomes part of a command."""
    import subprocess
    env = dict(os.environ, VP_LNK=str(_shortcut_path()), VP_EXE=str(exe), VP_DIR=str(Path(exe).parent),
               VP_LNK2=str(_capture_shortcut_path()), VP_KEY=CAPTURE_HOTKEY,
               VP_ICO2=str(Path(exe).parent / "app" / "vitepdf_capture.ico"))
    script = ("$w=New-Object -ComObject WScript.Shell;"
              "$s=$w.CreateShortcut($env:VP_LNK);"
              "$s.TargetPath=$env:VP_EXE;$s.WorkingDirectory=$env:VP_DIR;"
              "$s.Description='VitePDF: right-click image and PDF tools';$s.Save();"
              "$c=$w.CreateShortcut($env:VP_LNK2);"
              "$c.TargetPath=$env:VP_EXE;$c.Arguments='capture x desktop';"
              "$c.WorkingDirectory=$env:VP_DIR;$c.Hotkey=$env:VP_KEY;$c.IconLocation=$env:VP_ICO2;"
              "$c.Description='Capture an area of the screen to a PDF';$c.Save()")
    try:
        subprocess.run([_system("powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", script],
                       env=env, timeout=60, **_quiet())
    except Exception as e:
        log("shortcut failed: %r" % (e,))


def build_launcher(root, app):
    """Compile VitePDF.exe (a tiny starter with the logo) with the C# compiler
    that is part of Windows. Returns the exe path or None."""
    import subprocess
    exe = root / "VitePDF.exe"
    try:
        windir = Path(os.environ.get("WINDIR") or r"C:\Windows")
        csc = None
        for fw in ("Framework64", "Framework"):
            cand = windir / "Microsoft.NET" / fw / "v4.0.30319" / "csc.exe"
            if cand.exists():
                csc = cand
                break
        if csc is None:
            return exe if exe.exists() else None
        tmp = root / "VitePDF.new.exe"
        res = subprocess.run([str(csc), "/nologo", "/target:winexe", "/optimize+",
                              "/win32icon:%s" % (app / "vitepdf.ico"), "/out:%s" % tmp,
                              str(app / "launcher.cs")], capture_output=True, text=True)
        if res.returncode != 0 or not tmp.exists():
            log("launcher build failed: %s %s" % (res.stdout, res.stderr))
            return exe if exe.exists() else None
        os.replace(tmp, exe)
        return exe
    except Exception as e:
        log("launcher build failed: %r" % (e,))
        return exe if exe.exists() else None


# --------------------------------------------------------------------------
# Windows 11 classic menu
# --------------------------------------------------------------------------

def is_windows11():
    return os.name == "nt" and sys.getwindowsversion().build >= 22000


def classic_menu_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLASSIC_MENU_KEY + r"\InprocServer32"):
            return True
    except OSError:
        return False


def set_classic_menu(on):
    import winreg
    marker = data_dir() / "classic-menu-set"
    if on:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CLASSIC_MENU_KEY + r"\InprocServer32",
                                0, winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "")
        marker.write_text("1")
    else:
        _reg_delete(winreg, CLASSIC_MENU_KEY)
        if marker.exists():
            marker.unlink()


def restart_explorer():
    import subprocess
    subprocess.run([_system("taskkill.exe"), "/f", "/im", "explorer.exe"], **_quiet())
    time.sleep(2.0)
    listing = subprocess.run([_system("tasklist.exe"), "/fi", "imagename eq explorer.exe"],
                             capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.lower()
    if "explorer.exe" not in listing:       # Windows did not bring it back itself
        subprocess.Popen([_system("explorer.exe")])


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------

# A 64 x 64 HEIC picture, used by the self-test.
_TINY_HEIC = (
    "AAAAHGZ0eXBoZWljAAAAAG1pZjFoZWljbWlhZgAAAVZtZXRhAAAAAAAAACFoZGxyAAAAAAAAAABw"
    "aWN0AAAAAAAAAAAAAAAAAAAAACJpbG9jAAAAAERAAAEAAQAAAAABegABAAAAAAAAAB0AAAAjaWlu"
    "ZgAAAAAAAQAAABVpbmZlAgAAAAABAABodmMxAAAAAA5waXRtAAAAAAABAAAA1mlwcnAAAAC3aXBj"
    "bwAAAHhodmNDAQNwAAAAkAAAAAAAHvAA/P34+AAADwNgAAEAGEABDAH//wNwAAADAJAAAAMAAAMA"
    "HroCQGEAAQArQgEBA3AAAAMAkAAAAwAAAwAeoCCBBZbqSSmubgIaDAgAAAMAyAAAAwAIQGIAAQAH"
    "RAHBcrAiQAAAABNjb2xybmNseAABAA0ABoAAAAAUaXNwZQAAAAAAAABAAAAAQAAAABBwaXhpAAAA"
    "AAMICAgAAAAXaXBtYQAAAAAAAAABAAEEgQIDBAAAACVtZGF0AAAAGSgBrxOA5qhw0//+D9RX/XRq"
    "/7F6rSeb98A="
)


def selftest(quiet=False):
    """Check that every library works on this computer. Raises on failure."""
    import base64
    import tempfile
    import vp_ops as ops
    Image = core._pil()
    pikepdf = core._pikepdf()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        im = Image.new("RGB", (640, 480), (30, 90, 160))
        im.save(tmp / "a.jpg", quality=90)
        im.save(tmp / "b.png")
        (tmp / "c.heic").write_bytes(base64.b64decode("".join(_TINY_HEIC)))
        items = [core.SourceImage(tmp / n) for n in ("a.jpg", "b.png", "c.heic")]
        data = core.images_to_pdf(items, "original")[0]
        def need(ok, what):
            if not ok:
                raise RuntimeError("Self-test failed: %s" % what)

        with pikepdf.open(io.BytesIO(data)) as pdf:
            need(len(pdf.pages) == 3, "pictures to PDF")
        out = core.compress_pdf(core._opener([data]), "optimized")[0]
        with pikepdf.open(io.BytesIO(out)) as pdf:
            need(len(pdf.pages) == 3, "PDF compression")
        page = ops.render_page(ops.open_for_render(data), 0, dpi=72)
        need(page.size[0] > 100, "PDF page rendering")
        need(len(ops.strip_jpeg((tmp / "a.jpg").read_bytes())) > 100, "picture clean-up")
    import tkinter  # noqa: F401
    import customtkinter  # noqa: F401
    if not quiet:
        print("      Self-test passed (JPG, PNG, HEIC, PDF pages, windows).")
    return 0


# --------------------------------------------------------------------------
# Installing from source (install.bat) and from Setup.exe
# --------------------------------------------------------------------------

def _venv_python(venv, windowed=False):
    if os.name == "nt":
        return venv / "Scripts" / ("pythonw.exe" if windowed else "python.exe")
    return venv / "bin" / "python"


def _ask(question, default=True):
    try:
        answer = input("%s [%s] " % (question, "Y/n" if default else "y/N")).strip().lower()
    except EOFError:
        return default
    return default if not answer else answer.startswith("y")


def _copy_app(src, app, names):
    app.mkdir(parents=True, exist_ok=True)
    for name in names:
        if (src / name).exists():           # plain byte copy: no "downloaded" mark comes along
            (app / name).write_bytes((src / name).read_bytes())


def _remove_old_version(root):
    """Version 1.0 was called PDFit: remove its folder, keep its menu choice."""
    import shutil
    old = root.parent / "PDFit"
    # Only a folder that really is the old program: it must hold its script.
    if old.is_dir() and not old.is_symlink() and (old / "app" / "pdfit.py").is_file():
        if (old / "classic-menu-set-by-pdfit").exists():
            (root / "classic-menu-set").write_text("1")
        shutil.rmtree(old, ignore_errors=True)


def setup(src):
    """Install or update from the source folder. Called by install.bat."""
    import subprocess
    src = Path(src).resolve()
    root = data_dir()
    app, venv = root / "app", root / "venv"
    print("")
    print("%s %s setup (from source)" % (APP_NAME, VERSION))
    print("Install folder: %s" % root)
    if (src / "SHA256SUMS.sig").exists():
        print("")
        print("Checking the release signature ...")
        # The signature must come from the author's key, not from any key.
        from vp_core import AUTHOR_KEY
        subprocess.run([sys.executable, "-I", str(src / "vitepdf_sign.py"),
                        "--expect", AUTHOR_KEY, "verify", str(src)], check=True)
    else:
        print("NOTE: this copy is NOT signed by the author. Its checksums only show that")
        print("      the files match each other, not who made them. Install it only if")
        print("      you got it directly from the author.")
    print("")
    print("[1/5] Preparing a private Python environment ...")
    vpy = _venv_python(venv)
    if vpy.exists():
        # Rebuild the environment when it was made by another Python version,
        # so an update of Python really reaches VitePDF.
        try:
            have = subprocess.run([str(vpy), "-I", "-c", "import sys; print(sys.version.split()[0])"],
                                  capture_output=True, text=True).stdout.strip()
        except OSError:
            have = ""
        if have != sys.version.split()[0]:
            import shutil
            shutil.rmtree(venv, ignore_errors=True)
            if venv.exists():
                raise SystemExit("VitePDF is in use. Close its windows and run install.bat again.")
    if not vpy.exists():
        subprocess.run([sys.executable, "-I", "-m", "venv", str(venv)], check=True)
    print("[2/5] Installing the libraries (needs internet, about 30 MB) ...")
    subprocess.run([str(vpy), "-I", "-m", "pip", "--isolated", "install",
                    "--disable-pip-version-check", "--no-warn-script-location",
                    "--only-binary", ":all:", "--no-deps", "--require-hashes",
                    "-r", str(src / "requirements.txt")], check=True)
    print("[3/5] Copying VitePDF and running a self-test ...")
    _copy_app(src, app, APP_FILES + SOURCE_ONLY)
    subprocess.run([str(vpy), "-I", str(app / "vitepdf.py"), "--selftest"], check=True)
    subprocess.run([str(vpy), "-I", "-m", "compileall", "-q", str(app)])   # faster first start
    if os.name != "nt":
        print("[4/5] and [5/5] skipped: not running on Windows")
        return 0
    import shutil
    shutil.rmtree(root / "runtime", ignore_errors=True)     # left by an earlier Setup.exe
    print("[4/5] Building VitePDF.exe ...")
    exe = build_launcher(root, app)
    if exe:
        launch, icon = '"%s"' % exe, exe
    else:
        print("      Could not build the exe; the menu will start Python directly.")
        launch = '"%s" -I "%s"' % (_venv_python(venv, windowed=True), app / "vitepdf.py")
        icon = app / "vitepdf.ico"
    print("[5/5] Adding VitePDF to the right-click menu and to Settings > Apps ...")
    install_menu(launch, icon)
    register_program(root, icon, '"%s"' % (app / "uninstall.bat"))
    if exe:
        make_shortcut(exe)
    _remove_old_version(root)
    if is_windows11() and not classic_menu_enabled():
        print("")
        print("Windows 11 hides custom entries under 'Show more options'.")
        if _ask("Switch to the classic full menu, so VitePDF shows at the top level?"):
            set_classic_menu(True)
            print("File Explorer restarts now. Open folder windows will close.")
            input("Press Enter to continue ...")
            restart_explorer()
    print("")
    print("Done. Right-click a picture, a PDF, or empty space in a folder and choose VitePDF.")
    return 0


INSTALL_STEPS = ["Check the files", "Copy VitePDF", "Test", "Add the right-click menu", "Finish"]


def install_bundle(src, step, options):
    """Install from an unpacked Setup.exe payload: runtime, app, VitePDF.exe."""
    import shutil
    src = Path(src)
    root = data_dir()
    step(0)
    for name in ("runtime/pythonw.exe", "app/vitepdf.py", "app/vp_core.py", "VitePDF.exe"):
        if not (src / name).is_file():
            raise RuntimeError("The installer is incomplete (%s is missing)." % name)
    sums = src / "app" / "SHA256SUMS.txt"
    if sums.exists():
        import hashlib
        for line in sums.read_text(encoding="utf-8").splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and (src / "app" / parts[1]).is_file():
                digest = hashlib.sha256((src / "app" / parts[1]).read_bytes()).hexdigest()
                if digest != parts[0].lower():
                    raise RuntimeError("A file inside the installer was changed: %s" % parts[1])
    step(1)
    if os.name == "nt":
        # Staged update: copy the new version beside the old one, test it
        # there, and only then swap. A failed test leaves the old version.
        import subprocess
        new = root / "staging"
        shutil.rmtree(new, ignore_errors=True)
        if new.exists():
            raise RuntimeError("VitePDF is in use. Close its windows and run Setup again.")
        shutil.copytree(src / "runtime", new / "runtime")
        shutil.copytree(src / "app", new / "app")
        shutil.copyfile(src / "VitePDF.exe", new / "VitePDF.exe")
        step(2)
        test = subprocess.run([str(new / "runtime" / "pythonw.exe"), "-I",
                               str(new / "app" / "vitepdf.py"), "--selftest"],
                              cwd=str(new), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if test.returncode != 0:
            shutil.rmtree(new, ignore_errors=True)
            raise RuntimeError("The new version did not pass its test. Nothing was changed.")
        # Prepare the program files now, so the first window opens quickly.
        try:
            subprocess.run([str(new / "runtime" / "pythonw.exe"), "-I", "-m", "compileall", "-q",
                            str(new / "app"), str(new / "runtime" / "Lib" / "site-packages")],
                           cwd=str(new), timeout=300,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            log("pre-compiling skipped: %r" % (e,))
        old = root / "previous"
        shutil.rmtree(old, ignore_errors=True)
        moved = []
        try:
            for name in ("runtime", "venv", "app", "VitePDF.exe"):
                if (root / name).exists():
                    old.mkdir(exist_ok=True)
                    os.replace(root / name, old / name)
                    moved.append(name)
            for name in ("runtime", "app", "VitePDF.exe"):
                os.replace(new / name, root / name)
        except OSError:
            for name in moved:                      # put the old version back
                try:
                    if (root / name).is_dir():
                        shutil.rmtree(root / name, ignore_errors=True)
                    elif (root / name).exists():
                        (root / name).unlink()
                    os.replace(old / name, root / name)
                except OSError:
                    pass
            shutil.rmtree(new, ignore_errors=True)
            raise RuntimeError("VitePDF is in use. Close its windows and run Setup again.")
        shutil.rmtree(old, ignore_errors=True)
        shutil.rmtree(new, ignore_errors=True)
    else:
        step(2)
        selftest(quiet=True)
    step(3)
    restart = False
    if os.name == "nt":
        exe = root / "VitePDF.exe"
        install_menu('"%s"' % exe, exe)
        register_program(root, exe, '"%s" --uninstall' % exe)
        make_shortcut(exe)
        _remove_old_version(root)
        if options.get("classic") and is_windows11() and not classic_menu_enabled():
            set_classic_menu(True)
            restart = True
    step(4)
    if restart:
        restart_explorer()
    time.sleep(0.4)
    return 0


def uninstall(restore_menu=False, remove_folder=True):
    """Remove menus, shortcut and Settings > Apps entry; then the folder."""
    if os.name != "nt":
        return 0
    import subprocess
    root = data_dir()
    uninstall_menu()
    for link in (_shortcut_path(), _capture_shortcut_path()):
        try:
            link.unlink()
        except OSError:
            pass
    if restore_menu and classic_menu_enabled():
        set_classic_menu(False)
        restart_explorer()
    if remove_folder:
        # This program runs from inside the folder, so Windows removes the
        # folder a few seconds after we have closed.
        # The command line is handed over as one string, exactly as written.
        command = '"%s" /d /c ping -n 4 127.0.0.1 >nul & rmdir /s /q "%s"' % (_system("cmd.exe"), root)
        subprocess.Popen(command, cwd=os.environ.get("TEMP") or str(root.parent),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) |
                         getattr(subprocess, "DETACHED_PROCESS", 0))
    return 0
