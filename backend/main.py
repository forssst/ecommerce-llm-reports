import os
import re
import time
import uuid
import sqlite3
import shutil
import json
from typing import Optional

import psycopg2
from psycopg2 import sql as pgsql

import pandas as pd

import requests as http
import bcrypt
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

import database
import models

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="AI Data Analyst Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

METABASE_URL = os.getenv("METABASE_URL", "http://metabase:3000")
METABASE_PUBLIC_URL = os.getenv("METABASE_PUBLIC_URL", "http://localhost:3000")
METABASE_USER = os.getenv("METABASE_USER", "szymonforstkl3trgwitam@gmail.com")
METABASE_PASSWORD = os.getenv("METABASE_PASSWORD", "Szym0nMetabase")
# Katalog, w ktorym kontener Metabase widzi wgrane pliki baz (ten sam wolumen co UPLOAD_DIR).
METABASE_DB_DIR = os.getenv("METABASE_DB_DIR", "/data/uploads")
UPLOAD_DIR = "/data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
N8N_DASHBOARD_URL = os.getenv("N8N_DASHBOARD_URL", "http://n8n_local:5678/webhook/create-dashboard")

PG_HOST = os.getenv("PG_HOST", "postgres")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DB   = os.getenv("PG_DB", "analytics")
PG_USER = os.getenv("PG_USER", "analyst")
PG_PASS = os.getenv("PG_PASS", "analyst")


def _pg_conn(schema: str = None):
    conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB,
                            user=PG_USER, password=PG_PASS)
    if schema:
        with conn.cursor() as cur:
            cur.execute(pgsql.SQL("SET search_path TO {},public").format(
                pgsql.Identifier(schema)))
    return conn


def _sanitize_schema(user_id: int, filename: str) -> str:
    name = os.path.splitext(filename)[0].lower()
    name = re.sub(r'[^a-z0-9]', '_', name)[:40].strip('_')
    return f"u{user_id}_{name}"


class UserIn(BaseModel):
    email: str
    password_hash: str


class GenerateIn(BaseModel):
    user_id: int
    prompt: str
    description: str = ""
    chart_type: str = ""
    schema_text: str = ""
    db_path: str = ""
    n8n_url: str = ""
    n8n_timeout: int = 120


def _parse_requested_charts(text: str) -> list:
    """Wyciąga listę typów wykresów z tekstu konfiguracji w kolejności wystąpienia."""
    t = text.lower()
    patterns = [
        ("bar",   ["słupkow", "slupkow", "bar"]),
        ("line",  ["liniow", "line", "trend"]),
        ("pie",   ["kołow", "kolow", "pie", "kołowy", "kolowy"]),
        ("table", ["tabel", "table"]),
        ("area",  ["obszarow", "area"]),
        ("row",   ["poziom", "row"]),
    ]
    found = []
    for chart_type, keywords in patterns:
        for kw in keywords:
            pos = t.find(kw)
            if pos != -1:
                found.append((pos, chart_type))
                break
    found.sort()
    return [ct for _, ct in found]


def _find_date_column(schema_name: str):
    """Zwraca nazwę pierwszej kolumny datowej w schemacie PostgreSQL lub None."""
    try:
        conn = _pg_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = %s
                  AND data_type IN ('date','timestamp','timestamp without time zone',
                                    'timestamp with time zone')
                LIMIT 1
            """, (schema_name,))
            row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def _get_mb_date_fields(token: str, db_id: int) -> list:
    """Zwraca pola daty/czasu z metadanych Metabase: [{id, name, table}]."""
    try:
        r = http.get(f"{METABASE_URL}/api/database/{db_id}/metadata",
                     headers={"X-Metabase-Session": token}, timeout=15)
        r.raise_for_status()
        result = []
        for table in r.json().get("tables", []):
            for field in table.get("fields", []):
                bt = field.get("base_type", "")
                if "Date" in bt or "Time" in bt:
                    result.append({
                        "id": field["id"],
                        "name": field["name"].lower(),
                        "table": table["name"].lower(),
                    })
        return result
    except Exception:
        return []


def _sql_refs_date_field(sql: str, date_fields: list):
    """Zwraca pierwsze pole daty znalezione w SQL (lub None)."""
    sql_lower = sql.lower()
    for f in date_fields:
        if f["name"] in sql_lower:
            return f
    return None


def _inject_date_filter(sql: str, tag_name: str = "date_filter") -> str:
    """Wstawia opcjonalną klauzulę Metabase [[AND {{tag}}]] przed GROUP/ORDER BY."""
    clause = f"[[AND {{{{{tag_name}}}}}]]"
    for kw in [r"GROUP\s+BY", r"ORDER\s+BY", r"HAVING", r"LIMIT"]:
        m = re.search(kw, sql, re.IGNORECASE)
        if m:
            before, after = sql[:m.start()].rstrip(), sql[m.start():]
            has_where = bool(re.search(r'\bWHERE\b', before, re.IGNORECASE))
            sep = "\n" + clause + "\n"
            return (before + sep + after) if has_where else (before + "\nWHERE 1=1" + sep + after)
    has_where = bool(re.search(r'\bWHERE\b', sql, re.IGNORECASE))
    return sql + ("\n" + clause if has_where else "\nWHERE 1=1\n" + clause)


def get_db_schema(schema_name: str) -> dict:
    """Czyta schemat tabel z PostgreSQL (schema_name = schemat użytkownika)."""
    conn = _pg_conn()
    schema = {}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """, (schema_name,))
        tables = [r[0] for r in cur.fetchall()]
        for table in tables:
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (schema_name, table))
            cols = cur.fetchall()
            cur.execute(
                pgsql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    pgsql.Identifier(schema_name), pgsql.Identifier(table)))
            count = cur.fetchone()[0]
            schema[table] = {
                "columns": [{"name": c[0], "type": c[1], "pk": False} for c in cols],
                "row_count": count,
            }
    conn.close()
    return schema


