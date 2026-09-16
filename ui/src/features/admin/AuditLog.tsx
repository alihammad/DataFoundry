// Audit log search UI (feature 007, T046).
// Search by time, identity, resource, action (FR-014); every admin action
// appears with actor/timestamp/before-after (FR-015, US6-AC3).

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "../../app/auth";

export function AuditLog() {
  const { api } = useAuth();
  const [action, setAction] = useState("");
  const [identity, setIdentity] = useState("");
  const entries = useQuery({
    queryKey: ["audit-log", action, identity],
    queryFn: () => api.searchAuditLog({ action, identity }),
  });

  return (
    <div className="panel">
      <h2>Audit Log</h2>
      <div>
        <input value={action} onChange={(e) => setAction(e.target.value)} placeholder="Action" />
        <input value={identity} onChange={(e) => setIdentity(e.target.value)} placeholder="Identity" />
      </div>
      <table>
        <thead>
          <tr>
            <th>Actor</th>
            <th>Action</th>
            <th>Timestamp</th>
          </tr>
        </thead>
        <tbody>
          {(entries.data?.items ?? []).map((e) => (
            <tr key={e.id}>
              <td>{e.actor_identity}</td>
              <td>{e.action}</td>
              <td>{e.created_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}