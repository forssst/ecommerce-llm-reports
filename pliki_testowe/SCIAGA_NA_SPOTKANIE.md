# Ściąga na spotkanie z promotorem (aktualizacja 2026-07-06)

> Jedna kartka. Przeczytaj rano, opowiedz na głos 2× i jesteś gotowy.

---

## 🎯 CO ROBI SYSTEM (jedno zdanie)
System „AI Data Analyst": użytkownik pisze cel analityczny **po polsku**, lokalny model AI
zamienia go na SQL, wynik trafia na **interaktywny dashboard w Metabase**. Wszystko działa
**lokalnie** — bez chmury, bez kosztów, z zachowaniem prywatności danych.

---

## 🔄 PRZEPŁYW — opowiedz to z głowy (6 kroków)

1. **Upload** — użytkownik wgrywa plik (SQLite/CSV/Excel). Dane lądują w **PostgreSQL**
   jako osobny schemat dla tego użytkownika (`u{id}_nazwa`).
2. **Cel po polsku** — np. „pokaż TOP 10 klientów według zakupów". Backend przekazuje go
   do **n8n** (webhook) — n8n prowadzi CAŁY proces generowania.
3. **Etap A — Planowanie** (natywne węzły AI w n8n): model (qwen2.5-coder:7b przez Ollamę)
   rozbija cel na **2–4 wykresy** — dla każdego `{tytuł, typ wykresu, cel}`. Guard językowy:
   plan w obcym języku → jedna próba retry.
4. **Etap B — SQL**: dla każdego wykresu **osobne** zapytanie. Model pisze SQL → system
   **wykonuje go naprawdę** na danych (rolą read-only!) → jak błąd lub 0 wierszy, treść
   błędu wraca do modelu jako wskazówka (max 3 próby). Wykres bez poprawnego SQL jest
   **pomijany z jawnym ostrzeżeniem** w UI, nie wisi ani nie psuje całości.
5. **Metabase** — n8n tworzy dashboard, karty, filtr dat na poziomie dashboardu,
   publiczny link.
6. **Frontend** osadza dashboard przez `<iframe>`; pokazuje też SQL każdej karty
   i liczbę auto-korekt.

> **Klucz do zapamiętania:** n8n = orkiestracja (CO po CZYM — widać na canvasie),
> Python = logika (JAK: prompty, guardy, walidacja — przez endpointy `/internal/...`).

---

## 📊 LICZBY DO POKAZANIA (Ewaluacja — zmierzone, nie szacowane)

- **Harness (18 promptów, 5 baz, 3 poziomy trudności): 18/18 dashboardów (100%)**,
  na poziomie pojedynczych wykresów **47/54 (87%)** — różnicę ratuje mechanizm
  retry + pominięcie z ostrzeżeniem. **29 auto-korekt SQL** łącznie.
- Czasy: **mediana ~90 s** (57–150 s) — na GPU 3GB model liczy w ~83% na CPU;
  na lepszym sprzęcie byłoby kilkukrotnie szybciej.
- **Stress-test**: granica niezawodnej pracy między **3 a 5 równoczesnych** użytkowników
  (Ollama serializuje inferencję).
- **Bezpieczeństwo: 4 luki znalezione własnymi testami → 4 naprawione**
  (IDOR, user_id z tokenu, limity uploadu, SQL read-only). **31 testów pytest, 0 porażek.**
- Testy manualne: 21 scenariuszy na 5 bazach → **8 realnych bugów znalezionych
  i naprawionych** w trakcie.

---

## ❓ 6 ODPOWIEDZI „DLACZEGO" (najczęstsze pytania)

**1. Dlaczego lokalny model, a nie ChatGPT/API?**
→ Prywatność danych (nic nie wychodzi na zewnątrz), brak kosztów API, działanie offline.
To świadoma decyzja architektoniczna, nie ograniczenie.

**2. Dlaczego n8n jako orchestrator, a nie czysty Python?**
→ Control-flow WIDAĆ (canvas: plan → retry → pętla SQL → dashboard), orkiestracja
oddzielona od logiki, zmiany przepływu bez rebuildu backendu. Kosztem kilkunastu %
narzutu czasowego — zmierzone i opisane. Logika NIE jest zduplikowana: n8n woła
te same funkcje Pythona przez cienkie endpointy `/internal/...`, więc każdy guard
żyje w jednym miejscu.

