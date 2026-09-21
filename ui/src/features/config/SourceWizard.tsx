// Data source wizard (feature 007, T023).
// Consumes the feature 002 ingestion config API; validates + version-controls
// + makes deployable without manual file editing (US2-AC1).

import { useAuth } from "../../app/auth";
import { Wizard } from "./wizard";

export function SourceWizard() {
  const { api } = useAuth();
  const steps = [
    {
      id: "source",
      title: "Source",
      render: ({ data, setField }: { data: Record<string, unknown>; setField: (k: string, v: unknown) => void }) => (
        <div>
          <label>
            Source type
            <select value={(data.source_type as string) || "postgres"} onChange={(e) => setField("source_type", e.target.value)}>
              <option value="postgres">PostgreSQL</option>
              <option value="sqlserver">SQL Server</option>
              <option value="csv">CSV</option>
              <option value="s3">S3/GCS files</option>
            </select>
          </label>
          <label>
            Name
            <input value={(data.name as string) || ""} onChange={(e) => setField("name", e.target.value)} />
          </label>
          <label>
            Connection string
            <input value={(data.connection_string as string) || ""} onChange={(e) => setField("connection_string", e.target.value)} />
          </label>
        </div>
      ),
    },
    {
      id: "schedule",
      title: "Schedule",
      render: ({ data, setField }: { data: Record<string, unknown>; setField: (k: string, v: unknown) => void }) => (
        <div>
          <label>
            Schedule (cron)
            <input value={(data.schedule as string) || "0 * * * *"} onChange={(e) => setField("schedule", e.target.value)} />
          </label>
        </div>
      ),
    },
  ];

  return (
    <Wizard
      draftKey="source-wizard"
      initial={{ source_type: "postgres", schedule: "0 * * * *" }}
      steps={steps}
      onComplete={async (data) => {
        // Feature 002 ingestion config API (documented contract).
        await api.client.post("/ingestion/configs", data);
      }}
      submitLabel="Create data source"
    />
  );
}