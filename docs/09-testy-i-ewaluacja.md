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
wobec zasad doboru formy wykresu opartych na literaturze przedmiotu (bibliografia w
`Teoria/PLAN_PRACY.md`):
- **Cleveland W.S., McGill R., „Graphical Perception: Theory, Experimentation, and
  Application to the Development of Graphical Methods", JASA, 1984** — empiryczny
  eksperyment: ludzie oceniający proporcje z wykresu słupkowego robią to DOKŁADNIEJ niż
  z kołowego (hierarchia kanałów percepcyjnych: pozycja > długość > kąt > pole). Podstawa
  reguły „ranking/TOP N → słupkowy, nie kołowy".
- **Few S., „Information Dashboard Design: The Effective Visual Communication of Data",
  O'Reilly, 2006** — wprost odradza wykresy kołowe w dashboardach (razem z gauge/dial);
  dokładnie ta sama teza co poniższe znaleziska z kart 132/377 i 143/406.
- **Munzner T., „Visualization Analysis and Design", CRC Press** — rama „task and data
  abstraction": *magnitude/porównanie kategorii* → słupkowy, *identity/udział całości*
  → kołowy TYLKO dla nielicznych (≤5–6) kategorii, *zmiana w czasie* → liniowy/obszarowy,
  *pojedyncza wartość* → licznik.

Anty-wzorzec „przeciążona liczba serii/kategorii" (>8–10 elementów na wykresie liniowym
lub kołowym = nieczytelne — zamiast tego agregacja „Pozostałe", small multiples albo inna
forma) wynika wprost z powyższej hierarchii kanałów percepcyjnych Cleveland/McGill: powyżej
kilku kategorii różnicowanie po kącie (pie) czy po kolorze linii (line) przestaje być
rozróżnialne dla oka.

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

### Trzeci problem: dobór typu wykresu „dla różnorodności", nie po treści pytania

