"""
Melatih model AutoGluon dan menyimpan hasilnya ke database website.

Biasanya dijalankan otomatis dari panel admin (tombol "Latih model AutoGluon").
Bisa juga dijalankan manual dari terminal:

  python latih_model.py                          -> peramalan + deteksi lonjakan
  python latih_model.py --bagian peramalan       -> hanya TimeSeriesPredictor
  python latih_model.py --bagian risiko          -> hanya TabularPredictor
  python latih_model.py --waktu-peramalan 600 --waktu-risiko 300
"""
import argparse
import json
import os
import sys
import time
import traceback
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

import config
from database import connect, init_db
from ml.dataprep import muat_harga

PESAN_PASANG = ("AutoGluon belum terpasang. Jalankan: pip install \"autogluon.tabular[all]\" "
                "autogluon.timeseries --extra-index-url https://download.pytorch.org/whl/cpu")


def sekarang():
    return datetime.now().isoformat(timespec="seconds")


def set_status(**kolom):
    conn = connect()
    sets = ", ".join(f"{k} = ?" for k in kolom)
    conn.execute(f"UPDATE status_latih SET {sets} WHERE id = 1", list(kolom.values()))
    conn.commit()
    conn.close()


def catat(teks):
    print(f"[{datetime.now():%H:%M:%S}] {teks}", flush=True)
    set_status(tahap=teks)


def simpan_run(jenis, status, mulai, durasi, model_terbaik=None, ringkasan=None):
    conn = connect()
    conn.execute("INSERT INTO model_run (jenis, status, mulai, selesai, durasi, model_terbaik, ringkasan) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (jenis, status, mulai, sekarang(), round(durasi, 1), model_terbaik,
                  json.dumps(ringkasan or {}, ensure_ascii=False)))
    conn.execute("INSERT INTO log_proses (jenis, keterangan, dibuat) VALUES (?, ?, ?)",
                 ("AutoGluon " + ("TimeSeries" if jenis == "peramalan" else "Tabular"),
                  (ringkasan or {}).get("teks", status), sekarang()))
    conn.commit()
    conn.close()


def simpan_peramalan(h):
    waktu = sekarang()
    conn = connect()
    for tabel in ("hasil_peramalan", "evaluasi_model", "hasil_uji"):
        conn.execute(f"DELETE FROM {tabel}")
    conn.executemany(
        "INSERT INTO hasil_peramalan (komoditas, wilayah, tanggal, harga_prediksi, bawah, atas, dibuat) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(r["komoditas"], r["wilayah"], r["tanggal"], r["mean"], r["bawah"], r["atas"], waktu)
         for r in h["ramalan"]])
    conn.executemany(
        "INSERT INTO evaluasi_model (komoditas, wilayah, mape, rmse, harga_terakhir, tanggal_terakhir, dibuat) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(r["komoditas"], r["wilayah"], r["mape"], r["rmse"], r["harga_terakhir"], r["tanggal_terakhir"], waktu)
         for r in h["per_item"]])
    conn.executemany(
        "INSERT INTO hasil_uji (komoditas, wilayah, tanggal, aktual, prediksi) VALUES (?, ?, ?, ?, ?)",
        [(r["komoditas"], r["wilayah"], r["tanggal"], r["aktual"], r["prediksi"]) for r in h["uji"]])
    conn.commit()
    conn.close()


def simpan_risiko(h):
    waktu = sekarang()
    conn = connect()
    conn.execute("DELETE FROM hasil_risiko")
    conn.executemany(
        "INSERT INTO hasil_risiko (komoditas, wilayah, tanggal, harga, peluang, ubah_7h, ubah_30h, "
        "volatilitas_30h, vs_rata_30h, dibuat) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(r["komoditas"], r["wilayah"], r["tanggal"], r["harga"], r["peluang"], r["ubah_7h"], r["ubah_30h"],
          r["volatilitas_30h"], r["vs_rata_30h"], waktu) for r in h["terkini"]])
    conn.commit()
    conn.close()


