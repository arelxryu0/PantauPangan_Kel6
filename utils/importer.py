import re
from datetime import datetime

import pandas as pd

import config

ALIAS_KOLOM = {
    "tanggal": ["tanggal", "date", "tgl"],
    "wilayah": ["wilayah", "kabupaten_kota", "kab_kota", "kabupaten/kota", "kota"],
    "komoditas": ["komoditas", "commodity"],
    "harga": ["harga", "price", "harga_rp"],
}


def normalisasi_wilayah(nama):
    """'Kota Pekanbaru', 'KOTA DUMAI', 'tembilahan' -> nama baku di config."""
    if pd.isna(nama):
        return None
    s = str(nama).strip().lower()
    s = re.sub(r"^(kabupaten|kab\.?|kota)\s+", "", s)
    if s in config.ALIAS_WILAYAH:
        return config.ALIAS_WILAYAH[s]
    for w in config.WILAYAH_RIAU:
        if s == w.lower():
            return w
    return None


def bersihkan_harga(nilai):
    """Ubah '13.500', '13,500', 'Rp 13.500', 13500.0 menjadi float. '-' atau kosong -> None."""
    if pd.isna(nilai):
        return None
    if isinstance(nilai, (int, float)):
        return float(nilai) if nilai > 0 else None
    s = str(nilai).strip()
    if re.fullmatch(r"\d+(\.\d{1,2})?", s):
        angka = float(s)
    else:
        digit = re.sub(r"[^\d]", "", s)
        if not digit:
            return None
        angka = float(digit)
    return angka if angka > 0 else None


def parse_tanggal_kolom(header):
    if isinstance(header, (pd.Timestamp, datetime)):
        return pd.Timestamp(header).normalize()
    s = re.sub(r"\s+", "", str(header))
    if not re.search(r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}", s):
        return None
    t = pd.to_datetime(s, dayfirst=True, errors="coerce")
    return None if pd.isna(t) else t.normalize()


def baca_file(path, header="infer"):
    if path.lower().endswith(".csv"):
        if header is None:
            return pd.read_csv(path, sep=None, engine="python", header=None)
        return pd.read_csv(path, sep=None, engine="python")
    if header is None:
        return pd.read_excel(path, header=None)
    return pd.read_excel(path)


def impor_format_panjang(path):
    """Format: tanggal, wilayah, komoditas, harga (satu baris = satu harga)."""
    df = baca_file(path)
    kolom = {str(c).strip().lower(): c for c in df.columns}
    pilih = {}
    for baku, alias in ALIAS_KOLOM.items():
        for a in alias:
            if a in kolom:
                pilih[baku] = kolom[a]
                break
        if baku not in pilih:
            raise ValueError(
                f"Kolom '{baku}' tidak ditemukan. Header wajib: tanggal, wilayah, komoditas, harga."
            )
    return pd.DataFrame({
        "tanggal": pd.to_datetime(df[pilih["tanggal"]], dayfirst=True, errors="coerce"),
        "wilayah": df[pilih["wilayah"]].map(normalisasi_wilayah),
        "komoditas": df[pilih["komoditas"]].astype(str).str.strip(),
        "harga": df[pilih["harga"]].map(bersihkan_harga),
    })


def impor_format_pihps(path, wilayah):
    """
    Format unduhan tabel PIHPS untuk satu kota:
    baris = komoditas, kolom = tanggal (mis. '01/ 09/ 2026').
    Baris judul di atas tabel dilewati otomatis.
    """
    wilayah = normalisasi_wilayah(wilayah)
    if not wilayah:
        raise ValueError("Pilih kota untuk file PIHPS ini.")

    mentah = baca_file(path, header=None)
    baris_header = None
    for i in range(min(25, len(mentah))):
        if mentah.iloc[i].astype(str).str.lower().str.contains("komoditas").any():
            baris_header = i
            break
    if baris_header is None:
        raise ValueError("Kolom 'Komoditas' tidak ditemukan. Pastikan file berasal dari tabel PIHPS.")

    header = mentah.iloc[baris_header].tolist()
    data = mentah.iloc[baris_header + 1:].reset_index(drop=True)
    kol_kom = next(i for i, h in enumerate(header) if "komoditas" in str(h).lower())
    kol_no = kol_kom - 1 if kol_kom > 0 else None

    kolom_tanggal = [(j, parse_tanggal_kolom(h)) for j, h in enumerate(header)]
    kolom_tanggal = [(j, t) for j, t in kolom_tanggal if t is not None]
    if not kolom_tanggal:
        raise ValueError("Tidak ada kolom tanggal yang terbaca di file PIHPS.")

    baris = []
    for _, r in data.iterrows():
        nama = str(r[kol_kom]).strip()
        if not nama or nama.lower() == "nan" or re.fullmatch(r"[\dIVX.]+", nama):
            continue
        # Baris bernomor romawi (I, II, ...) adalah rata-rata kelompok, bukan komoditas rinci
        if kol_no is not None and re.fullmatch(r"[IVX]+\.?", str(r[kol_no]).strip()):
            continue
        for j, t in kolom_tanggal:
            h = bersihkan_harga(r[j])
            if h:
                baris.append({"tanggal": t, "wilayah": wilayah, "komoditas": nama, "harga": h})
    return pd.DataFrame(baris, columns=["tanggal", "wilayah", "komoditas", "harga"])


def simpan(df, conn):
    total = len(df)
    df = df.dropna(subset=["tanggal", "wilayah", "komoditas", "harga"])
    df = df[(df["komoditas"].str.len() > 0) & (df["komoditas"].str.lower() != "nan")]
    df = df.drop_duplicates(subset=["tanggal", "wilayah", "komoditas"], keep="last")
    rows = [
        (t.strftime("%Y-%m-%d"), w, k, float(h))
        for t, w, k, h in df[["tanggal", "wilayah", "komoditas", "harga"]].itertuples(index=False)
    ]
    conn.executemany(
        "INSERT INTO harga (tanggal, wilayah, komoditas, harga) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(tanggal, wilayah, komoditas) DO UPDATE SET harga = excluded.harga",
        rows,
    )
    conn.commit()
    return len(rows), total - len(rows)


def baca_dan_impor(path, format_file, wilayah, conn):
    if format_file == "pihps":
        df = impor_format_pihps(path, wilayah)
    else:
        df = impor_format_panjang(path)
    if df.empty:
        raise ValueError("Tidak ada baris harga yang terbaca dari file.")
    return simpan(df, conn)
