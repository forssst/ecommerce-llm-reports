"""Blok 3 — walidacja uploadu i higiena danych wejściowych.

Sprawdza reakcję /upload na złe pliki i nietypowe nazwy. Cel: żaden przypadek nie
kończy się surowym 500 / crashem — użytkownik dostaje czytelny błąd (4xx).
"""
import io
import requests
import pytest
from conftest import BASE_URL, TIMEOUT, auth


def _upload(user, filename, content, mime="application/octet-stream"):
    files = {"file": (filename, io.BytesIO(content), mime)}
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


@pytest.mark.xfail(reason="uszkodzony plik .db może rzucić 500 zamiast 400",
                   strict=False)
def test_uszkodzony_sqlite_nie_daje_500(user_a):
    """Plik z rozszerzeniem .db, ale niebędący bazą SQLite — powinien dać 4xx."""
    r = _upload(user_a, "zepsuta.db", b"nie sqlite, tylko smieci")
    assert r.status_code < 500, f"crash 500 na uszkodzonym .db (status {r.status_code})"


@pytest.mark.xfail(reason="brak limitu rozmiaru uploadu — potencjalny DoS",
                   strict=False)
def test_za_duzy_plik_odrzucony(user_a):
    """Bardzo duży plik powinien zostać odrzucony (limit rozmiaru). Obecnie brak
    limitu — cały plik trafia na dysk i do Postgresa. ~20 MB CSV."""
    big = b"a,b,c\n" + (b"1,2,3\n" * 1_500_000)
    r = _upload(user_a, "ogromny.csv", big)
    assert r.status_code in (400, 413), f"duzy plik przyjety (status {r.status_code})"


@pytest.mark.xfail(reason="nazwa pliku trafia do ścieżki /tmp/_upload_<filename> "
                          "bez sanityzacji — ryzyko path traversal",
                   strict=False)
def test_nazwa_z_traversal_nie_wychodzi_poza_tmp(user_a):
    """Nazwa ze ../ nie powinna pozwolić zapisać poza katalogiem tymczasowym.
    (main.py buduje tmp_path = f'/tmp/_upload_{file.filename}' — patrz upload)."""
    r = _upload(user_a, "../../etc/evil.csv", b"produkt\nX\n")
    assert r.status_code in (400, 422)
