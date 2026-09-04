# 01 — Architektura i model danych (deep dive)

> Część serii `docs/`. Przegląd całości: `DOKUMENTACJA.md`.

## 1. Usługi Docker Compose — szczegóły konfiguracji

### 1.1. `fastapi_backend`
- Obraz budowany z `backend/Dockerfile` (python:3.12-slim), uruchamia
  `uvicorn main:app` na porcie 8000.
- **Nie ma wolumenu z kodem** → każda zmiana w `main.py` wymaga
  `docker compose up -d --build fastapi_backend`. Sam restart NIE wystarczy
  (kod jest wpieczony w obraz). To najczęstsza pułapka operacyjna projektu.
- Wolumen `/data` — tam żyje `system.db` (SQLite) i katalog `uploads`
  (dziś już tylko historycznie — dane idą do Postgresa).
- Przy **starcie modułu** (import `main.py`) wykonują się kolejno:
  1. `models.Base.metadata.create_all(...)` — tworzy tabele SQLite, jeśli ich nie ma,
  2. wczytanie `prompts.json` do globalnego słownika `PROMPTS`,
  3. `_ensure_readonly_role()` — idempotentny bootstrap roli read-only w Postgresie.

### 1.2. `n8n` (kontener `n8n_local`)
- Obraz `n8nio/n8n:2.15.1`, port 5678.
- Kluczowe zmienne środowiskowe:
  - `N8N_RUNNERS_ENABLED=true` + `N8N_RUNNERS_MODE=internal` — Code node'y
    wykonują się we własnym procesie n8n. Tryb `external` (osobny kontener
    runnerów) timeoutował Code node'y po 60 s i kładł workflow — dlatego internal.
  - `N8N_ENCRYPTION_KEY` — klucz szyfrowania credentiali w bazie n8n.
- Wolumen `./n8n_config:/home/node/.n8n` — tam jest `database.sqlite` n8n
  (workflow, wykonania, użytkownicy). Katalog jest w `.gitignore`, dlatego
  finalny workflow jest EKSPORTOWANY do repo jako `n8n_orchestrator_workflow.json`.

### 1.3. `ollama`
- Port 11434, wolumen na modele (`ollama_data`).
- Model: `qwen2.5-coder:7b` (4.7 GB). Na GTX 1060 3 GB nie mieści się w VRAM →
  `docker exec ollama ollama ps` pokazuje `83%/17% CPU/GPU` → ~5,6 tokenów/s.
  Wszystkie czasy w ewaluacji trzeba czytać przez ten pryzmat.

### 1.4. `postgres` (kontener `postgres_analytics`)
- postgres:16-alpine, baza `analytics`, bootstrap user `analyst/analyst`
  (właściciel bazy → może tworzyć role, stąd bootstrap read-only działa).
- Wolumen `postgres_data` — dane przeżywają restarty.

### 1.5. `metabase`
- Port 3000; własna wewnętrzna baza (wolumen `metabase-data`).
- Wymaga `JAVA_OPTS=-Xms256m -Xmx1g` (Xms ≤ Xmx, inaczej pętla restartów).
- Konto administracyjne MUSI zgadzać się z `METABASE_USER`/`METABASE_PASSWORD`
  z `main.py` — to backend loguje się do API Metabase, nie użytkownik.

### 1.6. `frontend`
- Dwustopniowy Dockerfile: node:22-alpine (`npm run build` → `dist/`) →
  nginx:alpine serwuje statyki; port 5173→80. `nginx.conf` w repo.
- `API_URL` wskazuje `http://localhost:8000` — frontend gada z backendem
  Z PRZEGLĄDARKI (nie z kontenera), stąd localhost.


## 2. Zmienne konfiguracyjne backendu (wszystkie, z domyślnymi)

| Zmienna | Domyślna | Uwagi |
|---|---|---|
| `METABASE_URL` | `http://metabase:3000` | adres wewnątrz sieci docker |
| `METABASE_PUBLIC_URL` | `http://localhost:3000` | do budowy linków publicznych (widzianych z przeglądarki) |
| `METABASE_USER` / `METABASE_PASSWORD` | (zaszyte w kodzie) | konto admina MB; znane ograniczenie |
| `UPLOAD_DIR` | `/data/uploads` | katalog tymczasowy uploadu (historyczny) |
| `JWT_SECRET` | `zmien-mnie-...` | podpis tokenów; produkcyjnie z env |
| `JWT_EXPIRE_HOURS` | 168 (7 dni) | ważność tokenu |
| `OLLAMA_URL` | `http://ollama:11434` | |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | model planu/opisów/enhance |
| `OLLAMA_SQL_MODEL` | `qwen2.5-coder:7b` | osobna zmienna — pozostałość eksperymentu ze `sqlcoder` (są też osobne prompty `*_sqlcoder`) |
| `N8N_ORCHESTRATOR_URL` | `http://n8n_local:5678/webhook/create-dashboard` | webhook produkcyjny (nie `/webhook-test/`!) |
| `N8N_DASHBOARD_URL` | j.w. | używany przez STARĄ ścieżkę fallback w `_generate_multichart` |
| `PG_HOST/PORT/DB/USER/PASS` | postgres/5432/analytics/analyst/analyst | połączenie „pełne" (import, DDL) |
| `PG_RO_USER/PG_RO_PASS` | readonly/readonly | rola dla SQL-a od LLM |
| Uwaga | | compose przekazuje też `MB_*` — **martwe zmienne**, `main.py` czyta `METABASE_*` |

