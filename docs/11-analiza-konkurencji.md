# 11 — Analiza konkurencji: przegląd istniejących rozwiązań NL-to-SQL / auto-dashboard (deep dive)

> Część serii `docs/`. Przegląd całości: `DOKUMENTACJA.md`.
> Materiał do rozdziału 2.2 pracy (`Teoria/PLAN_PRACY.md`) — realizacja punktu 8 z uwag
> promotora ze spotkania 2026-07-08 (przekazanych 2026-07-23): brakujący przegląd istniejących
> rozwiązań działających na podobnej zasadzie. Research zrobiony 2026-07-24 — rynek AI-BI
> zmienia się szybko (patrz np. wycofanie Power BI Q&A poniżej), przed wysyłką pracy warto
> zweryfikować, czy opisane funkcje/ceny się nie zmieniły.

## 1. Kryteria porównania

Dla każdego narzędzia sprawdzono to, co odróżnia ten projekt od reszty rynku (patrz
`CLAUDE.md` — architektura jest CELOWO lokalna):

1. Czy działa lokalnie/offline, bez wysyłania danych do zewnętrznej chmury.
2. Czy z JEDNEGO polecenia w języku naturalnym powstaje CAŁY dashboard złożony z wielu
   wykresów, czy tylko pojedynczy wynik/wykres na pytanie.
3. Model kosztowy (open source / self-host / SaaS / enterprise).
4. Wsparcie języka polskiego — żadne z poniższych narzędzi go nie promuje.

## 2. Tabela porównawcza

| Narzędzie | Typ | Lokalnie/offline | Cały dashboard z 1 polecenia | Model kosztowy | Uwaga |
|---|---|---|---|---|---|
| **Ten projekt** | prototyp inżynierski | **TAK** (Ollama lokalny) | **TAK** (plan 2–4 wykresów + walidacja SQL z retry) | darmowy, self-host | polski, walidacja SQL na prawdziwym pliku/bazie |
| Power BI Copilot | komercyjny, wbudowany | NIE (Azure OpenAI) | częściowo — sugeruje wizualizacje i odpowiada na pytania, nie buduje całego dashboardu za jednym poleceniem | licencja Microsoft 365/Fabric | starsza funkcja Q&A (czyste NL-zapytania) ma zostać wycofana do końca 2026 na rzecz Copilota |
| Tableau Pulse / Ask Data | komercyjny, wbudowany | NIE (Salesforce Cloud) | NIE — odpowiedzi punktowe/metryki push, nie pełny raport | licencja Tableau + Salesforce | nacisk na gotowe "metryki" i powiadomienia, nie na budowę raportu od zera |
| ThoughtSpot Spotter | komercyjny, enterprise | NIE (wymaga hurtowni danych w chmurze / Spotter Semantics) | częściowo — search-driven, buduje pojedyncze liveboardy | enterprise, wycena indywidualna | wskazywany jako lider governed NL-analytics na 2026 |
| **Metabase AI (Metabot, od wersji 59, marzec 2026)** | wbudowany w narzędzie wizualizacji użyte w TYM projekcie | NIE (wymaga klucza API Anthropic) | NIE — jednostrzałowe generowanie SQL w edytorze, bez planowania wielu wykresów | darmowe w Open Source, ale wymaga płatnego API Anthropic | **najbliższy i najbardziej aktualny punkt odniesienia** — patrz sekcja 4 |
| Vanna.ai | open source (MIT) + SaaS | TAK, możliwe (współpracuje z Ollama, dowolna baza) | NIE — biblioteka do SQL + pojedynczej wizualizacji, nie planer dashboardu | darmowy self-host / ok. 30 USD za milion tokenów w wersji zarządzanej | architektonicznie najbliższy "kuzyn" (RAG nad przykładami zapytań), ale to biblioteka dla developerów, nie gotowa aplikacja z kontami i historią |
| WrenAI | open source + enterprise | TAK, możliwe (self-host, wariant "air-gapped" w Enterprise Plus) | częściowo — jawny model semantyczny (MDL), odpowiedzi/wykresy per pytanie | darmowy self-host / enterprise na wycenę | inne podejście niż RAG: jawnie zakodowany model semantyczny zamiast samego wyszukiwania podobieństwa |

