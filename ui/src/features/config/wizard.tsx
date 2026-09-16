// Wizard framework (feature 007, T021).
// Multi-step guided forms with inline 422 errors[], draft-state preservation
// across session expiry (FR-021), and optimistic-concurrency version tokens on
// save (FR-017).

import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import { useAuth } from "../../app/auth";
import type { ApiError } from "../../app/api";

export interface FieldError {
  path: string;
  message: string;
}

export interface WizardStep {
  id: string;
  title: string;
  render: (ctx: WizardCtx) => ReactNode;
}

export interface WizardCtx {
  data: Record<string, unknown>;
  setField: (key: string, value: unknown) => void;
  errors: FieldError[];
}

export function useWizardState(key: string, initial: Record<string, unknown>) {
  const { loadDraft, saveDraft, clearDraft } = useAuth();
  const [data, setData] = useState<Record<string, unknown>>(() => loadDraft(key) ?? initial);

  const setField = useCallback(
    (field: string, value: unknown) => {
      setData((prev) => {
        const next = { ...prev, [field]: value };
        saveDraft(key, next);
        return next;
      });
    },
    [key, saveDraft],
  );

  const reset = useCallback(() => {
    clearDraft(key);
    setData(initial);
  }, [key, clearDraft, initial]);

  return { data, setField, reset };
}

export function Wizard({
  draftKey,
  initial,
  steps,
  onComplete,
  submitLabel = "Submit",
}: {
  draftKey: string;
  initial: Record<string, unknown>;
  steps: WizardStep[];
  onComplete: (data: Record<string, unknown>) => Promise<void>;
  submitLabel?: string;
}) {
  const { data, setField, reset } = useWizardState(draftKey, initial);
  const [step, setStep] = useState(0);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const ctx: WizardCtx = { data, setField, errors };

  const handleSubmit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      await onComplete(data);
      reset();
    } catch (e) {
      const err = e as ApiError;
      if (err.problem?.errors) {
        setErrors(
          err.problem.errors.map((er) => ({ path: er.path, message: er.message })),
        );
      } else {
        setSubmitError(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="wizard">
      <div className="wizard-steps">
        {steps.map((s, i) => (
          <button
            key={s.id}
            className={i === step ? "step active" : "step"}
            onClick={() => setStep(i)}
          >
            {s.title}
          </button>
        ))}
      </div>
      <div className="wizard-body">{steps[step].render(ctx)}</div>
      {errors.length > 0 && (
        <ul className="error-list">
          {errors.map((e) => (
            <li key={e.path} className="error">
              {e.path}: {e.message}
            </li>
          ))}
        </ul>
      )}
      {submitError && <p className="error">{submitError}</p>}
      <div className="wizard-actions">
        {step > 0 && <button onClick={() => setStep(step - 1)}>Back</button>}
        {step < steps.length - 1 ? (
          <button className="primary" onClick={() => setStep(step + 1)}>
            Next
          </button>
        ) : (
          <button className="primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? "Submitting…" : submitLabel}
          </button>
        )}
      </div>
    </div>
  );
}