# 06 — Walidacja SQL i wszystkie guardy (deep dive)

> Filozofia potwierdzona ~8 razy w tym projekcie: **prompt-fix + code-level
> guard**. Instrukcja w prompcie obniża częstość błędu; deterministyczny guard
> w kodzie sprowadza ją do zera ALBO zamienia w kontrolowany retry.

## 1. `_clean_sql()` — normalizacja surowej odpowiedzi modelu, krok po kroku

Wejście: string z pola `sql` JSON-a modelu. Kolejność operacji MA znaczenie:

1. Zdejmij fence'y: `re.sub(r"```(?:sql)?", "")` — model owija kod w markdown.
2. Backticki MySQL: `` `OrderDate` `` → `orderdate` (lowercase bez cudzysłowów)
   — nawyk modeli trenowanych na MySQL; Postgres + pandas = lowercase.
3. CamelCase w cudzysłowach: `"OrderDate"` → `orderdate`; wyjątek: identyfikator
   CAŁY wielkimi literami zostaje (świadomie — to zwykle stała, nie kolumna).
4. Komentarze blokowe `/* */` i liniowe `--` — precz (mogą zawierać drugi SQL).
5. Prefiks `sql:` / `SQL` przed zapytaniem — precz.
6. Utnij na pierwszym `;` — pierwsza instrukcja.
7. **Wykrywanie drugiego SELECT-a bez średnika**: skan liniowy z licznikiem
   głębokości nawiasów; drugi `SELECT` na głębokości 0 = początek KOLEJNEGO
   zapytania → utnij. Licznik nawiasów chroni podzapytania i CTE
   (`WITH x AS (SELECT...) SELECT...` ma SELECT-y w nawiasach — nie tnie się).

Przykład wejście→wyjście:
````
```sql
-- policz sprzedaż
SELECT `Produkt`, SUM("Wartosc") AS suma FROM sklep GROUP BY 1;
SELECT * FROM sklep;
```
→  SELECT produkt, SUM(wartosc) AS suma FROM sklep GROUP BY 1
````

## 2. `_run_and_validate(schema, sql, chart_type)` — walidacja przez wykonanie

```python
conn = _pg_conn(schema_name, readonly=True)   # ROLA READONLY — patrz docs/10
cur.execute(sql)                              # prawdziwe wykonanie, nie EXPLAIN
cols = [d[0] for d in cur.description]
sample = cur.fetchmany(5)                     # próbka do dalszych guardów
```
- Sukces syntaktyczny ≠ sukces walidacji: po wykonaniu jeszcze
  `_check_label_column` i (dla licznika) `_check_smartscalar_shape`.
- Wyjątek Postgresa → `_hint_missing_column(schema, błąd)` wzbogaca komunikat
  o listę ISTNIEJĄCYCH kolumn podobnych tabel — model w retry dostaje nie
  tylko „column x does not exist", ale i podpowiedź, co istnieje.
- **Dlaczego wykonanie, nie parsowanie**: jedyny test, który łapie wszystko
  naraz (składnię, istnienie kolumn, typy, sens agregacji) — i produkuje
  błąd w formie, którą model rozumie w retry.

## 3. Guardy okołodatowe

- `_RELATIVE_DATE_FILTER = (current_date|now())\s*[-+]\s*interval` —
  odrzucenie PRZED wykonaniem (pusty wynik byłby „poprawny", więc wykonanie
  by go nie złapało!). Rodowód: dane 2024, zegar 2026 → wykres „No results".
- `_RELATIVE_PERIOD_IN_TITLE` — regex fraz „w ostatnich N miesiącach/latach..."
  w TYTULE; jeśli finalny SQL nie ma WHERE (bo retry usunął filtr), fraza
  jest wycinana z tytułu (tytuł nie może obiecywać filtra, którego nie ma).
  Aplikowany w `finalize-chart`.

## 4. Guardy kształtu wyniku

