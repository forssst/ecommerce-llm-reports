# 02 — Backend: uwierzytelnianie i API publiczne (deep dive)

> Plik: `backend/main.py` (~1550 linii). Tu: auth + wszystkie endpointy publiczne
> z przykładami żądań/odpowiedzi. Endpointy `/internal` → `docs/05`, upload → `docs/03`.

## 1. Uwierzytelnianie

### 1.1. Rejestracja i logowanie

Model wejścia (quirk nazewniczy wart znajomości!):
```python
class UserIn(BaseModel):
    email: str
    password_hash: str   # UWAGA: pole przenosi PLAINTEXT hasło; nazwa historyczna
```
Frontend wysyła hasło w polu `password_hash` — hashowanie robi DOPIERO backend.
Nazwa pola została z czasów, gdy frontend hashował sam; dziś jest myląca
(kandydat na refaktor, opisany, nie zmieniany).

`POST /register`:
```json
// żądanie                                  // odpowiedź 200
{"email":"jan@x.pl","password_hash":"tajne"} → {"id":7,"email":"jan@x.pl","token":"eyJhbGci..."}
// 409, gdy email zajęty
```
Backend: `bcrypt.hashpw(password.encode(), bcrypt.gensalt())` → zapis hasha.

`POST /login` — `bcrypt.checkpw` przeciw hashowi z bazy. Ciekawostka w kodzie:
fallback `password_hash == "x"` dla kont seedowanych przed wprowadzeniem haseł
(stare konta testowe logują się dowolnym hasłem — do usunięcia przy sprzątaniu).

### 1.2. Token JWT — anatomia

`_create_token()` podpisuje HS256 sekretem `JWT_SECRET`:
```json
// payload zdekodowanego tokenu:
{"sub": "7", "email": "jan@x.pl", "exp": 1783947185}
```
- `sub` = user_id (string — standard JWT), `exp` = wygaśnięcie (7 dni).
- Frontend trzyma token w `localStorage` i dokłada nagłówek
  `Authorization: Bearer <token>` do każdego żądania (`authHeaders()`).

### 1.3. Weryfikacja — `verify_token()` jako Depends

```python
def verify_token(authorization: str = Header(None)) -> int:
    # 401 gdy brak nagłówka / zły prefiks
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])  # sprawdza podpis + exp
    return int(payload["sub"])   # -> user_id trafia do endpointu
```
Wpięte przez `Depends(verify_token)` w KAŻDY chroniony endpoint. Zwracany
user_id jest jedynym zaufanym źródłem tożsamości — **wszystkie endpointy
ignorują user_id z body/formularza** (naprawa luki: `/generate` i `/upload`
przyjmują `user_id` w wejściu dla kompatybilności, ale natychmiast go nadpisują).

## 2. Endpointy publiczne — szczegółowo

### `GET /health` (bez auth)
Sprawdza Ollamę (`/api/tags` → lista modeli), Metabase (`/api/health`),
Postgresa (otwarcie połączenia).
```json
{"status":"ok","services":{"ollama":{"ok":true,"models":["qwen2.5-coder:7b",...]},
 "metabase":{"ok":true},"postgres":{"ok":true}}}
// "degraded" gdy cokolwiek pada — frontend może to pokazać
```

### `GET /users/{user_id}/databases`
Kontrola właściciela: `if user_id != token_user_id: 403`.
Dla każdej bazy próbuje pobrać ŚWIEŻY schemat z Postgresa (`get_db_schema`),
z fallbackiem na zapisany `schema_json`:
```json
[{"id":16,"name":"sakila.db","file_path":"u2_sakila",
  "schema":{"actor":[{"name":"actor_id","type":"bigint"},{"name":"first_name","type":"text"},...],
            "film":[...], ...}}]
```
Z tego frontend buduje `schema_text` (patrz docs/08) — czyli **schemat widziany
przez model pochodzi z żywego Postgresa**, nie z cache.

### `DELETE /databases/{db_id}`
404 gdy nie istnieje; 403 gdy cudzy. Jeśli `file_path` pasuje do `^u\d+_`,
wykonuje `DROP SCHEMA ... CASCADE` (dane znikają!) i usuwa wpis.
Lekcja z testów (2026-07-06): przed wprowadzeniem upsertu w uploadzie duble
wpisów współdzieliły schemat — usunięcie jednego osierocało pozostałe.

### `GET /users/{user_id}/queries`
Historia (kontrola właściciela), zwraca m.in. `prompt`, `sql` (JSON z URL-em
dashboardu), `status`, `retry_count`, `created_at`. Frontend wyciąga
`dashboard_url` z pola `sql` do ponownego otwarcia dashboardu.

