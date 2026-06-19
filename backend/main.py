import os
import re
import time
import sqlite3
import shutil
import json
from typing import Optional

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


def get_db_schema(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cursor.fetchall()]
    schema = {}
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        cols = cursor.fetchall()
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        schema[table] = {
            "columns": [{"name": c[1], "type": c[2], "pk": bool(c[5])} for c in cols],
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


def _run_and_validate(db_path, sql):
    """Sprawdza SQL na wgranej bazie i zwraca (ok, error, kolumny, probka)."""
    if not db_path or not os.path.exists(db_path):
        return True, None, [], []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute(sql)
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
    if "słup" in t or "slup" in t or "bar" in t:
        hits.add("bar")
    if "tabel" in t or "table" in t:
        hits.add("table")
    return next(iter(hits)) if len(hits) == 1 else None


def _viz_settings(display, columns):
    if not columns:
        return {}
    if display in ("bar", "line", "area", "row"):
        return {"graph.dimensions": [columns[0]],
                "graph.metrics": columns[1:] if len(columns) > 1 else [columns[0]]}
    if display == "pie":
        return {"pie.dimension": columns[0],
                "pie.metric": columns[1] if len(columns) > 1 else columns[0]}
    return {}


def _get_metabase_token() -> str:
    r = http.post(f"{METABASE_URL}/api/session",
                  json={"username": METABASE_USER, "password": METABASE_PASSWORD})
    r.raise_for_status()
    return r.json()["id"]


def _ensure_metabase_db(token: str, db_path: str) -> int:
    headers = {"X-Metabase-Session": token}
    r = http.get(f"{METABASE_URL}/api/database", headers=headers)
    r.raise_for_status()
    dbs = r.json()
    db_list = dbs.get("data", dbs) if isinstance(dbs, dict) else dbs
    db_name = os.path.basename(db_path)

    # 1. Czy baza o tej nazwie jest juz podlaczona?
    for db in db_list:
        if db.get("name") == db_name:
            return db["id"]

    # 2. Nie ma -> dodaj ja automatycznie przez API Metabase.
    #    Metabase musi widziec ten sam plik pod METABASE_DB_DIR (wspolny wolumen).
    mb_file = os.path.join(METABASE_DB_DIR, db_name)
    try:
        cr = http.post(f"{METABASE_URL}/api/database", headers=headers,
                       json={"engine": "sqlite", "name": db_name,
                             "details": {"db": mb_file}, "is_full_sync": True})
        cr.raise_for_status()
        new_id = cr.json()["id"]
        # Best-effort sync schematu (zapytania native dzialaja od razu, to pomaga GUI).
        try:
            http.post(f"{METABASE_URL}/api/database/{new_id}/sync_schema", headers=headers)
        except Exception:
            pass
        return new_id
    except Exception:
        pass

    # 3. Fallback jak wczesniej: pierwsza nie-systemowa baza SQLite, w ostatecznosci id=2.
    for db in db_list:
        if db.get("engine") == "sqlite" and not db.get("is_sample"):
            return db["id"]
    return 2


def create_metabase_dashboard(token: str, name: str) -> int:
    r = http.post(f"{METABASE_URL}/api/dashboard",
                  headers={"X-Metabase-Session": token}, json={"name": name})
    r.raise_for_status()
    return r.json()["id"]


def create_metabase_card(token, db_id, name, sql, display, columns):
    payload = {
        "name": name,
        "dataset_query": {"database": db_id, "type": "native", "native": {"query": sql}},
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
    plan_prompt = (
        "Jestes analitykiem danych. Rozbij cel na 2-4 OSOBNE wykresy, kazdy o innym celu.\n"
        "Zwroc WYLACZNIE JSON: {\"charts\":[{\"title\":\"...\",\"chart_type\":\"bar|line|pie|table\",\"goal\":\"co pokazac\"}]}\n"
        "Nie pisz SQL.\n"
        f"CEL: {g.prompt}\nWYTYCZNE UKLADU: {g.chart_type}\n"
        f"OPIS DANYCH: {g.description}\nSCHEMAT: {g.schema_text}"
    )
    plan = _ollama_json(plan_prompt, g.n8n_timeout)
    specs = [s for s in (plan.get("charts", []) if isinstance(plan, dict) else []) if isinstance(s, dict)][:4]
    if not specs:
        return None

    charts = []
    total_retries = 0
    for spec in specs:
        title = spec.get("title") or "Wykres"
        goal = spec.get("goal") or g.prompt
        ctype = (spec.get("chart_type") or "").strip().lower() or None
        sql, ok, cols, sample, err = "", False, [], [], None
        for attempt in range(2):
            sql_prompt = (
                "Wygeneruj JEDEN poprawny SQL (dialekt SQLite) dla celu ponizej.\n"
                "Uzyj WYLACZNIE tabel i kolumn ze schematu. Zwroc WYLACZNIE JSON: {\"sql\":\"...\"}\n"
                f"CEL WYKRESU: {goal}\nSCHEMAT: {g.schema_text}"
            )
            if err:
                sql_prompt += f"\nPOPRZEDNI SQL nie zadzialal: {sql}\nBLAD: {err}\nPopraw."
            try:
                out = _ollama_json(sql_prompt, g.n8n_timeout)
                sql = ((out.get("sql") if isinstance(out, dict) else "") or "").strip().rstrip(";")
            except Exception as e:
                err = f"LLM: {e}"; total_retries += 1; continue
            ok, verr, cols, sample = _run_and_validate(g.db_path, sql)
            if ok and sql:
                break
            err = verr or "pusty SQL"; total_retries += 1
        if not ok or not sql:
            continue
        display = ctype if ctype in ("bar", "line", "pie", "table", "area", "row", "scatter") \
            else _infer_display(cols, sample)
        charts.append((title, sql, display, cols))

    if not charts:
        return None

    mb_token = _get_metabase_token()
    mb_db_id = _ensure_metabase_db(mb_token, g.db_path)
    dash_id = create_metabase_dashboard(mb_token, "Dashboard Analityczny AI")
    dashcards = []
    for idx, (title, sql, display, cols) in enumerate(charts):
        card_id = create_metabase_card(mb_token, mb_db_id, title, sql, display, cols)
        dashcards.append({"id": -(idx + 1), "card_id": card_id,
                          "row": idx * 8, "col": 0, "size_x": 12, "size_y": 8})
    r = http.put(f"{METABASE_URL}/api/dashboard/{dash_id}/cards",
                 headers={"X-Metabase-Session": mb_token}, json={"cards": dashcards})
    r.raise_for_status()
    dash_url = publish_metabase_dashboard(mb_token, dash_id)

    pretty = json.dumps(
        {"dashboard_title": "Dashboard Analityczny AI",
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


@app.post("/upload")
async def upload_database(user_id: int = Form(...), file: UploadFile = File(...),
                          db: Session = Depends(database.get_db)):
    file_location = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    schema = get_db_schema(file_location)
    compact_schema = {t: [c["name"] for c in info["columns"]] for t, info in schema.items()}
    rec = models.Database(user_id=user_id, name=file.filename,
                          file_path=file_location, schema_json=compact_schema)
    db.add(rec); db.commit(); db.refresh(rec)
    return {"id": rec.id, "name": rec.name, "message": "Baza wgrana pomyślnie!"}


@app.get("/users/{user_id}/databases")
def get_user_databases(user_id: int, db: Session = Depends(database.get_db)):
    rows = db.query(models.Database).filter_by(user_id=user_id).order_by(
        models.Database.uploaded_at.desc()).all()
    return [{"id": r.id, "name": r.name, "file_path": r.file_path, "schema": r.schema_json}
            for r in rows]


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
                                  "row": idx * 8, "col": 0, "size_x": 12, "size_y": 8})
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
