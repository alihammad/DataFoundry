// Playwright E2E for the dashboard (feature 007, T048).
// Requires a running control plane in dev auth mode (quickstart Scenario 1).
import { test, expect } from "@playwright/test";

test("dashboard renders and navigates", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Platform Dashboard" })).toBeVisible();
  await expect(page.getByText("Pipelines")).toBeVisible();
  await expect(page.getByText("Quality Score")).toBeVisible();
  await page.getByText("Pipelines").click();
  await expect(page.getByRole("heading", { name: "Pipelines" })).toBeVisible();
});