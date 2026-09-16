// Unit tests for the API client problem+json parsing (feature 007, T013).
import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "../src/app/api";

describe("ApiClient", () => {
  it("parses 422 problem+json with errors array", async () => {
    const client = new ApiClient("/api/v1", { token: null, provider: null });
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          type: "https://datafoundry.example/errors/validation",
          title: "Validation error",
          status: 422,
          errors: [{ path: "name", code: "required", message: "name is required" }],
        }),
        { status: 422, headers: { "Content-Type": "application/problem+json" } },
      ),
    ) as unknown as typeof fetch;

    try {
      await client.post("/ui/saved-queries", {});
      expect.fail("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const err = e as ApiError;
      expect(err.problem.status).toBe(422);
      expect(err.problem.errors?.[0].path).toBe("name");
    }
  });

  it("parses 403 problem+json with missing permissions", async () => {
    const client = new ApiClient("/api/v1", { token: null, provider: null });
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          type: "https://datafoundry.example/errors/insufficient_permissions",
          title: "Forbidden",
          status: 403,
          missing: ["platform.create"],
        }),
        { status: 403, headers: { "Content-Type": "application/problem+json" } },
      ),
    ) as unknown as typeof fetch;

    try {
      await client.get("/platforms");
      expect.fail("should have thrown");
    } catch (e) {
      const err = e as ApiError;
      expect(err.problem.missing).toContain("platform.create");
    }
  });

  it("attaches bearer token and provider header in cloud_iam mode", async () => {
    const client = new ApiClient("/api/v1", { token: "tok123", provider: "aws" });
    const mock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), { status: 200 }),
    );
    globalThis.fetch = mock as unknown as typeof fetch;

    await client.get("/platforms");
    const [, init] = mock.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer tok123");
    expect(headers["x-datafoundry-provider"]).toBe("aws");
  });
});