"""Golden set — test poprawnosci MERYTORYCZNEJ generowanego SQL.

Harness (eval_harness.py) mierzy, czy system w ogole wyprodukowal dzialajacy
dashboard. Golden set idzie krok dalej: dla kazdego promptu istnieje WZORCOWY
SQL napisany recznie i sprawdzamy, czy ktoras karta wygenerowanego dashboardu
zwraca TEN SAM WYNIK co wzorzec (porownujemy WYNIKI zapytan, nie tekst SQL —
rozne zapytania moga byc rownowazne).

Dwa poziomy zgodnosci (oba raportowane):
- EXACT  — znormalizowane wiersze identyczne (etykiety + wartosci),
- VALUES — zgadzaja sie wartosci liczbowe i liczba wierszy (etykiety moga
           roznic sie formatem, np. '2024-01' vs timestamp 2024-01-01).

Normalizacja przed porownaniem: liczby zaokraglone do 4 miejsc, daty do
'YYYY-MM-DD', teksty lower/strip, wiersze posortowane.

Uruchamianie (venv projektu, dzialajacy stack):
    venv/bin/python golden_set.py
Wynik: raport na stdout + golden_set_results_<data>.csv (w .gitignore).
"""
import csv
import datetime
import os
import sys
from decimal import Decimal

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_harness import (BASE_URL, DATASETS, FILES_DIR,  # noqa: E402
                          _register, _run_prompt, _schema_texts, _upload)

PG = dict(host=os.getenv("PG_HOST", "localhost"), port=int(os.getenv("PG_PORT", "5432")),
          dbname=os.getenv("PG_DB", "analytics"),
          user=os.getenv("PG_RO_USER", "readonly"), password=os.getenv("PG_RO_PASS", "readonly"))

# (klucz bazy, prompt, wzorcowy SQL). Wzorce zweryfikowane recznie na danych.
# Prompty dobrane tak, zeby mialy JEDNA jednoznaczna poprawna odpowiedz.
GOLDEN = [
    ("sklep",
     "suma sprzedazy wedlug kategorii",
     "SELECT kategoria, SUM(wartosc_zamowienia) FROM sklep_testowy GROUP BY kategoria"),
    ("sklep",
     "top 5 produktow wedlug sumy sprzedazy",
     "SELECT produkt, SUM(wartosc_zamowienia) AS suma FROM sklep_testowy "
     "GROUP BY produkt ORDER BY suma DESC LIMIT 5"),
    ("firma",
     "liczba umow podpisanych w kazdym miesiacu",
     "SELECT DATE_TRUNC('month', data_podpisania) AS miesiac, COUNT(*) FROM umowy "
     "GROUP BY miesiac ORDER BY miesiac"),
    ("northwind",
     "liczba zamowien obslugiwanych przez kazdego pracownika",
     "SELECT e.firstname || ' ' || e.lastname AS pracownik, COUNT(o.orderid) "
     "FROM employees e JOIN orders o ON e.employeeid = o.employeeid "
     "GROUP BY e.employeeid, pracownik"),
    ("sakila",
     "najpopularniejsze kategorie filmow wedlug liczby wypozyczen",
     "SELECT c.name AS kategoria, COUNT(r.rental_id) AS liczba FROM rental r "
     "JOIN inventory i ON r.inventory_id = i.inventory_id "
     "JOIN film_category fc ON i.film_id = fc.film_id "
     "JOIN category c ON fc.category_id = c.category_id GROUP BY c.name"),
]


def _norm_cell(v):
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, str):
        return v.strip().lower()
    return v


def _norm_rows(rows):
    return sorted(tuple(_norm_cell(c) for c in row) for row in rows)


def _numeric_multiset(rows):
    """Posortowana lista wszystkich wartosci liczbowych — porownanie 'VALUES'
    odporne na rozny format etykiet."""
    out = []
    for row in rows:
        for c in row:
            if isinstance(c, Decimal):
                c = float(c)
            if isinstance(c, (int, float)) and not isinstance(c, bool):
                out.append(round(float(c), 4))
    return sorted(out)