### `POST /generate` — brama generowania
```json
// żądanie (GenerateIn):
{"user_id":0,                      // ignorowane — bierze z tokenu
 "prompt":"top 5 produktow wedlug sumy sprzedazy",
 "description":"...opis AI albo pusty...",
 "chart_type":"Dokładnie 2 wykresy: (1) Słupkowy, (2) Kołowy",  // buildChartType() z UI, może być ""
 "schema_text":"Tabela sklep_testowy: data_zamowienia (timestamp), ...",
 "db_path":"u35_sklep_testowy",
 "n8n_timeout":300}
```
Kroki: (1) `g.user_id = token_user_id`; (2) lookup wpisu `databases` po
`file_path` (do historii); (3) `_generate_via_n8n_orchestrator()`:
- **wzbogaca schemat**: `schema_text += _text_column_values(db_path)`
  (znane wartości kolumn tekstowych — guard na halucynacje, patrz docs/06),
- POST na webhook n8n (timeout `max(n8n_timeout, 300)`),
- parsuje odpowiedź; brak/niepoprawny JSON → czytelny wyjątek
  („generowanie przerwane — najczęściej Ollama albo Metabase nie odpowiada"),
- zapisuje historię, zwraca:
```json
{"status":"success","metabase":{"url":"http://localhost:3000/public/dashboard/<uuid>"},
 "sql":"-- Tytuł 1\nSELECT ...\n\n-- Tytuł 2\nSELECT ...",
 "retry_count":1,
 "chart_summary":{"requested":3,"generated":3,"failed":0,"failed_titles":[]}}
// każdy wyjątek → {"status":"error","error":"n8n orchestrator error: ..."} + wpis error w historii
```

### `POST /describe-schema`
Guard: pusty `schema_text` → 400 „Brak schematu bazy — odśwież listę baz".
Wywołanie Ollamy BEZ `format:json` (opis to proza), timeout 600 s (duże
schematy na wolnym GPU). Po odpowiedzi: strip znaków CJK/cyrylicy
(`_has_cjk` + regex zakresów Unicode) i czyszczenie podwójnych spacji.

### `POST /clarify-prompt`
`_ollama_json` (timeout 90 s) na szablonie `clarify_prompt` → model zwraca
`{"question": "..."} | {"question": null}`. 503 gdy Ollama niedostępna.
Few-shoty w szablonie są NIEZBĘDNE — bez nich 7B dopytuje o oczywistości.

### `POST /enhance-prompt`
Sekwencja guardów po odpowiedzi modelu (szczegóły docs/06):
odrzucenie CJK → wycięcie linii z SQL-em → usunięcie wymyślonego „TOP N" →
przywrócenie zgubionego „TOP N" → doklejenie zignorowanej odpowiedzi
doprecyzowującej (porównanie rdzeni słów).

### `GET/PUT /prompts`
GET zwraca szablony. PUT waliduje, że każdy edytowany szablon nadal zawiera
WYMAGANE placeholdery (`_PROMPT_PLACEHOLDERS`, parsowanie przez
`string.Formatter`) — inaczej `format()` w runtime by się wywalił; zapis
z powrotem do `prompts.json`. Zakładka UI do tego została świadomie usunięta
(brak ról admin/user — zwykły użytkownik nie powinien edytować globalnej
konfiguracji), endpointy zostały.

### `POST /users` (legacy)
Get-or-create bez hasła — pozostałość sprzed wprowadzenia auth; nieużywany
przez frontend. Kandydat do usunięcia.

## 3. Obsługa błędów — konwencje

- Błędy walidacyjne → 400 z polskim `detail` (frontend pokazuje `data.detail`).
- Brak auth → 401; cudzy zasób → 403; brak zasobu → 404; za duży plik → 413.
- Awaria Ollamy → dedykowane wyjątki `OllamaUnavailableError` /
  `OllamaResponseError` (rozróżnienie: niedostępna vs zła odpowiedź) → 503/500.
- `/generate` NIGDY nie rzuca 500 dla błędów pipeline'u — zwraca
  `{"status":"error", ...}` (frontend ma jedną ścieżkę renderowania błędu).

## Sprawdź się
1. Prześledź drogę hasła od formularza do bazy. Co jest mylące w nazwie pola?
2. Co dokładnie sprawdza `jwt.decode` i co się stanie po 7 dniach?
3. Dlaczego `/generate` przyjmuje `user_id` w body, skoro go ignoruje?
4. Skąd frontend bierze schemat do `schema_text` i czemu jest on zawsze aktualny?
5. Jakie dwa nagłówki/statusy odróżniają „nie zalogowany" od „nie twój zasób"?
