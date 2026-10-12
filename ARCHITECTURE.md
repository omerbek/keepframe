# KeepFrame — Architecture (v0.2)

> Türkçe: [docs/ARCHITECTURE.tr.md](docs/ARCHITECTURE.tr.md)
> License: **GPL-3.0-or-later** · GUI: **PySide6 (Qt 6)** · First target: **Windows 10/11 x64** · Languages: **English (primary) + Turkish**

---

## 1. Goal and scope

KeepFrame finds the following in personal photo libraries of 10k–200k photos and helps you clean them up safely:

| Kind | Example | Default handling |
|---|---|---|
| **Exact copy** | The same file in two folders | Can be resolved in one click |
| **Re-encoded copy** | A downsized WhatsApp version; JPG ↔ HEIC | Can be resolved in one click, with a preview |
| **Similar frame** (burst / same angle) | Five frames shot at the same moment from the same angle | **Always needs human confirmation** |

**Out of scope for v1:** video duplicates, face recognition / people grouping, cloud sync.

### Design principles (from the research)
1. **Never delete permanently.** Files go to the Recycle Bin or a quarantine folder, and every session can be undone.
2. **Always explain the suggestion**, e.g. "sharper (+38%), eyes open, 12 MP".
3. **Technical pairs count as one photo.** RAW+JPEG, Live Photo (HEIC+MOV) and XMP sidecars are never flagged as duplicates.
4. **User decisions persist.** A pair marked "not a duplicate" does not come back on the next scan.
5. **Local only.** No internet is needed; the models ship with the app.
6. **The second scan takes seconds,** thanks to a cache and incremental scanning.

---

## 2. Overview

```
┌──────────────────────────────── UI (PySide6) ────────────────────────────────┐
│  Start / folders │ Scan progress │ Group list │ Compare view │ Settings │ History│
│  i18n (en / tr)                                                                │
└───────────────▲───────────────────────────────────────────────┬──────────────┘
                │ Qt signals (progress, partial results)          │ commands
┌───────────────┴────────────── Application layer ───────────────▼──────────────┐
│  ScanController · ReviewSession · ActionExecutor (move / trash / undo)         │
└───────────────▲────────────────────────────────────────────────┬─────────────┘
                │                                                │
┌───────────────┴──────────────── core (no Qt dependency) ───────▼─────────────┐
│ 1 Discover → 2 Metadata → 3 Proxy → 4 Features → 5 Candidates → 6 Verify       │
│ → 7 Group → 8 Rank best shot                                                   │
│        ↕                      ↕                        ↕                       │
│  Catalog (SQLite WAL)   Model runner (ONNX Runtime)   Vector index (usearch)   │
└───────────────────────────────────────────────────────────────────────────────┘
```

- **The `core` package never imports Qt.** This means there can also be a CLI (`keepframe-cli`), and the tests run headless.
- **Decoding runs in worker pools so the GUI never blocks.** GPU inference runs in one thread, in batches.

---

## 3. Pipeline

### Stage 1 — Discover
- Recursive `os.scandir`. Each file becomes a **file record**: path, size, mtime.
- Supported formats: JPG/JPEG, PNG, HEIC/HEIF, WEBP, TIFF, BMP, AVIF and RAW (CR2/CR3, NEF, ARW, DNG, ORF, RW2, RAF…).
- Skipped: user-excluded folders, `$RECYCLE.BIN`, `System Volume Information` and the app's own quarantine folder.
- A file whose **(path, size, mtime)** is already in the catalog is **skipped**. This is what makes scanning incremental.

### Stage 2 — Metadata
Fields read: `DateTimeOriginal` (then `DateTimeDigitized`), `SubSecTimeOriginal`, camera make/model/serial number, orientation, dimensions.

Times are stored as **wall-clock seconds** (the naive local time read as UTC), so an original with an `OffsetTime` tag and an exported copy without one still line up, and the PC's timezone or DST never shifts them.

