# VitePDF security notes

Version 1.3.2. Written for anyone who wants to judge whether VitePDF is safe to run.

## What VitePDF can and cannot reach

- It runs as you, with your Windows permissions, only when you start it from the right-click menu.
- It has no network code, no login, no account access and no upload. It reads the files you select and writes results beside them.
- It keeps a small log, your presets and your recent sizes in `%LOCALAPPDATA%\VitePDF`. The log holds no folder or file names and no passwords.

## Checks run on every release

| Check | Tool | Result for 1.3.2 |
| --- | --- | --- |
| Code scan | bandit | No medium or high findings |
| Known vulnerabilities in the pinned libraries | pip-audit | None known on the release date |
| Damaged, truncated, mislabelled and oddly named files | 261 jobs across every tool | No crash, no hang, nothing written outside the folder, no temporary file left |
| Review findings of 17 November 2026 | 30 targeted tests with synthetic files | All pass |
| Conversion regressions | 96 image conversions plus PDF and tool suites | All pass |

These tests run on Linux with the pinned library versions. The Windows menu, the installers and the screen capture are checked by hand on Windows.

## Protections built in

- Only five image decoders are enabled (JPEG, PNG, WEBP, BMP, HEIF), whatever a file claims to be.
- Hard limits: 400 megapixels per picture, 600 MB per file, 3000 pages per PDF.
- The program never runs from the folder of your files, ignores Python environment variables and starts no command shell.
- Libraries are pinned to exact versions with checksums. The Setup builder refuses libraries that are not pinned.
- A signed source copy must carry the author's key (`A88B A544 E686 3A3C 1877 0B0C 3C40 DEBC`) or setup stops.
- Setup.exe tests the new version in a staging folder before it replaces the old one.
- Each folder has its own job queue. A result is written under a temporary name and gets its final name only when complete, without ever replacing a file.
- A result made from a locked PDF is encrypted before it is written; if that fails, nothing is saved.
- Saving a copy of a digitally signed PDF needs your confirmation first.
- Remove hidden data opens its own result again and reports anything it could not remove.

## Accepted risks

- **Decoder flaws.** PDFium, qpdf and the image decoders run in an ordinary user process. A new flaw in one of them, triggered by a prepared file, could run code with your permissions. VitePDF has no sandbox. Mitigation: few decoders, pinned and audited versions, regular updates. Do not process files from sources you do not trust at all.
- **No paid publisher certificate.** Windows SmartScreen cannot name the publisher. Authenticity rests on the author's signature and fingerprint, which you must compare yourself. An unsigned copy shows only that its files match each other.
- **Setup.exe is built on the author's computer** from its Python installation and the pinned libraries. It is not a reproducible build.
- **Two merges in one folder within half a second.** Windows starts one program per selected file and gives no sign of which selection a file belongs to. Different folders are kept apart; inside one folder two such merges share one list. The merge window shows the full list before saving and marks it when the files arrived in two groups. A full fix needs a compiled Windows shell extension, which VitePDF deliberately avoids.
- **Crop hides, it does not delete**, and "Original" keeps camera data inside a JPG. Both are stated in the readme.
- **Command-line passwords** (`--password` with `--now`) can be seen by other programs of the same user while the job runs. The windows never use the command line for passwords.

## Keeping it clean

1. A few times a year, or after a security notice for a pinned library: raise the versions and hashes in `requirements.txt`, run pip-audit, test, build and sign a new release.
2. Never share the signing key. Publish the fingerprint where colleagues can see it independently of the download.
3. Use only made-up files in any public repository or bug report.

## Reporting a problem

Tell the author directly, with the VitePDF version and a made-up file that shows the problem. Do not send real documents.