## 3. Model danych — SQLite `system.db` (SQLAlchemy, `backend/models.py`)

Cztery tabele (deklaratywne modele → `create_all` przy starcie):

```
users
  id            INTEGER PK
  email         STRING UNIQUE NOT NULL
  password_hash STRING NOT NULL      -- hash bcrypt (nigdy plaintext)
  created_at    DATETIME (UTC)

databases                            -- METADANE wgranej bazy (nie dane!)
  id            INTEGER PK
  user_id       FK -> users.id
  name          STRING               -- oryginalna nazwa pliku, np. 'northwind.db'
  file_path     STRING               -- UWAGA: nazwa SCHEMATU Postgresa (u2_northwind),
                                     -- nazwa kolumny jest historyczna (kiedyś ścieżka pliku)
  schema_json   JSON                 -- kompaktowy schemat {tabela: [kolumny]} (fallback)
  uploaded_at   DATETIME

queries                              -- historia generacji
  id            INTEGER PK
  user_id       FK, database_id FK
  prompt_nl     TEXT                 -- pełny prompt (cel + opis + układ) — _full_prompt()
  generated_sql TEXT                 -- JSON z URL-em dashboardu (ścieżka n8n)
  status        STRING               -- success | error
  retry_count   INTEGER              -- liczba auto-korekt SQL
  created_at    DATETIME

reports                              -- ZDEFINIOWANA, NIEUŻYWANA (pomysł: zapis dashboardów)
  id, query_id FK, metabase_question_id, metabase_dashboard_id, public_link, created_at
```

Relacje ORM: `User.databases`, `User.queries`, `Database.queries`,
`Query.report` — klasyczny układ 1:N.

**Kluczowa subtelność:** `file_path` to od migracji na Postgres-per-schema
NAZWA SCHEMATU, nie ścieżka. Cały kod używa jej jako identyfikatora danych
(np. `db_path` w `GenerateIn`, `schema_name` w `/internal/...`).

## 4. Dane analityczne — PostgreSQL

- Konwencja schematów: `u{user_id}_{sanityzowana_nazwa_pliku}`
  (`_sanitize_schema()`: lowercase, `[^a-z0-9]`→`_`, max 40 znaków).
  Przykłady: `u2_northwind`, `u35_sklep_testowy`.
- KAŻDY upload = `DROP SCHEMA IF EXISTS ... CASCADE` + `CREATE SCHEMA` +
  import tabel przez `pandas.to_sql`. Ponowny upload tego samego pliku
  NADPISUJE dane (i od 2026-07-06 również wpis w `databases` — upsert).
- Dwie role:
  - `analyst` — właściciel; import, DDL, odczyt metadanych (`get_db_schema`,
    `_find_date_columns`, `_text_column_values` — te ostatnie readonly),
  - `readonly` — WYŁĄCZNIE SELECT; wykonuje SQL wygenerowany przez model
    (walidacja `_run_and_validate`) i jest wpisana jako user połączeń Metabase.
- Bootstrap roli (`_ensure_readonly_role`, wykonywany przy KAŻDYM starcie
  backendu, idempotentny):
  1. `CREATE ROLE readonly LOGIN PASSWORD ...` (jeśli nie istnieje),
  2. `GRANT CONNECT ON DATABASE analytics`,
  3. `ALTER DEFAULT PRIVILEGES FOR ROLE analyst GRANT SELECT ON TABLES TO readonly`
     → tabele z PRZYSZŁYCH uploadów dostają SELECT automatycznie,
  4. pętla po istniejących schematach (`public` + `^u[0-9]+_`):
     `GRANT USAGE ON SCHEMA` + `GRANT SELECT ON ALL TABLES`.
  Do tego upload dokłada `GRANT USAGE` na każdym świeżo tworzonym schemacie
  (USAGE nie ma odpowiednika w default privileges).

## 5. Sieć i granice zaufania

```
przeglądarka ──HTTP──► localhost:5173 (frontend) ──► localhost:8000 (backend, JWT)
                                                     localhost:3000 (Metabase public link, iframe)

wewnątrz sieci docker (bez JWT — granica zaufania):
  n8n ──► fastapi_backend:8000/internal/...
  n8n ──► ollama:11434, metabase:3000, (postgres przez backend)
  backend ──► n8n_local:5678/webhook/create-dashboard
  metabase ──► postgres:5432 (rolą readonly)
```

Endpointy `/internal/...` nie mają uwierzytelniania — są osiągalne wyłącznie
z sieci dockerowej (nie są publikowane na hoście przez żaden routing frontendu).
Świadomy kompromis dla lokalnego demo; produkcyjnie: wewnętrzny token/mTLS.
