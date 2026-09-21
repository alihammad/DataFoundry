// Admin feature (feature 007, US6).
import { useState } from "react";
import { Roles } from "./Roles";
import { Approvals } from "./Approvals";
import { Notifications } from "./Notifications";
import { AuditLog } from "./AuditLog";

const TABS = [
  { id: "roles", label: "Roles", component: Roles },
  { id: "approvals", label: "Approvals", component: Approvals },
  { id: "notifications", label: "Notifications", component: Notifications },
  { id: "audit", label: "Audit Log", component: AuditLog },
];

export function Admin() {
  const [tab, setTab] = useState("roles");
  const Active = TABS.find((t) => t.id === tab)?.component ?? Roles;
  return (
    <div>
      <h1>Administration</h1>
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