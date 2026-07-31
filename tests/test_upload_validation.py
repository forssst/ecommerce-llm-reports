"""Blok 3 — walidacja uploadu i higiena danych wejściowych.

Sprawdza reakcję /upload na złe pliki i nietypowe nazwy. Cel: żaden przypadek nie
kończy się surowym 500 / crashem — użytkownik dostaje czytelny błąd (4xx).
"""
import io
import requests
import pytest
from conftest import BASE_URL, TIMEOUT, auth


def _upload(user, filename, content, mime="application/octet-stream"):
    files = {"files": (filename, io.BytesIO(content), mime)}
    return requests.post(f"{BASE_URL}/upload",
                         data={"user_id": user["id"]}, files=files,
                         headers=auth(user["token"]), timeout=TIMEOUT)


def test_zly_format_txt_daje_400(user_a):
    """Plik .txt (nieobsługiwany format) → 400 z komunikatem, nie 500."""
    r = _upload(user_a, "notatka.txt", b"to nie jest baza danych")
    assert r.status_code == 400, f"oczekiwano 400, jest {r.status_code}"


def test_zly_format_pdf_daje_400(user_a):
    r = _upload(user_a, "dokument.pdf", b"%PDF-1.4 fake")
    assert r.status_code == 400


def test_uszkodzony_sqlite_nie_daje_500(user_a):
    """Plik z rozszerzeniem .db, ale niebędący bazą SQLite — powinien dać 4xx."""
    r = _upload(user_a, "zepsuta.db", b"nie sqlite, tylko smieci")
    assert r.status_code < 500, f"crash 500 na uszkodzonym .db (status {r.status_code})"


def test_za_duzy_plik_odrzucony(user_a):
    """Plik powyżej limitu (500 MB) powinien zostać odrzucony. ~540 MB CSV."""
    big = b"a,b,c\n" + (b"1,2,3\n" * 90_000_000)
    r = _upload(user_a, "ogromny.csv", big)
    assert r.status_code in (400, 413), f"duzy plik przyjety (status {r.status_code})"


def test_upload_wielu_plikow_scala_w_jedna_baze(user_a):
    """Kilka plików w jednym /upload -> jeden wpis w databases, wszystkie tabele widoczne
    (z prefiksem nazwy pliku źródłowego, żeby uniknąć kolizji nazw tabel)."""
    f1 = ("czesc_a.csv", io.BytesIO(b"produkt,cena\nA,10\n"), "text/csv")
    f2 = ("czesc_b.csv", io.BytesIO(b"klient,miasto\nX,Krakow\n"), "text/csv")
    r = requests.post(f"{BASE_URL}/upload",
                      data={"user_id": user_a["id"], "db_name": "polaczona_baza"},
                      files=[("files", f1), ("files", f2)],
                      headers=auth(user_a["token"]), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    db_id = r.json()["id"]
    lst = requests.get(f"{BASE_URL}/users/{user_a['id']}/databases",
                       headers=auth(user_a["token"]), timeout=TIMEOUT).json()
    rec = next(d for d in lst if d["id"] == db_id)
    assert set(rec["schema"].keys()) == {"czesc_a__czesc_a", "czesc_b__czesc_b"}


def test_upload_wielu_plikow_bez_nazwy_daje_400(user_a):
    """Bez db_name przy >1 pliku -> czytelny 400, system nie zgaduje nazwy sam."""
    f1 = ("a.csv", io.BytesIO(b"x\n1\n"), "text/csv")
    f2 = ("b.csv", io.BytesIO(b"y\n2\n"), "text/csv")
    r = requests.post(f"{BASE_URL}/upload", data={"user_id": user_a["id"]},
                      files=[("files", f1), ("files", f2)],
                      headers=auth(user_a["token"]), timeout=TIMEOUT)
    assert r.status_code == 400


def test_nazwa_z_traversal_nie_wychodzi_poza_tmp(user_a):
    """Nazwa ze ../ nie może trafić surowo do ścieżki na dysku serwera. Backend
    zapisuje plik pod losową nazwą (uuid) i osobno sanityzuje wyświetlaną nazwę
    (os.path.basename) — traversal jest więc nieszkodliwy, żądanie nie musi być
    odrzucone, ale nazwa w odpowiedzi nie może zawierać '..' ani '/'."""
    r = _upload(user_a, "../../etc/evil.csv", b"produkt\nX\n")
    assert r.status_code < 500, f"crash 500 na nazwie z traversal (status {r.status_code})"
    if r.status_code == 200:
        assert "/" not in r.json()["name"] and ".." not in r.json()["name"]
