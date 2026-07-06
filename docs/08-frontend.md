# 08 — Frontend: stan, przepływy, konwencje (deep dive)

> Plik: `frontend/src/App.jsx` (~740 linii, JEDEN komponent — świadoma prostota
> pracy inż.; rozbicie na komponenty = łatwy „kierunek rozwoju" do wymienienia).
> Stack: React 18 + Vite + Tailwind (build → nginx w kontenerze).

## 1. Mapa stanu (useState — kompletna)

| Grupa | Stany | Uwagi |
|---|---|---|
| Sesja | `user, email, password, authMode` | `user` inicjalizowany z `localStorage` (odświeżenie strony nie wylogowuje) |
| Nawigacja | `activeTab` | kreator / bazy / historia |
| Bazy | `databases, selectedDbId, uploadFile, isUploading` | `selectedDbId` ustawiany na pierwszą bazę po `fetchDatabases` |
| Kreator | `goal, description, selectedTypes, showSchema, showDesc` | `selectedTypes` = tablica NAZW PL w kolejności kliknięć |
| Enhance | `isEnhancing, isClarifying, clarifyQuestion, clarifyAnswer` | dwustopniowy przepływ |
| Wynik | `loading, result, showSql` | `result` = pełna odpowiedź `/generate` |
| Opis | `isGeneratingDesc` | spinner przycisku opisu |
| Historia | `history` | |

Pomocnicze: `authHeaders()` → `{Authorization: Bearer <localStorage.token>}`;
`buildSchemaText(schema)` → `"Tabela X: kol (typ), ..."` per tabela, łączone `\n`
— DOKŁADNIE ten format widzi model (i ten sam buduje harness w testach).

## 2. Przepływ logowania

`handleLogin/handleRegister` → POST → `enterApp(data)`:
zapis `token` + `{id,email}` do localStorage → `fetchDatabases` + `fetchHistory`.
Każdy fetch listy z odpowiedzią 401 → `logout()` (czyści storage i stan) —
tak frontend obsługuje wygaśnięcie tokenu (test G7).
Quirk: hasło leci w polu `password_hash` (patrz docs/02 §1.1).

## 3. Przepływ „Ulepsz prompt AI" (dwustopniowy)

```
startEnhance():
  POST /clarify-prompt {goal, schema_text, description}
  ├─ question != null → pokaż żółty box (clarifyQuestion) i CZEKAJ
  │    ├─ „✦ Ulepsz z odpowiedzią" → runEnhance(question, answer)
  │    └─ „Pomiń"                  → runEnhance("", "")
  └─ question == null → runEnhance("", "")

runEnhance(q, a):
  1. opis: JEŚLI pole opisu niepuste (i nie jest ostrzeżeniem „⚠...") → użyj go;
     inaczej wygeneruj świeży (describe-schema) i wpisz do pola
     [naprawa 2026-07-06: wcześniej ZAWSZE generował drugi raz — ~1-2 min straty]
  2. POST /enhance-prompt {prompt: goal, schema_text, description, clarify_question, clarify_answer}
  3. setGoal(data.enhanced) — cel w polu zostaje PODMIENIONY
```

## 4. Przepływ „Generuj Dashboard"

`handleGenerate()`:
- walidacje lokalne (baza wybrana, cel niepusty),
- `buildChartType()`: `selectedTypes` → `"Dokładnie N wykresy: (1) Słupkowy, (2) ..."`
  — ten STRING parsuje potem backendowy `_parse_requested_charts`
  (kontrakt: kolejność liczb = kolejność kart),
- POST `/generate` z `n8n_timeout` (długi — inferencja na CPU),
- `setResult(data)`; render:
  - sukces → pasek statusu (zielona kropka, `retry_count` jako
    „N auto-korekta SQL", żółty badge `chart_summary.failed > 0` z tytułami
    pominiętych), przyciski „Otwórz w Metabase" / „Pokaż SQL"
    (`<pre>` z `result.sql`), iframe `result.metabase.url` na resztę ekranu,
  - błąd → czerwony box `result.error`.

## 5. Upload i lista baz

- Upload: `FormData(user_id, file)` — user_id i tak nadpisywany z tokenu;
  po sukcesie `fetchDatabases` (odświeża listę + selectedDbId).
- `handleDeleteDb`: `confirm()` → DELETE → refetch; jeśli usunięto wybraną,
  `selectedDbId=""`.
- Zmiana bazy w dropdownie CZYŚCI `description` i chowa ściągę schematu —
  opis dotyczy konkretnej bazy.

## 6. Historia

`GET /users/{id}/queries` → tabela wpisów; „otwórz ponownie" wyciąga
`dashboard_url` z JSON-a zapisanego w polu `sql` wpisu i ustawia jako result
(iframe) — dashboardy w Metabase są trwałe, więc stare linki działają.

## 7. Konwencje błędów w UI

- Operacje blokujące mają dedykowane spinnery (isUploading, isEnhancing,
  isGeneratingDesc, loading) — przyciski disabled w trakcie.
- Komunikaty z backendu (`data.detail`) pokazywane WPROST (naprawa: wcześniej
  generyczny tekst maskował prawdziwą przyczynę — np. „Brak schematu bazy").
- Znany dług techniczny: `generateDescription()` i `runEnhance()` mają
  zduplikowaną obsługę describe-schema (dwa miejsca robiące to samo —
  naprawiliśmy objaw, refaktor do wspólnej funkcji świadomie odłożony).

## Sprawdź się
1. Co dokładnie trzyma localStorage i jak frontend reaguje na 401?
2. Odtwórz kontrakt stringa `chart_type` między `buildChartType()` a
   `_parse_requested_charts` — czemu to string, nie tablica?
3. Kiedy runEnhance NIE wygeneruje nowego opisu?
4. Jak działa „otwórz ponownie" z historii, skoro backend nie ma endpointu
   „get dashboard"?
5. Wskaż przykład długu technicznego frontendu i jego koszt (miałeś go w testach!).
