# Raport techniczny — system „AI Data Analyst"

> Szczegółowy opis działania systemu od początku do końca: każda metoda po kolei,
> przepływ zapytania (prompt), przykłady danych wejściowych i wyjściowych.
> Dokument odzwierciedla aktualny stan kodu w `backend/main.py`, `backend/models.py`,
> `backend/database.py` oraz `frontend/src/App.jsx`.

---

## 1. Czym jest system (w jednym akapicie)

Użytkownik wgrywa plik z danymi (SQLite `.db` / CSV / Excel), pisze po polsku **cel
analityczny** (np. „pokaż TOP 10 klientów według zakupów"), a system:
1. zamienia cel na **plan 2–4 wykresów**,
2. dla każdego wykresu generuje **osobny SQL** (lokalny model LLM),
3. **waliduje SQL** na prawdziwych danych w PostgreSQL,
4. buduje **dashboard w Metabase** i osadza go w przeglądarce przez `<iframe>`.

Całość działa **lokalnie** (prywatność, brak kosztów API, offline).

---

## 2. Architektura i usługi

```
┌─────────────┐   HTTP    ┌──────────────────┐   HTTP   ┌──────────────┐
│  Frontend   │ ────────► │  FastAPI backend │ ───────► │   Ollama     │
│ React/Vite  │ ◄──────── │   (main.py)      │ ◄─────── │ qwen2.5-coder│
│  :5173      │   JSON    │     :8000        │   JSON   │   :11434     │
└─────────────┘           └────────┬─────────┘          └──────────────┘
       ▲                           │
       │ <iframe>                  │ SQL (walidacja)      ┌──────────────┐
       │                           ├─────────────────────►│  PostgreSQL  │
       │                           │                      │  analytics   │
       │                           │                      │    :5432     │
       │                           │ REST API             └──────────────┘
       │                  ┌────────▼─────────┐
       └──────────────────│    Metabase      │
         public dashboard │     :3000        │
                          └──────────────────┘
```

| Usługa            | Rola                                                         | Port  |
|-------------------|-------------------------------------------------------------|-------|
| `frontend`        | React + Vite + Tailwind (uruchamiany osobno)                | 5173  |
| `fastapi_backend` | Cała logika — `backend/main.py`                             | 8000  |
| `ollama`          | Lokalny model `qwen2.5-coder:7b`                            | 11434 |
| `postgres`        | Baza analityczna (dane wgranych plików, schemat per plik)   | 5432  |
| `metabase`        | Wizualizacja, generowanie dashboardów                       | 3000  |
| `n8n`             | Zapasowa orkiestracja (ścieżka fallback)                    | 5678  |

---

## 3. Model danych — dwie osobne bazy

### 3.1. Baza systemowa (SQLite `/data/system.db`)
Definicja: `backend/database.py` + `backend/models.py`. Przechowuje **metadane**, nie same dane.

| Tabela      | Co zawiera                                                                    |
|-------------|------------------------------------------------------------------------------|
| `users`     | `id`, `email`, `password_hash` (bcrypt), `created_at`                         |
| `databases` | `id`, `user_id`, `name` (oryg. nazwa pliku), `file_path` (= nazwa **schematu PG**), `schema_json` (zwięzły schemat), `uploaded_at` |
| `queries`   | historia: `prompt_nl`, `generated_sql` (JSON wyniku), `status`, `retry_count` |
| `reports`   | zdefiniowana, jeszcze nieużywana (miejsce na zapis dashboardów)               |

**Ważne:** kolumna `databases.file_path` nie wskazuje już na plik — przechowuje **nazwę
schematu w PostgreSQL** (np. `u2_chinook`). To pozostałość po starej architekturze (pliki SQLite).

### 3.2. Baza analityczna (PostgreSQL `analytics`)
Każdy wgrany plik = **osobny schemat** PostgreSQL o nazwie `u{user_id}_{nazwa_pliku}`.
Tabele z pliku stają się tabelami w tym schemacie. Dzięki temu:
- dane są trwałe (nie znikają jak pliki w kontenerze),
- daty mają poprawny typ `TIMESTAMP` (potrzebne do filtrów),
- Metabase łączy się z PG przez parametr `currentSchema`.

---

## 4. PRZEPŁYW OD POCZĄTKU DO KOŃCA (z przykładem)

Prześledźmy konkretny przykład: użytkownik (id=2) ma wgraną bazę **Chinook** i wpisuje cel:

> **„Pokaż TOP 10 artystów według łącznej sprzedaży"**

### Krok 0 — Logowanie (frontend → backend)
- `POST /login` z e-mailem i hasłem.
- Backend (`login`, linia 648) szuka usera, sprawdza hasło `bcrypt.checkpw`.
- Zwraca `{id, email}`. Frontend zapisuje usera i pobiera bazy + historię.

### Krok 1 — Front składa `schema_text`
W `handleGenerate` (App.jsx:157) frontend buduje tekstowy schemat z `schema_json`:
```
Tabela album: albumid, title, artistid
Tabela artist: artistid, name
Tabela invoice: invoiceid, customerid, invoicedate, total
Tabela invoiceline: invoicelineid, invoiceid, trackid, unitprice, quantity
Tabela track: trackid, name, albumid, ...
...
```
oraz `chart_type` z wybranych przycisków typów (`buildChartType`, App.jsx:106). Jeśli nic nie
wybrano → `chart_type = ""` (AI samo decyduje).

### Krok 2 — `POST /generate`
Wysyłany JSON:
```json
{
  "user_id": 2,
  "prompt": "Pokaż TOP 10 artystów według łącznej sprzedaży",
  "description": "Baza zawiera dane o muzyce...",
  "chart_type": "",
  "schema_text": "Tabela album: ...",
  "db_path": "u2_chinook"
}
```

### Krok 3 — Backend: `generate()` (linia 836)
1. Znajduje rekord bazy po `file_path == db_path` → ustala `db_id`.
2. Próbuje **ścieżki GŁÓWNEJ**: `_generate_multichart(g, db, db_id)`.
3. Jeśli rzuci wyjątek → **ścieżka ZAPASOWA** (n8n, pętla retry niżej).

### Krok 4 — `_generate_multichart()` — DWA ETAPY

**Etap A — Planowanie (1 wywołanie LLM):**
Backend wysyła `plan_prompt` do Ollamy z `format: json`. Model zwraca listę wykresów:
```json
{"charts": [
  {"title": "TOP 10 artystów", "chart_type": "bar",
   "goal": "Pokaż 10 artystów o najwyższej sumie sprzedaży. Użyj artist.name jako etykiety, SUM(invoiceline.unitprice*quantity) jako wartości. JOIN przez album i track. ORDER BY DESC LIMIT 10"},
  {"title": "Sprzedaż w czasie", "chart_type": "line", "goal": "..."},
  {"title": "Udział gatunków", "chart_type": "pie", "goal": "..."}
]}
```

**Etap B — SQL per wykres (pętla, do 3 prób każdy):**
Dla każdego wykresu osobne wywołanie LLM z `sql_prompt`. Model zwraca:
```json
{"sql": "SELECT artist.name, SUM(invoiceline.unitprice * invoiceline.quantity) AS total_sales FROM artist JOIN album ON artist.artistid = album.artistid JOIN track ON album.albumid = track.albumid JOIN invoiceline ON track.trackid = invoiceline.trackid GROUP BY artist.name ORDER BY total_sales DESC LIMIT 10"}
```
SQL przechodzi przez `_clean_sql()` (czyszczenie), a potem `_run_and_validate()` — backend
**wykonuje go naprawdę** na schemacie `u2_chinook`. Jeśli błąd → tekst błędu wraca do modelu
jako wskazówka i próba się powtarza (max 3).

### Krok 5 — Budowa dashboardu w Metabase
Po zebraniu poprawnych SQL-i backend (w bloku `except`, bo n8n zwykle nie odpowiada):
1. `_get_metabase_token()` — loguje się do Metabase API.
2. `_ensure_metabase_db()` — rejestruje połączenie PG↔Metabase (jeśli nie istnieje).
3. wymusza `sync_schema` + `sleep(6)` (Metabase skanuje pola, wykrywa daty).
4. `create_metabase_dashboard()` — tworzy pusty dashboard.
5. dla każdego wykresu: `create_metabase_card()` (karta SQL native + typ wizualizacji).
6. jeśli wykres ma kolumnę daty → wstrzykuje **filtr zakresu dat**.
7. `publish_metabase_dashboard()` — publiczny link.

### Krok 6 — Zapis i odpowiedź
Backend zapisuje rekord do `queries` (status, retry_count, JSON wyniku) i zwraca:
```json
{
  "status": "success",
  "sql": "{ ...sformatowany JSON z wykresami... }",
  "retry_count": 1,
  "metabase": {"url": "http://localhost:3000/public/dashboard/abc-uuid"}
}
```

### Krok 7 — Front osadza dashboard
React wstawia `<iframe src={metabase.url}>` (App.jsx:490). Użytkownik widzi gotowy dashboard.

---

## 5. SZCZEGÓŁOWY OPIS KAŻDEJ METODY (w kolejności użycia)

### 5.1. Konfiguracja i pomocnicze (góra pliku)

#### `_pg_conn(schema=None)` — linia 54
Otwiera połączenie psycopg2 do PostgreSQL. Jeśli podano `schema`, ustawia
`SET search_path TO {schema},public` — dzięki temu zapytania widzą tabele danego użytkownika
bez prefiksów.

#### `_sanitize_schema(user_id, filename)` — linia 64
Zamienia nazwę pliku na bezpieczną nazwę schematu PG.
Przykład: `(2, "Chinook_Sqlite.sqlite")` → `"u2_chinook_sqlite"`.
Usuwa znaki specjalne, ucina do 40 znaków, dodaje prefiks `u{id}_`.

### 5.2. Klasy wejściowe (Pydantic)
- `UserIn` — `email`, `password_hash` (linia 70)
- `GenerateIn` — pełny payload `/generate` (linia 75)
- `DescribeIn` — `schema_text` (linia 665)
- `EnhanceIn` — `prompt` + `schema_text` (linia 669)

### 5.3. Parsowanie konfiguracji wykresów

#### `_parse_requested_charts(text)` — linia 86
Wyciąga listę typów wykresów z tekstu `chart_type` **w kolejności wystąpienia**.
Przykład: `"Dokładnie 2 wykresy: (1) słupkowy, (2) kołowy"` → `["bar", "pie"]`.
Mapuje polskie słowa (słupkowy→bar, kołowy→pie, liniowy→line, …) na typy Metabase.

#### `_parse_chart_count(text)` — linia 261
Gdy user nie wybrał konkretnych typów, ale wpisał liczbę: `"4 wykresy"` → `4`.
Domyślnie (brak) → 3 wykresy.

### 5.4. Obsługa dat (dla filtrów Metabase)

#### `_find_date_column(schema_name)` — linia 108
Pyta `information_schema.columns` o pierwszą kolumnę typu `date`/`timestamp` w schemacie.
Zwraca nazwę kolumny lub `None`.

#### `_get_mb_date_fields(token, db_id)` — linia 127
Pobiera z **metadanych Metabase** wszystkie pola typu Date/Time:
`[{id, name, table}, ...]`. Potrzebne, bo filtr Metabase działa na `field_id`, nie na nazwie.

#### `_sql_refs_date_field(sql, date_fields)` — linia 148
Sprawdza, czy w treści SQL pojawia się nazwa którejś kolumny daty. Zwraca pierwsze trafienie
lub `None`. Dzięki temu filtr wstawiamy tylko do wykresów, które faktycznie używają daty.

#### `_inject_date_filter(sql, tag_name)` — linia 157
Wstawia opcjonalną klauzulę Metabase `[[AND {{date_filter}}]]` przed `GROUP BY`/`ORDER BY`.
Jeśli SQL nie ma `WHERE`, dokłada `WHERE 1=1`. To mechanizm „field filter" Metabase —
gdy użytkownik nic nie wybierze, klauzula znika; gdy wybierze daty, aktywuje się.

### 5.5. Odczyt schematu

#### `get_db_schema(schema_name)` — linia 171
Czyta z PostgreSQL strukturę: dla każdej tabeli listę kolumn (nazwa+typ) i liczbę wierszy.
Zwraca słownik `{tabela: {columns: [...], row_count: N}}`. Używane po uploadzie.

### 5.6. Czyszczenie i walidacja SQL

#### `_clean_sql(sql)` — linia 224 ⭐ (kluczowa)
Najważniejsza funkcja czyszcząca surowy SQL z modelu. Po kolei:
1. usuwa bloki ```` ```sql ... ``` ````,
2. **zamienia backticki** `` `OrderDate` `` → `orderdate` (model lubi składnię MySQL),
3. **zamienia `"CamelCase"`** → `camelcase` (pandas importuje kolumny małymi literami),
4. usuwa komentarze `/* */` i `--`,
5. usuwa prefiks `"sql:"`,
6. bierze tylko **pierwszą instrukcję** (przed `;`),
7. śledzi głębokość nawiasów, by nie uciąć podzapytań/CTE przy wielu `SELECT`.

To rozwiązuje większość błędów składniowych typowych dla LLM (backticki, CamelCase, wiele zapytań).

#### `_run_and_validate(schema_name, sql)` — linia 267 ⭐
**Faktycznie wykonuje SQL** na PostgreSQL (`SET search_path` → `cur.execute`).
Pobiera nazwy kolumn i 5 przykładowych wierszy.
Zwraca `(ok, error, columns, sample)`. To serce walidacji — SQL, który nie wykona się na
prawdziwych danych, nie trafi na dashboard.

### 5.7. Decyzja o typie wykresu

#### `_infer_display(columns, sample)` — linia 283
Gdy model nie poda typu: jeśli pierwsza kolumna wygląda jak data (`2009-01`) → `line`,
jeśli ≥2 kolumny → `bar`, inaczej → `table`.

#### `_config_hint(config_text)` — linia 294
Jeśli w wytycznych wskazano DOKŁADNIE jeden typ → użyj go (mapowanie słów PL→typ).
Obsługuje też typy specjalne: funnel, waterfall, smartscalar, combo.

#### `_viz_settings(display, columns)` — linia 323
Buduje `visualization_settings` dla karty Metabase zależnie od typu:
- bar/line/area/row/scatter/waterfall/combo → `graph.dimensions` (oś X) + `graph.metrics` (oś Y),
- pie → `pie.dimension` + `pie.metric`,
- funnel/smartscalar → puste (Metabase sam wykrywa kolumny),
- combo → dodatkowo `combo.series_settings` (które serie jako linie).

### 5.8. Integracja z Metabase

#### `_get_metabase_token()` — linia 343
`POST /api/session` z loginem/hasłem admina Metabase → token sesji.
⚠️ Login/hasło są **zaszyte w kodzie** (linie 36–37) i muszą pasować do konta admina Metabase.

#### `_ensure_metabase_db(token, schema_name)` — linia 350
Sprawdza, czy Metabase ma już połączenie o nazwie = schemat. Jeśli nie — tworzy:
silnik `postgres`, host/port/creds PG, `additional-options: currentSchema={schema}`.
Po utworzeniu wymusza `sync_schema` + `sleep(3)`.

#### `create_metabase_dashboard(token, name)` — linia 388
`POST /api/dashboard` → zwraca `dashboard_id`.

#### `create_metabase_card(token, db_id, name, sql, display, columns, template_tags)` — linia 395
`POST /api/card` — tworzy kartę z **native SQL**:
- `dataset_query.native.query` = nasz SQL,
- `template-tags` = ewentualny filtr daty,
- `display` = typ wykresu,
- `visualization_settings` = z `_viz_settings`.

#### `publish_metabase_dashboard(token, dash_id)` — linia 412
`POST /api/dashboard/{id}/public_link` → publiczny UUID → pełny URL do osadzenia w iframe.

### 5.9. Wywołania LLM

#### `_ollama_json(prompt, timeout)` — linia 438 ⭐
Wywołuje Ollamę z `"format": "json"` (wymusza poprawny JSON na wyjściu) i parsuje odpowiedź.
Używane w obu etapach (planowanie + SQL).

#### `_call_n8n(url, payload, timeout)` — linia 419
Wywołanie webhooka n8n (ścieżka zapasowa).

#### `_full_prompt(g)` — linia 428
Skleja cel+opis+układ do zapisu w historii (`queries.prompt_nl`).

---

## 6. GŁÓWNA LOGIKA — `_generate_multichart()` (linia 447)

To centralna funkcja całego systemu. Krok po kroku:

1. **Ustal liczbę i typy wykresów** (`_parse_requested_charts` / `_parse_chart_count`).
2. **Zbuduj instrukcję typów** (`types_instruction`) — albo dokładne typy w kolejności,
   albo „3–4 różnorodne wykresy".
3. **PLAN PROMPT** (linia 462) — wyślij do Ollamy, odbierz listę `{title, chart_type, goal}`.
4. Nadpisz `chart_type` żądaniami użytkownika (jeśli wybrał konkretne typy).
5. **Pętla po wykresach** (linia 504):
   - złóż `sql_prompt` z zasadami + ewentualnym `chart_hint` dla typu specjalnego,
   - jeśli była wcześniejsza próba — dołącz `POPRZEDNI SQL ... BŁĄD ...`,
   - wywołaj LLM → `_clean_sql` → `_run_and_validate`,
   - max 3 próby; po sukcesie zapamiętaj `(title, sql, display, columns)`,
   - po 3 nieudanych — pomiń wykres (`[SKIP]`).
6. **Zbuduj dashboard** (n8n → fallback Metabase), wstrzyknij filtry dat.
7. **Zapisz** do `queries`, zwróć wynik.

### 6.1. PLAN PROMPT (pełna treść, linia 462)
```
Jestes analitykiem danych. Zaplanuj wykresy analityczne do dashboardu.
{types_instruction}
ZASADY:
- Kazdy wykres musi miec INNY cel analityczny.
- W polu 'goal' napisz DOKLADNIE co pokazac i jakich kolumn uzyc jako etykiet vs wartosci.
- Jako etykiety uzyj kolumn TEXT z nazwami/kategoriami — NIGDY kolumn ID ani liczb.
- Jesli trzeba pokazac klientow/produkty/pracownikow — w 'goal' napisz explicite zeby uzyc JOIN...
- Jesli CEL zawiera slowa: trend/miesiac/rok/czas/timeline — MUSISZ dodac wykres z kolumna daty...
- Dla trendow w 'goal' napisz: 'GROUP BY DATE_TRUNC(month/year, kolumna_daty)'.
Zwroc WYLACZNIE JSON: {"charts":[{"title":"...","chart_type":"bar|line|pie|table","goal":"..."}]}
Nie pisz SQL.
CEL: {prompt}
WYTYCZNE: {chart_type}
OPIS DANYCH: {description}
SCHEMAT: {schema_text}
```

### 6.2. SQL PROMPT (pełna treść, linia 513)
```
Wygeneruj JEDEN poprawny SELECT (dialekt PostgreSQL) dla celu ponizej.
ZASADY — przestrzegaj wszystkich:
- Zwroc TYLKO jedno zapytanie SELECT. Zadnych srednikow w srodku...
- Uzyj PELNYCH nazw tabel bez aliasow...
- Jako etykiety (pierwsza kolumna) uzyj kolumn TEXT z nazwami/kategoriami.
- Kolumny konczace sie na '_id','_qty','_count','_price'... to liczby/ID — NIE jako etykiet.
- Jesli chcesz pokazac klientow/produkty po nazwie — uzyj JOIN...
- Agregaty: SUM(), COUNT(), AVG() na kolumnach numerycznych.
- Dla trendow czasowych: ZAWSZE grupuj po pelnym zakresie dat — NIGDY nie filtruj do roku.
- Dla dat uzywaj PostgreSQL: DATE_TRUNC('month', kol) ... LUB EXTRACT(YEAR FROM kol)::int.
- Wyniki sortuj sensownie: daty ASC, wartosci DESC (TOP N).
- WAZNE: wszystkie nazwy tabel i kolumn sa MALYMI LITERAMI (pandas importuje jako lowercase).
- NIE uzywaj backtickow (`).
{chart_hint — opcjonalna wskazówka dla scatter/funnel/waterfall/smartscalar/combo}
Zwroc WYLACZNIE JSON: {"sql":"SELECT ..."}
CEL WYKRESU: {goal}
SCHEMAT: {schema_text}
```

### 6.3. Wskazówki dla typów specjalnych (`_CHART_HINTS`, linia 494)
| Typ           | Wskazówka SQL dodawana do promptu                                   |
|---------------|---------------------------------------------------------------------|
| `scatter`     | zwróć dokładnie 2 kolumny numeryczne, bez tekstowych                 |
| `smartscalar` | jeden rząd, jeden agregat (np. `SUM(total)`)                         |
| `funnel`      | 2 kolumny: etykieta + wartość, sortuj malejąco                      |
| `waterfall`   | policz różnice rok-do-roku przez `LAG()` (wzorzec w prompcie)        |
| `combo`       | data + ≥2 kolumny numeryczne (np. miesięczna i skumulowana sprzedaż) |

---

## 7. ENDPOINTY HTTP (lista pełna)

| Metoda + ścieżka              | Funkcja              | Opis                                          |
|-------------------------------|----------------------|-----------------------------------------------|
| `POST /users`                 | `get_or_create_user` | Pobiera lub tworzy usera (legacy)             |
| `POST /register`              | `register`           | Rejestracja, hasło → bcrypt                    |
| `POST /login`                 | `login`              | Logowanie, `bcrypt.checkpw`                    |
| `POST /enhance-prompt`        | `enhance_prompt`     | „Ulepsz prompt AI" — doprecyzowuje cel po PL   |
| `POST /describe-schema`       | `describe_schema`    | „Opis bazy AI" — generuje opis bazy po PL      |
| `POST /upload`                | `upload_database`    | Wgranie pliku → schemat PostgreSQL             |
| `GET /users/{id}/databases`   | `get_user_databases` | Lista baz użytkownika                          |
| `DELETE /databases/{id}`      | `delete_database`    | Usuwa bazę (+ DROP SCHEMA + historię)          |
| `GET /users/{id}/queries`     | `get_user_queries`   | Historia 20 ostatnich promptów                 |
| `POST /generate`              | `generate`           | GŁÓWNY — generuje dashboard                     |

### 7.1. `/enhance-prompt` (linia 674)
Bierze surowy cel + schemat, prosi LLM o doprecyzowanie **po polsku** (bez SQL!).
Po stronie backendu jest filtr awaryjny: jeśli model mimo wszystko wstawi SQL
(`SELECT`/`FROM`/`JOIN`…), wycinamy te linie. Wynik trafia z powrotem do pola „cel".

### 7.2. `/describe-schema` (linia 704)
Generuje 3–4 zdaniowy opis bazy po polsku (pokazywany w panelu „Opis bazy danych").

### 7.3. `/upload` (linia 722) — szczegóły
1. Zapis pliku do `/tmp`.
2. Wczytanie **wszystkich tabel** do `DataFrame`-ów:
   - `.db/.sqlite` → po jednej tabeli z `sqlite_master`,
   - `.csv` → jeden DataFrame,
   - `.xlsx/.xls` → jeden DataFrame na arkusz.
3. `_sanitize_schema` → nazwa schematu PG.
4. `DROP SCHEMA ... CASCADE` + `CREATE SCHEMA` (czysty start).
5. Dla każdej tabeli: nazwy kolumn → lowercase, `df.to_sql(...)` do PG.
6. **Rzutowanie dat**: kolumny tekstowe z `date/time/created/updated/timestamp` w nazwie →
   `ALTER COLUMN ... TYPE TIMESTAMP` (potrzebne do filtrów Metabase).
7. `get_db_schema` → zapis metadanych do `databases`.

### 7.4. `/generate` (linia 836) — ścieżka zapasowa (n8n)
Gdy `_generate_multichart` rzuci wyjątek, uruchamia się pętla (max 3 próby):
- składa `base_query`, woła webhook n8n (`_call_n8n`),
- parsuje JSON, normalizuje wykresy (`_normalize_chart`),
- waliduje każdy SQL (`_run_and_validate`),
- buduje dashboard Metabase tak samo jak ścieżka główna.
W praktyce n8n zwykle nie odpowiada → realnie działa ścieżka główna z fallbackiem na bezpośrednie API Metabase.

---

## 8. OBSŁUGA BŁĘDÓW I MECHANIZM RETRY

```
Próba SQL (max 3 na wykres):
  ┌─────────────────────────────────────────────┐
  │ LLM generuje SQL                             │
  │        ↓                                     │
  │ _clean_sql (czyszczenie składni)             │
  │        ↓                                     │
  │ _run_and_validate (wykonanie na PG)          │
  │        ↓                                     │
  │   OK? ──TAK──► zapisz wykres, idź dalej       │
  │    │                                         │
  │   NIE                                        │
  │    ↓                                         │
  │ błąd wraca do promptu jako wskazówka:        │
  │ "POPRZEDNI SQL ... BŁĄD ... Popraw"          │
  └─────────────────────────────────────────────┘
  Po 3 nieudanych próbach → [SKIP], wykres pomijany.
