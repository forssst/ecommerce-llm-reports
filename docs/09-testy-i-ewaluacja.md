# 09 — Testowanie i ewaluacja (deep dive)

> Cztery poziomy, każdy mierzy CO INNEGO. Rozdział zawiera też pełne wyniki
> per prompt z przebiegu 2026-07-06 — do bezpośredniego użycia w pracy.

## 1. Testy automatyczne — `tests/` (pytest przez HTTP)

- Uruchamianie: `PG_HOST=localhost /home/symi/PracaInz/venv/bin/pytest tests/`
  (wymaga DZIAŁAJĄCEGO stacku — testy biją w prawdziwe API, nie TestClient;
  decyzja świadoma: testujemy system, nie kod w izolacji).
- `conftest.py`: fixtury `user_a`/`user_b` — świeże konta per test
  (`_register` z unikalnym emailem), więc testy nie zależą od stanu bazy.
- Bloki:
  1. **JWT**: brak tokenu → 401; zmanipulowany podpis → 401; token usera A
     na zasobach B → 403.
  2. **Izolacja**: A nie widzi baz/historii B; `test_b_nie_moze_generowac_jako_a`
     — pełny /generate z tokenem B i db_path A (timeout 300 s — realna generacja!).
  3. **Upload**: plik > limitu → 413; uszkodzony .db → 400 (nie 500);
     nazwa z `../../` → losowa nazwa na dysku, odpowiedź bez traversal.
  4. **Read-only SQL**: połączenie TĄ SAMĄ rolą, której używa system do SQL-a
     od LLM → `CREATE TABLE` musi rzucić `psycopg2.Error`.
- Historia: 23 passed/8 xfailed (xfail = udokumentowane luki) → po naprawach
  **31 passed, 0 xfailed**. Mechanizm xfail pozwalał mieć zielony przebieg
  PRZED naprawami — a naprawa ujawniała się jako XPASS.

## 2. Testy manualne — `pliki_testowe/PLAN_TESTOW.md`

9 bloków (A–I), ~49 scenariuszy; konwencja: cel wklejany DOKŁADNIE jak podano,
zrzut ekranu z pomarańczową etykietą numeru testu, notowanie liczby auto-korekt.

| Blok | Baza | Co naprawdę testuje |
|---|---|---|
| A | sklep_testowy.csv | regresja podstaw: clarify→enhance, filtr dat, wybór typów |
| B | firma_uslugi.xlsx | multi-arkusz, POLSKIE kolumny dat, JOIN-y 2-3 tabel |
| C | superstore.xls | stary format .xls, ~10k wierszy, dwie miary |
| D | northwind.db | SQLite, CamelCase→lowercase, JOIN-y, pełna kombinacja D5 |
| E | sakila.db | stres JOIN-ów 4 tabel (porażki = materiał, nie bug) |
| F | — | przekrojowe: historia, izolacja kont, zły plik, TOP bez liczby |
| G | — | **awarie**: stop Ollama/n8n/Metabase, destrukcyjny prompt, zły JWT |
| H | olist.sqlite | SKALA: 99 441 zamówień; portugalskie kategorie + tabela tłumaczeń |
| I | Chinook | najdłuższy JOIN (5 tabel: invoiceline→track→album→artist+invoice) |

Żniwo dwóch pełnych przebiegów (2026-07-05 i 06): ~10 realnych bugów
znalezionych i naprawionych, m.in.: typ tagu filtra dat, dobór kolumny dat
per wykres, wiszący webhook przy 0 wykresów, pusty „Pokaż SQL", ciche
pomijanie wykresów, halucynowane wartości kolumn (B4), kasujące się duble
baz, kryptyczne komunikaty awarii. **Wniosek metodyczny: testy manualne
człowieka znajdują klasy błędów niewidoczne dla testów API** (bo klikają
NAPRAWDĘ: wybierają datę w widgecie, patrzą na etykiety, usuwają bazy).

## 3. Harness ewaluacyjny — `eval_harness.py`

