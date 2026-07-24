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

## 6. Ocena zgodności z dobrymi praktykami wizualizacji (uwaga promotora, punkt 6)

Promotor zapytał, czy dobór typów i układu wykresów jest zgodny z dobrymi praktykami
wizualizacji danych — nie tylko „czy działa technicznie". Metoda: przegląd 30 kart
typu pie/line z 20 ostatnio wygenerowanych dashboardów (Metabase API, `/api/dashboard/{id}`
+ `/api/card/{id}/query` — pobrane bezpośrednio wyniki zapytań, nie tylko definicje kart)
wobec ogólnie przyjętych zasad doboru formy wykresu: *magnitude/porównanie kategorii* →
słupkowy, *identity/udział całości* → kołowy TYLKO dla nielicznych (≤5–6) kategorii,
*zmiana w czasie* → liniowy/obszarowy, *pojedyncza wartość* → licznik; oraz anty-wzorca
„przeciążona liczba serii/kategorii" (>8–10 elementów na wykresie liniowym lub kołowym =
nieczytelne — zamiast tego agregacja „Pozostałe", small multiples albo inna forma).

### Znalezione naruszenia (realne karty z wygenerowanych dashboardów)

| Dashboard/karta | Tytuł karty | Forma | Problem | Zasada naruszona |
|---|---|---|---|---|
| 132/377 | Suma sprzedaży po jednostce dla każdego artysty | kołowy | 165 unikalnych artystów w wyniku (SELECT bez LIMIT) — Metabase automatycznie zwija ogon w kategorię **„Other" = 78,43% całości** (zweryfikowane wizualnie, zrzut ekranu) | kategoria „Other" dominująca nad wszystkimi widocznymi wycinkami razem wziętymi czyni wykres bezużytecznym — nie pokazuje TEGO, co miał pokazać (kto naprawdę dominuje w sprzedaży) |
| 143/406 | Trend sprzedaży produktów w 2024 roku | liniowy | **25 nakładających się serii** (`GROUP BY miesiac, produkt`, 25 unikalnych produktów) | ≤8–10 serii na wykresie liniowym |
| 130/372 | Top 10 produktów | kołowy | ranking TOP N pokazany jako kołowy (10 wycinków) | ranking/porządek → słupkowy, nie kołowy |
| 145/411 | Udział kategorii produktów w sprzedaży | kołowy | SQL grupuje po `(miesiac, kategoria)` → **114 wycinków** zamiast 5 kategorii | tytuł ≠ SQL (ten sam wzorzec co B4, docs/06) |
| 139/393 | Wartość zamówień według segmentu klienta | kołowy | tytuł mówi „wartość", SQL liczy `SUM(ilosc)` — to ilość, nie wartość | metryka w tytule ≠ metryka w SQL |
| 136/384 | Procentowy udział produktów w każdym segmencie klienta | kołowy | tytuł obiecuje podział po PRODUKCIE, SQL grupuje tylko po segmencie (bez wymiaru produktu) | tytuł nadinterpretowuje własny SQL |

Wiersze/serie policzone bezpośrednio z wyniku zapytania (`/api/card/{id}/query`), nie
zgadywane z SQL — np. karta 406: 111 wierszy wynikowych, 25 unikalnych wartości w kolumnie
`produkt`. Obie skrajne karty (132/377, 143/406) zweryfikowane też WIZUALNIE w przeglądarce
(2026-07-24): karta 406 to potwierdzony „spaghetti chart" — 25 linii w legendzie (w tym
powtarzające się odcienie tego samego koloru dla różnych produktów, np. kilka linii
niebieskich pod rząd), zero czytelności który produkt jest który. Karta 377 okazała się
mieć INNY problem niż pierwotnie zakładano: Metabase NIE renderuje 165 osobnych wycinków,
tylko automatycznie zwija długi ogon w kategorię „Other" — ale to nie ratuje wykresu,
bo „Other" wychodzi na **78,43% całości**, więc widoczne pozostaje tylko 5 nic nieznaczących
wycinków (Iron Maiden 5,95% … Lost 3,50%) obok jednej nieprzejrzystej szarej masy, która
skrywa właśnie to, co wykres miał pokazać (kto faktycznie dominuje w sprzedaży).
Zrzuty ekranu obu kart: `pliki_testowe/screeny_wizualizacja/` (poza gitem, lokalnie —
gotowe jako rysunki do rozdziału Ewaluacja/Dyskusja).

