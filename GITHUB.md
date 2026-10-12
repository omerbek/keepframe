# KeepFrame: GitHub'a yayınlama ve devir notları

> Bu dosya iki iş için yazıldı:
> 1. **Bir kodlama ajanının (Codex vb.) projeyi GitHub'a otomatik yüklemesi** (Bölüm A).
> 2. **Projeyi devralacak geliştiricinin / ajanın şimdiye kadar ne yapıldığını bilmesi** (Bölüm B–E).
>
> Proje klasörü: `C:\Users\omer\Desktop\FOTODetection` · GitHub kullanıcısı: `omerbek` · Depo adı: `keepframe`
> Son güncelleme: 12 Ekim 2026

---

## A. Yapılacaklar: GitHub'a yükleme (adım adım)

Komutlar **PowerShell**'de ve proje klasöründe çalıştırılır:

```powershell
cd C:\Users\omer\Desktop\FOTODetection
```

### A1. Ön koşullar
- `git --version` ve `gh --version` çalışmalı. Yoksa şunlarla kurulur:
  - `winget install Git.Git`
  - `winget install GitHub.cli`
- `gh auth status` "Logged in to github.com as omerbek" demeli. Demiyorsa `gh auth login` çalıştırılır (GitHub.com → HTTPS → tarayıcıyla giriş).

### A2. İş akışı dosyalarını kontrol et
Şu iki dosya mevcut olmalı. Kullanıcıya ayrıca gönderildiler; yoksa Bölüm F'deki içerikle oluşturulur.
```
.github\workflows\ci.yml
.github\workflows\release.yml
```
**Önemli:** `release.yml` içindeki pip satırı `onnx onnxscript` içermeli (PyTorch 2.9+ için). İçermiyorsa Bölüm F'deki sürümle değiştirin.

### A3. Yüklenmemesi gerekenler
`.gitignore` bunları zaten dışlıyor, yine de kontrol edin:

| Yol | Neden |
|---|---|
| `.venv\`, `.venv-build\`, `.venv-model\` | Python ortamları (yüzlerce MB) |
| `src\ayikla.egg-info\`, `*.egg-info` | Eski adla kalmış kurulum artığı; **silinebilir** |
| `build\`, `dist\` | .exe derleme çıktıları |
| `src\keepframe\models\*.onnx` | Yapay zekâ modeli (~90 MB). Release iş akışı kendisi üretir |
| `__pycache__\`, `*.db`, `_keepframe_quarantine\` | Önbellek, veritabanı, karantina |
| `tools\get_model.log`, `*.tmp.onnx` | Model kurulum kaydı ve geçici dosya |
| Kişisel fotoğraflar | Proje klasöründe fotoğraf **olmamalı** |

Kontrol komutu (çıktı boş olmalı):
```powershell
git status --porcelain --ignored | Select-String -Pattern "\.(jpg|jpeg|heic|png|onnx)$" | Where-Object { $_ -notmatch "docs/|src/keepframe/ui/" }
```

### A4. Depoyu oluştur ve yükle
```powershell
# 1) Testler geçmeli
.venv\Scripts\activate
pip install -e ".[gui,ai,raw,win,dev]"
pytest -q            # beklenen: 24 passed
ruff check src tests tools

# 2) Git deposu
git init -b main
git add -A
git status            # sadece kaynak dosyalar görünmeli (~72 dosya)
git commit -m "KeepFrame 0.1.0: similar & duplicate photo finder with local AI"

# 3) GitHub'da oluştur + yükle (public)
gh repo create omerbek/keepframe --public --source . --remote origin --push `
  --description "Find the best frame, clear the rest. Duplicate & similar photo finder with local AI for Windows."

# 4) Etiketler (topics)
gh repo edit omerbek/keepframe --add-topic photos,duplicate-finder,similar-images,photo-culling,burst,dinov2,onnxruntime,pyside6,windows,python
```

### A5. İlk sürüm (otomatik .exe)
`release.yml` bir `v*` etiketi gönderilince Windows'ta şunları yapar:
1. DINOv2 modelini ONNX'e dönüştürür.
2. Testleri çalıştırır.
3. PyInstaller ile `KeepFrame.exe` derler.
4. Inno Setup ile kurulum dosyasını hazırlar.
5. GitHub Release'e `KeepFrame-Setup-0.1.0.exe` ve `KeepFrame-portable.zip` dosyalarını ekler.

```powershell
git tag v0.1.0
git push origin v0.1.0
gh run watch            # iş akışını izle (≈10–15 dk)
gh release view v0.1.0  # dosyalar eklendi mi?
```
Release iş akışı başarısız olursa önce şuna bakın: `gh run view --log-failed`.
- **PyInstaller hatası:** `packaging/keepframe.spec` içindeki `hiddenimports` / `collect_dynamic_libs` listesine bakın.
- **Inno Setup hatası:** `packaging/installer.iss` yollarına bakın.