## 3. Krótkie profile

### Power BI Copilot i wycofywane Q&A
Copilot korzysta z Azure OpenAI: generuje podsumowania raportów, sugeruje wizualizacje,
odpowiada na pytania w języku naturalnym i potrafi zaproponować formułę DAX. Microsoft
ogłosił wycofanie starszej, czysto zapytaniowej funkcji Q&A do grudnia 2026 na rzecz
Copilota — sygnał, że rynek przesuwa się w stronę asystentów konwersacyjnych osadzonych
w chmurowym ekosystemie dostawcy, a nie lekkich, lokalnych rozwiązań.

### Tableau Pulse / Ask Data
Należy do Salesforce; nacisk na "metryki" wypychane do użytkownika (Pulse) i punktowe
pytania (Ask Data), nie na budowę wielowykresowego raportu z jednego polecenia. Działa
wyłącznie w chmurze Salesforce/Tableau.

### ThoughtSpot Spotter
Wskazywany w porównaniach z 2026 roku jako lider "governed natural-language analytics"
dla danych na żywo w hurtowniach chmurowych. Mechanizm to wyszukiwanie (search-driven)
po warstwie semantycznej Spotter, nie planowanie wielu wykresów przez LLM od zera.

### Metabase AI / Metabot — najważniejszy punkt odniesienia
Metabase — narzędzie użyte w tym projekcie WYŁĄCZNIE jako silnik wizualizacji (karty,
dashboardy, publiczne linki) — od wersji 59 (marzec 2026) ma własną funkcję generowania
SQL z języka naturalnego wprost w edytorze SQL, oraz asystenta "Metabot" do pytań o dane
i wyjaśniania wykresów. Kluczowe ograniczenia względem tego projektu: (1) wymaga klucza
API Anthropic — nie działa lokalnie/offline; (2) generuje SQL "jednostrzałowo" do JEDNEJ
karty na raz, nie planuje ani nie buduje całego dashboardu z wielu powiązanych wykresów
z jednego polecenia, jak robi to orchestrator n8n w tym projekcie.

### Vanna.ai
Open source (MIT), architektura oparta o RAG: model dostaje trafne przykłady zapytań
dobrane przez podobieństwo wektorowe i na tej podstawie generuje SQL. Współpracuje z
lokalnymi modelami przez Ollama i z dowolną bazą danych. To jednak biblioteka/komponent
do wbudowania we własną aplikację przez developera, nie gotowy produkt z kontami
użytkowników, uploadem własnych plików i historią zapytań.

### WrenAI
Open source, z wariantem enterprise (w tym self-hosted "air-gapped", czyli w pełni
odciętym od sieci). Zamiast polegać na przykładach dobieranych przez RAG (jak Vanna),
WrenAI wymaga jawnego, ręcznie zdefiniowanego modelu semantycznego (MDL — Modeling
Definition Language w formacie JSON) opisującego pojęcia biznesowe, relacje i metryki.
Ciekawy kontrapunkt architektoniczny: ten projekt idzie bliżej podejścia Vanna
(automatyczny `schema_text`/opis AI generowany ze schematu, bez ręcznego modelu
semantycznego), kosztem mniejszej kontroli nad tym, jak model rozumie dane.

## 4. Czym różni się ten projekt (materiał do 2.2 i do rozdz. 6 — Dyskusja)

- **Lokalność jako wymóg projektowy, nie opcja.** Wszystkie trzy komercyjne narzędzia
  (Power BI, Tableau, ThoughtSpot) wymagają chmury dostawcy. Nawet Metabase — narzędzie
  wizualizacji użyte w TYM projekcie — wymaga płatnego klucza API Anthropic dla własnej
  funkcji AI. Jedyne dwa realnie lokalne rozwiązania (Vanna, WrenAI) to biblioteki/komponenty
  do wbudowania w aplikację, nie gotowe produkty z kontami i uploadem danych jak ten projekt.
- **Cały dashboard z jednego polecenia.** Żadne z porównanych narzędzi nie planuje
  wielu powiązanych wykresów (z walidacją SQL na prawdziwych danych i retry) z pojedynczego
  polecenia w języku naturalnym — najbliżej jest ThoughtSpot Spotter, ale mechanizm jest
  inny (wyszukiwanie po warstwie semantycznej, nie planowanie przez LLM).