### Kontrola — co jest zgodne z dobrymi praktykami
- Karty słupkowe grupujące po kategorii/mieście/segmencie: 3–8 kategorii — w normie.
- Karty liniowe z jedną serią (miesiąc → wartość, 12–24 punkty, np. dash 128/367,
  140/398): poprawna forma dla trendu w czasie.
- Karty liniowe z podziałem po mieście (dash 136/386, 139/395): 6 serii — mieści się
  w progu ≤8, czytelne.

### Wniosek dla pracy
System poprawnie dobiera BAZOWĄ formę wykresu (słupkowy do porównań, liniowy do trendu)
w większości przypadków, ale nie waliduje KARDYNALNOŚCI wymiaru grupującego przed wyborem
formy — etap planowania (model 7B) wybiera typ wykresu (pie/line) niezależnie od tego,
ile odrębnych wartości faktycznie zwróci SQL dla kolumny grupującej. To osobna klasa
błędu niż już udokumentowane „tytuł≠SQL" (docs/06) — w przypadkach 132/377 i 143/406
tytuł i SQL są ze sobą spójne, a mimo to forma jest źle dobrana do LICZBY kategorii.
**Naprawione (2026-07-24, `_check_category_cardinality`, `docs/06` §4):** backend przed
budową karty dolicza `SELECT COUNT(DISTINCT <kolumna>)` na PEŁNYM wyniku (nie na 5-wierszowej
próbce — próbka nigdy by nie wystarczyła) i zwraca `ok=False` z podpowiedzią, gdy kołowy
ma >8 kategorii albo liniowy ma >8 serii (przy ≥3 kolumnach — zwykły 1-seryjny trend, sama
data+miara, nie jest w ogóle sprawdzany, żeby nie fałszywie odrzucać normalnego trendu
12-24 punktów). Błąd wraca tym samym kanałem retry co pozostałe guardy — model dostaje
podpowiedź „ogranicz do najważniejszych 8 (…) albo zagreguj rzadsze wartości w „Inne""
i może spróbować ponownie, zanim wykres zostanie porzucony po 3 próbach.
**Zweryfikowane bezpośrednio na dokładnie tych samych zapytaniach SQL, które wyprodukowały
karty 132/377 i 143/406** (`/internal/process-sql-attempt`): oba teraz zwracają `ok=false`
z czytelnym komunikatem. Kontrolnie sprawdzone też 3 przypadki, które MUSIAŁY dalej przechodzić
(żeby nie wprowadzić fałszywych alarmów): kołowy z 5 kategoriami, liniowy z 6 seriami (miasta,
karty 136/386 i 139/395) i zwykły 1-seryjny trend 12-miesięczny — wszystkie trzy `ok=true`
bez zmian. Pełny pakiet testów regresyjnych: **33 passed** (bez regresji).

Warto zaznaczyć: sam Metabase już CZĘŚCIOWO łagodzi ten problem po swojej stronie
(automatyczne zwijanie ogona w „Other" na wykresie kołowym), ale to nie wystarcza — karta
132/377 pokazywała, że mechanizm Metabase'a może wyprodukować wykres, na którym dominująca
kategoria to nieinterpretowalny bucket „Other" (78%). Dlatego odpowiedzialność za sensowny
próg kardynalności musiała leżeć wyżej, na etapie WALIDACJI SQL przed budową karty, nie na
etapie renderowania — stąd guard w Pythonie (`process-sql-attempt`), nie w Metabase ani w JS.

## 7. Jak te poziomy się uzupełniają (na obronę)

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
6. Karta 132/377 miała poprawny SQL i poprawny tytuł, a mimo to była złym wykresem —
   wyjaśnij, czym różni się ten błąd od „tytuł≠SQL", i dlaczego `_check_category_cardinality`
   musiał liczyć DISTINCT na pełnym wyniku, a nie na 5-wierszowej próbce jak reszta guardów.
