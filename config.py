import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

SECRET_KEY = os.environ.get("SECRET_KEY", "ganti-kunci-rahasia-ini")
DATABASE = os.path.join(BASE_DIR, "instance", "pangan.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
FOLDER_MODEL = os.path.join(BASE_DIR, "model_ag")          # model AutoGluon disimpan di sini
LOG_LATIH = os.path.join(BASE_DIR, "instance", "latih.log")  # catatan proses pelatihan terakhir

# Kota di Provinsi Riau yang dipantau PIHPS (pasar tradisional)
WILAYAH_RIAU = ["Pekanbaru", "Dumai", "Tembilahan"]

# Nama lain yang mungkin muncul di file, diarahkan ke nama baku
ALIAS_WILAYAH = {"indragiri hilir": "Tembilahan"}

# ---------------------------------------------------------------
# AutoGluon
# ---------------------------------------------------------------
HORIZON = 7                     # jumlah hari yang diramalkan
PRESET_AUTOGLUON = "medium_quality"
WAKTU_LATIH_PERAMALAN = 300     # detik, batas waktu TimeSeriesPredictor
WAKTU_LATIH_RISIKO = 180        # detik, batas waktu TabularPredictor
PILIHAN_WAKTU = [120, 300, 600] # pilihan batas waktu di panel admin

# Definisi "lonjakan" untuk TabularPredictor:
# harga tertinggi 7 hari ke depan naik >= persen ini dari harga hari ini
AMBANG_LONJAKAN = 5.0

# ---------------------------------------------------------------
# Peringatan dini
# ---------------------------------------------------------------
# Ambang kenaikan hasil ramalan (persen), bisa diatur per komoditas di panel admin.
# Waspada jika kenaikan >= ambang, Siaga jika kenaikan >= 2 x ambang.
AMBANG_DEFAULT = 5.0
# Batas peluang naik dari TabularPredictor (persen)
PELUANG_WASPADA = 50.0
PELUANG_SIAGA = 70.0

# ---------------------------------------------------------------
# Tampilan
# ---------------------------------------------------------------
KOMODITAS_UTAMA = "Cabai Merah Keriting"   # komoditas yang tampil pertama di beranda
RENTANG_GRAFIK = [30, 90, 180, 365, 0]   # 0 = semua data
BARIS_PER_HALAMAN = 50

# ---------------------------------------------------------------
# Model yang dibandingkan
# Isi dengan nama model AutoGluon. AutoGluon tetap membuat satu
# WeightedEnsemble (gabungan) dari model-model ini.
# Ganti jadi None kalau ingin AutoGluon mencoba semua model bawaan.
# ---------------------------------------------------------------
# Peramalan harga (TimeSeriesPredictor):
#   "Chronos2"      -> deep learning, model fondasi Transformer pretrained
#                      (butuh internet saat pertama kali, untuk mengunduh model)
#   "DirectTabular" -> machine learning (LightGBM)
#   pilihan lain: "Toto2", "RecursiveTabular", "DeepAR", "ETS", "Theta"
MODEL_PERAMALAN = {
    "Chronos2": {},
    "DirectTabular": {},
}

# Peluang kenaikan harga (TabularPredictor):
#   "XGB" -> XGBoost
#   "GBM" -> LightGBM
#   pilihan lain: "CAT" (CatBoost), "NN_TORCH" (jaringan saraf), "XT" (Extra Trees)
MODEL_RISIKO = {
    "XGB": {},
    "GBM": {},
}
