"""Stress-test /generate pod obciazeniem N rownoczesnych uzytkownikow.

Cel: zmierzyc jak backend + Ollama (qwen2.5-coder:7b) zachowuja sie przy
N=1,2,3,5 rownoleglych zadaniach /generate na tej samej bazie testowej.
Wynik to material do rozdzialu Ewaluacja (czas odpowiedzi, bledy/timeouty),
nie test poprawnosci. Liniowa degradacja czasu wraz z N jest oczekiwana
(Ollama kolejkuje inferencje na slabym GPU) i NIE jest traktowana jako blad.

Uruchamianie:
    python3 stress_test_ollama.py                 # pelna macierz N x powtorzenia
    python3 stress_test_ollama.py --baseline-only  # tylko 1 pomiar bazowy (szybkie)

Wymaga dzialajacego stacku: docker compose up -d ollama postgres fastapi_backend
"""
import argparse
import csv
import io
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
CSV_PATH = os.path.join(os.path.dirname(__file__), "pliki_testowe", "sklep_testowy.csv")
PROMPT = "Pokaz liczbe zamowien wedlug miesiaca"
N_LEVELS = [1, 2, 3, 5]
REPEATS = 2
# Pomiar bazowy (N=1) dal ~91s na pelen multi-wykres. Przy N=5 rownoleglych zadan
# najgorszy przypadek (Ollama serializuje) to ~5x tyle na jedno zadanie w batchu —
# timeout musi to pokryc z zapasem, inaczej ostatnie zadanie w batchu zawsze padnie.
REQUEST_TIMEOUT = 600  # sekund na pojedyncze /generate


def _register_and_upload():
    """Zaklada swiezego usera testowego i wgrywa sklep_testowy.csv. Zwraca
    (token, user_id, db_path, schema_text)."""
    email = f"stresstest_{uuid.uuid4().hex[:8]}@test.local"
    r = requests.post(f"{BASE_URL}/register",
                      json={"email": email, "password_hash": "haslo12345"}, timeout=30)
    r.raise_for_status()
    user = r.json()
    headers = {"Authorization": f"Bearer {user['token']}"}

    with open(CSV_PATH, "rb") as f:
        content = f.read()
    files = {"file": ("sklep_testowy.csv", io.BytesIO(content), "text/csv")}
    r = requests.post(f"{BASE_URL}/upload", data={"user_id": user["id"]},
                      files=files, headers=headers, timeout=60)
    r.raise_for_status()

    r = requests.get(f"{BASE_URL}/users/{user['id']}/databases", headers=headers, timeout=30)
    r.raise_for_status()
    dbs = r.json()
    db = next(d for d in dbs if d["name"] == "sklep_testowy.csv")
    schema_text = "\n".join(
        f"Tabela {t}: " + ", ".join(f"{c['name']} ({c['type']})" for c in cols)
        for t, cols in db["schema"].items())
    return user["token"], user["id"], db["file_path"], schema_text


def _one_generate(token: str, user_id: int, db_path: str, schema_text: str) -> dict:
    """Wysyla jedno /generate i mierzy czas. Zwraca wpis wyniku."""
    headers = {"Authorization": f"Bearer {token}"}
    # user_id w body jest wymagany przez model Pydantic, ale backend i tak nadpisuje go
    # wartoscia z tokenu (fix IDOR z 2026-07-05) — podajemy wlasny, zeby przeszla walidacja.
    # n8n_timeout: nazwa mylaca, ale to on jest przekazywany jako timeout kazdego
    # wywolania Ollamy w _generate_multichart — zostawiamy domyslne 120s (jak frontend),
    # inaczej na wolnym GPU (GTX1060 3GB) requesty padaja na "model jeszcze ladowany".
    payload = {"user_id": user_id, "prompt": PROMPT, "db_path": db_path,
               "schema_text": schema_text, "n8n_timeout": 120}
    start = time.monotonic()
    try:
        r = requests.post(f"{BASE_URL}/generate", json=payload, headers=headers,
                          timeout=REQUEST_TIMEOUT)
        duration = time.monotonic() - start
        ok = False
        detail = ""
        if r.status_code == 200:
            try:
                body = r.json()
                detail = body.get("status", "")
                # /generate zwraca HTTP 200 nawet gdy generacja sie nie udala
                # (np. {"status":"error","error":"..."}) — sukces liczymy po polu status.
                ok = detail != "error"
                if not ok:
                    detail = body.get("error", detail)
            except Exception as e:
                detail = f"bad json: {e}"
        else:
            detail = r.text[:200]
        return {"duration_sec": round(duration, 2), "status_code": r.status_code,
                "ok": ok, "detail": detail}
    except requests.exceptions.Timeout:
        return {"duration_sec": round(time.monotonic() - start, 2), "status_code": 0,
                "ok": False, "detail": "TIMEOUT"}
    except Exception as e:
        return {"duration_sec": round(time.monotonic() - start, 2), "status_code": 0,
                "ok": False, "detail": str(e)[:200]}


def run_baseline(token, user_id, db_path, schema_text):
    print("Pomiar bazowy: 1x /generate (pelen multi-wykres dashboard)...")
    result = _one_generate(token, user_id, db_path, schema_text)
    print(f"  -> {result['duration_sec']}s, status={result['status_code']}, "
          f"ok={result['ok']}, detail={result['detail']}")
    return result


def run_matrix(token, user_id, db_path, schema_text, out_path):
    rows = []
    for n in N_LEVELS:
        for rep in range(1, REPEATS + 1):
            print(f"--- N={n}, powtorzenie {rep}/{REPEATS} ---")
            batch_start = time.monotonic()
            with ThreadPoolExecutor(max_workers=n) as pool:
                futures = [pool.submit(_one_generate, token, user_id, db_path, schema_text)
                          for _ in range(n)]
                results = [f.result() for f in as_completed(futures)]
            batch_duration = time.monotonic() - batch_start
            oks = sum(1 for r in results if r["ok"])
            print(f"    batch_time={batch_duration:.1f}s, sukcesy={oks}/{n}, "
                  f"czasy={[r['duration_sec'] for r in results]}")
            for i, r in enumerate(results):
                rows.append({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "n_level": n, "repeat": rep, "request_idx": i,
                    "batch_duration_sec": round(batch_duration, 2),
                    **r,
                })
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nZapisano {len(rows)} wynikow do {out_path}")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-only", action="store_true",
                       help="Tylko pojedynczy pomiar bazowy, bez pelnej macierzy N.")
    args = parser.parse_args()

    print(f"Backend: {BASE_URL}")
    print("Zakladam konto testowe i wgrywam sklep_testowy.csv...")
    token, user_id, db_path, schema_text = _register_and_upload()
    print(f"  -> konto ok, db_path={db_path}")

    run_baseline(token, user_id, db_path, schema_text)

    if not args.baseline_only:
        out_path = os.path.join(os.path.dirname(__file__),
                               f"stress_test_results_{datetime.now():%Y%m%d_%H%M}.csv")
        run_matrix(token, user_id, db_path, schema_text, out_path)
