# CLAUDE.md — kontekst projektu dla Claude Code

## Zasady współpracy
- **Odpowiadaj po polsku.**
- To jest **praca inżynierska** (NIE magisterska). Zmiany rób skupione i proste — bez
  nadmiernej inżynierii. Tłumacz, co i dlaczego zmieniasz (autor się uczy projektu).
- Architektura jest celowo **lokalna** (prywatność danych, brak kosztów API, działanie
  offline). Nie proponuj zamiany lokalnego modelu na chmurowy, chyba że autor o to poprosi.
- Po edycji `backend/main.py` sprawdzaj składnię: `python -m py_compile backend/main.py`.
- **Nie commituj** sekretów, danych ani wolumenów — patrz `.gitignore` (venv, data,
  uploads, metabase-data, *.sqlite, *.db itd.).

## Czym jest projekt
System „AI Data Analyst": użytkownik pisze zapytanie po polsku, system zamienia je na SQL,
wykonuje na bazie i prezentuje wynik jako interaktywny dashboard w Metabase.

## Stack i usługi (Docker Compose)
- **frontend** — React + Vite + Tailwind. Uruchamiany OSOBNO (nie ma go w compose):
  `cd frontend && npm install && npm run dev` → http://localhost:5173
- **fastapi_backend** — FastAPI, cała logika (`backend/main.py`), port 8000
- **ollama** — model `qwen2.5-coder:7b`, port 11434
- **metabase** — wizualizacja, port 3000
- **n8n_local** — zapasowa orkiestracja (webhook `sales-report`), port 5678
- (legacy) **streamlit**, **task-runners** — nieużywane, można ignorować

## Przepływ (najważniejsze)
1. Front składa `schema_text` ze schematu wybranej bazy i woła `POST /generate`.
2. Ścieżka GŁÓWNA: `_generate_multichart` (bezpośrednio Ollama, `format: json`), dwa etapy:
   - planowanie: model rozbija cel na 2–4 wykresy `{title, chart_type, goal}`;
   - generowanie: osobny SQL na każdy wykres, walidowany na PRAWDZIWYM pliku przez
     `_run_and_validate`, z retry ≤2 (błąd wraca do modelu jako wskazówka).
3. Budowa dashboardu w Metabase: `_ensure_metabase_db` (auto-rejestracja bazy, jeśli jej
   nie ma) → `create_metabase_dashboard` → `create_metabase_card` (native SQL) →
   publikacja publicznego linku.
4. Front osadza dashboard przez `<iframe>`.
5. Ścieżka ZAPASOWA: jeśli `_generate_multichart` rzuci wyjątek → webhook n8n.

## Kluczowe pliki
- `backend/main.py` — endpoints i cała logika (auth, upload, generate, integracja Metabase)
- `backend/models.py`, `backend/database.py` — modele i połączenie z bazą systemową
- `frontend/src/App.jsx` — interfejs (logowanie, kreator, historia, iframe)
- `docker-compose.yml` — definicja usług

## Kluczowe funkcje w main.py
- `/register`, `/login` — konta, hasła bcrypt
- `/upload` — zapis pliku bazy + odczyt schematu (`get_db_schema`)
- `/generate` → `_generate_multichart`
- `_ollama_json`, `_run_and_validate`, `_config_hint`, `_infer_display`
- `_get_metabase_token`, `_ensure_metabase_db`, `create_metabase_dashboard`,
  `create_metabase_card`, `publish_metabase_dashboard`

## Architektura danych
- **Baza systemowa** (SQLite `/data/system.db`): tabele `users`, `databases`
  (metadane: nazwa, `file_path`, `schema_json`), `queries` (historia promptów),
  `reports` (zdefiniowana, jeszcze nieużywana).
- **Wgrane bazy** — pliki `.db` na wolumenie `/data/uploads` (Metabase widzi je pod
  `/mb-uploads`). W bazie systemowej jest tylko wskaźnik do pliku, nie dane.

## Komendy
```bash
# usługi (bez legacy)
docker compose up -d --build ollama metabase n8n fastapi_backend
# model
docker exec -it ollama ollama pull qwen2.5-coder:7b
# frontend
cd frontend && npm install && npm run dev
# logi na żywo
docker logs -f fastapi_backend
docker logs -f ollama
```

## Pułapki (znane)
- Konto admina **Metabase musi pasować** do `METABASE_USER`/`METABASE_PASSWORD`
  zaszytych w `main.py` (sprawdź: `grep -iE "METABASE_USER|METABASE_PASSWORD" backend/main.py`).
  Inaczej backend nie zaloguje się do API Metabase.
- Metabase wymaga `JAVA_OPTS=-Xms256m -Xmx1g` (Xms ≤ Xmx), inaczej pętla restartu.
- „There was a problem displaying this chart" → karta celuje w złą bazę: plik musi być
  widoczny dla Metabase (`/mb-uploads`) i podłączony (auto-rejestracja ogarnia to przy generacji).
- Compose przekazuje zmienne `MB_*`, ale `main.py` czyta `METABASE_*` — to częściowo
  martwe zmienne; faktyczne creds są w kodzie.
- `n8n-task-runners.json` jest w `.gitignore`, więc usługa `task-runners` nie zbuduje się
  na czystym klonie — pomijaj ją (`... up -d --build ollama metabase n8n fastapi_backend`).

## Pomysły na rozbudowę (kontekst, gdyby autor pytał)
- Podsumowanie wyników po polsku generowane przez LLM (dobry efekt na demo).
- Zapis i ponowne otwieranie dashboardów (podłączenie nieużywanej tabeli `reports`).
- Globalny filtr w Metabase (interaktywność).
- Harness ewaluacyjny (zestaw promptów + metryki: % poprawnych SQL, retry, czas) — materiał
  do rozdziału „Ewaluacja".
- SQL tylko do odczytu + zabezpieczenie uploadu (sanityzacja nazw, limit rozmiaru, walidacja
  że to SQLite).
