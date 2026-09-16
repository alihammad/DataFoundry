// Quality views (feature 007, T039).
// Per-dataset scores/trends, gate run history with test-level and record-level
// drill-down, contract violation feed, anomaly indicators, alert history with
// filters (FR-011).

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "../../app/auth";

export function QualityViews() {
  const { api } = useAuth();
  const [datasetId, setDatasetId] = useState("");
  const quality = useQuery({
    queryKey: ["quality", datasetId],
    queryFn: () => api.getQuality(datasetId),
    enabled: Boolean(datasetId),
  });

  return (
    <div className="panel">
      <h2>Quality</h2>
      <label>
        Dataset ID
        <input value={datasetId} onChange={(e) => setDatasetId(e.target.value)} />
      </label>
      {quality.data && (
        <p>
          Score: <strong>{quality.data.score}</strong> ({quality.data.window_start} → {quality.data.window_end})
        </p>
      )}
      {quality.error && <p className="error">{quality.error.message}</p>}
      <p>Gate run history, contract violations, and alerts render here (feature 004 data).</p>
    </div>
  );
}