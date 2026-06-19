# Uruchomienie projektu na nowej maszynie

## Wymagania

- Docker + Docker Compose
- git
- ~8 GB RAM (model 7B + Metabase); na słabszym sprzęcie generacja będzie wolniejsza

## 1. Sklonuj repozytorium

Repozytorium jest prywatne — przy logowaniu użyj **Personal Access Token (PAT)**, a nie
hasła do konta (GitHub nie przyjmuje już haseł przy operacjach git):

```bash
git clone https://github.com/forssst/ecommerce-llm-reports.git
cd ecommerce-llm-reports
```

Token wygenerujesz w: GitHub → Settings → Developer settings → Personal access tokens
(classic), zakres `repo`. Wklejasz go w miejscu hasła.

## 2. Utwórz plik `.env`

Plik `.env` nie jest w repozytorium (zawiera dane logowania). Utwórz go w katalogu
głównym i uzupełnij zmienne wymagane przez `docker-compose.yml` (m.in. login i hasło
administratora Metabase). Nazwy zmiennych muszą zgadzać się z tymi, do których odwołuje
się `docker-compose.yml`.

## 3. Postaw usługi

```bash
docker compose up -d --build
```

## 4. Pobierz model językowy

Model nie jest w repozytorium — pobierz go do kontenera Ollama:

```bash
docker exec -it ollama ollama pull qwen2.5-coder:7b
```

## 5. Wgraj dane testowe

Skopiuj pliki baz (np. `olist.sqlite`, `AdventureWorks`) do katalogu `uploads/`
— przez interfejs aplikacji lub ręcznie. Pliki danych nie są w repozytorium.

## 6. Skonfiguruj Metabase

- Wejdź na http://localhost:3000 i załóż konto administratora.
- Włącz publiczne udostępnianie: Admin → Settings → Public sharing.
- Wgrane bazy podłączą się **automatycznie** przy pierwszej generacji (auto-rejestracja
  przez API Metabase).

## 7. (Opcjonalnie) n8n — ścieżka zapasowa

Jeśli korzystasz z fallbacku przez n8n: wejdź na http://localhost:5678, zaimportuj
workflow z webhookiem o ścieżce `sales-report` i ustaw go jako **Active** (produkcyjny
webhook rejestruje się dopiero po aktywacji).

## Adresy usług

| Usługa     | Adres                  |
|------------|------------------------|
| Frontend   | http://localhost:5173  |
| Backend API| http://localhost:8000  |
| Metabase   | http://localhost:3000  |
| n8n        | http://localhost:5678  |
| Ollama     | http://localhost:11434 |

(Porty zależą od `docker-compose.yml` — w razie potrzeby zweryfikuj.)

## Najczęstsze problemy

- **Metabase wpada w pętlę restartu z błędem „Initial heap size set to a larger value
  than the maximum heap size":** w `docker-compose.yml`, w serwisie `metabase`, ustaw
  `JAVA_OPTS=-Xms256m -Xmx1g` (warunek: `Xms` ≤ `Xmx`).
- **Błąd „webhook sales-report is not registered":** aktywuj workflow w n8n.
- **„There was a problem displaying this chart":** upewnij się, że Metabase widzi plik
  bazy (wspólny wolumen) i że baza jest podłączona jako źródło danych.
- **`Authentication failed` przy git push/clone:** użyj tokenu (PAT) zamiast hasła konta.
