// Integration test for quality (feature 007, T038).
// Renders the quality view and verifies score display (quickstart Scenario 5).
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { QualityViews } from "../src/features/quality/QualityViews";

vi.mock("../src/app/auth", () => ({
  useAuth: () => ({
    api: {
      getQuality: () => Promise.resolve({ score: 85, window_start: "2026-01-01", window_end: "2026-01-31" }),
      getQualityHistory: () => Promise.resolve({ items: [] }),
    },
  }),
}));

function renderQuality() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <QualityViews />
    </QueryClientProvider>,
  );
}

describe("QualityViews", () => {
  it("renders quality score for a dataset", async () => {
    renderQuality();
    fireEvent.change(screen.getByLabelText("Dataset ID"), { target: { value: "d1" } });
    expect(await screen.findByText("85")).toBeInTheDocument();
  });
});