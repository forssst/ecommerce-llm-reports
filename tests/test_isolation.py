"""Blok 2 — izolacja użytkowników (dostęp do CUDZYCH zasobów).

To najważniejszy blok. Sprawdza, czy zalogowany użytkownik B może odczytać albo
zmodyfikować zasoby użytkownika A (bazy, historię). Poprawnie: NIE może → 403/404.

UWAGA (stan na 2026-07-03): część tych testów jest oznaczona `xfail` — obecny
backend weryfikuje TYLKO ważność tokenu (`verify_token`), ale NIE sprawdza, czy
`user_id`/ID z URL należy do właściciela tokenu. To realna luka typu IDOR
(Insecure Direct Object Reference). xfail = "wiemy, że teraz przechodzi źle";
gdy dodasz kontrolę właściciela, testy zmienią się w XPASS i wtedy usuń markery.
Materiał wprost do rozdziału 'Bezpieczeństwo'.
"""
import io
import requests
import pytest
from conftest import BASE_URL, TIMEOUT, auth

CSV = b"produkt,miasto,ilosc\nLaptop,Krakow,3\nMysz,Gdansk,7\n"


@pytest.fixture(scope="module")
def db_of_a(user_a):
    """Wgrywa małą bazę CSV na konto użytkownika A. Zwraca (db_id, file_path)."""
    files = {"file": ("iso_test_a.csv", io.BytesIO(CSV), "text/csv")}
    r = requests.post(f"{BASE_URL}/upload",
                      data={"user_id": user_a["id"]}, files=files,
                      headers=auth(user_a["token"]), timeout=TIMEOUT)
    r.raise_for_status()
    db_id = r.json()["id"]
    # /upload zwraca tylko {id, name} — file_path (nazwę schematu Postgresa)
    # dobieramy z listy baz właściciela.
    lst = requests.get(f"{BASE_URL}/users/{user_a['id']}/databases",
                       headers=auth(user_a["token"]), timeout=TIMEOUT).json()
    file_path = next((d["file_path"] for d in lst if d["id"] == db_id), None)
    return db_id, file_path


def test_a_widzi_wlasne_bazy(user_a, db_of_a):
    """Kontrola pozytywna — A widzi bazę, którą wgrał."""
    r = requests.get(f"{BASE_URL}/users/{user_a['id']}/databases",
                     headers=auth(user_a["token"]), timeout=TIMEOUT)
    assert r.status_code == 200
    assert any(d["id"] == db_of_a[0] for d in r.json())


@pytest.mark.xfail(reason="IDOR: brak kontroli właściciela w GET /users/{id}/databases",
                   strict=False)
def test_b_nie_widzi_baz_a(user_a, user_b, db_of_a):
    """B, podając w URL user_id konta A, NIE powinien dostać jego baz."""
    r = requests.get(f"{BASE_URL}/users/{user_a['id']}/databases",
                     headers=auth(user_b["token"]), timeout=TIMEOUT)
    # Poprawne zachowanie: odmowa (403) albo pusta/własna lista — na pewno NIE dane A.
    assert r.status_code == 403 or all(d["id"] != db_of_a[0] for d in r.json())


@pytest.mark.xfail(reason="IDOR: brak kontroli właściciela w GET /users/{id}/queries",
                   strict=False)
def test_b_nie_widzi_historii_a(user_a, user_b):
    """B nie powinien odczytać historii zapytań konta A przez jego user_id w URL."""
    r = requests.get(f"{BASE_URL}/users/{user_a['id']}/queries",
                     headers=auth(user_b["token"]), timeout=TIMEOUT)
    assert r.status_code == 403


@pytest.mark.xfail(reason="brak kontroli właściciela w DELETE /databases/{id}",
                   strict=False)
def test_b_nie_moze_usunac_bazy_a(user_b, db_of_a):
    """B nie powinien móc usunąć bazy należącej do A (tylko po znajomości ID)."""
    db_id = db_of_a[0]
    r = requests.delete(f"{BASE_URL}/databases/{db_id}",
                        headers=auth(user_b["token"]), timeout=TIMEOUT)
    assert r.status_code in (403, 404)


@pytest.mark.xfail(reason="POST /generate ufa user_id z body zamiast tokenowi",
                   strict=False)
def test_b_nie_moze_generowac_jako_a(user_a, user_b, db_of_a):
    """B wysyła /generate z user_id konta A w body — wpis w historii nie powinien
    powstać na koncie A (albo żądanie odrzucone)."""
    _, file_path = db_of_a
    payload = {"user_id": user_a["id"], "prompt": "cokolwiek",
               "db_path": file_path, "n8n_timeout": 30}
    requests.post(f"{BASE_URL}/generate", json=payload,
                  headers=auth(user_b["token"]), timeout=120)
    # Wpis podszyty pod A nie powinien się pojawić w jego historii (czytanej przez A).
    hist = requests.get(f"{BASE_URL}/users/{user_a['id']}/queries",
                        headers=auth(user_a["token"]), timeout=TIMEOUT).json()
    assert not any("cokolwiek" in (q.get("prompt") or "") for q in hist)
