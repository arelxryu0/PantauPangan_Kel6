# Pantau Pangan Riau

**Sistem Monitoring dan Peringatan Dini Harga Pangan Strategis di Pasar Tradisional Provinsi Riau Berbasis AutoML AutoGluon**

Pantau Pangan Riau adalah aplikasi web untuk memantau, meramal, dan memberi peringatan dini harga 21 komoditas pangan pokok di pasar tradisional **Pekanbaru**, **Dumai**, dan **Tembilahan**. Data yang dipakai adalah harga harian dari PIHPS Nasional Bank Indonesia.

Project ini dikerjakan oleh Kelompok 6 untuk mata kuliah Capstone Project, Teknik Informatika, Universitas Islam Riau.

---

## Daftar Isi

- [Latar Belakang](#latar-belakang)
- [Tujuan](#tujuan)
- [Fitur](#fitur)
- [Metode dan Model](#metode-dan-model)
- [Tech Stack](#tech-stack)
- [Struktur Folder](#struktur-folder)
- [Instalasi](#instalasi)
- [Cara Menggunakan](#cara-menggunakan)
- [Cara Membaca Hasil](#cara-membaca-hasil)
- [Mengganti Model](#mengganti-model)
- [Troubleshooting](#troubleshooting)
- [Referensi](#referensi)

---

## Latar Belakang

Harga pangan pokok di Riau, terutama cabai dan bawang merah, naik turun hampir setiap hari karena musim, cuaca, hari besar, dan pasokan antar daerah. Contohnya, harga cabai merah keriting di Pekanbaru naik **47,8% dalam 30 hari** hingga Rp88.150/kg pada 1 Oktober 2026.

Bank Indonesia sudah mencatat harga harian lewat PIHPS, tetapi data itu hanya berupa tabel historis per kota. Tidak ada perkiraan harga ke depan dan tidak ada tanda bahaya, sehingga Tim Pengendalian Inflasi Daerah (TPID) dan dinas terkait biasanya baru bergerak setelah harga sudah tinggi.

Penelitian terdahulu umumnya hanya meneliti satu komoditas di satu wilayah, memakai data mingguan atau bulanan, memilih model secara manual, dan belum menyediakan peringatan dini. Project ini mengisi celah tersebut.

## Tujuan

1. **Memantau** harga harian 21 komoditas di tiga kota dalam satu dashboard.
2. **Meramal** harga 7 hari ke depan beserta rentang perkiraannya.
3. **Menghitung peluang** harga naik minimal 5% dalam 7 hari.
4. **Memperingatkan** dengan status Aman, Waspada, atau Siaga beserta alasannya.
5. **Menyajikan evaluasi** model secara terbuka pada data uji yang tidak ikut dilatih.

Project ini sejalan dengan **SDG 2 (Tanpa Kelaparan), target 2.c**: membuka akses informasi pasar yang tepat waktu untuk membatasi gejolak harga pangan yang ekstrem.

## Fitur

| Halaman | Isi |
|---|---|
| **Beranda** | Papan harga 3 kota, grafik perbandingan antar kota (30/90/180 hari, 1 tahun, semua), komoditas naik/turun terbesar |
| **Analisis** | Statistik per kota, rata-rata bulanan, selisih harga antar kota |
| **Data Harga** | Tabel data mentah, filter, dan unduh CSV |
| **Risiko Kenaikan** | Peta peluang naik per kota, 15 peluang tertinggi, faktor paling berpengaruh |
| **Peramalan** | Grafik harga asli dan ramalan 7 hari dengan rentang 10%–90%, serta uji model |
| **Peringatan Dini** | Status Siaga, Waspada, Aman per kota dan komoditas beserta alasannya |
| **Evaluasi Model** | Leaderboard model, MAPE per komoditas, confusion matrix, riwayat pelatihan |
| **Panel Admin** | Impor data PIHPS, latih model di latar belakang, atur ambang kenaikan per komoditas |

## Metode dan Model

Sistem memakai **AutoML AutoGluon** untuk dua tugas. Setiap tugas membandingkan dua model, lalu AutoGluon memilih yang terbaik dan membentuk **WeightedEnsemble** dari keduanya.

| Tugas | Predictor | Model | Metrik |
|---|---|---|---|
| Peramalan harga 7 hari | `TimeSeriesPredictor` | **Chronos-2** (Transformer pretrained) dan **DirectTabular** (LightGBM) | MAPE, RMSE |
| Peluang harga naik ≥5% | `TabularPredictor` | **XGBoost** dan **LightGBM** | Balanced accuracy, recall |

**Aturan peringatan dini**

| Status | Syarat |
|---|---|
| 🔴 Siaga | Ramalan naik ≥10% **atau** peluang naik ≥70% |
| 🟡 Waspada | Ramalan naik ≥5% **atau** peluang naik ≥50% |
| 🟢 Aman | Selain itu |

**Pengolahan data**

- Hari libur yang tidak tercatat diisi harga hari sebelumnya (forward fill). Interpolasi tidak dipakai agar tidak terjadi kebocoran data.
- 11 fitur: harga, perubahan 1/7/14/30 hari, volatilitas 14 dan 30 hari, selisih terhadap rata-rata 30 hari, bulan, hari, kota, komoditas.
- Label "naik" jika harga 7 hari kemudian lebih tinggi minimal 5%.
- Data dibagi menurut waktu: uji = 60 hari terakhir, validasi = 60 hari sebelumnya, dengan jeda 7 hari. Untuk peramalan, 7 hari terakhir dipakai sebagai data uji.

## Tech Stack

| Lapisan | Teknologi |
|---|---|
| Bahasa | Python 3.12 |
| Machine learning | AutoGluon 1.6 (TimeSeries + Tabular), PyTorch, LightGBM, XGBoost |
| Olah data | pandas, NumPy, scikit-learn, openpyxl, xlrd |
| Backend | Flask 3.0.3 |
| Database | SQLite (satu file `instance/pangan.db`) |
| Frontend | HTML, CSS, JavaScript, Jinja2, Chart.js 4.4.1 |
| Alat kerja | VS Code, Google Colab, Git |

## Struktur Folder

```
pp_pangan-riau/
├── app.py                 # Aplikasi Flask: semua halaman dan panel admin
├── config.py              # Pengaturan: daftar model, horizon, ambang, batas waktu latih
├── database.py            # Skema dan koneksi SQLite
├── init_db.py             # Membuat database dan akun admin
├── latih_model.py         # Menjalankan pelatihan kedua model (dipanggil dari panel admin)
├── jalankan.bat           # Sekali klik: buat venv, pasang library, jalankan website
├── requirements.txt
├── ml/
│   ├── dataprep.py        # Persiapan data, 11 fitur, pembagian data
│   ├── peramalan.py       # TimeSeriesPredictor (Chronos-2, DirectTabular)
│   ├── risiko.py          # TabularPredictor (XGBoost, LightGBM)
│   └── autogluon_util.py  # Mencatat bobot ensemble
├── utils/
│   ├── importer.py        # Membaca file Excel PIHPS dan CSV template
│   └── peringatan.py      # Aturan Aman, Waspada, Siaga
├── templates/             # Halaman HTML (Jinja2)
├── static/                # CSS, JavaScript, logo
├── data/
│   └── template_import.csv
├── instance/              # (dibuat otomatis) pangan.db dan log pelatihan
├── model_ag/              # (dibuat otomatis) model AutoGluon hasil pelatihan
└── uploads/               # (dibuat otomatis) arsip file yang diupload
```

## Instalasi

### Prasyarat

- Windows 10/11 (Linux dan macOS juga bisa dengan perintah yang disesuaikan)
- **Python 3.12**. Saat memasang dari python.org, centang **"Add python.exe to PATH"**.
- Koneksi internet saat pemasangan pertama dan saat pelatihan pertama (untuk mengunduh Chronos-2)
- Ruang disk sekitar 5 GB untuk library

### Cara cepat

1. Ekstrak zip, lalu buka foldernya di VS Code.
2. Di terminal, jalankan:

   ```powershell
   .\jalankan.bat
   ```

   Bisa juga dengan klik dua kali `jalankan.bat`. Pertama kali akan memasang library (10–30 menit). Berikutnya langsung jalan.
3. Browser terbuka otomatis ke **http://127.0.0.1:5000**.

### Cara manual

```powershell
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Kalau muncul *"running scripts is disabled"*, jalankan sekali:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Menjalankan lagi di lain waktu

```powershell
.\venv\Scripts\Activate.ps1
python app.py
```

## Cara Menggunakan

### 1. Login admin

Database baru otomatis membuat akun bawaan:

- Username: `admin`
- Password: `admin123`

Ganti password (atau buat akun baru) dengan:

```powershell
python init_db.py
```

Password disimpan dalam bentuk hash, jadi tidak bisa dilihat. Kalau lupa, jalankan perintah di atas lagi. Data harga tidak akan terhapus.

### 2. Impor data PIHPS

1. Unduh data **harian** dari PIHPS Nasional (hargapangan.id) untuk setiap kota.
2. Panel Admin → tab **Data** → pilih file → format **Tabel unduhan PIHPS** → pilih **kota** yang sesuai → **Impor data**.
3. Ulangi untuk Pekanbaru, Dumai, dan Tembilahan.

File PIHPS tidak mencantumkan nama kota, jadi pastikan kota yang dipilih benar. Data yang sama akan diperbarui, tidak digandakan.

### 3. Latih model

Panel Admin → tab **Model AutoGluon** → pilih **Keduanya** dan batas waktu **5 menit** → **Latih model sekarang**. Pelatihan berjalan di latar belakang, status dan log tampil langsung, dan halaman memuat ulang sendiri setelah selesai.

Latih ulang setiap kali ada data baru.

### Kebutuhan data

| Data | Keterangan |
|---|---|
| Minimal | 60 hari data harian per kota-komoditas (model peluang naik), 35 hari (peramalan) |
| Disarankan | 2–3 tahun data harian, agar pola musiman seperti Lebaran tercatat berulang |
| Tidak dipakai | Data bulanan atau tahunan (terlalu sedikit titik untuk melatih model) |

## Cara Membaca Hasil

| Istilah | Arti |
|---|---|
| **MAPE** | Rata-rata persentase ramalan meleset. Di bawah 10% tergolong baik |
| **Rentang 10%–90%** | Area perkiraan harga. Harga sebenarnya diperkirakan 80% berada di dalamnya |
| **Peluang naik** | Kemungkinan harga naik ≥5% dalam 7 hari. Tinggi ≥70%, sedang 50–70% |
| **Balanced accuracy** | Ketepatan menebak naik dan tidak naik secara seimbang (0–1) |
| **Recall** | Persentase lonjakan yang berhasil terdeteksi |
| **Confusion matrix** | Tabel tebakan benar dan salah pada data uji |

**Target keberhasilan**

- MAPE median peramalan 7 hari ≤10%
- Balanced accuracy ≥0,70 dan recall ≥0,60
- Semua fungsi wajib lolos uji black-box

## Mengganti Model

Daftar model diatur di `config.py`:

```python
MODEL_PERAMALAN = {
    "Chronos2": {},
    "DirectTabular": {},
}

MODEL_RISIKO = {
    "XGB": {},   # XGBoost
    "GBM": {},   # LightGBM
}
```

Pilihan lain untuk peramalan: `"Toto2"`, `"RecursiveTabular"`, `"DeepAR"`, `"ETS"`, `"Theta"`. Untuk peluang naik: `"CAT"` (CatBoost), `"NN_TORCH"`, `"XT"`. Isi `None` agar AutoGluon mencoba semua model bawaan. Setelah diubah, latih ulang dari panel admin.

## Troubleshooting

| Masalah | Solusi |
|---|---|
| `py` tidak dikenali | Python belum terpasang atau PATH belum dicentang. Pasang ulang Python 3.12 |
| `Activate.ps1` tidak ditemukan | venv belum dibuat di folder ini. Jalankan `py -3.12 -m venv venv` |
| `ModuleNotFoundError: flask` | venv belum aktif. Jalankan `.\venv\Scripts\Activate.ps1` |
| Link `127.0.0.1:5000` tidak terbuka | Pastikan `python app.py` masih berjalan dan muncul `Running on http://127.0.0.1:5000` |
| Login gagal | Jalankan `python init_db.py` untuk membuat ulang password |
| Halaman Peramalan/Risiko kosong | Model belum dilatih. Impor data lalu latih dari panel admin |
| Chronos-2 gagal saat pelatihan | Biasanya karena internet. Pelatihan tetap selesai memakai DirectTabular |
| `WARNING: This is a development server` | Normal, bukan error |

## Catatan

- Database (`instance/pangan.db`), `venv`, `model_ag`, dan `uploads` tidak ikut dalam repositori atau zip. Untuk berbagi data, kirim `instance/pangan.db` secara terpisah.
- Aplikasi ini dirancang untuk dijalankan secara lokal. Hosting statis seperti Netlify tidak bisa menjalankan Flask dan AutoGluon.

## Referensi

1. A. Apriliani, A. I. A. Himayati, dan F. Findasari, "Prediksi Harga Cabai Merah Berbasis Long Short-Term Memory dan Komparasi ARIMA pada Data Runtun Waktu," *Euler*, vol. 14, no. 2, hlm. 467–483, 2026. doi: 10.37905/euler.v14i2.39298
2. N. Ikhwana, A. T. Utomo, A. Syalsabila, dan L. R. Rahmanda, "Forecasting Monthly Red Chili Prices in South Sulawesi Using Prophet Model with Time Series Cross-Validation," *ARRUS Journal of Mathematics and Applied Science*, vol. 6, no. 1, hlm. 69–76, 2026. doi: 10.35877/mathscience4893
3. R. B. Salsabilah, Y. V. Via, dan E. Y. Puspaningrum, "Rapid Application Development Method for Web-Based Shallot Price Prediction Using Machine Learning Model," *Bit-Tech*, vol. 8, no. 2, hlm. 2724–2734, 2025. doi: 10.32877/bt.v8i2.3348
4. AutoGluon: https://auto.gluon.ai
5. PIHPS Nasional Bank Indonesia: https://www.bi.go.id/hargapangan

---

Kelompok 6 · Capstone Project · Teknik Informatika · Universitas Islam Riau · 2026