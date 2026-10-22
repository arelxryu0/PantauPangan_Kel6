"""
Penyiapan data harga untuk AutoGluon.

Catatan penting (mencegah kebocoran data):
Hari libur dan akhir pekan tidak punya harga di PIHPS. Hari-hari itu diisi dengan
harga hari kerja terakhir (forward-fill), BUKAN interpolasi. Interpolasi memakai
harga hari berikutnya, sehingga model diam-diam "melihat masa depan".
"""
import numpy as np
import pandas as pd

FITUR = [
    "harga", "ubah_1h", "ubah_7h", "ubah_14h", "ubah_30h",
    "volatilitas_14h", "volatilitas_30h", "vs_rata_30h",
    "bulan", "hari", "kota", "komoditas",
]

NAMA_FITUR = {
    "harga": "Harga hari ini",
    "ubah_1h": "Perubahan 1 hari",
    "ubah_7h": "Perubahan 7 hari",
    "ubah_14h": "Perubahan 14 hari",
    "ubah_30h": "Perubahan 30 hari",
    "volatilitas_14h": "Volatilitas 14 hari",
    "volatilitas_30h": "Volatilitas 30 hari",
    "vs_rata_30h": "Posisi vs rata-rata 30 hari",
    "bulan": "Bulan",
    "hari": "Hari dalam minggu",
    "kota": "Kota",
    "komoditas": "Jenis komoditas",
}


def muat_harga(conn):
    df = pd.read_sql_query("SELECT tanggal, wilayah, komoditas, harga FROM harga", conn)
    df["tanggal"] = pd.to_datetime(df["tanggal"])
    return df


def siapkan_deret(df, minimal=30):
    """
    Mengubah data harga menjadi deret harian per (kota, komoditas).
    Mengembalikan:
      seri : {(kota, komoditas): Series harian yang sudah di-forward-fill}
      asli : {(kota, komoditas): set tanggal yang benar-benar tercatat}
    Deret dengan kurang dari `minimal` hari tercatat dilewati.
    """
    seri, asli = {}, {}
    for (w, k), g in df.groupby(["wilayah", "komoditas"]):
        s = g.drop_duplicates("tanggal").set_index("tanggal")["harga"].sort_index()
        if len(s) < minimal:
            continue
        seri[(w, k)] = s.asfreq("D").ffill()
        asli[(w, k)] = set(s.index)
    return seri, asli


def nama_item(w, k):
    return f"{w} | {k}"


def pisah_item(item_id):
    w, k = str(item_id).split(" | ", 1)
    return w, k


def tabel_fitur(seri, asli, horizon=7, ambang_persen=5.0):
    """
    Tabel fitur untuk TabularPredictor. Satu baris = satu hari pasar di satu kota-komoditas.
    Label 'naik' = 1 jika harga tertinggi `horizon` hari ke depan naik >= ambang_persen.
    Baris yang masa depannya belum diketahui diberi label kosong (NaN).
    """
    ambang = ambang_persen / 100
    baris = []
    for (w, k), s in seri.items():
        f = pd.DataFrame({"harga": s})
        for n in (1, 7, 14, 30):
            f[f"ubah_{n}h"] = s.pct_change(n, fill_method=None) * 100
        harian = s.pct_change(fill_method=None)
        f["volatilitas_14h"] = harian.rolling(14).std() * 100
        f["volatilitas_30h"] = harian.rolling(30).std() * 100
        f["vs_rata_30h"] = (s / s.rolling(30).mean() - 1) * 100
        f["bulan"] = s.index.month
        f["hari"] = s.index.dayofweek
        f["kota"] = w
        f["komoditas"] = k
        maks = pd.concat([s.shift(-i) for i in range(1, horizon + 1)], axis=1).max(axis=1)
        f["naik"] = ((maks / s - 1) >= ambang).astype(float)
        f.loc[s.index[-horizon:], "naik"] = np.nan
        # hanya hari pasar yang benar-benar tercatat di PIHPS
        f = f[f.index.isin(asli[(w, k)])]
        baris.append(f)
    if not baris:
        return pd.DataFrame(columns=["tanggal"] + FITUR + ["naik"])
    tabel = pd.concat(baris).rename_axis("tanggal").reset_index()
    return tabel.dropna(subset=["ubah_30h"])
