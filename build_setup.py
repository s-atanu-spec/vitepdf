#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Builds VitePDF-Setup-<version>.exe: one file that installs VitePDF offline.

Run build-setup.bat on a Windows computer where VitePDF was installed with
install.bat. The Setup file is put together from what is on that computer:

  runtime\\   a private copy of Python (from the python.org installation)
             and the libraries (from VitePDF's own environment)
  app\\       the VitePDF files of this folder
  VitePDF.exe the small starter, compiled from launcher.cs

These are zipped and placed inside a small Setup program compiled from
setup_stub.cs with the C# compiler that is part of Windows. Nothing is
downloaded. The result is written next to this folder.

Created by Atanu Sarkar. Made with Claude.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

LIB_SKIP = {"test", "tests", "idlelib", "turtledemo", "ensurepip", "lib2to3", "site-packages",
            "__pycache__", "venv", "pydoc_data"}
SITE_SKIP = ("pip", "setuptools", "pkg_resources", "_distutils_hack", "wheel", "__pycache__")


def say(text):
    print(text, flush=True)


def find_csc():
    windir = Path(os.environ.get("WINDIR") or r"C:\Windows")
    for fw in ("Framework64", "Framework"):
        cand = windir / "Microsoft.NET" / fw / "v4.0.30319" / "csc.exe"
        if cand.exists():
            return cand
    raise SystemExit("The C# compiler of Windows (.NET Framework 4) was not found.")


def copy_tree(src, dst, skip=()):
    def ignore(_folder, names):
        return [n for n in names if n in skip or n.endswith(".pyc")]
    shutil.copytree(src, dst, ignore=ignore)


def check_libraries(site):
    """Only the pinned libraries, in exactly the pinned versions, may be packed."""
    import importlib.metadata as md
    import re
    pins = {}
    for line in (HERE / "requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", line.strip())
        if m:
            pins[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = m.group(2)
    found = {}
    for dist in md.distributions(path=[str(site)]):
        name = re.sub(r"[-_.]+", "-", dist.metadata["Name"] or "").lower()
        if name in ("pip", "setuptools", "wheel"):
            continue
        found[name] = dist.version
    extra = sorted(set(found) - set(pins))
    wrong = sorted(n for n in pins if found.get(n) != pins[n])
    if extra or wrong:
        raise SystemExit("The libraries on this computer do not match requirements.txt.\n"
                         "Not listed there: %s\nMissing or other version: %s\n"
                         "Run install.bat again, then retry."
                         % (", ".join(extra) or "none", ", ".join(wrong) or "none"))


def make_runtime(stage):
    base = Path(sys.base_prefix)
    if "WindowsApps" in str(base):
        raise SystemExit("This Python comes from the Microsoft Store and cannot be copied.\n"
                         "Install Python 3.13 from python.org, run install.bat again, then retry.")
    for need in ("python.exe", "pythonw.exe", "Lib/os.py", "DLLs/_tkinter.pyd", "tcl"):
        if not (base / need).exists():
            raise SystemExit("The Python installation is not complete (%s is missing): %s"
                             % (need, base))
    runtime = stage / "runtime"
    runtime.mkdir()
    for f in base.iterdir():
        if f.is_file() and f.suffix.lower() in (".exe", ".dll") or f.name == "LICENSE.txt":
            shutil.copy2(f, runtime / f.name)
    copy_tree(base / "DLLs", runtime / "DLLs")
    copy_tree(base / "Lib", runtime / "Lib", LIB_SKIP)
    copy_tree(base / "tcl", runtime / "tcl", {"demos", "__pycache__"})
    site = Path(sysconfig.get_paths()["purelib"])
    check_libraries(site)
    dest = runtime / "Lib" / "site-packages"
    dest.mkdir()
    for item in site.iterdir():
        low = item.name.lower()
        if any(low == s or low.startswith(s + "-") for s in SITE_SKIP) or low.endswith(".pth"):
            continue
        if item.is_dir():
            copy_tree(item, dest / item.name, {"__pycache__"})
        else:
            shutil.copy2(item, dest / item.name)
    # Fixed search path: this Python ignores the registry, environment
    # variables and the current folder, and sees only its own files.
    pth = "python%d%d._pth" % sys.version_info[:2]
    (runtime / pth).write_text("Lib\nDLLs\nLib\\site-packages\n", encoding="ascii")
    return runtime


def make_app(stage):
    import vp_shell
    app = stage / "app"
    app.mkdir()
    lines = []
    for name in vp_shell.APP_FILES:
        if not (HERE / name).is_file():
            raise SystemExit("A file is missing from this folder: %s" % name)
        shutil.copy2(HERE / name, app / name)
        lines.append("%s  %s" % (hashlib.sha256((app / name).read_bytes()).hexdigest(), name))
    (app / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return app


def run(cmd, what):
    res = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if res.returncode != 0:
        say(res.stdout)
        say(res.stderr)
        raise SystemExit("%s failed." % what)


def main():
    if os.name != "nt":
        raise SystemExit("Run this on Windows (build-setup.bat).")
    import vp_core
    version = vp_core.VERSION
    csc = find_csc()
    out = HERE.parent / ("VitePDF-Setup-%s.exe" % version)
    say("")
    say("Building %s" % out.name)
    with tempfile.TemporaryDirectory(prefix="VitePDF-build-", ignore_cleanup_errors=True) as tmp:
        stage = Path(tmp) / "stage"
        stage.mkdir()
        say("[1/5] Copying Python and the libraries ...")
        runtime = make_runtime(stage)
        say("[2/5] Copying VitePDF and building VitePDF.exe ...")
        app = make_app(stage)
        run([csc, "/nologo", "/target:winexe", "/optimize+", "/win32icon:%s" % (HERE / "vitepdf.ico"),
             "/out:%s" % (stage / "VitePDF.exe"), HERE / "launcher.cs"], "Building VitePDF.exe")
        say("[3/5] Testing the copy ...")
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "TCL", "TK"))}
        res = subprocess.run([str(runtime / "python.exe"), "-I", str(app / "vitepdf.py"), "--selftest"],
                             env=env, cwd=str(stage))
        if res.returncode != 0:
            raise SystemExit("The packed copy did not pass its self-test. Nothing was built.")
        for cache in stage.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
        say("[4/5] Packing ...")
        payload = Path(tmp) / "payload.zip"
        count = 0
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in sorted(stage.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(stage).as_posix())
                    count += 1
        say("      %d files, %.1f MB" % (count, payload.stat().st_size / 1e6))
        say("[5/5] Building the Setup file ...")
        new = Path(tmp) / "setup.exe"
        run([csc, "/nologo", "/target:winexe", "/optimize+", "/win32icon:%s" % (HERE / "vitepdf.ico"),
             "/resource:%s,payload.zip" % payload, "/r:System.IO.Compression.dll",
             "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll",
             "/out:%s" % new, HERE / "setup_stub.cs"], "Building the Setup file")
        shutil.copyfile(new, out)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    say("")
    say("Setup file : %s" % out)
    say("Size       : %.1f MB" % (out.stat().st_size / 1e6))
    say("SHA-256    : %s" % digest)
    say("")
    say("Next: run sign-release.bat. It signs this file together with the release ZIP.")
    say("Anyone can then check it:  python vitepdf_sign.py --expect <your fingerprint> verify-file <Setup.exe>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
