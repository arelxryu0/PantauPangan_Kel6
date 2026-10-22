import csv
import io
import json
import math
import os
import subprocess
import sys
from datetime import datetime
from functools import wraps

import pandas as pd
from flask import (Flask, Response, flash, g, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

import config
from database import close_db, get_db, init_db
from ml.dataprep import NAMA_FITUR
from utils.importer import baca_dan_impor
from utils.peringatan import STATUS, kategori_peluang, status_peringatan

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.teardown_appcontext(close_db)

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
init_db()

EKSTENSI_BOLEH = {".csv", ".xlsx", ".xls"}
KELAS_LABEL = {
    "Aman": "l-stabil", "Rendah": "l-stabil",
    "Waspada": "l-fluktuatif", "Sedang": "l-fluktuatif",
    "Siaga": "l-rawan", "Tinggi": "l-rawan",
}
URUTAN_STATUS = ["Siaga", "Waspada", "Aman"]
NAMA_BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
WARNA_KOTA = {"Pekanbaru": "#2E6B4E", "Dumai": "#C98A12", "Tembilahan": "#3D6F99"}

# Proses pelatihan AutoGluon yang sedang berjalan (dijalankan sebagai proses terpisah)
PROSES_LATIH = {}


# =========================================================
# Filter dan fungsi template
# =========================================================

@app.template_filter("rupiah")
def rupiah(nilai):
    if nilai is None:
        return "-"
    return "Rp " + f"{nilai:,.0f}".replace(",", ".")


@app.template_filter("persen")
def persen(nilai, tanda=True, desimal=1):
    if nilai is None:
        return "-"
    teks = f"{nilai:+.{desimal}f}" if tanda else f"{nilai:.{desimal}f}"
    return teks.replace(".", ",") + "%"


@app.template_filter("angka")
def angka(nilai, desimal=3):
    if nilai is None:
        return "-"
    return f"{nilai:.{desimal}f}".replace(".", ",")


@app.template_filter("ribuan")
def ribuan(nilai):
    return f"{int(nilai or 0):,}".replace(",", ".")


@app.template_filter("tgl")
def tgl(nilai):
    if not nilai:
        return "-"
    t = pd.Timestamp(nilai)
    return f"{t.day} {NAMA_BULAN[t.month - 1]} {t.year}"


@app.template_filter("waktu")
def waktu(nilai):
    if not nilai:
        return "-"
    t = pd.Timestamp(nilai)
    return f"{t.day} {NAMA_BULAN[t.month - 1]} {t.year}, {t:%H.%M}"


@app.template_filter("durasi")
def durasi(detik):
    if detik is None:
        return "-"
    detik = int(detik)
    return f"{detik // 60} menit {detik % 60} detik" if detik >= 60 else f"{detik} detik"


@app.template_global()
def kelas_label(label):
    return KELAS_LABEL.get(label, "")


@app.template_global()
def kelas_ubah(nilai):
    if nilai is None:
        return "tetap"
    return "naik" if nilai > 0.05 else ("turun" if nilai < -0.05 else "tetap")


@app.template_global()
def kelas_peluang(p):
    """Kelas warna sel peta risiko berdasarkan peluang naik."""
    if p is None:
        return "sel-kosong"
    if p >= config.PELUANG_SIAGA:
        return "sel-tinggi"
    if p >= config.PELUANG_WASPADA:
        return "sel-sedang"
    if p >= config.PELUANG_WASPADA / 2:
        return "sel-rendah"
    return "sel-aman"


@app.template_global()
def warna_kota(w):
    return WARNA_KOTA.get(w, "#5F6E66")


@app.template_global()
def nama_fitur(f):
    return NAMA_FITUR.get(f, f)


@app.template_global()
def url_dengan(**ubah):
    """URL halaman ini dengan sebagian parameter query diganti."""
    args = request.args.to_dict()
    args.update(ubah)
    args = {k: v for k, v in args.items() if v not in (None, "")}
    return url_for(request.endpoint, **args)


# =========================================================
# Helper umum
# =========================================================

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            flash("Masuk sebagai admin untuk membuka halaman ini.", "info")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def sekarang():
    return datetime.now().isoformat(timespec="seconds")


def catat_proses(jenis, keterangan):
    db = get_db()
    db.execute("INSERT INTO log_proses (jenis, keterangan, dibuat) VALUES (?, ?, ?)",
               (jenis, keterangan, sekarang()))
    db.commit()


def semua_harga():
    """Seluruh data harga sebagai DataFrame, dibaca sekali per request."""
    if "harga_df" not in g:
        df = pd.read_sql_query("SELECT tanggal, wilayah, komoditas, harga FROM harga", get_db())
        df["tanggal"] = pd.to_datetime(df["tanggal"])
        g.harga_df = df.sort_values("tanggal")
    return g.harga_df


def daftar_komoditas():
    rows = get_db().execute("SELECT DISTINCT komoditas FROM harga ORDER BY komoditas").fetchall()
    return [r["komoditas"] for r in rows]


def pilih_komoditas(daftar):
    k = request.args.get("komoditas")
    if k in daftar:
        return k
    if config.KOMODITAS_UTAMA in daftar:
        return config.KOMODITAS_UTAMA
    return daftar[0] if daftar else None


def pilih_wilayah(df=None):
    w = request.args.get("wilayah")
    if w in config.WILAYAH_RIAU:
        return w
    if df is not None and not df.empty:
        ada = set(df["wilayah"])
        for x in config.WILAYAH_RIAU:
            if x in ada:
                return x
    return config.WILAYAH_RIAU[0]


def ke_list(nilai):
    return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else round(float(v))
            for v in nilai]


