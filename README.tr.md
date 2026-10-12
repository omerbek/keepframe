<p align="center"><img src="docs/icon-512.png" width="112" alt="KeepFrame"></p>

# KeepFrame

**En iyi kareyi bul, gerisini temizle.** Kopya ve *benzer* fotoğrafları (seri çekimler, aynı
açıdan tekrar çekilen kareler) yerel yapay zekâ ile bulan, yan yana karşılaştırmanızı sağlayan ve
yalnızca **sizin** seçtiklerinizi kaldıran ücretsiz, açık kaynak bir Windows uygulaması. Hiçbir
dosya kalıcı olarak silinmez.

[English](README.md) · [Mimari](docs/ARCHITECTURE.tr.md)

> Durum: **erken geliştirme (0.1.0.dev0)**. Önce fotoğraflarınızın bir kopyası üzerinde deneyin.

## Özellikler

**Benzer fotoğraflar (ana araç)**
- Birkaç saniye içinde çekilen seri ve tekrar kareleri gruplar. Bunun için EXIF saati, dosya
  adındaki saat ve kamera bilgisini kullanır; farklı telefonlarla çekilenleri de karşılaştırır.
- Arşivin her yerindeki küçültülmüş / yeniden kaydedilmiş kopyaları (örn. EXIF'siz WhatsApp
  kopyaları) ve birebir aynı dosyaları da bulur.
- DINOv2 ile yapay zekâ benzerliği (NVIDIA CUDA, DirectML destekli her ekran kartı ya da CPU). Model
  yoksa hızlı dHash + ORB modu kullanılır.
- **Karar sizin.** Uygulama yalnızca en iyi bulduğu kareye *Önerilen* rozeti koyar ve nedenini
  söyler. Hiçbir şey önceden işaretlenmez.
- **Seç menüsü** (czkawka / Duplicate Cleaner gibi). Kurallar: önerilen hariç tümü, en yüksek
  çözünürlük hariç, en büyük dosya hariç, en keskin hariç, en eski / en yeni hariç, en kısa yol
  hariç, en keskinin %X'inden bulanık olanlar, HEIC/JPG/RAW tercihi, bir klasördeki kopyayı sakla,
  regex, tersine çevir, temizle. Kurallar bu gruba, filtrelenen gruplara ya da tüm gruplara
  uygulanabilir.
- **Hızlı görsel inceleme:**
  - Küçük resimli kartlar.
  - Anında tam ekran önizleme (Boşluk).
  - Senkron yakınlaştırmalı yan yana karşılaştırma (C).
  - Klavye akışı: X işaretle, J/K sonraki/önceki grup, R son kuralı uygula ve devam et.
- "Kopya değil" kararı sonraki taramalarda hatırlanır. Favori/yıldızlı fotoğraflar ve korumalı
  klasörler kurallarla asla işaretlenmez. Her grupta en az bir fotoğraf her zaman korunur.

**Dosya araçları (czkawka tarzı)**: kopya dosyalar (her tür), büyük dosyalar, boş dosyalar, boş
klasörler, geçici dosyalar, bozuk görseller, yanlış uzantılar.

**Güvenlik:**
- Kaldırılan dosyalar Geri Dönüşüm Kutusu'na ya da karantina klasörüne gider. Ağ ve USB
  sürücülerde her zaman karantina klasörü kullanılır.
- Taramadan sonra değişmiş dosyalara dokunulmaz.
- RAW+JPG, Live Photo ve XMP dosyaları birlikte taşınır.
- Her oturum Geçmiş ekranından geri alınabilir.
- Yalnızca bulutta duran OneDrive dosyaları varsayılan olarak atlanır, böylece toplu indirme
  olmaz.

**Hız**: Her dosya bir kez açılır. 512 piksellik küçük resimler diske, özellikler SQLite önbelleğe
yazılır. Böylece değişmemiş bir arşivin yeniden taranması saniyeler sürer.

## Kurulum

### En kolayı: kurulum dosyasını indirin (Python gerekmez)
1. **[Releases](https://github.com/omerbek/keepframe/releases/latest)** sayfasından
   **`KeepFrame-Setup-x.y.z.exe`** dosyasını indirin. Kurmadan kullanmak isterseniz
   `KeepFrame-portable.zip` dosyasını indirin.
2. Çalıştırın. Yapay zekâ modeli içinde gelir, başka kurulum gerekmez.
3. Uygulama henüz imzalı olmadığı için Windows SmartScreen *"Windows bilgisayarınızı korudu"*
   diyebilir: **Ek bilgi → Yine de çalıştır** seçeneğine tıklayın.

### Seçenek A: Kaynaktan çalıştırın (Python 3.10+ kurulu olmalı)
1. Bu depoyu indirin (Code → Download ZIP) ve zip'i açın.
2. **`run_keepframe.bat`** dosyasına çift tıklayın. İlk açılışta gerekli her şey kurulur.
3. İsteğe bağlı, yapay zekâ modu için: **`tools\get_model.bat`** dosyasını bir kez çalıştırın.
   Yaklaşık 100 MB indirir ve modeli dönüştürür.

### Seçenek B: `KeepFrame.exe` derleyin
**`packaging\build_exe.bat`** dosyasını çalıştırın. Sonuçta şunlar oluşur:
- `dist\KeepFrame\KeepFrame.exe` (taşınabilir sürüm).
- [Inno Setup 6](https://jrsoftware.org/isdl.php) kuruluysa `dist\KeepFrame-Setup-x.y.z.exe`
  kurulum dosyası.

## Lisans
GPL-3.0-or-later.
