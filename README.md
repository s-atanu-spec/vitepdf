# VitePDF

Right-click image and PDF tools for Windows 10 and 11. "Vite" means quick.
Everything runs offline on your own computer. Original files are never changed.

Created by Atanu Sarkar. Made with Claude. Free to use and share (MIT licence).

## What it does

Right-click one or more files, or the empty space in a folder, and choose **VitePDF**.

### Pictures (JPG, JPEG, JFIF, PNG, HEIC, HEIF, WEBP, BMP)

| Menu | What you get |
| --- | --- |
| To PDF | One PDF per picture: Original, Optimized, Under 1 MB, Custom size |
| Compress image | A smaller JPG: Optimized, Under 1 MB, Under 200 KB, Custom size |
| Merge into one PDF | One PDF from everything selected (pictures and PDFs together). The page order and the result size are chosen in one window |
| Convert to JPG | A JPG copy. This is also how HEIC, PNG and WEBP become JPG |
| More tools | A window with: Convert to PNG, Resize photo, Black and white copy, Remove hidden data, Repair image, your presets, About |

### PDF files

| Menu | What you get |
| --- | --- |
| Compress | Optimized, Under 1 MB, Under 350 KB, Custom size |
| Merge | One PDF from everything selected (PDFs and pictures together) |
| To JPG | One JPG per page: Best quality, Optimized, Under 1 MB each, Custom size |
| Organize pages | Shown for one PDF. Page thumbnails: reorder, remove, rotate, crop, then save as one PDF, only the selected pages, or one PDF per page |
| Password | Add a password, or save an unlocked copy of a PDF whose password you know |
| More tools | A window with: Split into single pages, Rotate all pages, Black and white copy, Remove hidden data, Repair PDF, your presets, About |

Windows shows at most 16 entries in a menu of this kind, so the less frequent tools live in the **More tools** window.

### Empty space in a folder

| Menu | What you get |
| --- | --- |
| Capture area to PDF | The screen dims, you drag a box, and that area is saved in the folder as a lossless PDF |
| Capture long page to PDF | For something taller than the screen, such as a long email: you drag a box, the page scrolls, and everything is saved as one PDF with A4 pages |
| New blank PDF | An empty PDF: paper size, orientation, number of pages |

### Capture from any program

To capture a browser page or any other window, bring it to the front and start **VitePDF Capture** in one of these ways:

- Pin it to the taskbar once (Start menu, right-click **VitePDF Capture**, **Pin to taskbar**), then click it.
- Press **Ctrl + Alt + Shift + P**.

The screen dims, you drag a box, and the PDF is saved. The first time, VitePDF asks where captures go: Downloads, Desktop, or a folder you choose. To change it later, use **Change folder** in the "Capture saved" message. To change the keys, open the properties of the Start menu shortcut and set another **Shortcut key**.

### Capture a long page: VitePDF Scroll

For an email or page that does not fit on the screen. Start **VitePDF Scroll** from the Start menu, from the taskbar once pinned, or with **Ctrl + Alt + Shift + S**. It is also in the right-click menu of a folder as **Capture long page to PDF**.

1. Scroll to where the capture should begin and drag a box around that part. Keep fixed side panels and fixed bars outside the box.
2. The box turns red. Its thick bottom edge is the **END line**: everything that passes above it is captured.
3. Scroll, either way:
   - **By itself:** keep the pointer inside the box and take your hand off the mouse. After a 2 second countdown the page scrolls on its own and stops at the end of the page.
   - **By hand:** just scroll down. Touching the mouse also takes over from the automatic scrolling at any time.
4. Set the end: drag the red **END** label up to just under the last line you want, or scroll until that line sits just above the END line. Press **Finish**.
5. In the preview, adjust "start" and "end" if needed, choose the page direction (Auto, Portrait, Landscape) and press **Save PDF**.

Good to know:

- The parts are joined at the exact row where they overlap. Nothing is resized or blended, so the PDF is as sharp as the screen. For sharper text, zoom the browser to 125 or 150 percent first.
- Pages are A4. A page break is placed in a gap between lines, or on the quietest row nearby in a table. Captures wider than 1100 pixels go on landscape pages.
- If the box turns amber, VitePDF lost its place: scroll back up a little until it is red again.
- While it scrolls by itself, VitePDF turns the mouse wheel for you. That is the only input it ever sends: no clicks, no typing, and it never moves the pointer.
- The saved PDF holds pictures of the page. Its text cannot be searched or copied.
- It is saved in the same folder as other captures.

### Sizes

