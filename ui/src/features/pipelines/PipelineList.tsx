// Pipeline list view (feature 007, T028).
// State, trigger/pause/resume/retry actions, execution history, logs, metrics,
// failure details (FR-006).

import { useMutation, useQuery } from "@tanstack/react-query";
import { useAuth } from "../../app/auth";

export function PipelineList({ platformId }: { platformId: string }) {
  const { api } = useAuth();
  const runs = useQuery({
    queryKey: ["runs", platformId],
    queryFn: () => api.listRuns(platformId),
    enabled: Boolean(platformId),
  });

  const retry = useMutation({
    mutationFn: (runId: string) => api.retryRun(runId),
  });

  return (
    <div className="panel">
      <h2>Pipelines</h2>
      {!platformId && <p>Select a platform to view pipelines.</p>}
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Status</th>
            <th>Type</th>
            <th>Initiated by</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {(runs.data?.items ?? []).map((run) => (
            <tr key={run.run_id}>
              <td>{run.run_id.slice(0, 8)}</td>
              <td className={`status-${run.status}`}>{run.status}</td>
              <td>{run.run_type}</td>
              <td>{run.initiated_by}</td>
              <td>
                {run.status === "failed" && (
                  <button onClick={() => retry.mutate(run.run_id)}>Retry</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {retry.error && <p className="error">{retry.error.message}</p>}
    </div>
  );
}