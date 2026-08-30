# Uruchomienie projektu na nowej maszynie

## Wymagania

- Docker i Docker Compose
- git
- ok. 8 GB RAM (model 7B + Metabase). Karta graficzna **nie jest wymagana** — domyślna
  konfiguracja uruchamia model na CPU. Generowanie trwa wtedy dłużej, ale działa
  poprawnie.
- ok. 10 GB wolnego miejsca (obrazy kontenerów + model językowy ~4,7 GB)

## 1. Przygotuj katalog projektu

Jeśli projekt został przekazany jako **gotowy katalog** (pendrive, archiwum, płyta) —
skopiuj go w wybrane miejsce, wejdź do niego i **przejdź od razu do kroku 2**.

Jeśli masz dostęp do repozytorium i wolisz je sklonować:

```bash
git clone https://github.com/forssst/ecommerce-llm-reports.git
cd ecommerce-llm-reports
```

Repozytorium jest prywatne — przy logowaniu w miejsce hasła podaje się **Personal Access
Token** (GitHub → Settings → Developer settings → Personal access tokens (classic),
zakres `repo`); GitHub nie przyjmuje już hasła do konta przy operacjach gitowych.

## 2. Utwórz plik `.env`

W **katalogu głównym projektu**, czyli tam, gdzie leży `docker-compose.yml` — Docker Compose
szuka tego pliku właśnie tam i nigdzie indziej:

```bash
cp .env.example .env
```

Jeśli pliku `.env.example` nie ma (zaczyna się od kropki, więc bywa pomijany przy
kopiowaniu przez menedżera plików), utwórz `.env` ręcznie z trzema liniami:
`METABASE_USER=`, `METABASE_PASSWORD=`, `METABASE_PUBLIC_URL=http://localhost:3000`.

Plik musi nazywać się dokładnie `.env` — Compose wczytuje automatycznie tylko taką nazwę.
Na Windowsie najprościej utworzyć go z PowerShella, bo Eksplorator utrudnia nazwy
zaczynające się od kropki, a Notatnik dopisuje `.txt`:

```powershell
@"
METABASE_USER=twoj@email
METABASE_PASSWORD=twoje_haslo
METABASE_PUBLIC_URL=http://localhost:3000
"@ | Set-Content -Path .env -Encoding ascii
```

`-Encoding ascii` jest istotne: domyślne kodowanie PowerShella wstawia na początku pliku
znacznik BOM, przez który pierwsza zmienna nie zostanie odczytana.

Sprawdzenie, czy plik został wczytany:

```bash
docker compose config | grep METABASE
```

W wyniku muszą być widoczne wartości, a nie puste miejsca.

Uzupełnij dwie zmienne — **bez nich backend celowo nie wystartuje**:

| zmienna | co wpisać |
|---|---|
| `METABASE_USER` | e-mail konta administratora Metabase (założysz je w kroku 5) |
| `METABASE_PASSWORD` | hasło tego konta |

Dane muszą się zgadzać **dokładnie** z kontem, które założysz w Metabase — backend loguje
się nimi do jego API. To najczęstsza przyczyna błędów przy pierwszym uruchomieniu.

## 3. Postaw usługi

```bash
docker compose up -d --build ollama postgres metabase n8n fastapi_backend frontend
```

> **Wymień usługi po nazwie.** Samo `docker compose up -d --build` spróbuje zbudować
> także usługę `task-runners`, która wymaga pliku `n8n-task-runners.json` nieobecnego
> w repozytorium — build zakończy się błędem. Usługi `task-runners` i `streamlit`
> to pozostałości wcześniejszych wersji i nie są potrzebne.

### Akceleracja GPU (opcjonalnie)

Domyślnie model działa na CPU, dzięki czemu system uruchamia się na dowolnej maszynie.
Jeśli masz kartę NVIDIA ze sterownikiem kontenerowym, dołóż nakładkę:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build \
    ollama postgres metabase n8n fastapi_backend frontend
```

Żeby nie dopisywać tego za każdym razem, można wpisać do `.env`:
`COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml` (na Windowsie separatorem jest
średnik zamiast dwukropka).

### Windows i Docker Desktop

- Uruchom Docker Desktop i poczekaj, aż ikona wieloryba przestanie się animować;
  zalecany backend to **WSL2**.
- Polecenia wpisuj w **PowerShell** albo w terminalu WSL. Działają bez zmian, z jednym
  wyjątkiem: `curl` w PowerShellu jest aliasem innego polecenia, więc sprawdzenie
  z kroku 7 wykonaj jako `curl.exe http://localhost:8000/health` albo po prostu otwórz
  ten adres w przeglądarce.
- Domyślny limit pamięci dla WSL2 bywa za niski dla modelu 7B razem z Metabase. Jeśli
  kontenery są ubijane albo generowanie kończy się bez odpowiedzi, zwiększ limit w pliku
  `C:\Users\<nazwa>\.wslconfig`:

  ```ini
  [wsl2]
  memory=10GB
  ```

  a potem `wsl --shutdown` i ponowny start Docker Desktop.

## 4. Pobierz model językowy

Model nie jest częścią repozytorium (ok. 4,7 GB):

