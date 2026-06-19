import streamlit as st
import requests
import json
import time
import sqlite3
import pandas as pd
import os
from pathlib import Path
# ── Konfiguracja strony ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sales Report Generator",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
# ── Stałe ────────────────────────────────────────────────────────────────────
N8N_WEBHOOK_URL = "http://n8n_local:5678/webhook/sales-report"
BACKEND_URL = "http://fastapi_backend:8000"
DB_DIR = Path("/app/uploaded_dbs")
DB_DIR.mkdir(exist_ok=True)
# ── Funkcje schematu ──────────────────────────────────────────────────────────
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
def schema_to_text(schema: dict) -> str:
    lines = ["Tabele (używaj TYLKO tych):"]
    for table, info in schema.items():
        cols = ", ".join(c["name"] for c in info["columns"])
        lines.append(f"- {table}({cols})")
    return "\n".join(lines)
# ── Komunikacja z backendem (FastAPI) ─────────────────────────────────────────
def backend_login(email: str):
    try:
        r = requests.post(f"{BACKEND_URL}/users",
                          json={"email": email, "password_hash": "x"}, timeout=10)
        if r.ok:
            return r.json()["id"]
    except Exception:
        return None
    return None
def backend_register_db(user_id, name, file_path, schema):
    try:
        r = requests.post(f"{BACKEND_URL}/databases",
                          json={"user_id": user_id, "name": name,
                                "file_path": file_path, "schema_json": schema}, timeout=10)
        if r.ok:
            return r.json()["id"]
    except Exception:
        return None
    return None
def backend_history(user_id):
    if not user_id:
        return []
    try:
        r = requests.get(f"{BACKEND_URL}/users/{user_id}/queries", timeout=10)
        if r.ok:
            return r.json()
    except Exception:
        return []
    return []
# ── Session state ─────────────────────────────────────────────────────────────
for key in ["db_path", "db_schema", "db_name",
            "user_id", "user_email", "database_id", "registered_db_name"]:
    if key not in st.session_state:
        st.session_state[key] = None
if st.session_state["user_id"] is None:
    st.session_state["user_id"] = backend_login("test@test.pl")
    st.session_state["user_email"] = "test@test.pl"
# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("👤 Profil")
    email_in = st.text_input("E-mail", value=st.session_state.get("user_email") or "test@test.pl")
    if st.button("Zaloguj / przełącz", use_container_width=True):
        uid = backend_login(email_in)
        if uid:
            st.session_state["user_id"] = uid
            st.session_state["user_email"] = email_in
            st.session_state["database_id"] = None
            st.session_state["registered_db_name"] = None
            st.success(f"Zalogowano (id={uid})")
        else:
            st.error("Backend niedostępny")
    if st.session_state.get("user_id"):
        st.caption(f"Zalogowany: {st.session_state['user_email']} (id={st.session_state['user_id']})")
    else:
        st.caption("Niezalogowany — historia nie będzie zapisywana.")
    st.divider()
    st.header("Ustawienia")
    n8n_url = st.text_input("URL webhooka n8n", value=N8N_WEBHOOK_URL)
    timeout = st.slider("Timeout (sekundy)", 30, 180, 90)
    st.divider()
    st.subheader("Wgraj bazę danych")
    tab_db, tab_csv = st.tabs(["SQLite .db", "Pliki CSV"])
    with tab_db:
        uploaded_db = st.file_uploader("Plik .db", type=["db", "sqlite", "sqlite3"])
        if uploaded_db:
            path = str(DB_DIR / uploaded_db.name)
            with open(path, "wb") as f:
                f.write(uploaded_db.getbuffer())
            st.session_state["db_path"] = path
            st.session_state["db_name"] = uploaded_db.name
            st.session_state["db_schema"] = get_db_schema(path)
            st.success(f"Załadowano: {uploaded_db.name}")
    with tab_csv:
        uploaded_csvs = st.file_uploader("Pliki CSV", type=["csv"], accept_multiple_files=True)
        if uploaded_csvs:
            path = str(DB_DIR / "uploaded.db")
            if os.path.exists(path):
                os.remove(path)
            conn = sqlite3.connect(path)
            for f in uploaded_csvs:
                table = Path(f.name).stem.replace("-", "_").replace(" ", "_")
                pd.read_csv(f).to_sql(table, conn, if_exists="replace", index=False)
                st.success(f"{f.name} → tabela `{table}`")
            conn.close()
            st.session_state["db_path"] = path
            st.session_state["db_name"] = "uploaded.db"
            st.session_state["db_schema"] = get_db_schema(path)
    if st.session_state["db_schema"]:
        st.divider()
        st.subheader("Struktura bazy")
        for table, info in st.session_state["db_schema"].items():
            with st.expander(f"{table} ({info['row_count']} wierszy)"):
                df_cols = pd.DataFrame([
                    {"Kolumna": c["name"], "Typ": c["type"], "PK": "✓" if c["pk"] else ""}
                    for c in info["columns"]
                ])
                st.dataframe(df_cols, hide_index=True, use_container_width=True)
    st.divider()
    st.subheader("🕘 Historia")
    hist = backend_history(st.session_state.get("user_id"))
    if hist:
        for h in hist[:10]:
            icon = "✅" if h.get("status") == "success" else "❌"
            with st.expander(f"{icon} {(h.get('prompt') or '')[:38]}"):
                st.code(h.get("sql") or "(brak SQL)", language="sql")
                st.caption(f"status: {h.get('status')} · retry: {h.get('retry_count')}")
    else:
        st.caption("Brak zapisanych zapytań.")
    st.divider()
    st.caption("Streamlit (GUI) → FastAPI (logika) → n8n → Ollama")
