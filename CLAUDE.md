# ReverseCAD

Meta Global AI Developer Hackathon projesi. Bir parçanın fotoğrafından, **gerçek milimetre ölçülerinde** ve **düzenlenebilir (parametrik)** bir 3B model üretir. Çıktı ölü bir mesh değil, parametreleri değiştirilebilen CadQuery kodudur.

## Benimle çalışırken

- Kodlamada yeniyim. Her adımda ne yaptığını ve neden yaptığını kısaca, basit bir dille açıkla.
- Bir şey kurman, silmen veya uzun süren bir şey çalıştırman gerektiğinde önce bana söyle.
- Kodları küçük, ayrı dosyalarda tut; her dosyanın başına ne işe yaradığını yazan kısa bir açıklama ekle.
- API anahtarları yalnızca `.env` dosyasında durur ve `.env` `.gitignore`'dadır. Anahtarları asla koda veya çıktıya yazma.
- Bir adımı bitirmeden diğerine geçme. Her adımın sonunda çalıştığını gösteren küçük bir test veya çıktı olsun.

## Akış

1. **Girdi:** Parça + yanında kredi kartı (85,60 × 53,98 mm) olan, üstten çekilmiş fotoğraf. (İleride: üstten ve yandan iki kanonik çekim.)
2. **Maske:** Meta SAM 3.1, metin komutuyla (`credit card`, `bracket` vb.) kartın ve parçanın maskesini çıkarır.
3. **Ölçek ve ölçü:** Deterministik Python kodu kart maskesinden `mm_per_pixel` oranını bulur; parçanın sınır kutusunu, delik çaplarını ve merkez koordinatlarını milimetre olarak hesaplar. Gerekirse kartın dört köşesiyle homografi (`cv2.getPerspectiveTransform`) kurup görüntüyü ortografiğe düzeltir.
4. **Aday üretimi:** Muse Spark Open (Baseten üzerinden) görüntü + ölçü tablosunu alıp 10-30 farklı aday CadQuery kodu yazar.
5. **Doğrulama:** Her aday derlenir, ortografik siluet render edilir, SAM maskesiyle IoU ölçülür.
6. **Seçim:** En yüksek IoU'lu aday kazanır. Eşik tutmazsa XOR fark görüntüsü modele geri verilip ikinci nesil üretilir.
7. **Çıktı:** Kazanan model gösterilir, STL/STEP indirilebilir; sürgülerle parametreler değiştirilip anında yeniden derlenir.

## Üç kritik mühendislik kararı

1. **Ölçek düzlemsel referanstan gelir.** Madeni para değil, kredi kartı veya bilinen kenarlı kare. Çekim 60-70 cm uzaktan, zoom ile, dik açıdan (paralaks hatasını azaltmak için).
2. **Hizalama kanonik çekimle yapılır, kamera pozu tahmin edilmez.** SAM maskesi ve render edilmiş siluet ikisi de ağırlık merkezine taşınır ve ana eksenine (PCA veya `cv2.minAreaRect`) göre döndürülür; sonra IoU hesaplanır. Render her zaman **ortografik**tir.
3. **Ölçüyü kod verir, topolojiyi model.** Dil modeli piksel sayıp milimetre hesaplamaz. Sayılar ölçü tablosundan gelir; modelden istenen yalnızca yapı: L-braket mi, plaka mı, delikler nerede, pah var mı.

## Kapsam

Yalnızca düz yüzeyli, prizmatik, delikli parçalar: braket, plaka, kapak, basit tırnak, aparat. Kavisli ve organik parçalar kapsam dışı.

## Modeller

| Model | Nerede | Kullanım |
|---|---|---|
| SAM 3.1 | Meta Model API | Maske çıkarma, doğrulama |
| Muse Spark Open | Baseten, model adı tam olarak `meta-models/muse-spark-open-1026` (dokümanlarda `-1026` yok, biz her zaman ekliyoruz) | Paralel aday kod üretimi |
| Muse Wonder | Meta Model API | Zor adaylarda geometrik akıl yürütme (sonraki aşama) |
| Muse Voice Transcribe | Meta Model API | Sesli düzenleme (olsa iyi olur) |

Ortam değişkenleri: `BASETEN_API_KEY`, `META_API_KEY` (`.env` içinde).

## Başarı ölçütleri

| Ölçü | Hedef |
|---|---|
| Ölçü hatası (model vs cetvel) | Ortalama %5 altı |
| Siluet IoU | %90 üstü |
| Başarı oranı (eşiği geçen çalışma) | %70 üstü |
| Parametre değişikliğinde derleme başarısı | %95 üstü |

## Hackathon kuralları

- Yalnızca hackathon süresince yazılan kod.
- Repo herkese açık ve tek parça; jüri demoyu kendisi çalıştırabilmeli (kurulum adımları README'de net olmalı).

## Durum

- [x] Ölçek testi (elle): anahtar + kart fotoğrafı, SAM maskeleri temiz ayrıldı; hesaplanan boy 56-57 mm, cetvel 55-56 mm, fark yaklaşık %1-3. Örnek fotoğraf: `ornek_anahtar.jpg`
- [x] Python ortamı, git, `.gitignore`, `.env` (`.venv` + `requirements.txt`, kontrol: `.venv\Scripts\python.exe check_env.py`)
- [ ] CadQuery ile elle yazılmış basit parça + ortografik siluet render
- [ ] IoU fonksiyonu (merkezleme + hizalama) ve testleri
- [ ] Baseten'e ilk çağrı
- [ ] SAM 3.1'i koddan çağırma
- [ ] Tek adayla uçtan uca iskelet: fotoğraf → maske → ölçü → kod → derleme → IoU
