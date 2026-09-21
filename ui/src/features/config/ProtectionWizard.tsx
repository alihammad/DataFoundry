// Quality gate + classification wizards (feature 007, T024).
// Consume the feature 004 gate/contract APIs and feature 005
// classification/protection APIs.

import { useAuth } from "../../app/auth";
import { Wizard } from "./wizard";

export function QualityWizard() {
  const { api } = useAuth();
  const steps = [
    {
      id: "gate",
      title: "Gate",
      render: ({ data, setField }: { data: Record<string, unknown>; setField: (k: string, v: unknown) => void }) => (
        <div>
          <label>
            Dataset ID
            <input value={(data.dataset_id as string) || ""} onChange={(e) => setField("dataset_id", e.target.value)} />
          </label>
          <label>
            Transition
            <select value={(data.transition as string) || "bronze_to_silver"} onChange={(e) => setField("transition", e.target.value)}>
              <option value="ingestion_to_bronze">Ingestion → Bronze</option>
              <option value="bronze_to_silver">Bronze → Silver</option>
              <option value="silver_to_gold">Silver → Gold</option>
              <option value="gold_to_consumable">Gold → Consumable</option>
            </select>
          </label>
        </div>
      ),
    },
  ];

  return (
    <Wizard
      draftKey="quality-wizard"
      initial={{ transition: "bronze_to_silver" }}
      steps={steps}
      onComplete={async (data) => {
        await api.client.post(`/datasets/${data.dataset_id}/gates/${data.transition}`, {});
      }}
      submitLabel="Define gate"
    />
  );
}

export function ProtectionWizard() {
  const { api } = useAuth();
  const steps = [
    {
      id: "classification",
      title: "Classification",
      render: ({ data, setField }: { data: Record<string, unknown>; setField: (k: string, v: unknown) => void }) => (
        <div>
          <label>
            Dataset ID
            <input value={(data.dataset_id as string) || ""} onChange={(e) => setField("dataset_id", e.target.value)} />
          </label>
          <label>
            Classification
            <select value={(data.classification as string) || "internal"} onChange={(e) => setField("classification", e.target.value)}>
              <option value="public">Public</option>
              <option value="internal">Internal</option>
              <option value="confidential">Confidential</option>
              <option value="restricted">Restricted</option>
              <option value="highly_restricted">Highly Restricted</option>
            </select>
          </label>
        </div>
      ),
    },
  ];

  return (
    <Wizard
      draftKey="protection-wizard"
      initial={{ classification: "internal" }}
      steps={steps}
      onComplete={async (data) => {
        // Feature 005 classification API (documented contract).
        await api.client.post(`/datasets/${data.dataset_id}/classification`, {
          classification: data.classification,
        });
      }}
      submitLabel="Set classification"
    />
  );
}