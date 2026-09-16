// Approvals UI (feature 007, T044).
// Pending requests (production changes, overrides, semantic publications,
// contracts) visible to approvers with approve/deny + recorded reasoning
// (FR-016, US6-AC2).

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "../../app/auth";

export function Approvals() {
  const { api } = useAuth();
  const [reasoning, setReasoning] = useState("");
  const approvals = useQuery({ queryKey: ["approvals"], queryFn: () => api.listApprovals() });
  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: string }) =>
      api.decideApproval(id, { decision, reasoning }),
  });

  return (
    <div className="panel">
      <h2>Pending Approvals</h2>
      <table>
        <thead>
          <tr>
            <th>Type</th>
            <th>Requester</th>
            <th>State</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody>
          {(approvals.data?.items ?? []).map((a) => (
            <tr key={a.approval_id}>
              <td>{a.approval_type}</td>
              <td>{a.requester}</td>
              <td>{a.decision_state}</td>
              <td>
                <input value={reasoning} onChange={(e) => setReasoning(e.target.value)} placeholder="Reasoning" />
                <button className="primary" onClick={() => decide.mutate({ id: a.approval_id, decision: "approved" })}>
                  Approve
                </button>
                <button onClick={() => decide.mutate({ id: a.approval_id, decision: "denied" })}>Deny</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {decide.error && <p className="error">{decide.error.message}</p>}
    </div>
  );
}