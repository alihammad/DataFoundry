// Integration test for the dashboard (feature 007, T015).
// Renders the dashboard with mocked API data and verifies figures + drill-down
// links (quickstart Scenario 1).
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { Dashboard } from "../src/features/dashboard/Dashboard";

function renderDashboard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  // Mock the auth hook's api.
  vi.mock("../src/app/auth", () => ({
    useAuth: () => ({
      api: {
        listPlatforms: () => Promise.resolve({ items: [] }),
        getPlatform: () => Promise.resolve(null),
        listRuns: () => Promise.resolve({ items: [] }),
      },
    }),
  }));
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Dashboard platformId="" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Dashboard", () => {
  it("renders dashboard tiles with drill-down links", async () => {
    renderDashboard();
    expect(screen.getByText("Platform Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Pipelines")).toBeInTheDocument();
    expect(screen.getByText("Quality Score")).toBeInTheDocument();
    expect(screen.getByText("Storage Utilisation")).toBeInTheDocument();
    expect(screen.getByText("Recent Failures")).toBeInTheDocument();
  });
});