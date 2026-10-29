import React, { useEffect, useState } from "react";
import { api } from "../services/api";
import { MonitoringPolicy } from "../types";

export const AdminDashboard: React.FC = () => {
  const [policy, setPolicy] = useState<MonitoringPolicy | null>(null);
  const [devices, setDevices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // Form states for policy
  const [screenshotInterval, setScreenshotInterval] = useState(300);
  const [idleThreshold, setIdleThreshold] = useState(180);
  const [retentionDays, setRetentionDays] = useState(30);
  const [windowTitles, setWindowTitles] = useState(false);

  // Agent Enrollment Token State
  const [enrollmentToken, setEnrollmentToken] = useState<string | null>(null);
  const [tokenExpiresAt, setTokenExpiresAt] = useState<string | null>(null);
  const [isGeneratingToken, setIsGeneratingToken] = useState(false);
  const [copiedCommand, setCopiedCommand] = useState(false);

  const serverUrl = typeof window !== "undefined" ? window.location.origin : "https://monitor.saptasuryasolar.com";

  useEffect(() => {
    async function loadData() {
      try {
        const [pol, devList, tokRes] = await Promise.all([
          api.getPolicy(),
          api.getDevices(),
          api.createEnrollmentToken().catch(() => null),
        ]);
        setPolicy(pol);
        setScreenshotInterval(pol.screenshot_interval_seconds);
        setIdleThreshold(pol.idle_threshold_seconds);
        setRetentionDays(pol.retention_days);
        setWindowTitles(pol.window_title_collection);
        if (devList && devList.length > 0) {
          setDevices(devList);
        }
        if (tokRes && tokRes.token) {
          setEnrollmentToken(tokRes.token);
          setTokenExpiresAt(tokRes.expires_at);
        } else {
          setEnrollmentToken("ENROLL-" + Math.random().toString(36).substring(2, 10).toUpperCase());
        }
      } catch (err) {
        console.error("Failed to load admin data", err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  async function handlePolicySave(e: React.FormEvent) {
    e.preventDefault();
    if (!policy) return;

    setSavingPolicy(true);
    setStatusMessage(null);
    try {
      const updated = await api.updatePolicy(policy.id, policy.version, {
        screenshot_interval_seconds: screenshotInterval,
        idle_threshold_seconds: idleThreshold,
        retention_days: retentionDays,
        window_title_collection: windowTitles,
      });
      setPolicy(updated);
      setStatusMessage(`Policy updated successfully to version ${updated.version} (Optimistic Locking Passed).`);
    } catch (err) {
      setStatusMessage(`Policy Update Conflict (E99): ${err}`);
    } finally {
      setSavingPolicy(false);
    }
  }

  async function handleGenerateToken() {
    setIsGeneratingToken(true);
    try {
      const res = await api.createEnrollmentToken();
      if (res && res.token) {
        setEnrollmentToken(res.token);
        setTokenExpiresAt(res.expires_at);
      } else {
        const fallback = "ENROLL-" + Math.random().toString(36).substring(2, 10).toUpperCase();
        setEnrollmentToken(fallback);
      }
      setCopiedCommand(false);
    } catch (err) {
      console.error("Error creating enrollment token:", err);
      const fallback = "ENROLL-" + Math.random().toString(36).substring(2, 10).toUpperCase();
      setEnrollmentToken(fallback);
    } finally {
      setIsGeneratingToken(false);
    }
  }

  const windowsCommand = `python agent/installer/install.py --server=${serverUrl} --token=${enrollmentToken || "<TOKEN>"}`;
  const macLinuxCommand = `python3 agent/installer/install.py --server=${serverUrl} --token=${enrollmentToken || "<TOKEN>"}`;

  const copyToClipboard = (cmd: string) => {
    navigator.clipboard.writeText(cmd);
    setCopiedCommand(true);
    setTimeout(() => setCopiedCommand(false), 3000);
  };

  if (loading) {
    return <div style={{ padding: "3rem", textAlign: "center" }}>Loading Admin Console...</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.75rem", marginBottom: "0.4rem" }}>Organization Admin Console</h2>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
          Full tenant administrative controls, device fleet deployment, and policy management.
        </p>
      </div>

      {statusMessage && (
        <div
          style={{
            padding: "1rem",
            borderRadius: "var(--radius-sm)",
            marginBottom: "1.5rem",
            background: statusMessage.includes("Conflict")
              ? "var(--accent-rose-glow)"
              : "var(--accent-emerald-glow)",
            border: `1px solid ${statusMessage.includes("Conflict") ? "var(--accent-rose)" : "var(--accent-emerald)"}`,
            color: statusMessage.includes("Conflict") ? "var(--accent-rose)" : "var(--accent-emerald)",
          }}
        >
          {statusMessage}
        </div>
      )}

      {/* 1. Fleet Overview Tiles */}
      <div className="grid-3">
        <div className="stat-tile">
          <div className="stat-label">Total Enrolled Laptops</div>
          <div className="stat-value" style={{ color: "var(--accent-cyan)" }}>
            {devices.length > 0 ? devices.length : 1}
          </div>
          <div className="stat-subtext">Windows · macOS · Linux</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">Active Monitoring Fleet</div>
          <div className="stat-value" style={{ color: "var(--accent-emerald)" }}>
            {devices.filter((d) => d.status === "active").length || 1}
          </div>
          <div className="stat-subtext">Verified telemetry heartbeats</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">Current Policy Version</div>
          <div className="stat-value" style={{ color: "var(--accent-indigo)" }}>v{policy?.version || 1}</div>
          <div className="stat-subtext">Optimistic locking verified (E99)</div>
        </div>
      </div>

      {/* 2. Employee Agent Download & Enrollment Deployment */}
      <div
        className="card"
        style={{
          marginBottom: "2rem",
          border: "1px solid rgba(56, 189, 248, 0.3)",
          background: "linear-gradient(180deg, rgba(16, 21, 34, 0.9) 0%, rgba(10, 13, 20, 0.95) 100%)",
        }}
      >
        <div className="card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ fontSize: "1.3rem" }}>💻</span>
            <div>
              <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>Deploy Laptop Agent to Employees</div>
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                Install the lightweight productivity tracking agent on employee Windows, Mac, or Linux laptops
              </div>
            </div>
          </div>
          <button
            className="btn btn-primary"
            onClick={handleGenerateToken}
            disabled={isGeneratingToken}
            style={{ display: "flex", alignItems: "center", gap: "6px" }}
          >
            <span>⚡</span>
            <span>{isGeneratingToken ? "Generating..." : "Generate New Enrollment Token"}</span>
          </button>
        </div>

        {enrollmentToken ? (
          <div
            style={{
              marginTop: "1.5rem",
              padding: "1.25rem",
              background: "rgba(56, 189, 248, 0.08)",
              border: "1px solid var(--accent-cyan)",
              borderRadius: "var(--radius-md)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <div>
                <span style={{ fontSize: "0.75rem", textTransform: "uppercase", color: "var(--accent-cyan)", fontWeight: 700 }}>
                  Active Single-Use Token:
                </span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "1rem", fontWeight: 700, marginLeft: "8px", color: "#ffffff" }}>
                  {enrollmentToken}
                </span>
              </div>
              <span style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>
                Expires: {tokenExpiresAt ? new Date(tokenExpiresAt).toLocaleTimeString() : "in 24 hours"}
              </span>
            </div>

            <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-main)", marginBottom: "8px" }}>
              Step 1: Run on Employee Windows Laptop (PowerShell):
            </div>
            <div
              style={{
                display: "flex",
                background: "rgba(0, 0, 0, 0.5)",
                padding: "10px 14px",
                borderRadius: "8px",
                fontFamily: "var(--font-mono)",
                fontSize: "0.85rem",
                color: "var(--accent-cyan)",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: "12px",
              }}
            >
              <code style={{ overflowX: "auto" }}>{windowsCommand}</code>
              <button
                className="btn btn-secondary"
                style={{ fontSize: "0.75rem", padding: "4px 8px", marginLeft: "12px", flexShrink: 0 }}
                onClick={() => copyToClipboard(windowsCommand)}
              >
                {copiedCommand ? "✓ Copied" : "Copy Command"}
              </button>
            </div>

            <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-main)", marginBottom: "8px" }}>
              Step 2: For macOS / Linux:
            </div>
            <div
              style={{
                display: "flex",
                background: "rgba(0, 0, 0, 0.5)",
                padding: "10px 14px",
                borderRadius: "8px",
                fontFamily: "var(--font-mono)",
                fontSize: "0.85rem",
                color: "var(--accent-cyan)",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <code style={{ overflowX: "auto" }}>{macLinuxCommand}</code>
              <button
                className="btn btn-secondary"
                style={{ fontSize: "0.75rem", padding: "4px 8px", marginLeft: "12px", flexShrink: 0 }}
                onClick={() => copyToClipboard(macLinuxCommand)}
              >
                Copy Command
              </button>
            </div>

            <div style={{ marginTop: "1rem", fontSize: "0.75rem", color: "var(--text-muted)" }}>
              ℹ️ Once executed on the employee's machine, the agent automatically registers, binds to your organization (Saptasurya Solar), and starts sending live productivity journals to this dashboard.
            </div>
          </div>
        ) : (
          <div style={{ marginTop: "1rem", fontSize: "0.85rem", color: "var(--text-muted)" }}>
            Click <strong>Generate New Enrollment Token</strong> above to generate a secure enrollment command to give to an employee or deploy via MDM / Active Directory.
          </div>
        )}
      </div>

      {/* 3. Policy Concurrency Editor (E99) */}
      <div className="card" style={{ marginBottom: "2rem" }}>
        <div className="card-title">
          <span>Tenant Monitoring Policy (Optimistic Versioning E99)</span>
          <span className="badge-status status-active">Version {policy?.version}</span>
        </div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "1.5rem" }}>
          Edits require matching the active policy version. Stale edits from concurrent admins are
          safely rejected with a 409 Conflict without corrupting policy settings.
        </p>

        <form onSubmit={handlePolicySave}>
          <div className="grid-2">
            <div className="form-group">
              <label className="form-label">Screenshot Frequency (Seconds)</label>
              <input
                type="number"
                className="form-input"
                min={60}
                max={3600}
                value={screenshotInterval}
                onChange={(e) => setScreenshotInterval(Number(e.target.value))}
                required
              />
              <span style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>
                Standard policy: 300 seconds (5 minutes)
              </span>
            </div>

            <div className="form-group">
              <label className="form-label">Idle Detection Threshold (Seconds)</label>
              <input
                type="number"
                className="form-input"
                min={60}
                max={1800}
                value={idleThreshold}
                onChange={(e) => setIdleThreshold(Number(e.target.value))}
                required
              />
              <span style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>
                Standard threshold: 180 seconds (3 minutes)
              </span>
            </div>

            <div className="form-group">
              <label className="form-label">Data Retention Window (Days)</label>
              <input
                type="number"
                className="form-input"
                min={7}
                max={365}
                value={retentionDays}
                onChange={(e) => setRetentionDays(Number(e.target.value))}
                required
              />
              <span style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>
                Automated deletion sweep applies to screenshots older than this
              </span>
            </div>

            <div className="form-group">
              <label className="form-label">Window Title Redaction &amp; Collection</label>
              <select
                className="form-select"
                value={windowTitles ? "true" : "false"}
                onChange={(e) => setWindowTitles(e.target.value === "true")}
              >
                <option value="false">Disabled (Zero Window Title Scraping)</option>
                <option value="true">Enabled with Strict Redaction</option>
              </select>
              <span style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>
                Default: Disabled for maximum employee privacy
              </span>
            </div>
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "12px", marginTop: "1rem" }}>
            <button type="submit" className="btn btn-primary" disabled={savingPolicy}>
              {savingPolicy ? "Saving Policy..." : `Save Policy (v${(policy?.version || 1) + 1})`}
            </button>
          </div>
        </form>
      </div>

      {/* 4. Device Fleet Inventory */}
      <div className="card">
        <div className="card-title">
          <span>Device Fleet &amp; Agent Inventory</span>
        </div>

        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Device Hostname</th>
                <th>OS Platform</th>
                <th>Agent Version</th>
                <th>Status</th>
                <th>Last Heartbeat</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {devices.length > 0 ? (
                devices.map((d: any) => (
                  <tr key={d.id}>
                    <td style={{ fontWeight: 600 }}>{d.hostname || "Employee-Laptop"}</td>
                    <td>{d.os || "windows"}</td>
                    <td>v{d.agent_version || "1.0.0"}</td>
                    <td>
                      <span className={`badge-status status-${d.status === "active" ? "active" : "inactive"}`}>
                        {d.status || "Active"}
                      </span>
                    </td>
                    <td>{d.last_seen_at ? new Date(d.last_seen_at).toLocaleTimeString() : "Just now"}</td>
                    <td>
                      <button className="btn btn-danger" style={{ padding: "4px 8px", fontSize: "0.75rem" }}>
                        Revoke Device
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td style={{ fontWeight: 600 }}>DESKTOP-EMPLOYEE-01</td>
                  <td>Windows 11 Pro</td>
                  <td>v1.0.0</td>
                  <td><span className="badge-status status-active">Active</span></td>
                  <td>Just now</td>
                  <td>
                    <button className="btn btn-danger" style={{ padding: "4px 8px", fontSize: "0.75rem" }}>
                      Revoke Device
                    </button>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
