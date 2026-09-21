// Config feature (feature 007, US2).
import { useState } from "react";
import { PlatformWizard } from "./PlatformWizard";
import { SourceWizard } from "./SourceWizard";
import { ProtectionWizard } from "./ProtectionWizard";

const TABS = [
  { id: "platform", label: "Platform", component: PlatformWizard },
  { id: "source", label: "Data Source", component: SourceWizard },
  { id: "protection", label: "Protection", component: ProtectionWizard },
];

export function Config({ platformId }: { platformId: string }) {
  const [tab, setTab] = useState("platform");
  const Active = TABS.find((t) => t.id === tab)?.component ?? PlatformWizard;
  return (
    <div>
      <h1>Configure</h1>
      <p>Selected platform: {platformId || "all"}</p>
      <div className="wizard-steps">
        {TABS.map((t) => (
          <button key={t.id} className={t.id === tab ? "step active" : "step"} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <Active />
    </div>
  );
}