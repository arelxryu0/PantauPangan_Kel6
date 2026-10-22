"""Jalankan sekali untuk membuat database dan akun admin:  python init_db.py"""
from getpass import getpass

from werkzeug.security import generate_password_hash

from database import connect, init_db

init_db()
print("Database siap di folder instance/")

username = input("Username admin [admin]: ").strip() or "admin"
password = getpass("Password admin: ")
while len(password) < 6:
    print("Password minimal 6 karakter.")
    password = getpass("Password admin: ")

conn = connect()
conn.execute(
    "INSERT INTO users (username, password_hash) VALUES (?, ?) "
    "ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash",
    (username, generate_password_hash(password)),
)
conn.commit()
conn.close()
print(f"Akun admin '{username}' tersimpan.")