Osobne pytanie niż kardynalność pojedynczego wykresu: czy sam ZESTAW 2–4 wykresów, jaki
system dobiera do jednego promptu, odpowiada temu, co dobrałby profesjonalny analityk danych.
Sprawdzone wprost w kodzie: instrukcja dla modelu na etapie planowania (gdy user NIE wybrał
ręcznie typów w UI), przed poprawką, brzmiała dosłownie **„Wygeneruj 3-4 różnorodne wykresy
(bar, line, pie, table)"** (`backend/main.py`, gałąź `else` w `internal_plan_prompt`) —
żadnego powiązania między charakterem pod-celu a wyborem typu, poza jednym twardym warunkiem
(cel zawiera „trend/miesiąc/rok" → musi być line/bar).

**Dowód empiryczny (nie teoria):** na tych samych 20 dashboardach z sekcji wyżej, **12 z 13
dashboardów 3-wykresowych miało DOKŁADNIE zestaw {bar, line, pie}** — po jednym z każdego,
niezależnie od treści promptu. Typ `table`, mimo że dozwolony, nie pojawił się ani razu w tej
próbce. To wygląda jak sztywny szablon „1 słupkowy + 1 liniowy + 1 kołowy" motywowany
instrukcją „bądź różnorodny", nie realną analizą treści każdego pod-celu — czyli coś, czego
profesjonalny analityk by NIE zrobił (dobiera formę wyłącznie po naturze pytania: trend→line,
ranking→bar, udział nielicznych kategorii→pie — nigdy „żeby było inaczej niż poprzedni wykres").

**Naprawione (2026-07-24):** instrukcja `types_instruction` w gałęzi swobodnego wyboru
zamieniona z „wygeneruj różnorodne" na jawne kryteria dopasowania typu do treści pod-celu
(oparte na tych samych źródłach co wyżej — Cleveland/McGill, Few, Munzner), z regułą
awaryjną „gdy wahasz się między pie a bar — wybierz bar". **Zweryfikowane na dwóch
kontrastowych promptach przez pełny łańcuch `plan-prompt` → Ollama:**
- prompt z 3 różnymi rodzajami pod-celów (ranking + trend + udział 3 segmentów) → model
  poprawnie zwrócił `bar` + `line` + `pie` — ale tym razem dlatego, że KAŻDY pod-cel
  faktycznie tego wymagał, nie z automatu;
- prompt z DWOMA rankingami i zerem trendu/udziału („top 5 produktów" + „top 5 klientów")
  → model zwrócił `bar` + `bar`, **bez sztucznego dociągania trzeciego, innego typu**. To
  jest rozstrzygający test: stary automatyzm wymuszałby różnorodność, nowa instrukcja
  poprawnie rozpoznaje, że oba pod-cele to ten sam rodzaj zadania (ranking).
- Ten sam drugi prompt puszczony przez PEŁNY pipeline (`/generate` → n8n → Metabase, nie
  tylko izolowany krok planowania): dashboard 147, 2/2 karty, obie `bar`, 63,6 s.
- Pełny pakiet testów regresyjnych po zmianie: **33 passed** (bez regresji — to zmiana
  tekstu instrukcji, nie logiki walidacji).

**Why to jest osobna klasa problemu:** guard kardynalności (wyżej) naprawia POJEDYNCZY
wykres po tym, jak SQL już powstał. Ten problem jest o krok wcześniej — na etapie
PLANOWANIA zestawu wykresów, zanim jakikolwiek SQL powstanie — więc nie da się go złapać
guardem wykonującym zapytanie; jedyna dźwignia to sama treść promptu do modelu.

### Czwarty problem: guard kardynalności naprawiał tylko objaw, nie typ wykresu

Luka znaleziona przy przeglądzie guardu kardynalności (sekcja wyżej): gdy model mimo
poprawki promptu i tak zwróci `pie` dla danych z >8 kategoriami, `_check_category_cardinality`
zwracał błąd każący modelowi **poprawić SQL** (`LIMIT 8` albo agregacja do „Inne") — ale
retry w pętli (`_generate_multichart` / `/internal/process-sql-attempt`, wołane przez węzeł
n8n „Generuj SQL i Zbierz Wykresy") nigdy nie zmieniał samego `chart_type`, bo jest on
ustalony raz na etapie planowania i przekazywany na sztywno przez wszystkie 3 próby. Skutek:
jeśli model nie potrafił w 3 próbach obciąć wyniku do 8 kategorii (a nie zawsze to sensowne —
czasem WSZYSTKIE 15 kategorii są ważne dla odpowiedzi na pytanie), wykres był **całkowicie
porzucany** (`continue` po wyczerpaniu prób) — gorszy wynik niż pokazanie tych samych danych
jako słupkowy, co i tak byłoby poprawną formą dla tylu kategorii (ten sam Cleveland/McGill
co uzasadnia regułę „ranking → bar" wyżej).

**Naprawione (2026-07-24):** `_run_and_validate` (backend/main.py) zwraca teraz piąty element —
rozwiązany `chart_type` — i gdy guard kardynalności odrzuca `pie`, zamiast błędu zwraca
deterministycznie `ok=True, chart_type="bar"` (dla `pie` bez dalszych prób SQL, O ILE słupkowy
z tymi samymi danymi sam przejdzie swój limit — patrz „Piąty problem" niżej, gdzie okazało się,
że `bar` też potrzebuje granicy, tylko wyższej). Zmiana objęła 3
miejsca: samą funkcję, wywołanie w `_generate_multichart` (kod referencyjny, nieużywany w
tej gałęzi) i żywy endpoint `/internal/process-sql-attempt`, którego JSON teraz zwraca
`chart_type` obok `ok/sql/error/columns/sample` — węzeł n8n „Generuj SQL i Zbierz Wykresy"
(`n8n_orchestrator_workflow.json`) zaktualizowany, by przekazywał ten ROZWIĄZANY typ (nie
oryginalny `spec.chart_type` z planu) do `/internal/finalize-chart`, inaczej poprawka nie
miałaby efektu na finalnej karcie w Metabase. Guard dla `line` (za dużo serii) celowo
zostawiony bez zmian — 3-kolumnowy wynik liniowy (data + seria + miara) nie da się bez
przekształcenia SQL pokazać jako `bar` 1:1, więc tam retry na SQL wciąż jest właściwą reakcją.

**Zweryfikowane bezpośrednio na żywym endpoincie** (`u2_superstore`, tabela `orders`):
- `SELECT sub_category, SUM(sales) FROM orders GROUP BY sub_category` (17 kategorii) z
  `chart_type=pie` → odpowiedź `{"ok": true, "chart_type": "bar", ...}` — dawniej `ok=false`
  z błędem kardynalności;
- kontrolnie to samo z `segment` (3 kategorie) i `chart_type=pie` → `{"ok": true,
  "chart_type": "pie", ...}` bez zmian — potwierdza, że fallback uruchamia się TYLKO przy
  realnym przekroczeniu limitu, nie zawsze.

### Piąty problem: słupkowy też może mieć za dużo kategorii — znalezione przez usera, nie przeze mnie

Poprawka wyżej (pie→bar) milcząco zakładała, że `bar` w ogóle nie ma problemu z kardynalnością.
**To założenie obalił bezpośrednio ręczny test usera** (nie test automatyczny) w tej samej
sesji: prompt „Pokaż ranking najlepiej sprzedających się produktów oraz ranking najlepszych
klientów..." na bazie `sklep_testowy.csv`, BEZ ręcznego wyboru typu wykresu (AI miało dobrać
samo) → karta „Ranking najlepiej sprzedających się produktów" wyrenderowała się jako słupkowy
z kilkudziesięcioma cieniutkimi słupkami malejącymi od ~270 000 do blisko zera — nieczytelny,
bo prompt nie zawierał słowa „top N", więc istniejący guard „`top N` w celu → dołóż `LIMIT`"
(`/internal/process-sql-attempt`) się nie uruchomił, a `_check_category_cardinality` w ogóle
nie obejmował `bar` (`_CARDINALITY_LIMITED_TYPES = {"pie", "line"}`). Kontrastowo: ten sam
rodzaj promptu na bazie „Sklepik" (mniej produktów) dał czytelny wynik (10 i 5 słupków) — czyli
błąd ujawnia się tylko przy realnie dużej liczbie kategorii, nie zawsze, co dokładnie pasuje do
klasy problemu „brak górnej granicy", a nie „zawsze się psuje".

**Naprawione (2026-07-24):** `bar` dołączony do `_CARDINALITY_LIMITED_TYPES`, ale z WŁASNYM,
wyższym limitem niż pie/line — `_MAX_BAR_CARDINALITY = 20` vs `_MAX_CATEGORY_CARDINALITY = 8` —
bo słupkowy toleruje więcej kategorii niż kołowy (Cleveland/McGill: pozycja/długość czytelniejsza
niż kąt), ale nie bez granic, co właśnie pokazał ten test. Dodatkowo wyjątek: gdy pierwsza
kolumna wygląda jak data (`^\d{4}-\d{2}(-\d{2})?$`, ta sama heurystyka co w `_infer_display`),
check jest pomijany całkowicie — słupkowy „sprzedaż po miesiącach" z 24 punktami (2 lata) to
naturalna liczba okresów czasu, nie ranking kategorii do obcinania, i nie powinien być fałszywie
łapany. Konsekwencja dla wcześniejszej poprawki (pie→bar): skoro `bar` ma teraz własny limit,
konwersja pie→bar sprawdza NAJPIERW, czy słupkowy z tymi samymi danymi sam przejdzie swój
(wyższy) limit — jeśli tak, konwertuje; jeśli nawet jako słupkowy byłoby za dużo kategorii
(np. 1849 unikalnych nazw produktów), fallback się NIE uruchamia i błąd wraca do modelu jak
dawniej, żeby SQL rzeczywiście ograniczył wynik, zamiast podać nieczytelny wykres jako „ok".

**Zweryfikowane bezpośrednio na żywym endpoincie**, odtwarzając dokładnie przypadek z testu
usera (`u2_superstore.orders`, 1849 unikalnych `product_name`):
- `bar` + `GROUP BY product_name` (1849 kategorii) → `ok=false`, błąd z podpowiedzią
  `LIMIT 20` / agregacja do „Inne" — dokładnie to, czego brakowało w oryginalnym znalezisku;
- kontrolnie `bar` + `GROUP BY segment` (5 kategorii) → `ok=true`, bez zmian;
- kontrolnie `bar` + `GROUP BY miesiąc` (etykieta w formacie `YYYY-MM`) → `ok=true` mimo
  wielu punktów — wyjątek daty działa, nie blokuje normalnego trendu miesięcznego pokazanego
  jako słupkowy;
- kontrolnie `pie` + `GROUP BY sub_category` (17 kategorii) → nadal konwertuje na
  `chart_type="bar"` (17 ≤ 20, przechodzi);
- **rozstrzygający test spójności:** `pie` + `GROUP BY product_name` (1849 kategorii) →
  `ok=false`, ZOSTAJE `pie` (fallback się NIE uruchamia, bo 1849 > 20 też dla słupkowego) —
  potwierdza, że nowa poprawka nie tworzy fałszywego poczucia bezpieczeństwa przy naprawdę
  dużej kardynalności, tam gdzie żaden typ wykresu tego nie uratuje bez realnego ograniczenia
  SQL. Pełny pakiet testów regresyjnych po zmianie: bez regresji (patrz historia commitów).

**Why to jest dobry materiał na obronę:** to jedyne z pięciu znalezisk w tym rozdziale, które
NIE wyszło z mojego przeglądu kart Metabase, tylko z samodzielnego, naiwnego testowania przez
usera jako zwykłego użytkownika (bez wiedzy, co system powinien czy nie powinien zrobić) —
dokładnie to, o co prosił promotor w metazadaniu „przejdź aplikację od zera".

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
