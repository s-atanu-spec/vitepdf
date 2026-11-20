# VitePDF security notes

Version 1.4.0. Written for anyone who wants to judge whether VitePDF is safe to run.

## What VitePDF can and cannot reach

- It runs as you, with your Windows permissions, only when you start it from the right-click menu.
- It has no network code, no login, no account access and no upload. It reads the files you select and writes results beside them.
- The two capture tools look at the screen, only inside the box you draw and only while the capture is open.
- **VitePDF Scroll may turn the mouse wheel** so that the page under the pointer scrolls. This is the only input VitePDF ever sends to another program. It sends no clicks and no keys, never moves the pointer, and stops the moment you move the mouse, press Esc or press Finish. It does not read text from other programs and does not use the clipboard.
- It keeps a small log, your presets and your recent sizes in `%LOCALAPPDATA%\VitePDF`. The log holds no folder or file names and no passwords.

## Checks run on every release

| Check | Tool | Result for 1.4.0 |
| --- | --- | --- |
| Code scan | bandit | No medium or high findings |
| Known vulnerabilities in the pinned libraries | pip-audit | None known on the release date |
| Damaged, truncated, mislabelled and oddly named files | 261 jobs across every tool | No crash, no hang, nothing written outside the folder, no temporary file left |
| Review findings of 17 November 2026 | 30 targeted tests with synthetic files | All pass |
| Conversion regressions | 96 image conversions plus PDF and tool suites | All pass |
| Long capture: joining, page breaks, hostile screen content, memory and speed limits | 45 logic tests plus 5 full runs on a simulated screen | All pass; the saved picture equals the page pixel for pixel |
| Long capture: sends nothing but wheel turns, starts no other program, writes only through the VitePDF file writer | Source checks in the test suite | Pass |

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
- **A capture holds whatever is inside the box**, including a notification that pops up there while it runs. Check a capture before you send it.
- **Automatic scrolling acts on the window under the pointer.** If another window comes to the front under the pointer during a long capture, the wheel turns go to that window. VitePDF then no longer recognises the page and stops; moving the mouse stops it at once.
- **Long captures are limited** to about 300 MB of picture data in memory, so a very long page ends early with a notice.
- **Crop hides, it does not delete**, and "Original" keeps camera data inside a JPG. Both are stated in the readme.
- **Command-line passwords** (`--password` with `--now`) can be seen by other programs of the same user while the job runs. The windows never use the command line for passwords.

## Keeping it clean

1. A few times a year, or after a security notice for a pinned library: raise the versions and hashes in `requirements.txt`, run pip-audit, test, build and sign a new release.
2. Never share the signing key. Publish the fingerprint where colleagues can see it independently of the download.
3. Use only made-up files in any public repository or bug report.

## Reporting a problem

Tell the author directly, with the VitePDF version and a made-up file that shows the problem. Do not send real documents.