Capture-time fallback (`time_source`): `exif` → `name` (IMG20251129104752, PXL_…, Screenshot_…) → `name_day` (WhatsApp IMG-20251201-WA0003) → `mtime`. Only `exif` and `name` are trusted for the time window; the rest only enter the library-wide copy pass (setting: *use file dates*).

**The file is opened once:** metadata, orientation and the proxy decode share one `Image.open`.

Burst IDs:
- Apple: `MakerNotes:BurstUUID`
- Google: `GCamera:BurstID`
- Samsung: file-name patterns

Live Photos are paired using `ContentIdentifier`.

Tools:
- Fast path: Pillow `getexif()` + `pillow-heif`.
- Fallback for missing fields: **exiftool** (bundled, run in batch `-json` mode).

**Asset merging:** RAW+JPG, HEIC+MOV and `.xmp` files with the same name in the same folder become one *asset*. The JPG/HEIC is used as its representative for comparison.

### Stage 3 — Proxy
- A 512 px proxy is produced, using the fastest route for each source:

| Source | Method |
|---|---|
| JPEG | `Image.draft()` (libjpeg-turbo DCT scaling, 3–8× faster) |
| RAW | Embedded JPEG preview via `rawpy.extract_thumb()` |
| HEIC | `pillow-heif` |

- EXIF orientation is applied.
- The proxy is cached on disk as **WebP** (`%LOCALAPPDATA%\KeepFrame\thumbs\ab\cd\<id>.webp`), and the UI reuses the same file.

### Stage 4 — Features
| Feature | Tool | Size | Used for |
|---|---|---|---|
| `sha256` (only for files whose sizes collide) | hashlib | 32 B | Exact copies |
| `pdq` + quality | `pdqhash` | 32 B | Re-encoded copies |
| `dhash64` | numpy | 8 B | Fast pre-filter and fallback |
| **`emb_dino`** | **DINOv2 ViT-S/14, ONNX, fp16** | 768×2 B | Similar frames (main signal) |
| `sharp` | Tenengrad / Laplacian variance (on the face or subject region) | float | Best shot |
| `exposure` | Fraction of clipped histogram ends | float | Best shot |
| `faces` | **YuNet** (OpenCV Zoo, MIT) | list | Best shot |
| `eyes_open`, `smile` | **MediaPipe Face Landmarker** blendshapes (Apache-2.0) | float | Best shot |

- Models run on **ONNX Runtime**. Provider order: `CUDAExecutionProvider` → `DmlExecutionProvider` → `CPUExecutionProvider`.
- Batch size: 64 on GPU, 8 on CPU. Input 224×224, ImageNet normalization.
- Embedding: CLS token concatenated with the mean patch token, L2-normalized.
- **Face analysis is lazy:** it only runs on photos that end up in a candidate group.

### Stage 5 — Candidate pairs
Comparing every photo with every other photo (O(n²)) is **not allowed**. Candidates come from:
1. **Time window:** same camera, trusted time, Δt ≤ `max_dt` (default 20 s), at most 40 neighbours.
2. **Cross-device:** any camera, Δt ≤ 10 s (two family phones shooting the same moment).
3. **Exact copies:** size → 64 KB pre-hash → full BLAKE2b, only for size collisions.
4. **Re-saved / resized copies, whole library:** 64-bit dHash multi-index buckets (Hamming ≤ 4,
   pigeonhole on 5 bands) + same aspect ratio. Two *timed* shots count as a copy only if taken at
   the same moment *and* re-encoded/resized; an untimed copy (WhatsApp) links only to its single
   closest match. One representative per exact / re-saved set stays in the similarity pool.
5. Screenshots (file name, PNG without camera) are excluded from similarity unless enabled.

### Stage 6 — Pair verification
| DINOv2 cosine | Decision |
|---|---|
| ≥ T_high (0.92) | Link |
| T_low (0.80) – T_high | Check with **ORB + RANSAC homography**: link if inliers ≥ 50 and inlier ratio ≥ 0.30 |
| < T_low | Do not link |

