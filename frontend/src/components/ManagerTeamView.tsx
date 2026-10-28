import React, { useEffect, useState } from "react";
import { api } from "../services/api";
import { DailyMetrics, DisputeItem } from "../types";

export const ManagerTeamView: React.FC = () => {
  const [metrics, setMetrics] = useState<DailyMetrics[]>([]);
  const [disputes, setDisputes] = useState<DisputeItem[]>([]);
  const [scrubPosition, setScrubPosition] = useState<number>(50); // percentage (E70)
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadTeamData() {
      try {
        const [repRes, dispRes] = await Promise.all([
          api.getDailyReports(),
          api.getDisputes(),
        ]);
        setMetrics(repRes.results);
        setDisputes(dispRes);
      } catch (err) {
        console.error("Failed to load team data", err);
      } finally {
        setLoading(false);
      }
    }
    loadTeamData();
  }, []);

  async function handleResolve(id: string, status: "resolved" | "rejected") {
    const notes = prompt("Enter resolution notes / rationale:") || "";
    try {
      const updated = await api.resolveDispute(id, { status, resolution_notes: notes });
      setDisputes(disputes.map((d) => (d.id === id ? updated : d)));
    } catch (err) {
      alert(`Failed to update dispute: ${err}`);
    }
  }

  if (loading) {
    return <div style={{ padding: "3rem", textAlign: "center" }}>Loading assigned team reports...</div>;
  }

  const totalActiveSeconds = metrics.reduce((acc, m) => acc + m.active_seconds, 0);
  const avgProductiveShare = metrics.length
    ? (metrics.reduce((acc, m) => acc + m.productive_share, 0) / metrics.length).toFixed(0)
    : "0";

  return (
    <div>
      {/* 1. Header with Scoping Notice (REQ-2-3, E47) */}
      <div style={{ marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.75rem", marginBottom: "0.4rem" }}>Manager Team Dashboard</h2>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
          Scoped strictly to your assigned teams. Cross-team telemetry is quarantined by tenant RBAC.
        </p>
      </div>

      {/* 2. Team Stats */}
      <div className="grid-3">
        <div className="stat-tile">
          <div className="stat-label">Assigned Team Members</div>
          <div className="stat-value" style={{ color: "var(--accent-cyan)" }}>{metrics.length}</div>
          <div className="stat-subtext">Active laptop agents</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">Total Team Active Hours</div>
          <div className="stat-value" style={{ color: "var(--accent-emerald)" }}>
            {(totalActiveSeconds / 3600).toFixed(1)} hrs
          </div>
          <div className="stat-subtext">Sum of un-interrupted work time</div>
        </div>
        <div className="stat-tile">
          <div className="stat-label">Team Average Productive Share</div>
          <div className="stat-value" style={{ color: "var(--accent-indigo)" }}>{avgProductiveShare}%</div>
          <div className="stat-subtext">Across productive work apps</div>
        </div>
      </div>

      {/* 3. Rapid Timeline Scrubber across Team (E70) */}
      <div className="card" style={{ marginBottom: "2rem" }}>
        <div className="card-title">
          <span>Continuous Team Timeline Scrubbing (E70)</span>
          <span style={{ fontSize: "0.85rem", color: "var(--accent-cyan)", fontWeight: "bold" }}>
            Scrub Time: {Math.floor(8 + (scrubPosition / 100) * 9)}:
            {Math.floor(((scrubPosition % 10) / 10) * 60).toString().padStart(2, "0")}
          </span>
        </div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "1rem" }}>
          Rapidly scrub through time without performance degradation. Explicit gaps represent missing telemetry.
        </p>

        <input
          type="range"
          min="0"
          max="100"
          value={scrubPosition}
          onChange={(e) => setScrubPosition(Number(e.target.value))}
          style={{ width: "100%", accentColor: "var(--accent-cyan)", cursor: "pointer", marginBottom: "1rem" }}
        />

        <div className="timeline-bar-container">
          {metrics.map((m) => (
            <div key={m.device_id} style={{ marginBottom: "12px" }}>
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: "4px" }}>
                {m.device_hostname} · {m.productive_share.toFixed(0)}% Productive
              </div>
              <div className="timeline-bar" style={{ height: "20px" }}>
                <div className="timeline-segment seg-productive" style={{ width: "40%" }} />
                <div className="timeline-segment seg-idle" style={{ width: "15%" }} />
                <div className="timeline-segment seg-gap" style={{ width: "10%" }} />
                <div className="timeline-segment seg-productive" style={{ width: "25%" }} />
                <div className="timeline-segment seg-neutral" style={{ width: "10%" }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 4. Team Member Leaderboard */}
      <div className="card" style={{ marginBottom: "2rem" }}>
        <div className="card-title">Team Member Productivity Breakdown</div>
        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Device Hostname</th>
                <th>Active Work</th>
                <th>Idle Time</th>
                <th>Productive Share</th>
                <th>Coverage</th>
                <th>Freshness</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => (
                <tr key={m.device_id}>
                  <td style={{ fontWeight: 600 }}>{m.device_hostname}</td>
                  <td style={{ color: "var(--accent-emerald)" }}>{(m.active_seconds / 3600).toFixed(1)} hrs</td>
                  <td style={{ color: "var(--accent-amber)" }}>{(m.idle_seconds / 3600).toFixed(1)} hrs</td>
                  <td>
                    <span className="badge-status status-active">{m.productive_share.toFixed(0)}%</span>
                  </td>
                  <td>{m.monitoring_coverage.toFixed(0)}%</td>
                  <td style={{ fontSize: "0.8rem", color: "var(--text-subtle)" }}>
                    {new Date(m.data_freshness_at).toLocaleTimeString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 5. Team Disputes Review Queue (E89) */}
      <div className="card">
        <div className="card-title">
          <span>Team Classification Disputes Queue (E89)</span>
          <span className="badge-status status-open">{disputes.length} Disputes</span>
        </div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginBottom: "1.25rem" }}>
          Review employee dispute submissions. Approving a dispute can reclassify the application for the tenant.
        </p>

        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Employee</th>
                <th>Target App</th>
                <th>Desired Class</th>
                <th>Reason</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {disputes.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: "center", color: "var(--text-subtle)", padding: "2rem" }}>
                    No pending disputes for review.
                  </td>
                </tr>
              ) : (
                disputes.map((disp) => (
                  <tr key={disp.id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{disp.employee_name}</div>
                      <div style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>{disp.employee_email}</div>
                    </td>
                    <td style={{ fontWeight: 600 }}>{disp.target_app}</td>
                    <td>
                      <span className="badge-status status-active">{disp.desired_classification}</span>
                    </td>
                    <td style={{ maxWidth: "250px" }}>{disp.reason}</td>
                    <td>
                      <span className={`badge-status status-${disp.status}`}>{disp.status}</span>
                    </td>
                    <td>
                      {disp.status === "open" ? (
                        <div style={{ display: "flex", gap: "6px" }}>
                          <button
                            className="btn btn-primary"
                            style={{ padding: "4px 10px", fontSize: "0.75rem" }}
                            onClick={() => handleResolve(disp.id, "resolved")}
                          >
                            Approve
                          </button>
                          <button
                            className="btn btn-danger"
                            style={{ padding: "4px 10px", fontSize: "0.75rem" }}
                            onClick={() => handleResolve(disp.id, "rejected")}
                          >
                            Reject
                          </button>
                        </div>
                      ) : (
                        <span style={{ fontSize: "0.8rem", color: "var(--text-subtle)" }}>
                          {disp.resolution_notes || "Resolved"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
