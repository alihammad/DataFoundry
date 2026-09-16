// Platform creation wizard (feature 007, T022).
// Consumes POST /platforms + GET /capabilities + GET /providers/{p}/regions
// (feature 001); surfaces 202 run + polls GET /runs/{id}.

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../app/auth";
import { Wizard } from "./wizard";

export function PlatformWizard() {
  const { api } = useAuth();
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: () => api.listCapabilities() });
  const regions = useQuery({
    queryKey: ["regions", "aws"],
    queryFn: () => api.listRegions("aws"),
  });

  const steps = [
    {
      id: "identity",
      title: "Identity",
      render: ({ data, setField }: { data: Record<string, unknown>; setField: (k: string, v: unknown) => void }) => (
        <div>
          <label>
            Name
            <input value={(data.name as string) || ""} onChange={(e) => setField("name", e.target.value)} />
          </label>
          <label>
            Provider
            <select value={(data.provider as string) || "aws"} onChange={(e) => setField("provider", e.target.value)}>
              <option value="aws">AWS</option>
              <option value="gcp">GCP</option>
            </select>
          </label>
          <label>
            Region
            <select value={(data.region as string) || ""} onChange={(e) => setField("region", e.target.value)}>
              <option value="">Select region</option>
              {(regions.data ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.id}
                </option>
              ))}
            </select>
          </label>
          <label>
            Environment
            <select
              value={(data.environment_type as string) || "development"}
              onChange={(e) => setField("environment_type", e.target.value)}
            >
              <option value="development">Development</option>
              <option value="test">Test</option>
              <option value="uat">UAT</option>
              <option value="production">Production</option>
            </select>
          </label>
        </div>
      ),
    },
    {
      id: "capabilities",
      title: "Capabilities",
      render: ({ data, setField }: { data: Record<string, unknown>; setField: (k: string, v: unknown) => void }) => (
        <div>
          {(capabilities.data ?? []).map((c) => (
            <label key={c.key}>
              <input
                type="checkbox"
                checked={((data.capabilities_enabled as string[]) || []).includes(c.key)}
                onChange={(e) => {
                  const cur = (data.capabilities_enabled as string[]) || [];
                  const next = e.target.checked ? [...cur, c.key] : cur.filter((k) => k !== c.key);
                  setField("capabilities_enabled", next);
                }}
              />
              {c.display_name}
            </label>
          ))}
        </div>
      ),
    },
  ];

  return (
    <Wizard
      draftKey="platform-wizard"
      initial={{ provider: "aws", environment_type: "development", capabilities_enabled: [] }}
      steps={steps}
      onComplete={async (data) => {
        await api.createPlatform({ config: data });
      }}
      submitLabel="Deploy platform"
    />
  );
}