- `_check_label_column(cols, sample, ctype)` — pierwsza kolumna (etykieta)
  nie może wyglądać jak metryka: sufiksy `_id,_lenght,_length,_qty,_count,
  _size,_weight,_price,_value,_num`. Sprawdzamy NAZWĘ, nie wartości —
  bo `review_score` 1–5 to legalna kategoria liczbowo wyglądająca.
  Wyjątki: `smartscalar`, `scatter` (tam pierwsza kolumna MA być
  numeryczna/datowa).
- `_check_smartscalar_shape(cols, sample)` — licznik w Metabase to wykres
  TRENDU: pierwsza kolumna musi być datą (próbka wartości parsowalna jako
  data), inaczej karta pada z „Group only by a time field". Rodowód: D5.
- `_check_category_cardinality(cur, sql, cols, ctype)` (2026-07-24) — kołowy
  z >8 unikalnymi wartościami w kolumnie etykiety, albo liniowy z >8 unikalnymi
  wartościami w kolumnie serii (gdy są ≥3 kolumny: data + seria + miara —
  zwykły 1-seryjny trend, 2 kolumny, nie jest sprawdzany). Jedyny guard, który
  NIE wystarcza sobie próbką 5 wierszy z `_run_and_validate` — dolicza
  `SELECT COUNT(DISTINCT kolumna) FROM (sql) AS sub` na PEŁNYM wyniku, na tym
  samym, jeszcze otwartym połączeniu, zanim `conn.close()`. Rodowód: analiza
  punktu 6 uwag promotora (docs/09 §6) — realne dashboardy z 165-kategoriowym
  wykresem kołowym (Metabase zwija ogon w „Other" = 78% całości, co i tak
  czyni wykres bezużytecznym) i 25-seriowym wykresem liniowym (nieczytelny
  „spaghetti chart"), zweryfikowane też wizualnie w przeglądarce. Odróżnia się
  od `_check_label_column`/`_check_has_metric` tym, że tytuł i SQL mogą być ze
  sobą w pełni zgodne — problem jest w LICZBIE kategorii względem wybranego
  typu wykresu, nie w treści zapytania.

## 5. Guardy TOP N (trzy różne!)

| Miejsce | Kierunek | Mechanizm |
|---|---|---|
| enhance | user NIE podał liczby, model wymyślił | `re.sub(r'\btop\s+\d+\b','TOP')` gdy prompt bez cyfr |
| enhance | user PODAŁ, model zgubił | jeśli liczba z `top (\d+)` promptu nie występuje w wyniku → dopisz „Zachowaj limit: TOP N."; UWAGA v1 tego guardu była błędna (sprawdzała DOWOLNĄ liczbę — rok „2024" maskował zgubione „10") |
| process-sql-attempt | goal ma `top N`, SQL bez LIMIT | deterministyczne doklejenie ` LIMIT N` (koniec zapytania, po zdjęciu `;`) — bez retry, bo naprawa jest pewna składniowo |

Guard SQL działa **per wykres po jego goal**, nie po prompcie usera —
inaczej wykres trendu w tym samym dashboardzie też dostałby LIMIT.

## 6. Guard 0 wierszy (2026-07-06)

Po udanym wykonaniu: `if ok and not sample:` → `ok=False` + komunikat
(„...sprawdź warunki WHERE — zakres dat może nie występować w danych, JOIN
może łączyć puste tabele...") → normalny retry; po 3 próbach wykres pomijany
i widoczny w żółtym ostrzeżeniu. Rodowód: pusta karta „No results!" (D5 —
puste tabele demograficzne northwinda; F4 — rok 2024 poza zakresem danych).
Świadomy trade-off: legalnie pusty wynik też zostanie odrzucony — uznaliśmy,
że pusta karta nigdy nie jest lepsza od jawnego ostrzeżenia.

## 7. Guardy enhance/clarify (języko-intencyjne)

- CJK/cyrylica w wyniku enhance → całkowite odrzucenie, zwrot oryginału
  (+ surowa odpowiedź doprecyzowująca, by intencja nie przepadła).
- Wynik zawiera SQL → wycinane są linie ze słowami kluczowymi SQL.
- **Rdzenie słów**: z odpowiedzi doprecyzowującej bierzemy słowa ≥4 znaki,
  tniemy do 5 pierwszych znaków (radzi sobie z polską fleksją:
  „miesięcznym"/„miesięczny" → `miesi`); jeśli ŻADEN rdzeń nie występuje
  w wyniku → odpowiedź doklejana jawnie („Uwzględnij: ..."). ZNANA GRANICA:
  guard nie wykryje przekręcenia SENSU (słowo jest, znaczenie inne) —
  przykład do rozdziału o granicach determinizmu.

## 8. `_text_column_values()` — wiedza o wartościach (2026-07-06, z testu B4)

Problem klasy text-to-SQL: model zna NAZWY kolumn, nie ZAWARTOŚĆ → z frazy
„podpisanych umów" + kolumny `data_podpisania` wyhalucynował
`WHERE status='podpisana'`, a prawdziwe wartości to
`zakończona / w trakcie / anulowana` → 0 wierszy → retry powtarzał błąd.

Rozwiązanie: przed wysłaniem do n8n backend dokleja do `schema_text` sekcję:
```
Znane wartosci kolumn tekstowych (w WHERE uzywaj WYLACZNIE tych dokladnych wartosci...):
- umowy.status: 'anulowana', 'w trakcie', 'zakończona'
- klienci.branza: 'finanse', 'handel', 'produkcja', 'usługi'
```
Selekcja: kolumny `text`, 2–8 wartości unikalnych w próbce 500 wierszy
(`SELECT DISTINCT ... FROM (... LIMIT 500)` — tanio nawet na olist),
wartości ≤40 znaków, max 12 kolumn. Efekt zmierzony: B4 z 2/3 wykresów
i 3 retry → 3/3 i 0 retry.

## 9. Guardy przepływu (n8n)

- IF `Trzeba Retry Planu?` — plan w obcym języku → jedna powtórka z ostrzeżeniem.
- IF `Sa Wykresy?` — 0 wykresów → jawny błąd zamiast wiszącego webhooka.
- Backend: pusta/nie-JSON odpowiedź n8n → czytelne „generowanie przerwane —
  najczęściej Ollama albo Metabase nie odpowiada" (zamiast `Expecting value...`).
- Frontend: `data.detail` z backendu pokazywany wprost (nie generyczny komunikat).

## 10. Mapa: który guard gdzie mieszka

```
frontend:  komunikaty błędów, reuse opisu
backend /enhance:   TOP N (oba kierunki), CJK, SQL-strip, rdzenie słów
backend /describe:  guard pustego schematu, strip CJK/cyrylicy
backend /internal/process-plan:    język planu, wymuszenie typów, fallback tytułu
backend /internal/process-sql-attempt: _clean_sql, relative-date, TOP N->LIMIT,
                                       wykonanie+kształt, kardynalność pie/line,
                                       0 wierszy, log FAIL
backend /internal/finalize-chart:  okres względny w tytule, wybór displayu
backend /generate:  _text_column_values, czytelny błąd nie-JSON
n8n:       retry planu (IF), pętla 3 prób SQL, bramka 0 wykresów,
           dobór kolumny daty per wykres, typ tagów 'date'
postgres:  rola readonly (guard ostateczny)
```

## Sprawdź się
1. Dlaczego `_RELATIVE_DATE_FILTER` musi działać PRZED wykonaniem, a guard
   0 wierszy PO wykonaniu?
2. Jak licznik głębokości nawiasów ratuje CTE przed ucięciem?
3. Opisz błąd pierwszej wersji guardu „zgubiony TOP N" i czemu był podstępny.
4. Które DWA guardy mają znaną, nazwaną granicę skuteczności i jaką?
5. Wybierz dowolny wiersz z mapy §10 i uzasadnij, czemu ten guard mieszka
   właśnie tam, a nie warstwę wyżej/niżej.
