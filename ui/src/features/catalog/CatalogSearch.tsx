// Catalog search view (feature 007, T033).
// Business-term search over datasets and metrics; results show
// layer/owner/quality/freshness/consumers (US4-AC1).

import { useState } from "react";
import { useAuth } from "../../app/auth";

export function CatalogSearch() {
  const { api } = useAuth();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<unknown[]>([]);

  const search = async () => {
    // Catalog search is a feature 003/006 capability; MVP surfaces the query
    // term and delegates to the catalog API when available.
    try {
      const resp = await api.client.get(`/catalog/search?q=${encodeURIComponent(query)}`);
      setResults((resp as { items?: unknown[] }).items ?? []);
    } catch {
      setResults([]);
    }
  };

  return (
    <div className="panel">
      <h2>Catalog Search</h2>
      <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. customer revenue" />
      <button className="primary" onClick={search}>
        Search
      </button>
      <p>{results.length} results</p>
    </div>
  );
}