import { useState } from 'react';

const API_URL = "http://localhost:8000";

export default function App() {
  const [user, setUser]             = useState(null);
  const [email, setEmail]           = useState("test@test.pl");
  const [password, setPassword]     = useState("");
  const [authMode, setAuthMode]     = useState("login");

  const [activeTab, setActiveTab]   = useState("kreator");
  const [databases, setDatabases]   = useState([]);
  const [selectedDbId, setSelectedDbId] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [history, setHistory]       = useState([]);

  const [description, setDescription]         = useState("");
  const [isGeneratingDesc, setIsGeneratingDesc] = useState(false);
  const [goal, setGoal]                       = useState("");
  const [selectedTypes, setSelectedTypes] = useState([]);
  const [loading, setLoading]           = useState(false);
  const [result, setResult]             = useState(null);
  const [showSql, setShowSql]           = useState(false);
  const [isEnhancing, setIsEnhancing]   = useState(false);
  const [showSchema, setShowSchema]     = useState(false);

  const enterApp = (data) => {
    setUser(data);
    fetchDatabases(data.id);
    fetchHistory(data.id);
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    if (!email || !password) return alert("Podaj e-mail i hasło.");
    try {
      const res = await fetch(`${API_URL}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password_hash: password }),
      });
      if (!res.ok) return alert("Nieprawidłowy e-mail lub hasło.");
      enterApp(await res.json());
    } catch {
      alert("Błąd połączenia z serwerem.");
    }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    if (!email || !password) return alert("Podaj e-mail i hasło.");
    try {
      const res = await fetch(`${API_URL}/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password_hash: password }),
      });
      if (res.status === 409) { alert("Konto istnieje. Zaloguj się."); setAuthMode("login"); return; }
      if (!res.ok) return alert("Nie udało się utworzyć konta.");
      enterApp(await res.json());
    } catch {
      alert("Błąd połączenia z serwerem.");
    }
  };

  const generateDescription = async (dbObj) => {
    if (!dbObj) return;
    const schemaText = Object.entries(dbObj.schema)
      .map(([table, cols]) => `Tabela ${table}: ${cols.join(", ")}`)
      .join("\n");
    setIsGeneratingDesc(true);
    setDescription("");
    try {
      const res  = await fetch(`${API_URL}/describe-schema`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schema_text: schemaText }),
      });
      const data = await res.json();
      setDescription(data.description || "");
    } catch { setDescription(""); }
    setIsGeneratingDesc(false);
  };

  const enhancePrompt = async () => {
    const selectedDb = databases.find(d => d.id == selectedDbId);
    if (!selectedDb) return alert("Wybierz bazę danych.");
    if (!goal.trim()) return alert("Wpisz cel analityczny do ulepszenia.");
    const schemaText = Object.entries(selectedDb.schema)
      .map(([table, cols]) => `Tabela ${table}: ${cols.join(", ")}`)
      .join("\n");
    setIsEnhancing(true);
    try {
      const res = await fetch(`${API_URL}/enhance-prompt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: goal, schema_text: schemaText }),
      });
      const data = await res.json();
      if (data.enhanced) setGoal(data.enhanced);
    } catch { alert("Błąd podczas ulepszania promptu."); }
    setIsEnhancing(false);
  };

  const buildChartType = () => {
    if (selectedTypes.length === 0) return "";
    const names = selectedTypes.map((t, i) => `(${i + 1}) ${t}`).join(', ');
    return `Dokładnie ${selectedTypes.length} wykresy: ${names}`;
  };

  const fetchDatabases = async (userId) => {
    try {
      const res  = await fetch(`${API_URL}/users/${userId}/databases`);
      const data = await res.json();
      setDatabases(data);
      if (data.length > 0) {
        setSelectedDbId(data[0].id);
        generateDescription(data[0]);
      }
    } catch (e) { console.error(e); }
  };

  const fetchHistory = async (userId) => {
    try {
      const res  = await fetch(`${API_URL}/users/${userId}/queries`);
      const data = await res.json();
      setHistory(data);
    } catch (e) { console.error(e); }
  };


  const handleDeleteDb = async (dbId, dbName) => {
    if (!confirm(`Usunąć bazę "${dbName}"? Tej operacji nie można cofnąć.`)) return;
    try {
      await fetch(`${API_URL}/databases/${dbId}`, { method: "DELETE" });
      fetchDatabases(user.id);
      if (selectedDbId == dbId) setSelectedDbId("");
    } catch { alert("Błąd podczas usuwania."); }
  };

  const handleFileUpload = async (e) => {
    e.preventDefault();
    if (!uploadFile) return alert("Wybierz plik .db");
    setIsUploading(true);
    const fd = new FormData();
    fd.append("user_id", user.id);
    fd.append("file", uploadFile);
    try {
      const res = await fetch(`${API_URL}/upload`, { method: "POST", body: fd });
      if (res.ok) { alert("Baza wgrana pomyślnie."); setUploadFile(null); fetchDatabases(user.id); }
      else alert("Błąd podczas wgrywania.");
    } catch { alert("Błąd komunikacji z serwerem."); }
    setIsUploading(false);
  };

  const handleGenerate = async () => {
    const selectedDb = databases.find(db => db.id == selectedDbId);
    if (!selectedDb) return alert("Wybierz bazę danych.");
    const schemaText = Object.entries(selectedDb.schema)
      .map(([table, cols]) => `Tabela ${table}: ${cols.join(", ")}`)
      .join("\n");

    setLoading(true);
    setResult(null);
    setShowSql(false);

    try {
      const res = await fetch(`${API_URL}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.id,
          prompt: goal,
          description,
          chart_type: buildChartType(),
          schema_text: schemaText,
          db_path: selectedDb.file_path,
          n8n_url: "http://n8n_local:5678/webhook/sales-report",
        }),
      });
      const data = await res.json();
      setResult(data);
      fetchHistory(user.id);
    } catch { alert("Błąd podczas generowania."); }
    setLoading(false);
  };

  // ── Ekran logowania ──────────────────────────────────────────────────────────
  if (!user) {
    const isLogin = authMode === "login";
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-slate-900 to-slate-800">
        <div className="p-8 bg-white rounded-2xl shadow-2xl w-full max-w-sm">
          <div className="mb-6 text-center">
            <div className="inline-flex items-center justify-center w-12 h-12 bg-blue-600 rounded-xl mb-3">
              <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <h1 className="text-2xl font-bold text-gray-900">AI Data Analyst</h1>
            <p className="text-sm text-gray-500 mt-1">{isLogin ? "Zaloguj się na konto" : "Utwórz nowe konto"}</p>
          </div>
          <form onSubmit={isLogin ? handleLogin : handleRegister} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">E-mail</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">Hasło</label>
              <input type="password" placeholder="••••••••" value={password} onChange={e => setPassword(e.target.value)}
                className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent" />
            </div>
            <button type="submit"
              className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2.5 rounded-lg transition text-sm">
              {isLogin ? "Zaloguj się" : "Zarejestruj się"}
            </button>
          </form>
          <p className="text-xs text-gray-500 mt-4 text-center">
            {isLogin ? "Nie masz konta? " : "Masz już konto? "}
            <button type="button" onClick={() => { setAuthMode(isLogin ? "register" : "login"); setPassword(""); }}
              className="text-blue-600 font-semibold hover:underline">
              {isLogin ? "Zarejestruj się" : "Zaloguj się"}
            </button>
          </p>
        </div>
      </div>
    );
  }

  // ── Główny layout ────────────────────────────────────────────────────────────
  return (
    <div className="flex h-screen bg-gray-50 font-sans overflow-hidden">

      {/* Sidebar */}
      <aside className="w-60 bg-slate-900 text-white flex flex-col shrink-0">
        <div className="p-5 border-b border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center shrink-0">
              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-bold leading-tight">AI Data Analyst</p>
              <p className="text-xs text-slate-400 truncate max-w-[130px]">{user.email}</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {[
            { id: "kreator",  label: "Kreator raportów" },
            { id: "bazy",     label: "Bazy danych" },
            { id: "historia", label: "Historia" },
          ].map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm transition font-medium
                ${activeTab === tab.id ? "bg-blue-600 text-white" : "text-slate-300 hover:bg-slate-800"}`}>
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="p-3 border-t border-slate-800">
          <button onClick={() => { setUser(null); setPassword(""); setResult(null); }}
            className="w-full text-xs text-slate-400 hover:text-white transition py-1.5 rounded-lg hover:bg-slate-800">
            Wyloguj się
          </button>
        </div>
      </aside>

      {/* Główna treść */}
      <main className="flex-1 overflow-y-auto">

        {/* ── KREATOR ─────────────────────────────────────────────────────── */}
        {activeTab === "kreator" && (
          <div className="flex flex-col h-full">

            {/* Formularz u góry */}
            <div className="bg-white border-b border-gray-200 p-6">
              <div className="max-w-5xl mx-auto">
                <h2 className="text-xl font-bold text-gray-900 mb-4">Kreator Dashboardu</h2>

                <div className="grid grid-cols-2 gap-4">
                  {/* Lewa kolumna */}
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">
                        Baza danych
                      </label>
                      <select value={selectedDbId} onChange={e => {
                          setSelectedDbId(e.target.value);
                          setShowSchema(false);
                          const db = databases.find(d => d.id == e.target.value);
                          generateDescription(db);
                        }}
                        className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500">
                        {databases.length === 0
                          ? <option>Brak baz — wgraj plik .db</option>
                          : databases.map(db => <option key={db.id} value={db.id}>{db.name}</option>)
                        }
                      </select>
                      {/* Ściąga schematu */}
                      {selectedDbId && databases.find(d => d.id == selectedDbId)?.schema && (
                        <div className="mt-1.5">
                          <button type="button" onClick={() => setShowSchema(v => !v)}
                            className="text-xs text-blue-600 hover:underline font-medium flex items-center gap-1">
                            {showSchema ? "▲ Ukryj tabele i kolumny" : "▼ Pokaż tabele i kolumny"}
                          </button>
                          {showSchema && (() => {
                            const db = databases.find(d => d.id == selectedDbId);
                            return (
                              <div className="mt-1.5 border border-blue-100 rounded-lg bg-blue-50 p-2 max-h-48 overflow-y-auto">
                                {Object.entries(db.schema).map(([table, cols]) => (
                                  <div key={table} className="mb-2 last:mb-0">
                                    <p className="text-xs font-bold text-blue-800 font-mono">{table}</p>
                                    <p className="text-xs text-blue-600 font-mono leading-relaxed pl-2">
                                      {cols.join(", ")}
                                    </p>
                                  </div>
                                ))}
                              </div>
                            );
                          })()}
                        </div>
                      )}
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">
                        Cel analityczny
                      </label>
                      <textarea rows="5" placeholder="Co chcesz zobaczyć? Np. 'TOP 10 kategorii wg sprzedaży i trend miesięczny'"
                        value={goal} onChange={e => setGoal(e.target.value)}
                        className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
                      <div className="mt-1.5 flex items-center gap-2">
                        <button type="button" onClick={enhancePrompt}
                          disabled={isEnhancing || !goal.trim()}
                          className="text-xs bg-purple-600 hover:bg-purple-700 disabled:opacity-40 text-white font-semibold px-3 py-1.5 rounded-lg transition flex items-center gap-1.5">
                          {isEnhancing ? (
                            <>
                              <svg className="animate-spin w-3 h-3" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                              </svg>
                              AI ulepsza...
                            </>
                          ) : "✦ Ulepsz prompt AI"}
                        </button>
                        {isEnhancing && (
                          <span className="text-xs text-gray-400">AI przepisuje zapytanie...</span>
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">
                        Typy wykresów
                      </label>
                      <p className="text-xs text-gray-400 mb-2">
                        Kliknij żądane typy w kolejności (AI zdecyduje, jeśli nic nie wybierzesz)
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {[
                          { label: "Słupkowy",          value: "słupkowy" },
                          { label: "Liniowy",            value: "liniowy" },
                          { label: "Obszarowy",          value: "obszarowy" },
                          { label: "Kołowy",             value: "kołowy" },
                          { label: "Tabela",             value: "tabela" },
                          { label: "Poziomy słupkowy",   value: "poziomy słupkowy" },
                          { label: "Punktowy",           value: "punktowy" },
                          { label: "Lejkowy",            value: "lejkowy" },
                          { label: "Kaskadowy",          value: "kaskadowy" },
                          { label: "Licznik",            value: "licznik" },
                          { label: "Kombinowany",        value: "kombinowany" },
                        ].map(({ label, value }) => {
                          const idx = selectedTypes.indexOf(value);
                          const isSelected = idx !== -1;
                          return (
                            <button key={value} type="button"
                              onClick={() => setSelectedTypes(prev =>
                                isSelected ? prev.filter(t => t !== value) : [...prev, value]
                              )}
                              className={`px-3 py-1.5 rounded-full text-xs font-medium border transition ${
                                isSelected
                                  ? "bg-blue-600 text-white border-blue-600"
                                  : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"
                              }`}>
                              {isSelected ? `${idx + 1}. ` : ""}{label}
                            </button>
                          );
                        })}
                        {selectedTypes.length > 0 && (
                          <button type="button" onClick={() => setSelectedTypes([])}
                            className="px-3 py-1.5 rounded-full text-xs text-gray-400 border border-dashed border-gray-300 hover:text-red-500 hover:border-red-300 transition">
                            Wyczyść
                          </button>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Prawa kolumna — opis AI */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide">
                        Opis bazy danych
                      </label>
                      {isGeneratingDesc ? (
                        <span className="text-xs text-blue-500 flex items-center gap-1">
                          <svg className="animate-spin w-3 h-3" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                          </svg>
                          AI generuje...
                        </span>
                      ) : (
                        <button type="button"
                          onClick={() => {
                            const db = databases.find(d => d.id == selectedDbId);
                            if (db) generateDescription(db);
                          }}
                          disabled={!selectedDbId || databases.length === 0}
                          className="text-xs text-blue-600 hover:underline disabled:opacity-40 font-medium">
                          {description ? "Odśwież opis AI" : "Generuj opis AI"}
                        </button>
                      )}
                    </div>
                    <textarea rows="9"
                      placeholder={isGeneratingDesc ? "AI analizuje schemat bazy..." : "Wybierz bazę, a AI automatycznie wygeneruje opis. Możesz go edytować."}
                      value={description}
                      onChange={e => setDescription(e.target.value)}
                      disabled={isGeneratingDesc}
                      className={`w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none h-full
                        ${isGeneratingDesc ? "bg-gray-50 text-gray-400 border-gray-200" : "border-gray-200 bg-white"}`} />
                  </div>
                </div>

                {/* Przycisk */}
                <div className="mt-4">
                  <button onClick={handleGenerate}
                    disabled={loading || !goal || databases.length === 0}
                    className="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white font-semibold px-8 py-2.5 rounded-lg transition text-sm">
                    {loading ? "Generowanie dashboardu..." : "Generuj Dashboard"}
                  </button>
                  {loading && (
                    <span className="ml-3 text-sm text-gray-500">
                      AI planuje wykresy i generuje SQL — może potrwać 30-60 sekund...
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Wyniki — zajmują resztę ekranu */}
            {result && (
              <div className="flex-1 flex flex-col min-h-0 p-4">
                {result.status === "success" ? (
                  <>
                    {/* Pasek statusu */}
                    <div className="flex items-center justify-between mb-3 max-w-full">
                      <div className="flex items-center gap-2">
                        <span className="inline-block w-2 h-2 rounded-full bg-green-500"></span>
                        <span className="text-sm font-medium text-gray-700">
                          Dashboard wygenerowany
                          {result.retry_count > 0 && (
                            <span className="text-gray-400 font-normal"> · {result.retry_count} auto-korekta SQL</span>
                          )}
                        </span>
                      </div>
                      <div className="flex items-center gap-3">
                        <a href={result.metabase?.url} target="_blank" rel="noopener noreferrer"
                          className="text-xs bg-blue-600 hover:bg-blue-700 text-white font-semibold px-3 py-1.5 rounded-lg transition">
                          Otwórz w Metabase ↗
                        </a>
                        <button onClick={() => setShowSql(v => !v)}
                          className="text-xs text-blue-600 hover:underline">
                          {showSql ? "Ukryj SQL" : "Pokaż SQL"}
                        </button>
                      </div>
                    </div>

                    {/* SQL (zwinięty domyślnie) */}
                    {showSql && (
                      <pre className="bg-slate-900 text-green-400 p-4 rounded-xl text-xs mb-3 overflow-x-auto max-h-48 overflow-y-auto">
                        {result.sql}
                      </pre>
                    )}

                    {/* Iframe — wypełnia resztę ekranu */}
                    <div className="flex-1 min-h-0 rounded-xl overflow-hidden border border-gray-200 shadow-sm bg-white">
                      <iframe
                        src={result.metabase?.url}
                        className="w-full h-full"
                        frameBorder="0"
                        allowTransparency="true"
                      />
                    </div>
                  </>
                ) : (
                  <div className="bg-red-50 border border-red-200 rounded-xl p-5 text-red-700 max-w-2xl">
                    <p className="font-bold mb-1">Błąd generowania</p>
                    <p className="text-sm">{result.error}</p>
                  </div>
                )}
              </div>
            )}

            {/* Placeholder gdy brak wyników */}
            {!result && !loading && (
              <div className="flex-1 flex items-center justify-center text-gray-300">
                <div className="text-center">
                  <svg className="w-16 h-16 mx-auto mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                  </svg>
                  <p className="text-sm">Wpisz cel analityczny i kliknij Generuj</p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── BAZY DANYCH ──────────────────────────────────────────────────── */}
        {activeTab === "bazy" && (
          <div className="p-8 max-w-3xl mx-auto">
            <h2 className="text-xl font-bold text-gray-900 mb-6">Bazy danych</h2>

            <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
              <h3 className="text-sm font-semibold text-gray-700 mb-3">Wgraj nową bazę SQLite (.db)</h3>
              <form onSubmit={handleFileUpload} className="flex gap-3 items-center">
                <input type="file" accept=".db,.sqlite,.sqlite3,.csv,.xlsx,.xls" onChange={e => setUploadFile(e.target.files[0])}
                  className="border border-gray-200 rounded-lg p-2 text-sm w-full bg-gray-50" />
                <button type="submit" disabled={isUploading}
                  className="shrink-0 bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-lg text-sm font-semibold disabled:opacity-40 transition">
                  {isUploading ? "Wgrywanie..." : "Wgraj"}
                </button>
              </form>
            </div>

            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h3 className="text-sm font-semibold text-gray-700 mb-3">Zarejestrowane bazy</h3>
              {databases.length === 0
                ? <p className="text-sm text-gray-400">Brak wgranych baz danych.</p>
                : (
                  <ul className="space-y-2">
                    {databases.map(db => (
                      <li key={db.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border border-gray-100">
                        <div>
                          <p className="text-sm font-semibold text-gray-800">{db.name}</p>
                          <p className="text-xs text-gray-400 mt-0.5">{db.file_path}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs bg-slate-200 text-slate-600 px-2 py-1 rounded font-mono">ID {db.id}</span>
                          <button onClick={() => handleDeleteDb(db.id, db.name)}
                            className="text-xs text-red-400 hover:text-red-600 hover:bg-red-50 px-2 py-1 rounded transition">
                            Usuń
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
            </div>
          </div>
        )}

        {/* ── HISTORIA ─────────────────────────────────────────────────────── */}
        {activeTab === "historia" && (
          <div className="p-8 max-w-3xl mx-auto">
            <h2 className="text-xl font-bold text-gray-900 mb-6">Historia zapytań</h2>
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              {history.length === 0
                ? <p className="text-sm text-gray-400">Brak historii zapytań.</p>
                : (
                  <div className="space-y-4">
                    {history.map(item => (
                      <div key={item.id} className="border border-gray-100 rounded-xl p-4">
                        <div className="flex justify-between items-start mb-2">
                          <p className="text-sm font-semibold text-gray-800 whitespace-pre-line">{item.prompt}</p>
                          <span className={`text-xs px-2 py-0.5 rounded-full font-bold ml-3 shrink-0
                            ${item.status === "success" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                            {item.status.toUpperCase()}
                          </span>
                        </div>
                        {(() => {
                          try {
                            const d = JSON.parse(item.sql || "{}");
                            if (d.dashboard_url) return (
                              <a href={d.dashboard_url} target="_blank" rel="noopener noreferrer"
                                className="inline-block mb-2 text-xs text-blue-600 hover:underline font-medium">
                                Otwórz dashboard →
                              </a>
                            );
                          } catch {}
                          return null;
                        })()}
                        <pre className="bg-gray-50 border border-gray-100 rounded-lg p-3 text-xs text-gray-500 overflow-x-auto whitespace-pre-wrap max-h-32">
                          {item.sql || "Brak SQL"}
                        </pre>
                        <p className="text-xs text-gray-400 mt-2 text-right">
                          Auto-korekty: {item.retry_count} · ID: {item.id}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