- In the dHash fallback, auto-link needs distance ≤ ~4 bits **and** Δt ≤ 3 s; everything else must pass ORB (Lowe ratio 0.75, MAGSAC homography, ≥ 40 inliers, ratio ≥ 0.35). ORB descriptors are computed once per thumbnail (LRU).
- Pairs the user marked "not duplicates" are dropped here. They are stored by **normalised path pair**, so they survive re-scans.
- A single **"Similarity strictness"** slider in the UI shifts T_low and T_high together.
- These thresholds are starting points. They will be **calibrated on 500 labeled pairs** (see §9).

### Stage 7 — Grouping
- Union-find with an **anti-chaining guard**: a photo joins a group only if its average cosine to the group's members is ≥ 0.85. This prevents a wrong merge when A≈B and B≈C but A≠C (for example a slow pan).
- A merge also needs every cross pair ≥ ~T_low (no outliers), and ORB-verified pairs count as `group_mean`.
- Groups larger than 40 are split into time-contiguous runs.
- Each group gets a kind: `exact` | `reencoded` | `similar`.

### Stage 8 — Best-shot suggestion (never a decision)
Every signal is turned into a z-score **within the group**; there are no global thresholds:

```
score = 0.35·sharpness_z + 0.30·eyes_open + 0.10·smile + 0.10·exposure
      + 0.10·resolution_z + 0.05·metadata_richness
```

- **Groups without faces:** the face weights move to sharpness, exposure and resolution.
- **A face with closed eyes** (blink > 0.5) gets a strong penalty.
- **Protection rules:** favorite, rated or edited photos, and files in a "protected folder", are **never auto-marked for trash**.
- **Exact copies are not scored.** Rule order: protected folder → user's preferred folder → shortest path → oldest.
- Every member gets `reasons[]` (sharpest, blurrier, lower resolution, worse exposure, near-identical…) and its similarity to the suggested photo.
- **Nothing is checked automatically.** The user checks photos by hand or with selection rules (§5.1).

---

## 4. Data model (SQLite, WAL)

Location: `%LOCALAPPDATA%\KeepFrame\catalog.db`

```sql
library(id, root_path, added_at, excluded_globs)
file(id, asset_id, path UNIQUE, size, mtime, kind)          -- kind: image|raw|video|sidecar
asset(id, primary_path, taken_at, camera, serial, burst_id,
      width, height, size, mtime, is_favorite, rating)
feature(asset_id PK, sha256, pdq BLOB, pdq_q, dhash INTEGER,
        emb BLOB /*fp16*/, model_ver, sharp, exposure, faces_json,
        eyes_open, smile, computed_at)
grp(id, kind, scan_id, status)                               -- status: open|resolved|ignored
grp_member(grp_id, asset_id, score, reasons_json, suggested, user_action)
ignored_pair(a, b, created_at)                               -- "not a duplicate"
action_log(id, session_id, asset_id, op, src_path, dst_path, ts, undone)
scan(id, started_at, finished_at, settings_json, stats_json)
```

- If `model_ver` changes, only the affected embeddings are invalidated and recomputed.
- The usearch index is stored in `emb.usearch`, keyed by `asset_id`.

---

## 5. User interface

### Screens
1. **Start:**
   - Add folders (several are allowed) and excluded folders.
   - A short settings summary.
   - On first launch, a three-step intro explains what counts as a copy vs. a similar shot, where removed files go, and how to undo.
2. **Scan:**
   - Shows the stage name, `n / N`, photos per second, time remaining and the device in use (GPU/CPU).
   - **Pause / Resume / Cancel** buttons.
   - Groups start appearing live, before the scan finishes.
3. **Summary dashboard:**
   - Cards such as "Exact copies: 412 (3.1 GB)", "Similar shots: 1,208 groups" and "Blurry: 87".
   - Each card shows the estimated space to be reclaimed.
4. **Review (main screen):**
   - A group list on the left, in a virtual `QListView` so 100k items scroll smoothly.
   - The group's photos side by side in the middle. Each card shows the preview, a **green "Keep" / red "Trash"** chip and a score bar.
   - Hovering over a card shows the reasons for the suggestion.
   - **Synced zoom/pan:** the wheel and drag apply to every card at once. A "zoom to face" option is included.
   - **Only the metadata fields that differ** are shown: resolution, size, time, folder, camera.
   - Group position appears as "12 / 340", with First / Previous / Next / Last buttons.
