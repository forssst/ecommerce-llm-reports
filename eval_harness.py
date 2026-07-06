"""Harness ewaluacyjny — automatyczna lawka testowa calego pipeline'u generowania.

Cel: zmierzyc SKUTECZNOSC systemu (nie wydajnosc pod obciazeniem — od tego jest
stress_test_ollama.py) na stalym zestawie promptow o roznej trudnosci, na 5 bazach
testowych. Kazdy prompt przechodzi pelna sciezke produkcyjna: /generate -> webhook
n8n -> plan wykresow -> SQL per wykres z retry -> walidacja -> dashboard Metabase.

Metryki per prompt: sukces/blad, czas, ile wykresow zaplanowano vs przeszlo
walidacje, ile bylo retry SQL. Zbiorczo: % sukcesow, srednie/mediany, rozklad
per baza i per poziom trudnosci. Wynik to material do rozdzialu Ewaluacja.

Powtarzalnosc: staly zestaw promptow + opis bazy zawsze pusty (kontrolowana
zmienna — opis AI potrafi "rozpraszac" plan, patrz notatki z testow manualnych).

Uruchamianie (przez venv projektu — systemowy python nie ma 'requests'):
    venv/bin/python eval_harness.py              # pelny zestaw (18 promptow, ~20-40 min)
    venv/bin/python eval_harness.py --smoke      # tylko po 1 prompcie z kazdej bazy
    venv/bin/python eval_harness.py --db sakila  # tylko prompty jednej bazy

Wymaga dzialajacego stacku: docker compose up -d (backend+n8n+ollama+postgres+metabase)
oraz plikow baz w pliki_testowe/ (northwind.db, sakila.db, superstore.xls,
firma_uslugi.xlsx, sklep_testowy.csv).
"""
import argparse
import csv
import io
import os
import statistics
import time
import uuid
from datetime import datetime

import requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
FILES_DIR = os.path.join(os.path.dirname(__file__), "pliki_testowe")
REQUEST_TIMEOUT = 600  # pojedynczy /generate; inferencja na CPU bywa wolna

# Zestaw ewaluacyjny: (klucz bazy, plik, prompt, trudnosc).
# Trudnosc: latwy = 1 tabela/prosta agregacja; sredni = grupowanie po czasie,
# top-N, polskie nazwy kolumn; trudny = JOIN-y wielotabelowe (northwind/sakila).
DATASETS = {
    "sklep":      "sklep_testowy.csv",
    "firma":      "firma_uslugi.xlsx",
    "superstore": "superstore.xls",
    "northwind":  "northwind.db",
    "sakila":     "sakila.db",
}

PROMPTS = [
    # sklep_testowy — 1 tabela, regresja podstaw
    ("sklep", "suma sprzedazy wedlug kategorii", "latwy"),
    ("sklep", "top 5 produktow wedlug sumy sprzedazy", "latwy"),
    ("sklep", "trend miesiecznej sprzedazy w 2024 roku", "latwy"),
    ("sklep", "TOP 10 produktow wedlug sumy sprzedazy z podzialem miesiecznym w 2024 roku", "sredni"),
    # firma_uslugi — 3 tabele, polskie kolumny dat
    ("firma", "liczba umow podpisanych w kazdym miesiacu", "sredni"),
    ("firma", "srednie wynagrodzenie pracownikow wedlug stanowiska", "sredni"),
    ("firma", "top 10 klientow wedlug lacznej wartosci umow", "sredni"),
    # superstore — wieksze dane, 3 arkusze
    ("superstore", "sprzedaz i zysk wedlug kategorii produktow", "sredni"),
    ("superstore", "top 10 klientow wedlug sprzedazy", "sredni"),
    ("superstore", "trend miesiecznej sprzedazy", "sredni"),
    # northwind — klasyczne JOIN-y
    ("northwind", "top 10 produktow wedlug przychodu", "trudny"),
    ("northwind", "sprzedaz wedlug kraju klienta", "trudny"),
    ("northwind", "liczba zamowien obslugiwanych przez kazdego pracownika", "trudny"),
    ("northwind", "kwartalny przychod ze sprzedazy", "trudny"),
    # sakila — najtrudniejsze JOIN-y (rental -> inventory -> film -> category)
    ("sakila", "najpopularniejsze kategorie filmow wedlug liczby wypozyczen", "trudny"),
    ("sakila", "miesieczny przychod z platnosci", "sredni"),
    ("sakila", "top 10 aktorow wedlug liczby filmow", "trudny"),
    ("sakila", "srednia dlugosc filmu wedlug kategorii", "trudny"),
]


def _register(email=None):
    email = email or f"harness_{uuid.uuid4().hex[:8]}@test.local"
    r = requests.post(f"{BASE_URL}/register",
                      json={"email": email, "password_hash": "haslo12345"}, timeout=30)
    r.raise_for_status()
    return r.json()


def _upload(token, user_id, path):
    name = os.path.basename(path)
    with open(path, "rb") as f:
        content = f.read()
    files = {"file": (name, io.BytesIO(content), "application/octet-stream")}
    r = requests.post(f"{BASE_URL}/upload", data={"user_id": user_id}, files=files,
                      headers={"Authorization": f"Bearer {token}"}, timeout=300)
    r.raise_for_status()


