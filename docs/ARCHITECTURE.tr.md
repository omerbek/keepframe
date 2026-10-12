# KeepFrame — Mimari Belgesi

> Bu belge [ARCHITECTURE.md](../ARCHITECTURE.md) dosyasının Türkçe özetidir. Çelişki olursa İngilizce sürüm geçerlidir.
>
> **v0.2'de değişenler:**
> - Yapay zekâ artık karar vermez, yalnızca *Önerilen* rozeti koyar.
> - Seçim kuralları (Seç menüsü) eklendi.
> - Çekim saati dosya adından da okunur.
> - Küçültülmüş / yeniden kaydedilmiş kopyalar tüm arşivde aranır.
> - Farklı telefonlarla aynı anda çekilen kareler de karşılaştırılır.
> - Yeni dosya araçları: kopya dosyalar, büyük dosyalar, boş dosya/klasör, geçici dosyalar, bozuk görseller, yanlış uzantılar.
> - Önbellek eklendi; tek seferde dosya okuma, iç içe klasör güvenliği ve OneDrive koruması eklendi.
> Lisans: **GPL-3.0-or-later** · Arayüz: **PySide6 (Qt 6)** · İlk hedef: **Windows 10/11 x64** · Dil: **İngilizce (ana) + Türkçe**

---

## 1. Amaç ve kapsam

Kişisel fotoğraf arşivlerinde (10 bin – 200 bin fotoğraf) şunları bulmak ve güvenle ayıklamak:

| Tür | Örnek | Varsayılan işlem |
|---|---|---|
| **Birebir kopya** | Aynı dosyanın iki klasörde olması | Tek tıkla çözülebilir |
| **Yeniden kodlanmış kopya** | WhatsApp'tan gelen küçültülmüş sürüm, JPG↔HEIC | Tek tıkla çözülebilir (önizlemeli) |
| **Benzer kare (seri / aynı açı)** | Aynı anda, aynı açıdan çekilmiş 5 kare | **Her zaman insan onayı** |

**Kapsam dışı (v1):** video kopyaları, yüz tanıma/kişi gruplama, bulut senkronizasyonu.

### Tasarım ilkeleri (araştırmadan çıkan)
1. **Hiçbir şey kalıcı silinmez.** Geri Dönüşüm Kutusu veya karantina klasörü kullanılır ve her oturum geri alınabilir.
2. **Önerinin gerekçesi her zaman gösterilir.** Örneğin "daha keskin (+%38), gözler açık, 12 MP".
3. **Teknik ikililer tek fotoğraf sayılır.** RAW+JPEG, Live Photo (HEIC+MOV) ve XMP yan dosyaları kopya olarak işaretlenmez.
4. **Kullanıcı kararları kalıcıdır.** "Bu kopya değil" denen ikili bir sonraki taramada tekrar çıkmaz.
5. **Bütün işlem yerelde yapılır, internet gerekmez.** Model uygulamayla birlikte gelir.
6. **İkinci tarama saniyeler sürer.** Bunun için önbellek ve artımlı tarama kullanılır.

---

## 2. Genel görünüm

```
┌──────────────────────────────── UI (PySide6) ────────────────────────────────┐
│  Başlangıç/Klasör seçimi │ Tarama ilerlemesi │ Gruplar listesi │ Karşılaştırma │
│  Ayarlar │ Geçmiş/Geri al │ i18n (tr/en .qm)                                   │
└───────────────▲───────────────────────────────────────────────┬──────────────┘
                │ Qt sinyalleri (ilerleme, sonuç parçaları)       │ komutlar
┌───────────────┴────────────── Uygulama katmanı ────────────────▼──────────────┐
│  ScanController · ReviewSession · ActionExecutor (taşı/çöp/geri al)            │
└───────────────▲────────────────────────────────────────────────┬─────────────┘
                │                                                │
┌───────────────┴────────────── Çekirdek (core) — UI'dan bağımsız ─▼─────────────┐
│ 1 Keşif → 2 Metadata → 3 Önizleme → 4 Özellik çıkarımı → 5 Aday → 6 Doğrulama   │
│ → 7 Gruplama → 8 En iyi kare puanlama                                           │
│        ↕                      ↕                       ↕                         │
│  Katalog (SQLite WAL)   Model çalıştırıcı (ONNX Runtime)   Vektör dizini (usearch)│
└───────────────────────────────────────────────────────────────────────────────┘
```

