# Plan testów manualnych — AI Data Analyst

> Testuj po kolei. Przy każdym teście: wklej cel DOKŁADNIE jak podano, odhacz checkboxy.
> Jeśli coś nie gra — zrzut ekranu + zapisz który to test (np. "B4 padł").
> Legenda: 🎯 = główny cel testu (co tak naprawdę sprawdzamy).

---

## A. sklep_testowy.csv — szybka regresja (baza już wgrana)

### A1 — Ulepsz prompt: pełny przepływ z pytaniem
🎯 Nowy połączony przepływ clarify→enhance
1. Cel: `pokaż produkty` → kliknij **✦ Ulepsz prompt AI**
2. Powinno pojawić się pytanie doprecyzowujące (żółty box)
3. Odpowiedz: `na podstawie miast` → **✦ Ulepsz z odpowiedzią**
- [x] Prompt przepisany po polsku, zawiera podział/grupowanie po miastach
- [x] NIE zawiera filtra typu "tylko w różnych miastach"
- [x] NIE wymyśla kolumn klienta (imię/nazwisko — ich nie ma w tej bazie)
4. Kliknij **Generuj Dashboard**
- [x] Wykresy faktycznie grupują po miastach

### A2 — Filtr dat + guard językowy
🎯 Widget "Zakres dat" + polskie tytuły
1. Wyczyść opis bazy (zostaw pusty!), cel: `trend sprzedaży miesięcznej` → **Generuj Dashboard**
- [x] Na dashboardzie jest widget **Zakres dat**
- [x] Tytuły wykresów PO POLSKU (nie węgierski/angielski)
- [x] Napisy na osiach po polsku (aliasy kolumn)
2. Ustaw w widgecie zakres `2024-01-01 – 2024-03-31`
- [x] Wykres trendu zawęża się do 3 miesięcy
3. Ustaw zakres z 2026 roku
- [x] Wykres z datą robi się pusty (dane są z 2024 — to poprawne zachowanie)

### A3 — Wybór typów wykresów
🎯 Czy wybrane typy są respektowane (naprawa z 2026-07-01)
1. Kliknij w kolejności: **Licznik**, **Kołowy**, **Liniowy**
2. Cel: `podsumowanie sprzedaży sklepu` → **Generuj Dashboard**
- [x] Dokładnie 3 wykresy
- [x] Typy zgadzają się z kolejnością: licznik (jedna liczba), kołowy, liniowy

---

## B. firma_uslugi.xlsx — Excel wielo-arkuszowy, polskie kolumny

### B1 — Upload i schemat
🎯 Multi-sheet + detekcja polskich dat (`data_podpisania` itd. → TIMESTAMP)
1. Wgraj `firma_uslugi.xlsx`
2. Rozwiń **Pokaż tabele i kolumny**
- [x] 3 tabele: `klienci`, `pracownicy`, `umowy`
- [x] Kolumny `data_rejestracji`, `data_zatrudnienia`, `data_podpisania` mają typ **timestamp** (NIE text)

### B2 — Generuj opis AI
🎯 Opis po polsku, bez obcych znaków, poprawne relacje
- [x] Opis po polsku, zero chińskich/rosyjskich/węgierskich wtrąceń
- [x] Wspomina powiązania `klient_id` / `pracownik_id` (tu NAPRAWDĘ istnieją)

### B3 — JOIN dwóch tabel
Cel: `wartość umów według miast klientów`
- [x] Wykres pokazuje miasta (Warszawa, Kraków...) — wymaga JOIN umowy+klienci
- [x] Wartości sumaryczne wyglądają sensownie

### B4 — Filtr dat na polskich kolumnach ⭐ NAJWAŻNIEJSZY TEST DNIA
🎯 Dzisiejszy fix: detekcja daty po polskiej nazwie kolumny
Cel: `trend wartości podpisanych umów miesięcznie`

- [x] Widget **Zakres dat** jest na dashboardzie
- [ ] Zawężenie zakresu realnie filtruje wykres (dane: 2024-2025)

### B5 — Przycisk "Pomiń" w doprecyzowaniu
🎯 Furtka ominięcia pytania
1. Cel: `pokaż umowy` → **✦ Ulepsz prompt AI** → powinno paść pytanie
2. Kliknij **Pomiń** (nie odpowiadaj)
- [x] Enhance wykonuje się mimo braku odpowiedzi, prompt ulepszony po polsku

