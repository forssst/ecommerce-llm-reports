"""Blok 1 — uwierzytelnianie tokenem JWT.

Sprawdza, czy chronione endpointy faktycznie wymagają poprawnego tokenu.
To najprostsza warstwa: bez tokenu / ze złym tokenem = 401.
"""
import requests
import pytest
from conftest import BASE_URL, TIMEOUT, auth

# Endpointy chronione przez Depends(verify_token). (metoda, ścieżka, przykładowe body).
# user_id/ID w ścieżce jest nieistotny — sprawdzamy warstwę tokenu PRZED logiką.
PROTECTED = [
    ("post", "/enhance-prompt", {"prompt": "x", "schema_text": ""}),
    ("post", "/describe-schema", {"schema_text": "t(a int)"}),
    ("post", "/clarify-prompt", {"prompt": "x", "schema_text": ""}),
    ("get", "/prompts", None),
    ("get", "/users/1/databases", None),
    ("get", "/users/1/queries", None),
    ("delete", "/databases/1", None),
    ("post", "/generate", {"user_id": 1, "prompt": "x", "db_path": "nope"}),
]


def _call(method: str, path: str, body, headers=None):
    fn = getattr(requests, method)
    kwargs = {"timeout": TIMEOUT, "headers": headers or {}}
    if body is not None:
        kwargs["json"] = body
    return fn(f"{BASE_URL}{path}", **kwargs)


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_brak_tokenu_daje_401(method, path, body):
    """Żądanie bez nagłówka Authorization musi dostać 401 (nie 200, nie 500)."""
    r = _call(method, path, body)
    assert r.status_code == 401, f"{method.upper()} {path} bez tokenu → {r.status_code}"


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_zepsuty_token_daje_401(method, path, body):
    """Losowy / uszkodzony token = 401."""
    r = _call(method, path, body, headers={"Authorization": "Bearer nie.jest.jwt"})
    assert r.status_code == 401, f"{method.upper()} {path} zły token → {r.status_code}"


def test_naglowek_bez_bearer_daje_401(user_a):
    """Token bez prefiksu 'Bearer ' nie może być zaakceptowany."""
    r = requests.get(f"{BASE_URL}/prompts",
                     headers={"Authorization": user_a["token"]}, timeout=TIMEOUT)
    assert r.status_code == 401


def test_poprawny_token_przechodzi(user_a):
    """Kontrola pozytywna — z ważnym tokenem endpoint /prompts odpowiada 200."""
    r = requests.get(f"{BASE_URL}/prompts", headers=auth(user_a["token"]), timeout=TIMEOUT)
    assert r.status_code == 200


def test_token_z_podpisem_obcym_sekretem_daje_401():
    """Token podpisany innym sekretem (podrobiony) = 401 — broni przed forge."""
    jose_jwt = pytest.importorskip("jose.jwt")
    jwt = jose_jwt
    fake = jwt.encode({"sub": "1", "email": "x@x.pl"}, "zly_sekret", algorithm="HS256")
    r = requests.get(f"{BASE_URL}/prompts", headers=auth(fake), timeout=TIMEOUT)
    assert r.status_code == 401