- **`core` paketi Qt'ye hiç bağımlı değildir.** Bu sayede ayrıca bir CLI (`keepframe-cli`) yazılabilir ve testler başsız (ekransız) çalışır.
- **Uzun işler `QThreadPool` dışında, ayrı bir `ProcessPoolExecutor` içinde çalışır.** Böylece görüntü çözme işi Python'un GIL kilidine takılmaz. GPU çıkarımı tek bir iş parçacığında, toplu (batch) olarak yapılır.

---

## 3. İşlem hattı (pipeline)

### Aşama 1 — Keşif
- `os.scandir` ile alt klasörlere iner. Sonuç **dosya kaydı** olur: yol, boyut, mtime.
- Desteklenen biçimler: JPG/JPEG, PNG, HEIC/HEIF, WEBP, TIFF, BMP, AVIF ve RAW (CR2/CR3, NEF, ARW, DNG, ORF, RW2, RAF…).
- Hariç tutulanlar: kullanıcının dışladığı klasörler, `$RECYCLE.BIN`, `System Volume Information` ve uygulamanın kendi karantina klasörü.
- Katalogda aynı **(yol, boyut, mtime)** üçlüsü varsa dosya **atlanır**. Artımlı taramayı sağlayan budur.

### Aşama 2 — Metadata
Okunacak alanlar: `DateTimeOriginal`, `SubSecTimeOriginal`, `OffsetTimeOriginal`, kamera marka/model/seri no, yön (orientation), boyutlar, GPS.

Seri (burst) kimlikleri:
- Apple: `MakerNotes:BurstUUID`
- Google: `GCamera:BurstID`
- Samsung: dosya adı desenleri

Live Photo için `ContentIdentifier` okunur.

Kullanılacak araçlar:
- Hızlı yol: Pillow `getexif()` + `pillow-heif`.
- Eksik alanlar için yedek: **exiftool** (paketle birlikte gelir, toplu `-json` modunda çalışır).

**Varlık (asset) birleştirme:** aynı klasörde aynı adı taşıyan RAW+JPG, HEIC+MOV ve `.xmp` dosyaları tek bir *asset* altında toplanır. Karşılaştırmada temsilci olarak JPG/HEIC kullanılır.

### Aşama 3 — Önizleme (proxy)
- 512 px'lik bir önizleme üretilir. Kaynağa göre en hızlı yol seçilir:

| Kaynak | Yöntem |
|---|---|
| JPEG | `Image.draft()` (libjpeg-turbo DCT ölçekleme, 3–8 kat hızlı) |
| RAW | `rawpy.extract_thumb()` ile gömülü JPEG önizleme |
| HEIC | `pillow-heif` |

- EXIF yönü uygulanır.
- Önizleme **WebP** olarak diskteki önbelleğe yazılır (`%LOCALAPPDATA%\KeepFrame\thumbs\ab\cd\<id>.webp`). Arayüz de aynı dosyayı kullanır.

### Aşama 4 — Özellik çıkarımı
| Özellik | Araç | Boyut | Ne işe yarar |
|---|---|---|---|
| `sha256` (yalnızca boyutu çakışan dosyalar için) | hashlib | 32 B | Birebir kopya |
| `pdq` + kalite | `pdqhash` | 32 B | Yeniden kodlanmış kopya |
| `dhash64` | numpy | 8 B | Hızlı ön eleme ve yedek yöntem |
| **`emb_dino`** | **DINOv2 ViT-S/14, ONNX, fp16** | 384×2 B | Benzer kare (ana sinyal) |
| `sharp` | Tenengrad / Laplacian varyansı (yüz veya özne bölgesinde) | float | En iyi kare |
| `exposure` | Histogram uçlarındaki kırpılma oranı | float | En iyi kare |
| `faces` | **YuNet** (OpenCV Zoo, MIT) | liste | En iyi kare |
| `eyes_open`, `smile` | **MediaPipe Face Landmarker** blendshape'leri (Apache-2.0) | float | En iyi kare |