**3. Dlaczego PostgreSQL, a nie pliki?**
→ Trwałość, poprawne typy (daty jako TIMESTAMP — potrzebne do filtrów), izolacja
użytkowników (schemat per user), bezpośrednie połączenie z Metabase, rola read-only.

**4. Dlaczego dwa etapy (plan + SQL osobno)?**
→ Małemu modelowi łatwiej napisać jeden poprawny SQL na wąski cel niż cały dashboard
naraz. Dekompozycja problemu = wyższa jakość.

**5. Co jak model wygeneruje zły SQL?**
→ System **wykonuje SQL na prawdziwych danych** rolą read-only. Błąd (albo 0 wierszy)
wraca do modelu jako wskazówka, max 3 próby, potem wykres pomijany z ostrzeżeniem.
A destrukcyjny SQL (DROP/DELETE) **fizycznie nie może się wykonać** — uprawnienia
Postgresa, nie parsowanie tekstu.

**6. Dlaczego Metabase?**
→ Gotowe, darmowe, open-source narzędzie BI z REST API i publicznymi linkami.
Nie wynajdowałem koła od nowa.

---

## ⚠️ ZNANE OGRANICZENIA (powiedz sam, zanim zapyta!)

1. **Złożone JOIN-y (3+ tabel)** — model 7B czasem gubi część wykresów (87% skuteczności
   per wykres; system raportuje to jawnie). Kierunek: większy model.
2. **Language drift** — 4 języki wyłapane w testach (chiński, rosyjski, węgierski,
   angielski); guard deterministyczny łapie 3 pierwsze, angielskiego się nie da bez
   słownika. Udokumentowane.
3. **Semantyczne poślizgi** — tytuł wykresu czasem obiecuje co innego, niż SQL liczy
   (np. „kategorie", a grupowanie po miesiącu). Granica deterministycznych guardów.
4. **Wydajność sprzętowa** — mediana ~90 s wynika z inferencji na CPU (VRAM 3GB);
   to własność sprzętu, nie architektury.
5. **Planner wypełnia dashboard** — przy wąskim celu (materiał na 1 wykres) model
   dorabia 2 dodatkowe „z własnej inwencji". Obejście: wybór konkretnych typów wykresów.

---

## 🛠️ STACK (gdyby zapytał czym to napisane)

| Warstwa        | Technologia                                    |
|----------------|------------------------------------------------|
| Frontend       | React + Vite + Tailwind (w Dockerze, nginx)    |
| Backend        | FastAPI (Python), SQLAlchemy                   |
| **Orkiestracja AI** | **n8n (workflow 29 węzłów, webhook)**     |
| Model AI       | Ollama + qwen2.5-coder:7b (lokalnie)           |
| Baza danych    | PostgreSQL (dane, rola read-only) + SQLite (metadane) |
| Wizualizacja   | Metabase                                       |
| Infrastruktura | Docker Compose (6 usług)                       |

---

## 🔑 KLUCZOWE ELEMENTY (gdyby chciał wejść głębiej)

- **Workflow n8n** — serce: plan (natywne węzły Ollama) → pętla SQL (Code node) →
  budowa dashboardu Metabase → odpowiedź z SQL i licznikami
- **`/internal/...`** — 6 cienkich endpointów: cała logika Pythona używana przez n8n
  (prompty, czyszczenie SQL, walidacja, guardy) — zero duplikacji
- **`_run_and_validate`** — wykonuje SQL na danych (read-only), zwraca błąd lub wynik
- **`_clean_sql`** — naprawia typowe błędy modelu (backticki, prefiksy, wiele zapytań)
- **Guardy** — każdy powstał z konkretnego buga znalezionego w testach: język, daty
  względne, TOP N, 0 wierszy, kształt licznika... (masz historię do każdego!)
- **`eval_harness.py` / `stress_test_ollama.py`** — pomiary do Ewaluacji, powtarzalne

---

## 💡 ZŁOTA ZASADA NA SPOTKANIE
Jak czegoś nie wiesz — **nie zmyślaj**. Powiedz: „to działa tak a tak, szczegóły mam w kodzie".
Promotor woli „wiem gdzie to jest" niż konfabulację. Mów o **decyzjach i przepływie**,
nie o składni. Ty znasz ten projekt najlepiej w tym pokoju.