def _run_sql(schema, sql):
    conn = psycopg2.connect(**PG)
    try:
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{schema}",public')
            cur.execute(sql)
            return cur.fetchall()
    finally:
        conn.close()


def _split_generated(sql_blob):
    """Odpowiedz n8n sklada SQL-e kart jako '-- tytul\\nSQL\\n\\n-- tytul\\nSQL'."""
    charts = []
    for block in (sql_blob or "").split("\n\n"):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        title = lines[0].lstrip("- ").strip() if lines[0].startswith("--") else "?"
        sql = "\n".join(l for l in lines if not l.startswith("--")).strip()
        if sql:
            charts.append((title, sql))
    return charts


def _compare(schema, generated_sql, ref_rows):
    try:
        gen_rows = _run_sql(schema, generated_sql)
    except Exception as e:
        return "ERROR", f"SQL nie wykonal sie: {e}"
    if _norm_rows(gen_rows) == _norm_rows(ref_rows):
        return "EXACT", f"{len(gen_rows)} wierszy identycznych"
    if (len(gen_rows) == len(ref_rows)
            and _numeric_multiset(gen_rows) == _numeric_multiset(ref_rows)):
        return "VALUES", (f"{len(gen_rows)} wierszy, wartosci liczbowe zgodne "
                          f"(rozny format etykiet)")
    return "MISMATCH", (f"wygenerowany: {len(gen_rows)} wierszy, "
                        f"wzorzec: {len(ref_rows)} wierszy")


RANK = {"EXACT": 3, "VALUES": 2, "MISMATCH": 1, "ERROR": 0}


def main():
    needed = {DATASETS[db] for db, _, _ in GOLDEN}
    for fname in needed:
        if not os.path.exists(os.path.join(FILES_DIR, fname)):
            raise SystemExit(f"Brak pliku testowego: {fname}")

    print(f"[golden] rejestracja konta i upload {len(needed)} baz...")
    user = _register()
    for fname in sorted(needed):
        _upload(user["token"], user["id"], os.path.join(FILES_DIR, fname))
    schemas = _schema_texts(user["token"], user["id"])

    results = []
    for i, (dbkey, prompt, ref_sql) in enumerate(GOLDEN, 1):
        fname = DATASETS[dbkey]
        db_path, schema_text = schemas[fname]
        ref_rows = _run_sql(db_path, ref_sql)
        assert ref_rows, f"wzorcowy SQL zwrocil 0 wierszy: {prompt!r}"

        print(f"[{i}/{len(GOLDEN)}] ({dbkey}) {prompt!r} ...", flush=True)
        gen = _run_prompt(user["token"], db_path, schema_text, prompt)
        if gen["status"] != "success":
            results.append({"db": dbkey, "prompt": prompt, "verdict": "GEN_FAILED",
                            "chart": "", "detail": gen["error"]})
            print(f"        -> GENERACJA PADLA: {gen['error']}", flush=True)
            continue

        best = ("ERROR", "brak kart", "")
        for title, sql in _split_generated(gen["sql"]):
            verdict, detail = _compare(db_path, sql, ref_rows)
            if RANK[verdict] > RANK[best[0]]:
                best = (verdict, detail, title)
            if verdict == "EXACT":
                break
        results.append({"db": dbkey, "prompt": prompt, "verdict": best[0],
                        "chart": best[2], "detail": best[1]})
        print(f"        -> {best[0]} (karta: {best[2]!r}) — {best[1]}", flush=True)

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(os.path.dirname(__file__), f"golden_set_results_{stamp}.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["db", "prompt", "verdict", "chart", "detail"])
        w.writeheader(); w.writerows(results)

    exact = sum(1 for r in results if r["verdict"] == "EXACT")
    values = sum(1 for r in results if r["verdict"] in ("EXACT", "VALUES"))
    print("\n===== GOLDEN SET — PODSUMOWANIE =====")
    print(f"promptow: {len(results)}")
    print(f"zgodnosc pelna (EXACT):            {exact}/{len(results)}")
    print(f"zgodnosc wartosci (EXACT+VALUES):  {values}/{len(results)}")
    print(f"\nCSV: {csv_path}")


if __name__ == "__main__":
    main()