```bash
docker exec -it ollama ollama pull qwen2.5-coder:7b
```

## 5. Skonfiguruj Metabase

1. Wejdź na <http://localhost:3000>.
2. Załóż konto administratora — **tym samym e-mailem i hasłem, które wpisałeś do `.env`**.
3. Włącz publiczne udostępnianie: *Admin settings → Public sharing → Enable*.
   Bez tego dashboardy powstaną, ale frontend nie osadzi ich w ramce.

Baz danych **nie dodajesz ręcznie** — backend rejestruje je w Metabase automatycznie
przy pierwszym generowaniu dashboardu.

## 6. Zaimportuj i aktywuj przepływ n8n

n8n jest główną warstwą orkiestracji generowania — bez niego system nie zbuduje dashboardu.

1. Wejdź na <http://localhost:5678> i załóż konto lokalne.
2. *Import from File* → wybierz `n8n_orchestrator_workflow.json` z katalogu repozytorium
   (29 węzłów).
3. Utwórz poświadczenie dla Ollamy: *Credentials* → *Add credential* → wyszukaj
   **Ollama** → w polu *Base URL* wpisz `http://ollama:11434` i zapisz. Następnie otwórz
   węzeł **Model Ollama (Plan)** i wybierz to poświadczenie z listy.
   Bez tego kroku węzeł ma wiszące odwołanie do poświadczenia z innej instalacji
   i etap planowania dashboardu zakończy się błędem — mimo że pozostałe wywołania modelu
   (węzeł *Generuj SQL i Zbierz Wykresy*) działają, bo wołają Ollamę wprost po adresie.
4. Otwórz węzeł **Metabase Login** i w polu *JSON Body* wpisz e-mail i hasło konta
   administratora Metabase w miejsce `WPISZ_EMAIL_ADMINA_METABASE` i
   `WPISZ_HASLO_ADMINA_METABASE`. Te same dane, co w `.env` — n8n loguje się do Metabase
   niezależnie od backendu i dlatego potrzebuje ich osobno.
5. Ustaw przepływ jako **Active**. Produkcyjny webhook rejestruje się dopiero po
   aktywacji — dopóki tego nie zrobisz, backend dostanie błąd 404.

Backend woła przepływ pod adresem `http://n8n_local:5678/webhook/create-dashboard`.

## 7. Sprawdź, czy wszystko żyje

```bash
curl http://localhost:8000/health
```

Odpowiedź `{"status":"ok"}` oznacza, że backend widzi Ollamę, Metabase i PostgreSQL.
Jeśli któraś usługa jeszcze wstaje, zobaczysz `"degraded"` i nazwę usługi z błędem.

Interfejs użytkownika: <http://localhost:5173>.

## 8. Wgraj dane

Załóż konto w aplikacji, a następnie wgraj plik przez zakładkę *Bazy danych*.
Obsługiwane formaty: `.csv`, `.xlsx`, `.xls` oraz pliki SQLite (`.db`, `.sqlite`,
`.sqlite3`). Dane trafiają do
PostgreSQL, do osobnego schematu na każdą wgraną bazę (nazwa schematu:
*identyfikator użytkownika + nazwa pliku*, np. `u2_northwind`).

Przykładowe zbiory testowe są w katalogu `pliki_testowe/`.

## Znane pułapki

| objaw | przyczyna |
|---|---|
| kontener `fastapi_backend` w pętli restartów, w logach `Brak METABASE_USER / METABASE_PASSWORD` | nie ma pliku `.env`, ma złą nazwę (`.env.txt`, `test.env`) albo zmienne są puste; `restart: always` podnosi kontener w kółko, więc objawem jest ciągłe „restarting" |
| backend startuje, ale generowanie kończy się błędem logowania do Metabase | konto w Metabase nie zgadza się z `.env` |
| `There was a problem displaying this chart` | karta celuje w bazę, której Metabase nie ma podłączonej — sprawdź, czy backend zarejestrował ją automatycznie |
| Metabase wpada w pętlę restartów | `JAVA_OPTS` musi mieć `-Xms` nie większe niż `-Xmx` |
| generowanie zwraca 404 z n8n | przepływ nie jest ustawiony jako *Active* |
| dashboard nie powstaje, w n8n błąd 401 na węźle *Metabase Login* | nie uzupełniono danych logowania w tym węźle po imporcie (krok 6) |
| generowanie pada na etapie planu, węzeł *Model Ollama (Plan)* zgłasza brak poświadczenia | nie utworzono poświadczenia Ollamy w n8n (krok 6) — nie jest ono częścią eksportu przepływu |
| `could not select device driver "nvidia" with capabilities: [[gpu]]` | uruchomiono z nakładką `docker-compose.gpu.yml` (albo z `COMPOSE_FILE` w `.env`) na maszynie bez karty NVIDIA — pomiń nakładkę, model pójdzie na CPU |
| build kończy się błędem na `task-runners` | uruchomiono `docker compose up` bez wymienienia usług (patrz krok 3) |

Po każdej zmianie w kodzie backendu trzeba przebudować obraz:

```bash
docker compose up -d --build fastapi_backend
```
