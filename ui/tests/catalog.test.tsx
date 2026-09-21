// Integration test for catalog (feature 007, T032).
// Renders the SQL editor and verifies save flow (quickstart Scenario 4).
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SqlEditor } from "../src/features/catalog/SqlEditor";

vi.mock("../src/app/auth", () => ({
  useAuth: () => ({
    api: {
      createSavedQuery: () => Promise.resolve({ query_id: "q1" }),
    },
  }),
}));

describe("SqlEditor", () => {
  it("saves a query", async () => {
    render(<SqlEditor />);
    fireEvent.change(screen.getByPlaceholderText("Query name"), { target: { value: "revenue" } });
    fireEvent.click(screen.getByText("Save"));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });
});