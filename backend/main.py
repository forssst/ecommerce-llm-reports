import os
import re
import time
import uuid
import sqlite3
import shutil
import json
from string import Formatter
from typing import Optional
from datetime import datetime, date, timezone, timedelta

import psycopg2
from psycopg2 import sql as pgsql

import pandas as pd

import requests as http
import bcrypt
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from jose import jwt, JWTError

import database
import models

models.Base.metadata.create_all(bind=database.engine)

_PROMPTS_PATH = os.path.join(os.path.dirname(__file__), "prompts.json")
with open(_PROMPTS_PATH, encoding="utf-8") as _f:
    PROMPTS = json.load(_f)

# Placeholdery, ktore kazdy prompt MUSI zawierac — zeby .format() w kodzie sie nie wywalil
# po edycji promptu przez /prompts.
_PROMPT_PLACEHOLDERS = {
    "plan_prompt": {"types_instruction", "goal", "chart_type", "description", "schema_text"},
    "sql_prompt": {"chart_hint", "goal", "schema_text"},
    "sql_retry_suffix": {"sql", "err"},
    "sql_prompt_sqlcoder": {"chart_hint", "goal", "schema_text"},
    "sql_retry_suffix_sqlcoder": {"sql", "err"},
    "describe_schema": {"schema_text"},
    "enhance_prompt": {"description", "schema_text", "prompt", "clarification"},
    "clarify_prompt": {"description", "schema_text", "goal"},
}

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

JWT_SECRET = os.getenv("JWT_SECRET", "zmien-mnie-na-cos-tajnego-w-produkcji")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7  # tydzień


