// Integration test for pipelines (feature 007, T027).
// Renders the pipeline list with mocked API data and verifies retry action
// (quickstart Scenario 3).
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PipelineList } from "../src/features/pipelines/PipelineList";

vi.mock("../src/app/auth", () => ({
  useAuth: () => ({
    api: {
      listRuns: () =>
        Promise.resolve({
          items: [
            { run_id: "11111111-1111-1111-1111-111111111111", status: "failed", run_type: "deploy", initiated_by: "dev" },
            { run_id: "22222222-2222-2222-2222-222222222222", status: "succeeded", run_type: "deploy", initiated_by: "dev" },
          ],
        }),
      retryRun: () => Promise.resolve({ run_id: "x" }),
    },
  }),
}));

function renderList() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PipelineList platformId="p1" />
    </QueryClientProvider>,
  );
}

describe("PipelineList", () => {
  it("renders runs with status and retry for failed runs", async () => {
    renderList();
    expect(await screen.findByText("failed")).toBeInTheDocument();
    expect(screen.getByText("succeeded")).toBeInTheDocument();
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });
});