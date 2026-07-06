# 05 — Generowanie: n8n węzeł po węźle + endpointy /internal (deep dive)

> Workflow: „Metabase - Utwórz Dashboard" (29 węzłów), eksport w repo:
> `n8n_orchestrator_workflow.json`. Webhook produkcyjny:
> `POST http://n8n_local:5678/webhook/create-dashboard`.

## 0. Kontrakt wejścia/wyjścia webhooka

```json
// wejście (od backendu, _generate_via_n8n_orchestrator):
{"prompt":"...", "schema_text":"...(+ znane wartości kolumn tekstowych)",
 "chart_type":"...", "description":"...", "db_path":"u2_northwind"}

// wyjście (węzeł "Odpowiedz"):
{"url":"http://localhost:3000/public/dashboard/<uuid>",
 "sql":"-- Tytuł 1\nSELECT...\n\n-- Tytuł 2\nSELECT...",
 "requested":3,"generated":2,"failed":1,"failed_titles":["..."],"retries":2}

// wyjście błędu (węzeł "Odpowiedz Blad"):
{"error":"Model nie wygenerowal poprawnego SQL dla zadnego z zaplanowanych wykresow..."}
```

## ETAP 1 — Plan (natywne węzły AI)

### `Webhook`
`httpMethod: POST`, `path: create-dashboard`, `responseMode: responseNode`
(odpowiedź wysyła dopiero węzeł RespondToWebhook — stąd guard „Sa Wykresy?"
jest krytyczny: workflow, który nie dotrze do żadnego Respond, zostawia
klienta na timeoucie).

### `Zbuduj Prompt Planu` (Code)
Woła `POST /internal/plan-prompt` z `{goal, chart_type, description, schema_text}`.
Backend: `_parse_requested_charts(chart_type)` → lista typów w kolejności
kliknięć (11 wzorców słów kluczowych PL/EN); `n_charts` = liczba typów albo
parsowane „Dokładnie N wykresy" albo 3. Zwraca `{prompt, n_charts, requested_types}`.

### `Model Ollama (Plan)` + `LLM Chain: Plan` (natywne `@n8n/n8n-nodes-langchain`)
- `lmOllama` wymaga credentiala `ollamaApi` (`baseUrl: http://ollama:11434`) —
  tworzonego ręcznie/przez API, nie istnieje domyślnie.
- JEDEN węzeł modelu zasila DWA chainy (Plan i Plan Retry) przez połączenie
  typu `ai_languageModel` (fan-out) — reuse konfiguracji.
