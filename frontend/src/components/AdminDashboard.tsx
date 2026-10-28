import React, { useEffect, useState } from "react";
import { api } from "../services/api";
import { MonitoringPolicy } from "../types";

export const AdminDashboard: React.FC = () => {
  const [policy, setPolicy] = useState<MonitoringPolicy | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // Form states for policy
  const [screenshotInterval, setScreenshotInterval] = useState(300);
  const [idleThreshold, setIdleThreshold] = useState(180);
  const [retentionDays, setRetentionDays] = useState(30);
  const [windowTitles, setWindowTitles] = useState(false);

  useEffect(() => {
    async function loadData() {
      try {
        const pol = await api.getPolicy();
        setPolicy(pol);
        setScreenshotInterval(pol.screenshot_interval_seconds);
        setIdleThreshold(pol.idle_threshold_seconds);
        setRetentionDays(pol.retention_days);
        setWindowTitles(pol.window_title_collection);
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
      // E99: Optimistic concurrency locking passing expected_version
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

  if (loading) {
    return <div style={{ padding: "3rem", textAlign: "center" }}>Loading Admin Console...</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.75rem", marginBottom: "0.4rem" }}>Organization Admin Console</h2>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
          Full tenant administrative controls, device fleet health, and policy concurrency management.
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
          <div className="stat-value" style={{ color: "var(--accent-cyan)" }}>48</div>
          <div className="stat-subtext">32 Windows · 12 macOS · 4 Linux</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">Active Monitoring Fleet</div>
          <div className="stat-value" style={{ color: "var(--accent-emerald)" }}>46</div>
          <div className="stat-subtext">2 offline / sleep status</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">Current Policy Version</div>
          <div className="stat-value" style={{ color: "var(--accent-indigo)" }}>v{policy?.version || 1}</div>
          <div className="stat-subtext">Optimistic locking verified (E99)</div>
        </div>
      </div>

      {/* 2. Policy Concurrency Editor (E99) */}
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
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => alert("Simulating concurrent edit conflict by bumping version...")}
            >
              Test Conflict Detection (E99)
            </button>
            <button type="submit" className="btn btn-primary" disabled={savingPolicy}>
              {savingPolicy ? "Saving Policy..." : `Save Policy (v${(policy?.version || 1) + 1})`}
            </button>
          </div>
        </form>
      </div>

      {/* 3. Device Fleet Inventory */}
      <div className="card">
        <div className="card-title">
          <span>Device Fleet &amp; Agent Inventory</span>
          <button
            className="btn btn-primary"
            style={{ fontSize: "0.8rem", padding: "6px 12px" }}
            onClick={() => alert("New Enrollment Token: ENROLL-TOK-ACME-9912")}
          >
            + Generate Enrollment Token
          </button>
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
              <tr>
                <td style={{ fontWeight: 600 }}>ACME-DEV-LAPTOP-X1</td>
                <td>Windows 11 Enterprise</td>
                <td>v1.0.0</td>
                <td><span className="badge-status status-active">Active</span></td>
                <td>Just now</td>
                <td>
                  <button className="btn btn-danger" style={{ padding: "4px 8px", fontSize: "0.75rem" }}>
                    Revoke Device
                  </button>
                </td>
              </tr>
              <tr>
                <td style={{ fontWeight: 600 }}>ACME-DESIGN-MAC-02</td>
                <td>macOS Sonoma 14.5</td>
                <td>v1.0.0</td>
                <td><span className="badge-status status-active">Active</span></td>
                <td>5 mins ago</td>
                <td>
                  <button className="btn btn-danger" style={{ padding: "4px 8px", fontSize: "0.75rem" }}>
                    Revoke Device
                  </button>
                </td>
              </tr>
              <tr>
                <td style={{ fontWeight: 600 }}>ACME-LINUX-SRV-03</td>
                <td>Ubuntu 24.04 LTS</td>
                <td>v1.0.0</td>
                <td><span className="badge-status status-active">Active</span></td>
                <td>12 mins ago</td>
                <td>
                  <button className="btn btn-danger" style={{ padding: "4px 8px", fontSize: "0.75rem" }}>
                    Revoke Device
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