5. **History:** a list of sessions, with "Undo all" and per-item undo.
6. **Settings:** strictness, time window, device, language, removal method (Recycle Bin or quarantine), protected folders.

### 5.1 Selection system
`core/selection.py` (pure Python, unit-tested). Rules return the photos to **check for removal** in one group:

| Rule | Keeps |
|---|---|
| All except suggested | the *Suggested* photo |
| All except highest resolution / largest file / sharpest | that one |
| All except oldest / newest / shortest path | that one |
| Blurrier than X % of the sharpest | everything sharper |
| Prefer format (HEIC > JPG, RAW > JPG…) | the preferred format |
| Keep the copy in folder… | the copy inside that folder |
| By path/name regex | everything not matching |
| Invert · Clear | — |

Scope: this group · visible (filtered) groups · all groups. Guards: protected photos (favorite, rated, protected folders) are never checked, and at least one photo per group always stays unchecked. 50-step undo of the selection.

### Keyboard shortcuts
| Key | Action |
|---|---|
| ← → ↑ ↓ | Move between cards |
| Space / Enter | Full-screen preview (← → browse, 1 = 100 %, Esc close) |
| X · 1–9 | Mark focused / n-th photo for removal |
| C | Synced compare (suggested vs focused, or two selected) |
| J / K · N | Next / previous group · next unreviewed |
| R | Apply last rule to this group and advance |
| U · I | Keep all (reviewed) · invert in group |
| Delete | Remove checked (with confirmation) |
| Ctrl+Z | Undo selection |

### Bulk actions
- "Resolve all exact copies (412)"
- "Apply suggestions to all groups in this filter"

Every bulk action first asks for confirmation, **showing the count and size**.

### Visual language
- Dark and light themes (Qt Fusion + custom QSS).
- Color never carries meaning on its own: every colored chip also has an icon and text.
- High-DPI aware.

---

### File tools (czkawka-style, `core/tools.py`)
Duplicate files (any type; size → pre-hash → full hash), big files, empty files, empty folders, temporary files (`*.tmp`, `Thumbs.db`, `.DS_Store`, partial downloads…), broken images (`verify()` + full decode), wrong extensions (magic-byte sniffing, HEIF `ftyp` brands). Results share one tree view with checkboxes, a Select menu (except oldest / newest / shortest / longest path, folder priority, regex, invert) and the same safe actions.

## 6. Safe action layer (ActionExecutor)

- **Default method:** Windows Recycle Bin (`send2trash`).
- **On network drives / NAS** the Recycle Bin does not work. KeepFrame then **switches to the quarantine folder automatically** and warns the user.
- **Quarantine folder:** `<root>\_keepframe_quarantine\<session>\<original relative path>`, so the folder structure is preserved.
- Every operation is written to `action_log` (intent first, then the move). Undo moves the file back to `src_path`; Recycle Bin items are restored through the Windows shell (pywin32), otherwise the user is told to restore them manually.
- A file whose size or mtime changed since the scan is refused.
- The Recycle Bin is used in one batch call; on removable and network drives the quarantine folder is used instead.
- **The last copy in a group can never be removed.** This rule is enforced both in the UI and in the core logic.
- RAW+JPG, HEIC+MOV and XMP companions **move together**.
- **(v1.1) Metadata merge:** ratings and tags of the removed copy are written to the kept photo's XMP.

---

## 7. Repository layout

