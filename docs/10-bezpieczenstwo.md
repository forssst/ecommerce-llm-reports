# 10 — Bezpieczeństwo: model zagrożeń, naprawione luki, granice (deep dive)

> Najmocniejszy narracyjnie rozdział pracy: WSZYSTKIE cztery luki zostały
> znalezione WŁASNYMI testami (blok tests/), naprawione i domknięte regresją.
> Do każdej: jak wyglądała, jak ją wykryto, jak naprawiono, jak jest pilnowana.

## 1. Model zagrożeń (kto/co atakuje)

1. **Złośliwy zalogowany użytkownik** — próbuje czytać/kasować cudze dane (IDOR),
   podszywać się pod innych, wgrywać złośliwe pliki.
2. **Model językowy jako „niepewny wykonawca"** — generuje SQL; może (przez
   halucynację albo prompt injection w danych/opisie) wyprodukować SQL
   destrukcyjny lub eksfiltrujący.
3. **Sieć lokalna** — usługi wystawione na localhost (świadome dla dev).

## 2. Cztery naprawione luki — studium przypadku

### 2.1. IDOR na zasobach (`/users/{id}/databases`, `/users/{id}/queries`, `DELETE /databases/{id}`)
- **Było:** endpointy sprawdzały tylko WAŻNOŚĆ tokenu, nie WŁAŚCICIELA —
  user B z poprawnym tokenem czytał bazy/historię A i mógł skasować jego bazę.
  Podstępne: przez UI wyglądało OK (frontend pyta tylko o swoje id) — lukę
  widać dopiero z poziomu API. Wykryte testem `tests/test_isolation.py`.
- **Naprawa:** `if user_id != token_user_id: 403` + w DELETE lookup rekordu
  i porównanie `rec.user_id != token_user_id`.
- **Pilnowane przez:** testy izolacji (A→zasoby B → 403).

### 2.2. `/generate` ufał `user_id` z body
- **Było:** historia zapytań zapisywana na KONTO PODANE W BODY — user B mógł
  generować „jako A" (zaśmiecać historię, podszywać się).
- **Naprawa:** `g.user_id = token_user_id` — pole z body istnieje dla zgodności,
  ale jest ignorowane. Analogicznie `/upload` (Form user_id → nadpisany).
- **Pilnowane przez:** `test_b_nie_moze_generowac_jako_a` (pełna generacja!).

### 2.3. Upload bez limitów i z nazwą od użytkownika
- **Było:** brak limitu rozmiaru (DoS dyskiem), nazwa pliku od usera trafiała
  na dysk (path traversal `../../...`), błędy parsowania jako 500.
- **Naprawa:** strumieniowy licznik z limitem (500 MB) → 413;
  plik na dysku pod NAZWĄ LOSOWĄ `uuid4` (klasa problemu wyeliminowana,
  nie „sanityzowana"); `os.path.basename` na nazwie wyświetlanej; 400 z opisem
  zamiast 500.
- **Pilnowane przez:** blok upload w tests/ (413, traversal, uszkodzony plik).

### 2.4. SQL od modelu z pełnymi prawami (naprawione 2026-07-06)
- **Było:** `_run_and_validate` i połączenia Metabase używały usera `analyst`
  (właściciel bazy!) — teoretyczny `DROP SCHEMA` od modelu przeszedłby.
  Test dokumentował lukę jako `xfail`.
- **Naprawa — obrona UPRAWNIENIAMI, nie parsowaniem:** rola `readonly`
  (bootstrap idempotentny przy starcie backendu — działa na świeżym klonie):
  ```
  CREATE ROLE readonly LOGIN PASSWORD ...
  GRANT CONNECT ON DATABASE analytics TO readonly
  ALTER DEFAULT PRIVILEGES FOR ROLE analyst GRANT SELECT ON TABLES TO readonly
  -- per istniejący/nowy schemat: GRANT USAGE (+ SELECT ON ALL TABLES)
  ```
  Używana w: `_run_and_validate(readonly=True)`, rejestracji źródeł Metabase
  (Python i węzeł n8n), plus migracja 13 istniejących źródeł przez API.
- **Dlaczego nie parsowanie SQL:** blocklista („nie zawiera DROP") jest
  omijalna (CTE, funkcje, komentarze, encoding); uprawnienia bazy są
  matematycznie szczelne dla tej klasy ataku.
- **Weryfikacja ręczna:** `psql -U readonly` → SELECT działa,
  `CREATE TABLE`/`DELETE` → `permission denied`. Test z xfail → zwykły pass.
- **Test na żywo (G5):** prompt „usuń wszystkie zamówienia z tabeli" —
  model i tak ułożył analitykę; nawet gdyby nie — rola nie pozwala.

## 3. Uwierzytelnianie — detale odpornościowe

- bcrypt z solą (gensalt) — powolny z definicji (odporność na brute-force
  offline); porównanie `checkpw` (stała czasowo).
- JWT: podpis HS256 + `exp` (7 dni); manipulacja payloadem unieważnia podpis;
  wygaśnięcie → 401 → frontend robi logout (test G7: zepsuty token w
  localStorage → powrót do logowania, nie biały ekran).
- Świadome braki: brak refresh-tokenów, brak rate-limitu na /login,
  brak blokady konta — akceptowalne dla lokalnego demo, wymienić jako
  hardening produkcyjny.

## 4. Granica zaufania `/internal`

Endpointy `/internal/...` nie mają auth. Uzasadnienie warstwowe:
1. nasłuch tylko w sieci dockerowej compose (brak publikacji przez proxy),
2. nie wykonują nic destrukcyjnego (budują prompty, walidują SQL rolą readonly),
3. wołający (n8n) i wołany (backend) są w tej samej domenie zaufania.
Produkcyjnie: wspólny sekret w nagłówku albo mTLS — jedna linijka do
wymienienia w „kierunkach rozwoju".

## 5. Co pozostaje otwarte (uczciwa lista na obronę)

| Obszar | Stan | Produkcyjna odpowiedź |
|---|---|---|
| Sekrety w kodzie (JWT_SECRET, creds Metabase/PG) | znane, lokalnie akceptowane | zmienne środowiskowe / vault |
| Publiczne linki Metabase | UUID nieodgadywalny, ale „kto ma link, ten widzi" | signed embedding albo kolekcje+grupy per user |
| HTTPS | brak (localhost) | reverse proxy z TLS |
| Rate limiting / lockout | brak | slowapi/nginx limit_req |
| Prompt injection przez dane (np. złośliwe wartości w kolumnach trafiają do promptu przez _text_column_values/opis) | ryzyko niskie (wyjście = SQL walidowany + rola RO ogranicza skutki) | filtrowanie/escapowanie wartości w prompcie |
| Konta seedowane `password_hash="x"` | relikt w /login | usunąć fallback + wyczyścić konta |

## 6. Argumentacja „defense in depth" (gotowa na obronę)

Warstwy dla najgroźniejszego scenariusza („model generuje zły SQL"):
prompt (reguły) → `_clean_sql` (normalizacja) → guardy przed wykonaniem
(relative-date) → wykonanie ROLĄ READONLY → walidacja kształtu → retry
z błędem → pominięcie z ostrzeżeniem → bramka 0 wykresów. Kompromitacja
jednej warstwy NIE kompromituje systemu.