def jalankan_peramalan(df, batas_waktu):
    from ml.peramalan import latih_peramalan
    mulai, t0 = sekarang(), time.time()
    try:
        h = latih_peramalan(df, os.path.join(config.FOLDER_MODEL, "peramalan"), horizon=config.HORIZON,
                            time_limit=batas_waktu, presets=config.PRESET_AUTOGLUON, catat=catat,
                            model=config.MODEL_PERAMALAN)
        simpan_peramalan(h)
        r = h["ringkas"]
        teks = (f"{r['jumlah_deret']} kota-komoditas, model terbaik {h['model_terbaik']}, "
                f"MAPE median {r['mape_median']:.2f}%")
        ringkasan = {k: h[k] for k in ("bobot", "leaderboard", "ringkas")} | {"teks": teks}
        simpan_run("peramalan", "selesai", mulai, time.time() - t0, h["model_terbaik"], ringkasan)
        catat(f"Peramalan selesai: {teks}")
        return None
    except ImportError:
        simpan_run("peramalan", "gagal", mulai, time.time() - t0, ringkasan={"teks": PESAN_PASANG})
        return f"Peramalan: {PESAN_PASANG}"
    except Exception as e:
        traceback.print_exc()
        simpan_run("peramalan", "gagal", mulai, time.time() - t0, ringkasan={"teks": str(e)})
        return f"Peramalan gagal: {e}"


def jalankan_risiko(df, batas_waktu):
    from ml.risiko import latih_risiko
    mulai, t0 = sekarang(), time.time()
    try:
        h = latih_risiko(df, os.path.join(config.FOLDER_MODEL, "risiko"), horizon=config.HORIZON,
                         ambang_persen=config.AMBANG_LONJAKAN, time_limit=batas_waktu,
                         presets=config.PRESET_AUTOGLUON, catat=catat,
                         model=config.MODEL_RISIKO)
        simpan_risiko(h)
        m = h["metrik"]
        teks = (f"model terbaik {h['model_terbaik']}, balanced accuracy {m.get('balanced_accuracy', 0):.3f}, "
                f"recall {m.get('recall', 0):.3f}")
        ringkasan = {k: h[k] for k in ("bobot", "leaderboard", "metrik", "confusion", "fitur_penting",
                                       "pembagian", "ringkas")} | {"teks": teks}
        simpan_run("risiko", "selesai", mulai, time.time() - t0, h["model_terbaik"], ringkasan)
        catat(f"Deteksi lonjakan selesai: {teks}")
        return None
    except ImportError:
        simpan_run("risiko", "gagal", mulai, time.time() - t0, ringkasan={"teks": PESAN_PASANG})
        return f"Deteksi lonjakan: {PESAN_PASANG}"
    except Exception as e:
        traceback.print_exc()
        simpan_run("risiko", "gagal", mulai, time.time() - t0, ringkasan={"teks": str(e)})
        return f"Deteksi lonjakan gagal: {e}"


def main():
    p = argparse.ArgumentParser(description="Latih model AutoGluon Pantau Pangan Riau")
    p.add_argument("--bagian", choices=["semua", "peramalan", "risiko"], default="semua")
    p.add_argument("--waktu-peramalan", type=int, default=config.WAKTU_LATIH_PERAMALAN)
    p.add_argument("--waktu-risiko", type=int, default=config.WAKTU_LATIH_RISIKO)
    args = p.parse_args()

    init_db()
    set_status(status="berjalan", bagian=args.bagian, mulai=sekarang(), selesai=None, pesan=None,
               tahap="Menyiapkan data")
    gagal = []
    try:
        conn = connect()
        df = muat_harga(conn)
        conn.close()
        if df.empty:
            raise ValueError("belum ada data harga, impor data PIHPS dulu")
        catat(f"Data siap: {len(df)} baris harga, {df['tanggal'].min().date()} s/d {df['tanggal'].max().date()}")

        bagian = ["peramalan", "risiko"] if args.bagian == "semua" else [args.bagian]
        if "peramalan" in bagian:
            gagal.append(jalankan_peramalan(df, args.waktu_peramalan))
        if "risiko" in bagian:
            gagal.append(jalankan_risiko(df, args.waktu_risiko))
        gagal = [g for g in gagal if g]

        if not gagal:
            set_status(status="selesai", selesai=sekarang(), tahap="Selesai", pesan="Semua model berhasil dilatih.")
        elif len(gagal) < len(bagian):
            set_status(status="sebagian", selesai=sekarang(), tahap="Selesai sebagian", pesan=" | ".join(gagal))
        else:
            set_status(status="gagal", selesai=sekarang(), tahap="Gagal", pesan=" | ".join(gagal))
    except Exception as e:
        traceback.print_exc()
        set_status(status="gagal", selesai=sekarang(), tahap="Gagal", pesan=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