def _normalize_chart(chart, idx):
    if not isinstance(chart, dict):
        return f"Wykres {idx + 1}", str(chart).strip(), None
    title = chart.get("title") or chart.get("name") or f"Wykres {idx + 1}"
    sql = (chart.get("sql") or chart.get("text") or chart.get("query")
           or chart.get("output") or "")
    sql = str(sql).strip()
    if sql.startswith("```"):
        sql = sql.strip("`").strip()
    if sql[:3].lower() == "sql":
        sql = sql[3:].lstrip(": \n\r\t")
    sql = sql.replace("```", "").strip()
    ctype = chart.get("chart_type") or chart.get("type") or chart.get("display")
    if ctype:
        ctype = str(ctype).strip().lower()
        ctype = {"słupkowy": "bar", "slupkowy": "bar", "liniowy": "line",
                 "kołowy": "pie", "kolowy": "pie", "tabela": "table"}.get(ctype, ctype)
        if ctype not in ("bar", "line", "pie", "table", "area", "row", "scatter"):
            ctype = None
    return title, sql, ctype


def _clean_sql(sql: str) -> str:
    """Bierze tylko pierwsze zapytanie SQL — usuwa komentarze i wielokrotne instrukcje."""
    # Obsługa backtick code blocks (```sql ... ```)
    if "```" in sql:
        sql = re.sub(r"```(?:sql)?", "", sql, flags=re.IGNORECASE)
    sql = sql.strip()
    # Zamień backticki MySQL/SQLite na lowercase bez cudzysłowów (PostgreSQL ma lowercase kolumny)
    sql = re.sub(r'`([^`]+)`', lambda m: m.group(1).lower(), sql)
    # Zamień "CamelCase" identyfikatory na lowercase (pandas importuje jako lowercase)
    sql = re.sub(r'"([A-Za-z][A-Za-z0-9_]*)"',
                 lambda m: m.group(1).lower() if not m.group(1).isupper() else m.group(0), sql)
    # Usuń bloki komentarzy /* ... */
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    # Usuń komentarze liniowe -- ...
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = sql.strip()
    # Usuń prefiks "sql" lub "SQL:" wstawiany przez LLM przed właściwym zapytaniem
    sql = re.sub(r"^sql\s*:?\s*", "", sql, flags=re.IGNORECASE)
    sql = sql.strip()
    # Weź tylko pierwszą instrukcję (przed pierwszym ;)
    sql = sql.split(";")[0].strip()
    # Obsługa wielu SELECT bez średnika: śledź głębokość nawiasów,
    # żeby nie ucinać podzapytań ani CTE-ów
    lines = sql.split('\n')
    result_lines = []
    paren_depth = 0
    toplevel_selects = 0
    for line in lines:
        if re.match(r'\s*SELECT\b', line, re.IGNORECASE) and paren_depth == 0:
            toplevel_selects += 1
            if toplevel_selects > 1:
                break  # Drugi SELECT na poziomie top = drugi statement
        result_lines.append(line)
        paren_depth += line.count('(') - line.count(')')
    return '\n'.join(result_lines).strip() or sql


