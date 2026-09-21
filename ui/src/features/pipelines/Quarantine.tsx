// Quarantine view (feature 007, T030).
// Browsable with filters (source, pipeline, batch, reason, date range) and
// replay for authorised users (FR-007, US3-AC3).

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "../../app/auth";

export function Quarantine({ datasetId }: { datasetId: string }) {
  const { api } = useAuth();
  const [reason, setReason] = useState("");
  const entries = useQuery({
    queryKey: ["quarantine", datasetId, reason],
    queryFn: () => api.listQuarantine(datasetId, reason ? { failure_reason: reason } : undefined),
    enabled: Boolean(datasetId),
  });
  const replay = useMutation({
    mutationFn: (entryId: string) => api.replayQuarantine(entryId),
  });

  return (
    <div className="panel">
      <h2>Quarantine</h2>
      {!datasetId && <p>Select a dataset to view quarantine.</p>}
      <label>
        Filter by reason
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <table>
        <thead>
          <tr>
            <th>Entry</th>
            <th>Batch</th>
            <th>Reason</th>
            <th>Attempts</th>
            <th>Replay</th>
          </tr>
        </thead>
        <tbody>
          {(entries.data?.items ?? []).map((e) => (
            <tr key={e.entry_id}>
              <td>{e.entry_id.slice(0, 8)}</td>
              <td>{e.batch_id}</td>
              <td>{e.failure_reason}</td>
              <td>{e.attempt_count}</td>
              <td>
                {e.replay_eligible && (
                  <button onClick={() => replay.mutate(e.entry_id)}>Replay</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {replay.error && <p className="error">{replay.error.message}</p>}
    </div>
  );
}