### B6 — Kombinacja: opis + ulepszenie + typy
1. **Generuj opis AI** → poczekaj na opis
2. Cel: `zmiana łącznej wartości umów rok do roku` + typy: **Kaskadowy**, **Tabela**
3. **✦ Ulepsz prompt AI** (odpowiedz na pytanie, jeśli będzie) → **Generuj Dashboard**
- [ ] 2 wykresy: kaskadowy (waterfall, może mieć ujemne słupki) + tabela
- [x] Tytuły po polsku

---

## C. superstore.xls — stary format .xls, angielskie kolumny, ~10k wierszy

### C1 — Upload .xls
🎯 Dzisiejszy fix: biblioteka xlrd w backendzie
1. Wgraj `superstore.xls`
- [x] Upload przechodzi bez błędu (przed dzisiejszym fixem: błąd 500)
- [x] 3 tabele: `orders`, `people`, `returns`

### C2 — Detekcja dat po angielsku (stara ścieżka)
Rozwiń **Pokaż tabele i kolumny**:
- [x] `order_date` i `ship_date` mają typ timestamp

### C3 — Dwie miary na jednym wykresie
Cel: `sprzedaż i zysk według regionów`
- [x] Wykres z dwiema wartościami (sales, profit) per region

### C4 — Trend + filtr na większych danych
Cel: `miesięczny trend sprzedaży` (~10 tys. wierszy)
- [x] Generacja kończy się sukcesem (może potrwać dłużej)
- [x] Filtr dat obecny i działa

---

## D. northwind.db — SQLite, wiele tabel, nazwy CamelCase

### D1 — Upload .db
🎯 Normalizacja nazw (CamelCase → lowercase, "Order Details" → order_details)
1. Wgraj `northwind.db`
- [x] Tabele widoczne małymi literami: `customers`, `orders`, `order_details`, `products`...
- [x] UWAGA: może pojawić się śmieciowa tabelka `sqlite_sequence` — znane, kosmetyczne, zignoruj

### D2 — Opis AI z prawdziwymi relacjami
**Generuj opis AI**:

- [x] Opisane relacje FK (orders↔customers itd.) — tu istnieją naprawdę
- [x] Po polsku, bez obcych znaków

### D3 — JOIN trzech tabel
Cel: `najlepsi klienci według łącznej wartości zamówień`
(wymaga orders + order_details + customers)

- [x] Etykiety = NAZWY firm (nie ID!)
- [x] Sensowne kwoty; zanotuj liczbę auto-korekt SQL

### D4 — Trend + filtr dat
Cel: `trend liczby zamówień miesięcznie`
- [x] Filtr dat obecny, zawężanie działa

### D5 — Pełna kombinacja wszystkich funkcji
1. **Generuj opis AI** → 2. Cel: `raport sprzedaży` → 3. **✦ Ulepsz prompt AI** →
   odpowiedz na pytanie (jeśli padnie) → 4. Typy: **Słupkowy**, **Kołowy**, **Licznik** →
   5. **Generuj Dashboard** → 6. **Pokaż SQL** → 7. **Otwórz w Metabase**
- [ ] Każdy krok przechodzi; typy wykresów zgodne z wyborem
- [x] "Pokaż SQL" pokazuje SQL każdego wykresu
- [x] Link do Metabase działa

---

## E. sakila.db — stres-test JOIN-ów (zbieramy materiał do Ewaluacji!)

> Tu spodziewamy się potknięć modelu 7B — NOTUJ liczbę auto-korekt i co wyszło źle.
> Porażki są tu równie cenne jak sukcesy (rozdział "Ewaluacja").

### E1 — JOIN czterech tabel (najtrudniejszy)
Cel: `najpopularniejsze kategorie filmów według liczby wypożyczeń`
(category + film_category + inventory + rental)

- [x] Zanotuj: sukces/porażka, liczba auto-korekt, czy kategorie mają nazwy

### E2 — Prostszy przypadek na tej samej bazie
Cel: `miesięczny przychód z płatności`
- [x] Trend po miesiącach (dane z 2005-2006!), filtr dat obecny

### E3 — JOIN dwóch tabel
Cel: `top 10 aktorów według liczby filmów`
- [x] Imiona i nazwiska aktorów jako etykiety (nie actor_id)

---

## F. Testy przekrojowe i negatywne

### F1 — Historia zapytań
- [x] Wszystkie dzisiejsze generacje widoczne w historii
- [x] Kliknięcie wpisu z historii otwiera dashboard ponownie

### F2 — Izolacja użytkowników
1. Wyloguj się, zarejestruj drugie konto testowe
- [x] Nowe konto NIE widzi baz i historii pierwszego konta
2. Wróć na swoje konto — wszystko na miejscu

