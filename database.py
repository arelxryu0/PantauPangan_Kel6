import os
import sqlite3

from flask import g

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS harga (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tanggal TEXT NOT NULL,
    wilayah TEXT NOT NULL,
    komoditas TEXT NOT NULL,
    harga REAL NOT NULL,
    UNIQUE (tanggal, wilayah, komoditas)
);
CREATE INDEX IF NOT EXISTS idx_harga ON harga (komoditas, wilayah, tanggal);

-- Hasil AutoGluon TimeSeriesPredictor: ramalan 7 hari + rentang kuantil 10%-90%
CREATE TABLE IF NOT EXISTS hasil_peramalan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    komoditas TEXT NOT NULL,
    wilayah TEXT NOT NULL,
    tanggal TEXT NOT NULL,
    harga_prediksi REAL NOT NULL,
    bawah REAL,
    atas REAL,
    dibuat TEXT
);

-- Akurasi peramalan per kota-komoditas pada 7 hari terakhir yang disembunyikan
CREATE TABLE IF NOT EXISTS evaluasi_model (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    komoditas TEXT NOT NULL,
    wilayah TEXT NOT NULL,
    mape REAL,
    rmse REAL,
    harga_terakhir REAL,
    tanggal_terakhir TEXT,
    dibuat TEXT,
    UNIQUE (komoditas, wilayah)
);

-- Harga asli vs ramalan pada periode uji
CREATE TABLE IF NOT EXISTS hasil_uji (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    komoditas TEXT NOT NULL,
    wilayah TEXT NOT NULL,
    tanggal TEXT NOT NULL,
    aktual REAL,
    prediksi REAL
);

-- Hasil AutoGluon TabularPredictor: peluang harga naik tajam dalam 7 hari
CREATE TABLE IF NOT EXISTS hasil_risiko (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    komoditas TEXT NOT NULL,
    wilayah TEXT NOT NULL,
    tanggal TEXT,
    harga REAL,
    peluang REAL,
    ubah_7h REAL,
    ubah_30h REAL,
    volatilitas_30h REAL,
    vs_rata_30h REAL,
    dibuat TEXT,
    UNIQUE (komoditas, wilayah)
);

-- Riwayat setiap pelatihan model beserta ringkasan hasilnya (JSON)
CREATE TABLE IF NOT EXISTS model_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jenis TEXT NOT NULL,
    status TEXT NOT NULL,
    mulai TEXT,
    selesai TEXT,
    durasi REAL,
    model_terbaik TEXT,
    ringkasan TEXT
);

-- Status proses pelatihan yang sedang berjalan (hanya satu baris, id = 1)
CREATE TABLE IF NOT EXISTS status_latih (
    id INTEGER PRIMARY KEY,
    status TEXT,
    tahap TEXT,
    bagian TEXT,
    mulai TEXT,
    selesai TEXT,
    pesan TEXT
);

CREATE TABLE IF NOT EXISTS ambang (
    komoditas TEXT PRIMARY KEY,
    persen REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS log_proses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jenis TEXT,
    keterangan TEXT,
    dibuat TEXT
);

CREATE TABLE IF NOT EXISTS log_import (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nama_file TEXT,
    format TEXT,
    jumlah_baris INTEGER,
    dibuat TEXT
);
"""


def connect():
    os.makedirs(os.path.dirname(config.DATABASE), exist_ok=True)
    conn = sqlite3.connect(config.DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def tambah_kolom(conn, tabel, kolom, tipe):
    ada = [r["name"] for r in conn.execute(f"PRAGMA table_info({tabel})")]
    if kolom not in ada:
        conn.execute(f"ALTER TABLE {tabel} ADD COLUMN {kolom} {tipe}")


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    # Database dari versi sebelumnya (LSTM) belum punya kolom rentang ramalan
    tambah_kolom(conn, "hasil_peramalan", "bawah", "REAL")
    tambah_kolom(conn, "hasil_peramalan", "atas", "REAL")
    conn.execute("INSERT OR IGNORE INTO status_latih (id, status) VALUES (1, 'siap')")
    conn.commit()
    conn.close()
