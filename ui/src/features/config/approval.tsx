// Approval-aware save flow (feature 007, T025).
// Changes requiring approval show pending state and take effect only after
// approval (US2-AC2); UI-made changes are indistinguishable in governance
// terms from code-made changes (US2-AC4, SC-004).

import { useState } from "react";
import { useAuth } from "../../app/auth";

export function ApprovalStatus({ approvalId }: { approvalId: string | null }) {
  if (!approvalId) return null;
  return (
    <p className="panel">
      <strong>Pending approval</strong> — this change takes effect only after an approver approves it.
      <span> Approval ref: {approvalId}</span>
    </p>
  );
}

export function useApproval() {
  const { api } = useAuth();
  const [pending, setPending] = useState<string | null>(null);

  const submitForApproval = async (payload: unknown) => {
    // MVP: submit the change through the governed workflow; the backend
    // returns a pending approval reference when approval is required.
    const resp = await api.client.post("/ui/approvals", payload);
    const approvalId = (resp as { approval_id?: string }).approval_id ?? null;
    setPending(approvalId);
    return approvalId;
  };

  return { pending, submitForApproval };
}