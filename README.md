# ecommerce-llm-reports

Prototyp systemu do dynamicznego generowania raportów sprzedażowych w e-commerce
z wykorzystaniem dużych modeli językowych (LLM). Użytkownik formułuje zapytanie w
języku naturalnym (polskim), a system zamienia je na zapytanie SQL, wykonuje je na
bazie danych i prezentuje wynik w postaci interaktywnego dashboardu.

Projekt realizowany jako **praca inżynierska**.

## Jak to działa

Przepływ: **React → FastAPI → n8n (orkiestracja) → Ollama (LLM) → walidacja SQL na
bazie → Metabase**.

1. Użytkownik wybiera bazę danych i opisuje cel analizy po polsku.
2. Backend przekazuje żądanie do przepływu n8n, który rozbija cel na zestaw wykresów,
   wołając lokalny model językowy.
3. Dla każdego wykresu powstaje osobne zapytanie SQL, walidowane przez wykonanie na
   prawdziwych danych; błędne zapytanie wraca do modelu wraz z treścią błędu (do trzech prób).
4. n8n buduje dashboard w Metabase, publikuje go i zwraca link, który frontend osadza.
   Logika (budowa promptów, czyszczenie i walidacja SQL, zabezpieczenia) pozostaje po
   stronie backendu, wołana przez n8n jako punkty końcowe `/internal/...`.

## Stack technologiczny

- **Frontend:** React + Vite + Tailwind
- **Backend:** FastAPI (Python), SQLAlchemy + SQLite (baza systemowa)
- **Dane analityczne:** PostgreSQL (osobny schemat na każdą wgraną bazę)
- **Model językowy:** Ollama (qwen2.5-coder:7b)
- **Wizualizacja:** Metabase
- **Orkiestracja:** n8n (główna ścieżka generowania dashboardu)
- **Konteneryzacja:** Docker Compose

## Architektura danych

- **Baza systemowa** (SQLite) przechowuje użytkowników, metadane wgranych baz oraz
  historię zapytań.
- **Wgrane dane** trafiają do PostgreSQL, do osobnego schematu na każdą wgraną bazę;
  w bazie systemowej znajduje się tylko wskaźnik do schematu i wykryta struktura tabel.
- **Dashboardy** żyją w Metabase; backend steruje nimi przez API i osadza publiczny link.

## Struktura repozytorium

- `backend/` — API i logika aplikacji (FastAPI)
- `frontend/` — interfejs użytkownika (React)
- `streamlit_app/` — wcześniejsza wersja prototypu (Streamlit), obecnie nieużywana
- `docker-compose.yml` — definicja usług
- `n8n_orchestrator_workflow.json` — przepływ orkiestracji do zaimportowania w n8n
- `docs/` — dokumentacja techniczna (architektura, prompty, walidacja, bezpieczeństwo)
- `tests/` — testy automatyczne (pytest, przeciwko działającemu API)
- `pliki_testowe/` — dane i plan testów manualnych
- `ollama_api_test.py` — pomocniczy skrypt testowy

## Uruchomienie

Instrukcja krok po kroku znajduje się w pliku [SETUP.md](SETUP.md).
