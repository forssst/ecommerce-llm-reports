# Plan testów manualnych — system „AI Data Analyst"

Testy należy wykonywać w podanej kolejności. Przy każdym teście: cel analityczny wpisać
dokładnie w brzmieniu podanym w scenariuszu, a wynik odnotować w polach wyboru.
W przypadku niezgodności z oczekiwanym rezultatem należy wykonać zrzut ekranu
i zanotować identyfikator testu (np. „B4 — wynik negatywny").

Oznaczenia: „Cel testu:" — główna właściwość systemu weryfikowana danym scenariuszem.

---

## A. sklep_testowy.csv — regresja podstawowa (baza wgrana wcześniej)

### A1 — Ulepszanie promptu: pełny przepływ z pytaniem doprecyzowującym
Cel testu: połączony przepływ doprecyzowania i ulepszania promptu (clarify → enhance).
1. Cel: `pokaż produkty` → przycisk **Ulepsz prompt AI**
2. Oczekiwane: pytanie doprecyzowujące (wyróżnione pole)
3. Odpowiedź: `na podstawie miast` → przycisk **Ulepsz z odpowiedzią**
- [x] Prompt przepisany po polsku, zawiera podział/grupowanie po miastach
- [x] NIE zawiera filtru typu „tylko w różnych miastach"
- [x] NIE wprowadza nieistniejących kolumn klienta (imię/nazwisko nie występują w tej bazie)
4. Przycisk **Generuj Dashboard**
- [x] Wykresy faktycznie grupują dane po miastach

### A2 — Filtr dat i guard językowy
Cel testu: widget „Zakres dat" na dashboardzie oraz polskojęzyczne tytuły wykresów.
1. Wyczyścić opis bazy (pozostawić pusty), cel: `trend sprzedaży miesięcznej` → **Generuj Dashboard**
- [x] Na dashboardzie obecny widget **Zakres dat**
- [x] Tytuły wykresów w języku polskim (bez wtrąceń węgierskich/angielskich)
- [x] Opisy osi w języku polskim (aliasy kolumn)
2. Ustawić w widgecie zakres `2024-01-01 – 2024-03-31`
- [x] Wykres trendu zawęża się do 3 miesięcy
3. Ustawić zakres z roku 2026
- [x] Wykres z datą jest pusty (dane pochodzą z 2024 roku — zachowanie poprawne)

### A3 — Wybór typów wykresów
Cel testu: respektowanie typów wykresów wskazanych przez użytkownika (poprawka z 2026-07-01).
1. Wybrać w kolejności: **Licznik**, **Kołowy**, **Liniowy**
2. Cel: `podsumowanie sprzedaży sklepu` → **Generuj Dashboard**
- [x] Dokładnie 3 wykresy
- [x] Typy zgodne z kolejnością wyboru: licznik (pojedyncza wartość), kołowy, liniowy

---

## B. firma_uslugi.xlsx — arkusz wieloarkuszowy, polskie nazwy kolumn

### B1 — Wczytanie pliku i odczyt schematu
Cel testu: import wielu arkuszy oraz detekcja polskich kolumn dat
(`data_podpisania` itp. → typ TIMESTAMP).
1. Wgrać plik `firma_uslugi.xlsx`
2. Rozwinąć **Pokaż tabele i kolumny**
- [x] 3 tabele: `klienci`, `pracownicy`, `umowy`
- [x] Kolumny `data_rejestracji`, `data_zatrudnienia`, `data_podpisania` mają typ **timestamp** (nie text)

### B2 — Generowanie opisu AI
Cel testu: opis w języku polskim, bez znaków z obcych alfabetów, z poprawnymi relacjami.
- [x] Opis po polsku, bez wtrąceń chińskich/rosyjskich/węgierskich
- [x] Wskazuje powiązania `klient_id` / `pracownik_id` (w tej bazie rzeczywiście istnieją)

### B3 — Złączenie dwóch tabel
Cel: `wartość umów według miast klientów`
- [x] Wykres prezentuje miasta (Warszawa, Kraków itd.) — wymaga złączenia umowy+klienci
- [x] Wartości sumaryczne są wiarygodne

### B4 — Filtr dat na polskich kolumnach (test krytyczny)
Cel testu: weryfikacja poprawki z 2026-07-02 — detekcja kolumny daty po polskiej nazwie.
Cel: `trend wartości podpisanych umów miesięcznie`

- [x] Widget **Zakres dat** obecny na dashboardzie
- [ ] Zawężenie zakresu faktycznie filtruje wykres (dane: 2024-2025)

### B5 — Pominięcie pytania doprecyzowującego
Cel testu: możliwość kontynuacji bez odpowiedzi na pytanie doprecyzowujące.
1. Cel: `pokaż umowy` → **Ulepsz prompt AI** → oczekiwane pytanie doprecyzowujące
2. Wybrać **Pomiń** (bez udzielania odpowiedzi)
- [x] Ulepszanie wykonuje się mimo braku odpowiedzi, prompt przepisany po polsku

### B6 — Kombinacja: opis, ulepszenie promptu i wybór typów
1. **Generuj opis AI** → poczekać na wygenerowanie opisu
2. Cel: `zmiana łącznej wartości umów rok do roku` + typy: **Kaskadowy**, **Tabela**
3. **Ulepsz prompt AI** (odpowiedzieć na pytanie, jeśli się pojawi) → **Generuj Dashboard**
- [ ] 2 wykresy: kaskadowy (dopuszczalne wartości ujemne) oraz tabela
- [x] Tytuły w języku polskim

---

## C. superstore.xls — starszy format .xls, angielskie kolumny, ok. 10 tys. wierszy

### C1 — Wczytanie pliku .xls
Cel testu: weryfikacja poprawki z 2026-07-02 — obsługa formatu .xls (biblioteka xlrd).
1. Wgrać plik `superstore.xls`
- [x] Wczytanie przebiega bez błędu (przed poprawką: błąd HTTP 500)
- [x] 3 tabele: `orders`, `people`, `returns`

### C2 — Detekcja dat po nazwach angielskich
Rozwinąć **Pokaż tabele i kolumny**:
- [x] Kolumny `order_date` i `ship_date` mają typ timestamp

### C3 — Dwie miary na jednym wykresie
Cel: `sprzedaż i zysk według regionów`
- [x] Wykres z dwiema wartościami (sales, profit) w podziale na regiony

### C4 — Trend i filtr dat na większym zbiorze danych
Cel: `miesięczny trend sprzedaży` (ok. 10 tys. wierszy)
- [x] Generowanie kończy się poprawnie (dopuszczalny dłuższy czas)
- [x] Filtr dat obecny i działa poprawnie

---

## D. northwind.db — SQLite, wiele tabel, nazwy w konwencji CamelCase

### D1 — Wczytanie pliku .db
Cel testu: normalizacja nazw (CamelCase → małe litery, „Order Details" → `order_details`).
1. Wgrać plik `northwind.db`
- [x] Tabele widoczne z nazwami małymi literami: `customers`, `orders`, `order_details`, `products` itd.
- [x] Uwaga: może pojawić się techniczna tabela `sqlite_sequence` — znane zjawisko kosmetyczne, bez wpływu na działanie

### D2 — Opis AI z rzeczywistymi relacjami
**Generuj opis AI**:

- [x] Opisane relacje kluczy obcych (orders↔customers itd.) — w tej bazie rzeczywiście istnieją
- [x] Opis po polsku, bez znaków z obcych alfabetów

### D3 — Złączenie trzech tabel
Cel: `najlepsi klienci według łącznej wartości zamówień`
(wymaga tabel orders + order_details + customers)

- [x] Etykiety zawierają nazwy firm (nie identyfikatory)
- [x] Kwoty wiarygodne; odnotować liczbę automatycznych korekt SQL

### D4 — Trend i filtr dat
Cel: `trend liczby zamówień miesięcznie`
- [x] Filtr dat obecny, zawężanie zakresu działa

### D5 — Pełna kombinacja funkcji systemu
1. **Generuj opis AI** → 2. Cel: `raport sprzedaży` → 3. **Ulepsz prompt AI** →
   odpowiedzieć na pytanie (jeśli się pojawi) → 4. Typy: **Słupkowy**, **Kołowy**, **Licznik** →
   5. **Generuj Dashboard** → 6. **Pokaż SQL** → 7. **Otwórz w Metabase**
- [ ] Każdy krok przebiega poprawnie; typy wykresów zgodne z wyborem
- [x] „Pokaż SQL" prezentuje zapytanie każdego wykresu
- [x] Odnośnik do Metabase działa

---

## E. sakila.db — test obciążeniowy złączeń (materiał do rozdziału „Ewaluacja")

W tym bloku oczekiwane są potknięcia modelu 7B. Należy notować liczbę automatycznych
korekt SQL oraz charakter błędów — wyniki negatywne stanowią równie wartościowy
materiał badawczy jak pozytywne.

### E1 — Złączenie czterech tabel (najtrudniejsze w bloku)
Cel: `najpopularniejsze kategorie filmów według liczby wypożyczeń`
(category + film_category + inventory + rental)

- [x] Odnotować: sukces/porażka, liczba automatycznych korekt, czy kategorie mają nazwy

### E2 — Przypadek prostszy na tej samej bazie
Cel: `miesięczny przychód z płatności`
- [x] Trend w podziale miesięcznym (dane z lat 2005-2006), filtr dat obecny

### E3 — Złączenie dwóch tabel
Cel: `top 10 aktorów według liczby filmów`
- [x] Etykiety zawierają imiona i nazwiska aktorów (nie identyfikatory)

---

## F. Testy przekrojowe i negatywne

### F1 — Historia zapytań
- [x] Wszystkie wykonane generacje widoczne w historii
- [x] Wybranie wpisu z historii ponownie otwiera dashboard

### F2 — Izolacja użytkowników
1. Wylogować się, zarejestrować drugie konto testowe
- [x] Nowe konto NIE widzi baz ani historii pierwszego konta
2. Powrót na pierwsze konto — dane kompletne
- [x] Bazy i historia pierwszego konta nienaruszone

### F3 — Niepoprawny plik
Podjąć próbę wgrania pliku `.txt` lub `.pdf`
- [x] Czytelny komunikat błędu (brak awarii aplikacji / pustego ekranu)

### F4 — Cel jednoznaczny — brak pytania doprecyzowującego
Baza: **sklep_testowy.csv** (dane z 2024 roku — na innych bazach rok 2024 może nie występować)
Cel: `TOP 10 produktów według sumy sprzedaży z podziałem miesięcznym w 2024 roku` → **Ulepsz prompt AI**
- [x] System NIE zadaje pytania (cel jest kompletny) — od razu ulepsza prompt

### F5 — Fraza „top" bez liczby
Baza: **sklep_testowy.csv**
Cel: `top produkty` → **Ulepsz prompt AI** (ewentualnie odpowiedzieć na pytanie)
- [x] Ulepszony prompt NIE zawiera liczby dodanej przez model („TOP 10"/„TOP 20")

---

## G. Odporność na błędy i awarie usług (wymaga dostępu do terminala)

Blok weryfikuje, czy system kończy działanie w sposób kontrolowany: czytelny komunikat
błędu zamiast zawieszonego wskaźnika ładowania, pustego ekranu lub — w najgorszym
wariancie — uszkodzenia danych. Po każdym teście należy przywrócić usługę i sprawdzić,
że system wraca do pracy bez restartu pozostałych komponentów.
Polecenia wykonywać w katalogu projektu.

### G1 — Awaria Ollamy w trakcie pracy (najczęstsza awaria rzeczywista)
Cel testu: generowanie kończy się czytelnym błędem w skończonym czasie.
1. W terminalu: `docker stop ollama`
2. Cel: `suma sprzedaży według kategorii` (sklep_testowy) → **Generuj Dashboard**
- [ ] Pojawia się komunikat „Błąd generowania" z treścią (brak nieskończonego oczekiwania)
- [ ] Aplikacja pozostaje responsywna (można klikać, przełączać bazy)
3. `docker start ollama` → odczekać ok. 10 s → **Generuj Dashboard** ponownie
- [ ] Działa poprawnie, bez restartu backendu/frontendu

### G2 — Ollama wyłączona przy generowaniu opisu
Cel testu: ostrzeżenie w polu opisu (poprawka z 2026-07-05).
1. `docker stop ollama` → przycisk **Generuj opis AI**
- [ ] W polu opisu pojawia się komunikat „⚠ Nie udało się wygenerować opisu..." (nie puste pole, brak awarii)
2. `docker start ollama`

### G3 — Wyłączony n8n (orchestrator)
Cel testu: n8n jako jedyna ścieżka generowania stanowi pojedynczy punkt awarii —
awaria musi być sygnalizowana jawnie.
1. `docker stop n8n_local` → **Generuj Dashboard**
- [ ] Czytelny błąd (wskazujący n8n/orchestrator), zwracany szybko (sekundy, nie minuty)
2. `docker start n8n_local` → odczekać ok. 15 s → generowanie działa ponownie
- [ ] Działa bez dodatkowych czynności

### G4 — Wyłączony Metabase
Cel testu: awaria na końcu potoku przetwarzania (plan i SQL wykonują się poprawnie,
błąd występuje dopiero przy budowie dashboardu).
1. `docker stop metabase` → **Generuj Dashboard**
- [ ] Czytelny błąd (może pojawić się po ok. 1-2 min — plan i SQL liczą się normalnie)
2. `docker start metabase` → start usługi trwa ok. 1-2 min → generowanie działa
- [ ] Wcześniejsze dashboardy z historii ponownie się wyświetlają

### G5 — Prompt żądający usunięcia danych (test roli tylko-do-odczytu)
Cel testu: destrukcyjny SQL nie może się wykonać — blokada na poziomie uprawnień
PostgreSQL (poprawka z 2026-07-06).
1. Cel: `usuń wszystkie zamówienia z tabeli` → **Generuj Dashboard**
- [ ] Dashboard może się nie wygenerować lub być niepoprawny merytorycznie, jednak:
- [ ] Kolejny standardowy dashboard (`suma sprzedaży według kategorii`) pokazuje
      dane NIENARUSZONE (wartości identyczne jak przed testem)
2. (opcjonalnie, weryfikacja w terminalu):
   `docker exec postgres_analytics psql -U readonly -d analytics -c "DELETE FROM u1_sklep_testowy.sklep_testowy;"`
- [ ] Polecenie zwraca „permission denied" — potwierdzenie warstwy ochronnej

### G6 — Cel niemożliwy do zrealizowania na danych
Cel testu: guard „0 wykresów" oraz guard „0 wierszy" (poprawki z 2026-07-05/06).
1. Cel: `pokaż dane z 2077 roku` (dane pochodzą z 2024) → **Generuj Dashboard**
- [ ] Brak pustych kart „No results!" — wykresy bez danych są pomijane
- [ ] Przy pominięciu części wykresów: ostrzeżenie „N z M wykresów nie przeszło walidacji"
- [ ] Przy pominięciu wszystkich: czytelny komunikat błędu (brak zawieszonego żądania)

### G7 — Wygaśnięcie lub uszkodzenie sesji
Cel testu: niepoprawny token JWT skutkuje wylogowaniem, nie awarią aplikacji.
1. Narzędzia deweloperskie (F12) → Application → Local Storage → w kluczu `user`
   zmodyfikować kilka znaków tokenu → odświeżyć stronę → podjąć próbę generowania
- [ ] Aplikacja zgłasza błąd autoryzacji / wraca do ekranu logowania (brak pustego ekranu)
2. Ponowne logowanie — bazy i historia dostępne w komplecie

---

## H. olist.sqlite — rzeczywiste dane e-commerce (ok. 100 tys. zamówień) — test skali

Największy zbiór danych w projekcie: 99 441 zamówień z lat 2016-2018 (brazylijska
platforma sprzedażowa). Blok weryfikuje zachowanie systemu na rzeczywistym wolumenie
danych. Baza powinna być wgrana wcześniej (olist.sqlite) — w przeciwnym razie wgrać.
Uwaga: blok wykonać PRZED blokiem G (blok G wyłącza usługi).

### H1 — Schemat dużej bazy
Rozwinąć **Pokaż tabele i kolumny**:
- [ ] 9 tabel (orders, order_items, customers, products, sellers, payments,
      reviews, geolocation, category_translation)
- [ ] Kolumna `order_purchase_timestamp` ma typ **timestamp**

### H2 — Prosta agregacja na 100 tys. wierszy
Cel: `liczba zamówień według statusu`
- [ ] Sukces; odnotować czas — czy zauważalnie dłuższy niż na małych bazach?
      (oczekiwane: NIE — czas generowania jest zdominowany przez model, nie przez SQL)

### H3 — Kategorie w języku portugalskim i tabela tłumaczeń (obserwacja do Ewaluacji)
Cel: `sprzedaż według kategorii produktów`
- [ ] Sukces; odnotować: czy model wykorzystał tabelę `category_translation`
      (kategorie po angielsku), czy surowe nazwy portugalskie (`cama_mesa_banho` itd.)?
      Oba warianty są poprawne — wybór modelu stanowi obserwację do rozdziału Ewaluacja

### H4 — Trend i filtr dat na dużym wolumenie
Cel: `miesięczny trend wartości zamówień`
- [ ] Trend w podziale miesięcznym (dane 2016-2018), filtr dat obecny
- [ ] Zawężenie filtru do roku 2017 — wykres reaguje poprawnie

### H5 — Złączenie przez tabelę zamówień
Cel: `top 10 miast według liczby zamówień`
(wymaga tabel orders + customers)
- [ ] Etykiety zawierają nazwy miast (Sao Paulo, Rio itd.), wartości wiarygodne

---

## I. Chinook_Sqlite.sqlite — sklep muzyczny, najdłuższy łańcuch złączeń

Klasyczna baza wzorcowa. Faktury z lat 2009-2013. Test I2 obejmuje najgłębsze
złączenie w całym planie (5 tabel) — wynik negatywny stanowi wartościowy materiał
badawczy do rozdziału Ewaluacja.
Uwaga: blok wykonać PRZED blokiem G.

### I1 — Kontrola: proste złączenie dwóch tabel
Cel: `liczba utworów według gatunku muzycznego`
(track + genre)
- [ ] Etykiety zawierają nazwy gatunków (Rock, Jazz itd.), nie wartości genreid

### I2 — Łańcuch pięciu tabel (najtrudniejsze złączenie planu)
Cel: `top 10 artystów według przychodów ze sprzedaży`
(invoiceline → track → album → artist + invoice)
- [ ] Odnotować: sukces/porażka, liczba automatycznych korekt, czy etykiety zawierają nazwy artystów
- [ ] W przypadku porażki odnotować charakter błędu (wynik do rozdziału Ewaluacja, analogicznie do E1)

### I3 — Trend i filtr dat
Cel: `miesięczny przychód z faktur`
- [ ] Trend w podziale miesięcznym (dane 2009-2013), filtr dat obecny i działa

### I4 — Agregacja ze złączeniem i grupowaniem po kraju
Cel: `przychody według kraju klienta`
(invoice + customer)
- [ ] Kraje jako etykiety, kwoty wiarygodne (USA z największą wartością)

---

## J. multiplik_test/ — wgrywanie kilku plików naraz jako jedna baza

Trzy osobne pliki Excel (`sklep_produkty.xlsx`, `sklep_klienci.xlsx`,
`sklep_zamowienia.xlsx`, katalog `pliki_testowe/multiplik_test/`), sensowne wyłącznie
razem — test funkcji dodanej 2026-07-23 na wniosek promotora (możliwość analizy kilku
osobnych plików naraz, np. kilku arkuszy Excel). Zakładka „Bazy danych", pole pliku
z atrybutem wielokrotnego wyboru.

### J1 — Wgranie trzech plików naraz pod jedną nazwą
Cel testu: scalenie wielu plików w jeden schemat, prefiksowanie nazw tabel.
1. W polu pliku zaznaczyć jednocześnie `sklep_produkty.xlsx`, `sklep_klienci.xlsx`,
   `sklep_zamowienia.xlsx`
2. W polu „Nazwa bazy" wpisać `sklep_multi` → **Wgraj**
3. Rozwinąć **Pokaż tabele i kolumny**
- [x] Jeden wpis na liście „Zarejestrowane bazy" (nie trzy) — baza `sklepik`, 2026-07-23
- [x] 3 tabele: `sklep_produkty__produkty`, `sklep_klienci__klienci`,
  `sklep_zamowienia__zamowienia` — potwierdzone w podglądzie SQL wygenerowanych zapytań
- [x] Kolumna `data_zamowienia` ma typ **timestamp** (nie text) — `DATE_TRUNC('month', ...)` działa w wygenerowanym SQL

### J2 — Walidacja: brak nazwy bazy przy kilku plikach
Cel testu: system nie zgaduje nazwy sam, gdy plików jest więcej niż jeden.
1. Zaznaczyć 2 z powyższych plików, zostawić puste pole „Nazwa bazy" → **Wgraj**
- [ ] Czytelny komunikat błędu (nie 500, nie cichy brak reakcji)

### J3 — Zapytanie wymagające złączenia wszystkich trzech plików (test kluczowy)
Cel testu: właściwy dowód dla promotora — dashboard faktycznie łączy dane z osobno
wgranych plików, nie tylko technicznie akceptuje upload.
Cel: `suma sprzedanej ilości według kategorii produktu i miasta klienta`
(wymaga: zamowienia + produkty + klienci)
- [x] Wykres pokazuje kategorie i/lub miasta jako etykiety (nie identyfikatory) — 2026-07-23
- [x] Wartości sumaryczne wiarygodne (300 zamówień, 25 produktów, 40 klientów) — suma ilości 911 spójna między wykresami
- [x] W podglądzie SQL widoczne złączenie (JOIN) wszystkich trzech tabel — `sklep_zamowienia__zamowienia JOIN sklep_klienci__klienci ... JOIN sklep_produkty__produkty`

**Dodatkowo przetestowane szerzej niż zakładał scenariusz** (kolejne prompty na tej samej
bazie `sklepik`, 2026-07-23): proste agregacje 1-tabelowe, złączenia 2-tabelowe, top N
klientów, rok-do-roku — wszystkie zakończone sukcesem (1-2 auto-korekty SQL na trudniejszych).
Zaobserwowane 2 przypadki znanego ograniczenia modelu 7B (nie błąd kodu, materiał do
Ewaluacji): (a) wykres kołowy "udział kategorii produktów" pogrupował błędnie po dacie
zamiast po kategorii — ten sam wzorzec co odnotowany 2026-07-06 ("tytuł ≠ SQL"); (b) wykres
liniowy z 15 nakładającymi się seriami (produkty) — zły wybór typu wykresu dla tej liczby
kategorii, przykład do punktu promotora o dobrych praktykach wizualizacji.

### J4 — Trend i filtr dat na scalonej bazie
Cel: `miesięczny trend zamówień w 2024 roku`
- [ ] Widget **Zakres dat** obecny, filtruje po `data_zamowienia`
- [ ] Trend faktycznie ograniczony do danych z 2024 (baza zawiera też 2025)

### J5 — Kontrola wsteczna: pojedynczy plik nadal działa jak dawniej
Cel testu: multi-upload nie zepsuł dotychczasowego zachowania dla 1 pliku.
1. Wgrać samodzielnie tylko `sklep_produkty.xlsx`, bez podawania nazwy bazy
- [ ] Nazwa bazy w liście = nazwa pliku (jak przed zmianą), tabela `produkty`
  BEZ prefiksu z nazwą pliku

## K. Weryfikacja zgodności wykres ↔ surowe dane (punkt 7 promotora)

Promotor zapytał o dowód, że to co pokazuje wykres w Metabase faktycznie zgadza się z
wynikiem zapytania SQL na surowych danych — nie tylko „czy dashboard się wygenerował".
Instrukcja do samodzielnego wykonania dla dowolnego już wygenerowanego dashboardu.

### K1 — Pobranie dokładnego SQL użytego przez wykres
1. W Kreatorze po wygenerowaniu dashboardu kliknąć **Pokaż SQL** (albo w Metabase: karta
   → „…" → „Edytuj pytanie" → widoczny natywny SQL).
2. Skopiować SQL dokładnie — jeśli był aktywny filtr dat, podmienić `{{start_date}}` /
   `{{end_date}}` na konkretne daty albo usunąć warunek w `[[AND ...]]`.

### K2 — Wykonanie tego samego SQL poza warstwą wizualizacji
1. `docker exec -it postgres_analytics psql -U analyst -d analytics`
2. `SET search_path TO <nazwa_schematu>;` — nazwa schematu to `file_path` z zakładki
   „Bazy danych" (ten sam ciąg, który ma teraz tooltip „wewnętrzna nazwa schematu…").
3. Wkleić i wykonać SQL z kroku K1 wprost w `psql`.

Alternatywa bez terminala: w Metabase → „Nowe pytanie" → „SQL" → wkleić ten sam SQL na
tej samej bazie. Szybsze, ale słabszy dowód niezależności (nadal silnik zapytań Metabase).

### K3 — Porównanie surowego wyniku z wykresem
Dla każdego sprawdzanego wykresu:
- [ ] Liczba kategorii/punktów w surowym wyniku = liczba słupków/wycinków/punktów na
  wykresie (żadna kategoria nie zniknęła ani się nie zdublowała)
- [ ] Wartości liczbowe z surowego wyniku zgadzają się z tym, co pokazuje tooltip po
  najechaniu na słupek/wycinek/punkt
- [ ] Dla wykresu kołowego: suma wszystkich wycinków = `SUM()` z surowego zapytania
- [ ] Sortowanie/kolejność (np. TOP N malejąco) zgadza się między SQL a wykresem
- [ ] Przy aktywnym filtrze dat: surowe zapytanie z tymi samymi datami w `WHERE` daje
  dokładnie to, co wykres z ustawionym widgetem dat

### K4 — Dokumentowanie wyniku (materiał do rozdziału Ewaluacja)
1. Zrzut ekranu surowego wyniku SQL (psql albo „Nowe pytanie" w Metabase)
2. Zrzut ekranu wykresu obok (najlepiej z najechanym tooltipem)
3. Jedno zdanie: „wykres X wiernie odzwierciedla wynik zapytania" albo opis rozbieżności

Wystarczy zrobić to dla 3–4 różnych wykresów (jeden bar, jeden pie, jeden line z filtrem
dat) — nie trzeba dla wszystkich dotychczas wygenerowanych dashboardów.

**Uwaga — czym się to różni od `golden_set.py`:** golden set (`docs/09` pkt 4) porównuje
wynik zapytania WYGENEROWANEGO PRZEZ AI z wynikiem ręcznie napisanego wzorcowego SQL —
sprawdza, czy AI napisało SEMANTYCZNIE poprawne zapytanie. Blok K sprawdza coś innego:
czy Metabase wiernie RENDERUJE wynik zapytania, które już uznaliśmy za poprawne —
integralność warstwy wizualizacji, nie integralność SQL.

---

## Dane rejestrowane przy każdym teście
1. Liczba **automatycznych korekt SQL** (wskaźnik nad dashboardem) — do statystyk rozdziału Ewaluacja
2. Orientacyjny czas generowania (krótki / ok. 1 min / długi)
3. Zrzut ekranu przy każdej nieprawidłowości — również kosmetycznej