### A6. Yükleme sonrası kontrol
- [ ] https://github.com/omerbek/keepframe açılıyor, README'de simge görünüyor (`docs/icon-512.png`)
- [ ] Actions sekmesinde **CI** yeşil
- [ ] Releases'te v0.1.0 altında `.exe` ve `.zip` var
- [ ] Depo ayarları → "Releases" ve "Issues" açık; About kısmında açıklama ve etiketler var

---

## B. Ne yaptık (özet)

### Amaç
Kullanıcının ~10.000 fotoğrafında **aynı anda / aynı açıdan çekilmiş benzer kareleri** bulmak. czkawka'nın "similar images" modu bu iş için yetersiz kaldı. Hedef: **herkese açık, GUI'li, ücretsiz** bir Windows uygulaması.

### Süreç
1. **İlk prototip:** Tek dosyalık bir tkinter + DINOv2 betiği yazıldı. Kullanıcı bunu "çok basit" buldu.
2. **Piyasa araştırması (5 ajan):** Ticari uygulamalar (Gemini 2, PhotoSweeper, Excire, Lightroom Assisted Culling…), açık kaynak araçlar (czkawka, dupeGuru, digiKam, Immich…), algoritma ve modeller, mobil/bulut UX desenleri, kullanıcı şikâyetleri ve teknoloji yığını incelendi.
3. **Kararlar:**
   - Lisans **GPL-3.0** (pillow-heif içindeki x265 nedeniyle).
   - Arayüz **PySide6/Qt**.
   - Önce **Windows**.
   - Ana dil **İngilizce**, ikinci dil **Türkçe**.
   - Ad **KeepFrame**. "Photo Doctor" adı başka uygulamalarla çakışıyordu.
4. **Mimari ve iskelet:** Yazıldı (bkz. `ARCHITECTURE.md`).
5. **İkinci ajan turu:** 5 ajan kodu farklı modellerle sorguladı: tespit doğruluğu, performans ve Windows, seçim UX'i, görsel tema, czkawka özellik karşılaştırması. Bulgulara göre çekirdek ve arayüz yeniden yazıldı.
6. **Gerçek veriyle test:** Kullanıcı 4.066 fotoğrafla denedi (dHash modu, model kurulu değil). Sonuç: 381 grup, ilk tarama 443 sn. Kullanıcı yorumu: "sonuçlar çok iyi".
7. **Düzeltilen hatalar:**
   - Tarama bitince ekran tarama sayfasında takılı kalıyordu. Neden: QThread hâlâ açıktı, `runner.running` yanlış sonuç veriyordu.
   - "İptal ediliyor"da takılma. Çözüm: token tabanlı `TaskRunner`, ayrıca 3 sn sonra arayüzü zorla serbest bırakma.
   - "Bulunan dosya" sayacı son değeri göstermiyordu.
8. **Simge:** A konsepti ("Seçilen kare") seçildi. Kaynak: `src/keepframe/ui/app_icon.svg`.

### Temel ilkeler (değiştirmeyin)
- **Uygulama karar vermez.** Hiçbir şey otomatik işaretlenmez; yapay zekâ sadece "Önerilen" rozeti koyar. Kullanıcı elle ya da **Seç menüsündeki kurallarla** işaretler.
- **Kalıcı silme yok.** Dosyalar Geri Dönüşüm Kutusu'na ya da `_keepframe_quarantine` klasörüne gider. Ağ ve USB sürücülerde her zaman karantina kullanılır. Her oturum geri alınabilir.
- **Her grupta en az bir fotoğraf korunur.** Favori / yıldızlı / korumalı klasördeki fotoğraflar kurallarla asla işaretlenmez.
- **Taramadan sonra değişmiş dosyaya dokunulmaz.** Boyut ve değiştirilme zamanı (mtime) kontrol edilir.
- **`core` paketi Qt'ye bağımlı değildir.** CLI ve testler başsız çalışır.

---

## C. Kod haritası

```
src/keepframe/
  core/                    # Qt'siz çekirdek
    discovery.py           # klasör tarama; iç içe kök + hardlink tekilleştirme, OneDrive placeholder atlama
    metadata.py            # EXIF zamanı (wall-clock), dosya adından zaman, ekran görüntüsü tespiti
    decode.py              # dosyayı TEK kez aç: metadata + 512 px proxy (JPEG draft, HEIC, RAW thumb)
    assets.py              # RAW+JPG, HEIC+MOV (Live Photo), XMP birleştirme
    thumbs.py, cache.py    # disk küçük resim önbelleği + SQLite özellik önbelleği (CACHE_VERSION)
    features/              # quality (Laplacian, pozlama, dHash), hashes (BLAKE2b), embedder (DINOv2 ONNX), faces (TODO)
    candidates.py          # zaman penceresi, cihazlar arası, dHash çoklu-indeks kopya çiftleri
    verify.py              # eşikler + ORB/Lowe/MAGSAC doğrulama (OrbCache)
    grouping.py            # zincirleme korumalı union-find, büyük grup bölme
    ranking.py             # sadece ÖNERİ + gerekçe anahtarları
    selection.py           # seçim kuralları + SelectionState (koruma, geri al)
    pipeline.py            # orkestrasyon (ScanOptions → ScanResult)
    tools.py               # czkawka tarzı araçlar
    actions.py, catalog.py # güvenli taşıma/geri alma, "kopya değil" listesi, işlem günlüğü
  app/controller.py        # TaskRunner: her iş ayrı QThread + token
  ui/                      # theme (QSS token'ları), icons (SVG), i18n (EN/TR), review, toolpage, pages, viewers, widgets
  cli.py                   # keepframe-cli scan / tool
tests/                     # pytest (24 test) — i18n anahtar eşitliği dahil
tools/                     # export_dinov2_onnx.py, get_model.bat, calibrate.py
packaging/                 # keepframe.spec, launcher.py, manifest, installer.iss, build_exe.bat, keepframe.ico
```

