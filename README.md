<p align="center"><img src="docs/icon-512.png" width="112" alt="KeepFrame"></p>

# KeepFrame

**Find the best frame, clear the rest.** A free, open-source Windows app that finds duplicate and
*similar* photos (bursts, the same scene shot again from the same angle) with local AI, lets you
compare them side by side, and removes the ones **you** choose. Nothing is ever deleted
permanently.

[Türkçe](README.tr.md) · [Architecture](ARCHITECTURE.md)

> Status: **early development (0.1.0.dev0)**. Try it on a copy of your photos first.

## Features

**Similar photos (main tool)**
- Groups burst shots and repeated shots taken within seconds (EXIF time, file-name time, camera),
  across phones too, plus resized/re-saved copies anywhere in the library (e.g. WhatsApp copies
  without EXIF) and byte-identical copies.
- AI similarity with DINOv2 (ONNX Runtime: NVIDIA CUDA, any DirectML GPU, or CPU). Without the
  model a quick dHash + ORB mode is used.
- **You decide.** The app only puts a *Suggested* badge on the frame it thinks is best (sharpest,
  highest resolution, best exposure) and explains why. Nothing is pre-checked.
- **Select menu** (like czkawka / Duplicate Cleaner): all except suggested · except highest
  resolution · except largest file · except sharpest · except oldest / newest · except shortest
  path · blurrier than X% · prefer HEIC/JPG/RAW · keep the copy in a folder · by regex · invert ·
  clear. Apply to this group, the filtered groups or all groups.
- Fast visual review: thumbnail cards, instant full-screen preview (Space), synced side-by-side
  compare with zoom (C), keyboard flow (X mark, J/K next/prev group, R apply last rule and go on).
- "Not duplicates" is remembered across scans. Favorite/rated photos and protected folders are
  never checked by rules, and at least one photo per group is always kept.

**File tools (czkawka-style)**: duplicate files (any type, size → pre-hash → full hash), big
files, empty files, empty folders, temporary files, broken images, wrong extensions.

**Safety**: Recycle Bin or quarantine folder (always quarantine on network/USB drives), files that
changed since the scan are never touched, RAW+JPG / Live Photo / XMP move together, every session
can be undone from History. OneDrive cloud-only files are skipped by default (no mass downloads).

**Speed**: one decode per file, 512 px thumbnails cached on disk, SQLite feature cache: a re-scan
of an unchanged library takes seconds.

## Install

### Easiest — download the installer (no Python needed)
1. Go to **[Releases](https://github.com/omerbek/keepframe/releases/latest)** and download
   **`KeepFrame-Setup-x.y.z.exe`** (or `KeepFrame-portable.zip` if you don't want to install).
2. Run it. The AI model is already included — nothing else to set up.
3. Windows SmartScreen may say *"Windows protected your PC"* because the app is not code-signed
   yet: click **More info → Run anyway**.

### Option A — run from source (Python 3.10+ installed)
1. Download this repository (Code → Download ZIP) and unzip it.
2. Double-click **`run_keepframe.bat`**. The first start installs everything.
3. Optional, for the AI mode: double-click **`tools\get_model.bat`** once (downloads ~100 MB, converts the model).

### Option B — build `KeepFrame.exe`
Run **`packaging\build_exe.bat`**. You get `dist\KeepFrame\KeepFrame.exe` (portable) and, if
[Inno Setup 6](https://jrsoftware.org/isdl.php) is installed, `dist\KeepFrame-Setup-x.y.z.exe`.
Pushing a `v*` tag builds both on GitHub Actions (`.github/workflows/release.yml`).

## Keyboard
| Key | Action |
|---|---|
| Space / Enter | Full-screen preview |
| X / 1–9 | Mark the focused / n-th photo for removal |
| C | Compare (suggested vs focused, or two selected) |
| J / K | Next / previous group · N next unreviewed |
| R | Apply the last rule to this group and go to the next |
| U | Keep all in this group · I invert |
| Delete | Remove checked photos (asks first) |
| Ctrl+Z | Undo selection |

## Development
```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[gui,ai,raw,win,dev]"
pytest
python -m keepframe
keepframe-cli scan "D:\Photos" --csv report.csv
```

## License
GPL-3.0-or-later. See [LICENSE](LICENSE) and [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