- **Aktualny, konkretny argument do Dyskusji:** narzędzie wizualizacji użyte w projekcie
  (Metabase) zdobyło WŁASNĄ funkcję AI SQL generation (Metabot, marzec 2026) już PO
  rozpoczęciu prac nad tym systemem — a mimo to robi mniej (jeden SQL na polecenie w
  edytorze) i wymaga chmurowego klucza Anthropic, podczas gdy orchestrator n8n w tym
  projekcie planuje wiele wykresów i działa w pełni lokalnie na modelu 7B. To bezpośredni
  dowód, że problem rozwiązywany w pracy jest aktualny i nie jest jeszcze rozwiązany
  "za darmo" przez istniejącą infrastrukturę projektu.
- **Brak wsparcia języka polskiego** w żadnym z powyższych — spójne z luką motywującą
  pracę opisaną w `Teoria/PLAN_PRACY.md`, rozdz. 1.1.

## 5. Kontekst akademicki (uzupełnienie, nie zamiennik powyższego)

Powyższe to narzędzia PRODUKCYJNE. Równolegle istnieje osobny nurt akademicki — benchmarki
text-to-SQL takie jak Spider i Spider 2.0 (już omówione z promotorem — `golden_set.py`
w tym projekcie jest metodologicznie "mini-Spider po polsku", patrz `docs/09` pkt 4).
Różnica: benchmarki oceniają samo tłumaczenie pojedynczego pytania na SQL na gotowej,
zwykle anglojęzycznej bazie referencyjnej — nie generowanie całego dashboardu z wielu
wykresów ani obsługę danych samodzielnie wgrywanych przez użytkownika.

## Sprawdź się
1. Które z porównanych narzędzi nie wymaga połączenia z chmurą — i dlaczego to i tak
   nie czyni go pełnym odpowiednikiem tego projektu?
2. Dlaczego akurat Metabase AI/Metabot jest „najważniejszym punktem odniesienia" spośród
   wszystkich porównanych narzędzi?
3. Czym różni się podejście WrenAI (MDL) od podejścia Vanna.ai (RAG nad przykładami) —
   i do którego z nich bliżej jest sposobowi, w jaki ten projekt buduje `schema_text`
   i opis bazy (`_describe_schema`)?
4. Czym różni się cel benchmarków Spider/Spider 2.0 od celu `golden_set.py` w tym projekcie?

## Źródła
- [Best AI Analytics Platforms: 13 Tools Reviewed (2026) — Holistics](https://www.holistics.io/blog/ai-analytics-platforms/)
- [Best AI BI Tools (2026): A Fact-Based Comparison — Holistics](https://www.holistics.io/bi-tools/ai-analytics/)
- [ThoughtSpot vs Power BI vs Tableau 2026 — Querio](https://querio.ai/articles/natural-language-query-business-intelligence-thoughtspot-vs-power-bi-vs-tableau-2026)
- [NLP in Power BI: Q&A, Copilot & 2026 Guide — NeenOpal](https://www.neenopal.com/blog/NaturalLanguageProcessing)
- [AI Releases — Metabase (oficjalne)](https://www.metabase.com/releases-ai)
- [Metabase 59 release notes — Metabase (oficjalne)](https://www.metabase.com/releases-ai/metabase-59)
- [SQL generation — Metabase docs](https://www.mintlify.com/metabase/metabase/ai/sql-generation)
- [Metabot — Metabase AI assistant — Metabase docs](https://www.metabase.com/docs/latest/ai/metabot)
- [Metabase AI — strona produktowa](https://www.metabase.com/features/metabase-ai)
- [Wren AI vs. Vanna: The Enterprise Guide to Choosing a Text-to-SQL Solution — getwren.ai](https://www.getwren.ai/post/wren-ai-vs-vanna-the-enterprise-guide-to-choosing-a-text-to-sql-solution)
- [Dissecting Open-Source NL2SQL: Vanna, WrenAI, DB-GPT — Sudipta Pathak](https://sudiptapathak.com/blog/dissecting-open-source-nl2sql/)
- [Wren AI Pricing](https://www.getwren.ai/pricing)
- [Vanna 2.0 Pricing](https://vanna.ai/pricing)