# ── Główna zawartość ──────────────────────────────────────────────────────────
st.title("📊 Sales Report Generator")
st.caption("Wgraj bazę i przejdź przez kreator: opisz dane → podaj cel → wybierz wykres.")
if not st.session_state["db_schema"]:
    st.info("Wgraj bazę danych w panelu po lewej (.db lub pliki .csv) żeby zacząć.")
    st.stop()
db_name = st.session_state["db_name"]
schema = st.session_state["db_schema"]
tables_count = len(schema)
total_rows = sum(t["row_count"] for t in schema.values())
st.success(f"Aktywna baza: **{db_name}** — {tables_count} tabel, {total_rows:,} wierszy łącznie")
# Rejestracja aktywnej bazy w backendzie (dla FK queries)
if st.session_state.get("user_id") and st.session_state.get("registered_db_name") != db_name:
    compact_schema = {t: [c["name"] for c in info["columns"]] for t, info in schema.items()}
    st.session_state["database_id"] = backend_register_db(
        st.session_state["user_id"], db_name, st.session_state["db_path"], compact_schema)
    st.session_state["registered_db_name"] = db_name
# ── Kreator raportu (łańcuch promptów) ────────────────────────────────────────
st.markdown("### Kreator raportu")
st.text_area(
    "1️⃣ Opisz swoją bazę — co przedstawiają dane?",
    placeholder="np. Dane sklepu internetowego: zamówienia, klienci, produkty. Tabela orders to zamówienia...",
    height=80,
    key="desc_input",
)
st.text_area(
    "2️⃣ Co chcesz osiągnąć? (cel / pytanie biznesowe)",
    placeholder="np. Pokaż top 10 kategorii produktów według przychodu",
    height=80,
    key="query_input",
)
chart_type = st.selectbox(
    "3️⃣ Jaki wykres?",
    ["Auto", "Słupkowy", "Liniowy", "Tabela"],
    key="chart_input",
)
col1, col2 = st.columns([1, 4])
with col1:
    generate = st.button("Generuj raport", type="primary", use_container_width=True)
with col2:
    if st.button("Wyczyść", use_container_width=True):
        st.session_state["query_input"] = ""
        st.session_state["desc_input"] = ""
        st.rerun()
st.divider()
# ── Generowanie: frontend tylko ZLECA zadanie backendowi ──────────────────────
if generate:
    goal = st.session_state.get("query_input", "").strip()
    if not goal:
        st.warning("Wpisz cel w kroku 2.")
        st.stop()
    schema_text = schema_to_text(schema)
    with st.spinner("Backend pracuje: łańcuch promptów → n8n → Ollama → SQL → wykonanie (z retry)..."):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/generate",
                json={
                    "user_id": st.session_state.get("user_id"),
                    "database_id": st.session_state.get("database_id"),
                    "prompt": goal,
                    "description": st.session_state.get("desc_input", "").strip(),
                    "chart_type": st.session_state.get("chart_input", "Auto"),
                    "schema_text": schema_text,
                    "db_path": st.session_state["db_path"],
                    "tables": list(schema.keys()),
                    "n8n_url": n8n_url,
                    "n8n_timeout": timeout,
                    "max_retries": 3,
                },
                timeout=timeout * 4 + 30,
            )
        except requests.exceptions.RequestException as e:
            st.error(f"Backend niedostępny: {e}")
            st.stop()
    if not resp.ok:
        st.error(f"Backend zwrócił {resp.status_code}: {resp.text}")
        st.stop()
    out = resp.json()
    sql_text = out.get("sql") or ""
    status_val = out.get("status")
    retry_count = out.get("retry_count", 0)
    if retry_count > 0 and status_val == "success":
        st.info(f"SQL nie zadziałał za pierwszym razem — backend poprawił go automatycznie (próby: {retry_count}).")
    st.subheader("Wynik")
    with st.expander("Wygenerowane zapytanie SQL", expanded=True):
        st.code(sql_text or "(brak SQL)", language="sql")
    if status_val == "success":
        rows = out.get("rows", [])
        if not rows:
            st.info("Zapytanie nie zwróciło wyników.")
        else:
            df_result = pd.DataFrame(rows)
            st.dataframe(df_result, use_container_width=True)
            chart_choice = st.session_state.get("chart_input", "Auto")
            num_cols = df_result.select_dtypes(include="number").columns.tolist()
            txt_cols = df_result.select_dtypes(exclude="number").columns.tolist()
            if chart_choice != "Tabela" and num_cols:
                x = txt_cols[0] if txt_cols else df_result.columns[0]
                y = num_cols[0]
                chart_data = df_result.set_index(x)[y]
                st.subheader("Wizualizacja")
                if chart_choice == "Liniowy":
                    st.line_chart(chart_data)
                else:
                    st.bar_chart(chart_data)
        st.subheader("Wykres w Metabase (interaktywny)")
        import streamlit.components.v1 as components
        FALLBACK = "http://192.168.0.227:3000/public/dashboard/88a74cb7-fafc-45dd-a0af-11ba8d24a65e"
        mb = out.get("metabase")
        if mb and mb.get("url"):
            st.caption("Wykres utworzony dynamicznie w Metabase dla tego zapytania.")
            components.iframe(mb["url"], height=600, scrolling=True)
        else:
            if mb and mb.get("error"):
                st.warning(f"Metabase API: {mb['error']} — pokazuję dashboard zapasowy.")
            components.iframe(FALLBACK, height=700, scrolling=True)
    else:
        st.error(f"Nie udało się wygenerować poprawnego SQL (próby: {retry_count}).")
        if out.get("error"):
            st.caption(f"Ostatni błąd: {out['error']}")
    with st.expander("Co poszło do LLM (debug)", expanded=False):
        st.code(schema_text)