def _schema_texts(token, user_id):
    """Mapa nazwa_pliku -> (db_path, schema_text) — identyczny format co buildSchemaText
    we frontendzie (Tabela X: kol (typ), ...)."""
    r = requests.get(f"{BASE_URL}/users/{user_id}/databases",
                     headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    out = {}
    for db in r.json():
        text = "\n".join(
            f"Tabela {t}: " + ", ".join(f"{c['name']} ({c['type']})" for c in cols)
            for t, cols in db["schema"].items())
        out[db["name"]] = (db["file_path"], text)
    return out


def _run_prompt(token, db_path, schema_text, prompt):
    t0 = time.monotonic()
    try:
        r = requests.post(f"{BASE_URL}/generate",
                          headers={"Authorization": f"Bearer {token}"},
                          json={"prompt": prompt, "schema_text": schema_text,
                                "chart_type": "", "description": "",
                                "db_path": db_path, "user_id": 0,
                                "n8n_timeout": REQUEST_TIMEOUT},
                          timeout=REQUEST_TIMEOUT)
        elapsed = time.monotonic() - t0
        data = r.json()
        summary = data.get("chart_summary") or {}
        return {
            "status": data.get("status", "error"),
            "elapsed_s": round(elapsed, 1),
            "requested": summary.get("requested"),
            "generated": summary.get("generated"),
            "failed": summary.get("failed"),
            "retries": data.get("retry_count"),
            "url": (data.get("metabase") or {}).get("url", ""),
            "error": (data.get("error") or "")[:200],
        }
    except Exception as e:
        return {"status": "exception", "elapsed_s": round(time.monotonic() - t0, 1),
                "requested": None, "generated": None, "failed": None,
                "retries": None, "url": "", "error": str(e)[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="tylko 1 prompt na baze")
    ap.add_argument("--db", help="ogranicz do jednej bazy (klucz: sklep/firma/superstore/northwind/sakila)")
    args = ap.parse_args()

    prompts = PROMPTS
    if args.db:
        prompts = [p for p in prompts if p[0] == args.db]
    if args.smoke:
        seen, smoke = set(), []
        for p in prompts:
            if p[0] not in seen:
                smoke.append(p); seen.add(p[0])
        prompts = smoke

    needed = {DATASETS[db] for db, _, _ in prompts}
    for fname in needed:
        fpath = os.path.join(FILES_DIR, fname)
        if not os.path.exists(fpath):
            raise SystemExit(f"Brak pliku testowego: {fpath}")

    print(f"[harness] rejestracja konta i upload {len(needed)} baz...")
    user = _register()
    for fname in sorted(needed):
        print(f"[harness]   upload {fname}...")
        _upload(user["token"], user["id"], os.path.join(FILES_DIR, fname))
    schemas = _schema_texts(user["token"], user["id"])

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(os.path.dirname(__file__), f"eval_results_{stamp}.csv")
    fields = ["db", "difficulty", "prompt", "status", "elapsed_s",
              "requested", "generated", "failed", "retries", "url", "error"]
    results = []

    print(f"[harness] start: {len(prompts)} promptow\n")
    for i, (dbkey, prompt, difficulty) in enumerate(prompts, 1):
        fname = DATASETS[dbkey]
        db_path, schema_text = schemas[fname]
        print(f"[{i}/{len(prompts)}] ({dbkey}/{difficulty}) {prompt!r} ...", flush=True)
        row = {"db": dbkey, "difficulty": difficulty, "prompt": prompt}
        row.update(_run_prompt(user["token"], db_path, schema_text, prompt))
        results.append(row)
        print(f"        -> {row['status']} w {row['elapsed_s']}s, "
              f"wykresy {row['generated']}/{row['requested']}, retry {row['retries']}"
              + (f", BLAD: {row['error']}" if row["error"] else ""), flush=True)

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)

    ok = [r for r in results if r["status"] == "success"]
    times = [r["elapsed_s"] for r in ok]
    print("\n===== PODSUMOWANIE =====")
    print(f"promptow: {len(results)}, sukcesow: {len(ok)} "
          f"({100 * len(ok) / max(len(results), 1):.0f}%)")
    if times:
        print(f"czas [s]: min {min(times)}, mediana {statistics.median(times)}, "
              f"max {max(times)}, srednia {statistics.mean(times):.1f}")
        total_req = sum(r["requested"] or 0 for r in ok)
        total_gen = sum(r["generated"] or 0 for r in ok)
        total_ret = sum(r["retries"] or 0 for r in ok)
        print(f"wykresy: {total_gen}/{total_req} przeszlo walidacje "
              f"({100 * total_gen / max(total_req, 1):.0f}%), retry SQL lacznie: {total_ret}")
    for level in ("latwy", "sredni", "trudny"):
        sub = [r for r in results if r["difficulty"] == level]
        if sub:
            oks = sum(1 for r in sub if r["status"] == "success")
            print(f"  {level}: {oks}/{len(sub)} sukcesow")
    print(f"\nCSV: {csv_path}")


if __name__ == "__main__":
    main()