- `chainLlm` zwraca tekst w **`$json.text`**; NIE wymusza JSON (w odróżnieniu
  od `format:"json"` surowego API), więc odpowiedź bywa w ```` ```json ```` —
  następny węzeł zdejmuje fence'y.
- Zmierzony koszt natywności: sam plan przez chainLlm potrafił zająć ~112 s,
  gdy cały pipeline surowym HTTP mieścił się w 53–91 s. Świadomy kompromis:
  czytelność canvasu za wydajność.

### `Przetworz Plan` (Code)
```js
const cleaned = chainText.replace(/```json/gi,'').replace(/```/g,'').trim();
rawPlan = JSON.parse(cleaned)  // catch -> {charts: []}
```
→ `POST /internal/process-plan` `{raw_plan, requested_types, n_charts,
user_prompt, is_retry:false}`. Backend:
- **guard językowy**: jeśli JAKIKOLWIEK `title/goal` zawiera znaki spoza
  polskiego alfabetu (`_FOREIGN_CHARS`: CJK, cyrylica, obce łacińskie
  diakrytyki — polskie ąćęłńóśźż dozwolone) → `{specs:[], need_retry:true}`,
- normalizacja speców: przycięcie do `n_charts`, nadpisanie `chart_type`
  żądanymi typami (kolejność!), tytuł: pusty/„Wykres N" → goal[:60];
  nadal obcy język → fallback na prompt użytkownika.

### `Trzeba Retry Planu?` (IF) → gałąź retry
`Zbuduj Prompt Retry Planu` dokleja ostrzeżenie „POPRZEDNI PLAN byl w obcym
jezyku..." → `LLM Chain: Plan Retry` (ten sam model) → `Przetworz Plan Retry`
(`is_retry:true` — drugi raz języka NIE sprawdzamy; ostatnia linia obrony to
fallback tytułu). Celowo NIE jest to pętla (cykl na canvasie budowany „na
ślepo" przez API był zbyt ryzykowny) — dokładnie jedna dodatkowa próba,
tak samo jak w pythonowym pierwowzorze.

## ETAP 2 — SQL per wykres (`Generuj SQL i Zbierz Wykresy`, Code)

Pseudokod rzeczywistego JS (pełny w eksporcie):
```js
for (const spec of input.specs) {          // 2-4 wykresy
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt > 0) totalRetries++;
    prompt = POST /internal/sql-prompt {goal, chart_type, schema_text,
                                        prev_sql, prev_err}   // retry-suffix gdy prev_err
    raw    = POST ollama /api/generate {model, prompt, format:'json',
                                        timeout: 180000}      // surowe HTTP, nie chain
    v      = POST /internal/process-sql-attempt {schema_name: db_path,
                                                 chart_type, raw_sql, goal}
    {ok, sql, error, columns, sample} = v;  if (ok && sql) break;
  }
  if (!ok) { failedTitles.push(spec.title); continue; }   // wykres pomijany
  f = POST /internal/finalize-chart {title, sql, chart_type, columns, sample, user_prompt}
  charts.push({title: f.title, sql, display: f.display, columns});
}
dateColumns = GET /internal/date-column?schema_name=...   // LISTA kandydatów
return {charts, db_path, user_prompt, date_columns,
        requested: specs.length, failed: specs.length - charts.length,
        failed_titles, retries: totalRetries};