def persen_ubah(sekarang_, lalu):
    if lalu is None or lalu.empty:
        return None
    h0 = float(lalu.iloc[-1]["harga"])
    return (float(sekarang_) - h0) / h0 * 100


def harga_terakhir(df):
    """Harga terakhir serta perubahan 7 dan 30 hari untuk setiap pasangan komoditas-kota."""
    hasil = {}
    for (k, w), grp in df.groupby(["komoditas", "wilayah"]):
        akhir = grp.iloc[-1]
        hasil[(k, w)] = {
            "komoditas": k, "wilayah": w, "harga": float(akhir["harga"]), "tanggal": akhir["tanggal"],
            "perubahan": persen_ubah(akhir["harga"], grp[grp["tanggal"] <= akhir["tanggal"] - pd.Timedelta(days=7)]),
            "perubahan30": persen_ubah(akhir["harga"], grp[grp["tanggal"] <= akhir["tanggal"] - pd.Timedelta(days=30)]),
        }
    return hasil


def ambang_untuk(komoditas):
    if "ambang" not in g:
        g.ambang = {r["komoditas"]: r["persen"] for r in get_db().execute("SELECT * FROM ambang")}
    return g.ambang.get(komoditas, config.AMBANG_DEFAULT)


def hasil_risiko():
    """Peluang naik terbaru dari TabularPredictor: {(komoditas, wilayah): baris}"""
    if "risiko" not in g:
        g.risiko = {}
        for r in get_db().execute("SELECT * FROM hasil_risiko"):
            d = dict(r)
            d["kategori"] = kategori_peluang(d["peluang"])
            g.risiko[(d["komoditas"], d["wilayah"])] = d
    return g.risiko