- **Original**: the picture is stored exactly as it is. JPG data is copied byte for byte; PNG pixels are stored losslessly. (HEIC and WEBP cannot live inside a PDF, so their pixels are stored losslessly and the PDF is larger than the source.)
- **Optimized**: visually identical, usually much smaller. Pictures longer than 3000 pixels are scaled to 3000 and saved at high quality. Files that are already small are left as they are.
- **Under 1 MB / 350 KB / 200 KB**: the best quality that fits. Files that already fit are not degraded.
- **Custom size**: type the limit in KB or MB. Recent sizes are offered again. Black and white can be ticked to reach a small size with sharper text.
- **Presets**: two sizes you save under your own name, for limits you need often. Set them under **More tools > Presets**; they then appear as rows in More tools.

Pages always keep the exact shape of the picture: no stretching, no margins. Phone photos that are stored sideways are turned upright.

### Output names

Results are saved next to the source file. Nothing is overwritten; a number is added if the name is taken.

| Action | Example |
| --- | --- |
| To PDF | `ticket.pdf`, `ticket_optimized.pdf`, `ticket_under1MB.pdf`, `ticket_under500KB.pdf` |
| Merge | `ticket_merged.pdf`, `ticket_merged_under1MB.pdf` |
| Compress | `scan_optimized.pdf`, `photo_under200KB.jpg` |
| To JPG, split | `scan_page01.jpg`, `scan_page01.pdf` |
| Other tools | `_bw`, `_clean`, `_rotated`, `_protected`, `_unlocked`, `_repaired`, `_organized`, `_pages`, `_600x600` |
| Target not reachable | `scan_smallest.pdf`, with a message that states the real size |

### Messages

VitePDF stays silent when everything went as asked. A message appears only when you need to know something: the file is already under the target, quality had to drop a lot, the target could not be reached, or a file was skipped.

### Merging

A window lists the files before merging. Drag the rows, or use **Move up** and **Move down**, to set the page order, pick the result size, then **Merge**. Windows does not tell programs the order in which you clicked the files, so the list starts in file-name order. Up to 100 files can be selected at once (a Windows limit).

## Install

### With Setup.exe (one file, no internet)

1. Double-click **VitePDF-Setup-1.4.0.exe**.
2. If Windows shows a blue "Windows protected your PC" box, choose **More info**, then **Run anyway**. The box appears because the file has no paid publisher certificate.
3. Read the welcome window, tick **I accept**, choose **Install**.

### From the source ZIP (needs internet once)

1. Extract the ZIP to any folder and double-click **install.bat**.
2. Read the welcome window, tick the box and choose **Install**.