```

`process-sql-attempt` po stronie Pythona (sekwencja):
1. `_clean_sql(raw_sql)` (docs/06 §1),
2. guard `_RELATIVE_DATE_FILTER` → odrzucenie PRZED wykonaniem,
3. guard TOP N: `goal` zawiera `top N` + SQL bez `LIMIT` → doklej `LIMIT N`,
4. `_run_and_validate(schema, sql, ctype)` — wykonanie **rolą readonly**,
   próbka `fetchmany(5)`, potem `_check_label_column` i (dla licznika)
   `_check_smartscalar_shape`,
5. guard 0 wierszy: ok, ale pusta próbka → `ok=False` z podpowiedzią,
6. każdy fail → `print("[sql-attempt FAIL] ...")` (diagnostyka w logach).

Dlaczego Code node zamiast rozrysowania: pętla o zmiennej długości (2–4
wykresy) z 3 próbami i wymianą stanu (prev_sql/prev_err) wymagałaby ~15–20
węzłów (Loop Over Items + rozpisane próby) — nieproporcjonalny koszt/ryzyko.

## ETAP 3 — Bramka `Sa Wykresy?` (IF `charts.length > 0`)

Gałąź FAŁSZ: `Zbuduj Blad Brak Wykresow` (statyczny komunikat) →
`Odpowiedz Blad` (RespondToWebhook z `{error}`). Rodowód: bez tej gałęzi
0 wykresów = kolejne węzły dostają zero itemów, workflow nigdy nie dociera
do Respond, webhook wisi do timeoutu, a Python dostawał
`Expecting value: line 1 column 1` (bug B6 z testów manualnych).

## ETAP 4 — Budowa dashboardu w Metabase (HTTP + Code)

Sekwencja (szczegóły API → docs/07):
1. `Metabase Login` → `POST /api/session` (creds admina) → token.
2. `Pobierz Bazy` → `GET /api/database`; `Sprawdź DB` (Code) szuka źródła
   o nazwie = `db_path`; IF `DB Istnieje?` → `Zarejestruj DB`
   (`engine: postgres`, `currentSchema=...`, **user readonly**) — dokładny
   odpowiednik pythonowego `_ensure_metabase_db`.
3. `Scal DB ID` (Code) — łączy token/db_id/charts w jeden item.
4. `Utwórz Dashboard` → `POST /api/dashboard`.
5. `Przygotuj Wykresy` (Code) — NAJWAŻNIEJSZY węzeł ogona; per wykres:
   - znajduje kolumnę daty **TEGO wykresu**: pierwszy kandydat z
     `date_columns`, którego nazwa występuje w SQL-u (`sql.includes(col)`)
     [rodowód: globalna JEDNA kolumna dat psuła bazy wielotabelowe —
     3 różne kolumny dat w firma_uslugi, bug B4],
   - jeśli jest: wstrzykuje `[[AND col >= {{start_date}}]] [[AND col <= {{end_date}}]]`
     przed GROUP/ORDER/LIMIT/HAVING (albo `WHERE 1=1 ...` gdy nie było WHERE),
     `has_date_filter=true`.
6. `Utwórz Kartę` (HTTP, per item) → `POST /api/card` z template-tags
   `start_date`/`end_date` **typu `date`** [rodowód: `type:'text'` powodował
   „There was a problem displaying this chart" po wybraniu daty — mismatch
   z parametrem `date/single`, bug A2].
7. `Zbierz Karty` (Aggregate) → `Zbuduj Układ` (Code): siatka 24-kolumnowa,
   `row=(i//2)*8, col=(i%2)*12, size 12x8`; `parameter_mappings` TYLKO dla
   kart z tagami; parametry dashboardu `Data od`/`Data do` (`date/single`).
   Czyta tagi z `card.dataset_query.stages[0]['template-tags']` z fallbackiem
   na `.native` [rodowód: nowy format MBQL — bez fallbacku filtr na poziomie
   dashboardu nigdy nie powstawał].
8. `Dodaj Parametry` (PUT dashboard) → `Dodaj Karty` (PUT dashboard/cards) →
   `Opublikuj` (POST public_link) → `Odpowiedz` (kontrakt z §0; SQL składany
   z itemów `Generuj SQL...`, licznik retry przekazywany dalej).

## Edycja workflow przez API (bez UI) — procedura sprawdzona

```
POST /rest/login {emailOrLdapLoginId, password}        → cookie n8n-auth
GET  /rest/workflows/{id}                              → nodes, connections, versionId
PATCH /rest/workflows/{id} {nodes, connections}        → NOWY versionId (zapis!)
POST /rest/workflows/{id}/activate {versionId}         → PUBLIKACJA (bez tego webhook
                                                          wykonuje STARĄ wersję; restart
                                                          kontenera NIE pomaga —
                                                          activeVersionId w SQLite)
```
Pułapki znalezione w praktyce:
- **Osierocone `connections`**: po usunięciu węzła z `nodes[]` martwy klucz
  w `connections{}` psuje RespondToWebhook kryptycznym
  `Cannot read properties of undefined (reading 'name')`.
- Dane wykonań (`/rest/executions/{id}`) są serializowane biblioteką
  `flatted` — surowy JSON to tablica indeksów; dekodować:
  `docker exec n8n_local node -e "console.log(JSON.stringify(require('flatted').parse(...)))"`.

## Sprawdź się
1. Odtwórz kontrakt wejścia i wyjścia webhooka z pamięci.
2. Które trzy guardy wykonują się w `process-sql-attempt` PRZED wykonaniem SQL,
   a które dwa PO wykonaniu?
3. Dlaczego dopasowanie kolumny daty musi być per wykres? Podaj bazę-kontrprzykład.
4. Jaki dokładnie objaw ma niezawołanie `activate` po `PATCH`?
5. Czemu retry planu NIE jest pętlą, a retry SQL-a jest?
