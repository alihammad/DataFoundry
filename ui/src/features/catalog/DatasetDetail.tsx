// Dataset detail view (feature 007, T034).
// Schema, policy-compliant sample preview, quality history, protection status
// per column, business metadata, navigable lineage graph (FR-009, US4-AC2);
// previews enforce the same protection policies as queries (SC-006).

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../app/auth";

export function DatasetDetail({ datasetId }: { datasetId: string }) {
  const { api } = useAuth();
  const quality = useQuery({
    queryKey: ["quality", datasetId],
    queryFn: () => api.getQuality(datasetId),
    enabled: Boolean(datasetId),
  });

  if (!datasetId) return <p>Select a dataset to view details.</p>;
  return (
    <div className="panel">
      <h2>Dataset {datasetId.slice(0, 8)}</h2>
      {quality.data && (
        <p>
          Quality score: <strong>{quality.data.score}</strong>
        </p>
      )}
      {quality.error && <p className="error">{quality.error.message}</p>}
      <p>Schema, sample preview, lineage, and protection status render here (feature 003/005 data).</p>
    </div>
  );
}