- Model çalıştırma **ONNX Runtime** ile yapılır. Sağlayıcı (provider) sırası: `CUDAExecutionProvider` → `DmlExecutionProvider` → `CPUExecutionProvider`.
- Batch boyutu: GPU'da 64, CPU'da 8. Girdi 224×224, ImageNet normalizasyonu.
- Gömme vektörü: CLS + ortalama patch token birleştirilir, L2 ile normalize edilir.
- **Yüz analizi tembel yapılır:** yalnızca aday gruba giren fotoğraflarda çalışır.

### Aşama 5 — Aday çiftler
Her fotoğrafı her fotoğrafla karşılaştırmak (O(n²)) **yasaktır**. Adaylar dört kaynaktan gelir:
1. **Aynı burst ID'si** taşıyan fotoğraflar doğrudan aday olur.
2. **Zaman oturumları:** aynı kamera içinde, aradaki boşluk 60 sn'yi aşmayan çekimler bir oturumdur. Oturum içinde sıralamada ±30 komşu karşılaştırılır.
3. **Birebir ve yeniden kodlanmış kopyalar:** sha256 eşitliği ve PDQ değerinin ≤31 olduğu çiftler, tüm kütüphane genelinde. PDQ/dHash bir BK-ağacında, sha256 bir hash tablosunda tutulur.
4. **(İsteğe bağlı) "Farklı günlerdeki benzerler" taraması:** usearch HNSW dizininde k=10 en yakın komşu, kosinüs ≥ 0.95.

### Aşama 6 — Çift doğrulama
| DINOv2 kosinüs | Karar |
|---|---|
| ≥ T_high (0.92) | Bağla |
| T_low (0.80) – T_high | **ORB + RANSAC homografi** ile kontrol: inlier sayısı ≥ 50 ve oranı ≥ 0.30 ise bağla |
| < T_low | Bağlama |

- Kullanıcının "kopya değil" dediği çiftler (`ignored_pairs`) burada elenir.
- Arayüzdeki tek **"Benzerlik hassasiyeti"** kaydırıcısı T_low ve T_high değerlerini birlikte kaydırır.
- Eşikler sabit değildir. **500 etiketli çiftle kalibre edilir** (bkz. §9).

### Aşama 7 — Gruplama
- Union-find kullanılır ve **zincirlemeye karşı bir koruma** eklenir: bir fotoğraf gruba ancak grup üyelerine ortalama kosinüs benzerliği ≥ 0.85 ise katılır. Bu, A≈B, B≈C ama A≠C durumunda yanlış birleşmeyi önler.
- Grup türü belirlenir: `exact` | `reencoded` | `similar`.

### Aşama 8 — En iyi kare puanlama
Her değer **grup içinde** z-skoruna çevrilir, yani küresel bir eşik kullanılmaz:

```
puan = 0.35·keskinlik_z + 0.30·göz_açık + 0.10·gülümseme + 0.10·pozlama
     + 0.10·çözünürlük_z + 0.05·metadata_zenginliği
```

- **Yüzü olmayan gruplarda** ağırlıklar keskinlik, pozlama ve çözünürlüğe dağıtılır.
- **Gözü kapalı yüz varsa** (blink > 0.5) puana güçlü bir ceza uygulanır.
- **Koruma kuralları:** favori, yıldızlı ya da düzenlenmiş fotoğraflar ve "korumalı klasör"deki dosyalar **asla otomatik olarak çöpe işaretlenmez**.
- **Birebir kopyalarda** puan kullanılmaz. Kural sırası şöyledir: korumalı klasör → kullanıcının tercih ettiği klasör → en kısa yol → en eski.
- Her öneri bir `reasons[]` listesi üretir. Arayüz bu listeyi gösterir.

---

## 4. Veri modeli (SQLite, WAL)

Konum: `%LOCALAPPDATA%\KeepFrame\catalog.db`

