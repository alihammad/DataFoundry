// Catalog feature (feature 007, US4).
import { useState } from "react";
import { CatalogSearch } from "./CatalogSearch";
import { DatasetDetail } from "./DatasetDetail";
import { SqlEditor } from "./SqlEditor";
import { SavedQueries } from "./SavedQueries";

export function Catalog() {
  const [datasetId, setDatasetId] = useState("");
  return (
    <div>
      <h1>Catalog</h1>
      <CatalogSearch />
      <label>
        Dataset ID
        <input value={datasetId} onChange={(e) => setDatasetId(e.target.value)} />
      </label>
      <DatasetDetail datasetId={datasetId} />
      <SqlEditor />
      <SavedQueries />
    </div>
  );
}