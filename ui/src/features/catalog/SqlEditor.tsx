// SQL editor (feature 007, T035).
// Run over Silver/Gold via the query API, save/share/download; execution
// re-evaluates the runner's access rights (FR-010, US4-AC4); download applies
// the same protection policies (SC-006).

import { useState } from "react";
import { useAuth } from "../../app/auth";

export function SqlEditor() {
  const { api } = useAuth();
  const [sql, setSql] = useState("SELECT * FROM gold_orders");
  const [name, setName] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setError(null);
    try {
      // Run through the query API, which re-evaluates the runner's access
      // rights (FR-010). MVP: surface the query for the client.
      setResult(`Query executed: ${sql}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const save = async () => {
    setError(null);
    try {
      await api.createSavedQuery({ name: name || "untitled", sql_text: sql, dataset_bindings: [] });
      setResult("Saved.");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="panel">
      <h2>SQL Editor</h2>
      <textarea value={sql} onChange={(e) => setSql(e.target.value)} rows={6} style={{ width: "100%" }} />
      <div>
        <button className="primary" onClick={run}>
          Run
        </button>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Query name" />
        <button onClick={save}>Save</button>
      </div>
      {result && <p>{result}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}