```

`retry_count` (suma poprawek) jest zapisywany w `queries` i pokazywany w UI jako
„N auto-korekt SQL". To dobry materiał do rozdziału „Ewaluacja".

---

## 9. PRZYKŁADY (wejście → wyjście)

### Przykład 1 — prosty ranking
**Cel:** „Pokaż TOP 10 albumów według liczby sprzedanych utworów"
**Plan LLM:** 1 wykres, `chart_type: bar`
**SQL (po `_clean_sql`):**
```sql
SELECT album.title, SUM(invoiceline.quantity) AS total_quantity_sold
FROM album
JOIN track ON album.albumid = track.albumid
JOIN invoiceline ON track.trackid = invoiceline.trackid
GROUP BY album.title
ORDER BY total_quantity_sold DESC
LIMIT 10
```
**Wynik:** słupkowy, 10 albumów. ✅

### Przykład 2 — trend czasowy (z filtrem dat)
**Cel:** „Pokaż miesięczny przychód w latach 2009–2013"
**Plan LLM:** `chart_type: line`
**SQL:**
```sql
SELECT DATE_TRUNC('month', invoice.invoicedate) AS month, SUM(invoice.total) AS total_revenue
FROM invoice
GROUP BY DATE_TRUNC('month', invoice.invoicedate)
ORDER BY month
```
Backend wykrywa kolumnę daty → wstrzykuje `[[AND {{date_filter}}]]` → na dashboardzie
pojawia się filtr „Zakres dat". ✅

### Przykład 3 — typowy błąd i auto-korekta
**Próba 1 SQL:** `SELECT o.OrderDate ...` → błąd `column o.orderdate does not exist`
(model użył CamelCase + aliasu). `_clean_sql` zamienia CamelCase, ale alias zostaje.
**Wskazówka do modelu:** „POPRZEDNI SQL ... BŁĄD: column does not exist ... Popraw".
**Próba 2:** model używa pełnych nazw lowercase → SQL działa. `retry_count = 1`. ✅

---

## 10. ZNANE OGRANICZENIA

1. **Złożone JOIN-y (3+ tabel)** — model 7B czasem myli klucze lub agreguje źle
   (np. oś Y = `customerid` zamiast sumy). To ograniczenie małego modelu lokalnego.
2. **Wykresy specjalne (lejkowy, kaskadowy)** — Metabase nie zawsze renderuje je zgodnie
   z intencją; wymagają niekiedy ręcznej konfiguracji w interfejsie.
3. **SQL bez ograniczenia do read-only** — generowany SQL nie jest wymuszany jako `SELECT`
   (potencjalny kierunek poprawy bezpieczeństwa).
4. **Creds Metabase zaszyte w kodzie** — muszą pasować do konta admina (pułapka konfiguracyjna).

---

## 11. PODSUMOWANIE PRZEPŁYWU (skrót dla obrony)

```
1. Login (bcrypt)                          → /login
2. Upload pliku → schemat PostgreSQL       → /upload  (pandas → to_sql → ALTER dat)
3. (opcja) Ulepsz prompt / Opisz bazę      → /enhance-prompt, /describe-schema
4. Generate                                → /generate
   ├─ _generate_multichart
   │   ├─ ETAP A: plan wykresów (LLM, JSON)
   │   └─ ETAP B: SQL per wykres (LLM) → _clean_sql → _run_and_validate → retry≤3
   ├─ Metabase: db → dashboard → karty → filtr dat → public link
   └─ zapis do queries (status, retry_count)
5. Front osadza dashboard w <iframe>
```

**Najważniejsze funkcje do zapamiętania:**
`_generate_multichart` (orkiestracja), `_clean_sql` (naprawa SQL),
`_run_and_validate` (walidacja na danych), `_ollama_json` (LLM),
`create_metabase_card` (wizualizacja).
