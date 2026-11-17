#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VitePDF release signing tool. Needs nothing but Python.

  vitepdf_sign.py keygen                 create the author's signing key (once)
  vitepdf_sign.py sums    <folder>       write SHA256SUMS.txt
  vitepdf_sign.py sign    <folder>       write SHA256SUMS.txt and SHA256SUMS.sig
  vitepdf_sign.py verify  <folder>       check both; exit code 0 means good
  vitepdf_sign.py release <folder>       sign, then build the ZIP and its checksum
  vitepdf_sign.py sign-file   <file>     sign one file, for example the Setup.exe
  vitepdf_sign.py verify-file <file>     check one signed file

How it works
  SHA256SUMS.txt lists the SHA-256 checksum of every file of a release.
  SHA256SUMS.sig is an Ed25519 signature of that list, made with the author's
  private key. Anyone can check it with the public key; only the holder of
  the private key can make it. The key's fingerprint identifies the author.

The private key lives in  Documents\\VitePDF-signing\\vitepdf-signing.key
(or the path given with --key). Keep it private and keep a backup: whoever
has it can sign as you, and without it you cannot sign under the same
fingerprint again.

Created by Atanu Sarkar. Made with Claude.
"""

import hashlib
import os
import re
import sys
import zipfile
from pathlib import Path

SIGNER = "Atanu Sarkar"
SUMS = "SHA256SUMS.txt"
SIG = "SHA256SUMS.sig"
SKIP = {SUMS, SIG}

# --------------------------------------------------------------------------
# Ed25519 (RFC 8032), following the reference algorithm of the RFC.
# Plain Python: fine for signing a release offline, not meant for servers.
# --------------------------------------------------------------------------

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _inv(x):
    return pow(x, _P - 2, _P)


def _add(a, b):
    aa = (a[1] - a[0]) * (b[1] - b[0]) % _P
    bb = (a[1] + a[0]) * (b[1] + b[0]) % _P
    cc = 2 * a[3] * b[3] * _D % _P
    dd = 2 * a[2] * b[2] % _P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s, pt):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _equal(a, b):
    return ((a[0] * b[2] - b[0] * a[2]) % _P == 0 and
            (a[1] * b[2] - b[1] * a[2]) % _P == 0)


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(pt):
    zinv = _inv(pt[2])
    x, y = pt[0] * zinv % _P, pt[1] * zinv % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(data):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _expand(seed):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _hash_mod_l(data):
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % _L


def ed_public(seed):
    a, _prefix = _expand(seed)
    return _compress(_mul(a, _G))


def ed_sign(seed, msg):
    a, prefix = _expand(seed)
    pub = _compress(_mul(a, _G))
    r = _hash_mod_l(prefix + msg)
    rs = _compress(_mul(r, _G))
    h = _hash_mod_l(rs + pub + msg)
    s = (r + h * a) % _L
    return rs + s.to_bytes(32, "little")


def ed_verify(pub, msg, sig):
    if len(pub) != 32 or len(sig) != 64:
        return False
    a = _decompress(pub)
    r = _decompress(sig[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _L:
        return False
    h = _hash_mod_l(sig[:32] + pub + msg)
    return _equal(_mul(s, _G), _add(r, _mul(h, a)))


# --------------------------------------------------------------------------
# Keys, checksums, signatures
# --------------------------------------------------------------------------

def fingerprint(pub):
    h = hashlib.sha256(pub).hexdigest().upper()[:32]
    return " ".join(h[i:i + 4] for i in range(0, 32, 4))


def default_key_path():
    return Path.home() / "Documents" / "VitePDF-signing" / "vitepdf-signing.key"


def load_key(path):
    text = Path(path).read_text(encoding="ascii")
    m = re.search(r"^seed=([0-9a-fA-F]{64})\s*$", text, re.M)
    if not m:
        raise SystemExit("This is not a VitePDF signing key: %s" % path)
    return bytes.fromhex(m.group(1))


def keygen(path):
    path = Path(path)
    if path.exists():
        raise SystemExit("A key already exists here and was left untouched:\n  %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = os.urandom(32)
    pub = ed_public(seed)
    path.write_text("VITEPDF-SIGNING-KEY-1\n"
                    "# PRIVATE. Never share this file. Keep a backup in a safe place.\n"
                    "signer=%s\nseed=%s\npublic=%s\n" % (SIGNER, seed.hex(), pub.hex()),
                    encoding="ascii")
    path.with_suffix(".pub").write_text(
        "VITEPDF-PUBLIC-KEY-1\nsigner=%s\npublic=%s\nfingerprint=%s\n"
        % (SIGNER, pub.hex(), fingerprint(pub)), encoding="ascii")
    print("New signing key created:")
    print("  private key : %s   (keep private, keep a backup)" % path)
    print("  public key  : %s" % path.with_suffix(".pub"))
    print("  fingerprint : %s" % fingerprint(pub))
    print("Publish the fingerprint where people can see it (README, GitHub profile).")
    return seed


def release_files(folder):
    folder = Path(folder)
    return sorted(p.name for p in folder.iterdir()
                  if p.is_file() and p.name not in SKIP and not p.name.endswith(".pyc"))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_sums(folder):
    folder = Path(folder)
    lines = ["%s  %s" % (sha256_file(folder / n), n) for n in release_files(folder)]
    (folder / SUMS).write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return len(lines)


def check_sums(folder):
    """Returns a list of problems; empty means every file matches."""
    folder = Path(folder)
    problems, listed = [], set()
    try:
        text = (folder / SUMS).read_text(encoding="utf-8")
    except OSError:
        return ["%s is missing" % SUMS]
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            problems.append("unreadable line in %s" % SUMS)
            continue
        name = parts[1].lstrip("*")
        if "/" in name or "\\" in name or ":" in name or ".." in name:
            problems.append("suspicious file name: %s" % name)
            continue
        listed.add(name)
        if not (folder / name).is_file():
            problems.append("missing: %s" % name)
        elif sha256_file(folder / name) != parts[0].lower():
            problems.append("changed or damaged: %s" % name)
    for name in release_files(folder):
        if name not in listed:
            problems.append("not covered by the checksums: %s" % name)
    return problems


def sign_folder(folder, key_path):
    folder = Path(folder)
    seed = load_key(key_path) if Path(key_path).exists() else keygen(key_path)
    count = write_sums(folder)
    pub = ed_public(seed)
    sig = ed_sign(seed, (folder / SUMS).read_bytes())
    (folder / SIG).write_bytes(("VITEPDF-SIGNATURE-1\nsigner=%s\npublic=%s\nsignature=%s\n"
                                % (SIGNER, pub.hex(), sig.hex())).encode("ascii"))
    print("Signed %d files in %s" % (count, folder))
    print("Key fingerprint: %s" % fingerprint(pub))
    return pub


def verify_folder(folder, expect=None):
    folder = Path(folder)
    problems = check_sums(folder)
    if problems:
        print("CHECKSUM PROBLEM:")
        for p in problems:
            print("  " + p)
        return False
    print("Checksums: all files match.")
    if not (folder / SIG).exists():
        print("Signature: none (this copy is not signed).")
        return expect is None
    text = (folder / SIG).read_text(encoding="ascii", errors="replace")
    mp = re.search(r"^public=([0-9a-fA-F]{64})\s*$", text, re.M)
    ms = re.search(r"^signature=([0-9a-fA-F]{128})\s*$", text, re.M)
    if not mp or not ms:
        print("SIGNATURE PROBLEM: %s is not readable." % SIG)
        return False
    pub = bytes.fromhex(mp.group(1))
    if not ed_verify(pub, (folder / SUMS).read_bytes(), bytes.fromhex(ms.group(1))):
        print("SIGNATURE PROBLEM: the signature does not match these files.")
        return False
    print("Signature: valid.")
    print("Signed with key fingerprint: %s" % fingerprint(pub))
    if expect:
        want = re.sub(r"[^0-9A-Fa-f]", "", expect).upper()
        have = fingerprint(pub).replace(" ", "")
        if want != have and want != pub.hex().upper():
            print("SIGNATURE PROBLEM: signed by a different key than expected.")
            return False
        print("This is the expected key.")
    else:
        print("Compare this fingerprint with the one the author published.")
    return True


def build_release(folder, key_path):
    folder = Path(folder).resolve()
    sign_folder(folder, key_path)
    if not verify_folder(folder):
        raise SystemExit("The freshly signed folder did not verify. Nothing was packed.")
    version = "0.0.0"
    main = folder / "vp_core.py"
    if main.exists():
        m = re.search(r'^VERSION = "([^"]+)"', main.read_text(encoding="utf-8"), re.M)
        if m:
            version = m.group(1)
    top = "VitePDF-%s" % version
    out = folder.parent / (top + ".zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in release_files(folder) + [SUMS, SIG]:
            z.write(folder / name, "%s/%s" % (top, name))
    digest = sha256_file(out)
    Path(str(out) + ".sha256").write_bytes(("%s  %s\n" % (digest, out.name)).encode("ascii"))
    print("")
    print("Release file : %s" % out)
    print("SHA-256      : %s" % digest)
    print("Publish the ZIP together with its SHA-256 and your key fingerprint.")
    for setup in sorted(folder.parent.glob("VitePDF-Setup-%s.exe" % version)):
        print("")
        sign_file(setup, key_path)
    return out


def sign_file(path, key_path):
    """Writes <file>.sha256 and <file>.sig next to one file."""
    path = Path(path)
    seed = load_key(key_path) if Path(key_path).exists() else keygen(key_path)
    line = ("%s  %s\n" % (sha256_file(path), path.name)).encode("utf-8")
    Path(str(path) + ".sha256").write_bytes(line)
    pub = ed_public(seed)
    Path(str(path) + ".sig").write_bytes(
        ("VITEPDF-SIGNATURE-1\nsigner=%s\npublic=%s\nsignature=%s\n"
         % (SIGNER, pub.hex(), ed_sign(seed, line).hex())).encode("ascii"))
    print("Signed file  : %s" % path)
    print("SHA-256      : %s" % line.decode("utf-8").split()[0])
    print("Key fingerprint: %s" % fingerprint(pub))
    print("Share the .exe together with its .sha256 and .sig files.")
    return pub


def verify_file(path, expect=None):
    path = Path(path)
    try:
        line = Path(str(path) + ".sha256").read_bytes()
        text = Path(str(path) + ".sig").read_text(encoding="ascii", errors="replace")
    except OSError:
        print("SIGNATURE PROBLEM: the .sha256 or .sig file is missing.")
        return False
    if line.decode("utf-8", "replace").split()[:1] != [sha256_file(path)]:
        print("CHECKSUM PROBLEM: the file was changed or damaged.")
        return False
    print("Checksum: the file matches.")
    mp = re.search(r"^public=([0-9a-fA-F]{64})\s*$", text, re.M)
    ms = re.search(r"^signature=([0-9a-fA-F]{128})\s*$", text, re.M)
    if not mp or not ms:
        print("SIGNATURE PROBLEM: the .sig file is not readable.")
        return False
    pub = bytes.fromhex(mp.group(1))
    if not ed_verify(pub, line, bytes.fromhex(ms.group(1))):
        print("SIGNATURE PROBLEM: the signature does not match this file.")
        return False
    print("Signature: valid.")
    print("Signed with key fingerprint: %s" % fingerprint(pub))
    if expect:
        want = re.sub(r"[^0-9A-Fa-f]", "", expect).upper()
        if want != fingerprint(pub).replace(" ", "") and want != pub.hex().upper():
            print("SIGNATURE PROBLEM: signed by a different key than expected.")
            return False
        print("This is the expected key.")
    else:
        print("Compare this fingerprint with the one the author published.")
    return True


def main(argv):
    args = list(argv)
    key = default_key_path()
    expect = None
    for flag in ("--key", "--expect"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                raise SystemExit("%s needs a value" % flag)
            if flag == "--key":
                key = Path(args[i + 1])
            else:
                expect = args[i + 1]
            del args[i:i + 2]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd == "keygen":
        keygen(key)
        return 0
    if cmd in ("sign-file", "verify-file"):
        if len(args) < 2 or not Path(args[1]).is_file():
            raise SystemExit("Please name the file.")
        if cmd == "sign-file":
            sign_file(args[1], key)
            return 0
        return 0 if verify_file(args[1], expect) else 1
    if len(args) < 2:
        raise SystemExit("Please name the release folder.")
    folder = Path(args[1])
    if not folder.is_dir():
        raise SystemExit("Not a folder: %s" % folder)
    if cmd == "sums":
        print("Wrote %s for %d files." % (SUMS, write_sums(folder)))
        return 0
    if cmd == "sign":
        sign_folder(folder, key)
        return 0
    if cmd == "verify":
        return 0 if verify_folder(folder, expect) else 1
    if cmd == "release":
        build_release(folder, key)
        return 0
    raise SystemExit("Unknown command: %s" % cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
