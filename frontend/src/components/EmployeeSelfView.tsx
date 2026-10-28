import React, { useEffect, useState } from "react";
import { api } from "../services/api";
import { DisputeItem, SelfViewData } from "../types";
import { DisputeModal } from "./DisputeModal";

export const EmployeeSelfView: React.FC = () => {
  const [data, setData] = useState<SelfViewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [isDisputeOpen, setIsDisputeOpen] = useState(false);

  useEffect(() => {
    async function loadData() {
      try {
        const res = await api.getSelfView();
        setData(res);
      } catch (err) {
        console.error("Failed to load self-view", err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  function handleDisputeCreated(newDispute: DisputeItem) {
    if (data) {
      setData({
        ...data,
        disputes: [newDispute, ...data.disputes],
      });
    }
  }

  if (loading) {
    return <div style={{ padding: "3rem", textAlign: "center" }}>Loading your monitoring state...</div>;
  }

  if (!data) {
    return <div style={{ padding: "3rem", textAlign: "center" }}>Could not load employee self-view.</div>;
  }

  const latestMetric = data.recent_metrics[0];
  const activeHours = latestMetric ? (latestMetric.active_seconds / 3600).toFixed(1) : "0.0";
  const idleHours = latestMetric ? (latestMetric.idle_seconds / 3600).toFixed(1) : "0.0";
  const productiveShare = latestMetric ? latestMetric.productive_share.toFixed(0) : "0";

  return (
    <div>
      {/* 1. Transparency Notice Banner (REQ-2-1, REQ-11-3) */}
      <div className="transparency-banner">
        <div>
          <div className="transparency-title">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            Transparency & Employee Privacy Guarantee
          </div>
          <p style={{ fontSize: "0.88rem", color: "var(--text-muted)" }}>
            Your organization adheres to policy-driven, transparent monitoring. Keystroke logging,
            password scraping, and private message inspection are strictly forbidden and technically impossible.
          </p>
          <ul className="transparency-list">
            {data.privacy_notice.transparency_principles.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </div>
        <div style={{ textAlign: "right", minWidth: "180px" }}>
          <span className="badge-status status-active" style={{ fontSize: "0.85rem", padding: "6px 14px" }}>
            ● Policy Active (v{data.policy.version})
          </span>
          <div style={{ fontSize: "0.8rem", color: "var(--text-subtle)", marginTop: "8px" }}>
            Retention: {data.policy.retention_days} Days
          </div>
        </div>
      </div>

      {/* 2. Stat Tiles */}
      <div className="grid-4">
        <div className="stat-tile">
          <div className="stat-label">Active Work Time</div>
          <div className="stat-value" style={{ color: "var(--accent-emerald)" }}>{activeHours} hrs</div>
          <div className="stat-subtext">Foreground application focus</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">Idle / Away Time</div>
          <div className="stat-value" style={{ color: "var(--accent-amber)" }}>{idleHours} hrs</div>
          <div className="stat-subtext">No user input detected</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">Productive Share</div>
          <div className="stat-value" style={{ color: "var(--accent-cyan)" }}>{productiveShare}%</div>
          <div className="stat-subtext">Against classified work apps</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">Sync Lag</div>
          <div className="stat-value" style={{ color: "var(--text-main)" }}>
            {latestMetric?.sync_lag_seconds ?? 0}s
          </div>
          <div className="stat-subtext">Real-time local journal sync</div>
        </div>
      </div>

      {/* 3. Daily Timeline Bar with Explicit Gaps (REQ-9-3, E70) */}
      <div className="card" style={{ marginBottom: "2rem" }}>
        <div className="card-title">
          <span>Today&apos;s Activity Timeline &amp; Telemetry Gaps</span>
          <span style={{ fontSize: "0.8rem", color: "var(--text-subtle)", fontWeight: "normal" }}>
            Continuous Timeline (08:00 – 17:00)
          </span>
        </div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
          Notice: Missing telemetry (offline or unmonitored) is explicitly rendered as a gap. It is
          never assumed or counted as productive or idle work.
        </p>

        <div className="timeline-bar-container">
          <div className="timeline-bar">
            <div className="timeline-segment seg-productive" style={{ width: "35%" }} title="Productive (VS Code, Slack)" />
            <div className="timeline-segment seg-idle" style={{ width: "10%" }} title="Idle (Away from keyboard)" />
            <div className="timeline-segment seg-productive" style={{ width: "25%" }} title="Productive (GitHub, Terminal)" />
            <div className="timeline-segment seg-gap" style={{ width: "12%" }} title="Telemetry Gap (Offline / Network Loss) (REQ-9-3)" />
            <div className="timeline-segment seg-neutral" style={{ width: "8%" }} title="Neutral (Documentation)" />
            <div className="timeline-segment seg-distracting" style={{ width: "10%" }} title="Distracting (News / Social)" />
          </div>

          <div className="timeline-legend">
            <div className="legend-item">
              <div className="legend-dot seg-productive" />
              <span>Productive</span>
            </div>
            <div className="legend-item">
              <div className="legend-dot seg-neutral" />
              <span>Neutral</span>
            </div>
            <div className="legend-item">
              <div className="legend-dot seg-distracting" />
              <span>Distracting</span>
            </div>
            <div className="legend-item">
              <div className="legend-dot seg-idle" />
              <span>Idle</span>
            </div>
            <div className="legend-item">
              <div className="legend-dot seg-gap" />
              <span style={{ color: "#c084fc", fontWeight: 600 }}>Telemetry Gap (Explicit Unknown)</span>
            </div>
          </div>
        </div>
      </div>

      {/* 4. Enrolled Devices & Effective Policy */}
      <div className="grid-2">
        <div className="card">
          <div className="card-title">
            <span>Enrolled Hardware</span>
            <span className="badge-status status-active">Active</span>
          </div>
          {data.monitoring_state.devices.map((dev) => (
            <div
              key={dev.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "12px",
                background: "var(--bg-glass)",
                borderRadius: "var(--radius-sm)",
                marginBottom: "8px",
              }}
            >
              <div>
                <div style={{ fontWeight: 600 }}>{dev.hostname}</div>
                <div style={{ fontSize: "0.8rem", color: "var(--text-subtle)" }}>
                  OS: {dev.os} · Agent v{dev.agent_version}
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <span className="badge-status status-active">{dev.status}</span>
                <div style={{ fontSize: "0.75rem", color: "var(--text-subtle)", marginTop: "4px" }}>
                  Last sync: {dev.last_seen_at ? new Date(dev.last_seen_at).toLocaleTimeString() : "Never"}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="card">
          <div className="card-title">
            <span>Policy Boundaries</span>
            <span style={{ fontSize: "0.8rem", color: "var(--text-subtle)" }}>Tenant Scope</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "10px", fontSize: "0.88rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-muted)" }}>Screenshot Frequency:</span>
              <span style={{ fontWeight: 600 }}>Every {data.policy.screenshot_interval_seconds}s</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-muted)" }}>Idle Detection Threshold:</span>
              <span style={{ fontWeight: 600 }}>{data.policy.idle_threshold_seconds}s (3 min)</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-muted)" }}>Window Title Redaction:</span>
              <span style={{ fontWeight: 600 }}>
                {data.policy.window_title_collection ? "Enabled (Redacted)" : "Disabled (Zero Scraping)"}
              </span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "var(--text-muted)" }}>Exclusion Rules:</span>
              <span style={{ fontWeight: 600 }}>
                {Array.isArray(data.policy.exclusion_rules)
                  ? data.policy.exclusion_rules.join(", ")
                  : typeof data.policy.exclusion_rules === "object" && data.policy.exclusion_rules !== null
                  ? Object.keys(data.policy.exclusion_rules).length > 0
                    ? JSON.stringify(data.policy.exclusion_rules)
                    : "None configured"
                  : String(data.policy.exclusion_rules || "None configured")}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* 5. Classification Disputes (E89) */}
      <div className="card" style={{ marginTop: "1rem" }}>
        <div className="card-title">
          <span>Activity &amp; Classification Disputes (E89)</span>
          <button className="btn btn-primary" onClick={() => setIsDisputeOpen(true)}>
            + Dispute Classification
          </button>
        </div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "1.25rem" }}>
          If an application or interval was misclassified, submit a dispute for manager or admin review.
        </p>

        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Target App / Date</th>
                <th>Desired Class</th>
                <th>Reason</th>
                <th>Status</th>
                <th>Resolution Notes</th>
              </tr>
            </thead>
            <tbody>
              {data.disputes.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: "center", color: "var(--text-subtle)", padding: "2rem" }}>
                    No disputes filed. All activity classifications are in good standing.
                  </td>
                </tr>
              ) : (
                data.disputes.map((disp) => (
                  <tr key={disp.id}>
                    <td style={{ fontWeight: 600 }}>
                      {disp.target_app}
                      <div style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>{disp.target_date}</div>
                    </td>
                    <td>
                      <span className="badge-status status-active">{disp.desired_classification}</span>
                    </td>
                    <td>{disp.reason}</td>
                    <td>
                      <span className={`badge-status status-${disp.status}`}>{disp.status}</span>
                    </td>
                    <td style={{ color: "var(--text-muted)" }}>{disp.resolution_notes || "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Dispute Modal */}
      <DisputeModal
        isOpen={isDisputeOpen}
        onClose={() => setIsDisputeOpen(false)}
        onDisputeCreated={handleDisputeCreated}
      />
    </div>
  );
};
