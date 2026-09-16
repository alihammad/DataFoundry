// Run detail view (feature 007, T029).
// Ordered step progress, logs, failure details, retry/rollback actions; retry
// links to original run (US3-AC2).

import { useMutation, useQuery } from "@tanstack/react-query";
import { useAuth } from "../../app/auth";

export function RunDetail({ runId }: { runId: string }) {
  const { api } = useAuth();
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId),
    enabled: Boolean(runId),
  });
  const retry = useMutation({ mutationFn: () => api.retryRun(runId) });
  const rollback = useMutation({ mutationFn: () => api.rollbackRun(runId) });

  if (!runId) return <p>Select a run to view details.</p>;
  if (run.isLoading) return <p>Loading…</p>;
  if (run.error) return <p className="error">{run.error.message}</p>;

  const r = run.data!;
  return (
    <div className="panel">
      <h2>Run {r.run_id.slice(0, 8)}</h2>
      <p>
        Status: <span className={`status-${r.status}`}>{r.status}</span> · Type: {r.run_type} ·
        Initiated by: {r.initiated_by}
      </p>
      {r.status === "failed" && (
        <div>
          <button className="primary" onClick={() => retry.mutate()}>
            Retry
          </button>
          <button onClick={() => rollback.mutate()}>Rollback</button>
        </div>
      )}
      {retry.error && <p className="error">{retry.error.message}</p>}
      {rollback.error && <p className="error">{rollback.error.message}</p>}
    </div>
  );
}