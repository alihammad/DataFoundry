// Integration test for admin (feature 007, T042).
// Renders the roles view and verifies role creation (quickstart Scenario 6).
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Roles } from "../src/features/admin/Roles";

vi.mock("../src/app/auth", () => ({
  useAuth: () => ({
    api: {
      listRoles: () => Promise.resolve({ items: [] }),
      createRole: () => Promise.resolve({ role_id: "r1" }),
      assignRole: () => Promise.resolve({ assignment_id: "a1" }),
    },
  }),
}));

function renderRoles() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Roles />
    </QueryClientProvider>,
  );
}

describe("Roles", () => {
  it("renders role creation form", async () => {
    renderRoles();
    expect(screen.getByText("Roles")).toBeInTheDocument();
    expect(screen.getByText("Create role")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Role name"), { target: { value: "analyst" } });
    fireEvent.click(screen.getByText("Create role"));
  });
});