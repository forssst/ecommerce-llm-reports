# 03 — Pipeline uploadu: od pliku do schematu Postgresa (deep dive)

> Endpoint: `POST /upload` (multipart: `user_id` + `file`). Kod: `main.py`,
> okolice `MAX_UPLOAD_BYTES`. Obsługiwane formaty: `.db/.sqlite/.sqlite3`,
> `.csv`, `.xlsx`, `.xls`.

## 0. Big picture

```
plik → [limit 150MB, strumieniowo] → /tmp/_upload_<uuid><ext>
     → parsowanie do {nazwa_tabeli: DataFrame}
     → DROP+CREATE SCHEMA u{uid}_{nazwa} → GRANT USAGE dla readonly
     → to_sql per tabela → detekcja i rzutowanie kolumn dat
     → odczyt schematu → UPSERT wpisu w `databases`
```

## 1. Przyjęcie pliku — bezpieczeństwo zanim cokolwiek się stanie

```python
user_id = token_user_id          # tożsamość TYLKO z JWT
orig_name = os.path.basename(file.filename or "upload")   # utnij ścieżki (../../etc/x)
tmp_path = f"/tmp/_upload_{uuid.uuid4().hex}{ext}"        # LOSOWA nazwa na dysku
```
Czytanie STRUMIENIOWE po 1 MB z licznikiem — przekroczenie
`MAX_UPLOAD_BYTES` (150 MB; podniesione z 20→50→150 pod northwind i olist)
przerywa zapis, kasuje plik częściowy i zwraca **413**. Dzięki strumieniowaniu
nie ładujemy 150 MB do RAM ani nie pozwalamy zapchać dysku plikiem 10 GB.

Nazwa oryginalna służy WYŁĄCZNIE do wyświetlania i wyliczenia nazwy schematu;
na dysku plik nigdy nie nosi nazwy od użytkownika (path traversal wyeliminowany
klasą, nie sanityzacją).

## 2. Parsowanie per format → słownik DataFrame'ów

| Format | Metoda | Nazwy tabel |
|---|---|---|
| `.db/.sqlite/.sqlite3` | `sqlite3.connect` + `SELECT name FROM sqlite_master WHERE type='table'` → `pd.read_sql` per tabela | oryginalne nazwy tabel SQLite |
| `.csv` | `pd.read_csv(..., encoding="utf-8-sig")` (BOM z Excela!) | nazwa pliku (sanityzowana) |
| `.xlsx/.xls` | `pd.ExcelFile` → pętla po arkuszach | nazwa arkusza → lowercase, `\W`→`_` |

Błąd parsowania → **400** „Nie udało się odczytać pliku: ..." (nie 500 — to
też była naprawa: uszkodzony plik nie może wyglądać jak awaria serwera).
`finally: os.remove(tmp_path)` — plik tymczasowy znika zawsze.
Pusty wynik (`not dfs`) → 400 „Plik nie zawiera żadnych danych."

`.xls` wymaga biblioteki `xlrd` — jej brak w kontenerze dawał kiedyś 500
na każdy `.xls` (naprawione dodaniem do `requirements.txt`; ważna lekcja:
deklarowany format ≠ działający format, dopóki nie ma testu).

## 3. Utworzenie schematu i import

```python
schema_name = _sanitize_schema(user_id, orig_name)   # u{id}_{lowercase, [^a-z0-9]->_, max 40}
DROP SCHEMA IF EXISTS "{schema}" CASCADE
CREATE SCHEMA "{schema}"
GRANT USAGE ON SCHEMA "{schema}" TO readonly         # rola RO musi widzieć nowy schemat
```
Potem per tabela: sanityzacja nazwy tabeli i KOLUMN
(`re.sub(r"\W+","_",c).strip("_").lower()`) i `df.to_sql(...)`.
Konsekwencja lowercase'owania: model MUSI pisać `orderdate`, nie `"OrderDate"`
— stąd zarówno reguła w prompcie SQL, jak i normalizacja w `_clean_sql`.

## 4. Detekcja kolumn dat (dwutorowa) — warunek działania filtrów

Kolumna tekstowa jest KANDYDATEM na TIMESTAMP, gdy:
- **nazwa** zawiera hint PL/EN: `date, time, created, updated, timestamp, data, czas`, LUB
- **wartości**: próbka 5 niepustych pasuje do `^\s*\d{4}-\d{2}-\d{2}` (ISO).

Dla kandydata: `ALTER TABLE ... ALTER COLUMN ... TYPE TIMESTAMP USING col::timestamp`
w try/except z **rollbackiem** — jak choć jedna wartość nie jest datą, kolumna
bezpiecznie zostaje tekstem.

Historia: pierwotnie tylko hinty EN → polska `data_zamowienia` zostawała
tekstem → Metabase nie widział pola daty → **filtr dat w ogóle nie powstawał**
(bug B4 z 2026-07-02, jedna z ważniejszych napraw projektu).

## 5. Rejestracja metadanych — upsert

```python
rec = db.query(Database).filter_by(user_id=user_id, file_path=schema_name).first()
if rec:   # ponowny upload TEGO SAMEGO pliku → aktualizacja wpisu
    rec.name, rec.schema_json = orig_name, compact_schema
    → {"message": "Baza zaktualizowana (nadpisano poprzednią wersję)."}
else:     # nowy plik → nowy wpis
```
Dlaczego upsert (naprawa 2026-07-06): wcześniej każdy upload dodawał NOWY
wiersz, a wszystkie duble wskazywały ten sam schemat. `DELETE` jednego dubla
robił `DROP SCHEMA` → pozostałe wpisy zostawały OSIEROCONE (lista pokazuje
bazę, danych nie ma) → kaskada mylących objawów (opis AI „nie dostał schematu").

## 6. Znane ograniczenia pipeline'u (świadome)

- Typy wykrywane tylko dla dat; liczby/teksty zostawia pandas (zwykle OK).
- Brak walidacji, że `.db` to naprawdę SQLite (magic bytes) — złośliwy plik
  po prostu nie sparsuje się (400), więc szkody brak, ale komunikat mógłby być ładniejszy.
- Import jednowątkowy; olist (~100k wierszy, 9 tabel) wchodzi w kilkanaście
  sekund — akceptowalne.
- Duplikaty NAZW arkuszy/tabel po sanityzacji nadpisują się nawzajem (rzadkie).

## Sprawdź się
1. Które dwa mechanizmy (nie „walidacje"!) eliminują path traversal i zapchanie dysku?
2. Czemu czytamy plik po 1 MB zamiast `await file.read()` w całość?
3. Opisz dwutorową detekcję dat i po co rollback przy rzutowaniu.
4. Co dokładnie psuło się przez brak upsertu? Odtwórz łańcuch: upload → upload → delete → objaw.
5. Dlaczego wszystkie kolumny są lowercase i JAKIE DWA inne miejsca w systemie muszą o tym wiedzieć?
