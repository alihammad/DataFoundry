// Pipelines feature (feature 007, US3).
import { useState } from "react";
import { PipelineList } from "./PipelineList";
import { Quarantine } from "./Quarantine";

export function Pipelines({ platformId }: { platformId: string }) {
  const [datasetId, setDatasetId] = useState("");
  return (
    <div>
      <h1>Pipelines</h1>
      <p>Selected platform: {platformId || "all"}</p>
      <PipelineList platformId={platformId} />
      <label>
        Dataset ID (for quarantine)
        <input value={datasetId} onChange={(e) => setDatasetId(e.target.value)} />
      </label>
      <Quarantine datasetId={datasetId} />
    </div>
  );
}