```sql
library(id, root_path, added_at, excluded_globs)
file(id, library_id, path UNIQUE, size, mtime, asset_id, kind)          -- kind: image|raw|video|sidecar
asset(id, primary_file_id, taken_at, subsec, tz, camera, serial, burst_id,
      width, height, orientation, is_favorite, rating)
feature(asset_id PK, sha256, pdq BLOB, pdq_q, dhash INTEGER,
        emb BLOB /*fp16*/, model_ver, sharp, exposure, faces_json,
        eyes_open, smile, computed_at)
grp(id, kind, created_scan_id, status)                                  -- status: open|resolved|ignored
grp_member(grp_id, asset_id, score, reasons_json, suggested_action, user_action)
ignored_pair(a_asset, b_asset, created_at)                              -- "kopya değil"
action_log(id, session_id, asset_id, op, src_path, dst_path, ts, undone)
scan(id, started_at, finished_at, settings_json, stats_json)
```

- `model_ver` değişirse ilgili gömme vektörleri geçersiz sayılır ve yalnızca onlar yeniden hesaplanır.
- usearch dizini `emb.usearch` dosyasında, `asset_id` anahtarıyla tutulur.

---

## 5. Arayüz (UX)

### Ekranlar
1. **Başlangıç:** Klasör ekleme (birden fazla klasör olabilir), dışlanan klasörler ve hızlı bir ayar özeti. İlk açılışta 3 adımlı tanıtım gösterilir: kopya ile benzer farkı, dosyaların nereye gittiği, nasıl geri alındığı.
2. **Tarama:**
   - Aşama adı, `n / N`, saniyede işlenen fotoğraf, kalan süre, kullanılan cihaz (GPU/CPU).
   - **Duraklat / Devam / İptal** düğmeleri.
   - Bulunan gruplar tarama bitmeden canlı olarak listelenmeye başlar.
3. **Özet panosu:**
   - Kartlar: "Birebir kopyalar: 412 (3,1 GB)", "Benzer kareler: 1.208 grup", "Bulanık: 87".
   - Kartlarda tahmini kazanılacak alan gösterilir.
4. **İnceleme (ana ekran):**
   - Sol tarafta gruplar listesi; sanal bir `QListView` ile 100 bin öğe takılmadan kaydırılır.
   - Ortada grubun kartları yan yana durur. Her kartta önizleme, **yeşil "Sakla" / kırmızı "Çöpe"** etiketi ve puan çubuğu bulunur.
   - Fareyle üzerine gelince gerekçe görünür.
   - **Senkron zoom/pan:** tekerlek ve sürükleme tüm kartlarda aynı anda işler. Yüze yakınlaştırma seçeneği var.
   - **Sadece farklı olan metadata alanları** gösterilir: çözünürlük, boyut, saat, klasör, kamera.
   - Grup ilerlemesi "12 / 340" biçiminde, İlk / Önceki / Sonraki / Son düğmeleriyle.
5. **Geçmiş:** Oturum listesi, "Tümünü geri al" ve tek tek geri alma.
6. **Ayarlar:** Hassasiyet, zaman penceresi, cihaz seçimi, dil, silme yöntemi (Geri Dönüşüm Kutusu veya karantina), korumalı klasörler.

### Klavye kısayolları
| Tuş | İşlem |
|---|---|
| ← → | Kartlar arasında gezin |
| ↑ ↓ / J K | Önceki / sonraki grup |
| `S` | Odaktaki kartı sakla |
| `D` | Odaktaki kartı çöpe işaretle |
| `Enter` | Öneriyi onayla ve sonraki gruba geç |
| `A` | Hepsini sakla ("kopya değil") |
| `Space` | Tam ekran / 100% zoom |
| `Ctrl+Z` | Geri al |
| `?` | Kısayol yardımı |

### Toplu işlemler
- "Tüm birebir kopyaları çöz (412)"
- "Önerileri bu filtredeki tüm gruplara uygula"

Her toplu işlem önce **sayı ve boyutu gösteren bir onay** ister.

### Görsel dil
- Koyu ve açık tema (Qt Fusion + özel QSS).
- Renk hiçbir zaman tek başına bilgi taşımaz: her renk etiketine bir ikon ve metin eşlik eder.
- Yüksek DPI desteği vardır.

