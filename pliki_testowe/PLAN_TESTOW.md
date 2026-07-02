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
- [ ] Prompt przepisany po polsku, zawiera podział/grupowanie po miastach
- [ ] NIE zawiera filtra typu "tylko w różnych miastach"
- [ ] NIE wymyśla kolumn klienta (imię/nazwisko — ich nie ma w tej bazie)
4. Kliknij **Generuj Dashboard**
- [ ] Wykresy faktycznie grupują po miastach

### A2 — Filtr dat + guard językowy
🎯 Widget "Zakres dat" + polskie tytuły
1. Wyczyść opis bazy (zostaw pusty!), cel: `trend sprzedaży miesięcznej` → **Generuj Dashboard**
- [ ] Na dashboardzie jest widget **Zakres dat**
- [ ] Tytuły wykresów PO POLSKU (nie węgierski/angielski)
- [ ] Napisy na osiach po polsku (aliasy kolumn)
2. Ustaw w widgecie zakres `2024-01-01 – 2024-03-31`
- [ ] Wykres trendu zawęża się do 3 miesięcy
3. Ustaw zakres z 2026 roku
- [ ] Wykres z datą robi się pusty (dane są z 2024 — to poprawne zachowanie)

### A3 — Wybór typów wykresów
🎯 Czy wybrane typy są respektowane (naprawa z 2026-07-01)
1. Kliknij w kolejności: **Licznik**, **Kołowy**, **Liniowy**
2. Cel: `podsumowanie sprzedaży sklepu` → **Generuj Dashboard**
- [ ] Dokładnie 3 wykresy
- [ ] Typy zgadzają się z kolejnością: licznik (jedna liczba), kołowy, liniowy

---

## B. firma_uslugi.xlsx — Excel wielo-arkuszowy, polskie kolumny

### B1 — Upload i schemat
🎯 Multi-sheet + detekcja polskich dat (`data_podpisania` itd. → TIMESTAMP)
1. Wgraj `firma_uslugi.xlsx`
2. Rozwiń **Pokaż tabele i kolumny**
- [ ] 3 tabele: `klienci`, `pracownicy`, `umowy`
- [ ] Kolumny `data_rejestracji`, `data_zatrudnienia`, `data_podpisania` mają typ **timestamp** (NIE text)

### B2 — Generuj opis AI
🎯 Opis po polsku, bez obcych znaków, poprawne relacje
- [ ] Opis po polsku, zero chińskich/rosyjskich/węgierskich wtrąceń
- [ ] Wspomina powiązania `klient_id` / `pracownik_id` (tu NAPRAWDĘ istnieją)

### B3 — JOIN dwóch tabel
Cel: `wartość umów według miast klientów`
- [ ] Wykres pokazuje miasta (Warszawa, Kraków...) — wymaga JOIN umowy+klienci
- [ ] Wartości sumaryczne wyglądają sensownie

### B4 — Filtr dat na polskich kolumnach ⭐ NAJWAŻNIEJSZY TEST DNIA
🎯 Dzisiejszy fix: detekcja daty po polskiej nazwie kolumny
Cel: `trend wartości podpisanych umów miesięcznie`
- [ ] Widget **Zakres dat** jest na dashboardzie
- [ ] Zawężenie zakresu realnie filtruje wykres (dane: 2024-2025)

### B5 — Przycisk "Pomiń" w doprecyzowaniu
🎯 Furtka ominięcia pytania
1. Cel: `pokaż umowy` → **✦ Ulepsz prompt AI** → powinno paść pytanie
2. Kliknij **Pomiń** (nie odpowiadaj)
- [ ] Enhance wykonuje się mimo braku odpowiedzi, prompt ulepszony po polsku

### B6 — Kombinacja: opis + ulepszenie + typy
1. **Generuj opis AI** → poczekaj na opis
2. Cel: `zmiana łącznej wartości umów rok do roku` + typy: **Kaskadowy**, **Tabela**
3. **✦ Ulepsz prompt AI** (odpowiedz na pytanie, jeśli będzie) → **Generuj Dashboard**
- [ ] 2 wykresy: kaskadowy (waterfall, może mieć ujemne słupki) + tabela
- [ ] Tytuły po polsku

---

## C. superstore.xls — stary format .xls, angielskie kolumny, ~10k wierszy

### C1 — Upload .xls
🎯 Dzisiejszy fix: biblioteka xlrd w backendzie
1. Wgraj `superstore.xls`
- [ ] Upload przechodzi bez błędu (przed dzisiejszym fixem: błąd 500)
- [ ] 3 tabele: `orders`, `people`, `returns`

### C2 — Detekcja dat po angielsku (stara ścieżka)
Rozwiń **Pokaż tabele i kolumny**:
- [ ] `order_date` i `ship_date` mają typ timestamp

