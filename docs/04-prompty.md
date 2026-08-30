# 04 — Prompty: pełna treść z adnotacjami (deep dive)

> Plik: `backend/prompts.json`, ładowany do `PROMPTS` przy starcie; edytowalny
> przez `PUT /prompts` (z walidacją placeholderów). KAŻDA reguła w tych
> szablonach ma rodowód w konkretnym bugu — adnotacje [→ skąd].

## 1. `plan_prompt` — planowanie dashboardu

Placeholdery: `types_instruction, goal, chart_type, description, schema_text`.

Kluczowe reguły i ich rodowody:
- *„Pola 'title' i 'goal' pisz WYLACZNIE po polsku — nigdy po angielsku,
  wegiersku..."* [→ plan wygenerowany CAŁY po węgiersku przy pustym opisie;
  sama instrukcja nie wystarcza — jest jeszcze guard `_is_foreign_language`
  + retry planu]
- *„Jako etykiety uzyj kolumn TEXT z nazwami/kategoriami — NIGDY kolumn ID"*
  [→ wykresy z `customerid` na osi zamiast nazw firm; wsparte guardem
  `_check_label_column`]
- *„Jesli trzeba pokazac klientow/produkty/pracownikow — napisz explicite
  zeby uzyc JOIN i kolumny z nazwa"* [→ plan mówi „pokaż klientów", SQL robił
  to bez JOIN po samych ID]
- *„Jesli CEL zawiera slowa: trend/miesiac/rok/czas — MUSISZ dodac wykres
  z kolumna daty"* + *„GROUP BY DATE_TRUNC..."* [→ trend bez daty = filtr dat
  nie ma się do czego podpiąć]
- `{types_instruction}` — dynamiczna: gdy user wybrał typy, wstrzykiwane jest
  „UZYTKOWNIK ZADA DOKLADNIE N WYKRESOW W TEJ KOLEJNOSCI: (1) chart_type=bar..."
  (budowane w `/internal/plan-prompt` z `_parse_requested_charts`); bez wyboru
  (2026-07-24, było „Wygeneruj 3-4 roznorodne wykresy (bar, line, pie, table)"
  [→ przyczyna: 12/13 dashboardów 3-wykresowych miało DOKŁADNIE zestaw
  {bar, line, pie} niezależnie od treści promptu — instrukcja kazała być
  „różnorodnym", nie dobierać formy do treści, patrz `docs/09` §6]) — teraz
  jawne kryterium per pod-cel: trend→line, ranking/TOP N→bar, udział ≤5-6
  kategorii→pie, zestawienie szczegółowe→table, przy niepewności pie/bar→bar.
  Zweryfikowane, że model już NIE dociąga sztucznie trzeciego/innego typu gdy
  nie ma po temu podstawy (dwa pod-cele rankingowe → `bar`+`bar`, nie
  `bar`+`pie`).
- Wyjście wymuszone: `{"charts":[{"title","chart_type","goal"}]}` — dzięki
  `format:"json"` w wywołaniu Ollamy (ścieżka SQL) / zdejmowaniu fence'ów
  (natywny LLM Chain w planie).

**Znane ograniczenie plannera:** przy celu „jednowykresowym" model dopełnia
plan wykresami z własnej inwencji (czasem przepisanymi z sekcji „Możliwe
analizy" opisu AI — „opis rozprasza plan"). Obejście: jawny wybór typów.

## 2. `sql_prompt` — generowanie pojedynczego SQL-a

Placeholdery: `chart_hint, goal, schema_text`.

Reguły i rodowody (wybór najważniejszych):
- *„TYLKO jedno zapytanie SELECT, zadnych srednikow"* [→ model zwracał
  2-3 zapytania naraz; dodatkowo `_clean_sql` tnie deterministycznie]
- *„Kolumny konczace sie na _id, _lenght, _length, _qty... NIE uzywaj jako
  etykiet"* [→ superstore/olist mają kolumny `product_name_lenght` (sic!) —
  literówka W DANYCH źródłowych olist, stąd `_lenght` w regule]
