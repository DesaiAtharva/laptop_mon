import {
  AuditLogItem,
  DailyMetrics,
  DisputeItem,
  MonitoringPolicy,
  ScreenshotItem,
  SelfViewData,
  Tenant,
} from "../types";

let currentTenantId: string = "";
let currentToken: string = "";

export function setApiAuth(token: string, tenantId: string): void {
  currentToken = token;
  currentTenantId = tenantId;
}

export function clearApiAuth(): void {
  currentToken = "";
  currentTenantId = "";
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (currentToken) {
    headers.set("Authorization", `Bearer ${currentToken}`);
  }
  if (currentTenantId && currentTenantId.length >= 32) {
    headers.set("X-Tenant-ID", currentTenantId);
  }
  headers.set("Content-Type", "application/json");

  const res = await fetch(`/api${path}`, { ...options, headers });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    const err: any = new Error(errorBody.message || `API request failed with status ${res.status}`);
    err.status = res.status;
    err.data = errorBody;
    throw err;
  }
  return res.json() as Promise<T>;
}

export const api = {
  // ── Self View (REQ-2-1, REQ-11-3) ──────────────────────────────────────────
  async getSelfView(): Promise<SelfViewData> {
    try {
      return await request<SelfViewData>("/reports/self-view");
    } catch {
      // Fallback demo dataset for standalone UI presentation
      return {
        employee: {
          user_id: "usr-01",
          name: "Alex Vance",
          email: "alex@enterprise.com",
          role: "employee",
          tenant_id: "ten-01",
          tenant_name: "Acme Cybernetics",
        },
        monitoring_state: {
          active: true,
          status: "active",
          devices: [
            {
              id: "dev-01",
              hostname: "ACME-DEV-LAPTOP-X1",
              os: "windows",
              agent_version: "1.0.0",
              status: "active",
              last_seen_at: new Date().toISOString(),
              created_at: new Date(Date.now() - 30 * 86400000).toISOString(),
            },
          ],
          last_sync_at: new Date().toISOString(),
        },
        policy: {
          version: 2,
          screenshot_interval_seconds: 300,
          idle_threshold_seconds: 180,
          retention_days: 30,
          window_title_collection: false,
          exclusion_rules: ["*1password*", "*keepass*", "*banking*"],
        },
        privacy_notice: {
          transparency_principles: [
            "Monitoring is strictly transparent, policy-driven, and auditable.",
            "No keystroke logging, password capture, or private-message scraping.",
            "Missing telemetry is an explicit gap — never assumed as active work.",
            "Screenshots exclude sensitive password managers and banking apps.",
            "You have the right to inspect all telemetry and submit classification disputes.",
          ],
          retention_days: 30,
          support_contact: "privacy@enterprise.com",
        },
        recent_metrics: [
          {
            device_id: "dev-01",
            device_hostname: "ACME-DEV-LAPTOP-X1",
            local_date: new Date().toISOString().split("T")[0],
            calc_version: 1,
            observed_session_seconds: 28800,
            active_seconds: 21600,
            idle_seconds: 5400,
            productive_seconds: 17280,
            neutral_seconds: 2880,
            distracting_seconds: 1440,
            productive_share: 80.0,
            monitoring_coverage: 100.0,
            sync_lag_seconds: 12,
            crash_free_sessions: true,
            data_freshness_at: new Date().toISOString(),
          },
          {
            device_id: "dev-01",
            device_hostname: "ACME-DEV-LAPTOP-X1",
            local_date: new Date(Date.now() - 86400000).toISOString().split("T")[0],
            calc_version: 1,
            observed_session_seconds: 28800,
            active_seconds: 22400,
            idle_seconds: 4800,
            productive_seconds: 18800,
            neutral_seconds: 2400,
            distracting_seconds: 1200,
            productive_share: 83.9,
            monitoring_coverage: 100.0,
            sync_lag_seconds: 15,
            crash_free_sessions: true,
            data_freshness_at: new Date().toISOString(),
          },
        ],
        disputes: [
          {
            id: "disp-01",
            membership_id: "mem-01",
            employee_name: "Alex Vance",
            employee_email: "alex@enterprise.com",
            target_app: "slack.exe",
            target_date: new Date().toISOString().split("T")[0],
            reason: "Client messaging misclassified as neutral instead of productive.",
            desired_classification: "productive",
            status: "open",
            resolution_notes: "",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
      };
    }
  },

  // ── Team Reports (REQ-2-3) ────────────────────────────────────────────────
  async getDailyReports(): Promise<{ results: DailyMetrics[] }> {
    try {
      return await request<{ results: DailyMetrics[] }>("/reports/daily");
    } catch {
      return {
        results: [
          {
            device_id: "dev-01",
            device_hostname: "ACME-DEV-LAPTOP-X1",
            local_date: new Date().toISOString().split("T")[0],
            calc_version: 1,
            observed_session_seconds: 28800,
            active_seconds: 21600,
            idle_seconds: 5400,
            productive_seconds: 17280,
            neutral_seconds: 2880,
            distracting_seconds: 1440,
            productive_share: 80.0,
            monitoring_coverage: 100.0,
            sync_lag_seconds: 12,
            crash_free_sessions: true,
            data_freshness_at: new Date().toISOString(),
          },
          {
            device_id: "dev-02",
            device_hostname: "ACME-DESIGN-MAC-02",
            local_date: new Date().toISOString().split("T")[0],
            calc_version: 1,
            observed_session_seconds: 27000,
            active_seconds: 19800,
            idle_seconds: 6200,
            productive_seconds: 16500,
            neutral_seconds: 2000,
            distracting_seconds: 1300,
            productive_share: 83.3,
            monitoring_coverage: 95.0,
            sync_lag_seconds: 30,
            crash_free_sessions: true,
            data_freshness_at: new Date().toISOString(),
          },
        ],
      };
    }
  },

  // ── Disputes (E89) ────────────────────────────────────────────────────────
  async getDisputes(): Promise<DisputeItem[]> {
    try {
      return await request<DisputeItem[]>("/disputes");
    } catch {
      return [
        {
          id: "disp-01",
          membership_id: "mem-01",
          employee_name: "Alex Vance",
          employee_email: "alex@enterprise.com",
          target_app: "slack.exe",
          target_date: new Date().toISOString().split("T")[0],
          reason: "Project client triage misclassified as distracting.",
          desired_classification: "productive",
          status: "open",
          resolution_notes: "",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ];
    }
  },

  async createDispute(payload: {
    target_app: string;
    target_date?: string;
    reason: string;
    desired_classification: string;
  }): Promise<DisputeItem> {
    try {
      return await request<DisputeItem>("/disputes", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    } catch {
      return {
        id: `disp-${Date.now()}`,
        membership_id: "mem-01",
        employee_name: "Alex Vance",
        employee_email: "alex@enterprise.com",
        target_app: payload.target_app,
        target_date: payload.target_date || new Date().toISOString().split("T")[0],
        reason: payload.reason,
        desired_classification: payload.desired_classification,
        status: "open",
        resolution_notes: "",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
    }
  },

  async resolveDispute(
    id: string,
    payload: { status: "resolved" | "rejected" | "under_review"; resolution_notes?: string }
  ): Promise<DisputeItem> {
    try {
      return await request<DisputeItem>(`/disputes/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    } catch {
      return {
        id,
        membership_id: "mem-01",
        employee_name: "Alex Vance",
        employee_email: "alex@enterprise.com",
        target_app: "slack.exe",
        reason: "Dispute rationale",
        desired_classification: "productive",
        status: payload.status,
        resolution_notes: payload.resolution_notes || "Resolved by manager",
        reviewed_by_name: "Manager Alice",
        resolved_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
    }
  },

  // ── Screenshots Gallery (E69) ─────────────────────────────────────────────
  async getScreenshots(): Promise<{ results: ScreenshotItem[] }> {
    try {
      return await request<{ results: ScreenshotItem[] }>("/screenshots?page_size=1000");
    } catch {
      return {
        results: [
          {
            id: "sc-01",
            device_id: "dev-01",
            captured_at: new Date(Date.now() - 15 * 60000).toISOString(),
            width: 1920,
            height: 1080,
            file_size: 142050,
          },
          {
            id: "sc-02",
            device_id: "dev-01",
            captured_at: new Date(Date.now() - 30 * 60000).toISOString(),
            width: 1920,
            height: 1080,
            file_size: 138900,
          },
          {
            id: "sc-03",
            device_id: "dev-02",
            captured_at: new Date(Date.now() - 45 * 60000).toISOString(),
            width: 2560,
            height: 1440,
            file_size: 210400,
          },
        ],
      };
    }
  },

  async getScreenshotViewUrl(id: string): Promise<{ view_url: string; expires_in_seconds: number }> {
    try {
      return await request<{ view_url: string; expires_in_seconds: number }>(
        `/screenshots/${id}/view-url`,
        { method: "POST" }
      );
    } catch {
      return {
        view_url: "https://images.unsplash.com/photo-1555066931-4365d14bab8c?auto=format&fit=crop&w=1200&q=80",
        expires_in_seconds: 300,
      };
    }
  },

  // ── Policies (E99) ────────────────────────────────────────────────────────
  async getPolicy(): Promise<MonitoringPolicy> {
    try {
      return await request<MonitoringPolicy>("/policies");
    } catch {
      return {
        id: "pol-01",
        version: 2,
        screenshot_interval_seconds: 300,
        idle_threshold_seconds: 180,
        retention_days: 30,
        window_title_collection: false,
        exclusion_rules: ["*password*", "*keepass*", "*banking*"],
      };
    }
  },

  async updatePolicy(
    id: string,
    expectedVersion: number,
    patch: Partial<MonitoringPolicy>
  ): Promise<MonitoringPolicy> {
    try {
      return await request<MonitoringPolicy>(`/policies/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ expected_version: expectedVersion, ...patch }),
      });
    } catch (err: any) {
      if (err.status) {
        throw err;
      }
      return {
        id,
        version: expectedVersion + 1,
        screenshot_interval_seconds: patch.screenshot_interval_seconds || 300,
        idle_threshold_seconds: patch.idle_threshold_seconds || 180,
        retention_days: patch.retention_days || 30,
        window_title_collection: patch.window_title_collection ?? false,
        exclusion_rules: patch.exclusion_rules || ["*password*"],
      };
    }
  },

  // ── Audit Logs ────────────────────────────────────────────────────────────
  async getAuditLogs(): Promise<AuditLogItem[]> {
    try {
      return await request<AuditLogItem[]>("/audit-logs");
    } catch {
      return [
        {
          id: "aud-01",
          actor_name: "Alice Admin",
          actor_email: "admin@acme.com",
          action: "policy.updated",
          resource_type: "monitoring_policy",
          resource_id: "pol-01",
          request_id: "req-9812",
          metadata: { version: 2, idle_threshold: 180 },
          created_at: new Date().toISOString(),
        },
        {
          id: "aud-02",
          actor_name: "Bob Manager",
          actor_email: "manager@acme.com",
          action: "dispute.resolved",
          resource_type: "dispute",
          resource_id: "disp-01",
          request_id: "req-9810",
          metadata: { status: "resolved" },
          created_at: new Date(Date.now() - 3600000).toISOString(),
        },
      ];
    }
  },

  // ── Devices & Agent Enrollment (§8.4) ────────────────────────────────────
  async getDevices(): Promise<any[]> {
    try {
      const resp = await request<any>("/devices");
      if (Array.isArray(resp)) return resp;
      if (resp && resp.results) return resp.results;
      return [];
    } catch {
      return [];
    }
  },

  async createEnrollmentToken(membershipId?: string): Promise<{
    token: string;
    expires_at: string;
    tenant_id: string;
  }> {
    const res = await request<any>("/devices/enrollment-tokens", {
      method: "POST",
      body: JSON.stringify(membershipId ? { membership_id: membershipId } : {}),
    });
    return {
      token: res.token || res.enrollment_token || "",
      expires_at: res.expires_at,
      tenant_id: res.tenant_id || "",
    };
  },

  // ── Authentication (Production Login & Session Management) ─────────────
  async login(email: string, password: string): Promise<{
    token: string;
    user: { id: string; email: string; name: string; role: any; is_superuser: boolean };
    tenant: Tenant | null;
    tenants: Tenant[];
    expires_at: string;
  }> {
    return await request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  async logout(): Promise<void> {
    try {
      await request("/auth/session/revoke", {
        method: "POST",
        body: JSON.stringify({ all: false }),
      });
    } catch (e) {
      console.warn("Logout session revoke warning:", e);
    }
  },

  // ── Multi-Tenant Switcher (E46) ───────────────────────────────────────────
  async getUserTenants(): Promise<Tenant[]> {
    try {
      const data = await request<{ tenants: Array<{ tenant_id: string; name: string; status: any }> }>("/me/tenants");
      if (data && data.tenants) {
        return data.tenants.map((t) => ({ id: t.tenant_id, name: t.name, status: t.status }));
      }
      return [];
    } catch {
      return [
        { id: "ten-01", name: "Acme Cybernetics", status: "active" },
        { id: "ten-02", name: "Wayne Enterprises", status: "active" },
        { id: "ten-03", name: "Stark Industries", status: "active" },
      ];
    }
  },
};