The source installer checks every file against `SHA256SUMS.txt` (a signed copy must carry the author's key, or setup stops; an unsigned copy is installed with a clear notice), uses Python 3.13.17 or installs it from python.org after checking its digital signature (older patch levels are not accepted), installs the pinned libraries with checksum checks, runs a self-test and builds `VitePDF.exe` from `launcher.cs`.

Both ways install into `%LOCALAPPDATA%\VitePDF` for the current user only, add the right-click menu, a Start menu shortcut and an entry under Settings > Apps, and on Windows 11 offer the classic full right-click menu so VitePDF shows at the top level.

To update, install the new version over the old one. To remove, use **Settings > Apps > VitePDF > Uninstall**.

## Security

- **Offline**: the program contains no network code. Only the source installer uses the internet.
- **No admin rights**: everything is installed for the current user only.
- **Few decoders**: only the JPEG, PNG, WEBP, BMP and HEIF decoders are enabled, whatever a file claims to be. This limits what a booby-trapped file can reach.
- **Hard limits**: pictures above 400 megapixels, files above 600 MB and PDFs above 3000 pages are refused before any heavy work.
- **Safe start**: the program never runs from the folder that holds your files, ignores Python environment variables, and passes file names as single arguments (no command shell is involved).
- **Pinned libraries**: exact versions with checksums. A swapped download is rejected. The Setup builder refuses to pack anything that is not pinned.
- **Passwords**: PDFs are protected with AES-256. A password is never written to the log or to a settings file.
- **Private log**: the log holds no folder or file names.
- **One job per folder**: files selected in different folders are never combined into one job. Inside one folder, Windows gives a program no way to tell two selections apart, so two merges started within half a second of each other land in one list. The merge window always shows that list before anything is saved, and marks it when the files arrived in two groups.
- **Results appear complete**: a result gets its name only when it is fully written, and never replaces an existing file.
- **No test mode in the app**: screenshots and automatic answers used for testing live in a separate test harness that is not shipped.
- **Honest limit**: VitePDF opens files with the same open-source decoders that browsers and viewers use, inside your own Windows account. A new flaw in one of them could affect VitePDF until the pinned versions are updated. Update the pins a few times a year (see below). See `SECURITY.md` for the full list of checks and accepted risks.

## Checksums and signature

- `SHA256SUMS.txt` lists the SHA-256 checksum of every file of the source copy. The installer refuses to run if a file does not match.
- `SHA256SUMS.sig`, when present, is the author's Ed25519 signature of that list.
- A signed Setup file comes with two small files, `.sha256` and `.sig`.
- Check a copy yourself: `python vitepdf_sign.py --expect <fingerprint> verify <folder>` or `python vitepdf_sign.py --expect <fingerprint> verify-file <Setup.exe>`, with the fingerprint the author published. The check fails if the copy was signed by any other key.
- Author's key fingerprint: `A88B A544 E686 3A3C 1877 0B0C 3C40 DEBC`

### For the author: building and signing a release

1. Install this version on your computer with **install.bat** and test it.
2. Double-click **build-setup.bat**. It packs the Python and libraries of your computer, the VitePDF files and `VitePDF.exe` into `VitePDF-Setup-<version>.exe`, beside this folder. Nothing is downloaded.
3. Double-click **sign-release.bat**.
   - The first run creates your key in `Documents\VitePDF-signing`. Back up `vitepdf-signing.key` and never share it.
   - Every run rewrites `SHA256SUMS.txt`, signs it, builds `VitePDF-<version>.zip` beside the folder with its `.sha256`, and signs the Setup file if it is there.
4. Share the Setup file with its `.sha256` and `.sig`, and publish your key fingerprint.

Run steps 2 and 3 again after any change to any file.

## Good to know

- Text-only PDFs are already small. They get a lossless clean-up; their text is never turned into a picture.
- A long scan may not fit in 350 KB with readable text; VitePDF then saves the smallest readable version and tells you.
- Detail that is not in a picture cannot be recovered. VitePDF never upscales or "enhances".
- **Locked PDFs**: every PDF tool asks for the password of a locked PDF, once per file. Tick **Keep this password on the result** to protect the result with the same password, or untick it for a result that opens freely. JPG pictures cannot carry a password. A merged PDF takes the password of the first locked file you kept.
- **Filled forms**: values typed into a form are drawn in JPG exports and stay registered form fields after Merge, Split and Organize. A question whose buttons sit on several pages stays one question. Fields with the same name in two merged files are renamed. Bookmarks are not carried over.
- **Signed PDFs**: any saved copy of a digitally signed PDF loses its valid signature. VitePDF asks before it saves such a copy; the original is not changed and stays valid.
- **Original keeps camera data**: "Original" stores a JPG byte for byte, including its camera and location data. Use **Remove hidden data** before sharing outside.
- **Remove hidden data** removes document information, scripts, and attachments (also those fixed to a page), then opens the saved copy again to check. If anything is left it says so.
- **Crop hides, it does not delete**: the cropped-away part of a page is still inside the file.
- A black and white copy of a PDF changes its pictures; coloured text and drawings keep their colour.
- A log is kept in `%LOCALAPPDATA%\VitePDF\vitepdf.log`; presets and recent sizes are in `settings.json` beside it.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| VitePDF is not in the menu on Windows 11 | Look under **Show more options**, or install again and accept the classic menu. |
| Nothing happens after clicking | Open `%LOCALAPPDATA%\VitePDF\vitepdf.log` and look at the last lines. |
| Menu broke after a Windows or Python update | Install again. |
| "This file was changed or damaged" | The copy is incomplete or was edited. Get it again from the author. |

## For developers

| File | Role |
| --- | --- |
| `vitepdf.py` | Start file |
| `vp_core.py` | Engine: pictures to PDF, compressing, size search |
| `vp_ops.py` | Other tools: merge, convert, pages, password, clean-up, capture, blank |
| `vp_ui.py` | Windows (customtkinter) |
| `vp_scroll.py` | VitePDF Scroll: capturing a long page while it scrolls |
| `vp_shell.py` | Right-click menus, install, uninstall, self-test |
| `vp_main.py` | Command handling |
| `launcher.cs`, `setup_stub.cs` | Starter and Setup program, compiled with the C# compiler of Windows |
| `build_setup.py`, `vitepdf_sign.py` | Build and signing tools |
| `SECURITY.md` | Security checks, accepted risks, how to report a problem |

- `python vitepdf.py --help` lists every action. Exit codes: 0 done, 2 wrong command, 3 one or more files failed. `--now` runs a job directly, without windows, for example `python vitepdf.py --now pdf-compress custom --limit 500KB scan.pdf`.
- Updating the libraries: change the versions in `requirements.txt`, replace the hashes with those of the new Windows 64-bit wheels for Python 3.13 (from pypi.org), test, then build and sign a new release.
- Libraries: pikepdf (MPL-2.0), Pillow (MIT-CMU), pillow-heif (BSD-3-Clause), pypdfium2 (BSD-3-Clause / Apache-2.0), customtkinter (CC0-1.0), darkdetect (BSD-3-Clause). No AGPL components.