```
keepframe/
├─ pyproject.toml
├─ LICENSE                       # GPL-3.0
├─ README.md / README.tr.md
├─ ARCHITECTURE.md / docs/ARCHITECTURE.tr.md
├─ THIRD_PARTY_LICENSES.md
├─ src/keepframe/
│  ├─ core/
│  │  ├─ types.py                # dataclasses shared by all stages
│  │  ├─ discovery.py            # stage 1
│  │  ├─ metadata.py             # stage 2
│  │  ├─ assets.py               # RAW+JPG / Live Photo merging
│  │  ├─ decode.py               # stage 3: draft / rawpy / heif → proxy
│  │  ├─ features/
│  │  │  ├─ hashes.py            # sha256, pdq, dhash
│  │  │  ├─ embedder.py          # ONNX Runtime + DINOv2
│  │  │  ├─ quality.py           # sharpness, exposure
│  │  │  └─ faces.py             # YuNet + MediaPipe (v0.2)
│  │  ├─ candidates.py           # stage 5
│  │  ├─ verify.py               # stage 6 (ORB + RANSAC)
│  │  ├─ grouping.py             # stage 7
│  │  ├─ ranking.py              # stage 8 + reasons
│  │  ├─ catalog.py              # SQLite access
│  │  ├─ index.py                # usearch wrapper
│  │  ├─ actions.py              # move / trash / undo
│  │  └─ pipeline.py             # orchestrates the stages, emits progress
│  ├─ app/                       # Qt-dependent controllers
│  ├─ ui/                        # windows, widgets, i18n
│  ├─ models/                    # ONNX / task files (not in git)
│  └─ cli.py
├─ tools/
│  ├─ export_dinov2_onnx.py
│  └─ calibrate.py
├─ tests/
├─ packaging/                    # PyInstaller, Inno Setup, winget
└─ .github/workflows/            # CI: lint + tests on Windows and Linux
```

---

## 8. Packaging and distribution

| Package | Contents | Approx. size |
|---|---|---|
| **KeepFrame-Setup.exe** (default) | Python runtime, PySide6, `onnxruntime-directml`, models, exiftool | ~250–350 MB |
| **NVIDIA CUDA add-on** (optional) | Offered on first launch ("Download GPU acceleration"): `onnxruntime-gpu` with CUDA/cuDNN DLLs | ~0.6–1 GB |
| **Portable .zip** | No installer | Same as the installer |

- **DirectML** works on any DX12 GPU (NVIDIA, AMD, Intel), so GPU acceleration is available even without the CUDA add-on.
- **Build:** PyInstaller first; switch to Nuitka if antivirus false positives become a problem.
- **Code signing:** SignPath Foundation (free for open-source projects), which reduces SmartScreen warnings.
- **Release flow:** pushing a `v*` tag in GitHub Actions builds on Windows, makes the installer, signs it, creates the GitHub Release and opens a winget PR.

---

## 9. Quality assurance

- **Labeled set:** 500 pairs (bursts, same angle, similar-but-different, exact copies, WhatsApp copies). `tools/calibrate.py` draws the precision/recall curve from this set and picks the default thresholds.
- **Target:** for similar frames, **precision ≥ 97%** and recall ≥ 90%. A false positive costs more than a false negative here.
- **Performance target:** 10k JPEGs on an RTX-class GPU in **< 5 min** for the first scan and **< 15 s** for a re-scan. First scan on CPU < 25 min.
- **Unit tests:** grouping (anti-chaining), asset merging, undo, the "last copy cannot be removed" rule.
- **CI:** `ruff` + `pytest` on Windows and Linux for every PR.

---

## 10. Roadmap

| Version | Content |
|---|---|
| **0.1 (MVP)** | Folder scan, metadata, proxies, dHash + DINOv2, time sessions, grouping, sharpness-based best shot, review screen, Recycle Bin + undo, EN/TR |
| **0.2** | Face / eyes / smile scoring; ORB verification; synced zoom; keyboard flow; bulk actions |
| **0.3** | RAW+JPG and Live Photo merging, HEIC, exiftool, quarantine and network drives |
| **0.4** | Installer, CUDA add-on, code signing, winget |
| **1.0** | Calibrated thresholds, "similar on different days" pass, metadata merge, documentation |
| **Later** | macOS / Linux builds, CLI features, Lightroom catalog support |

---

## 11. Third-party license summary

See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). **Not used** because of non-commercial or restrictive terms: InsightFace models, SuperPoint weights, pyiqa, DINOv3 (license is not OSI-compatible).