- *„NIGDY nie uzywaj CURRENT_DATE, NOW()... dane testowe moga byc z innego
  okresu niz biezaca data"* [→ dane z 2024, zegar z 2026 → `WHERE data >=
  CURRENT_DATE - INTERVAL '12 months'` zwracał PUSTO; wsparte guardem
  `_RELATIVE_DATE_FILTER` który odrzuca taki SQL zanim dotknie bazy]
- *„Aliasy kolumn pisz po polsku bez znakow diakrytycznych"* [→ osie wykresów
  po angielsku = language drift; bez diakrytyków, bo trafiają do nazw kolumn]
- *„wszystkie nazwy tabel i kolumn sa MALYMI LITERAMI"* [→ pandas importuje
  lowercase; `"OrderDate"` = błąd kolumny; wsparte normalizacją w `_clean_sql`]
- *„NIE uzywaj backtickow"* [→ nawyk MySQL modeli code'owych; `_clean_sql`
  i tak je zdejmuje]
- `{chart_hint}` — doklejany TYLKO dla trudnych typów (patrz §4).
- Wyjście: `{"sql":"SELECT ..."}` (format:"json").

## 3. `sql_retry_suffix` — pętla naprawcza

```
POPRZEDNI SQL nie zadzialal: {sql}
BLAD: {err}
Popraw blad i zwroc poprawiony JSON.
```
Doklejany do `sql_prompt` przy próbie 2 i 3. `{err}` to PEŁNA treść błędu:
Postgresa (np. `column "x" does not exist` — wzbogacony o podpowiedź
`_hint_missing_column`), albo guardów (relative date, 0 wierszy, kształt
licznika, zła etykieta). **To serce mechanizmu samonaprawy** — 29 skutecznych
auto-korekt w harnessie.

## 4. `_CHART_HINTS` — instrukcje per trudny typ wykresu (w kodzie, nie w json)

| Typ | Sedno hinta | Rodowód |
|---|---|---|
| `scatter` | dokładnie 2 kolumny NUMERYCZNE, agreguj do sensownej liczby punktów | scatter z tekstową osią nie renderował |
| `smartscalar` | to wykres TRENDU: `DATE_TRUNC('month',...)` + JEDEN agregat, sort po miesiącu; przykład w treści | Metabase: „Group only by a time field"; wcześniejszy hint kazał zwracać 1 wiersz i właśnie to psuło karty (naprawa D5) |
| `funnel` | etykieta TEXT + wartość, sort malejąco | puste lejki |
| `waterfall` | MUSISZ policzyć różnice rok-do-roku przez `LAG()`; pełny wzorzec CTE w treści | waterfall to najtrudniejszy typ dla 7B — nawet z wzorcem bywa porażka (znane ograniczenie) |
| `combo` | data/kategoria + ≥2 kolumny numeryczne | — |

## 5. `describe_schema` — opis bazy prozą

Wymusza strukturę (domena → tabele z kolumnami → relacje FK → przykłady analiz)
i czystą polszczyznę: *„ani jednego chinskiego... znaku, nawet w nazwach branz
(pisz 'e-commerce', NIGDY chinskich znakow)"* [→ „branży电子商务" w opisie].
Po stronie kodu i tak jest strip CJK+cyrylicy [→ „Wключaj"] — podwójna warstwa.
Bez `format:"json"` (proza), timeout 600 s [→ opis northwinda nie mieścił się w 300 s].

## 6. `enhance_prompt` — przepisywanie celu

Najbardziej „obłożony" regułami szablon, bo enhance najłatwiej psuje intencję:
- *„KRYTYCZNE: NIE ZMIENIAJ SENSU... 'TOP 20 pracownikow' zostaw"* + przykład
  [→ model dodawał kryterium „najmłodszych" z powietrza]
- *„jesli 'TOP' bez LICZBY — NIE wymyslaj liczby"* + guard w kodzie usuwający
  wymyślone `TOP \d+` [→ „top produkty" → „TOP 20 produktów"]
- Sekcja DOPRECYZOWANIE (placeholder `{clarification}` **na końcu** szablonu —
  w środku był ignorowany!): *„odpowiedz... WPLEC w tresc... 'na podstawie
  miast' to GRUPOWANIE, NIE filtr"* + przykład dobrego/złego wyniku
  [→ model robił z odpowiedzi filtr „tylko w różnych miastach"]
- Guardy w kodzie po odpowiedzi: strip SQL-owych linii, CJK→fallback,
  TOP N w obie strony, rdzenie słów (docs/06 §7).

## 7. `clarify_prompt` — jedno pytanie doprecyzowujące

Definiuje binarnie, kiedy cel jest JASNY (ma zakres + granulację czasu jeśli
trend + N jeśli TOP) i few-shoty obu przypadków [→ bez few-shotów 7B pytał
o oczywistości typu „czy pokazać wykres?"]. Wyjście: `{"question": null|"..."}`.

## 8. Warianty `*_sqlcoder` (nieużywane, zostawione)

Pozostałość eksperymentu z modelem `sqlcoder:7b` (format promptu `### Task /
### Database Schema / ### Question`). Wybór modelu: `OLLAMA_SQL_MODEL`;
gdy zawiera „sqlcoder", kod używa tych szablonów i buduje schemat jako DDL
(`_build_ddl_schema`). Wniosek z eksperymentu: qwen2.5-coder radził sobie
lepiej z polskimi celami — sqlcoder odłożony, infrastruktura została.

## 9. Mechanizm bezpieczeństwa edycji promptów

`PUT /prompts` parsuje nowy szablon `string.Formatter` i wymaga, by zawierał
WSZYSTKIE placeholdery z `_PROMPT_PLACEHOLDERS[klucz]` — inaczej 400.
Bez tego literówka w edytowanym szablonie wywalałaby `KeyError` dopiero
w środku generowania.