def _parse_chart_count(text: str) -> int:
    """Parsuje żądaną liczbę wykresów z tekstu (np. 'Dokładnie 4 wykresy')."""
    m = re.search(r'\b([2-6])\s*wykres', text, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def _run_and_validate(schema_name, sql):
    """Sprawdza SQL na schemacie PostgreSQL i zwraca (ok, error, kolumny, próbka)."""
    if not schema_name:
        return True, None, [], []
    try:
        conn = _pg_conn(schema_name)
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            sample = [list(r) for r in cur.fetchmany(5)]
        conn.close()
        return True, None, cols, sample
    except Exception as e:
        return False, str(e), [], []


def _infer_display(columns, sample):
    """Zgaduje typ wykresu z kształtu danych, gdy LLM go nie poda."""
    if columns and sample and sample[0]:
        first = str(sample[0][0])
        if re.match(r"^\d{4}-\d{2}(-\d{2})?$", first):   # data/miesiąc -> liniowy
            return "line"
    if columns and len(columns) >= 2:                    # kategoria + liczba -> słupkowy
        return "bar"
    return "table"


def _config_hint(config_text):
    """Jeśli w konfiguracji wskazano DOKŁADNIE jeden typ wykresu, użyj go."""
    t = (config_text or "").lower()
    hits = set()
    if "koł" in t or "kol" in t or "pie" in t:
        hits.add("pie")
    if "lini" in t or "line" in t:
        hits.add("line")
    if "obszar" in t or "area" in t:
        hits.add("area")
    if "poziom" in t or "row" in t:
        hits.add("row")
    if "słup" in t or "slup" in t or ("bar" in t and "poziom" not in t and "row" not in t):
        hits.add("bar")
    if "tabel" in t or "table" in t:
        hits.add("table")
    if "punkt" in t or "scatter" in t:
        hits.add("scatter")
    if "lejk" in t or "funnel" in t:
        hits.add("funnel")
    if "kaskad" in t or "waterfall" in t:
        hits.add("waterfall")
    if "licznik" in t or "scalar" in t or "smartscalar" in t:
        hits.add("smartscalar")
    if "kombin" in t or "combo" in t:
        hits.add("combo")
    return next(iter(hits)) if len(hits) == 1 else None


def _viz_settings(display, columns):
    if not columns:
        return {}
    if display in ("bar", "line", "area", "row", "scatter", "waterfall", "combo"):
        return {"graph.dimensions": [columns[0]],
                "graph.metrics": columns[1:] if len(columns) > 1 else [columns[0]]}
    if display == "pie":
        return {"pie.dimension": columns[0],
                "pie.metric": columns[1] if len(columns) > 1 else columns[0]}
    if display == "funnel":
        return {}
    if display == "smartscalar":
        return {}
    if display == "combo":
        return {"graph.dimensions": [columns[0]],
                "graph.metrics": columns[1:] if len(columns) > 1 else [columns[0]],
                "combo.series_settings": {col: {"display": "line"} for col in columns[2:]}}
    return {}


def _get_metabase_token() -> str:
    r = http.post(f"{METABASE_URL}/api/session",
                  json={"username": METABASE_USER, "password": METABASE_PASSWORD})
    r.raise_for_status()
    return r.json()["id"]


def _ensure_metabase_db(token: str, schema_name: str) -> int:
    """Rejestruje (lub zwraca istniejące) połączenie Metabase → PostgreSQL dla danego schematu."""
    headers = {"X-Metabase-Session": token}
    r = http.get(f"{METABASE_URL}/api/database", headers=headers)
    r.raise_for_status()
    db_list = r.json()
    if isinstance(db_list, dict):
        db_list = db_list.get("data", [])

    for db in db_list:
        if db.get("name") == schema_name:
            return db["id"]

    payload = {
        "engine": "postgres",
        "name": schema_name,
        "details": {
            "host": PG_HOST,
            "port": PG_PORT,
            "dbname": PG_DB,
            "user": PG_USER,
            "password": PG_PASS,
            "ssl": False,
            "additional-options": f"currentSchema={schema_name}",
        },
        "is_full_sync": True,
    }
    cr = http.post(f"{METABASE_URL}/api/database", headers=headers, json=payload)
    cr.raise_for_status()
    new_id = cr.json()["id"]
    try:
        http.post(f"{METABASE_URL}/api/database/{new_id}/sync_schema", headers=headers)
        time.sleep(3)  # daj Metabase chwilę na skan pól (potrzebne dla field filters)
    except Exception:
        pass
    return new_id


def create_metabase_dashboard(token: str, name: str) -> int:
    r = http.post(f"{METABASE_URL}/api/dashboard",
                  headers={"X-Metabase-Session": token}, json={"name": name})
    r.raise_for_status()
    return r.json()["id"]


def create_metabase_card(token, db_id, name, sql, display, columns, template_tags=None):
    payload = {
        "name": name,
        "dataset_query": {
            "database": db_id,
            "type": "native",
            "native": {"query": sql, "template-tags": template_tags or {}},
        },
        "display": display,
        "visualization_settings": _viz_settings(display, columns),
    }
    r = http.post(f"{METABASE_URL}/api/card",
                  headers={"X-Metabase-Session": token}, json=payload)
    r.raise_for_status()
    return r.json()["id"]


def publish_metabase_dashboard(token: str, dash_id: int) -> str:
    r = http.post(f"{METABASE_URL}/api/dashboard/{dash_id}/public_link",
                  headers={"X-Metabase-Session": token})
    r.raise_for_status()
    return f"{METABASE_PUBLIC_URL}/public/dashboard/{r.json()['uuid']}"


def _call_n8n(url: str, payload: dict, timeout: int) -> str:
    r = http.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "output" in data:
        return data["output"]
    return r.text


def _full_prompt(g):
    """Pelny prompt do historii: cel + opis + uklad."""
    parts = [f"Cel: {g.prompt}"]
    if g.description:
        parts.append(f"Opis: {g.description}")
    if g.chart_type:
        parts.append(f"Uklad: {g.chart_type}")
    return "\n".join(parts)


def _ollama_json(prompt: str, timeout: int = 120):
    """Bezposrednie wywolanie Ollamy z wymuszonym JSON-em."""
    r = http.post(f"{OLLAMA_URL}/api/generate",
                  json={"model": OLLAMA_MODEL, "prompt": prompt,
                        "stream": False, "format": "json"}, timeout=timeout)
    r.raise_for_status()
    return json.loads((r.json().get("response") or "").strip())


def _generate_multichart(g, db, db_id):
    """Dekompozycja: planowanie -> SQL na kazdy wykres -> jeden dashboard.
    Zwraca None, gdy sie nie uda (wtedy /generate robi fallback do n8n)."""
    requested_types = _parse_requested_charts(g.chart_type)
    n_charts = len(requested_types) if requested_types else (_parse_chart_count(g.chart_type) or 3)

    if requested_types:
        types_instruction = (
            f"UZYTKOWNIK ZADA DOKLADNIE {n_charts} WYKRESOW W TEJ KOLEJNOSCI: "
            + ", ".join(f"({i+1}) chart_type={t}" for i, t in enumerate(requested_types))
            + "\nMUSISZ wygenerowac DOKLADNIE tyle elementow i uzyc DOKLADNIE tych typow chart_type."
        )
    else:
        types_instruction = "Wygeneruj 3-4 roznorodne wykresy (bar, line, pie, table)."

    plan_prompt = (
        "Jestes analitykiem danych. Zaplanuj wykresy analityczne do dashboardu.\n"
        f"{types_instruction}\n"
        "ZASADY:\n"
        "- Kazdy wykres musi miec INNY cel analityczny.\n"
        "- W polu 'goal' napisz DOKLADNIE co pokazac i jakich kolumn uzyc jako etykiet vs wartosci.\n"
        "- Jako etykiety uzyj kolumn TEXT z nazwami/kategoriami — NIGDY kolumn ID ani liczb.\n"
        "- Jesli trzeba pokazac klientow/produkty/pracownikow — w 'goal' napisz explicite zeby uzyc JOIN i kolumny z nazwa (np. customers.companyname, products.productname).\n"
        "- Jesli CEL zawiera slowa: trend/miesiac/rok/czas/timeline — MUSISZ dodac wykres z kolumna daty (chart_type: line lub bar) i opisac to w 'goal'.\n"
        "- Dla trendow w 'goal' napisz: 'GROUP BY DATE_TRUNC(month/year, kolumna_daty)'.\n"
        f"Zwroc WYLACZNIE JSON: {{\"charts\":[{{\"title\":\"...\",\"chart_type\":\"bar|line|pie|table\",\"goal\":\"...\"}}]}}\n"
        "Nie pisz SQL.\n"
        f"CEL: {g.prompt}\n"
        f"WYTYCZNE: {g.chart_type}\n"
        f"OPIS DANYCH: {g.description}\n"
        f"SCHEMAT: {g.schema_text}"
    )
    plan = _ollama_json(plan_prompt, g.n8n_timeout)
    raw_specs = [s for s in (plan.get("charts", []) if isinstance(plan, dict) else []) if isinstance(s, dict)]

    # Nadpisz chart_type jeśli użytkownik podał konkretne typy
    specs = []
    for i, spec in enumerate(raw_specs[:n_charts]):
        if requested_types and i < len(requested_types):
            spec["chart_type"] = requested_types[i]
        specs.append(spec)
    if not specs:
        return None

    _VALID_DISPLAYS = {"bar", "line", "pie", "table", "area", "row", "scatter",
                       "funnel", "smartscalar", "waterfall", "combo"}

    _CHART_HINTS = {
        "scatter":     "- WYKRES PUNKTOWY: zwroc DOKLADNIE 2 kolumny NUMERYCZNE (np. avg_minutes, avg_price). BEZ kolumn tekstowych. Uzyj GROUP BY i AVG/SUM zeby zredukowac wiersze do sensownego zbioru punktow.\n",
        "smartscalar": "- LICZNIK (scalar): zwroc DOKLADNIE JEDEN rzad z JEDNYM agregatem numerycznym. Przyklad: SELECT ROUND(SUM(total)::numeric,2) AS total_revenue FROM invoice\n",
        "funnel":      "- LEJKOWY (funnel): zwroc 2 kolumny — etykieta TEXT (np. nazwa etapu/kategorii) i wartosc numeryczna — posortowane MALEJACO.\n",
        "waterfall":   "- KASKADOWY (waterfall): MUSISZ policzyc ROZNICE rok-do-roku uzywajac LAG(). Przyklad wzorca: WITH y AS (SELECT EXTRACT(YEAR FROM invoicedate)::int AS rok, SUM(total) AS rev FROM invoice GROUP BY 1) SELECT rok::text AS rok, ROUND((rev - LAG(rev) OVER (ORDER BY rok))::numeric, 2) AS zmiana FROM y WHERE LAG(rev) OVER (ORDER BY rok) IS NOT NULL ORDER BY rok. Zwroc 2 kolumny: kategoria (TEXT) i zmiana (NUMERIC, moze byc ujemna).\n",
        "combo":       "- KOMBINOWANY (combo): zwroc kolumne daty/kategorii jako pierwsza, potem co najmniej 2 kolumny numeryczne (np. miesieczna sprzedaz i skumulowana). Sortuj ASC po dacie.\n",
    }

    charts = []
    total_retries = 0
    for spec in specs:
        title = spec.get("title") or ""
        goal = spec.get("goal") or g.prompt
        if not title or title.lower().startswith("wykres"):
            title = goal[:60].strip()
        ctype = (spec.get("chart_type") or "").strip().lower() or None
        chart_hint = _CHART_HINTS.get(ctype, "")
        sql, ok, cols, sample, err = "", False, [], [], None
        for attempt in range(3):
            sql_prompt = (
                "Wygeneruj JEDEN poprawny SELECT (dialekt PostgreSQL) dla celu ponizej.\n"
                "ZASADY — przestrzegaj wszystkich:\n"
                "- Zwroc TYLKO jedno zapytanie SELECT. Zadnych srednikow w srodku, zadnych wielu instrukcji.\n"
                "- Uzyj PELNYCH nazw tabel bez aliasow (np. Invoice.\"InvoiceDate\", nie i.\"InvoiceDate\").\n"
                "  Jesli musisz uzyc aliasu, zdefiniuj go jawnie: FROM \"Invoice\" AS i.\n"
                "- Jako etykiety (pierwsza kolumna) uzyj kolumn TEXT z nazwami/kategoriami.\n"
                "- Kolumny konczace sie na '_id', '_lenght', '_length', '_qty', '_count', '_size', '_weight', '_price' to liczby/ID — NIE uzywaj jako etykiet.\n"
                "- Jesli chcesz pokazac klientow/produkty/pracownikow po nazwie — uzyj JOIN: np. JOIN customers ON orders.customerid = customers.customerid i wybierz customers.companyname jako etykiete.\n"
                "- NIGDY nie uzywaj samego ID (customerid, productid itp.) jako etykiety w wykresie.\n"
                "- Agregaty: SUM(), COUNT(), AVG() na kolumnach numerycznych.\n"
                "- Dla trendow czasowych: ZAWSZE grupuj po pelnym zakresie dat — NIGDY nie filtruj WHERE do konkretnego roku/miesiaca.\n"
                "- Dla dat uzywaj PostgreSQL: DATE_TRUNC('month', kol_daty) AS miesiac  LUB  EXTRACT(YEAR FROM kol_daty)::int AS rok.\n"
                "- Wyniki sortuj sensownie: daty ASC, wartosci DESC (TOP N).\n"
                "- WAZNE: wszystkie nazwy tabel i kolumn sa MALYMI LITERAMI (pandas importuje jako lowercase). Pisz: orderdate, productname, customerid — NIE \"OrderDate\", NIE `OrderDate`.\n"
                "- NIE uzywaj backtickow (`). Jezeli chcesz oznaczyc identyfikator, uzyj podwojnych cudzyslowow lub po prostu pisz bez zadnych cudzyslowow.\n"
                + chart_hint +
                "Zwroc WYLACZNIE JSON: {\"sql\":\"SELECT ...\"}\n"
                f"CEL WYKRESU: {goal}\nSCHEMAT: {g.schema_text}"
            )
            if err:
                sql_prompt += f"\nPOPRZEDNI SQL nie zadzialal: {sql}\nBLAD: {err}\nPopraw blad i zwroc poprawiony JSON."
            try:
                out = _ollama_json(sql_prompt, g.n8n_timeout)
                raw_sql = ((out.get("sql") if isinstance(out, dict) else "") or "").strip()
                sql = _clean_sql(raw_sql)
            except Exception as e:
                err = f"LLM: {e}"; total_retries += 1; continue
            ok, verr, cols, sample = _run_and_validate(g.db_path, sql)
            if ok and sql:
                break
            err = verr or "pusty SQL"; total_retries += 1
            print(f"[SQL ERROR] chart='{title}' attempt={attempt} err={err} sql={sql[:200]}")
        if not ok or not sql:
            print(f"[SKIP] chart='{title}' po {3} probach — pomijam")
            continue
        display = ctype if ctype in _VALID_DISPLAYS else _infer_display(cols, sample)
        charts.append((title, sql, display, cols))

    if not charts:
        return None

    n8n_payload = {
        "db_path": g.db_path,
        "date_column": _find_date_column(g.db_path),
        "charts": [
            {"title": t, "sql": s, "display": d, "columns": c}
            for t, s, d, c in charts
        ],
    }
    # Próba przez n8n; jeśli workflow nie odpowie — bezpośrednie API Metabase jako backup
    try:
        n8n_r = http.post(N8N_DASHBOARD_URL, json=n8n_payload, timeout=120)
        n8n_r.raise_for_status()
        dash_url = n8n_r.json()["url"]
    except Exception:
        mb_token = _get_metabase_token()
        mb_db_id = _ensure_metabase_db(mb_token, g.db_path)
        # Zawsze wymuszaj re-sync żeby Metabase odczytał aktualne typy kolumn (np. TIMESTAMP)
        try:
            http.post(f"{METABASE_URL}/api/database/{mb_db_id}/sync_schema",
                      headers={"X-Metabase-Session": mb_token})
            time.sleep(6)
        except Exception:
            pass
        date_fields = _get_mb_date_fields(mb_token, mb_db_id)
        dash_id = create_metabase_dashboard(mb_token, "Dashboard Analityczny AI")
        param_id = str(uuid.uuid4())
        has_date_filter = False
        dashcards = []
        for i2, (t2, s2, d2, c2) in enumerate(charts):
            date_field = _sql_refs_date_field(s2, date_fields) if date_fields else None
            template_tags, card_sql, card_has_filter = {}, s2, False
            if date_field:
                tag_uuid = str(uuid.uuid4())
                template_tags = {"date_filter": {
                    "id": tag_uuid, "name": "date_filter",
                    "display-name": "Zakres dat", "type": "dimension",
                    "dimension": ["field", date_field["id"], None],
                    "widget-type": "date/range", "default": None,
                }}
                card_sql = _inject_date_filter(s2)
                card_has_filter = True
                has_date_filter = True
            card_id = create_metabase_card(mb_token, mb_db_id, t2, card_sql, d2, c2, template_tags)
            dashcard = {"id": -(i2 + 1), "card_id": card_id,
                        "row": (i2 // 2) * 8, "col": (i2 % 2) * 12,
                        "size_x": 12, "size_y": 8, "parameter_mappings": []}
            if card_has_filter:
                dashcard["parameter_mappings"] = [{"parameter_id": param_id,
                    "card_id": card_id, "target": ["dimension", ["template-tag", "date_filter"]]}]
            dashcards.append(dashcard)
        if has_date_filter:
            http.put(f"{METABASE_URL}/api/dashboard/{dash_id}",
                     headers={"X-Metabase-Session": mb_token},
                     json={"name": "Dashboard Analityczny AI",
                           "parameters": [{"id": param_id, "type": "date/range",
                                           "name": "Zakres dat", "slug": "date_filter"}]})
        if dashcards:
            http.put(f"{METABASE_URL}/api/dashboard/{dash_id}/cards",
                     headers={"X-Metabase-Session": mb_token},
                     json={"cards": dashcards})
        dash_url = publish_metabase_dashboard(mb_token, dash_id)

    pretty = json.dumps(
        {"dashboard_title": "Dashboard Analityczny AI",
         "dashboard_url": dash_url,
         "charts": [{"title": t, "sql": s, "chart_type": d} for t, s, d, _ in charts]},
        indent=2, ensure_ascii=False)
    rec = models.Query(user_id=g.user_id, database_id=db_id, prompt_nl=_full_prompt(g),
                       generated_sql=pretty, status="success", retry_count=total_retries)
    db.add(rec); db.commit()
    return {"status": "success", "sql": pretty, "retry_count": total_retries,
            "metabase": {"url": dash_url}}


@app.post("/users")
def get_or_create_user(user: UserIn, db: Session = Depends(database.get_db)):
    db_user = db.query(models.User).filter_by(email=user.email).first()
    if not db_user:
        db_user = models.User(email=user.email, password_hash=user.password_hash)
        db.add(db_user); db.commit(); db.refresh(db_user)
    return {"id": db_user.id, "email": db_user.email}


@app.post("/register")
def register(user: UserIn, db: Session = Depends(database.get_db)):
    if db.query(models.User).filter_by(email=user.email).first():
        raise HTTPException(status_code=409, detail="Konto z tym e-mailem juz istnieje")
    h = bcrypt.hashpw(user.password_hash.encode(), bcrypt.gensalt()).decode()
    u = models.User(email=user.email, password_hash=h)
    db.add(u); db.commit(); db.refresh(u)
    return {"id": u.id, "email": u.email}


@app.post("/login")
def login(user: UserIn, db: Session = Depends(database.get_db)):
    u = db.query(models.User).filter_by(email=user.email).first()
    if not u:
        raise HTTPException(status_code=401, detail="Nieprawidlowy e-mail lub haslo")
    ok = False
    try:
        ok = bcrypt.checkpw(user.password_hash.encode(), u.password_hash.encode())
    except Exception:
        ok = (u.password_hash == "x")   # konta seedowane przed dodaniem hasel
    if not ok and u.password_hash == "x":
        ok = True
    if not ok:
        raise HTTPException(status_code=401, detail="Nieprawidlowy e-mail lub haslo")
    return {"id": u.id, "email": u.email}


class DescribeIn(BaseModel):
    schema_text: str


class EnhanceIn(BaseModel):
    prompt: str
    schema_text: str


@app.post("/enhance-prompt")
def enhance_prompt(body: EnhanceIn):
    enhance_prompt_text = (
        "Jestes ekspertem analityki danych. Przepisz zapytanie uzytkownika na bardziej szczegolowe.\n"
        "ZASADY — przestrzegaj wszystkich:\n"
        "- Odpowiedz WYLACZNIE po polsku, naturalnym jezykiem (1-3 zdania).\n"
        "- ABSOLUTNIE NIE pisz SQL, kodu, SELECT, FROM, WHERE, JOIN ani zadnych fragmentow kodu.\n"
        "- NIE uzywaj nazw kolumn w formacie technicznych (bez customer.firstname — pisz 'imie i nazwisko klienta').\n"
        "- Dodaj: co konkretnie pokazac, jak sortowac, ile rekordow (np. TOP 10), jaka agregacja (suma/srednia/liczba).\n"
        "- Uzyj wiedzy ze schematu zeby wiedziec co jest dostepne, ale pisz o tym po polsku.\n"
        "Przyklad dobrego wyniku: 'Pokaż TOP 10 klientów według łącznej kwoty zakupów, posortowanych malejąco. Uwzględnij imię, nazwisko i sumę wydatków.'\n"
        f"SCHEMAT:\n{body.schema_text}\n"
        f"ZAPYTANIE UZYTKOWNIKA: {body.prompt}"
    )
    try:
        r = http.post(f"{OLLAMA_URL}/api/generate",
                      json={"model": OLLAMA_MODEL, "prompt": enhance_prompt_text, "stream": False},
                      timeout=90)
        r.raise_for_status()
        enhanced = (r.json().get("response") or "").strip()
        # Jeśli model mimo wszystko wygenerował SQL — bierzemy tylko pierwsze zdanie przed SELECT/FROM
        if any(kw in enhanced.upper() for kw in ("SELECT ", "FROM ", "JOIN ", "WHERE ", "GROUP BY")):
            lines = [l for l in enhanced.splitlines() if not any(
                kw in l.upper() for kw in ("SELECT", "FROM", "JOIN", "WHERE", "GROUP BY", "ORDER BY", "LIMIT", "HAVING"))]
            enhanced = " ".join(lines).strip() or body.prompt
        return {"enhanced": enhanced}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/describe-schema")
def describe_schema(body: DescribeIn):
    prompt = (
        "Jestes ekspertem od baz danych. Na podstawie schematu ponizej napisz krotki opis po polsku (3-4 zdania).\n"
        "Opisz: co zawiera baza, jakie sa glowne tabele i do czego sluza, jakie analizy mozna z niej robic.\n"
        "Odpowiedz WYLACZNIE opisem tekstowym — bez JSON, bez punktow, bez markdown.\n"
        f"SCHEMAT:\n{body.schema_text}"
    )
    try:
        r = http.post(f"{OLLAMA_URL}/api/generate",
                      json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                      timeout=60)
        r.raise_for_status()
        return {"description": (r.json().get("response") or "").strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload")
async def upload_database(user_id: int = Form(...), file: UploadFile = File(...),
                          db: Session = Depends(database.get_db)):
    ext = os.path.splitext(file.filename)[1].lower()
    tmp_path = f"/tmp/_upload_{file.filename}"

    with open(tmp_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    # Wczytaj wszystkie tabele do słownika DataFrame-ów
    dfs: dict = {}
    try:
        if ext in (".db", ".sqlite", ".sqlite3"):
            sq = sqlite3.connect(tmp_path)
            cur = sq.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            for (tname,) in cur.fetchall():
                dfs[tname] = pd.read_sql(f'SELECT * FROM "{tname}"', sq)
            sq.close()
        elif ext == ".csv":
            stem = re.sub(r"[^\w]", "_", os.path.splitext(file.filename)[0])
            dfs[stem] = pd.read_csv(tmp_path, encoding="utf-8-sig")
        elif ext in (".xlsx", ".xls"):
            xls = pd.ExcelFile(tmp_path)
            for sheet in xls.sheet_names:
                tname = re.sub(r"[^\w]", "_", sheet).strip("_").lower() or "sheet"
                dfs[tname] = pd.read_excel(xls, sheet_name=sheet)
        else:
            raise HTTPException(status_code=400, detail="Nieobsługiwany format pliku.")
    finally:
        os.remove(tmp_path)

    schema_name = _sanitize_schema(user_id, file.filename)

    # Załaduj do PostgreSQL (usuń stary schemat jeśli istnieje)
    from sqlalchemy import create_engine, text as sa_text
    pg_url = f"postgresql://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    engine = create_engine(pg_url)
    with engine.connect() as conn:
        conn.execute(sa_text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        conn.execute(sa_text(f'CREATE SCHEMA "{schema_name}"'))
        conn.commit()
    for tname, df in dfs.items():
        safe_tname = re.sub(r"[^\w]", "_", tname).strip("_").lower() or "data"
        df.columns = [re.sub(r"\W+", "_", c).strip("_").lower() for c in df.columns]
        df.to_sql(safe_tname, engine, schema=schema_name, if_exists="replace", index=False)
    # Rzutuj kolumny tekstowe z datami na TIMESTAMP bezpośrednio w PostgreSQL
    date_hints = {'date', 'time', 'created', 'updated', 'timestamp'}
    from sqlalchemy import text as sa_text2
    with engine.connect() as conn:
        for safe_t in [re.sub(r"[^\w]", "_", t).strip("_").lower() or "data" for t in dfs.keys()]:
            rows = conn.execute(sa_text2(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND data_type = 'text'"),
                {"s": schema_name, "t": safe_t}).fetchall()
            for (col,) in rows:
                if any(h in col.lower() for h in date_hints):
                    try:
                        conn.execute(sa_text2(
                            f'ALTER TABLE "{schema_name}"."{safe_t}" '
                            f'ALTER COLUMN "{col}" TYPE TIMESTAMP '
                            f'USING "{col}"::timestamp'))
                        conn.commit()
                    except Exception:
                        conn.rollback()
    engine.dispose()

    schema = get_db_schema(schema_name)
    compact_schema = {t: [c["name"] for c in info["columns"]] for t, info in schema.items()}
    rec = models.Database(user_id=user_id, name=file.filename,
                          file_path=schema_name, schema_json=compact_schema)
    db.add(rec); db.commit(); db.refresh(rec)
    return {"id": rec.id, "name": rec.name, "message": "Baza wgrana pomyślnie!"}


@app.get("/users/{user_id}/databases")
def get_user_databases(user_id: int, db: Session = Depends(database.get_db)):
    rows = db.query(models.Database).filter_by(user_id=user_id).order_by(
        models.Database.uploaded_at.desc()).all()
    return [{"id": r.id, "name": r.name, "file_path": r.file_path, "schema": r.schema_json}
            for r in rows]


@app.delete("/databases/{db_id}")
def delete_database(db_id: int, db: Session = Depends(database.get_db)):
    rec = db.query(models.Database).filter_by(id=db_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Baza nie istnieje")
    schema_name = rec.file_path
    # Usuń schemat z PostgreSQL jeśli wygląda jak pg schema (u{id}_nazwa)
    if schema_name and re.match(r'^u\d+_', schema_name):
        try:
            from sqlalchemy import create_engine, text as sa_text
            pg_url = f"postgresql://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}"
            engine = create_engine(pg_url)
            with engine.connect() as conn:
                conn.execute(sa_text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
                conn.commit()
            engine.dispose()
        except Exception:
            pass
    db.query(models.Query).filter_by(database_id=db_id).delete()
    db.delete(rec); db.commit()
    return {"message": "Usunięto"}


@app.get("/users/{user_id}/queries")
def get_user_queries(user_id: int, db: Session = Depends(database.get_db)):
    rows = db.query(models.Query).filter_by(user_id=user_id).order_by(
        models.Query.created_at.desc()).limit(20).all()
    return [{"id": r.id, "prompt": r.prompt_nl, "sql": r.generated_sql,
             "status": r.status, "retry_count": r.retry_count} for r in rows]


@app.post("/generate")
def generate(g: GenerateIn, db: Session = Depends(database.get_db)):
    db_obj = db.query(models.Database).filter_by(file_path=g.db_path).first()
    db_id = db_obj.id if db_obj else 1

    # Najpierw multi-wykres (dekompozycja przez Ollamę). W razie czego -> fallback n8n niżej.
    try:
        multi = _generate_multichart(g, db, db_id)
        if multi:
            return multi
    except Exception:
        pass

    max_retries = 3
    last_error = ""
    base_query = (f"Cel główny: {g.prompt}\n"
                  f"Wytyczne do dashboardu: {g.chart_type}\n"
                  f"Dodatkowy opis bazy: {g.description}")
    config_hint = _config_hint(g.chart_type)

    for attempt in range(max_retries):
        query_text = base_query
        if last_error:
            query_text += (f"\n\nUWAGA: poprzednia próba dała błędny SQL.\n"
                           f"Błąd: {last_error}\n"
                           "Popraw zapytania — użyj WYŁĄCZNIE istniejących tabel i kolumn ze schematu.")
        payload = {"query": query_text, "schema": g.schema_text,
                   "db_name": os.path.basename(g.db_path)}
        try:
            raw = _call_n8n(g.n8n_url, payload, g.n8n_timeout)
            if raw:
                raw = raw.replace("```json", "").replace("```", "").strip()
            try:
                dash_data = json.loads(raw)
            except Exception as e:
                last_error = f"Błąd parsowania JSON: {e}"
                continue
            if isinstance(dash_data, list):
                dash_data = {"dashboard_title": "Dashboard Analityczny AI", "charts": dash_data}

            charts_raw = dash_data.get("charts", [])
            normalized = []
            problem = None
            for idx, ch in enumerate(charts_raw):
                title, sql, ctype = _normalize_chart(ch, idx)
                if not sql:
                    problem = f"Wykres '{title}' nie zawiera SQL."; break
                sql = _clean_sql(sql)
                ok, err, cols, sample = _run_and_validate(g.db_path, sql)
                if not ok:
                    problem = f"SQL dla '{title}' nie działa: {err}"; break
                display = ctype or config_hint or _infer_display(cols, sample)
                normalized.append((title, sql, display, cols))

            if problem or not normalized:
                last_error = problem or "Brak poprawnych wykresów."
                continue

            mb_token = _get_metabase_token()
            mb_db_id = _ensure_metabase_db(mb_token, g.db_path)
            dash_title = dash_data.get("dashboard_title", "Dashboard Analityczny AI")
            dash_id = create_metabase_dashboard(mb_token, dash_title)

            dashcards = []
            for idx, (title, sql, display, cols) in enumerate(normalized):
                card_id = create_metabase_card(mb_token, mb_db_id, title, sql, display, cols)
                dashcards.append({"id": -(idx + 1), "card_id": card_id,
                                  "row": (idx // 2) * 8, "col": (idx % 2) * 12,
                                  "size_x": 12, "size_y": 8})
            if dashcards:
                r = http.put(f"{METABASE_URL}/api/dashboard/{dash_id}/cards",
                             headers={"X-Metabase-Session": mb_token}, json={"cards": dashcards})
                r.raise_for_status()

            dash_url = publish_metabase_dashboard(mb_token, dash_id)
            pretty_json = json.dumps(dash_data, indent=2, ensure_ascii=False)
            rec = models.Query(user_id=g.user_id, database_id=db_id, prompt_nl=_full_prompt(g),
                               generated_sql=pretty_json, status="success", retry_count=attempt)
            db.add(rec); db.commit()
            return {"status": "success", "sql": pretty_json,
                    "retry_count": attempt, "metabase": {"url": dash_url}}

        except Exception as e:
            last_error = f"Metabase / n8n Error: {e}"
            continue

    rec = models.Query(user_id=g.user_id, database_id=db_id, prompt_nl=_full_prompt(g),
                       generated_sql="", status="error", retry_count=max_retries)
    db.add(rec); db.commit()
    return {"status": "error", "error": last_error}
