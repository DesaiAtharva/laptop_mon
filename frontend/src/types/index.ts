export type MembershipRole = "admin" | "manager" | "employee" | "auditor";

export interface Tenant {
  id: string;
  name: string;
  status: "active" | "suspended" | "deleting";
}

export interface User {
  id: string;
  email: string;
  name: string;
  mfa_enabled: boolean;
}

export interface Membership {
  id: string;
  tenant_id: string;
  tenant_name?: string;
  user_id: string;
  user_name?: string;
  user_email?: string;
  role: MembershipRole;
  status: "active" | "disabled";
  has_screenshot_permission?: boolean;
}

export interface Device {
  id: string;
  hostname: string;
  os: "windows" | "macos" | "linux";
  agent_version: string;
  status: "active" | "revoked";
  last_seen_at: string | null;
  created_at: string;
}

export interface MonitoringPolicy {
  id: string;
  version: number;
  screenshot_interval_seconds: number;
  idle_threshold_seconds: number;
  retention_days: number;
  window_title_collection: boolean;
  exclusion_rules: string[];
}

export interface DailyMetrics {
  device_id: string;
  device_hostname: string;
  local_date: string;
  calc_version: number;
  observed_session_seconds: number;
  active_seconds: number;
  idle_seconds: number;
  productive_seconds: number;
  neutral_seconds: number;
  distracting_seconds: number;
  productive_share: number;
  monitoring_coverage: number;
  sync_lag_seconds: number;
  crash_free_sessions: boolean;
  data_freshness_at: string;
}

export interface AppUsageInterval {
  id: string;
  device_id: string;
  app_identifier: string;
  app_classification: "productive" | "neutral" | "distracting" | "excluded";
  started_at: string;
  ended_at: string;
  duration_seconds: number;
  state: "active" | "idle" | "locked" | "asleep" | "telemetry-gap" | "unobserved";
  calc_version: number;
  is_inferred: boolean;
}

export interface AppUsageSummary {
  app_identifier: string;
  app_classification: string;
  total_seconds: number;
  percentage_of_active: number;
}

export interface ScreenshotItem {
  id: string;
  device_id: string;
  captured_at: string;
  width: number;
  height: number;
  file_size: number;
  thumbnail_url?: string;
  view_url?: string;
}

export type DisputeStatus = "open" | "under_review" | "resolved" | "rejected";

export interface DisputeItem {
  id: string;
  membership_id: string;
  employee_name: string;
  employee_email: string;
  interval_id?: string;
  target_app: string;
  target_date?: string;
  reason: string;
  desired_classification: string;
  status: DisputeStatus;
  resolution_notes: string;
  reviewed_by_name?: string;
  resolved_at?: string;
  created_at: string;
  updated_at: string;
}

export interface SelfViewData {
  employee: {
    user_id: string;
    name: string;
    email: string;
    role: MembershipRole;
    tenant_id: string;
    tenant_name: string;
  };
  monitoring_state: {
    active: boolean;
    status: string;
    devices: Device[];
    last_sync_at: string | null;
  };
  policy: {
    version: number;
    screenshot_interval_seconds: number;
    idle_threshold_seconds: number;
    retention_days: number;
    window_title_collection: boolean;
    exclusion_rules: string[];
  };
  privacy_notice: {
    transparency_principles: string[];
    retention_days: number;
    support_contact: string;
  };
  recent_metrics: DailyMetrics[];
  disputes: DisputeItem[];
}

export interface AuditLogItem {
  id: string;
  actor_name: string;
  actor_email: string;
  action: string;
  resource_type: string;
  resource_id: string;
  request_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
}
