// Dashboard view (feature 007, US1, T017).
import { useDashboard } from "./useDashboard";
import { Link } from "react-router-dom";

export function Dashboard({ platformId }: { platformId: string }) {
  const state = useDashboard(platformId);
  return (
    <div>
      <h1>Platform Dashboard</h1>
      {state.error && <p className="error">{state.error}</p>}
      <div className="tile-grid">
        <Link className="tile" to="/pipelines">
          <h3>Pipelines</h3>
          <div className="value">{state.pipelineCounts}</div>
        </Link>
        <Link className="tile" to="/quality">
          <h3>Quality Score</h3>
          <div className="value">{state.qualityScore ?? "—"}</div>
        </Link>
        <Link className="tile" to="/pipelines">
          <h3>Storage Utilisation</h3>
          <div className="value">{state.storageUtilisation ?? "—"}</div>
        </Link>
        <Link className="tile" to="/pipelines">
          <h3>Recent Failures</h3>
          <div className="value">{state.recentFailures}</div>
        </Link>
      </div>
      {state.stale && <p className="stale">Showing last-known values (stale)</p>}
    </div>
  );
}