# AI Data Analyst — dokumentacja techniczna systemu

> Stan na 2026-07-06, branch `n8n-experiment`. Dokument pełni trzy role:
> 1) **podręcznik do nauki systemu** (każdy rozdział kończy się pytaniami kontrolnymi),
> 2) **podwaliny pod rozdziały pracy inżynierskiej** (mapowanie na końcu),
> 3) **dokumentacja operacyjna** (jak uruchomić, debugować, mierzyć).

---

## Spis treści

1. [Czym jest system](#1-czym-jest-system)
2. [Architektura](#2-architektura)
3. [Komponenty szczegółowo](#3-komponenty-szczegółowo)
4. [Przepływ generowania — krok po kroku z przykładem](#4-przepływ-generowania)
5. [Guardy — mechanizmy jakości i ich historie](#5-guardy)
6. [Bezpieczeństwo](#6-bezpieczeństwo)
7. [Testowanie](#7-testowanie)
8. [Ewaluacja — wyniki liczbowe](#8-ewaluacja)
9. [Znane ograniczenia](#9-znane-ograniczenia)
10. [Podobne rozwiązania — kontekst](#10-podobne-rozwiązania)
11. [Kierunki rozwoju](#11-kierunki-rozwoju)
12. [Operacje — komendy i debugowanie](#12-operacje)
13. [Słowniczek](#13-słowniczek)
14. [FAQ na obronę](#14-faq-na-obronę)
15. [Mapowanie na rozdziały pracy](#15-mapowanie-na-rozdziały-pracy)

---

## 1. Czym jest system

**AI Data Analyst** — webowa aplikacja typu *self-service BI*: użytkownik wgrywa
własną bazę danych (SQLite/CSV/Excel), opisuje **po polsku** co chce zobaczyć
(np. „TOP 10 produktów według sprzedaży z podziałem miesięcznym"), a system:

1. planuje dashboard (2–4 wykresy),
2. generuje SQL dla każdego wykresu lokalnym modelem językowym,
3. waliduje każdy SQL wykonując go na prawdziwych danych,
4. buduje interaktywny dashboard w Metabase (z filtrem dat) i osadza go w aplikacji.

**Trzy filary koncepcji** (świadome decyzje, nie ograniczenia):
- **Lokalność** — model AI (Ollama + qwen2.5-coder:7b) działa na maszynie
  użytkownika. Dane nigdy nie opuszczają komputera.
- **Prywatność** — brak kluczy API, brak kosztów, działanie offline.
- **Język polski** — cały interfejs, prompty i wyniki po polsku (nietrywialne
  dla małego modelu — patrz rozdz. 9, *language drift*).

**Sprawdź się:** Wymień 3 filary koncepcji i uzasadnij każdy jednym zdaniem.
Co system robi między wpisaniem celu a pokazaniem dashboardu (4 kroki)?

---

## 2. Architektura

### 2.1. Usługi (Docker Compose — 6 kontenerów)

| Usługa | Obraz | Port | Rola |
|---|---|---|---|
| `frontend` | node:22 (build) → nginx:alpine | 5173→80 | React + Vite + Tailwind; kreator, historia, iframe |
| `fastapi_backend` | python:3.12-slim | 8000 | Auth, upload, logika AI (`/internal`), pośrednik do n8n |
| `n8n` | n8nio/n8n:**2.15.1** | 5678 | **Orchestrator generowania** (workflow 29 węzłów) |
| `ollama` | ollama/ollama | 11434 | Lokalny LLM: **qwen2.5-coder:7b** (~4.7 GB) |
| `postgres` | postgres:**16**-alpine | 5432 | Dane wgranych baz (baza `analytics`) |
| `metabase` | metabase/metabase | 3000 | Wizualizacja: karty, dashboardy, publiczne linki |

Plus **SQLite `/data/system.db`** (wolumen backendu) — baza *systemowa*:
konta, metadane baz, historia zapytań.

### 2.2. Diagram przepływu głównego

```
przeglądarka (React)
   │  POST /generate  (JWT)
   ▼
fastapi_backend ──────────────► SQLite system.db (historia)
   │  POST webhook create-dashboard
   ▼
n8n (workflow 29 węzłów) ──── ORCHESTRATOR: kolejność, retry, IF-y
   │        │           │
   │        │           └──► Metabase API (dashboard, karty, filtr dat, publiczny link)
   │        └──► Ollama /api/generate (plan + SQL per wykres)
   └──► backend /internal/... (prompty, guardy, walidacja SQL)
                 │
                 └──► PostgreSQL (wykonanie SQL rolą READ-ONLY)
```

### 2.3. Kluczowe decyzje architektoniczne

**(a) n8n jako orchestrator, logika w Pythonie.** n8n decyduje *co po czym*
(plan → pętla SQL → budowa dashboardu), ale każdą operację *merytoryczną*
(budowa promptu, czyszczenie SQL, walidacja, guardy) wykonuje przez cienkie
endpointy `/internal/...` backendu. **Dlaczego:** guardy były wielokrotnie
poprawiane po realnych bugach — druga kopia w JavaScript rozjechałaby się
po cichu. To wzorzec przemysłowy (Airflow/Temporal: DAG orkiestruje, workery
wykonują). Wyjątek: integracja z Metabase (sekwencja wywołań REST) mieszka
w całości w n8n.

**(b) PostgreSQL, schemat-per-plik.** Upload dowolnego formatu importuje dane
do schematu `u{user_id}_{nazwa}` (np. `u2_northwind`). **Dlaczego:** trwałość,
prawdziwe typy (daty jako TIMESTAMP — warunek działania filtrów), izolacja
użytkowników, natywne połączenie z Metabase, możliwość nadania roli read-only.
W systemowej SQLite jest tylko *wskaźnik* (kolumna `file_path` = nazwa schematu).

**(c) Dwie bazy danych o różnych rolach.** SQLite = metadane aplikacji
(małe, transakcyjne, jeden plik). PostgreSQL = dane analityczne użytkowników
(duże, wymagające typów i SQL-a analitycznego).

**(d) Dwuetapowe generowanie (plan → SQL per wykres).** Małemu modelowi
łatwiej napisać jeden poprawny SQL do wąskiego celu niż cały dashboard naraz.
Dekompozycja = wyższa jakość + niezależna walidacja każdego wykresu.

**Sprawdź się:** Narysuj z pamięci diagram 2.2. Dlaczego logika NIE została
przepisana do n8n? Co dokładnie trzyma `file_path` w tabeli `databases` i czemu
to nie jest ścieżka pliku?

---

## 3. Komponenty szczegółowo

### 3.1. Frontend (`frontend/src/App.jsx` — jeden plik, ~800 linii)

Widoki: logowanie/rejestracja → **Kreator raportów** (główny) → Bazy danych → Historia.

Kluczowe elementy kreatora:
- wybór bazy (dropdown) + zwijana ściąga schematu („Pokaż tabele i kolumny"),
- **Opis bazy danych** — panel z opisem AI (przycisk „Generuj opis AI");
  opis trafia potem do promptów jako dodatkowy kontekst,
- **✦ Ulepsz prompt AI** — dwustopniowy przepływ: najpierw `/clarify-prompt`
  (model może zadać JEDNO pytanie doprecyzowujące), potem `/enhance-prompt`
  (przepisanie celu); istniejący opis bazy jest reużywany (nie generuje się drugi raz),
- **Typy wykresów** — 11 przycisków; wybór wymusza dokładnie te typy w tej kolejności,
- wynik: pasek statusu (⚠ ostrzeżenie o pominiętych wykresach, licznik auto-korekt),
  „Pokaż SQL" (SQL każdej karty), „Otwórz w Metabase", iframe z dashboardem.

Ważne funkcje: `buildSchemaText()` (schemat → tekst dla modelu:
`Tabela X: kol (typ), ...`), `generateDescription()`, `startEnhance()/runEnhance()`,
`handleGenerate()`.

### 3.2. Backend (`backend/main.py` — FastAPI)

**Endpointy publiczne** (wszystkie poza `/register`, `/login`, `/health`
wymagają JWT):

| Endpoint | Metoda | Rola |
|---|---|---|
| `/register`, `/login` | POST | konta; bcrypt + JWT (HS256, z terminem ważności) |
| `/health` | GET | status usług (Ollama, Postgres) |
| `/upload` | POST | import pliku → schemat Postgresa; **upsert** wpisu; limit 150 MB |
| `/users/{id}/databases` | GET | lista baz usera + świeży schemat (kontrola właściciela) |
| `/databases/{id}` | DELETE | usuwa wpis + DROP SCHEMA (kontrola właściciela) |
| `/users/{id}/queries` | GET | historia generacji (kontrola właściciela) |
| `/generate` | POST | **brama generowania** → webhook n8n → zapis historii |
| `/describe-schema` | POST | opis bazy po polsku (bezpośrednio Ollama) |
| `/clarify-prompt` | POST | opcjonalne pytanie doprecyzowujące |
| `/enhance-prompt` | POST | przepisanie celu (guardy TOP N w obie strony) |
| `/prompts` | GET/PUT | podgląd/edycja szablonów promptów (bez UI — świadomie) |

**Endpointy wewnętrzne `/internal/...`** (bez JWT — dostępne tylko w sieci
dockerowej; to *granica zaufania*):

| Endpoint | Co robi dla n8n |
|---|---|
| `/internal/plan-prompt` | składa prompt planowania z szablonu + liczy żądane typy wykresów |
| `/internal/process-plan` | parsuje plan, guard językowy, wymusza typy; `need_retry` |
| `/internal/sql-prompt` | składa prompt SQL (hint typu wykresu, przy retry — poprzedni błąd) |
| `/internal/process-sql-attempt` | czyści SQL, guard TOP N, **wykonuje na Postgresie (read-only)**, walidacja kształtu, guard 0 wierszy |
| `/internal/finalize-chart` | tytuł (guard okresu względnego) + typ wizualizacji |
| `/internal/date-column` | kandydaci na kolumny dat do filtra (lista, per baza) |

**Prompty** żyją w `backend/prompts.json` (ładowane przy starcie):
`plan_prompt`, `sql_prompt`, `sql_retry_suffix`, `describe_schema`,
`enhance_prompt`, `clarify_prompt` (+ warianty `_sqlcoder` — pozostałość
po eksperymencie z modelem sqlcoder).

**Pipeline uploadu** (`/upload`): walidacja rozmiaru → zapis pod LOSOWĄ nazwą
(uuid; obrona przed path traversal) → parsowanie (pandas: .csv/.xlsx/.xls/.db)
→ `DROP+CREATE SCHEMA` → `to_sql` per tabela/arkusz → **detekcja dat**
(hinty nazw PL/EN: `data`, `czas`, `date`… ORAZ próbka wartości ISO;
nieudany cast bezpiecznie wycofywany) → `GRANT USAGE` dla roli read-only →
odczyt schematu → **upsert** wpisu w `databases`.

### 3.3. Workflow n8n („Metabase - Utwórz Dashboard", 29 węzłów)

Etapy (nazwy węzłów jak na canvasie):

1. **Wejście + PLAN**: `Webhook` → `Zbuduj Prompt Planu` → natywne węzły AI
   `LLM Chain: Plan` + `Model Ollama (Plan)` → `Przetworz Plan` →
   IF `Trzeba Retry Planu?` → (`Zbuduj Prompt Retry Planu` → `LLM Chain: Plan Retry`
   → `Przetworz Plan Retry`).
2. **SQL per wykres**: `Generuj SQL i Zbierz Wykresy` (Code node, pętla ≤3 prób
   na wykres: `/internal/sql-prompt` → Ollama `format:json` →
   `/internal/process-sql-attempt` → `finalize-chart`); zbiera `failed_titles`
   i licznik retry. *Dlaczego Code node:* pętla o zmiennej długości w pełni
   natywnie wymagałaby ~15–20 dodatkowych węzłów.
3. **Bramka**: IF `Sa Wykresy?` → fałsz: `Zbuduj Blad Brak Wykresow` → `Odpowiedz Blad`.
4. **Metabase**: `Metabase Login` → `Pobierz Bazy` → `Sprawdź DB` → IF `DB Istnieje?`
   → `Zarejestruj DB` (creds **readonly**) → `Scal DB ID` → `Utwórz Dashboard` →
   `Przygotuj Wykresy` (dokleja `[[AND kolumna >= {{start_date}}]]`, dobierając
   kolumnę daty **per wykres** z listy kandydatów) → `Utwórz Kartę` (×N, tagi typu
   `date`) → `Zbierz Karty` → `Zbuduj Układ` (siatka + spięcie parametrów
   dashboardu z tagami kart; czyta `dataset_query.stages[0]` — nowy format MBQL) →
   `Dodaj Parametry` → `Dodaj Karty` → `Opublikuj` → `Odpowiedz`
   (JSON: `url`, `sql` wszystkich kart, `requested/generated/failed/failed_titles`, `retries`).

**Pułapka wersjonowania n8n** (kosztowała nas godziny): `PATCH /rest/workflows/{id}`
zapisuje zmiany, ale webhook wykonuje STARĄ wersję dopóki nie wywoła się
`POST /rest/workflows/{id}/activate {versionId}` — kolumny `versionId` vs
`activeVersionId` w `workflow_entity`. Restart kontenera NIE pomaga.

Eksport workflow do repo: `n8n_orchestrator_workflow.json` (żeby przetrwał
gitignorowany `n8n_config/`).

### 3.4. Model AI (Ollama)

- `qwen2.5-coder:7b` — model 7B nastawiony na kod; wybrany jako kompromis
  jakość/rozmiar dla lokalnego sprzętu.
- Wołany dwojako: natywne węzły n8n (etap planu; zwraca `$json.text`, bywa
  owinięty w ```` ```json ````) i surowe HTTP `POST /api/generate`
  z `format:"json"` (etap SQL — wymusza poprawny JSON).
- Kontekst przekazywany modelowi: schemat bazy (tekst), opis AI (opcjonalny),
  **znane wartości kolumn tekstowych** (patrz guard 5.11), cel użytkownika,
  hint typu wykresu, a przy retry — poprzedni SQL + treść błędu.
- Sprzęt referencyjny: GTX 1060 3 GB → model liczy w ~83% na CPU → ~5,6 tok./s;
  stąd czasy ~60–150 s na dashboard. Na lepszym GPU byłoby wielokrotnie szybciej.

### 3.5. PostgreSQL

- Baza `analytics`; właściciel `analyst` (import, DDL przy uploadzie).
- **Rola `readonly`** — tworzona idempotentnie przy starcie backendu
  (`_ensure_readonly_role`): `SELECT`-only na schematach użytkowników;
  wykonuje CAŁY SQL pochodzący od modelu (walidacja + karty Metabase).
- `ALTER DEFAULT PRIVILEGES` sprawia, że tabele z przyszłych uploadów
  automatycznie dostają SELECT dla readonly.

### 3.6. Metabase

- Backend loguje się kontem administracyjnym (creds w `main.py` — znane
  ograniczenie: produkcyjnie do zmiennych środowiskowych).
- Auto-rejestracja bazy: jeśli schematu nie ma wśród źródeł Metabase, tworzone
  jest połączenie `engine: postgres` z `currentSchema={schemat}` i **rolą readonly**.
- Karta = *native question* (SQL) + `visualization_settings` (typ wykresu,
  wymiary/miary) + template-tags `start_date`/`end_date` (typ `date`).
- Dashboard: parametry „Data od"/„Data do" (`date/single`) spięte z tagami kart;
  publikacja przez **public link** (UUID) osadzany w iframe.
- Gotcha: ta wersja Metabase zwraca zapytania kart w nowym formacie MBQL
  (`dataset_query.stages[0]`), nie `dataset_query.native`.

**Sprawdź się:** Które endpointy nie wymagają JWT i dlaczego to bezpieczne
(słowo-klucz: granica zaufania)? Po co są DWA sposoby wołania Ollamy w n8n?
Co się stanie, gdy zapomnisz `activate` po `PATCH` workflow?

---

## 4. Przepływ generowania

Prześledźmy PRAWDZIWY przykład: baza `sklep_testowy` (1500 zamówień z 2024 r.),
cel: **„top 5 produktow wedlug sumy sprzedazy"**.

1. **Frontend** składa `schema_text`:
   `Tabela sklep_testowy: data_zamowienia (timestamp), produkt (text), ... wartosc_zamowienia (double)`
   i wysyła `POST /generate` z JWT.
2. **Backend**: user_id z tokenu (nie z body!), dokleja do schematu **znane
   wartości kolumn tekstowych** (np. `kategoria: 'AGD', 'Elektronika', ...`),
   woła webhook n8n.
3. **n8n — PLAN**: model zwraca np.
   ```json
   {"charts": [
     {"title": "Top 5 produktów według sumy sprzedaży", "chart_type": "bar",
      "goal": "5 produktów o najwyższej sumie wartości zamówień"},
     {"title": "Zysk ze sprzedaży przez miesiące", "chart_type": "line", ...},
     {"title": "Podział sprzedaży po kategoriach", "chart_type": "pie", ...}]}
   ```
   `process-plan` sprawdza język (polski ✓) i ewentualne wymuszone typy.
4. **n8n — SQL** (dla wykresu 1): model pisze
   `SELECT produkt, SUM(wartosc_zamowienia) AS suma FROM sklep_testowy GROUP BY produkt ORDER BY suma DESC`
   → `process-sql-attempt`: czyszczenie ✓, goal zawiera „5" przy „top" a SQL
   nie ma LIMIT → **doklejone `LIMIT 5`** → wykonanie rolą readonly ✓,
   5 wierszy, kolumny `[produkt, suma]` ✓ → `finalize-chart`: display `bar`.
   Analogicznie wykresy 2–3 (trend dostaje `line`, podział `pie`).
5. **n8n — Metabase**: baza już zarejestrowana → dashboard → 3 karty (trend
   dostaje tagi dat, bo jego SQL używa `data_zamowienia`) → układ + parametry
   „Data od/do" → publiczny link.
6. **Odpowiedź** → backend zapisuje historię → frontend: iframe + „Pokaż SQL"
   + ewentualne ostrzeżenia. Czas na sprzęcie referencyjnym: ~57 s.

**Ścieżka błędu** (przykład z testów): SQL z `WHERE status = 'podpisana'`
(halucynacja) → 0 wierszy → guard zwraca błąd z podpowiedzią → model dostaje
błąd w prompcie retry → poprawia lub (po 3 próbach) wykres jest pomijany
i trafia do żółtego ostrzeżenia. Przy 0 wykresów — czytelny błąd całości.

**Sprawdź się:** Opowiedz ten przepływ na głos bez patrzenia (6 kroków).
W którym momencie i czym różni się ścieżka błędu od ścieżki sukcesu?

---

## 5. Guardy

Filozofia (sprawdzona wielokrotnie w tym projekcie): **instrukcja w prompcie
NIE wystarcza** — mały model łamie zasady niedeterministycznie. Każda reguła
ma więc dwie warstwy: instrukcję w prompcie **+ deterministyczny guard w kodzie**.
Każdy guard poniżej powstał z KONKRETNEGO buga znalezionego w testach.

| # | Guard | Problem, który go zrodził | Mechanizm |
|---|---|---|---|
| 1 | `_clean_sql` | model owija SQL w backticki, dokleja „sql:", zwraca kilka zapytań | regexy czyszczące, bierze pierwsze zapytanie |
| 2 | strip CJK/cyrylicy | „branży电子商务", „Wключaj" w polskim opisie | regex zakresów Unicode w `/describe-schema` |
| 3 | `_is_foreign_language` | CAŁY plan po węgiersku przy pustym opisie | detekcja obcych diakrytyków (polskie dozwolone) → jeden retry planu → fallback tytułu |
| 4 | `_RELATIVE_DATE_FILTER` | `WHERE data >= CURRENT_DATE - INTERVAL '12 months'` przy danych z 2024 i zegarze 2026 → pusto | odrzucenie SQL z tym wzorcem + wskazówka |
| 5 | `_RELATIVE_PERIOD_IN_TITLE` | tytuł obiecuje „ostatnie 3 miesiące", choć filtr usunięto w retry | wycięcie frazy z tytułu gdy SQL bez WHERE |
| 6 | `_check_smartscalar_shape` | Licznik (smartscalar) = wykres TRENDU w Metabase; zła 1. kolumna → błąd karty | walidacja kształtu (pierwsza kolumna: data) + hint |
| 7 | `_check_label_column` | etykiety = ID zamiast nazw | walidacja pierwszej kolumny + hint |
| 8 | TOP bez liczby (enhance) | „top produkty" → model wymyślał „TOP 20" | usunięcie liczby, gdy user jej nie podał |
| 9 | TOP N zgubiony (enhance) | „TOP 10..." → enhance gubił limit (test F4) | dopisanie „Zachowaj limit: TOP N" gdy liczba z `top N` znikła |
| 10 | TOP N w SQL | limit w celu, SQL bez `LIMIT` → 40 słupków | deterministyczne doklejenie `LIMIT N` (per wykres, wg goal) |
| 11 | `_text_column_values` | `WHERE status='podpisana'`, a wartości to `zakończona/w trakcie/anulowana` (test B4) | do kontekstu modelu dołączane są PRAWDZIWE wartości kolumn tekstowych (2–8 wariantów, próbka 500 wierszy) |
| 12 | 0 wierszy | poprawny SQL, pusty wynik → karta „No results!" | błąd walidacji z hintem → retry → pominięcie z ostrzeżeniem |
| 13 | 0 wykresów (n8n IF) | webhook wisiał bez odpowiedzi (test B6) | jawna gałąź błędu z czytelnym komunikatem |
| 14 | rdzenie słów (enhance) | model ignorował odpowiedź doprecyzowującą | porównanie rdzeni (5 znaków) → doklejenie odpowiedzi |
| 15 | `_parse_requested_charts` | 5 z 11 typów wykresów było ignorowanych | pełna mapa słów kluczowych PL→typ Metabase |
| 16 | read-only SQL | LLM mógłby wygenerować DROP/DELETE | rola Postgresa — obrona uprawnieniami, nie parsowaniem |

**Granica guardów deterministycznych** (ważny wątek do pracy): guard rdzeni
słów nie wykryje PRZEKRĘCENIA SENSU (słowo jest, znaczenie inne); detekcja
języka nie łapie angielskiego (bez słownika się nie da); tytuł może obiecywać
„kategorie", a SQL grupować po miesiącach. Tam, gdzie kończy się determinizm,
zaczyna się dokumentowanie ograniczeń (rozdz. 9).

**Sprawdź się:** Wybierz 3 dowolne guardy i opowiedz: jaki bug → jaka naprawa.
Dlaczego sama instrukcja w prompcie nie wystarcza? Który guard NIE jest
w Pythonie i gdzie jest?

---

## 6. Bezpieczeństwo

### 6.1. Model zagrożeń i wdrożone obrony

| Warstwa | Obrona |
|---|---|
| Hasła | bcrypt (hash+salt), nigdy plaintext |
| Sesje | JWT HS256 z terminem ważności; `Depends(verify_token)` na endpointach |
| Autoryzacja | user_id **z tokenu**, nie z requesta; kontrola właściciela zasobów (naprawione IDOR-y na `/users/{id}/...` i `DELETE /databases`) |
| Upload | limit 150 MB, losowa nazwa pliku na dysku (path traversal), walidacja treści, 400 zamiast 500 |
| SQL od modelu | **rola read-only w Postgresie** — DROP/DELETE/UPDATE fizycznie niemożliwe (walidacja i karty Metabase) |
| Izolacja danych | schemat-per-user w Postgresie; historia i bazy filtrowane po user_id |
| `/internal/...` | bez JWT, ale nieosiągalne spoza sieci dockerowej — **granica zaufania** |

Historia ma wartość dowodową: **4 luki znalezione własnymi testami → 4 naprawione**,
z testami regresyjnymi (31 przypadków pytest, 0 porażek).

### 6.2. Czego świadomie brakuje (lokalne demo ≠ produkcja)

- sekrety (JWT secret, hasła Metabase) w kodzie → do zmiennych środowiskowych,
- brak HTTPS, rate-limitingu, blokady kont po nieudanych logowaniach,
- porty n8n/Metabase/Postgresa wystawione na localhost (wygoda debugowania),
- publiczne linki Metabase: kto ma URL, ten widzi dashboard (patrz rozdz. 11 —
  signed embedding / kolekcje per user).

**Sprawdź się:** Czym różni się uwierzytelnianie od autoryzacji — pokaż na
przykładzie `DELETE /databases/{id}`. Dlaczego read-only to obrona lepsza niż
parsowanie SQL-a w poszukiwaniu „DROP"?

---

## 7. Testowanie

Cztery uzupełniające się poziomy:

### 7.1. Testy automatyczne (pytest, `tests/`) — **31 passed, 0 xfailed**
Bloki: tokeny JWT (manipulacja, brak, cudzy), izolacja użytkowników
(A nie widzi zasobów B, nie może generować jako B), walidacja uploadu
(za duży plik, uszkodzony plik, path traversal), read-only SQL (DDL odrzucany
na poziomie uprawnień). Uruchamianie: `PG_HOST=localhost venv/bin/pytest tests/`.

### 7.2. Testy manualne (`pliki_testowe/PLAN_TESTOW.md`) — 9 bloków, ~49 scenariuszy
A (regresja sklep) · B (Excel wieloarkuszowy, polskie daty) · C (.xls, ~10k wierszy)
· D (SQLite, CamelCase, JOIN-y) · E (sakila — stres JOIN-ów) · F (przekrojowe
i negatywne) · **G (reagowanie na awarie: stop Ollama/n8n/Metabase, destrukcyjny
prompt, zepsuty JWT)** · H (olist ~100 tys. wierszy — skala) · I (Chinook —
JOIN 5 tabel). Wykonane w całości; **~10 realnych bugów znalezionych i
naprawionych** w trakcie (m.in. filtr dat per wykres, halucynowane wartości
kolumn, kasujące się duble baz).

### 7.3. Harness ewaluacyjny (`eval_harness.py`)
18 promptów × 5 baz × 3 poziomy trudności, pełna ścieżka produkcyjna, metryki
per prompt (status, czas, wykresy zaplanowane/zwalidowane, retry) → CSV +
podsumowanie. Powtarzalny — po każdej zmianie można zmierzyć, czy jest lepiej.

### 7.4. Golden set (`golden_set.py`) — poprawność MERYTORYCZNA
5 promptów z ręcznie napisanym wzorcowym SQL; porównywane są **WYNIKI zapytań**
(nie tekst SQL) po normalizacji; dwa poziomy: EXACT (wiersze identyczne)
i VALUES (wartości liczbowe + liczba wierszy zgodne).

**Sprawdź się:** Czym różni się to, co mierzy harness, od tego, co mierzy
golden set? Po co porównywać WYNIKI zapytań zamiast tekstu SQL?

---

## 8. Ewaluacja

Wyniki zmierzone (sprzęt referencyjny: GTX 1060 3 GB → inferencja ~83% na CPU):

| Pomiar | Wynik |
|---|---|
| **Harness: skuteczność na poziomie dashboardu** | **18/18 (100%)** — łatwe 3/3, średnie 8/8, trudne 7/7 |
| Harness: skuteczność pojedynczych wykresów | **47/54 (87%)** — porażki w najtrudniejszych JOIN-ach |
| Harness: auto-korekty SQL (retry) | 29 łącznie |
| Harness: czas generacji | mediana **89,6 s** (57–150 s) |
| **Golden set: zgodność wartości** | **5/5 (100%)** |
| Golden set: zgodność pełna (EXACT) | 4/5 (jedyna różnica: format etykiety, nie dane) |
| **Stress-test: N równoczesnych generacji** | N=1: ~61 s · N=2: ~123 s · N=3: ~202 s (100% sukcesów, degradacja liniowa) |
| Stress-test: granica | N=5 → 40% błędów; przyczyna zidentyfikowana: sztywny timeout 120 s vs kolejkowanie Ollamy |
| Testy bezpieczeństwa | 4 luki znalezione → 4 naprawione; 31/31 pytest |

**Interpretacje do pracy:**
- Rozróżnienie metryk dashboard/wykres pokazuje wartość **warstwowej
  odporności**: retry → pominięcie → ostrzeżenie zamienia porażki cząstkowe
  w częściowy sukces zamiast błędu całości.
- Degradacja liniowa przy N≤3 = Ollama uczciwie kolejkuje; granica skalowania
  jest **znaleziona, zmierzona i wyjaśniona** (nie „system czasem pada").
- Czasy są własnością sprzętu (VRAM), nie architektury — warto pokazać
  przeliczenie: przy pełnym GPU ~5–8× szybciej.

---

## 9. Znane ograniczenia

Świadomie udokumentowane zamiast naprawiane na siłę (granica możliwości
modelu 7B) — materiał do rozdziału „Ewaluacja/Dyskusja":

1. **Language drift** — przy słabym kontekście model dryfuje do innych języków;
   złapane 4: chiński, rosyjski, węgierski (guardy łapią), angielski (nie do
   wykrycia deterministycznie bez słownika).
2. **Złożone JOIN-y (3–5 tabel)** — spadek skuteczności per wykres (87%);
   najtrudniejsze przypadki: northwind kwartalny przychód, sakila średnia
   długość filmu wg kategorii.
3. **Wykres kaskadowy (waterfall)** — notorycznie za trudny dla 7B.
4. **Semantyczne poślizgi** — tytuł ≠ SQL (np. „Podział na kategorie",
   a grupowanie po miesiącu; „Dyskryminacja Produkty" zamiast „Rozkład").
5. **Planner wypełnia dashboard** — wąski cel (materiał na 1 wykres) → model
   dorabia 2 wykresy „z inwencji" (czasem przepisane z opisu AI — „opis
   rozprasza plan"). Obejście: jawny wybór typów wykresów.
6. **Własności danych mylące na demo** — northwind kończy się na 2023-10
   (prompt o 2024 → pusto), sakila ma wszystkich klientów z jednej sekundy,
   northwind ma puste tabele demograficzne. To nie bugi — ale trzeba umieć
   je rozpoznać.

---

## 10. Podobne rozwiązania

Kontekst rynkowy/naukowy (rozdział „Przegląd istniejących rozwiązań"):

**Komercyjne BI z NL:**
- **Metabase Metabot** — wbudowany asystent AI Metabase (chmurowy, wymaga
  kluczy API); nasz system używa Metabase TYLKO jako warstwy wizualizacji,
  a „mózg" jest lokalny.
- **Tableau (Ask Data / Pulse)**, **Power BI (Q&A, Copilot)**, **Amazon
  QuickSight Q**, **ThoughtSpot (Sage)** — pytania w języku naturalnym nad
  danymi; wszystkie chmurowe, po angielsku, płatne, dane wychodzą do dostawcy.

**Open source / badawcze:**
- **Vanna.AI**, **WrenAI**, **DB-GPT** — frameworki text-to-SQL (często
  z RAG nad schematem); zwykle generują JEDNO zapytanie, nie cały dashboard.
- Benchmarki akademickie **Spider / BIRD** — standard oceny text-to-SQL;
  nasz golden set to ta sama idea w miniaturze (porównanie wyników wykonania,
  *execution accuracy*).

**Czym ten system się wyróżnia:** (1) w pełni lokalny/offline (prywatność,
zero kosztów), (2) język polski end-to-end (z guardami na language drift
małego modelu), (3) generuje CAŁY dashboard (plan wielowykresowy + filtr dat),
nie jedno zapytanie, (4) warstwowa odporność z jawnym raportowaniem porażek,
(5) zmierzona ewaluacja (harness + golden set + stress-test).

---

## 11. Kierunki rozwoju

Uporządkowane wg wartość/koszt:

1. **Większy model lub lepszy GPU** — najprostsza dźwignia jakości JOIN-ów
   i czasów; architektura gotowa (zmiana jednej zmiennej `OLLAMA_MODEL`).
2. **Izolacja w Metabase**: kolekcje + grupy uprawnień per user (OSS, darmowe)
   albo **signed embedding** (podpisane tokeny zamiast publicznych linków).
3. **Zapis i ponowne otwieranie dashboardów** — tabela `reports` już istnieje
   w modelach, nieużywana.
4. **Streaming postępu generacji** (SSE/WebSocket) — dziś user czeka ~90 s
   z ogólnym spinnerem; etapy (plan → SQL 1/3 → …) są znane w n8n.
5. **Produkcyjne wdrożenie**: sekrety do env, HTTPS, rate limiting, schowanie
   portów wewnętrznych.
6. **Rozszerzony golden set** (20–30 promptów) + próg regresyjny w CI.
7. **RAG nad schematem** dla bardzo dużych baz (embeddingi kolumn zamiast
   pełnego schematu w prompcie).
8. **Globalny filtr/interaktywność** w Metabase; **podsumowanie wyników
   po polsku** generowane przez LLM (efektowne na demo).

---

## 12. Operacje

```bash
# start całości (w katalogu projektu)
docker compose up -d --build ollama metabase n8n fastapi_backend frontend postgres
# model (jednorazowo)
docker exec -it ollama ollama pull qwen2.5-coder:7b

# logi na żywo
docker logs -f fastapi_backend        # w tym [sql-attempt FAIL] i [describe-schema ERROR]
docker logs -f n8n_local
docker exec ollama ollama ps          # ile modelu na GPU vs CPU

# testy
PG_HOST=localhost venv/bin/pytest tests/          # 31 testów (venv głównego projektu)
venv/bin/python eval_harness.py [--smoke|--db X]  # harness
venv/bin/python golden_set.py                     # golden set
python3 stress_test_ollama.py                     # stress-test

# n8n przez API (edycja workflow bez UI)
POST /rest/login {emailOrLdapLoginId, password}    → cookie
GET/PATCH /rest/workflows/{id}                     → zmiana zwraca nowy versionId
POST /rest/workflows/{id}/activate {versionId}     → BEZ TEGO webhook używa starej wersji!
# dane wykonań: serializacja 'flatted' — dekodować przez node -e "require('flatted').parse(...)"

# Postgres — szybkie zerknięcie w dane
docker exec postgres_analytics psql -U readonly -d analytics \
  -c "SELECT ... FROM u2_northwind.orders LIMIT 5;"
```

Znane pułapki operacyjne: backend NIE ma wolumenu z kodem (zmiany w `main.py`
wymagają `--build`, restart nie wystarczy); Metabase wymaga `Xms ≤ Xmx`;
konto admina Metabase musi zgadzać się z creds w `main.py`.

---

## 13. Słowniczek

- **Orchestrator** — narzędzie prowadzące wieloetapowy proces (kolejność,
  retry, rozgałęzienia); nie zawiera logiki domenowej, woła workerów
  (tu: n8n woła backend). Przemysłowe odpowiedniki: Airflow, Temporal.
- **Guard** — deterministyczne zabezpieczenie w kodzie egzekwujące regułę,
  której model nie przestrzega niezawodnie.
- **Harness (eval)** — automatyczna ławka testowa z metrykami dla systemu z LLM.
- **Golden set** — zestaw przypadków z ręcznie przygotowanym wzorcem;
  miara *execution accuracy* (zgodność wyników wykonania).
- **JWT** — podpisany token sesji; **bcrypt** — powolny hash haseł z solą.
- **IDOR** — dostęp do cudzego zasobu przez podmianę ID; naprawiony kontrolą właściciela.
- **Granica zaufania** — linia, za którą żądania uznajemy za zaufane
  (tu: wewnętrzna sieć dockerowa dla `/internal`).
- **Schemat-per-user** — izolacja danych: każdy upload = osobny schemat Postgresa.
- **MBQL / native question** — formaty zapytań Metabase; karty tworzymy jako native (SQL).
- **Template-tag / parametr dashboardu** — mechanizm filtrów Metabase
  (`[[AND col >= {{start_date}}]]` + parametr `date/single`).
- **Language drift** — dryf małego modelu do innego języka przy słabym kontekście.
- **Execution accuracy** — porównanie WYNIKÓW zapytań zamiast ich tekstu.

---

## 14. FAQ na obronę

**„Dlaczego lokalny model, nie ChatGPT?"** Prywatność (dane nie wychodzą),
zero kosztów API, offline. Świadoma decyzja architektoniczna — cała reszta
projektu (guardy, ewaluacja) wynika z konsekwencji tej decyzji (mały model
wymaga zabezpieczeń).

**„Po co n8n, skoro logika i tak w Pythonie?"** Bo od orkiestracji jest
orchestrator, a od logiki — kod. n8n dostał control-flow (widoczny,
modyfikowalny bez rebuildu), Python zachował logikę w JEDNYM miejscu
(`/internal`), by uniknąć rozjazdu dwóch implementacji. Wzorzec z Airflow/
Temporal. Koszt zmierzony (narzut czasowy, pułapka `activeVersionId`) i opisany.

**„Co, jeśli model wygeneruje złośliwy/zły SQL?"** Trzy warstwy: (1) SQL
wykonuje ROLA READ-ONLY — DROP/DELETE fizycznie niemożliwe; (2) walidacja
przez wykonanie — błąd wraca do modelu (≤3 próby); (3) porażka = pominięcie
wykresu z jawnym ostrzeżeniem, nie awaria całości.

**„Ile osób może używać naraz?"** Zmierzone: do 3 równoczesnych generacji
komplet sukcesów (czas rośnie liniowo — Ollama kolejkuje); przy 5 błędy
z konkretnej przyczyny (timeout 120 s). Izolacja danych pełna (JWT + schematy
+ testy izolacji).

**„Skąd wiadomo, że SQL jest POPRAWNY, a nie tylko wykonywalny?"** Golden set:
5 promptów z ręcznym wzorcem, porównanie WYNIKÓW — 100% zgodności wartości.

**„Największy wniosek z projektu?"** Mały lokalny model NIE jest niezawodny —
niezawodny jest dopiero SYSTEM wokół niego: dekompozycja problemu, walidacja
przez wykonanie, deterministyczne guardy, warstwowa odporność i pomiar.
Każdy guard w tym systemie ma historię konkretnego buga z testów.

**„Czego pan NIE zrobił i dlaczego?"** (lista z rozdz. 6.2 i 11 — umieć
wymienić 3 pozycje z uzasadnieniem „lokalne demo vs produkcja").

---

## 15. Mapowanie na rozdziały pracy

| Rozdział pracy | Materiał w tej dokumentacji |
|---|---|
| Wstęp, cel i zakres | rozdz. 1 |
| Przegląd istniejących rozwiązań | rozdz. 10 |
| Technologie | rozdz. 2.1, 3 (opisy komponentów) |
| Architektura i projekt systemu | rozdz. 2, 3, 4 (+ decyzje 2.3) |
| Implementacja | rozdz. 3, 4, 5 (guardy jako studium przypadków) |
| Bezpieczeństwo | rozdz. 6 (+ historia 4 luk z testów) |
| Testowanie | rozdz. 7 (4 poziomy) |
| Ewaluacja / wyniki | rozdz. 8 (tabela liczb), 9 (dyskusja ograniczeń) |
| Wnioski i kierunki rozwoju | rozdz. 11, FAQ („największy wniosek") |

> **Plan nauki (2026-07-07):** rano — rozdz. 1–4 + pytania kontrolne;
> południe — canvas n8n na żywo (localhost:5678) węzeł po węźle + rozdz. 5;
> popołudnie — rozdz. 6–8 + przećwiczenie FAQ na głos.