def _create_token(user_id: int, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    return jwt.encode({"sub": str(user_id), "email": email, "exp": expire},
                      JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(authorization: str = Header(None)) -> int:
    """Weryfikuje JWT i zwraca user_id. Używaj jako Depends() w chronionych endpointach."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Brak tokenu autoryzacji")
    token = authorization.removeprefix("Bearer ")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Nieprawidłowy lub wygasły token")


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_SQL_MODEL = os.getenv("OLLAMA_SQL_MODEL", "qwen2.5-coder:7b")
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


_RELATIVE_DATE_FILTER = re.compile(r'(?i)(current_date|now\(\))\s*[-+]\s*interval')

# Fraza "w ostatnich 3 miesiącach" / "w ostatnim roku" itp. w TYTULE wykresu.
# Guard _RELATIVE_DATE_FILTER usuwa taki filtr z SQL przy retry, ale tytul z planu
# zostaje — wtedy tytul obiecuje okres, ktorego SQL nie filtruje.
_RELATIVE_PERIOD_IN_TITLE = re.compile(
    r'(?i)\s*(?:w\s+ci[ąa]gu\s+|w\s+|z\s+|za\s+)?ostatni\w*\s*(?:\d+\s*)?'
    r'(?:miesi[ąa]c\w*|miesi[ęe]cy|dni\w*|tygodni\w*|lat(?:ach)?|rok\w*)')

# Znaki spoza polskiego alfabetu: CJK, cyrylica oraz łacińskie diakrytyki innych języków
# (np. węgierskie á/ő/ű, niemieckie ä/ß, czeskie š/č). Polskie ąćęłńóśźż są dozwolone.
_FOREIGN_CHARS = re.compile(
    r'[一-鿿぀-ゟ゠-ヿ가-힯а-яА-ЯёЁáàâäãåéèêëíìîïöőõòôúùûüűñçßýÿæøšžčřěůďťň]',
    re.IGNORECASE)


def _is_foreign_language(text: str) -> bool:
    """True gdy tekst zawiera znaki spoza polskiego alfabetu (model dryfuje w obcy język)."""
    return bool(_FOREIGN_CHARS.search(text or ""))


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
        ("scatter",     ["punktow", "scatter"]),
        ("funnel",      ["lejkow", "funnel"]),
        ("waterfall",   ["kaskadow", "waterfall"]),
        ("smartscalar", ["licznik", "scalar"]),
        ("combo",       ["kombinowan", "combo"]),
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
    cols = _find_date_columns(schema_name)
    return cols[0] if cols else None


def _find_date_columns(schema_name: str):
    """Zwraca WSZYSTKIE (unikalne) nazwy kolumn datowych w schemacie. Uzywane do
    dopasowania kolumny daty PER WYKRES (main.py: 'Przygotuj Wykresy' w n8n) —
    baza moze miec kilka tabel z roznymi kolumnami dat (np. data_rejestracji,
    data_zatrudnienia, data_podpisania), wiec jedna globalna kolumna (stare
    zachowanie _find_date_column) czesto nie pasuje do konkretnego wykresu."""
    try:
        conn = _pg_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT column_name FROM information_schema.columns
                WHERE table_schema = %s
                  AND data_type IN ('date','timestamp','timestamp without time zone',
                                    'timestamp with time zone')
            """, (schema_name,))
            rows = cur.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


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


def _build_ddl_schema(schema_name: str) -> str:
    """Buduje CREATE TABLE DDL w formacie którego oczekuje sqlcoder."""
    try:
        conn = _pg_conn()
        lines = []
        with conn.cursor() as cur:
            cur.execute("""SELECT table_name FROM information_schema.tables
                           WHERE table_schema=%s AND table_type='BASE TABLE'
                           ORDER BY table_name""", (schema_name,))
            tables = [r[0] for r in cur.fetchall()]
            for table in tables:
                cur.execute("""SELECT column_name, data_type
                               FROM information_schema.columns
                               WHERE table_schema=%s AND table_name=%s
                               ORDER BY ordinal_position""", (schema_name, table))
                cols = ", ".join(f"{c[0]} {c[1].upper()}" for c in cur.fetchall())
                lines.append(f"CREATE TABLE {table} ({cols});")
        conn.close()
        return "\n".join(lines)
    except Exception:
        return ""


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


_NUMERIC_COL_SUFFIXES = (
    "_id", "_lenght", "_length", "_qty", "_count",
    "_size", "_weight", "_price", "_value", "_num",
)


_NUMERIC_COL_SUFFIXES = (
    "_id", "_lenght", "_length", "_qty", "_count",
    "_size", "_weight", "_price", "_value", "_num",
)
_CHART_TYPES_NUMERIC_FIRST_OK = {"smartscalar", "scatter"}


def _check_label_column(cols, sample, chart_type=None):
    """Zwraca komunikat błędu jeśli pierwsza kolumna (etykieta) wygląda jak metryka numeryczna.
    Sprawdzamy tylko NAZWĘ kolumny — nie wartości, bo liczby całkowite mogą być kategoriami (np. review_score 1-5)."""
    if chart_type in _CHART_TYPES_NUMERIC_FIRST_OK:
        return None
    if not cols:
        return None
    first_col = cols[0].lower()
    if any(first_col.endswith(s) for s in _NUMERIC_COL_SUFFIXES):
        return (
            f"Kolumna '{cols[0]}' to metryka numeryczna, nie etykieta tekstowa. "
            f"Użyj kolumny z nazwą/kategorią (np. product_category_name, customer_name) "
            f"jako pierwszej kolumny — NIE kolumn kończących się na _id, _length, _lenght, _count itp."
        )
    return None


def _check_smartscalar_shape(cols, sample):
    """Licznik (smartscalar) w Metabase to wykres TRENDU: wymaga pierwszej kolumny z datą
    (inaczej karta pokazuje 'Group only by a time field...'). Sprawdzamy próbkę wyników."""
    if not cols or not sample:
        return None
    first = next((row[0] for row in sample if row and row[0] is not None), None)
    if first is None:
        return None
    if isinstance(first, (date, datetime)) or re.match(r"^\d{4}-\d{2}", str(first)):
        return None
    return (
        "LICZNIK (smartscalar) wymaga trendu w czasie: pierwsza kolumna MUSI byc miesiacem "
        "(DATE_TRUNC('month', kolumna_daty)), druga JEDNYM agregatem numerycznym. "
        "Przyklad: SELECT DATE_TRUNC('month', data_zamowienia) AS miesiac, COUNT(*) AS liczba "
        "FROM zamowienia GROUP BY 1 ORDER BY 1"
    )


def _hint_missing_column(schema_name: str, error_msg: str) -> str:
    """Jeśli błąd to 'column X does not exist', dołącza listę dostępnych kolumn z PostgreSQL."""
    m = re.search(r'column ["\w.]*?(\w+)["\w.]*? does not exist', error_msg, re.IGNORECASE)
    if not m:
        return error_msg
    missing = m.group(1).lower()
    try:
        conn = _pg_conn()
        with conn.cursor() as cur:
            cur.execute("""SELECT table_name, column_name FROM information_schema.columns
                           WHERE table_schema = %s ORDER BY table_name, ordinal_position""",
                        (schema_name,))
            rows = cur.fetchall()
        conn.close()
        by_table = {}
        for tname, cname in rows:
            by_table.setdefault(tname, []).append(cname)
        available = "; ".join(f"{t}: {', '.join(c)}" for t, c in by_table.items())
        return (f"{error_msg}\n"
                f"Kolumna '{missing}' NIE ISTNIEJE w schemacie.\n"
                f"Dostepne kolumny: {available}")
    except Exception:
        return error_msg


def _run_and_validate(schema_name, sql, chart_type=None):
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
        label_err = _check_label_column(cols, sample, chart_type)
        if label_err:
            return False, label_err, cols, sample
        if chart_type == "smartscalar":
            ss_err = _check_smartscalar_shape(cols, sample)
            if ss_err:
                return False, ss_err, cols, sample
        return True, None, cols, sample
    except Exception as e:
        enriched = _hint_missing_column(schema_name, str(e))
        return False, enriched, [], []


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


class OllamaUnavailableError(Exception):
    pass


class OllamaResponseError(Exception):
    pass


def _ollama_json(prompt: str, timeout: int = 120, model: str = None):
    """Bezposrednie wywolanie Ollamy z wymuszonym JSON-em."""
    used_model = model or OLLAMA_MODEL
    try:
        r = http.post(f"{OLLAMA_URL}/api/generate",
                      json={"model": used_model, "prompt": prompt,
                            "stream": False, "format": "json"}, timeout=timeout)
        r.raise_for_status()
    except http.exceptions.ConnectionError:
        raise OllamaUnavailableError("Ollama jest niedostępna — sprawdź czy kontener ollama działa.")
    except http.exceptions.Timeout:
        raise OllamaUnavailableError(f"Ollama nie odpowiedziała w ciągu {timeout}s — model może być jeszcze ładowany.")
    except http.exceptions.HTTPError as e:
        raise OllamaResponseError(f"Ollama zwróciła błąd HTTP: {e}")
    raw = (r.json().get("response") or "").strip()
    if not raw:
        raise OllamaResponseError("Ollama zwróciła pustą odpowiedź — spróbuj ponownie.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise OllamaResponseError(f"Odpowiedź Ollamy nie jest poprawnym JSON: {e}")


_VALID_DISPLAYS = {"bar", "line", "pie", "table", "area", "row", "scatter",
                   "funnel", "smartscalar", "waterfall", "combo"}

_CHART_HINTS = {
    "scatter":     "- WYKRES PUNKTOWY: zwroc DOKLADNIE 2 kolumny NUMERYCZNE (np. avg_minutes, avg_price). BEZ kolumn tekstowych. Uzyj GROUP BY i AVG/SUM zeby zredukowac wiersze do sensownego zbioru punktow.\n",
    "smartscalar": "- LICZNIK (smartscalar): to wykres TRENDU — zwroc DOKLADNIE 2 kolumny: miesiac (DATE_TRUNC('month', kolumna_daty)) i JEDEN agregat numeryczny, posortowane po miesiacu. Przyklad: SELECT DATE_TRUNC('month', invoicedate) AS miesiac, ROUND(SUM(total)::numeric,2) AS przychod FROM invoice GROUP BY 1 ORDER BY 1\n",
    "funnel":      "- LEJKOWY (funnel): zwroc 2 kolumny — etykieta TEXT (np. nazwa etapu/kategorii) i wartosc numeryczna — posortowane MALEJACO.\n",
    "waterfall":   "- KASKADOWY (waterfall): MUSISZ policzyc ROZNICE rok-do-roku uzywajac LAG(). Przyklad wzorca: WITH y AS (SELECT EXTRACT(YEAR FROM invoicedate)::int AS rok, SUM(total) AS rev FROM invoice GROUP BY 1) SELECT rok::text AS rok, ROUND((rev - LAG(rev) OVER (ORDER BY rok))::numeric, 2) AS zmiana FROM y WHERE LAG(rev) OVER (ORDER BY rok) IS NOT NULL ORDER BY rok. Zwroc 2 kolumny: kategoria (TEXT) i zmiana (NUMERIC, moze byc ujemna).\n",
    "combo":       "- KOMBINOWANY (combo): zwroc kolumne daty/kategorii jako pierwsza, potem co najmniej 2 kolumny numeryczne (np. miesieczna sprzedaz i skumulowana). Sortuj ASC po dacie.\n",
}


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

    plan_prompt = PROMPTS["plan_prompt"].format(
        types_instruction=types_instruction,
        goal=g.prompt,
        chart_type=g.chart_type,
        description=g.description,
        schema_text=g.schema_text,
    )
    plan = _ollama_json(plan_prompt, g.n8n_timeout)
    raw_specs = [s for s in (plan.get("charts", []) if isinstance(plan, dict) else []) if isinstance(s, dict)]

    # Model czasem generuje caly plan w obcym jezyku (widziane: wegierski) mimo polskiego
    # promptu — wykryj znaki spoza polskiego alfabetu i powtorz planowanie raz z ostrzezeniem.
    if raw_specs and any(_is_foreign_language(f"{s.get('title', '')} {s.get('goal', '')}") for s in raw_specs):
        retry_plan = _ollama_json(
            plan_prompt + "\nUWAGA: POPRZEDNI PLAN byl w obcym jezyku. Pola 'title' i 'goal' "
                          "MUSZA byc napisane WYLACZNIE po polsku.",
            g.n8n_timeout)
        retry_specs = [s for s in (retry_plan.get("charts", []) if isinstance(retry_plan, dict) else []) if isinstance(s, dict)]
        if retry_specs:
            raw_specs = retry_specs

    # Nadpisz chart_type jeśli użytkownik podał konkretne typy
    specs = []
    for i, spec in enumerate(raw_specs[:n_charts]):
        if requested_types and i < len(requested_types):
            spec["chart_type"] = requested_types[i]
        specs.append(spec)
    if not specs:
        return None

    is_sqlcoder = "sqlcoder" in OLLAMA_SQL_MODEL.lower()
    sql_schema = _build_ddl_schema(g.db_path) if is_sqlcoder else g.schema_text

    charts = []
    total_retries = 0
    for spec in specs:
        title = spec.get("title") or ""
        goal = spec.get("goal") or g.prompt
        if not title or title.lower().startswith("wykres"):
            title = goal[:60].strip()
        # Ostatnia linia obrony: tytul nadal w obcym jezyku -> uzyj promptu uzytkownika
        # (zawsze po polsku); 'goal' zostaje, bo SQL i tak powstaje z sensu, nie jezyka.
        if _is_foreign_language(title):
            title = (g.prompt or goal)[:60].strip()
        ctype = (spec.get("chart_type") or "").strip().lower() or None
        chart_hint = _CHART_HINTS.get(ctype, "")
        sql, ok, cols, sample, err = "", False, [], [], None
        for attempt in range(3):
            prompt_key = "sql_prompt_sqlcoder" if is_sqlcoder else "sql_prompt"
            retry_key  = "sql_retry_suffix_sqlcoder" if is_sqlcoder else "sql_retry_suffix"
            sql_prompt = PROMPTS[prompt_key].format(
                chart_hint=chart_hint,
                goal=goal,
                schema_text=sql_schema,
            )
            if err:
                sql_prompt += PROMPTS[retry_key].format(sql=sql, err=err)
            try:
                out = _ollama_json(sql_prompt, g.n8n_timeout, model=OLLAMA_SQL_MODEL)
                raw_sql = ((out.get("sql") if isinstance(out, dict) else "") or "").strip()
                sql = _clean_sql(raw_sql)
            except Exception as e:
                err = f"LLM: {e}"; total_retries += 1; continue
            if _RELATIVE_DATE_FILTER.search(sql):
                err = ("SQL uzywa CURRENT_DATE/NOW() z INTERVAL do filtrowania WHERE — to zwroci PUSTY "
                       "wynik, bo dane moga byc z innego okresu niz biezaca data serwera. Usun ten "
                       "filtr calkowicie i pokaz PELNY zakres dat z tabeli, bez WHERE na kolumnie daty.")
                total_retries += 1
                continue
            ok, verr, cols, sample = _run_and_validate(g.db_path, sql, ctype)
            if ok and sql:
                break
            err = verr or "pusty SQL"; total_retries += 1
            print(f"[SQL ERROR] chart='{title}' attempt={attempt} err={err} sql={sql[:200]}")
        if not ok or not sql:
            print(f"[SKIP] chart='{title}' po {3} probach — pomijam")
            continue
        # Tytul obiecuje "ostatnie X miesiecy", a zaakceptowany SQL nie ma zadnego WHERE
        # (np. retry po _RELATIVE_DATE_FILTER usunal filtr) -> usun fraze z tytulu.
        if "where" not in sql.lower() and _RELATIVE_PERIOD_IN_TITLE.search(title):
            title = _RELATIVE_PERIOD_IN_TITLE.sub("", title).strip(" ,–-") or (g.prompt or goal)[:60].strip()
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
    # Ścieżka GŁÓWNA: bezpośrednie API Metabase — tylko ona obsługuje filtr dat
    # (workflow n8n buduje dashboard bez filtra). n8n zostaje jako fallback awaryjny.
    try:
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
    except Exception:
        n8n_r = http.post(N8N_DASHBOARD_URL, json=n8n_payload, timeout=120)
        n8n_r.raise_for_status()
        dash_url = n8n_r.json()["url"]

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


@app.get("/health")
def health_check():
    """Sprawdza dostępność Ollamy, Metabase i PostgreSQL."""
    status = {}

    try:
        r = http.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models_list = [m["name"] for m in r.json().get("models", [])]
        status["ollama"] = {"ok": True, "models": models_list}
    except Exception as e:
        status["ollama"] = {"ok": False, "error": str(e)}

    try:
        r = http.get(f"{METABASE_URL}/api/health", timeout=5)
        status["metabase"] = {"ok": r.status_code == 200}
    except Exception as e:
        status["metabase"] = {"ok": False, "error": str(e)}

    try:
        conn = _pg_conn()
        conn.close()
        status["postgres"] = {"ok": True}
    except Exception as e:
        status["postgres"] = {"ok": False, "error": str(e)}

    all_ok = all(v["ok"] for v in status.values())
    return {"status": "ok" if all_ok else "degraded", "services": status}


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
    return {"id": u.id, "email": u.email, "token": _create_token(u.id, u.email)}


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
    return {"id": u.id, "email": u.email, "token": _create_token(u.id, u.email)}


class DescribeIn(BaseModel):
    schema_text: str


class EnhanceIn(BaseModel):
    prompt: str
    schema_text: str
    description: str = ""
    clarify_question: str = ""
    clarify_answer: str = ""


class ClarifyIn(BaseModel):
    goal: str
    schema_text: str
    description: str = ""


class PromptsIn(BaseModel):
    prompts: dict[str, str]


def _has_cjk(text: str) -> bool:
    """Zwraca True jeśli tekst zawiera znaki chińskie/japońskie/koreańskie lub cyrylicę.

    Model potrafi wtrącić pojedyncze obce znaki w polski tekst (np. 'Wключaj') —
    traktujemy cyrylicę tak samo jak CJK."""
    return bool(re.search(r'[一-鿿぀-ゟ゠-ヿ가-힯а-яА-ЯёЁ]', text))


@app.post("/enhance-prompt")
def enhance_prompt(body: EnhanceIn, _: int = Depends(verify_token)):
    # Opcjonalne doprecyzowanie z kroku clarify — pytanie modelu + odpowiedź użytkownika.
    # Trafia do szablonu tylko gdy oba pola są wypełnione (samo pytanie bez odpowiedzi nic nie wnosi).
    clarification = ""
    if body.clarify_question.strip() and body.clarify_answer.strip():
        clarification = (
            f"DOPRECYZOWANIE OD UZYTKOWNIKA (MUSISZ uwzglednic w przepisanym zapytaniu): "
            f"na pytanie '{body.clarify_question.strip()}' uzytkownik odpowiedzial: "
            f"'{body.clarify_answer.strip()}'"
        )
    enhance_prompt_text = PROMPTS["enhance_prompt"].format(
        schema_text=body.schema_text,
        description=body.description,
        prompt=body.prompt,
        clarification=clarification,
    )
    try:
        r = http.post(f"{OLLAMA_URL}/api/generate",
                      json={"model": OLLAMA_MODEL, "prompt": enhance_prompt_text, "stream": False},
                      timeout=90)
        r.raise_for_status()
        enhanced = (r.json().get("response") or "").strip()

        # Jeśli model wygenerował obce znaki (CJK/cyrylica) — odrzuć i zwróć oryginał
        # (z doklejoną odpowiedzią z doprecyzowania, żeby intencja użytkownika nie przepadła)
        if _has_cjk(enhanced):
            fallback = body.prompt
            if body.clarify_answer.strip():
                fallback = f"{fallback.strip()} {body.clarify_answer.strip()}"
            return {"enhanced": fallback}

        # Jeśli model mimo wszystko wygenerował SQL — bierzemy tylko linie bez słów kluczowych SQL
        if any(kw in enhanced.upper() for kw in ("SELECT ", "FROM ", "JOIN ", "WHERE ", "GROUP BY")):
            lines = [l for l in enhanced.splitlines() if not any(
                kw in l.upper() for kw in ("SELECT", "FROM", "JOIN", "WHERE", "GROUP BY", "ORDER BY", "LIMIT", "HAVING"))]
            enhanced = " ".join(lines).strip() or body.prompt

        # Jeśli user nie podał żadnej liczby, a model mimo instrukcji dopisał "TOP 20" itp. —
        # model ma silny wyuczony nawyk wymyslania liczby przy słowie "top", niezależny od promptu.
        if not re.search(r'\d', body.prompt) and re.search(r'(?i)\btop\s+\d+\b', enhanced):
            enhanced = re.sub(r'(?i)\btop\s+\d+\b', 'TOP', enhanced)

        # Model czasem ignoruje doprecyzowanie mimo instrukcji w prompcie (silny prior 7B).
        # Porównujemy po rdzeniach słów (pierwsze 5 znaków — radzi sobie z polską odmianą,
        # np. 'miesięcznym' vs 'miesięczny'); jeśli nic z odpowiedzi użytkownika nie trafiło
        # do wyniku — doklejamy ją, żeby intencja nie zginęła.
        answer = body.clarify_answer.strip()
        if enhanced and answer:
            stems = [w[:5] for w in re.findall(r'\w{4,}', answer.lower())]
            if stems and not any(s in enhanced.lower() for s in stems):
                enhanced = f"{enhanced.rstrip('.')}. Uwzględnij: {answer}."

        return {"enhanced": enhanced or body.prompt}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/describe-schema")
def describe_schema(body: DescribeIn, _: int = Depends(verify_token)):
    prompt = PROMPTS["describe_schema"].format(schema_text=body.schema_text)
    try:
        r = http.post(f"{OLLAMA_URL}/api/generate",
                      json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                      timeout=300)
        r.raise_for_status()
        desc = (r.json().get("response") or "").strip()
        if not desc:
            raise HTTPException(status_code=500, detail="Model zwrócił pustą odpowiedź")

        # Model czasem wtraca pojedyncze chinskie/japonskie/koreanskie znaki w polskim tekscie — usun je.
        if _has_cjk(desc):
            desc = re.sub(r'[一-鿿぀-ゟ゠-ヿ가-힯а-яА-ЯёЁ]+', '', desc)
            desc = re.sub(r'\s+([.,;:])', r'\1', desc)
            desc = re.sub(r'[ \t]{2,}', ' ', desc).strip()

        return {"description": desc}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[describe-schema ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/clarify-prompt")
def clarify_prompt(body: ClarifyIn, _: int = Depends(verify_token)):
    """Opcjonalny krok: model zwraca jedno pytanie doprecyzowujace cel, albo None jesli cel jest juz jasny."""
    prompt = PROMPTS["clarify_prompt"].format(
        goal=body.goal, schema_text=body.schema_text, description=body.description,
    )
    try:
        out = _ollama_json(prompt, timeout=90)
    except (OllamaUnavailableError, OllamaResponseError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    question = out.get("question") if isinstance(out, dict) else None
    return {"question": question or None}


@app.get("/prompts")
def get_prompts(_: int = Depends(verify_token)):
    return PROMPTS


@app.put("/prompts")
def update_prompts(body: PromptsIn, _: int = Depends(verify_token)):
    global PROMPTS
    updated = dict(PROMPTS)
    for key, text in body.prompts.items():
        if key not in PROMPTS:
            raise HTTPException(status_code=400, detail=f"Nieznany klucz promptu: '{key}'")
        required = _PROMPT_PLACEHOLDERS.get(key, set())
        found = {field for _, field, _, _ in Formatter().parse(text) if field}
        missing = required - found
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Prompt '{key}': brakuje wymaganych placeholderow {sorted(missing)}",
            )
        updated[key] = text
    with open(_PROMPTS_PATH, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
    PROMPTS = updated
    return {"ok": True, "prompts": PROMPTS}


MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB (northwind.db z pliki_testowe ma ~24MB)


@app.post("/upload")
async def upload_database(user_id: int = Form(...), file: UploadFile = File(...),
                          db: Session = Depends(database.get_db),
                          token_user_id: int = Depends(verify_token)):
    user_id = token_user_id  # nie ufaj user_id z formularza — właścicielem jest zalogowany user
    orig_name = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(orig_name)[1].lower()
    # nazwa pliku na dysku NIE pochodzi od użytkownika (path traversal) — losowy identyfikator
    tmp_path = f"/tmp/_upload_{uuid.uuid4().hex}{ext}"

    size = 0
    with open(tmp_path, "wb") as buf:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                buf.close()
                os.remove(tmp_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"Plik za duży — limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
            buf.write(chunk)

    # Wczytaj wszystkie tabele do słownika DataFrame-ów
    dfs: dict = {}
    try:
        if ext in (".db", ".sqlite", ".sqlite3"):
            sq = sqlite3.connect(tmp_path)
            try:
                cur = sq.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                for (tname,) in cur.fetchall():
                    dfs[tname] = pd.read_sql(f'SELECT * FROM "{tname}"', sq)
            finally:
                sq.close()
        elif ext == ".csv":
            stem = re.sub(r"[^\w]", "_", os.path.splitext(orig_name)[0])
            dfs[stem] = pd.read_csv(tmp_path, encoding="utf-8-sig")
        elif ext in (".xlsx", ".xls"):
            xls = pd.ExcelFile(tmp_path)
            for sheet in xls.sheet_names:
                tname = re.sub(r"[^\w]", "_", sheet).strip("_").lower() or "sheet"
                dfs[tname] = pd.read_excel(xls, sheet_name=sheet)
        else:
            raise HTTPException(status_code=400, detail="Nieobsługiwany format pliku.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Nie udało się odczytać pliku: {e}")
    finally:
        os.remove(tmp_path)

    if not dfs:
        raise HTTPException(status_code=400, detail="Plik nie zawiera żadnych danych.")

    schema_name = _sanitize_schema(user_id, orig_name)

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
    # Rzutuj kolumny tekstowe z datami na TIMESTAMP bezpośrednio w PostgreSQL.
    # Kolumna jest kandydatem gdy: nazwa zawiera wskazówkę (EN/PL, np. 'data_zamowienia')
    # LUB próbka wartości wygląda jak data ISO (np. '2024-01-31'). Nieudane rzutowanie
    # (wartości nie są datami) jest bezpiecznie wycofywane — kolumna zostaje tekstem.
    date_hints = {'date', 'time', 'created', 'updated', 'timestamp', 'data', 'czas'}
    iso_date_re = re.compile(r'^\s*\d{4}-\d{2}-\d{2}')
    from sqlalchemy import text as sa_text2
    with engine.connect() as conn:
        for safe_t in [re.sub(r"[^\w]", "_", t).strip("_").lower() or "data" for t in dfs.keys()]:
            rows = conn.execute(sa_text2(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND data_type = 'text'"),
                {"s": schema_name, "t": safe_t}).fetchall()
            for (col,) in rows:
                candidate = any(h in col.lower() for h in date_hints)
                if not candidate:
                    try:
                        sample = conn.execute(sa_text2(
                            f'SELECT "{col}" FROM "{schema_name}"."{safe_t}" '
                            f'WHERE "{col}" IS NOT NULL LIMIT 5')).fetchall()
                        candidate = bool(sample) and all(
                            iso_date_re.match(str(v[0])) for v in sample)
                    except Exception:
                        conn.rollback()
                if candidate:
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
    rec = models.Database(user_id=user_id, name=orig_name,
                          file_path=schema_name, schema_json=compact_schema)
    db.add(rec); db.commit(); db.refresh(rec)
    return {"id": rec.id, "name": rec.name, "message": "Baza wgrana pomyślnie!"}


@app.get("/users/{user_id}/databases")
def get_user_databases(user_id: int, db: Session = Depends(database.get_db),
                       token_user_id: int = Depends(verify_token)):
    if user_id != token_user_id:
        raise HTTPException(status_code=403, detail="Brak dostępu do cudzych zasobów")
    rows = db.query(models.Database).filter_by(user_id=user_id).order_by(
        models.Database.uploaded_at.desc()).all()
    result = []
    for r in rows:
        try:
            full = get_db_schema(r.file_path)
            rich = {t: [{"name": c["name"], "type": c["type"]} for c in info["columns"]]
                    for t, info in full.items()}
        except Exception:
            plain = r.schema_json or {}
            rich = {t: [{"name": c, "type": "unknown"} for c in cols]
                    for t, cols in plain.items()}
        result.append({"id": r.id, "name": r.name, "file_path": r.file_path, "schema": rich})
    return result


@app.delete("/databases/{db_id}")
def delete_database(db_id: int, db: Session = Depends(database.get_db),
                    token_user_id: int = Depends(verify_token)):
    rec = db.query(models.Database).filter_by(id=db_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Baza nie istnieje")
    if rec.user_id != token_user_id:
        raise HTTPException(status_code=403, detail="Brak dostępu do cudzych zasobów")
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
def get_user_queries(user_id: int, db: Session = Depends(database.get_db),
                     token_user_id: int = Depends(verify_token)):
    if user_id != token_user_id:
        raise HTTPException(status_code=403, detail="Brak dostępu do cudzych zasobów")
    rows = db.query(models.Query).filter_by(user_id=user_id).order_by(
        models.Query.created_at.desc()).limit(20).all()
    return [{"id": r.id, "prompt": r.prompt_nl, "sql": r.generated_sql,
             "status": r.status, "retry_count": r.retry_count} for r in rows]


N8N_ORCHESTRATOR_URL = os.getenv("N8N_ORCHESTRATOR_URL", "http://n8n_local:5678/webhook/create-dashboard")


def _generate_via_n8n_orchestrator(g, db, db_id):
    """Eksperyment 'n8n jako orchestrator' (patrz plan resilient-prancing-bentley):
    n8n prowadzi caly control-flow plan+SQL+walidacja+Metabase, wolajac cienkie
    endpointy /internal/... zamiast duplikowac logike z _generate_multichart."""
    payload = {
        "prompt": g.prompt,
        "schema_text": g.schema_text,
        "chart_type": g.chart_type,
        "description": g.description,
        "db_path": g.db_path,
    }
    r = http.post(N8N_ORCHESTRATOR_URL, json=payload, timeout=max(g.n8n_timeout, 300))
    r.raise_for_status()
    data = r.json()
    dash_url = data.get("url")
    if not dash_url:
        raise Exception(f"n8n orchestrator nie zwrocil url dashboardu: {data}")
    rec = models.Query(user_id=g.user_id, database_id=db_id, prompt_nl=_full_prompt(g),
                       generated_sql=json.dumps({"dashboard_url": dash_url}, ensure_ascii=False),
                       status="success", retry_count=0)
    db.add(rec); db.commit()
    return {"status": "success", "metabase": {"url": dash_url}}


@app.post("/generate")
def generate(g: GenerateIn, db: Session = Depends(database.get_db),
             token_user_id: int = Depends(verify_token)):
    g.user_id = token_user_id  # nie ufaj user_id z body — historia zapytań idzie na konto z tokenu
    db_obj = db.query(models.Database).filter_by(file_path=g.db_path).first()
    db_id = db_obj.id if db_obj else 1

    # EKSPERYMENT: n8n jako jedyna sciezka (nie fallback) — zamiast _generate_multichart.
    # _generate_multichart zostaje w pliku NIETKNIETA jako martwy kod / punkt odniesienia.
    try:
        return _generate_via_n8n_orchestrator(g, db, db_id)
    except Exception as e:
        rec = models.Query(user_id=g.user_id, database_id=db_id, prompt_nl=_full_prompt(g),
                           generated_sql="", status="error", retry_count=0)
        db.add(rec); db.commit()
        return {"status": "error", "error": f"n8n orchestrator error: {e}"}


# ============================================================================
# Wewnetrzne endpointy dla eksperymentu "n8n jako orchestrator" (patrz plan
# resilient-prancing-bentley). Cienkie wrappery na sprawdzona logike z
# _generate_multichart — n8n prowadzi control-flow (wolania Ollamy, retry,
# petle), Python tylko formatuje prompty i waliduje SQL, zeby nie duplikowac
# (i nie rozjechac) guardow wielokrotnie naprawianych w poprzednich sesjach.
# Bez JWT: wolane tylko wewnatrz sieci dockerowej przez n8n.
# ============================================================================

class InternalPlanPromptIn(BaseModel):
    goal: str
    chart_type: str = ""
    description: str = ""
    schema_text: str = ""


@app.post("/internal/plan-prompt")
def internal_plan_prompt(body: InternalPlanPromptIn):
    requested_types = _parse_requested_charts(body.chart_type)
    n_charts = len(requested_types) if requested_types else (_parse_chart_count(body.chart_type) or 3)
    if requested_types:
        types_instruction = (
            f"UZYTKOWNIK ZADA DOKLADNIE {n_charts} WYKRESOW W TEJ KOLEJNOSCI: "
            + ", ".join(f"({i+1}) chart_type={t}" for i, t in enumerate(requested_types))
            + "\nMUSISZ wygenerowac DOKLADNIE tyle elementow i uzyc DOKLADNIE tych typow chart_type."
        )
    else:
        types_instruction = "Wygeneruj 3-4 roznorodne wykresy (bar, line, pie, table)."
    prompt = PROMPTS["plan_prompt"].format(
        types_instruction=types_instruction,
        goal=body.goal,
        chart_type=body.chart_type,
        description=body.description,
        schema_text=body.schema_text,
    )
    return {"prompt": prompt, "n_charts": n_charts, "requested_types": requested_types}


class InternalProcessPlanIn(BaseModel):
    raw_plan: dict | list
    requested_types: list[str] = []
    n_charts: int = 3
    user_prompt: str = ""
    is_retry: bool = False


@app.post("/internal/process-plan")
def internal_process_plan(body: InternalProcessPlanIn):
    raw_plan = body.raw_plan
    raw_specs = [s for s in (raw_plan.get("charts", []) if isinstance(raw_plan, dict) else []) if isinstance(s, dict)]
    # Na pierwszym przebiegu (nie retry): jezyk obcy w planie -> sygnalizuj n8n zeby
    # zapytalo Ollame jeszcze raz z ostrzezeniem (main.py:668-677). Na przebiegu retry
    # uzywamy tego co przyszlo, nawet jesli nadal obce — tytul i tak ma fallback nizej
    # (main.py:709-712), a Python tez nie sprawdza jezyka po raz drugi.
    if not body.is_retry:
        need_retry = bool(raw_specs) and any(
            _is_foreign_language(f"{s.get('title', '')} {s.get('goal', '')}") for s in raw_specs)
        if need_retry:
            return {"specs": [], "need_retry": True}
    specs = []
    for i, spec in enumerate(raw_specs[:body.n_charts]):
        if body.requested_types and i < len(body.requested_types):
            spec["chart_type"] = body.requested_types[i]
        title = spec.get("title") or ""
        goal = spec.get("goal") or body.user_prompt
        if not title or title.lower().startswith("wykres"):
            title = goal[:60].strip()
        if _is_foreign_language(title):
            title = (body.user_prompt or goal)[:60].strip()
        specs.append({"title": title, "goal": goal, "chart_type": spec.get("chart_type")})
    return {"specs": specs, "need_retry": False}


class InternalSqlPromptIn(BaseModel):
    goal: str
    chart_type: str = ""
    schema_text: str = ""
    prev_sql: str = ""
    prev_err: str = ""


@app.post("/internal/sql-prompt")
def internal_sql_prompt(body: InternalSqlPromptIn):
    ctype = (body.chart_type or "").strip().lower() or None
    chart_hint = _CHART_HINTS.get(ctype, "")
    prompt = PROMPTS["sql_prompt"].format(chart_hint=chart_hint, goal=body.goal, schema_text=body.schema_text)
    if body.prev_err:
        prompt += PROMPTS["sql_retry_suffix"].format(sql=body.prev_sql, err=body.prev_err)
    return {"prompt": prompt}


class InternalProcessSqlIn(BaseModel):
    schema_name: str
    chart_type: str = ""
    raw_sql: str


@app.post("/internal/process-sql-attempt")
def internal_process_sql_attempt(body: InternalProcessSqlIn):
    ctype = (body.chart_type or "").strip().lower() or None
    sql = _clean_sql(body.raw_sql)
    if _RELATIVE_DATE_FILTER.search(sql):
        return {"ok": False, "sql": sql,
                "error": ("SQL uzywa CURRENT_DATE/NOW() z INTERVAL do filtrowania WHERE — to zwroci PUSTY "
                          "wynik, bo dane moga byc z innego okresu niz biezaca data serwera. Usun ten "
                          "filtr calkowicie i pokaz PELNY zakres dat z tabeli, bez WHERE na kolumnie daty."),
                "columns": [], "sample": []}
    ok, verr, cols, sample = _run_and_validate(body.schema_name, sql, ctype)
    return {"ok": ok, "sql": sql, "error": verr, "columns": cols, "sample": sample}


class InternalFinalizeChartIn(BaseModel):
    title: str
    sql: str
    chart_type: str = ""
    columns: list = []
    sample: list = []
    user_prompt: str = ""


@app.post("/internal/finalize-chart")
def internal_finalize_chart(body: InternalFinalizeChartIn):
    ctype = (body.chart_type or "").strip().lower() or None
    title = body.title
    if "where" not in body.sql.lower() and _RELATIVE_PERIOD_IN_TITLE.search(title):
        title = _RELATIVE_PERIOD_IN_TITLE.sub("", title).strip(" ,–-") or (body.user_prompt or "")[:60].strip()
    display = ctype if ctype in _VALID_DISPLAYS else _infer_display(body.columns, body.sample)
    return {"title": title, "display": display}


@app.get("/internal/date-column")
def internal_date_column(schema_name: str):
    cols = _find_date_columns(schema_name)
    return {"date_column": cols[0] if cols else None, "date_columns": cols}