### F3 — Zły plik
Spróbuj wgrać plik `.txt` albo `.pdf`
- [x] Czytelny komunikat błędu (nie crash / biały ekran)

### F4 — Jasny cel = brak pytania
Cel: `TOP 10 produktów według sumy sprzedaży z podziałem miesięcznym w 2024 roku` → **✦ Ulepsz prompt AI**
- [x] NIE zadaje pytania (cel jest kompletny) — od razu ulepsza

### F5 — "top" bez liczby
Cel: `top produkty` → **✦ Ulepsz prompt AI** (+ ew. odpowiedź na pytanie)
- [x] Ulepszony prompt NIE zawiera wymyślonej liczby ("TOP 10"/"TOP 20")

---

## G. Reagowanie na błędy i awarie (wymaga terminala!)

> Testujemy, czy system PADA Z KLASĄ: czytelny komunikat zamiast wiszącego spinnera,
> białego ekranu albo — najgorzej — uszkodzonych danych. Po każdym teście przywróć
> usługę i sprawdź, że system wraca do życia BEZ restartu całości.
> Komendy odpalaj w folderze projektu.

### G1 — Ollama pada w trakcie pracy ⭐ najczęstsza realna awaria
🎯 Generowanie kończy się czytelnym błędem, nie wisi w nieskończoność
1. W terminalu: `docker stop ollama`
2. Cel: `suma sprzedaży według kategorii` (sklep_testowy) → **Generuj Dashboard**
- [ ] Pojawia się czerwony box "Błąd generowania" z komunikatem (nie wieczny spinner)
- [ ] Aplikacja dalej reaguje (można klikać, przełączać bazy)
3. `docker start ollama` → odczekaj ~10 s → **Generuj Dashboard** ponownie
- [ ] Działa normalnie, BEZ restartu backendu/frontendu

### G2 — Ollama wyłączona przy "Generuj opis AI"
🎯 Ostrzeżenie w polu opisu (naprawa z 2026-07-05)
1. `docker stop ollama` → kliknij **Generuj opis AI**
- [ ] W polu opisu pojawia się "⚠ Nie udało się wygenerować opisu..." (nie puste pole, nie crash)
2. `docker start ollama`

### G3 — n8n (orchestrator) wyłączony
🎯 Jedna ścieżka generowania = n8n to pojedynczy punkt awarii; ma zawieść GŁOŚNO
1. `docker stop n8n_local` → **Generuj Dashboard**
- [ ] Czytelny błąd (wspomina n8n/orchestrator), pojawia się szybko (sekundy, nie minuty)
2. `docker start n8n_local` → odczekaj ~15 s → generacja znowu działa
- [ ] Działa bez żadnych dodatkowych kroków

### G4 — Metabase wyłączony
🎯 Awaria na KOŃCU pipeline'u (plan i SQL zdążą się policzyć — tym ciekawszy przypadek)
1. `docker stop metabase` → **Generuj Dashboard**
- [ ] Czytelny błąd (może przyjść po ~1-2 min — plan+SQL liczą się normalnie, pada dopiero budowa dashboardu)
2. `docker start metabase` → Metabase wstaje ~1-2 min → generacja działa
- [ ] Stare dashboardy z historii też znów się wyświetlają

### G5 — Prompt żądający zniszczenia danych ⭐ test roli read-only
🎯 Destrukcyjny SQL fizycznie nie może się wykonać (uprawnienia Postgresa, naprawa 2026-07-06)
1. Cel: `usuń wszystkie zamówienia z tabeli` → **Generuj Dashboard**
- [ ] Dashboard może się nie wygenerować albo wyjść dziwny — ALE:
- [ ] Wygeneruj potem normalny dashboard (`suma sprzedaży według kategorii`) —
      dane są NIETKNIĘTE (te same kwoty co wcześniej)
2. (opcjonalnie, dowód w terminalu):
   `docker exec postgres_analytics psql -U readonly -d analytics -c "DELETE FROM u1_sklep_testowy.sklep_testowy;"`
- [ ] Zwraca "permission denied" — to jest ta warstwa obrony

### G6 — Cel niemożliwy do zrealizowania
🎯 Guard "0 wykresów" + guard "0 wierszy" (naprawy z 2026-07-05/06)
1. Cel: `pokaż dane z 2077 roku` (dane są z 2024) → **Generuj Dashboard**
- [ ] ŻADNEJ pustej karty "No results!" — wykresy bez danych są pominięte
- [ ] Jeśli pominięto część: żółte ostrzeżenie "N z M wykresów nie przeszło walidacji"
- [ ] Jeśli pominięto wszystkie: czytelny czerwony błąd (nie wiszący webhook)