- Konstrukcja: świeże konto → upload 5 baz przez API → 18 promptów
  sekwencyjnie przez `/generate` (opis bazy ZAWSZE pusty — kontrola zmiennej;
  opis potrafi „rozpraszać" plan) → CSV + agregaty.
- Metryki per prompt: `status, elapsed_s, requested, generated, failed,
  retries, url, error`.
- Uruchamianie: `venv/bin/python eval_harness.py [--smoke|--db klucz]`.

**Pełne wyniki 2026-07-06** (`eval_results_20260706_173109.csv`):

| # | baza | trudność | prompt | czas [s] | wykresy | retry |
|---|---|---|---|---|---|---|
| 1 | sklep | łatwy | suma sprzedazy wedlug kategorii | 57,0 | 3/3 | 0 |
| 2 | sklep | łatwy | top 5 produktow wedlug sumy sprzedazy | 66,5 | 3/3 | 1 |
| 3 | sklep | łatwy | trend miesiecznej sprzedazy w 2024 roku | 70,1 | 3/3 | 0 |
| 4 | sklep | średni | TOP 10 produktow ... podzialem miesiecznym w 2024 | 96,3 | 3/3 | 0 |
| 5 | firma | średni | liczba umow podpisanych w kazdym miesiacu | 74,6 | 3/3 | 0 |
| 6 | firma | średni | srednie wynagrodzenie pracownikow wg stanowiska | 95,0 | 3/3 | 0 |
| 7 | firma | średni | top 10 klientow wedlug lacznej wartosci umow | 110,9 | 2/3 | 3 |
| 8 | superstore | średni | sprzedaz i zysk wedlug kategorii produktow | 95,4 | 1/3 | 4 |
| 9 | superstore | średni | top 10 klientow wedlug sprzedazy | 85,4 | 3/3 | 3 |
| 10 | superstore | średni | trend miesiecznej sprzedazy | 68,8 | 3/3 | 1 |
| 11 | northwind | trudny | top 10 produktow wedlug przychodu | 103,2 | 3/3 | 1 |
| 12 | northwind | trudny | sprzedaz wedlug kraju klienta | 150,1 | 2/3 | 2 |
| 13 | northwind | trudny | liczba zamowien obslugiwanych przez pracownika | 90,3 | 3/3 | 1 |
| 14 | northwind | trudny | kwartalny przychod ze sprzedazy | 128,6 | 2/3 | 5 |
| 15 | sakila | trudny | najpopularniejsze kategorie filmow wg wypozyczen | 75,3 | 3/3 | 0 |
| 16 | sakila | średni | miesieczny przychod z platnosci | 86,5 | 3/3 | 1 |
| 17 | sakila | trudny | top 10 aktorow wedlug liczby filmow | 88,9 | 3/3 | 3 |
| 18 | sakila | trudny | srednia dlugosc filmu wedlug kategorii | 113,1 | 1/3 | 4 |

Agregaty: **18/18 dashboardów (100%)**; wykresy **47/54 (87%)**; retry **29**;
czas: min 57,0 / mediana 89,6 / max 150,1 / średnia 92,0 s.
Per trudność: łatwe 3/3, średnie 8/8, trudne 7/7 (na poziomie dashboardu).

## 4. Golden set — `golden_set.py` (poprawność MERYTORYCZNA)

Idea = *execution accuracy* z benchmarków text-to-SQL (Spider/BIRD):
porównujemy WYNIKI wykonania, nie tekst SQL (różne zapytania bywają równoważne).

- 5 promptów z ręcznie napisanym i ZWERYFIKOWANYM wzorcem SQL.
- Normalizacja przed porównaniem: liczby→round(4), daty→`YYYY-MM-DD`,
  teksty→lower/strip, wiersze posortowane.
- Werdykty: **EXACT** (wiersze identyczne) → **VALUES** (multizbiór wartości
  liczbowych + liczba wierszy zgodne; łapie różnice formatu etykiet) →
  MISMATCH/ERROR. Dashboard ma 2–4 karty — porównujemy każdą, liczy się najlepsza.

**Wyniki 2026-07-06:** EXACT **4/5**, VALUES **5/5**. Jedyny nie-EXACT:
northwind zamówienia/pracownik — te same liczby, inaczej sklejone imię
i nazwisko w etykiecie.

## 5. Stress-test — `stress_test_ollama.py`

N równoczesnych `/generate` (N=1,2,3,5 × 2 powtórzenia, ta sama baza/prompt):

| N | śr. czas/żądanie | sukcesy |
|---|---|---|
| 1 | ~61 s | 2/2 |
| 2 | ~123 s | 4/4 |
| 3 | ~202 s | 6/6 |
| 5 | 170–211 s (te co przeszły) | **6/10** — 4 porażki, każda dokładnie ~120,1 s |

Diagnoza: porażki to trafienia w sztywny timeout 120 s pojedynczego wywołania
(ówczesny `n8n_timeout`); żądania, które ZDĄŻYŁY, trwały PONAD 120 s → model
by je obsłużył przy większym budżecie. Granica: **między N=3 a N=5**, przyczyna
konkretna, nie „niestabilność". Wyniki CSV: `stress_test_results_*.csv`
(gitignore; kopia w głównym repo), wykres: artifact z sesji 2026-07-05.

## 6. Jak te poziomy się uzupełniają (na obronę)

| Poziom | Pytanie, na które odpowiada |
|---|---|
| pytest | „czy zabezpieczenia działają?" (deterministyczne, szybkie) |
| manualne | „czy człowiek może tego używać?" (znajduje klasy błędów niewidoczne dla API) |
| harness | „jak CZĘSTO system daje działający wynik i jakim kosztem?" (powtarzalne liczby) |
| golden set | „czy wynik jest PRAWDZIWY, nie tylko wykonywalny?" |
| stress | „ile równoczesności wytrzyma i CZEMU tyle?" |

## Sprawdź się
1. Czemu pytest bije w żywe API zamiast TestClient — co zyskujemy, co tracimy?
2. Wskaż w tabeli harnessu 3 najgorsze przypadki i powiąż je z ograniczeniami z docs/06,09.
3. Czym różni się werdykt VALUES od EXACT i jaki realny przypadek go wymusił?
4. Odtwórz diagnozę stress-testu: skąd wiadomo, że winny jest timeout, a nie model?
5. Który poziom testów znalazł halucynowane wartości kolumn i CZEMU tylko on mógł?
