// Saved-query + share UI (feature 007, T036).
// List/save/share/run saved queries via the UI-owned API (ui-api.md §2).

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "../../app/auth";

export function SavedQueries() {
  const { api } = useAuth();
  const [shareTarget, setShareTarget] = useState("");
  const [shareError, setShareError] = useState<string | null>(null);
  const queries = useQuery({ queryKey: ["saved-queries"], queryFn: () => api.listSavedQueries() });

  const share = async (queryId: string) => {
    setShareError(null);
    try {
      await api.shareSavedQuery(queryId, { shared_with_identity: shareTarget });
      setShareTarget("");
    } catch (e) {
      setShareError((e as Error).message);
    }
  };

  return (
    <div className="panel">
      <h2>Saved Queries</h2>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Owner</th>
            <th>Sharing</th>
            <th>Share with</th>
          </tr>
        </thead>
        <tbody>
          {(queries.data?.items ?? []).map((q) => (
            <tr key={q.query_id}>
              <td>{q.name}</td>
              <td>{q.owner_identity}</td>
              <td>{q.sharing}</td>
              <td>
                <input value={shareTarget} onChange={(e) => setShareTarget(e.target.value)} placeholder="user@example.com" />
                <button onClick={() => share(q.query_id)}>Share</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {shareError && <p className="error">{shareError}</p>}
    </div>
  );
}