---

## 6. Güvenli işlem katmanı (ActionExecutor)

- **Varsayılan yöntem:** Windows Geri Dönüşüm Kutusu (`send2trash`).
- **Ağ sürücüsü veya NAS** algılanırsa Geri Dönüşüm Kutusu orada çalışmaz. Bu durumda **otomatik olarak karantina klasörüne** geçilir ve kullanıcı uyarılır.
- **Karantina klasörü:** `<kök>\_keepframe_quarantine\<oturum>\<orijinal göreli yol>` yapısında, yani klasör yapısı korunur.
- Her işlem `action_log` tablosuna yazılır. Geri alma işlemi dosyayı log'daki `src_path` konumuna geri taşır.
- **Bir gruptaki son kopya asla silinemez.** Bu kural arayüzde de iş mantığında da uygulanır.
- RAW+JPG, HEIC+MOV ve XMP ikilileri **birlikte** taşınır.
- **(v1.1) Metadata birleştirme:** silinen kopyadaki yıldız ve etiketler, kalan fotoğrafın XMP dosyasına aktarılır.

---

## 7. Klasör yapısı (depo)

```
keepframe/
├─ pyproject.toml            # bağımlılıklar, ruff, pytest, entry points
├─ LICENSE                   # GPL-3.0
├─ README.md / README.tr.md
├─ ARCHITECTURE.md
├─ THIRD_PARTY_LICENSES.md   # Qt(LGPL), DINOv2(Apache), YuNet(MIT), MediaPipe(Apache), x265(GPL)...
├─ src/keepframe/
│  ├─ core/
│  │  ├─ discovery.py        # Aşama 1
│  │  ├─ metadata.py         # Aşama 2 (+ exiftool köprüsü)
│  │  ├─ assets.py           # RAW+JPG / Live Photo birleştirme
│  │  ├─ decode.py           # Aşama 3: draft/rawpy/heif → proxy
│  │  ├─ features/
│  │  │  ├─ hashes.py        # sha256, pdq, dhash
│  │  │  ├─ embedder.py      # ONNX Runtime + DINOv2
│  │  │  ├─ quality.py       # keskinlik, pozlama
│  │  │  └─ faces.py         # YuNet + MediaPipe
│  │  ├─ candidates.py       # Aşama 5
│  │  ├─ verify.py           # Aşama 6 (ORB+RANSAC)
│  │  ├─ grouping.py         # Aşama 7
│  │  ├─ ranking.py          # Aşama 8 + gerekçeler
│  │  ├─ catalog.py          # SQLite erişimi, migrasyonlar
│  │  ├─ index.py            # usearch sarmalayıcı
│  │  ├─ actions.py          # taşı/çöp/geri al
│  │  └─ pipeline.py         # aşamaları yöneten orkestratör, ilerleme olayları
│  ├─ app/                   # Qt'ye bağlı denetleyiciler
│  ├─ ui/                    # pencereler, widget'lar, QSS, ikonlar
│  ├─ i18n/                  # keepframe_tr.ts / keepframe_en.ts → .qm
│  ├─ models/                # dinov2_vits14.onnx, yunet.onnx, face_landmarker.task (+ SHA256)
│  └─ cli.py
├─ tools/
│  ├─ export_dinov2_onnx.py  # modeli ONNX'e dönüştürür (fp16)
│  └─ calibrate.py           # etiketli çiftlerden eşikleri hesaplar
├─ tests/                    # birim testleri + küçük örnek fotoğraf seti
├─ packaging/
│  ├─ keepframe.spec / nuitka.cfg
│  ├─ installer.iss          # Inno Setup
│  └─ winget/                # winget manifest
└─ .github/workflows/        # lint+test (Win/Linux), etiket push'ta Windows derleme + release
```

---

## 8. Paketleme ve dağıtım