Kullanıcı için başlatma: `run_keepframe.bat` · Model: `tools\get_model.bat` · .exe: `packaging\build_exe.bat`

---

## D. Geliştirme kuralları (Codex / katkıda bulunanlar için)

1. Her değişiklikten sonra `pytest -q` ve `ruff check src tests tools` çalıştırılır (CI de bunu yapar).
2. **Yeni arayüz metni** `ui/i18n.py` içinde **hem `EN` hem `TR`** sözlüğüne eklenir. Anahtarlar ve `{yer tutucular}` aynı olmalıdır; `tests/test_i18n.py` bunu denetler.
3. Özellik hesaplamasını değiştirirseniz `core/cache.py` içindeki `CACHE_VERSION` değerini artırın. Gömme vektörü (embedding) değişirse `embedder.MODEL_VERSION` değerini artırın.
4. `core/` altına Qt import'u eklemeyin.
5. Dosya taşıyan / silen her kod `ActionExecutor` üzerinden geçmeli. Doğrudan `os.remove` kullanılmaz.
6. Uzun işler `TaskRunner.start(fn)` ile çalışır. `fn(progress, cancel)` imzası kullanılır ve `progress` sık çağrılır, çünkü iptal bu çağrıda yakalanır.
7. Lisans: GPL-3.0. InsightFace modelleri, SuperPoint ağırlıkları, pyiqa ve DINOv3 **kullanılmaz** (lisans kısıtları).

---

## E. Bilinen eksikler / yol haritası

| Öncelik | Konu | Not |
|---|---|---|
| Yüksek | İlk tarama hızı | 4.066 foto 443 sn (çoğu HEIC çözme). Fikirler: HEIC'te gömülü önizleme, iş parçacığı sayısını ayarlama, ORB adımını paralel kısıtlama |
| Yüksek | Yapay zekâ modu gerçek veride denenmedi | `tools\get_model.bat` ile model üret, aynı klasörü tara, grupları dHash moduyla karşılaştır; eşikleri `tools/calibrate.py` ile ayarla |
| Orta | Yüz / göz açık-kapalı puanı | `core/features/faces.py` boş (YuNet + MediaPipe Face Landmarker planlandı) |
| Orta | Geri Dönüşüm Kutusu'ndan otomatik geri alma | `pywin32` gerekiyor (`[win]` ekstrası); farklı Windows dillerinde "Geri yükle" fiili test edilmeli |
| Orta | Arayüz testleri | Ekransız (offscreen) pytest-qt testleri eklenebilir |
| Düşük | Kod imzalama | SignPath Foundation (açık kaynak için ücretsiz), winget manifesti |
| Düşük | Kullanılmayan kod | `core/index.py` (usearch kNN), `catalog` içindeki `grp/grp_member` tabloları: "farklı günlerdeki benzerler" özelliği için ayrıldı |
| Düşük | macOS / Linux derlemeleri | Kod taşınabilir; paketleme yok |

---

## F. İş akışı dosyaları (A2'de eksikse buradan oluşturun)

`.github/workflows/ci.yml`
```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [windows-latest, ubuntu-latest]
        python: ["3.11", "3.12"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pip install -e ".[gui,dev]"
      - run: ruff check src tests tools
      - run: pytest -q
```

`.github/workflows/release.yml`
```yaml
name: Release
on:
  push:
    tags: ["v*"]
  workflow_dispatch:
permissions:
  contents: write
jobs:
  windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Export AI model (DINOv2-small, Apache-2.0)
        shell: pwsh
        run: |
          python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
          python -m pip install "transformers>=4.40" onnx onnxscript
          python tools/export_dinov2_onnx.py
          python -m pip uninstall -y torch transformers
      - name: Install
        run: python -m pip install -e ".[gui,ai,raw,win,build,dev]"
      - name: Test
        run: pytest -q
      - name: Build exe
        run: pyinstaller packaging/keepframe.spec --noconfirm --clean
      - name: Installer
        shell: pwsh
        run: |
          choco install innosetup -y --no-progress
          & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
          Compress-Archive -Path dist\KeepFrame\* -DestinationPath dist\KeepFrame-portable.zip
      - uses: softprops/action-gh-release@v2
        if: startsWith(github.ref, 'refs/tags/')
        with:
          files: |
            dist/KeepFrame-Setup-*.exe
            dist/KeepFrame-portable.zip
```
