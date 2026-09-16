// Typed API client for the control plane (feature 007, T010).
// Base URL from DF_API_PREFIX; bearer-token + provider header in cloud_iam
// mode (R-03); uniform RFC 9457 problem+json parsing.

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  errors?: Array<{ path: string; code: string; message: string; remediation?: string }>;
  missing?: string[];
  code?: string;
}

export class ApiError extends Error {
  problem: Problem;
  constructor(problem: Problem) {
    super(problem.detail || problem.title);
    this.problem = problem;
  }
}

export interface AuthContext {
  token: string | null;
  provider: "aws" | "gcp" | null;
}

export class ApiClient {
  baseUrl: string;
  auth: AuthContext;

  constructor(baseUrl: string, auth: AuthContext) {
    this.baseUrl = baseUrl;
    this.auth = auth;
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (this.auth.token) {
      h["Authorization"] = `Bearer ${this.auth.token}`;
    }
    if (this.auth.provider) {
      h["x-datafoundry-provider"] = this.auth.provider;
    }
    return h;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: this.headers(),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) {
      let problem: Problem;
      try {
        problem = (await res.json()) as Problem;
      } catch {
        problem = { type: "about:blank", title: "HTTP error", status: res.status };
      }
      throw new ApiError(problem);
    }
    if (res.status === 204) {
      return undefined as T;
    }
    return (await res.json()) as T;
  }

  get<T>(path: string): Promise<T> {
    return this.request<T>("GET", path);
  }
  post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("POST", path, body);
  }
  put<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("PUT", path, body);
  }
  delete<T>(path: string): Promise<T> {
    return this.request<T>("DELETE", path);
  }
}

// -- typed wrappers for the features 001-006 endpoints the UI consumes -------

export interface PlatformSummary {
  id: string;
  name: string;
  provider: string;
  region: string;
  environment_type: string;
  status: string;
  owner: string;
}

export interface PlatformDetail extends PlatformSummary {
  storage_utilisation?: number;
  health?: unknown;
  latest_run?: unknown;
  recent_failures?: unknown[];
}

export interface RunSummary {
  run_id: string;
  platform_id: string;
  status: string;
  run_type: string;
  initiated_by: string;
  config_version: number;
  duration_seconds?: number;
}

export interface QualitySummary {
  score: number;
  window_start: string;
  window_end: string;
}

export interface Capability {
  key: string;
  display_name: string;
  selectable: boolean;
  depends_on: string[];
  providers: string[];
}

export interface RegionMatrix {
  id: string;
  capabilities_supported: string[];
}

export interface QuarantineEntry {
  entry_id: string;
  batch_id: string;
  payload_ref: string;
  failure_reason: string;
  failed_test: string;
  attempt_count: number;
  replay_eligible: boolean;
  retention_expiry: string;
}

export interface SavedQuery {
  query_id: string;
  name: string;
  owner_identity: string;
  sharing: string;
  created_at: string;
}

export interface UIRole {
  role_id: string;
  name: string;
  scope: string;
  permissions: string[];
}

export interface ApprovalItem {
  approval_id: string;
  approval_type: string;
  requester: string;
  payload_ref: string;
  decision_state: string;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  actor_identity: string;
  action: string;
  resource: string;
  before_state?: unknown;
  after_state?: unknown;
  created_at: string;
}

export class ControlPlaneApi {
  client: ApiClient;

  constructor(client: ApiClient) {
    this.client = client;
  }

  // platforms (feature 001)
  listPlatforms(): Promise<{ items: PlatformSummary[]; next_cursor?: string }> {
    return this.client.get("/platforms");
  }
  getPlatform(id: string): Promise<PlatformDetail> {
    return this.client.get(`/platforms/${id}`);
  }
  listRuns(platformId: string): Promise<{ items: RunSummary[]; next_cursor?: string }> {
    return this.client.get(`/platforms/${platformId}/runs`);
  }
  getRun(runId: string): Promise<RunSummary> {
    return this.client.get(`/runs/${runId}`);
  }
  retryRun(runId: string): Promise<{ run_id: string }> {
    return this.client.post(`/runs/${runId}/retry`);
  }
  rollbackRun(runId: string): Promise<{ run_id: string }> {
    return this.client.post(`/runs/${runId}/rollback`);
  }
  listCapabilities(): Promise<Capability[]> {
    return this.client.get("/capabilities");
  }
  listRegions(provider: string): Promise<RegionMatrix[]> {
    return this.client.get(`/providers/${provider}/regions`);
  }
  createPlatform(body: unknown): Promise<{ platform_id: string; run_id: string; status: string }> {
    return this.client.post("/platforms", body);
  }
  triggerHealthCheck(platformId: string): Promise<{ check_id: string }> {
    return this.client.post(`/platforms/${platformId}/health-checks`);
  }

  // quality (feature 004)
  getQuality(datasetId: string): Promise<QualitySummary> {
    return this.client.get(`/datasets/${datasetId}/quality`);
  }
  getQualityHistory(datasetId: string): Promise<{ items: unknown[] }> {
    return this.client.get(`/datasets/${datasetId}/quality/history`);
  }
  getReport(reportId: string): Promise<unknown> {
    return this.client.get(`/reports/${reportId}`);
  }
  listQuarantine(datasetId: string, params?: Record<string, string>): Promise<{ items: QuarantineEntry[] }> {
    const qs = new URLSearchParams(params || {}).toString();
    return this.client.get(`/datasets/${datasetId}/quarantine${qs ? `?${qs}` : ""}`);
  }
  replayQuarantine(entryId: string): Promise<{ replay_run_id: string }> {
    return this.client.post(`/quarantine/${entryId}/replay`);
  }

  // UI-owned (feature 007)
  listSavedQueries(): Promise<{ items: SavedQuery[] }> {
    return this.client.get("/ui/saved-queries");
  }
  createSavedQuery(body: unknown): Promise<{ query_id: string }> {
    return this.client.post("/ui/saved-queries", body);
  }
  shareSavedQuery(queryId: string, body: unknown): Promise<{ share_id: string }> {
    return this.client.post(`/ui/saved-queries/${queryId}/share`, body);
  }
  listRoles(): Promise<{ items: UIRole[] }> {
    return this.client.get("/ui/roles");
  }
  createRole(body: unknown): Promise<{ role_id: string }> {
    return this.client.post("/ui/roles", body);
  }
  assignRole(roleId: string, body: unknown): Promise<{ assignment_id: string }> {
    return this.client.post(`/ui/roles/${roleId}/assign`, body);
  }
  listApprovals(): Promise<{ items: ApprovalItem[] }> {
    return this.client.get("/ui/approvals");
  }
  decideApproval(approvalId: string, body: unknown): Promise<{ approval_id: string; decision_state: string }> {
    return this.client.post(`/ui/approvals/${approvalId}/decide`, body);
  }
  searchAuditLog(params?: Record<string, string>): Promise<{ items: AuditEntry[]; next_cursor?: string }> {
    const qs = new URLSearchParams(params || {}).toString();
    return this.client.get(`/ui/audit-log${qs ? `?${qs}` : ""}`);
  }
}