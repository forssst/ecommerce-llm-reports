# 07 — Integracja z Metabase (deep dive)

> Metabase = warstwa WIZUALIZACJI. System nie rysuje wykresów sam — tworzy
> obiekty Metabase przez REST API i osadza publiczny dashboard w iframe.
> Ta sama logika istnieje 2×: Python (`_ensure_metabase_db`, `create_metabase_*`,
> stara ścieżka) i węzły n8n (ścieżka produkcyjna) — celowo IDENTYCZNA.

## 1. Sesja

`POST /api/session {username, password}` → `{"id": "<token>"}` →
nagłówek `X-Metabase-Session: <token>` we wszystkich kolejnych wywołaniach.
Creds = konto ADMINA Metabase zaszyte w `main.py` (i w węźle `Metabase Login`).
Konsekwencja: wszystkie dashboardy powstają na jednym koncie (izolacja
per-user w Metabase — patrz kierunki rozwoju).

## 2. Rejestracja źródła danych (`_ensure_metabase_db` / węzeł `Zarejestruj DB`)

Idempotentna: `GET /api/database` → szukaj po `name == schema_name` → jest?
zwróć id. Nie ma? →
```json
POST /api/database
{"engine":"postgres","name":"u2_northwind",
 "details":{"host":"postgres","port":5432,"dbname":"analytics",
            "user":"readonly","password":"readonly","ssl":false,
            "additional-options":"currentSchema=u2_northwind"},
 "is_full_sync":true}
```
- `currentSchema=...` — jedno „źródło" Metabase na schemat; Metabase widzi
  tylko tabele tego użytkownika/pliku.
- **user readonly** — karty wykonują SQL od LLM (2026-07-06).
- Po utworzeniu: `POST /api/database/{id}/sync_schema` + `sleep(3)` —
  Metabase musi zeskanować pola, INACZEJ field filters nie znajdą kolumn dat.
  (Stara ścieżka Pythona robi jeszcze re-sync z `sleep(6)` przed budową kart —
  żeby świeżo zrzutowane TIMESTAMP-y były widoczne.)

Historyczny bug (zastany w oryginalnym workflow): rejestracja jako
`engine: sqlite` ze ścieżką PLIKU — architektura sprzed migracji na Postgres;
objaw „There was a problem displaying this chart". Naprawione na postgres.

## 3. Karta (`create_metabase_card` / węzeł `Utwórz Kartę`)

```json
POST /api/card
{"name":"Top 5 produktów według sumy sprzedaży",
 "dataset_query":{"database":14,"type":"native",
   "native":{"query":"SELECT ... [[AND data_zamowienia >= {{start_date}}]] ...",
             "template-tags":{
               "start_date":{"id":"...","name":"start_date","display_name":"Data od",
                             "type":"date","required":false,"default":null},
               "end_date":{...}}}},
 "display":"bar",
 "visualization_settings":{"graph.dimensions":["produkt"],"graph.metrics":["suma"]}}
```
- `type:"native"` = surowy SQL (nie kreator MBQL) — jedyna droga dla SQL od LLM.
- **Typ tagu MUSI być `date`** — `text` powodował błąd karty przy wybraniu
  daty w widgecie (mismatch z parametrem `date/single`; bug A2 z testów).
- `[[ ... ]]` = opcjonalna klauzula Metabase: znika z zapytania, gdy parametr
  pusty. Stąd wzorzec `WHERE 1=1 [[AND ...]]` gdy SQL nie miał WHERE.

### `visualization_settings` per typ (`_viz_settings`)
| display | ustawienia |
|---|---|
| bar / line / area / row | `graph.dimensions: [pierwsza kolumna]`, `graph.metrics: [reszta]` |
| pie | `pie.dimension: kol[0]`, `pie.metric: kol[1]` |
| scatter | dimensions/metrics numeryczne |
| smartscalar | `{}` (Metabase sam interpretuje trend) |
| combo | dimensions + metrics + `combo.series_settings` (kolejne serie jako linie) |
| table | `{}` |

## 4. Dashboard, układ, parametry

1. `POST /api/dashboard {"name":"Dashboard Analityczny AI"}` → id.
2. Układ: siatka **24 kolumn**; karty po dwie w rzędzie:
   `row=(i//2)*8, col=(i%2)*12, size_x=12, size_y=8`; `id` dashcarda ujemne
   (konwencja Metabase dla nowych).
3. Parametry dashboardu (tylko gdy ≥1 karta ma tagi):
   ```json
   PUT /api/dashboard/{id}
   {"parameters":[{"id":"<uuid1>","name":"Data od","slug":"data_od","type":"date/single","sectionId":"date"},
                  {"id":"<uuid2>","name":"Data do",...}]}
   ```
4. Spięcie parametr↔karta w `parameter_mappings` dashcarda:
   ```json
   {"card_id":123,"parameter_id":"<uuid1>",
    "target":["variable",["template-tag","start_date"]]}
   ```
5. `PUT /api/dashboard/{id}/cards {"cards":[...]}` — dodanie kart z układem.
6. `POST /api/dashboard/{id}/public_link` → `{"uuid":"..."}` → URL:
   `{METABASE_PUBLIC_URL}/public/dashboard/{uuid}` (localhost:3000 — link
   otwiera PRZEGLĄDARKA, nie kontener!).

### Różnica wariantów filtrów (ciekawostka porównawcza)
- Stara ścieżka Pythona: JEDEN parametr `date/range` + tagi `type:"dimension"`
  (field filter wskazujący konkretne POLE przez id z metadanych Metabase).
- Ścieżka n8n: DWA parametry `date/single` (od/do) + tagi `type:"date"`
  (zmienne w SQL). Prostsze, bez potrzeby znania field-id; wybór świadomy.

## 5. Pułapka MBQL `stages` (Metabase 50+)

`GET /api/card/{id}` zwraca zapytanie w NOWYM formacie:
`dataset_query.stages[0]['template-tags']` — a nie klasycznie
`dataset_query.native['template-tags']`. Węzeł `Zbuduj Układ` czyta OBA
miejsca (fallback). Bez tego: karty MIAŁY tagi, ale dashboard nie dostawał
parametrów → filtr dat „znikał" (zastany bug, naprawiony 2026-07-05).

## 6. Debug — przydatne wywołania

```bash
# lista źródeł + user połączenia (sprawdzenie readonly):
GET /api/database  → data[].details.user
# wykonaj zapytanie ad-hoc na źródle (test uprawnień / danych):
POST /api/dataset {"type":"native","database":14,"native":{"query":"SELECT 1"}}
# uruchom kartę z parametrem (test filtra dat):
POST /api/card/{id}/query {"parameters":[{"type":"date/single",
  "target":["variable",["template-tag","start_date"]],"value":"2024-02-01"}]}
```

## Sprawdź się
1. Po co `currentSchema` w details źródła i co by było bez niego?
2. Dlaczego typ template-taga `text` psuł filtr, skoro karta się tworzyła?
3. Wytłumacz składnię `[[AND ...]]` i wzorzec `WHERE 1=1`.
4. Jak wygląda pełna droga od „user wybrał 2024-02-01 w widgecie" do
   zmienionego SQL-a karty?
5. Co czyta `Zbuduj Układ` i czemu w dwóch miejscach?
