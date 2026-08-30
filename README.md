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
2. Backend planuje wykresy i generuje dla każdego z nich SQL przez lokalny model językowy.
3. Każde zapytanie jest walidowane na prawdziwych danych; błędne SQL są automatycznie
   poprawiane (mechanizm retry z informacją o błędzie).
4. Backend buduje dashboard w Metabase i zwraca publiczny link, który frontend osadza.

## Stack technologiczny

- **Frontend:** React + Vite + Tailwind
- **Backend:** FastAPI (Python), SQLAlchemy + SQLite
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
