"""
Peramalan harga 7 hari ke depan dengan AutoGluon TimeSeriesPredictor
(pengganti LSTM pada versi sebelumnya).

AutoGluon melatih beberapa model sekaligus (Chronos-2, Toto-2, ETS, Theta,
LightGBM berbasis deret waktu, dan lain-lain), lalu menggabungkannya menjadi
weighted ensemble. Semua kota-komoditas dilatih dalam satu kali proses.
"""
import shutil

import numpy as np
import pandas as pd

from ml.autogluon_util import Penangkap, rapikan_bobot
from ml.dataprep import nama_item, pisah_item, siapkan_deret


def latih_peramalan(df, path, horizon=7, time_limit=300, presets="medium_quality", catat=print,
                    model=None):
    from autogluon.timeseries import TimeSeriesDataFrame, TimeSeriesPredictor

    seri, asli = siapkan_deret(df, minimal=horizon * 5)
    if not seri:
        raise ValueError(f"belum ada kota-komoditas dengan minimal {horizon * 5} hari data harian")

    panjang = pd.concat({nama_item(w, k): s for (w, k), s in seri.items()},
                        names=["item_id", "timestamp"]).rename("target").reset_index()
    data = TimeSeriesDataFrame.from_data_frame(panjang, id_column="item_id", timestamp_column="timestamp")

    # 7 hari terakhir disembunyikan sebagai data uji
    latih, uji = data.train_test_split(horizon)

    shutil.rmtree(path, ignore_errors=True)
    catat(f"Melatih TimeSeriesPredictor untuk {len(seri)} kota-komoditas (batas {time_limit} detik)")
    prediktor = TimeSeriesPredictor(prediction_length=horizon, target="target", eval_metric="MAPE",
                                    freq="D", path=path, verbosity=2)
    with Penangkap() as tangkap:
        prediktor.fit(latih, presets=presets, time_limit=time_limit, hyperparameters=model)

    catat("Mengevaluasi model peramalan pada data uji")
    papan = prediktor.leaderboard(uji)
    leaderboard = [{
        "model": r["model"],
        "mape_uji": round(-float(r["score_test"]) * 100, 3) if pd.notna(r.get("score_test")) else None,
        "mape_val": round(-float(r["score_val"]) * 100, 3) if pd.notna(r.get("score_val")) else None,
        "waktu_latih": round(float(r.get("fit_time_marginal", 0) or 0), 2),
    } for _, r in papan.iterrows()]

    # Akurasi per kota-komoditas, hanya pada hari pasar yang benar-benar tercatat
    pred_uji = prediktor.predict(latih)
    aktual = uji.slice_by_timestep(-horizon, None)["target"]
    gab = pd.DataFrame({"aktual": aktual, "prediksi": pred_uji["mean"]}).dropna().reset_index()
    per_item, baris_uji = [], []
    for item, g in gab.groupby("item_id"):
        w, k = pisah_item(item)
        g = g[g["timestamp"].isin(asli[(w, k)])]
        if g.empty:
            continue
        galat = g["aktual"] - g["prediksi"]
        s = seri[(w, k)]
        per_item.append({
            "wilayah": w, "komoditas": k,
            "mape": float((galat.abs() / g["aktual"]).mean() * 100),
            "rmse": float(np.sqrt((galat ** 2).mean())),
            "harga_terakhir": float(s.iloc[-1]),
            "tanggal_terakhir": s.index[-1].strftime("%Y-%m-%d"),
        })
        for _, r in g.iterrows():
            baris_uji.append({"wilayah": w, "komoditas": k, "tanggal": r["timestamp"].strftime("%Y-%m-%d"),
                              "aktual": float(r["aktual"]), "prediksi": float(r["prediksi"])})

    catat("Membuat ramalan 7 hari ke depan")
    ramalan = prediktor.predict(data).reset_index()
    baris_ramalan = [{
        "wilayah": pisah_item(r["item_id"])[0], "komoditas": pisah_item(r["item_id"])[1],
        "tanggal": r["timestamp"].strftime("%Y-%m-%d"),
        "mean": float(r["mean"]), "bawah": float(r["0.1"]), "atas": float(r["0.9"]),
    } for _, r in ramalan.iterrows()]

    mape_item = pd.Series([p["mape"] for p in per_item])
    return {
        "model_terbaik": prediktor.model_best,
        "bobot": rapikan_bobot(tangkap.bobot),
        "leaderboard": leaderboard,
        "per_item": per_item,
        "uji": baris_uji,
        "ramalan": baris_ramalan,
        "ringkas": {
            "jumlah_deret": len(seri),
            "awal": str(df["tanggal"].min().date()),
            "akhir": str(df["tanggal"].max().date()),
            "horizon": horizon,
            "preset": presets,
            "batas_waktu": time_limit,
            "mape_median": round(float(mape_item.median()), 3) if len(mape_item) else None,
            "mape_rata": round(float(mape_item.mean()), 3) if len(mape_item) else None,
            "persen_di_bawah_10": round(float((mape_item < 10).mean() * 100), 1) if len(mape_item) else None,
        },
    }
