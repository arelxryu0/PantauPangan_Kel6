"""
Deteksi potensi lonjakan harga dengan AutoGluon TabularPredictor (klasifikasi biner),
pengganti K-Means pada versi sebelumnya.

Pertanyaan yang dijawab model untuk setiap kota-komoditas:
"Apakah harga tertinggi dalam 7 hari ke depan naik >= 5% dari harga hari ini?"

AutoGluon melatih LightGBM, CatBoost, XGBoost, Random Forest, Extra Trees, dan
neural network, lalu menggabungkannya menjadi weighted ensemble.
"""
import shutil

import pandas as pd
from sklearn.metrics import confusion_matrix

from ml.autogluon_util import Penangkap, rapikan_bobot
from ml.dataprep import FITUR, siapkan_deret, tabel_fitur


def _info(nama, d):
    return {"nama": nama, "baris": int(len(d)), "naik": int(d["naik"].sum()),
            "persen": round(float(d["naik"].mean() * 100), 2) if len(d) else 0,
            "awal": str(d["tanggal"].min().date()) if len(d) else "-",
            "akhir": str(d["tanggal"].max().date()) if len(d) else "-"}


def latih_risiko(df, path, horizon=7, ambang_persen=5.0, time_limit=180,
                 presets="medium_quality", catat=print, model=None):
    from autogluon.tabular import TabularPredictor

    seri, asli = siapkan_deret(df, minimal=60)
    tabel = tabel_fitur(seri, asli, horizon=horizon, ambang_persen=ambang_persen)
    berlabel = tabel.dropna(subset=["naik"]).copy()
    if berlabel.empty:
        raise ValueError("data belum cukup, butuh minimal 60 hari data harian per kota-komoditas")
    berlabel["naik"] = berlabel["naik"].astype(int)

    # Pembagian berdasarkan urutan waktu, dengan jeda `horizon` hari di setiap batas
    akhir = berlabel["tanggal"].max()
    awal_uji = akhir - pd.Timedelta(days=60)
    awal_val = awal_uji - pd.Timedelta(days=60 + horizon)
    jeda = pd.Timedelta(days=horizon)
    uji = berlabel[berlabel["tanggal"] > awal_uji]
    val = berlabel[(berlabel["tanggal"] > awal_val) & (berlabel["tanggal"] <= awal_uji - jeda)]
    latih = berlabel[berlabel["tanggal"] <= awal_val - jeda]
    pembagian = [_info("Latih", latih), _info("Validasi", val), _info("Uji", uji)]

    for nama, d in (("latih", latih), ("uji", uji)):
        if d["naik"].nunique() < 2:
            raise ValueError(f"data {nama} belum memuat kejadian naik dan tidak naik sekaligus; "
                             f"tambah rentang data harian")

    shutil.rmtree(path, ignore_errors=True)
    kolom = FITUR + ["naik"]
    catat(f"Melatih TabularPredictor dengan {len(latih)} baris data latih (batas {time_limit} detik)")
    prediktor = TabularPredictor(label="naik", problem_type="binary", eval_metric="balanced_accuracy",
                                 sample_weight="balance_weight", path=path, verbosity=2)
    pakai_val = val["naik"].nunique() == 2
    with Penangkap() as tangkap:
        prediktor.fit(latih[kolom], tuning_data=val[kolom] if pakai_val else None,
                      presets=presets, time_limit=time_limit,
                      hyperparameters=model)

    catat("Mengevaluasi model deteksi lonjakan pada data uji")
    data_uji = uji[kolom]
    papan = prediktor.leaderboard(data_uji, silent=True)
    leaderboard = [{
        "model": r["model"],
        "skor_uji": round(float(r["score_test"]), 4) if pd.notna(r.get("score_test")) else None,
        "skor_val": round(float(r["score_val"]), 4) if pd.notna(r.get("score_val")) else None,
        "waktu_latih": round(float(r.get("fit_time", 0) or 0), 2),
    } for _, r in papan.iterrows()]

    metrik = {k: round(float(v), 4) for k, v in
              prediktor.evaluate(data_uji, auxiliary_metrics=True, silent=True).items()}
    tebak = prediktor.predict(data_uji)
    tn, fp, fn, tp = confusion_matrix(uji["naik"], tebak, labels=[0, 1]).ravel()

    catat("Menghitung fitur yang paling berpengaruh")
    try:
        penting = prediktor.feature_importance(data_uji, time_limit=90, silent=True)
        fitur_penting = [{"fitur": f, "nilai": round(float(r["importance"]), 5),
                          "stddev": round(float(r.get("stddev", 0) or 0), 5),
                          "p_value": round(float(r.get("p_value", 1) or 1), 4)}
                         for f, r in penting.iterrows()]
    except Exception as e:
        catat(f"Fitur penting dilewati: {e}")
        fitur_penting = []

    catat("Menghitung peluang naik untuk kondisi terkini")
    terkini = tabel.sort_values("tanggal").groupby(["kota", "komoditas"]).tail(1).copy()
    terkini["peluang"] = prediktor.predict_proba(terkini[FITUR])[1].values * 100
    baris_terkini = [{
        "wilayah": r["kota"], "komoditas": r["komoditas"], "tanggal": r["tanggal"].strftime("%Y-%m-%d"),
        "harga": float(r["harga"]), "peluang": float(r["peluang"]),
        "ubah_7h": None if pd.isna(r["ubah_7h"]) else float(r["ubah_7h"]),
        "ubah_30h": None if pd.isna(r["ubah_30h"]) else float(r["ubah_30h"]),
        "volatilitas_30h": None if pd.isna(r["volatilitas_30h"]) else float(r["volatilitas_30h"]),
        "vs_rata_30h": None if pd.isna(r["vs_rata_30h"]) else float(r["vs_rata_30h"]),
    } for _, r in terkini.iterrows()]

    return {
        "model_terbaik": prediktor.model_best,
        "bobot": rapikan_bobot(tangkap.bobot),
        "leaderboard": leaderboard,
        "metrik": metrik,
        "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "fitur_penting": fitur_penting,
        "pembagian": pembagian,
        "terkini": baris_terkini,
        "ringkas": {
            "ambang_lonjakan": ambang_persen,
            "horizon": horizon,
            "preset": presets,
            "batas_waktu": time_limit,
            "jumlah_deret": len(seri),
        },
    }