| Paket | İçerik | Tahmini boyut |
|---|---|---|
| **KeepFrame-Setup.exe** (varsayılan) | Python çalışma ortamı, PySide6, `onnxruntime-directml`, modeller, exiftool | ~250–350 MB |
| **NVIDIA CUDA eklentisi** (isteğe bağlı) | İlk açılışta "GPU hızlandırmayı indir" seçeneğiyle gelir: `onnxruntime-gpu` ve CUDA/cuDNN DLL'leri | ~600 MB – 1 GB |
| **Taşınabilir .zip** | Kurulumsuz sürüm | Kurulum paketiyle aynı |

- **DirectML** her DX12 ekran kartında çalışır (NVIDIA, AMD, Intel). Bu yüzden CUDA eklentisi olmadan da GPU hızlandırması vardır.
- **Derleme:** önce PyInstaller ile başlanır. Antivirüs yanlış alarmı sorun olursa Nuitka'ya geçilir.
- **Kod imzalama:** SignPath Foundation (açık kaynak projelere ücretsiz) ile yapılır. Bu, SmartScreen uyarısını azaltır.
- **Sürüm akışı:** GitHub Actions'ta bir `v*` etiketi gönderilince Windows derlemesi, kurulum paketi, imzalama, GitHub Release ve winget PR adımları otomatik çalışır.

---

## 9. Kalite güvencesi

- **Etiketli test seti:** 500 çift (seri, aynı açı, benzer ama farklı, birebir kopya, WhatsApp kopyası). `tools/calibrate.py` bu setten hassasiyet/duyarlılık (precision/recall) eğrisini çizer ve varsayılan eşikleri belirler.
- **Hedef:** benzer kareler için **precision ≥ %97**, recall ≥ %90. Burada yanlış pozitif yanlış negatiften daha pahalıdır.
- **Performans hedefi:** 10 bin JPEG, RTX sınıfı bir GPU'da ilk taramada **< 5 dk**, ikinci taramada **< 15 sn**. CPU'da ilk tarama < 25 dk.
- **Birim testleri:** gruplama (zincirleme koruması), varlık birleştirme, geri alma, "son kopya silinemez" kuralı.
- **CI:** her PR'da Windows ve Linux üzerinde `ruff` + `pytest` çalışır.

---

## 10. Yol haritası

| Sürüm | İçerik |
|---|---|
| **0.1 (MVP)** | Klasör tarama, metadata, önizleme, dHash + DINOv2, zaman oturumları, gruplama, keskinliğe dayalı en iyi kare, inceleme ekranı, Geri Dönüşüm Kutusu + geri alma, TR/EN |
| **0.2** | Yüz, göz ve gülümseme puanlaması; ORB doğrulaması; senkron zoom; klavye akışı; toplu işlemler |
| **0.3** | RAW+JPG ve Live Photo birleştirme, HEIC, exiftool, karantina klasörü ve ağ sürücüsü desteği |
| **0.4** | Kurulum paketi, CUDA eklentisi, kod imzalama, winget |
| **1.0** | Kalibre edilmiş eşikler, "farklı günlerdeki benzerler" taraması, metadata birleştirme, belgeler |
| **Sonra** | macOS / Linux derlemeleri, CLI, Lightroom katalog desteği |

---

## 11. Üçüncü taraf lisans özeti

| Bileşen | Lisans | Not |
|---|---|---|
| PySide6 / Qt 6 | LGPL-3.0 | Dinamik bağlanır |
| ONNX Runtime | MIT | |
| DINOv2 ağırlıkları | Apache-2.0 | |
| YuNet | MIT | |
| MediaPipe Face Landmarker | Apache-2.0 | |
| OpenCV | Apache-2.0 | |
| usearch | Apache-2.0 | |
| pdqhash (Meta PDQ) | BSD | |
| rawpy / LibRaw | MIT / LGPL-2.1 | |
| pillow-heif (libheif, libde265, x265) | BSD / LGPL / **GPL-2.0** | GPL-3.0 seçimimizle uyumlu |
| exiftool | Artistic/GPL | Ayrı bir çalıştırılabilir dosya olarak gelir |
| send2trash | BSD | |

**Kullanılmayacaklar** (ticari kullanıma kapalı ya da kısıtlayıcı lisanslar): InsightFace modelleri, SuperPoint ağırlıkları, pyiqa, DINOv3 (lisansı OSI uyumlu değil).
