# ecommerce-llm-reports

Prototyp systemu do dynamicznego generowania raportów sprzedażowych w e-commerce
z wykorzystaniem dużych modeli językowych (LLM). Użytkownik formułuje zapytanie w
języku naturalnym (polskim), a system zamienia je na zapytanie SQL, wykonuje je na
bazie danych i prezentuje wynik w postaci interaktywnego dashboardu.

Projekt realizowany jako **praca inżynierska**.

## Jak to działa

Przepływ: **React → FastAPI → Ollama (LLM) → walidacja SQL na bazie → Metabase**.
Warstwą zapasowej orkiestracji jest n8n.

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
- **Orkiestracja (fallback):** n8n
- **Konteneryzacja:** Docker Compose

## Architektura danych

- **Baza systemowa** (SQLite) przechowuje użytkowników, metadane wgranych baz oraz
  historię zapytań.
- **Wgrane bazy danych** przechowywane są jako pliki na wolumenie; w bazie systemowej
  znajduje się tylko wskaźnik do pliku i wykryty schemat.
- **Dashboardy** żyją w Metabase; backend steruje nimi przez API i osadza publiczny link.

## Struktura repozytorium

- `backend/` — API i logika aplikacji (FastAPI)
- `frontend/` — interfejs użytkownika (React)
- `streamlit_app/` — wcześniejsza wersja prototypu (Streamlit), obecnie nieużywana
- `docker-compose.yml` — definicja usług
- `ollama_api_test.py` — pomocniczy skrypt testowy

## Uruchomienie

Instrukcja krok po kroku znajduje się w pliku [SETUP.md](SETUP.md).