### C3 — Dwie miary na jednym wykresie
Cel: `sprzedaż i zysk według regionów`
- [ ] Wykres z dwiema wartościami (sales, profit) per region

### C4 — Trend + filtr na większych danych
Cel: `miesięczny trend sprzedaży` (~10 tys. wierszy)
- [ ] Generacja kończy się sukcesem (może potrwać dłużej)
- [ ] Filtr dat obecny i działa

---

## D. northwind.db — SQLite, wiele tabel, nazwy CamelCase

### D1 — Upload .db
🎯 Normalizacja nazw (CamelCase → lowercase, "Order Details" → order_details)
1. Wgraj `northwind.db`
- [ ] Tabele widoczne małymi literami: `customers`, `orders`, `order_details`, `products`...
- [ ] UWAGA: może pojawić się śmieciowa tabelka `sqlite_sequence` — znane, kosmetyczne, zignoruj

### D2 — Opis AI z prawdziwymi relacjami
**Generuj opis AI**:
- [ ] Opisane relacje FK (orders↔customers itd.) — tu istnieją naprawdę
- [ ] Po polsku, bez obcych znaków

### D3 — JOIN trzech tabel
Cel: `najlepsi klienci według łącznej wartości zamówień`
(wymaga orders + order_details + customers)
- [ ] Etykiety = NAZWY firm (nie ID!)
- [ ] Sensowne kwoty; zanotuj liczbę auto-korekt SQL

### D4 — Trend + filtr dat
Cel: `trend liczby zamówień miesięcznie`
- [ ] Filtr dat obecny, zawężanie działa

### D5 — Pełna kombinacja wszystkich funkcji
1. **Generuj opis AI** → 2. Cel: `raport sprzedaży` → 3. **✦ Ulepsz prompt AI** →
   odpowiedz na pytanie (jeśli padnie) → 4. Typy: **Słupkowy**, **Kołowy**, **Licznik** →
   5. **Generuj Dashboard** → 6. **Pokaż SQL** → 7. **Otwórz w Metabase**
- [ ] Każdy krok przechodzi; typy wykresów zgodne z wyborem
- [ ] "Pokaż SQL" pokazuje SQL każdego wykresu
- [ ] Link do Metabase działa

---

## E. sakila.db — stres-test JOIN-ów (zbieramy materiał do Ewaluacji!)

> Tu spodziewamy się potknięć modelu 7B — NOTUJ liczbę auto-korekt i co wyszło źle.
> Porażki są tu równie cenne jak sukcesy (rozdział "Ewaluacja").

### E1 — JOIN czterech tabel (najtrudniejszy)
Cel: `najpopularniejsze kategorie filmów według liczby wypożyczeń`
(category + film_category + inventory + rental)
- [ ] Zanotuj: sukces/porażka, liczba auto-korekt, czy kategorie mają nazwy

### E2 — Prostszy przypadek na tej samej bazie
Cel: `miesięczny przychód z płatności`
- [ ] Trend po miesiącach (dane z 2005-2006!), filtr dat obecny

### E3 — JOIN dwóch tabel
Cel: `top 10 aktorów według liczby filmów`
- [ ] Imiona i nazwiska aktorów jako etykiety (nie actor_id)

---

## F. Testy przekrojowe i negatywne

### F1 — Historia zapytań
- [ ] Wszystkie dzisiejsze generacje widoczne w historii
- [ ] Kliknięcie wpisu z historii otwiera dashboard ponownie

### F2 — Izolacja użytkowników
1. Wyloguj się, zarejestruj drugie konto testowe
- [ ] Nowe konto NIE widzi baz i historii pierwszego konta
2. Wróć na swoje konto — wszystko na miejscu

### F3 — Zły plik
Spróbuj wgrać plik `.txt` albo `.pdf`
- [ ] Czytelny komunikat błędu (nie crash / biały ekran)

### F4 — Jasny cel = brak pytania
Cel: `TOP 10 produktów według sumy sprzedaży z podziałem miesięcznym w 2024 roku` → **✦ Ulepsz prompt AI**
- [ ] NIE zadaje pytania (cel jest kompletny) — od razu ulepsza

### F5 — "top" bez liczby
Cel: `top produkty` → **✦ Ulepsz prompt AI** (+ ew. odpowiedź na pytanie)
- [ ] Ulepszony prompt NIE zawiera wymyślonej liczby ("TOP 10"/"TOP 20")

---

## Co notować przy każdym teście
1. Liczba **auto-korekt SQL** (pasek nad dashboardem) — do statystyk Ewaluacji
2. Czas generacji "na oko" (szybko / ~1 min / długo)
3. Zrzut ekranu przy WSZYSTKIM co dziwne — nawet kosmetycznym
