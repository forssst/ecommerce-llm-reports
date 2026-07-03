# Testy autoryzacji i bezpieczeństwa

Szkielet testów automatycznych do rozdziału „Bezpieczeństwo / Testy". Uderzają
w **działający** backend przez HTTP (tak jak frontend), więc przed uruchomieniem:

```bash
docker compose up -d fastapi_backend
```

## Uruchamianie

```bash
# wszystkie testy (z katalogu projektu)
venv/bin/pytest tests/ -v

# tylko warstwa danych (SQL read-only) — potrzebuje dostępu do Postgresa z hosta
PG_HOST=localhost PG_PORT=5432 venv/bin/pytest tests/test_sql_safety.py -v

# inny adres backendu
BASE_URL=http://localhost:8000 venv/bin/pytest tests/ -v
```

## Co jest sprawdzane

| Plik | Blok | Zakres |
|------|------|--------|
| `test_auth_token.py` | Token JWT | brak/zły/podrobiony token → 401; poprawny → 200 |
| `test_isolation.py` | Izolacja użytkowników | czy user B sięga po zasoby usera A (IDOR) |
| `test_upload_validation.py` | Walidacja uploadu | złe formaty, rozmiar, nazwy plików |
| `test_sql_safety.py` | Read-only SQL | czy generowany SQL może modyfikować dane |

## Odczyt wyników — ważne

Część testów jest oznaczona `@pytest.mark.xfail`. To **celowo udokumentowane luki**
obecnej wersji, nie błędy w testach:

- **XFAIL** (żółte) = test przechodzi „na czerwono" zgodnie z oczekiwaniem — luka
  nadal istnieje. Przykłady: IDOR na `/users/{id}/databases` i `/queries`, brak
  read-only dla SQL, brak limitu rozmiaru uploadu.
- **XPASS** = luka została naprawiona → usuń wtedy marker `xfail` z danego testu.
- **PASSED** (zielone) = zachowanie już jest poprawne (np. warstwa tokenu JWT).

Dzięki temu przebieg jest „zielony", a lista `xfail` w podsumowaniu to gotowa
tabela znanych podatności do opisania i naprawy.