### G7 — Wygaśnięcie sesji
🎯 Stary/zepsuty token JWT = wylogowanie, nie crash
1. DevTools (F12) → Application → Local Storage → w kluczu `user` zepsuj token
   (zmień kilka znaków w środku) → odśwież stronę → spróbuj wygenerować dashboard
- [ ] Aplikacja pokazuje błąd autoryzacji / wraca do logowania (nie biały ekran)
2. Zaloguj się ponownie — wszystko (bazy, historia) na miejscu

---

## H. olist.sqlite — prawdziwe dane e-commerce (~100 tys. zamówień) — TEST SKALI

> Największa baza w projekcie: 99 441 zamówień z lat 2016-2018 (brazylijski
> marketplace). Tu sprawdzamy zachowanie na PRAWDZIWYM wolumenie danych.
> Baza powinna już być wgrana (olist.sqlite na Twoim koncie) — jeśli nie, wgraj.
> ⚠ Testuj PRZED blokiem G (G wyłącza usługi).

### H1 — Schemat dużej bazy
Rozwiń **Pokaż tabele i kolumny**:
- [ ] 9 tabel (orders, order_items, customers, products, sellers, payments,
      reviews, geolocation, category_translation)
- [ ] `order_purchase_timestamp` ma typ **timestamp**

### H2 — Prosta agregacja na 100k wierszy
Cel: `liczba zamówień według statusu`
- [ ] Sukces; zanotuj czas — czy zauważalnie wolniej niż na małych bazach?
      (spodziewane: NIE — czas i tak dominuje model, nie SQL)

### H3 — Kategorie po portugalsku + tabela tłumaczeń 🎯 ciekawostka do Ewaluacji
Cel: `sprzedaż według kategorii produktów`
- [ ] Sukces; zanotuj: czy model użył tabeli `category_translation` (kategorie
      po angielsku), czy surowych nazw portugalskich (`cama_mesa_banho`...)?
      Obie wersje są poprawne — ale która, to materiał o "sprycie" modelu

### H4 — Trend + filtr dat na dużym wolumenie
Cel: `miesięczny trend wartości zamówień`
- [ ] Trend po miesiącach (dane 2016-2018), filtr dat obecny
- [ ] Zawęź filtr do roku 2017 — wykres reaguje poprawnie

### H5 — JOIN przez zamówienia
Cel: `top 10 miast według liczby zamówień`
(wymaga orders + customers)
- [ ] Etykiety = nazwy miast (Sao Paulo, Rio...), sensowne liczby

---

## I. Chinook_Sqlite.sqlite — sklep muzyczny, NAJDŁUŻSZY łańcuch JOIN-ów

> Klasyczna baza-benchmark. Faktury 2009-2013. Test I2 to najgłębszy JOIN
> w całym planie (5 tabel) — porażka jest tu cennym wynikiem, nie wstydem.
> ⚠ Testuj PRZED blokiem G.

### I1 — Kontrola: prosty JOIN dwóch tabel
Cel: `liczba utworów według gatunku muzycznego`
(track + genre)
- [ ] Etykiety = nazwy gatunków (Rock, Jazz...), nie genreid

### I2 — Łańcuch 5 tabel ⭐ najtrudniejszy JOIN całego planu
Cel: `top 10 artystów według przychodów ze sprzedaży`
(invoiceline → track → album → artist + invoice)
- [ ] Zanotuj: sukces/porażka, liczba auto-korekt, czy etykiety to NAZWY artystów
- [ ] Porażka = zanotuj CO wyszło (to jest wynik do Ewaluacji, jak E1)

### I3 — Trend + filtr dat
Cel: `miesięczny przychód z faktur`
- [ ] Trend po miesiącach (dane 2009-2013!), filtr dat obecny i działa

### I4 — Agregacja z JOIN + grupowanie po kraju
Cel: `przychody według kraju klienta`
(invoice + customer)
- [ ] Kraje jako etykiety, kwoty sensowne (USA największe)

---

## Co notować przy każdym teście
1. Liczba **auto-korekt SQL** (pasek nad dashboardem) — do statystyk Ewaluacji
2. Czas generacji "na oko" (szybko / ~1 min / długo)
3. Zrzut ekranu przy WSZYSTKIM co dziwne — nawet kosmetycznym
