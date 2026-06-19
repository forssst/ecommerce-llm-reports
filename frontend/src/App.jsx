import { useState } from 'react';
const API_URL = "http://localhost:8000";
export default function App() {
  const [user, setUser] = useState(null);
  const [email, setEmail] = useState("test@test.pl");
  const [password, setPassword] = useState("");
  const [authMode, setAuthMode] = useState("login"); // "login" | "register"

  const [activeTab, setActiveTab] = useState("kreator");
  const [databases, setDatabases] = useState([]);
  const [selectedDbId, setSelectedDbId] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [history, setHistory] = useState([]);
  // Formularz Kreatora
  const [description, setDescription] = useState("");
  const [goal, setGoal] = useState("");
  const [dashboardPrompt, setDashboardPrompt] = useState("Wygeneruj dashboard zawierający wykresy słupkowe i filtry czasowe.");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

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
        body: JSON.stringify({ email: email, password_hash: password })
      });
      if (!res.ok) {
        alert("Nieprawidłowy e-mail lub hasło.");
        return;
      }
      const data = await res.json();
      enterApp(data);
    } catch (error) {
      alert("Błąd połączenia z serwerem FastAPI.");
    }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    if (!email || !password) return alert("Podaj e-mail i hasło.");
    try {
      const res = await fetch(`${API_URL}/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email, password_hash: password })
      });
      if (res.status === 409) {
        alert("Konto z tym e-mailem już istnieje. Zaloguj się.");
        setAuthMode("login");
        return;
      }
      if (!res.ok) {
        alert("Nie udało się utworzyć konta.");
        return;
      }
      const data = await res.json();
      enterApp(data); // po rejestracji od razu wchodzimy do aplikacji
    } catch (error) {
      alert("Błąd połączenia z serwerem FastAPI.");
    }
  };

  const fetchDatabases = async (userId) => {
    try {
      const res = await fetch(`${API_URL}/users/${userId}/databases`);
      const data = await res.json();
      setDatabases(data);
      if (data.length > 0) setSelectedDbId(data[0].id);
    } catch (error) {
      console.error("Błąd pobierania baz danych:", error);
    }
  };
  const fetchHistory = async (userId) => {
    try {
      const res = await fetch(`${API_URL}/users/${userId}/queries`);
      const data = await res.json();
      setHistory(data);
    } catch (error) {
      console.error("Błąd pobierania historii:", error);
    }
  };
  const handleFileUpload = async (e) => {
    e.preventDefault();
    if (!uploadFile) return alert("Wybierz plik .db");

    setIsUploading(true);
    const formData = new FormData();
    formData.append("user_id", user.id);
    formData.append("file", uploadFile);
    try {
      const res = await fetch(`${API_URL}/upload`, {
        method: "POST",
        body: formData,
      });
      if (res.ok) {
        alert("Baza wgrana pomyślnie.");
        setUploadFile(null);
        fetchDatabases(user.id);
      } else {
        alert("Błąd podczas wgrywania pliku.");
      }
    } catch (error) {
      alert("Błąd komunikacji z serwerem.");
    }
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
    try {
      const res = await fetch(`${API_URL}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.id,
          prompt: goal,
          description: description,
          chart_type: dashboardPrompt, // Przekazujemy to do backendu
          schema_text: schemaText,
          db_path: selectedDb.file_path,
          n8n_url: "http://n8n_local:5678/webhook/sales-report"
        })
      });
      const data = await res.json();
      setResult(data);
      fetchHistory(user.id); // Odśwież historię po wygenerowaniu
    } catch (error) {
      alert("Błąd podczas generowania raportu.");
    }
    setLoading(false);
  };
  if (!user) {
    const isLogin = authMode === "login";
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="p-8 bg-white rounded-xl shadow-lg max-w-sm w-full">
          <h2 className="text-2xl font-bold mb-2 text-gray-800 text-center">Data Analyst System</h2>
          <p className="text-sm text-gray-500 mb-6 text-center">
            {isLogin ? "Zaloguj się na swoje konto" : "Utwórz nowe konto"}
          </p>
          <form onSubmit={isLogin ? handleLogin : handleRegister} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Adres e-mail</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 block w-full px-4 py-2 border border-gray-300 rounded-lg" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Hasło</label>
              <input type="password" placeholder="••••••••" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 block w-full px-4 py-2 border border-gray-300 rounded-lg" />
            </div>
            <button type="submit" className="w-full bg-blue-600 text-white py-2 px-4 rounded-lg hover:bg-blue-700 transition">
              {isLogin ? "Zaloguj się" : "Zarejestruj się"}
            </button>
          </form>
          <p className="text-sm text-gray-500 mt-6 text-center">
            {isLogin ? "Nie masz konta? " : "Masz już konto? "}
            <button
              type="button"
              onClick={() => { setAuthMode(isLogin ? "register" : "login"); setPassword(""); }}
              className="text-blue-600 font-semibold hover:underline"
            >
              {isLogin ? "Zarejestruj się" : "Zaloguj się"}
            </button>
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="flex h-screen bg-gray-100 font-sans">
      <aside className="w-64 bg-slate-900 text-white flex flex-col">
        <div className="p-6 border-b border-slate-800">
          <h1 className="text-xl font-bold">Data Analyst</h1>
          <p className="text-slate-400 text-xs mt-2">{user.email}</p>
        </div>
        <nav className="flex-1 px-4 space-y-2 mt-6">
          <button onClick={() => setActiveTab("kreator")} className={`w-full text-left px-4 py-2 rounded-lg transition ${activeTab === 'kreator' ? 'bg-blue-600 text-white' : 'text-slate-300 hover:bg-slate-800'}`}>Kreator Raportów</button>
          <button onClick={() => setActiveTab("bazy")} className={`w-full text-left px-4 py-2 rounded-lg transition ${activeTab === 'bazy' ? 'bg-blue-600 text-white' : 'text-slate-300 hover:bg-slate-800'}`}>Zarządzanie Bazami</button>
          <button onClick={() => setActiveTab("historia")} className={`w-full text-left px-4 py-2 rounded-lg transition ${activeTab === 'historia' ? 'bg-blue-600 text-white' : 'text-slate-300 hover:bg-slate-800'}`}>Historia Promptów</button>
        </nav>
        <div className="p-4 border-t border-slate-800">
          <button onClick={() => { setUser(null); setPassword(""); }} className="w-full text-sm text-slate-400 hover:text-white transition">Wyloguj się</button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto p-10">
        <div className="max-w-4xl mx-auto">

          {/* ZAKŁADKA: BAZY DANYCH */}
          {activeTab === "bazy" && (
            <div>
              <h2 className="text-3xl font-bold text-gray-800 mb-6">Zarządzanie Bazami Danych</h2>
              <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200 mb-8">
                <h3 className="text-lg font-semibold mb-4 text-gray-800">Wgraj nową bazę SQLite (.db)</h3>
                <form onSubmit={handleFileUpload} className="flex gap-4 items-center">
                  <input type="file" accept=".db" onChange={(e) => setUploadFile(e.target.files[0])} className="border border-gray-300 p-2 rounded-lg w-full text-sm" />
                  <button type="submit" disabled={isUploading} className="bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700 font-semibold disabled:opacity-50 transition">
                    {isUploading ? "Wgrywanie..." : "Wgraj plik"}
                  </button>
                </form>
              </div>
              <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
                <h3 className="text-lg font-semibold mb-4 text-gray-800">Zarejestrowane bazy danych</h3>
                {databases.length === 0 ? (
                  <p className="text-gray-500 text-sm">Brak wgranych baz danych w systemie.</p>
                ) : (
                  <ul className="space-y-3">
                    {databases.map(db => (
                      <li key={db.id} className="p-4 bg-gray-50 border border-gray-100 rounded-lg flex justify-between items-center">
                        <div>
                          <span className="font-semibold text-gray-800">{db.name}</span>
                          <p className="text-xs text-gray-500 mt-1">Ścieżka systemowa: {db.file_path}</p>
                        </div>
                        <span className="bg-slate-200 text-slate-700 text-xs px-3 py-1 rounded-full font-mono">ID: {db.id}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
          {/* ZAKŁADKA: HISTORIA */}
          {activeTab === "historia" && (
            <div>
              <h2 className="text-3xl font-bold text-gray-800 mb-6">Historia Zapytań</h2>
              <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
                {history.length === 0 ? (
                  <p className="text-gray-500 text-sm">Brak zapisanej historii zapytań.</p>
                ) : (
                  <div className="space-y-4">
                    {history.map(item => (
                      <div key={item.id} className="p-4 border border-gray-200 rounded-lg">
                        <div className="flex justify-between items-start mb-2">
                          <p className="font-semibold text-gray-800 whitespace-pre-line">{item.prompt}</p>
                          <span className={`text-xs px-2 py-1 rounded-full font-bold ml-4 shrink-0 ${item.status === 'success' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                            {item.status.toUpperCase()}
                          </span>
                        </div>
                        <div className="bg-slate-50 p-3 rounded border border-slate-100 text-xs font-mono text-slate-600 overflow-x-auto whitespace-pre-wrap">
                          {item.sql || "Brak wygenerowanego kodu SQL"}
                        </div>
                        <div className="text-xs text-gray-400 mt-2 text-right">
                          Liczba prób auto-korekty: {item.retry_count} | ID: {item.id}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
          {/* ZAKŁADKA: KREATOR */}
          {activeTab === "kreator" && (
            <div>
              <h2 className="text-3xl font-bold text-gray-800 mb-2">Kreator Raportów Analitycznych</h2>
              <p className="text-gray-500 mb-8">Zdefiniuj parametry analizy oraz strukturę docelowego dashboardu.</p>

              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 space-y-6">

                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">Wybór źródła danych</label>
                  <select value={selectedDbId} onChange={(e) => setSelectedDbId(e.target.value)} className="w-full border-gray-300 rounded-lg border p-3 bg-gray-50">
                    {databases.length === 0 && <option>Brak dostępnych baz danych</option>}
                    {databases.map(db => (
                      <option key={db.id} value={db.id}>{db.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">Opis kontekstu biznesowego bazy danych</label>
                  <textarea rows="2" placeholder="Opcjonalny opis struktury, np. 'Tabela orders zawiera transakcje klientów...'" value={description} onChange={(e) => setDescription(e.target.value)} className="w-full border-gray-300 rounded-lg border p-3"></textarea>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">Cel analityczny (Prompt)</label>
                  <textarea rows="2" placeholder="Wprowadź zapytanie biznesowe..." value={goal} onChange={(e) => setGoal(e.target.value)} className="w-full border-gray-300 rounded-lg border p-3"></textarea>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">Konfiguracja i układ docelowego Dashboardu</label>
                  <textarea rows="2" placeholder="Np. Stwórz dashboard z wykresem kołowym kategorii oraz tabelą szczegółową, dodaj filtr daty..." value={dashboardPrompt} onChange={(e) => setDashboardPrompt(e.target.value)} className="w-full border-gray-300 rounded-lg border p-3"></textarea>
                </div>
                <div className="pt-2">
                  <button onClick={handleGenerate} disabled={loading || !goal || databases.length === 0} className="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 px-8 rounded-lg disabled:opacity-50 transition">
                    {loading ? "Przetwarzanie zapytania..." : "Generuj Dashboard Analityczny"}
                  </button>
                </div>
              </div>
              {/* Sekcja Wyników */}
              {result && (
                <div className="mt-8 bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                  {result.status === "success" ? (
                    <>
                      <div className="flex justify-between items-center mb-4">
                        <p className="text-sm text-green-700 font-semibold">Generacja zakończona sukcesem (Iteracje: {result.retry_count})</p>
                      </div>
                      <pre className="bg-slate-900 text-green-400 p-4 rounded-lg overflow-x-auto text-sm mb-6">{result.sql}</pre>

                      {result.metabase?.url && (
                        <div className="border border-gray-200 rounded-lg overflow-hidden h-[600px] bg-gray-50">
                          <iframe src={result.metabase.url} width="100%" height="100%" frameBorder="0"></iframe>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="bg-red-50 text-red-700 p-4 rounded-lg border border-red-200">
                      <p className="font-bold">Błąd przetwarzania</p>
                      <p className="text-sm mt-1">{result.error}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
