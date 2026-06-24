# Ściąga na spotkanie z promotorem

> Jedna kartka. Przeczytaj rano, opowiedz na głos 2× i jesteś gotowy.

---

## 🎯 CO ROBI SYSTEM (jedno zdanie)
System „AI Data Analyst": użytkownik pisze cel analityczny **po polsku**, lokalny model AI
zamienia go na SQL, wynik trafia na **interaktywny dashboard w Metabase**. Wszystko działa
**lokalnie** — bez chmury, bez kosztów, z zachowaniem prywatności danych.

---

## 🔄 PRZEPŁYW — opowiedz to z głowy (6 kroków)

1. **Upload** — użytkownik wgrywa plik (SQLite/CSV/Excel). Dane lądują w **PostgreSQL**
   jako osobny schemat dla tego użytkownika (`u{id}_nazwa`).
2. **Cel po polsku** — np. „pokaż TOP 10 klientów według zakupów".
3. **Etap A — Planowanie**: model AI (qwen2.5-coder:7b przez Ollamę) rozbija cel na
   **2–4 wykresy** — dla każdego zwraca `{tytuł, typ wykresu, cel}`.
4. **Etap B — SQL**: dla każdego wykresu **osobne** zapytanie. Model pisze SQL →
   system **wykonuje go naprawdę** na danych → jak błąd, wraca do modelu (max 3 próby).
5. **Metabase** — system tworzy dashboard, karty (wykresy), filtr dat, publiczny link.
6. **Frontend** osadza dashboard przez `<iframe>`.

> **Klucz do zapamiętania:** DWA ETAPY (najpierw plan, potem SQL osobno na każdy wykres)
> + WALIDACJA na prawdziwych danych z retry.

---

## ❓ 5 ODPOWIEDZI „DLACZEGO" (najczęstsze pytania)

**1. Dlaczego lokalny model, a nie ChatGPT/API?**
→ Prywatność danych (nic nie wychodzi na zewnątrz), brak kosztów API, działanie offline.
To świadoma decyzja architektoniczna, nie ograniczenie.

**2. Dlaczego PostgreSQL, a nie pliki?**
→ Trwałość danych, poprawne typy (daty jako TIMESTAMP — potrzebne do filtrów),
izolacja użytkowników (każdy ma swój schemat), bezpośrednie połączenie z Metabase.

**3. Dlaczego dwa etapy (plan + SQL osobno)?**
→ Małemu modelowi łatwiej napisać jeden poprawny SQL na wąski cel niż cały dashboard naraz.
Dekompozycja problemu = wyższa jakość. Każdy wykres ma inny, konkretny cel.

**4. Co jak model wygeneruje zły SQL?**
→ Funkcja `_run_and_validate` **wykonuje SQL na prawdziwych danych**. Jeśli błąd —
treść błędu wraca do modelu jako wskazówka i próba się powtarza (max 3×).
Liczba poprawek zapisywana jest jako `retry_count` (widać w UI „N auto-korekt SQL").

**5. Dlaczego Metabase?**
→ Gotowe, darmowe, open-source narzędzie BI. Tworzenie wykresów przez REST API,
publiczne linki do osadzenia, obsługa wielu typów wykresów. Nie wynajdowałem koła od nowa.

---

## ⚠️ 3 ZNANE OGRANICZENIA (powiedz sam, zanim zapyta!)

1. **Złożone JOIN-y (3+ tabel)** — model 7B czasem agreguje źle. To ograniczenie małego
   modelu lokalnego. Kierunek rozwoju: większy model (13B/34B).
2. **Brak ograniczenia SQL do read-only** — generowany SQL nie jest wymuszany jako SELECT.
   Kierunek rozwoju: walidacja + sanityzacja (bezpieczeństwo).
3. **Brak harnessu ewaluacyjnego** — planowany: zestaw promptów + metryki (% poprawnych SQL,
   średni retry, czas). Materiał na rozdział „Ewaluacja".

---

## 🛠️ STACK (gdyby zapytał czym to napisane)

| Warstwa        | Technologia                                  |
|----------------|----------------------------------------------|
| Frontend       | React + Vite + Tailwind                      |
| Backend        | FastAPI (Python), SQLAlchemy                 |
| Model AI       | Ollama + qwen2.5-coder:7b (lokalnie)         |
| Baza danych    | PostgreSQL (dane) + SQLite (metadane systemu)|
| Wizualizacja   | Metabase                                     |
| Orkiestracja   | Docker Compose                               |

---

## 🔑 5 NAJWAŻNIEJSZYCH FUNKCJI (gdyby chciał wejść w kod)

- **`_generate_multichart`** — serce systemu, orkiestruje całość (plan → SQL → dashboard)
- **`_ollama_json`** — wywołanie modelu z wymuszonym JSON na wyjściu
- **`_clean_sql`** — naprawia typowe błędy modelu (backticki, CamelCase, wiele zapytań)
- **`_run_and_validate`** — wykonuje SQL na danych, zwraca błąd lub wynik
- **`create_metabase_card`** — tworzy wykres w Metabase z SQL i typem wizualizacji

---

## 💡 ZŁOTA ZASADA NA SPOTKANIE
Jak czegoś nie wiesz — **nie zmyślaj**. Powiedz: „to działa tak a tak, szczegóły mam w kodzie".
Promotor woli „wiem gdzie to jest" niż konfabulację. Mów o **decyzjach i przepływie**,
nie o składni. Ty znasz ten projekt najlepiej w tym pokoju.
