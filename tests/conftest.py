"""Wspólne fixture'y dla testów autoryzacji.

Testy uderzają w DZIAŁAJĄCY backend przez HTTP (nie TestClient) — bo chcemy
sprawdzić prawdziwą ścieżkę: JWT + baza systemowa + Postgres, dokładnie tak jak
używa tego frontend. Backend musi działać (docker compose up fastapi_backend).

Uruchamianie:
    venv/bin/pytest tests/ -v
    BASE_URL=http://localhost:8000 venv/bin/pytest tests/ -v
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
TIMEOUT = int(os.getenv("TEST_TIMEOUT", "30"))


def _unique_email(tag: str) -> str:
    # Osobny e-mail na każdy przebieg, żeby testy nie kolidowały ze sobą ani z
    # kontami z poprzednich uruchomień.
    return f"test_{tag}_{uuid.uuid4().hex[:8]}@test.local"


def _register(email: str, password: str = "haslo12345") -> dict:
    """Rejestruje konto i zwraca {id, email, token}. Pole nazywa się 'password_hash'
    (backend sam hashuje bcryptem — mylna nazwa, patrz UserIn w main.py)."""
    r = requests.post(f"{BASE_URL}/register",
                      json={"email": email, "password_hash": password},
                      timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session", autouse=True)
def _require_running_backend():
    """Przerywa cały przebieg z czytelnym komunikatem, gdy backend nie odpowiada —
    zamiast zalać wynik dziesiątkami ConnectionError."""
    try:
        requests.get(f"{BASE_URL}/health", timeout=5)
    except requests.exceptions.RequestException:
        pytest.exit(f"Backend nie odpowiada pod {BASE_URL} — uruchom "
                    f"'docker compose up -d fastapi_backend'", returncode=3)


@pytest.fixture(scope="session")
def user_a() -> dict:
    """Pierwszy użytkownik testowy (właściciel zasobów)."""
    return _register(_unique_email("a"))


@pytest.fixture(scope="session")
def user_b() -> dict:
    """Drugi użytkownik — do prób dostępu do cudzych zasobów (testy izolacji)."""
    return _register(_unique_email("b"))


def auth(token: str) -> dict:
    """Nagłówek Authorization z tokenem Bearer."""
    return {"Authorization": f"Bearer {token}"}