def run_terakhir(jenis, hanya_sukses=True):
    q = "SELECT * FROM model_run WHERE jenis = ?" + (" AND status = 'selesai'" if hanya_sukses else "")
    r = get_db().execute(q + " ORDER BY id DESC LIMIT 1", (jenis,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["data"] = json.loads(d["ringkasan"] or "{}")
    return d


def data_peringatan(komoditas=None):
    """Gabungan ramalan TimeSeriesPredictor dan peluang naik TabularPredictor per kota-komoditas."""
    if "peringatan" not in g:
        db = get_db()
        evaluasi = {(r["komoditas"], r["wilayah"]): dict(r) for r in db.execute("SELECT * FROM evaluasi_model")}
        ramalan = {(r["komoditas"], r["wilayah"]): dict(r) for r in db.execute(
            "SELECT komoditas, wilayah, MAX(harga_prediksi) AS prediksi_maks, MAX(tanggal) AS sampai, "
            "MAX(atas) AS atas_maks FROM hasil_peramalan GROUP BY komoditas, wilayah")}
        risiko = hasil_risiko()
        hasil = []
        for key in sorted(set(evaluasi) | set(ramalan) | set(risiko)):
            k, w = key
            ev, rm, rs = evaluasi.get(key, {}), ramalan.get(key, {}), risiko.get(key, {})
            harga = ev.get("harga_terakhir") or rs.get("harga")
            kenaikan = None
            if harga and rm.get("prediksi_maks"):
                kenaikan = (rm["prediksi_maks"] - harga) / harga * 100
            peluang = rs.get("peluang")
            ambang = ambang_untuk(k)
            status, alasan = status_peringatan(kenaikan, peluang, ambang)
            hasil.append({
                "komoditas": k, "wilayah": w, "harga_terakhir": harga,
                "tanggal_terakhir": ev.get("tanggal_terakhir") or rs.get("tanggal"),
                "prediksi_maks": rm.get("prediksi_maks"), "sampai": rm.get("sampai"),
                "kenaikan": kenaikan, "peluang": peluang, "ambang": ambang, "mape": ev.get("mape"),
                "status": status, "alasan": alasan,
            })
        hasil.sort(key=lambda x: (URUTAN_STATUS.index(x["status"]), -(x["peluang"] or 0), -(x["kenaikan"] or 0)))
        g.peringatan = hasil
    if komoditas:
        return [p for p in g.peringatan if p["komoditas"] == komoditas]
    return g.peringatan


@app.context_processor
def info_global():
    try:
        n = sum(1 for p in data_peringatan() if p["status"] in ("Siaga", "Waspada"))
        st = get_db().execute("SELECT status FROM status_latih WHERE id = 1").fetchone()
        berjalan = bool(st and st["status"] == "berjalan")
    except Exception:
        n, berjalan = 0, False
    return {"jumlah_peringatan_aktif": n, "latih_berjalan": berjalan, "cfg": config}


def angka_csv(v, desimal=0):
    if v is None:
        return ""
    return f"{v:.{desimal}f}".replace(".", ",")


def kirim_csv(nama_file, header, baris):
    buf = io.StringIO()
    buf.write("﻿")  # supaya Excel membaca UTF-8 dengan benar
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    w.writerows(baris)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={nama_file}"})


# =========================================================
# Halaman publik
# =========================================================

@app.route("/")
def dashboard():
    df = semua_harga()
    if df.empty:
        return render_template("index.html", kosong=True)

    komoditas_list = sorted(df["komoditas"].unique())
    komoditas = pilih_komoditas(komoditas_list)
    # Pilihan rentang grafik: sembunyikan yang lebih panjang dari data yang ada
    rentang_data = (df["tanggal"].max() - df["tanggal"].min()).days
    rentang_list = [r for r in config.RENTANG_GRAFIK if r == 0 or r < rentang_data]
    rentang = request.args.get("rentang", type=int)
    if rentang not in rentang_list:
        rentang = 90 if 90 in rentang_list else 0

    terakhir = harga_terakhir(df)
    risiko = hasil_risiko()
    peringatan = data_peringatan()
    status = {(p["komoditas"], p["wilayah"]): p["status"] for p in peringatan}
    d = df[df["komoditas"] == komoditas]

    papan = []
    for w in config.WILAYAH_RIAU:
        r = terakhir.get((komoditas, w))
        rs = risiko.get((komoditas, w)) or {}
        papan.append({
            "wilayah": w,
            "harga": r["harga"] if r else None,
            "perubahan": r["perubahan"] if r else None,
            "tanggal": r["tanggal"] if r else None,
            "peluang": rs.get("peluang"), "kategori": rs.get("kategori"),
            "status": status.get((komoditas, w)),
            "spark": ke_list(d[d["wilayah"] == w]["harga"].tail(30)),
        })

    if rentang:
        d_grafik = d[d["tanggal"] > d["tanggal"].max() - pd.Timedelta(days=rentang)]
    else:
        d_grafik = d
    pivot = d_grafik.pivot_table(index="tanggal", columns="wilayah", values="harga")
    grafik = {
        "label": [t.strftime("%d/%m/%Y") for t in pivot.index],
        "seri": [{"nama": w, "data": ke_list(pivot[w])} for w in config.WILAYAH_RIAU if w in pivot],
    }

    matriks = [{"komoditas": k, "kota": [terakhir.get((k, w)) for w in config.WILAYAH_RIAU]}
               for k in komoditas_list]

    kota = request.args.get("kota") if request.args.get("kota") in config.WILAYAH_RIAU else config.WILAYAH_RIAU[0]
    detail_kota = []
    for k in komoditas_list:
        r = terakhir.get((k, kota))
        if r:
            rs = risiko.get((k, kota)) or {}
            detail_kota.append({**r, "peluang": rs.get("peluang"), "kategori": rs.get("kategori"),
                                "status": status.get((k, kota))})

    berubah = [r for r in terakhir.values() if r["perubahan"] is not None]
    naik = sorted([r for r in berubah if r["perubahan"] > 0], key=lambda r: -r["perubahan"])[:5]
    turun = sorted([r for r in berubah if r["perubahan"] < 0], key=lambda r: r["perubahan"])[:5]
    peluang_teratas = sorted(risiko.values(), key=lambda r: -r["peluang"])[:5]

    stat = {
        "tanggal": df["tanggal"].max(),
        "komoditas": len(komoditas_list),
        "kota": df["wilayah"].nunique(),
        "siaga": sum(1 for p in peringatan if p["status"] == "Siaga"),
        "waspada": sum(1 for p in peringatan if p["status"] == "Waspada"),
        "peluang_tinggi": sum(1 for r in risiko.values() if r["peluang"] >= config.PELUANG_WASPADA),
        "ada_model": bool(peringatan),
    }
    return render_template(
        "index.html", kosong=False, komoditas=komoditas, komoditas_list=komoditas_list,
        rentang=rentang, rentang_list=rentang_list, papan=papan, grafik=grafik,
        matriks=matriks, wilayah_list=config.WILAYAH_RIAU, naik=naik, turun=turun, stat=stat,
        kota=kota, detail_kota=detail_kota, peluang_teratas=peluang_teratas,
    )


@app.route("/analisis")
def analisis():
    df = semua_harga()
    komoditas_list = sorted(df["komoditas"].unique()) if not df.empty else []
    komoditas = pilih_komoditas(komoditas_list)
    if not komoditas:
        return render_template("analisis.html", komoditas=None)

    periode = request.args.get("periode", type=int)
    if periode not in (90, 180, 365):
        periode = 180
    d = df[df["komoditas"] == komoditas]
    d = d[d["tanggal"] > d["tanggal"].max() - pd.Timedelta(days=periode)]

    statistik = []
    for w in config.WILAYAH_RIAU:
        s = d[d["wilayah"] == w].set_index("tanggal")["harga"]
        if s.empty:
            statistik.append({"wilayah": w})
            continue
        sek, rata = float(s.iloc[-1]), float(s.mean())
        lalu = s[s.index <= s.index[-1] - pd.Timedelta(days=30)]
        statistik.append({
            "wilayah": w, "sekarang": sek, "rata": rata,
            "min": float(s.min()), "tgl_min": s.idxmin(), "max": float(s.max()), "tgl_max": s.idxmax(),
            "posisi": (sek - rata) / rata * 100,
            "ubah30": (sek - float(lalu.iloc[-1])) / float(lalu.iloc[-1]) * 100 if not lalu.empty else None,
            "cv": float(s.std() / rata * 100) if len(s) > 1 else 0.0,
        })

    ada = [x for x in statistik if "sekarang" in x]
    disparitas = None
    if len(ada) >= 2:
        mahal = max(ada, key=lambda x: x["sekarang"])
        murah = min(ada, key=lambda x: x["sekarang"])
        disparitas = {"mahal": mahal, "murah": murah, "selisih": mahal["sekarang"] - murah["sekarang"],
                      "persen": (mahal["sekarang"] - murah["sekarang"]) / murah["sekarang"] * 100}

    puncak, lembah = d.loc[d["harga"].idxmax()], d.loc[d["harga"].idxmin()]
    ringkas = {
        "rata": float(d["harga"].mean()),
        "puncak": {"harga": float(puncak["harga"]), "wilayah": puncak["wilayah"], "tanggal": puncak["tanggal"]},
        "lembah": {"harga": float(lembah["harga"]), "wilayah": lembah["wilayah"], "tanggal": lembah["tanggal"]},
    }

    b = d.assign(bulan=d["tanggal"].dt.to_period("M")).groupby(["bulan", "wilayah"])["harga"].mean().unstack()
    bulanan = {
        "label": [f"{NAMA_BULAN[p.month - 1]} {p.year}" for p in b.index],
        "seri": [{"nama": w, "data": ke_list(b[w])} for w in config.WILAYAH_RIAU if w in b],
    }

    grafik_disp = None
    p = d.pivot_table(index="tanggal", columns="wilayah", values="harga")
    if p.shape[1] >= 2:
        disp = ((p.max(axis=1) - p.min(axis=1)) / p.min(axis=1) * 100).dropna()
        grafik_disp = {"label": [t.strftime("%d/%m/%Y") for t in disp.index],
                       "data": [round(float(v), 2) for v in disp]}

    return render_template("analisis.html", komoditas=komoditas, komoditas_list=komoditas_list,
                           periode=periode, statistik=statistik, disparitas=disparitas, ringkas=ringkas,
                           bulanan=bulanan, grafik_disp=grafik_disp)


@app.route("/data")
def data_harga():
    komoditas_list = daftar_komoditas()
    f = {k: request.args.get(k, "") for k in ("komoditas", "wilayah", "dari", "sampai")}
    where, params = [], []
    if f["komoditas"] in komoditas_list:
        where.append("komoditas = ?")
        params.append(f["komoditas"])
    if f["wilayah"] in config.WILAYAH_RIAU:
        where.append("wilayah = ?")
        params.append(f["wilayah"])
    if f["dari"]:
        where.append("tanggal >= ?")
        params.append(f["dari"])
    if f["sampai"]:
        where.append("tanggal <= ?")
        params.append(f["sampai"])
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""

    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM harga" + sql_where, params).fetchone()[0]
    per = config.BARIS_PER_HALAMAN
    jumlah_halaman = max(1, math.ceil(total / per))
    halaman = min(max(request.args.get("halaman", 1, type=int), 1), jumlah_halaman)
    rows = db.execute("SELECT tanggal, wilayah, komoditas, harga FROM harga" + sql_where +
                      " ORDER BY tanggal DESC, komoditas, wilayah LIMIT ? OFFSET ?",
                      params + [per, (halaman - 1) * per]).fetchall()
    return render_template("data.html", rows=rows, f=f, total=total, halaman=halaman,
                           jumlah_halaman=jumlah_halaman, komoditas_list=komoditas_list,
                           wilayah_list=config.WILAYAH_RIAU)


@app.route("/clustering")
def clustering():
    # Halaman lama (K-Means) sudah diganti dengan Risiko Kenaikan
    return redirect(url_for("risiko"), code=301)


@app.route("/risiko")
def risiko():
    komoditas_list = daftar_komoditas()
    semua = sorted(hasil_risiko().values(), key=lambda r: -r["peluang"])
    run = run_terakhir("risiko")

    kota = request.args.get("kota") if request.args.get("kota") in config.WILAYAH_RIAU else ""
    komoditas = request.args.get("komoditas") if request.args.get("komoditas") in komoditas_list else ""
    kategori = request.args.get("kategori") if request.args.get("kategori") in ("Tinggi", "Sedang", "Rendah") else ""
    hasil = [r for r in semua if (not kota or r["wilayah"] == kota) and (not komoditas or r["komoditas"] == komoditas)
             and (not kategori or r["kategori"] == kategori)]

    peta = {(r["komoditas"], r["wilayah"]): r["peluang"] for r in semua}
    matriks = [{"komoditas": k, "peluang": [peta.get((k, w)) for w in config.WILAYAH_RIAU]}
               for k in sorted({r["komoditas"] for r in semua})]
    jumlah = {kat: sum(1 for r in semua if r["kategori"] == kat) for kat in ("Tinggi", "Sedang", "Rendah")}

    teratas = semua[:15]
    grafik_teratas = {"label": [f'{r["komoditas"]} ({r["wilayah"]})' for r in teratas],
                      "data": [round(r["peluang"], 1) for r in teratas], "satuan": "%",
                      "warna": ["#B83227" if r["peluang"] >= config.PELUANG_SIAGA else
                                "#C98A12" if r["peluang"] >= config.PELUANG_WASPADA else "#2E6B4E" for r in teratas]}
    grafik_fitur = None
    if run and run["data"].get("fitur_penting"):
        fp = [f for f in run["data"]["fitur_penting"] if f["nilai"] > 0][:10]
        grafik_fitur = {"label": [nama_fitur(f["fitur"]) for f in fp],
                        "data": [round(f["nilai"], 4) for f in fp], "satuan": ""}

    return render_template("risiko.html", semua=semua, hasil=hasil, matriks=matriks, jumlah=jumlah, run=run,
                           grafik_teratas=grafik_teratas, grafik_fitur=grafik_fitur, kota=kota,
                           komoditas=komoditas, kategori=kategori, komoditas_list=komoditas_list,
                           wilayah_list=config.WILAYAH_RIAU)


@app.route("/peramalan")
def peramalan():
    komoditas_list = daftar_komoditas()
    komoditas = pilih_komoditas(komoditas_list)
    if not komoditas:
        return render_template("peramalan.html", komoditas=None, komoditas_list=[])

    df = semua_harga()
    d = df[df["komoditas"] == komoditas]
    wilayah = pilih_wilayah(d)
    s = d[d["wilayah"] == wilayah].set_index("tanggal")["harga"].tail(60)

    db = get_db()
    pred = db.execute("SELECT tanggal, harga_prediksi, bawah, atas FROM hasil_peramalan "
                      "WHERE komoditas = ? AND wilayah = ? ORDER BY tanggal", (komoditas, wilayah)).fetchall()
    evaluasi = db.execute("SELECT * FROM evaluasi_model WHERE komoditas = ? AND wilayah = ?",
                          (komoditas, wilayah)).fetchone()
    uji = db.execute("SELECT tanggal, aktual, prediksi FROM hasil_uji WHERE komoditas = ? AND wilayah = ? "
                     "ORDER BY tanggal", (komoditas, wilayah)).fetchall()

    aktual = {t.strftime("%Y-%m-%d"): v for t, v in s.items()}
    prediksi = {r["tanggal"]: r["harga_prediksi"] for r in pred}
    atas = {r["tanggal"]: r["atas"] for r in pred}
    bawah = {r["tanggal"]: r["bawah"] for r in pred}
    if evaluasi and pred:
        t0, h0 = evaluasi["tanggal_terakhir"], evaluasi["harga_terakhir"]
        prediksi.setdefault(t0, h0)
        atas.setdefault(t0, h0)
        bawah.setdefault(t0, h0)
    semua_tgl = sorted(set(aktual) | set(prediksi))
    grafik = {
        "label": [pd.Timestamp(t).strftime("%d/%m/%Y") for t in semua_tgl],
        "aktual": ke_list([aktual.get(t) for t in semua_tgl]),
        "prediksi": ke_list([prediksi.get(t) for t in semua_tgl]),
        "atas": ke_list([atas.get(t) for t in semua_tgl]),
        "bawah": ke_list([bawah.get(t) for t in semua_tgl]),
    }
    grafik_uji = {
        "label": [pd.Timestamp(r["tanggal"]).strftime("%d/%m/%Y") for r in uji],
        "aktual": ke_list([r["aktual"] for r in uji]),
        "prediksi": ke_list([r["prediksi"] for r in uji]),
    }

    peringatan_k = data_peringatan(komoditas)
    status = next((p for p in peringatan_k if p["wilayah"] == wilayah), None)
    banding = {p["wilayah"]: p for p in peringatan_k}
    perbandingan = [{"wilayah": w, **(banding.get(w) or {})} for w in config.WILAYAH_RIAU]
    return render_template(
        "peramalan.html", komoditas=komoditas, komoditas_list=komoditas_list, wilayah=wilayah,
        wilayah_list=config.WILAYAH_RIAU, grafik=grafik, grafik_uji=grafik_uji, pred=pred,
        evaluasi=evaluasi, status=status, perbandingan=perbandingan, run=run_terakhir("peramalan"),
        akhir=pred[-1] if pred else None,
    )


@app.route("/peringatan")
def peringatan():
    komoditas_list = daftar_komoditas()
    k = request.args.get("komoditas")
    st = request.args.get("status")
    w = request.args.get("wilayah")
    semua = data_peringatan()
    data = [p for p in semua if (k not in komoditas_list or p["komoditas"] == k)
            and (st not in URUTAN_STATUS or p["status"] == st)
            and (w not in config.WILAYAH_RIAU or p["wilayah"] == w)]
    jumlah = {s: sum(1 for p in semua if p["status"] == s) for s in URUTAN_STATUS}
    per_kota = {kota: {s: sum(1 for p in semua if p["wilayah"] == kota and p["status"] == s) for s in URUTAN_STATUS}
                for kota in config.WILAYAH_RIAU}
    return render_template("peringatan.html", data=data, jumlah=jumlah, total=len(semua), per_kota=per_kota,
                           komoditas=k if k in komoditas_list else "", status=st if st in URUTAN_STATUS else "",
                           wilayah=w if w in config.WILAYAH_RIAU else "", komoditas_list=komoditas_list,
                           status_list=URUTAN_STATUS, wilayah_list=config.WILAYAH_RIAU)


@app.route("/evaluasi")
def evaluasi():
    run_p = run_terakhir("peramalan")
    run_r = run_terakhir("risiko")
    db = get_db()
    per_item = [dict(r) for r in db.execute("SELECT * FROM evaluasi_model ORDER BY mape DESC")]

    grafik_model = None
    if run_p:
        lb = [x for x in run_p["data"].get("leaderboard", []) if x.get("mape_uji") is not None]
        lb.sort(key=lambda x: x["mape_uji"])
        grafik_model = {"label": [x["model"] for x in lb], "data": [x["mape_uji"] for x in lb], "satuan": "%",
                        "warna": ["#C98A12" if x["model"] == run_p["model_terbaik"] else "#2E6B4E" for x in lb]}

    grafik_komoditas = None
    if per_item:
        rata = pd.DataFrame(per_item).groupby("komoditas")["mape"].mean().sort_values(ascending=False)
        grafik_komoditas = {"label": list(rata.index), "data": [round(float(v), 2) for v in rata], "satuan": "%",
                            "warna": ["#B83227" if v >= 10 else "#C98A12" if v >= 5 else "#2E6B4E" for v in rata]}

    grafik_fitur = grafik_skor = None
    if run_r:
        fp = [f for f in run_r["data"].get("fitur_penting", []) if f["nilai"] > 0][:10]
        if fp:
            grafik_fitur = {"label": [nama_fitur(f["fitur"]) for f in fp],
                            "data": [round(f["nilai"], 4) for f in fp], "satuan": ""}
        lb = [x for x in run_r["data"].get("leaderboard", []) if x.get("skor_uji") is not None]
        lb.sort(key=lambda x: -x["skor_uji"])
        grafik_skor = {"label": [x["model"] for x in lb], "data": [x["skor_uji"] for x in lb], "satuan": "",
                       "warna": ["#C98A12" if x["model"] == run_r["model_terbaik"] else "#2E6B4E" for x in lb]}

    riwayat = db.execute("SELECT * FROM model_run ORDER BY id DESC LIMIT 15").fetchall()
    riwayat = [{**dict(r), "teks": json.loads(r["ringkasan"] or "{}").get("teks")} for r in riwayat]
    return render_template("evaluasi.html", run_p=run_p, run_r=run_r, per_item=per_item, riwayat=riwayat,
                           grafik_model=grafik_model, grafik_komoditas=grafik_komoditas,
                           grafik_fitur=grafik_fitur, grafik_skor=grafik_skor)


@app.route("/tentang")
def tentang():
    return render_template("tentang.html", wilayah_list=config.WILAYAH_RIAU)


# =========================================================
# Ekspor CSV
# =========================================================

@app.route("/ekspor/harga")
def ekspor_harga():
    where, params = [], []
    for kunci in ("komoditas", "wilayah"):
        if request.args.get(kunci):
            where.append(f"{kunci} = ?")
            params.append(request.args[kunci])
    if request.args.get("dari"):
        where.append("tanggal >= ?")
        params.append(request.args["dari"])
    if request.args.get("sampai"):
        where.append("tanggal <= ?")
        params.append(request.args["sampai"])
    sql = "SELECT tanggal, wilayah, komoditas, harga FROM harga"
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = get_db().execute(sql + " ORDER BY tanggal, komoditas, wilayah", params).fetchall()
    return kirim_csv("data_harga.csv", ["Tanggal", "Kota", "Komoditas", "Harga (Rp)"],
                     [(r["tanggal"], r["wilayah"], r["komoditas"], angka_csv(r["harga"])) for r in rows])


@app.route("/ekspor/risiko")
def ekspor_risiko():
    rows = sorted(hasil_risiko().values(), key=lambda r: -r["peluang"])
    return kirim_csv(
        "peluang_naik_autogluon.csv",
        ["Komoditas", "Kota", "Tanggal data", "Harga (Rp)", "Peluang naik (%)", "Kategori",
         "Perubahan 7 hari (%)", "Perubahan 30 hari (%)", "Volatilitas 30 hari (%)"],
        [(r["komoditas"], r["wilayah"], r["tanggal"], angka_csv(r["harga"]), angka_csv(r["peluang"], 1),
          r["kategori"], angka_csv(r["ubah_7h"], 2), angka_csv(r["ubah_30h"], 2),
          angka_csv(r["volatilitas_30h"], 2)) for r in rows])


@app.route("/ekspor/peringatan")
def ekspor_peringatan():
    return kirim_csv(
        "peringatan_dini.csv",
        ["Status", "Komoditas", "Kota", "Harga terakhir (Rp)", "Perkiraan tertinggi (Rp)", "Kenaikan ramalan (%)",
         "Peluang naik (%)", "Ambang (%)", "Alasan", "MAPE (%)"],
        [(p["status"], p["komoditas"], p["wilayah"], angka_csv(p["harga_terakhir"]), angka_csv(p["prediksi_maks"]),
          angka_csv(p["kenaikan"], 2), angka_csv(p["peluang"], 1), angka_csv(p["ambang"], 1),
          "; ".join(p["alasan"]), angka_csv(p["mape"], 2)) for p in data_peringatan()])


@app.route("/ekspor/peramalan")
def ekspor_peramalan():
    rows = get_db().execute("SELECT komoditas, wilayah, tanggal, harga_prediksi, bawah, atas FROM hasil_peramalan "
                            "ORDER BY komoditas, wilayah, tanggal").fetchall()
    return kirim_csv("ramalan_autogluon.csv",
                     ["Komoditas", "Kota", "Tanggal", "Ramalan (Rp)", "Batas bawah 10% (Rp)", "Batas atas 90% (Rp)"],
                     [(r["komoditas"], r["wilayah"], r["tanggal"], angka_csv(r["harga_prediksi"]),
                       angka_csv(r["bawah"]), angka_csv(r["atas"])) for r in rows])


@app.route("/ekspor/evaluasi")
def ekspor_evaluasi():
    rows = get_db().execute("SELECT * FROM evaluasi_model ORDER BY komoditas, wilayah").fetchall()
    return kirim_csv("akurasi_peramalan.csv", ["Komoditas", "Kota", "MAPE (%)", "RMSE (Rp)", "Harga terakhir (Rp)"],
                     [(r["komoditas"], r["wilayah"], angka_csv(r["mape"], 2), angka_csv(r["rmse"]),
                       angka_csv(r["harga_terakhir"])) for r in rows])


# =========================================================
# Login
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = get_db().execute("SELECT * FROM users WHERE username = ?",
                                (request.form.get("username", "").strip(),)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session["user"] = user["username"]
            tujuan = request.args.get("next") or url_for("admin")
            return redirect(tujuan if tujuan.startswith("/") else url_for("admin"))
        flash("Username atau password salah.", "gagal")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Kamu sudah keluar dari akun admin.", "info")
    return redirect(url_for("dashboard"))


# =========================================================
# Pelatihan AutoGluon (proses terpisah supaya website tidak macet)
# =========================================================

def baca_status_latih():
    db = get_db()
    st = dict(db.execute("SELECT * FROM status_latih WHERE id = 1").fetchone())
    p = PROSES_LATIH.get("proses")
    if st["status"] == "berjalan" and p is not None and p.poll() is not None:
        # proses sudah berhenti tetapi tidak sempat melaporkan hasil
        db.execute("UPDATE status_latih SET status = 'gagal', selesai = ?, tahap = 'Gagal', "
                   "pesan = 'Proses pelatihan berhenti mendadak. Lihat catatan proses di bawah.' WHERE id = 1",
                   (sekarang(),))
        db.commit()
        st = dict(db.execute("SELECT * FROM status_latih WHERE id = 1").fetchone())
    if p is not None and p.poll() is not None and PROSES_LATIH.get("log"):
        PROSES_LATIH.pop("log").close()
    return st


def ekor_log(n=14):
    try:
        with open(config.LOG_LATIH, encoding="utf-8", errors="replace") as f:
            baris = [b.rstrip() for b in f.readlines() if b.strip() and "it/s]" not in b]
        return baris[-n:]
    except FileNotFoundError:
        return []


def mulai_latih(bagian, waktu_peramalan, waktu_risiko):
    st = baca_status_latih()
    p = PROSES_LATIH.get("proses")
    if st["status"] == "berjalan" and (p is None or p.poll() is None):
        return False
    db = get_db()
    db.execute("UPDATE status_latih SET status = 'berjalan', bagian = ?, mulai = ?, selesai = NULL, "
               "tahap = 'Memulai proses pelatihan', pesan = NULL WHERE id = 1", (bagian, sekarang()))
    db.commit()
    log = open(config.LOG_LATIH, "w", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    PROSES_LATIH["proses"] = subprocess.Popen(
        [sys.executable, os.path.join(config.BASE_DIR, "latih_model.py"), "--bagian", bagian,
         "--waktu-peramalan", str(waktu_peramalan), "--waktu-risiko", str(waktu_risiko)],
        cwd=config.BASE_DIR, stdout=log, stderr=subprocess.STDOUT, env=env)
    PROSES_LATIH["log"] = log
    catat_proses("Latih", f"Pelatihan AutoGluon dimulai ({bagian})")
    return True


@app.post("/admin/latih")
@login_required
def latih():
    bagian = request.form.get("bagian", "semua")
    if bagian not in ("semua", "peramalan", "risiko"):
        bagian = "semua"
    w = request.form.get("waktu", type=int)
    w = w if w in config.PILIHAN_WAKTU else None
    if not semua_harga().shape[0]:
        flash("Impor data harga dulu sebelum melatih model.", "gagal")
    elif mulai_latih(bagian, w or config.WAKTU_LATIH_PERAMALAN, w or config.WAKTU_LATIH_RISIKO):
        flash("Pelatihan AutoGluon dimulai. Halaman ini akan diperbarui otomatis saat selesai.", "info")
    else:
        flash("Pelatihan lain masih berjalan. Tunggu sampai selesai.", "gagal")
    return redirect(url_for("admin") + "#model")


@app.route("/admin/status-latih")
@login_required
def status_latih():
    st = baca_status_latih()
    berjalan_detik = None
    if st.get("mulai"):
        akhir = pd.Timestamp(st["selesai"]) if st.get("selesai") else pd.Timestamp.now()
        berjalan_detik = int((akhir - pd.Timestamp(st["mulai"])).total_seconds())
    return jsonify({**st, "detik": berjalan_detik, "log": ekor_log()})


@app.post("/admin/reset-latih")
@login_required
def reset_latih():
    p = PROSES_LATIH.get("proses")
    if p is not None and p.poll() is None:
        p.terminate()
    db = get_db()
    db.execute("UPDATE status_latih SET status = 'siap', tahap = NULL, pesan = 'Status direset admin.', "
               "selesai = ? WHERE id = 1", (sekarang(),))
    db.commit()
    flash("Status pelatihan direset.", "info")
    return redirect(url_for("admin") + "#model")


# =========================================================
# Admin
# =========================================================

@app.route("/admin")
@login_required
def admin():
    db = get_db()
    info = db.execute("SELECT COUNT(*) AS n, MIN(tanggal) AS awal, MAX(tanggal) AS akhir, "
                      "COUNT(DISTINCT wilayah) AS jml_wilayah FROM harga").fetchone()
    cakupan = {r["wilayah"]: dict(r) for r in db.execute(
        "SELECT wilayah, COUNT(DISTINCT komoditas) AS komoditas, COUNT(DISTINCT tanggal) AS hari, "
        "MIN(tanggal) AS awal, MAX(tanggal) AS akhir, COUNT(*) AS baris FROM harga GROUP BY wilayah")}
    cakupan = [{"wilayah": w, **cakupan.get(w, {})} for w in config.WILAYAH_RIAU]
    komoditas_list = daftar_komoditas()
    ambang = [{"komoditas": k, "persen": ambang_untuk(k)} for k in komoditas_list]

    evaluasi_ = {(r["komoditas"], r["wilayah"]): r for r in db.execute("SELECT * FROM evaluasi_model")}
    risiko_ = hasil_risiko()
    status_model = [{"komoditas": k, "kota": [{"mape": (evaluasi_.get((k, w)) or {"mape": None})["mape"],
                                               "peluang": (risiko_.get((k, w)) or {}).get("peluang")}
                                              for w in config.WILAYAH_RIAU]} for k in komoditas_list]
    return render_template(
        "admin.html", info=info, cakupan=cakupan, komoditas_list=komoditas_list,
        wilayah_list=config.WILAYAH_RIAU, ambang=ambang, status_model=status_model,
        log_impor=db.execute("SELECT * FROM log_import ORDER BY id DESC LIMIT 10").fetchall(),
        log_proses=db.execute("SELECT * FROM log_proses ORDER BY id DESC LIMIT 10").fetchall(),
        run_p=run_terakhir("peramalan", False), run_r=run_terakhir("risiko", False),
        st=baca_status_latih(), log=ekor_log(),
    )


@app.route("/admin/template")
@login_required
def unduh_template():
    return send_file(os.path.join(config.BASE_DIR, "data", "template_import.csv"),
                     as_attachment=True, download_name="template_import.csv")


@app.post("/admin/import")
@login_required
def impor():
    kembali = url_for("admin") + "#data"
    berkas = request.files.get("berkas")
    if not berkas or not berkas.filename:
        flash("Pilih file CSV atau Excel lebih dulu.", "gagal")
        return redirect(kembali)
    nama = secure_filename(berkas.filename)
    if os.path.splitext(nama)[1].lower() not in EKSTENSI_BOLEH:
        flash("Format file harus .csv, .xlsx, atau .xls.", "gagal")
        return redirect(kembali)

    path = os.path.join(config.UPLOAD_FOLDER, datetime.now().strftime("%Y%m%d%H%M%S_") + nama)
    berkas.save(path)
    format_file = request.form.get("format", "pihps")
    wilayah = request.form.get("wilayah")
    db = get_db()
    try:
        masuk, dilewati = baca_dan_impor(path, format_file, wilayah, db)
    except ValueError as e:
        flash(f"Impor gagal: {e}", "gagal")
        return redirect(kembali)

    label = f"{nama} ({wilayah})" if format_file == "pihps" else nama
    db.execute("INSERT INTO log_import (nama_file, format, jumlah_baris, dibuat) VALUES (?, ?, ?, ?)",
               (label, format_file, masuk, sekarang()))
    db.commit()
    pesan = f"{masuk} baris harga tersimpan."
    if dilewati:
        pesan += f" {dilewati} baris dilewati karena tanggal, kota, atau harganya tidak terbaca."
    flash(pesan, "sukses")
    if request.form.get("latih_ulang"):
        if mulai_latih("semua", config.WAKTU_LATIH_PERAMALAN, config.WAKTU_LATIH_RISIKO):
            flash("Pelatihan ulang AutoGluon dimulai di latar belakang.", "info")
            return redirect(url_for("admin") + "#model")
        flash("Pelatihan ulang tidak dimulai karena pelatihan lain masih berjalan.", "info")
    return redirect(kembali)


@app.post("/admin/ambang")
@login_required
def simpan_ambang():
    db = get_db()
    for k, p in zip(request.form.getlist("komoditas"), request.form.getlist("persen")):
        try:
            nilai = float(p.replace(",", "."))
        except ValueError:
            continue
        if nilai > 0:
            db.execute("INSERT INTO ambang (komoditas, persen) VALUES (?, ?) "
                       "ON CONFLICT(komoditas) DO UPDATE SET persen = excluded.persen", (k, nilai))
    db.commit()
    flash("Ambang peringatan tersimpan.", "sukses")
    return redirect(url_for("admin") + "#pengaturan")


@app.post("/admin/hapus")
@login_required
def hapus_komoditas():
    k = request.form.get("komoditas")
    db = get_db()
    for tabel in ("harga", "hasil_peramalan", "hasil_uji", "evaluasi_model", "hasil_risiko", "ambang"):
        db.execute(f"DELETE FROM {tabel} WHERE komoditas = ?", (k,))
    db.commit()
    catat_proses("Hapus", f"Semua data {k} dihapus")
    flash(f"Semua data {k} dihapus. Latih ulang model supaya hasil AutoGluon ikut diperbarui.", "sukses")
    return redirect(url_for("admin") + "#pengaturan")


@app.post("/admin/kosongkan")
@login_required
def kosongkan_data():
    if request.form.get("konfirmasi", "").strip().upper() != "HAPUS":
        flash("Ketik HAPUS untuk mengosongkan semua data.", "gagal")
        return redirect(url_for("admin") + "#pengaturan")
    db = get_db()
    for tabel in ("harga", "hasil_peramalan", "hasil_uji", "evaluasi_model", "hasil_risiko", "ambang",
                  "log_import", "model_run"):
        db.execute(f"DELETE FROM {tabel}")
    db.commit()
    catat_proses("Hapus", "Semua data harga dan hasil model dikosongkan")
    flash("Semua data harga dan hasil model sudah dikosongkan. Akun admin tetap ada.", "sukses")
    return redirect(url_for("admin") + "#data")


@app.errorhandler(404)
def tidak_ditemukan(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    # use_reloader=False supaya pelatihan model tidak terputus saat server memuat ulang
    app.run(debug=True, use_reloader=False)
