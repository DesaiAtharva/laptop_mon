import React, { useEffect, useState, useMemo } from "react";
import { api } from "../services/api";
import {
  ProductivitySummaryData,
  ProductivityDeviceItem,
  ProductivityDaySummary,
  AppLeaderboardItem,
} from "../types";

type ViewLevel = "devices" | "days" | "detail";

export const ProductivityDashboard: React.FC = () => {
  const [data, setData] = useState<ProductivitySummaryData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [viewLevel, setViewLevel] = useState<ViewLevel>("devices");
  const [selectedDevice, setSelectedDevice] = useState<ProductivityDeviceItem | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>(
    new Date().toISOString().split("T")[0]
  );
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedCategory, setSelectedCategory] = useState<string>("All");
  const [expandedApps, setExpandedApps] = useState<Record<string, boolean>>({});
  const [hoveredInterval, setHoveredInterval] = useState<any | null>(null);
  const [scrubberMinute, setScrubberMinute] = useState<number>(720); // 12:00 PM default

  const loadProductivity = async (devId?: string, dt?: string) => {
    setLoading(true);
    try {
      const res = await api.getProductivitySummary(devId, dt);
      setData(res);

      // Keep selected device updated with latest metrics
      if (res.available_devices && res.available_devices.length > 0) {
        if (devId) {
          const match = res.available_devices.find((d) => d.id === devId);
          if (match) setSelectedDevice(match);
        } else if (!selectedDevice) {
          setSelectedDevice(res.available_devices[0]);
        }
      }
    } catch (err) {
      console.error("Failed to load productivity data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProductivity(selectedDevice?.id, selectedDate);
  }, []);

  const handleSelectDevice = (dev: ProductivityDeviceItem) => {
    setSelectedDevice(dev);
    setViewLevel("days");
    loadProductivity(dev.id, selectedDate);
  };

  const handleSelectDay = (dateStr: string) => {
    setSelectedDate(dateStr);
    setViewLevel("detail");
    loadProductivity(selectedDevice?.id, dateStr);
  };

  const toggleExpand = (appId: string) => {
    setExpandedApps((prev) => ({ ...prev, [appId]: !prev[appId] }));
  };

  const formatSeconds = (sec: number | undefined): string => {
    if (!sec || sec <= 0) return "0s";
    const hrs = Math.floor(sec / 3600);
    const mins = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    if (hrs > 0) {
      return `${hrs}h ${mins}m`;
    }
    if (mins > 0) {
      return `${mins}m ${s}s`;
    }
    return `${s}s`;
  };

  const formatTimeOnly = (isoStr?: string): string => {
    if (!isoStr) return "—";
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return "—";
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "—";
    }
  };

  const formatTimeWithSeconds = (isoStr?: string): string => {
    if (!isoStr) return "—";
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return "—";
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return "—";
    }
  };

  const filteredApps = useMemo(() => {
    if (!data) return [];
    return data.app_leaderboard.filter((app: AppLeaderboardItem) => {
      const matchesSearch =
        app.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        app.app_identifier.toLowerCase().includes(searchQuery.toLowerCase()) ||
        app.tabs.some((t) =>
          t.tab_title.toLowerCase().includes(searchQuery.toLowerCase()) ||
          t.domain.toLowerCase().includes(searchQuery.toLowerCase())
        );
      const matchesCategory =
        selectedCategory === "All" || app.category === selectedCategory;
      return matchesSearch && matchesCategory;
    });
  }, [data, searchQuery, selectedCategory]);

  const quickDates = [
    { label: "Today", value: new Date().toISOString().split("T")[0] },
    {
      label: "Yesterday",
      value: new Date(Date.now() - 86400000).toISOString().split("T")[0],
    },
    {
      label: "2 Days Ago",
      value: new Date(Date.now() - 172800000).toISOString().split("T")[0],
    },
  ];

  // Derive current activity at scrubber position
  const activeAtScrubber = useMemo(() => {
    if (!data || !data.timeline_intervals || data.timeline_intervals.length === 0)
      return null;
    const targetSecond = scrubberMinute * 60;
    const baseDateStr = data.date;
    for (const inv of data.timeline_intervals) {
      const start = new Date(inv.started_at);
      const end = new Date(inv.ended_at);
      const dayStart = new Date(`${baseDateStr}T00:00:00Z`);
      const invStartSec = (start.getTime() - dayStart.getTime()) / 1000;
      const invEndSec = (end.getTime() - dayStart.getTime()) / 1000;
      if (targetSecond >= invStartSec && targetSecond <= invEndSec) {
        return inv;
      }
    }
    return null;
  }, [data, scrubberMinute]);

  const scrubberTimeStr = `${Math.floor(scrubberMinute / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(scrubberMinute % 60)
    .toString()
    .padStart(2, "0")}`;

  const topApp = data?.app_leaderboard?.[0];

  // Fleet Totals for Level 1
  const fleetTotals = useMemo(() => {
    const devices = data?.available_devices || [];
    const totalActiveSec = devices.reduce(
      (sum, d) => sum + (d.total_active_seconds || 0),
      0
    );
    const validScores = devices.filter((d) => (d.avg_productive_share || 0) > 0);
    const avgScore = validScores.length
      ? Math.round(
          validScores.reduce((sum, d) => sum + (d.avg_productive_share || 0), 0) /
            validScores.length
        )
      : 0;
    const totalProofs = devices.reduce((sum, d) => sum + (d.total_screenshots || 0), 0);
    return {
      deviceCount: devices.length,
      totalActiveSec,
      avgScore,
      totalProofs,
    };
  }, [data?.available_devices]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* ── TOP BREADCRUMB NAVIGATION & HEADER ───────────────────────────────── */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "1rem",
          background: "var(--bg-card)",
          padding: "1.2rem 1.5rem",
          borderRadius: "12px",
          border: "1px solid var(--border-color)",
        }}
      >
        <div>
          {/* Breadcrumb Path */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              fontSize: "0.85rem",
              color: "var(--text-subtle)",
              marginBottom: "4px",
            }}
          >
            <span
              onClick={() => setViewLevel("devices")}
              style={{
                cursor: "pointer",
                color: viewLevel === "devices" ? "var(--accent-cyan)" : "var(--text-muted)",
                fontWeight: 600,
              }}
            >
              📊 24h Productivity &amp; Apps
            </span>

            {viewLevel !== "devices" && (
              <>
                <span>/</span>
                <span
                  onClick={() => setViewLevel("days")}
                  style={{
                    cursor: "pointer",
                    color: viewLevel === "days" ? "var(--accent-cyan)" : "var(--text-muted)",
                    fontWeight: 600,
                  }}
                >
                  💻 {selectedDevice?.hostname || "Device"}
                </span>
              </>
            )}

            {viewLevel === "detail" && (
              <>
                <span>/</span>
                <span style={{ color: "var(--accent-cyan)", fontWeight: 700 }}>
                  📅 {selectedDate} (24-Hour Breakdown)
                </span>
              </>
            )}
          </div>

          <h2 style={{ fontSize: "1.45rem", margin: 0, fontWeight: 700 }}>
            {viewLevel === "devices" && "Monitored Laptops Fleet Overview"}
            {viewLevel === "days" && `Activity Calendar: ${selectedDevice?.hostname}`}
            {viewLevel === "detail" && `24h Productivity: ${selectedDevice?.hostname} on ${selectedDate}`}
          </h2>
          <p style={{ margin: "3px 0 0", fontSize: "0.85rem", color: "var(--text-muted)" }}>
            {viewLevel === "devices" && "Select any monitored laptop below to drill into its daily activity calendar."}
            {viewLevel === "days" && "Select any active calendar day to inspect its full 24-hour timeline and application breakdown."}
            {viewLevel === "detail" && "Full continuous 24-hour timeline scrubbing, active browser tabs, and workload distribution."}
          </p>
        </div>

        {/* Level Controls & Back Buttons */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
          {viewLevel === "days" && (
            <button
              onClick={() => setViewLevel("devices")}
              style={{
                background: "rgba(255, 255, 255, 0.08)",
                color: "var(--text-main)",
                border: "1px solid var(--border-color)",
                padding: "8px 14px",
                borderRadius: "8px",
                fontSize: "0.85rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              ← Back to All Devices
            </button>
          )}

          {viewLevel === "detail" && (
            <button
              onClick={() => setViewLevel("days")}
              style={{
                background: "rgba(255, 255, 255, 0.08)",
                color: "var(--text-main)",
                border: "1px solid var(--border-color)",
                padding: "8px 14px",
                borderRadius: "8px",
                fontSize: "0.85rem",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              ← Back to Days Calendar
            </button>
          )}

          {/* Refresh Button */}
          <button
            onClick={() => loadProductivity(selectedDevice?.id, selectedDate)}
            disabled={loading}
            style={{
              background: "var(--accent-indigo)",
              color: "#fff",
              border: "none",
              padding: "8px 14px",
              borderRadius: "8px",
              fontWeight: 600,
              fontSize: "0.85rem",
              cursor: loading ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            {loading ? "Refreshing..." : "↻ Refresh"}
          </button>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════════════════════
          LEVEL 1: MONITORED DEVICES OVERVIEW TABLE
      ═══════════════════════════════════════════════════════════════════════ */}
      {viewLevel === "devices" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          {/* Fleet KPI Tiles */}
          <div
            className="grid-4"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "1rem",
            }}
          >
            <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(6, 182, 212, 0.2)" }}>
              <div className="stat-label">💻 Monitored Laptops</div>
              <div className="stat-value" style={{ color: "var(--accent-cyan)" }}>
                {fleetTotals.deviceCount}
              </div>
              <div className="stat-subtext">Active corporate laptops enrolled</div>
            </div>

            <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(16, 185, 129, 0.2)" }}>
              <div className="stat-label">⏱️ Fleet Total Work Time</div>
              <div className="stat-value" style={{ color: "var(--accent-emerald)" }}>
                {formatSeconds(fleetTotals.totalActiveSec)}
              </div>
              <div className="stat-subtext">Cumulative focused work duration</div>
            </div>

            <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(139, 92, 246, 0.2)" }}>
              <div className="stat-label">🎯 Average Focus Score</div>
              <div className="stat-value" style={{ color: "var(--accent-indigo)" }}>
                {fleetTotals.avgScore}%
              </div>
              <div className="stat-subtext">Across work applications</div>
            </div>

            <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(255, 255, 255, 0.1)" }}>
              <div className="stat-label">📷 Verified Screenshot Proofs</div>
              <div className="stat-value" style={{ color: "var(--text-main)" }}>
                {fleetTotals.totalProofs}
              </div>
              <div className="stat-subtext">Total visual audit proofs stored</div>
            </div>
          </div>

          {/* Devices Table Card */}
          <div
            className="card"
            style={{
              background: "var(--bg-card)",
              borderRadius: "12px",
              border: "1px solid var(--border-color)",
              padding: "1.5rem",
            }}
          >
            <div style={{ marginBottom: "1rem" }}>
              <h3 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 700 }}>
                Fleet Devices Directory
              </h3>
              <span style={{ fontSize: "0.82rem", color: "var(--text-muted)" }}>
                Click on any device row or the action button to inspect its day-wise activity calendar.
              </span>
            </div>

            <div style={{ overflowX: "auto" }}>
              <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border-color)", color: "var(--text-muted)", fontSize: "0.82rem" }}>
                    <th style={{ padding: "12px 10px" }}>Laptop / Hostname</th>
                    <th style={{ padding: "12px 10px" }}>Operating System</th>
                    <th style={{ padding: "12px 10px" }}>Status</th>
                    <th style={{ padding: "12px 10px" }}>Monitored Days</th>
                    <th style={{ padding: "12px 10px" }}>Total Active Work</th>
                    <th style={{ padding: "12px 10px" }}>Avg Focus Score</th>
                    <th style={{ padding: "12px 10px" }}>Screenshot Proofs</th>
                    <th style={{ padding: "12px 10px" }}>Last Active</th>
                    <th style={{ padding: "12px 10px", textAlign: "right" }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.available_devices && data.available_devices.length > 0 ? (
                    data.available_devices.map((dev) => (
                      <tr
                        key={dev.id}
                        onClick={() => handleSelectDevice(dev)}
                        style={{
                          borderBottom: "1px solid rgba(255, 255, 255, 0.05)",
                          cursor: "pointer",
                          transition: "background 0.15s ease",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "rgba(255, 255, 255, 0.03)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "transparent";
                        }}
                      >
                        <td style={{ padding: "14px 10px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                            <span style={{ fontSize: "1.3rem" }}>💻</span>
                            <div>
                              <div style={{ fontWeight: 700, color: "var(--text-main)", fontSize: "0.95rem" }}>
                                {dev.hostname}
                              </div>
                              <div style={{ fontSize: "0.75rem", color: "var(--text-subtle)", fontFamily: "monospace" }}>
                                {dev.id}
                              </div>
                            </div>
                          </div>
                        </td>

                        <td style={{ padding: "14px 10px" }}>
                          <span
                            style={{
                              padding: "4px 8px",
                              borderRadius: "4px",
                              background: "rgba(255, 255, 255, 0.06)",
                              fontSize: "0.78rem",
                              fontWeight: 600,
                              textTransform: "capitalize",
                            }}
                          >
                            {dev.os}
                          </span>
                        </td>

                        <td style={{ padding: "14px 10px" }}>
                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: "5px",
                              fontSize: "0.8rem",
                              color: dev.status === "active" ? "var(--accent-emerald)" : "var(--text-muted)",
                              fontWeight: 600,
                            }}
                          >
                            <span
                              style={{
                                width: "8px",
                                height: "8px",
                                borderRadius: "50%",
                                background: dev.status === "active" ? "#10b981" : "#64748b",
                              }}
                            />
                            {dev.status === "active" ? "Enrolled" : dev.status}
                          </span>
                        </td>

                        <td style={{ padding: "14px 10px", fontWeight: 600, fontSize: "0.9rem" }}>
                          {dev.total_days || 1} Days
                        </td>

                        <td style={{ padding: "14px 10px", fontWeight: 700, fontSize: "0.92rem", color: "var(--accent-emerald)" }}>
                          {formatSeconds(dev.total_active_seconds)}
                        </td>

                        <td style={{ padding: "14px 10px" }}>
                          <span
                            className="badge-classification classification-productive"
                            style={{ fontSize: "0.78rem" }}
                          >
                            {dev.avg_productive_share || 0}% Focus
                          </span>
                        </td>

                        <td style={{ padding: "14px 10px", color: "var(--text-main)", fontWeight: 600, fontSize: "0.88rem" }}>
                          📷 {dev.total_screenshots || 0}
                        </td>

                        <td style={{ padding: "14px 10px", fontSize: "0.82rem", color: "var(--text-muted)" }}>
                          {dev.last_seen_at ? new Date(dev.last_seen_at).toLocaleString() : "Never"}
                        </td>

                        <td style={{ padding: "14px 10px", textAlign: "right" }}>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleSelectDevice(dev);
                            }}
                            style={{
                              background: "rgba(6, 182, 212, 0.15)",
                              color: "var(--accent-cyan)",
                              border: "1px solid rgba(6, 182, 212, 0.3)",
                              padding: "6px 12px",
                              borderRadius: "6px",
                              fontSize: "0.8rem",
                              fontWeight: 600,
                              cursor: "pointer",
                              transition: "all 0.15s ease",
                            }}
                          >
                            View Calendar →
                          </button>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={9} style={{ textAlign: "center", padding: "3rem", color: "var(--text-muted)" }}>
                        No monitored devices enrolled in this organization.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          LEVEL 2: DAY-WISE ACTIVITY TABLE FOR SELECTED DEVICE
      ═══════════════════════════════════════════════════════════════════════ */}
      {viewLevel === "days" && selectedDevice && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          {/* Selected Device Summary Header Card */}
          <div
            style={{
              background: "rgba(6, 182, 212, 0.05)",
              border: "1px solid rgba(6, 182, 212, 0.2)",
              borderRadius: "12px",
              padding: "1.2rem 1.5rem",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "1rem",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <span style={{ fontSize: "2rem" }}>💻</span>
              <div>
                <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--text-main)" }}>
                  {selectedDevice.hostname}
                </div>
                <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", fontFamily: "monospace" }}>
                  Device ID: {selectedDevice.id} • OS: {selectedDevice.os}
                </div>
              </div>
            </div>

            <div style={{ display: "flex", gap: "2rem", alignItems: "center", flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Total Active Days</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--accent-cyan)" }}>
                  {data?.device_days?.length || selectedDevice.total_days || 1} Days
                </div>
              </div>
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Cumulative Work Time</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--accent-emerald)" }}>
                  {formatSeconds(selectedDevice.total_active_seconds)}
                </div>
              </div>
              <div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Average Focus</div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--accent-indigo)" }}>
                  {selectedDevice.avg_productive_share || 0}%
                </div>
              </div>
            </div>
          </div>

          {/* Days Table Card */}
          <div
            className="card"
            style={{
              background: "var(--bg-card)",
              borderRadius: "12px",
              border: "1px solid var(--border-color)",
              padding: "1.5rem",
            }}
          >
            <div style={{ marginBottom: "1rem" }}>
              <h3 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 700 }}>
                Daily Activity Calendar
              </h3>
              <span style={{ fontSize: "0.82rem", color: "var(--text-muted)" }}>
                Click on any calendar day to inspect its full second-by-second 24-hour timeline and application usage.
              </span>
            </div>

            <div style={{ overflowX: "auto" }}>
              <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border-color)", color: "var(--text-muted)", fontSize: "0.82rem" }}>
                    <th style={{ padding: "12px 10px" }}>Calendar Date</th>
                    <th style={{ padding: "12px 10px" }}>Active Work Time</th>
                    <th style={{ padding: "12px 10px" }}>Idle / Away Time</th>
                    <th style={{ padding: "12px 10px" }}>Focus Percentage</th>
                    <th style={{ padding: "12px 10px" }}>Screenshot Proofs</th>
                    <th style={{ padding: "12px 10px", textAlign: "right" }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.device_days && data.device_days.length > 0 ? (
                    data.device_days.map((day: ProductivityDaySummary) => {
                      const isToday = day.date === new Date().toISOString().split("T")[0];
                      const isYesterday =
                        day.date === new Date(Date.now() - 86400000).toISOString().split("T")[0];

                      return (
                        <tr
                          key={day.date}
                          onClick={() => handleSelectDay(day.date)}
                          style={{
                            borderBottom: "1px solid rgba(255, 255, 255, 0.05)",
                            cursor: "pointer",
                            transition: "background 0.15s ease",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background = "rgba(255, 255, 255, 0.03)";
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = "transparent";
                          }}
                        >
                          <td style={{ padding: "14px 10px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                              <span style={{ fontSize: "1.2rem" }}>📅</span>
                              <div>
                                <div style={{ fontWeight: 700, color: "var(--text-main)", fontSize: "0.95rem" }}>
                                  {day.date}
                                </div>
                                <div>
                                  {isToday && (
                                    <span style={{ fontSize: "0.7rem", padding: "1px 6px", borderRadius: "4px", background: "rgba(16, 185, 129, 0.2)", color: "var(--accent-emerald)", fontWeight: 700 }}>
                                      Today
                                    </span>
                                  )}
                                  {isYesterday && (
                                    <span style={{ fontSize: "0.7rem", padding: "1px 6px", borderRadius: "4px", background: "rgba(6, 182, 212, 0.2)", color: "var(--accent-cyan)", fontWeight: 700 }}>
                                      Yesterday
                                    </span>
                                  )}
                                </div>
                              </div>
                            </div>
                          </td>

                          <td style={{ padding: "14px 10px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                              <span style={{ fontWeight: 700, color: "var(--accent-emerald)", fontSize: "0.92rem", minWidth: "70px" }}>
                                {formatSeconds(day.active_seconds)}
                              </span>
                              <div style={{ width: "120px", height: "6px", background: "rgba(255, 255, 255, 0.08)", borderRadius: "3px", overflow: "hidden" }}>
                                <div
                                  style={{
                                    width: `${Math.min(100, (day.active_seconds / 28800) * 100)}%`,
                                    height: "100%",
                                    background: "#10b981",
                                  }}
                                />
                              </div>
                            </div>
                          </td>

                          <td style={{ padding: "14px 10px", color: "var(--accent-amber)", fontWeight: 600, fontSize: "0.9rem" }}>
                            {formatSeconds(day.idle_seconds)}
                          </td>

                          <td style={{ padding: "14px 10px" }}>
                            <span
                              className="badge-classification classification-productive"
                              style={{ fontSize: "0.78rem" }}
                            >
                              {day.productive_share}% Focus
                            </span>
                          </td>

                          <td style={{ padding: "14px 10px", color: "var(--text-main)", fontWeight: 600, fontSize: "0.88rem" }}>
                            📷 {day.total_screenshots || 0} Captures
                          </td>

                          <td style={{ padding: "14px 10px", textAlign: "right" }}>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleSelectDay(day.date);
                              }}
                              style={{
                                background: "rgba(6, 182, 212, 0.15)",
                                color: "var(--accent-cyan)",
                                border: "1px solid rgba(6, 182, 212, 0.3)",
                                padding: "6px 12px",
                                borderRadius: "6px",
                                fontSize: "0.8rem",
                                fontWeight: 600,
                                cursor: "pointer",
                                transition: "all 0.15s ease",
                              }}
                            >
                              View 24h Breakdown →
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan={6} style={{ textAlign: "center", padding: "3rem", color: "var(--text-muted)" }}>
                        No activity records found for this laptop.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          LEVEL 3: FULL 24-HOUR DETAILED PRODUCTIVITY BREAKDOWN (FOR SELECTED DAY)
      ═══════════════════════════════════════════════════════════════════════ */}
      {viewLevel === "detail" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          {/* Quick Date Bar */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "1rem",
              background: "var(--bg-card)",
              padding: "10px 16px",
              borderRadius: "8px",
              border: "1px solid var(--border-color)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <span style={{ fontSize: "0.85rem", color: "var(--text-muted)", fontWeight: 600 }}>
                Jump to Date:
              </span>
              <div style={{ display: "flex", gap: "4px" }}>
                {quickDates.map((q) => (
                  <button
                    key={q.value}
                    onClick={() => {
                      setSelectedDate(q.value);
                      loadProductivity(selectedDevice?.id, q.value);
                    }}
                    style={{
                      padding: "5px 10px",
                      borderRadius: "6px",
                      fontSize: "0.78rem",
                      fontWeight: 600,
                      cursor: "pointer",
                      background:
                        selectedDate === q.value
                          ? "var(--accent-cyan)"
                          : "rgba(255, 255, 255, 0.05)",
                      color: selectedDate === q.value ? "#0a0e17" : "var(--text-main)",
                      border: "1px solid var(--border-color)",
                    }}
                  >
                    {q.label}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <input
                type="date"
                value={selectedDate}
                onChange={(e) => {
                  setSelectedDate(e.target.value);
                  loadProductivity(selectedDevice?.id, e.target.value);
                }}
                style={{
                  background: "var(--bg-main)",
                  color: "var(--text-main)",
                  border: "1px solid var(--border-color)",
                  padding: "5px 10px",
                  borderRadius: "6px",
                  fontSize: "0.82rem",
                  cursor: "pointer",
                }}
              />
            </div>
          </div>

          {/* 5 KPI Metric Tiles */}
          <div
            className="grid-5"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "1rem",
            }}
          >
            <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(16, 185, 129, 0.2)" }}>
              <div className="stat-label">🟢 Total Active Work</div>
              <div className="stat-value" style={{ color: "var(--accent-emerald)" }}>
                {formatSeconds(data?.summary?.active_seconds || 0)}
              </div>
              <div className="stat-subtext">Direct keyboard &amp; window focus</div>
            </div>

            <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(245, 158, 11, 0.2)" }}>
              <div className="stat-label">🟡 Inactivity / Idle</div>
              <div className="stat-value" style={{ color: "var(--accent-amber)" }}>
                {formatSeconds(data?.summary?.idle_seconds || 0)}
              </div>
              <div className="stat-subtext">Away from keyboard / pauses</div>
            </div>

            <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(6, 182, 212, 0.2)" }}>
              <div className="stat-label">🎯 Focus Share</div>
              <div className="stat-value" style={{ color: "var(--accent-cyan)" }}>
                {data?.summary?.productive_share ?? 0}%
              </div>
              <div className="stat-subtext">Classified work application time</div>
            </div>

            <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(139, 92, 246, 0.2)" }}>
              <div className="stat-label">🏆 Leading App</div>
              <div
                className="stat-value"
                style={{
                  color: "var(--accent-indigo)",
                  fontSize: "1.3rem",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {topApp ? topApp.display_name : "None"}
              </div>
              <div className="stat-subtext">
                {topApp ? `${formatSeconds(topApp.total_seconds)} (${topApp.percentage}%)` : "No activity recorded"}
              </div>
            </div>

            <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(255, 255, 255, 0.1)" }}>
              <div className="stat-label">📷 Verified Proofs</div>
              <div className="stat-value" style={{ color: "var(--text-main)" }}>
                {data?.summary?.total_screenshots || 0}
              </div>
              <div className="stat-subtext">S3 stored screenshot captures</div>
            </div>
          </div>

          {/* Interactive Continuous 24-Hour Timeline Bar (00:00 to 23:59) */}
          <div
            className="card"
            style={{
              background: "var(--bg-card)",
              borderRadius: "12px",
              border: "1px solid var(--border-color)",
              padding: "1.5rem",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "1rem",
                flexWrap: "wrap",
                gap: "0.5rem",
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700 }}>
                  Continuous 24-Hour Activity Timeline
                </h3>
                <span style={{ fontSize: "0.82rem", color: "var(--text-muted)" }}>
                  Full day breakdown from 00:00 to 23:59. Hover segments for window &amp; tab details.
                </span>
              </div>

              {/* Legend */}
              <div style={{ display: "flex", gap: "12px", fontSize: "0.78rem" }}>
                <span style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                  <span style={{ width: "10px", height: "10px", borderRadius: "2px", background: "#10b981" }} />
                  Productive
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                  <span style={{ width: "10px", height: "10px", borderRadius: "2px", background: "#3b82f6" }} />
                  Neutral
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                  <span style={{ width: "10px", height: "10px", borderRadius: "2px", background: "#ef4444" }} />
                  Distracting
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                  <span style={{ width: "10px", height: "10px", borderRadius: "2px", background: "#f59e0b" }} />
                  Idle
                </span>
                <span style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                  <span style={{ width: "10px", height: "10px", borderRadius: "2px", background: "#1f293d" }} />
                  Offline
                </span>
              </div>
            </div>

            {/* 24-Hour Bar Container */}
            <div
              style={{
                position: "relative",
                width: "100%",
                height: "44px",
                background: "#121826",
                borderRadius: "8px",
                overflow: "hidden",
                border: "1px solid rgba(255, 255, 255, 0.08)",
                display: "flex",
              }}
            >
              {data?.timeline_intervals && data.timeline_intervals.length > 0 ? (
                data.timeline_intervals.map((inv) => {
                  const baseDateStr = data.date;
                  const start = new Date(inv.started_at);
                  const dayStart = new Date(`${baseDateStr}T00:00:00Z`);
                  const invStartSec = Math.max(0, (start.getTime() - dayStart.getTime()) / 1000);
                  const leftPercent = (invStartSec / 86400) * 100;
                  const widthPercent = Math.max(0.2, (inv.duration_seconds / 86400) * 100);

                  let bgColor = "#1f293d";
                  if (inv.state === "idle") {
                    bgColor = "#f59e0b";
                  } else if (inv.state === "active") {
                    if (inv.classification === "productive") bgColor = "#10b981";
                    else if (inv.classification === "distracting") bgColor = "#ef4444";
                    else bgColor = "#3b82f6";
                  }

                  return (
                    <div
                      key={inv.id}
                      onMouseEnter={() => setHoveredInterval(inv)}
                      onMouseLeave={() => setHoveredInterval(null)}
                      style={{
                        position: "absolute",
                        left: `${leftPercent}%`,
                        width: `${widthPercent}%`,
                        height: "100%",
                        background: bgColor,
                        cursor: "pointer",
                        transition: "opacity 0.15s ease",
                        opacity: hoveredInterval && hoveredInterval.id === inv.id ? 1 : 0.85,
                      }}
                    />
                  );
                })
              ) : (
                <div
                  style={{
                    width: "100%",
                    height: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "var(--text-subtle)",
                    fontSize: "0.85rem",
                  }}
                >
                  No activity intervals recorded on this date.
                </div>
              )}

              {/* Scrubber vertical needle */}
              <div
                style={{
                  position: "absolute",
                  left: `${(scrubberMinute / 1440) * 100}%`,
                  top: 0,
                  bottom: 0,
                  width: "2px",
                  background: "#06b6d4",
                  boxShadow: "0 0 8px #06b6d4",
                  pointerEvents: "none",
                }}
              />
            </div>

            {/* Hour markers row (00:00 to 24:00) */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginTop: "6px",
                fontSize: "0.75rem",
                color: "var(--text-subtle)",
                fontFamily: "monospace",
              }}
            >
              <span>00:00</span>
              <span>03:00</span>
              <span>06:00</span>
              <span>09:00</span>
              <span>12:00</span>
              <span>15:00</span>
              <span>18:00</span>
              <span>21:00</span>
              <span>23:59</span>
            </div>

            {/* Timeline Scrubber slider input */}
            <div style={{ marginTop: "1.2rem", display: "flex", alignItems: "center", gap: "1rem" }}>
              <span style={{ fontSize: "0.82rem", color: "var(--text-muted)", minWidth: "140px" }}>
                Scrub Time: <strong style={{ color: "var(--accent-cyan)", fontSize: "0.95rem" }}>{scrubberTimeStr}</strong>
              </span>
              <input
                type="range"
                min="0"
                max="1439"
                value={scrubberMinute}
                onChange={(e) => setScrubberMinute(Number(e.target.value))}
                style={{ flex: 1, accentColor: "var(--accent-cyan)", cursor: "pointer" }}
              />
            </div>

            {/* Hover / Scrubber Detail Inspector Card */}
            {(hoveredInterval || activeAtScrubber) && (
              <div
                style={{
                  marginTop: "1rem",
                  background: "rgba(6, 182, 212, 0.06)",
                  border: "1px solid rgba(6, 182, 212, 0.2)",
                  padding: "0.9rem 1.2rem",
                  borderRadius: "8px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "1rem",
                }}
              >
                {(() => {
                  const active = hoveredInterval || activeAtScrubber;
                  return (
                    <>
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span style={{ fontWeight: 700, fontSize: "0.95rem", color: "var(--text-main)" }}>
                            {active.app_identifier}
                          </span>
                          <span
                            className={`badge-classification classification-${active.classification || "neutral"}`}
                            style={{ fontSize: "0.75rem", textTransform: "capitalize" }}
                          >
                            {active.classification || "neutral"}
                          </span>
                          <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                            State: <strong>{active.state.toUpperCase()}</strong>
                          </span>
                        </div>
                        <div style={{ fontSize: "0.85rem", color: "var(--accent-cyan)", marginTop: "4px" }}>
                          {active.window_title ? `"${active.window_title}"` : "No window title recorded"}
                        </div>
                      </div>

                      <div style={{ textAlign: "right" }}>
                        <div style={{ fontSize: "0.9rem", fontWeight: 700, color: "var(--text-main)" }}>
                          Duration: {formatSeconds(active.duration_seconds)}
                        </div>
                        <div style={{ fontSize: "0.78rem", color: "var(--text-subtle)", marginTop: "2px" }}>
                          {new Date(active.started_at).toLocaleTimeString()} – {new Date(active.ended_at).toLocaleTimeString()}
                        </div>
                      </div>
                    </>
                  );
                })()}
              </div>
            )}
          </div>

          {/* Hourly Workload Distribution */}
          <div
            className="card"
            style={{
              background: "var(--bg-card)",
              borderRadius: "12px",
              border: "1px solid var(--border-color)",
              padding: "1.5rem",
            }}
          >
            <div style={{ marginBottom: "1rem" }}>
              <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700 }}>
                Hourly Workload &amp; Focus Distribution
              </h3>
              <span style={{ fontSize: "0.82rem", color: "var(--text-muted)" }}>
                Active work time (green) vs idle pauses (amber) for every hour of the 24-hour day.
              </span>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(24, 1fr)",
                gap: "4px",
                alignItems: "flex-end",
                height: "120px",
                paddingTop: "10px",
                borderBottom: "1px solid rgba(255, 255, 255, 0.1)",
              }}
            >
              {data?.hourly_activity?.map((h) => {
                const maxSecondsPerHour = 3600;
                const activeHeight = Math.min(100, (h.active_seconds / maxSecondsPerHour) * 100);
                const idleHeight = Math.min(100 - activeHeight, (h.idle_seconds / maxSecondsPerHour) * 100);

                return (
                  <div
                    key={h.hour}
                    title={`${h.label}: ${formatSeconds(h.active_seconds)} Active, ${formatSeconds(h.idle_seconds)} Idle`}
                    style={{
                      height: "100%",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "flex-end",
                      cursor: "pointer",
                    }}
                  >
                    {idleHeight > 0 && (
                      <div
                        style={{
                          height: `${idleHeight}%`,
                          background: "#f59e0b",
                          borderRadius: "2px 2px 0 0",
                          opacity: 0.85,
                        }}
                      />
                    )}
                    {activeHeight > 0 && (
                      <div
                        style={{
                          height: `${activeHeight}%`,
                          background: "#10b981",
                          borderRadius: idleHeight > 0 ? "0" : "2px 2px 0 0",
                        }}
                      />
                    )}
                    {activeHeight === 0 && idleHeight === 0 && (
                      <div
                        style={{
                          height: "3px",
                          background: "rgba(255, 255, 255, 0.05)",
                          borderRadius: "1px",
                        }}
                      />
                    )}
                  </div>
                );
              })}
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(24, 1fr)",
                gap: "4px",
                marginTop: "6px",
                fontSize: "0.68rem",
                color: "var(--text-subtle)",
                textAlign: "center",
              }}
            >
              {data?.hourly_activity?.map((h) => (
                <span key={h.hour}>{h.hour % 3 === 0 ? `${h.hour}h` : ""}</span>
              ))}
            </div>
          </div>

          {/* Application Leaderboard & Browser Tab Breakdown */}
          <div
            className="card"
            style={{
              background: "var(--bg-card)",
              borderRadius: "12px",
              border: "1px solid var(--border-color)",
              padding: "1.5rem",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "1rem",
                marginBottom: "1.2rem",
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700 }}>
                  Application &amp; In-Browser Tab Analytics
                </h3>
                <span style={{ fontSize: "0.82rem", color: "var(--text-muted)" }}>
                  Ranked screen time per application. Expand web browsers to inspect individual tabs and domains.
                </span>
              </div>

              {/* Search + Category Filter */}
              <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
                <input
                  type="text"
                  placeholder="Search apps or website tabs..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{
                    background: "var(--bg-main)",
                    color: "var(--text-main)",
                    border: "1px solid var(--border-color)",
                    padding: "7px 12px",
                    borderRadius: "6px",
                    fontSize: "0.85rem",
                    minWidth: "220px",
                  }}
                />

                <select
                  value={selectedCategory}
                  onChange={(e) => setSelectedCategory(e.target.value)}
                  style={{
                    background: "var(--bg-main)",
                    color: "var(--text-main)",
                    border: "1px solid var(--border-color)",
                    padding: "7px 12px",
                    borderRadius: "6px",
                    fontSize: "0.85rem",
                    cursor: "pointer",
                  }}
                >
                  <option value="All">All Categories</option>
                  <option value="Development">Development</option>
                  <option value="Web Browsing">Web Browsing</option>
                  <option value="Productivity & Docs">Productivity & Docs</option>
                  <option value="Communication">Communication</option>
                  <option value="Entertainment & Social">Entertainment</option>
                  <option value="Other Utilities">Other</option>
                </select>
              </div>
            </div>

            {/* Application List Table */}
            <div style={{ overflowX: "auto" }}>
              <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border-color)", color: "var(--text-muted)", fontSize: "0.82rem" }}>
                    <th style={{ padding: "10px" }}>Application / Process</th>
                    <th style={{ padding: "10px" }}>Category</th>
                    <th style={{ padding: "10px" }}>Duration</th>
                    <th style={{ padding: "10px" }}>Active Timing Window</th>
                    <th style={{ padding: "10px" }}>% of Day</th>
                    <th style={{ padding: "10px" }}>Classification</th>
                    <th style={{ padding: "10px", textAlign: "right" }}>Timing &amp; Details</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredApps.length > 0 ? (
                    filteredApps.map((app) => {
                      const isExpanded = !!expandedApps[app.app_identifier];
                      const hasTabs = app.tabs && app.tabs.length > 0;
                      const hasSessions = app.sessions && app.sessions.length > 0;
                      const canExpand = hasTabs || hasSessions;

                      return (
                        <React.Fragment key={app.app_identifier}>
                          <tr
                            style={{
                              borderBottom: "1px solid rgba(255, 255, 255, 0.05)",
                              cursor: canExpand ? "pointer" : "default",
                              background: isExpanded ? "rgba(255, 255, 255, 0.02)" : "transparent",
                            }}
                            onClick={() => canExpand && toggleExpand(app.app_identifier)}
                          >
                            <td style={{ padding: "12px 10px" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                                <span style={{ fontSize: "1.2rem" }}>
                                  {app.is_browser ? "🌐" : app.category === "Development" ? "💻" : app.category === "Communication" ? "💬" : "📁"}
                                </span>
                                <div>
                                  <div style={{ fontWeight: 600, color: "var(--text-main)", fontSize: "0.92rem" }}>
                                    {app.display_name}
                                  </div>
                                  <div style={{ fontSize: "0.75rem", color: "var(--text-subtle)", fontFamily: "monospace" }}>
                                    {app.app_identifier}
                                  </div>
                                </div>
                              </div>
                            </td>

                            <td style={{ padding: "12px 10px", fontSize: "0.85rem", color: "var(--text-muted)" }}>
                              {app.category}
                            </td>

                            <td style={{ padding: "12px 10px", fontWeight: 700, fontSize: "0.92rem", color: "var(--text-main)" }}>
                              {formatSeconds(app.total_seconds)}
                            </td>

                            {/* App Wise Timing Window */}
                            <td style={{ padding: "12px 10px" }}>
                              <div style={{ display: "flex", flexDirection: "column" }}>
                                <span style={{ fontSize: "0.84rem", fontWeight: 600, color: "var(--accent-cyan)", fontFamily: "monospace" }}>
                                  {app.first_used && app.last_used
                                    ? `${formatTimeOnly(app.first_used)} – ${formatTimeOnly(app.last_used)}`
                                    : "—"}
                                </span>
                                <span style={{ fontSize: "0.74rem", color: "var(--text-muted)", marginTop: "2px" }}>
                                  {app.session_count || (app.sessions ? app.sessions.length : 1)} session{(app.session_count || 1) !== 1 ? "s" : ""}
                                </span>
                              </div>
                            </td>

                            <td style={{ padding: "12px 10px", width: "150px" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                <div
                                  style={{
                                    flex: 1,
                                    height: "6px",
                                    background: "rgba(255, 255, 255, 0.08)",
                                    borderRadius: "3px",
                                    overflow: "hidden",
                                  }}
                                >
                                  <div
                                    style={{
                                      width: `${app.percentage}%`,
                                      height: "100%",
                                      background:
                                        app.classification === "productive"
                                          ? "#10b981"
                                          : app.classification === "distracting"
                                          ? "#ef4444"
                                          : "#3b82f6",
                                    }}
                                  />
                                </div>
                                <span style={{ fontSize: "0.82rem", color: "var(--text-muted)", minWidth: "35px" }}>
                                  {app.percentage}%
                                </span>
                              </div>
                            </td>

                            <td style={{ padding: "12px 10px" }}>
                              <span
                                className={`badge-classification classification-${app.classification}`}
                                style={{ fontSize: "0.78rem", textTransform: "capitalize" }}
                              >
                                {app.classification}
                              </span>
                            </td>

                            <td style={{ padding: "12px 10px", textAlign: "right" }}>
                              {canExpand ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    toggleExpand(app.app_identifier);
                                  }}
                                  style={{
                                    background: isExpanded ? "var(--accent-cyan)" : "rgba(255, 255, 255, 0.06)",
                                    color: isExpanded ? "#0a0e17" : "var(--text-main)",
                                    border: "1px solid var(--border-color)",
                                    borderRadius: "6px",
                                    padding: "5px 12px",
                                    fontSize: "0.78rem",
                                    fontWeight: 600,
                                    cursor: "pointer",
                                    transition: "all 0.15s ease",
                                  }}
                                >
                                  {isExpanded
                                    ? "▲ Hide Timing"
                                    : hasTabs
                                    ? `▼ Timing & Tabs (${app.tabs.length})`
                                    : `▼ View Timing (${app.sessions?.length || 1})`}
                                </button>
                              ) : (
                                <span style={{ fontSize: "0.78rem", color: "var(--text-subtle)" }}>—</span>
                              )}
                            </td>
                          </tr>

                          {/* Expandable Session Timings & Tabs Breakdown */}
                          {isExpanded && canExpand && (
                            <tr>
                              <td colSpan={7} style={{ padding: "0 14px 18px 40px", background: "rgba(0, 0, 0, 0.25)" }}>
                                <div
                                  style={{
                                    borderLeft: "3px solid var(--accent-cyan)",
                                    paddingLeft: "16px",
                                    marginTop: "12px",
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: "16px",
                                  }}
                                >
                                  {/* 1. 24-Hour App Focus Timeline Lane */}
                                  <div>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                                      <span style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--accent-cyan)" }}>
                                        🕒 24-Hour Focus Lane for {app.display_name}
                                      </span>
                                      <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                                        Active Span: {formatTimeOnly(app.first_used)} – {formatTimeOnly(app.last_used)} • {app.sessions?.length || 1} session{(app.sessions?.length || 1) > 1 ? "s" : ""}
                                      </span>
                                    </div>

                                    {/* Visual Gantt Bar across 24 hours */}
                                    <div
                                      style={{
                                        position: "relative",
                                        height: "26px",
                                        background: "rgba(255, 255, 255, 0.04)",
                                        borderRadius: "6px",
                                        border: "1px solid rgba(255, 255, 255, 0.08)",
                                        overflow: "hidden",
                                      }}
                                    >
                                      {app.sessions?.map((sess, sIdx) => {
                                        const sDate = new Date(sess.start);
                                        const eDate = new Date(sess.end);
                                        const startM = sDate.getHours() * 60 + sDate.getMinutes() + sDate.getSeconds() / 60;
                                        const endM = eDate.getHours() * 60 + eDate.getMinutes() + eDate.getSeconds() / 60;
                                        const left = Math.max(0, Math.min(100, (startM / 1440) * 100));
                                        const width = Math.max(0.6, Math.min(100 - left, ((Math.max(endM, startM + 1) - startM) / 1440) * 100));
                                        return (
                                          <div
                                            key={sIdx}
                                            title={`Session ${sIdx + 1}: ${formatTimeWithSeconds(sess.start)} – ${formatTimeWithSeconds(sess.end)} (${formatSeconds(sess.duration_seconds)})${sess.window_title ? ` | "${sess.window_title}"` : ""}`}
                                            style={{
                                              position: "absolute",
                                              left: `${left}%`,
                                              width: `${width}%`,
                                              top: "3px",
                                              bottom: "3px",
                                              background:
                                                app.classification === "productive"
                                                  ? "#10b981"
                                                  : app.classification === "distracting"
                                                  ? "#ef4444"
                                                  : "#06b6d4",
                                              borderRadius: "3px",
                                              opacity: 0.9,
                                              cursor: "pointer",
                                            }}
                                          />
                                        );
                                      })}
                                    </div>
                                    {/* 24-Hour Markers */}
                                    <div
                                      style={{
                                        display: "flex",
                                        justifyContent: "space-between",
                                        marginTop: "4px",
                                        fontSize: "0.7rem",
                                        color: "var(--text-subtle)",
                                        fontFamily: "monospace",
                                      }}
                                    >
                                      <span>00:00</span>
                                      <span>04:00</span>
                                      <span>08:00</span>
                                      <span>12:00</span>
                                      <span>16:00</span>
                                      <span>20:00</span>
                                      <span>23:59</span>
                                    </div>
                                  </div>

                                  {/* 2. Detailed Session Timings Table */}
                                  <div>
                                    <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--text-main)", marginBottom: "8px" }}>
                                      ⏱️ Session Timings &amp; Focused Windows ({app.sessions?.length || 0} Sessions)
                                    </div>
                                    <div
                                      style={{
                                        maxHeight: "220px",
                                        overflowY: "auto",
                                        border: "1px solid rgba(255, 255, 255, 0.06)",
                                        borderRadius: "8px",
                                        background: "rgba(0, 0, 0, 0.2)",
                                      }}
                                    >
                                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
                                        <thead>
                                          <tr
                                            style={{
                                              textAlign: "left",
                                              borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
                                              color: "var(--text-muted)",
                                              background: "rgba(255, 255, 255, 0.02)",
                                            }}
                                          >
                                            <th style={{ padding: "8px 12px", width: "70px" }}>Session</th>
                                            <th style={{ padding: "8px 12px", width: "200px" }}>Start – End Time</th>
                                            <th style={{ padding: "8px 12px", width: "110px" }}>Duration</th>
                                            <th style={{ padding: "8px 12px" }}>Active Window / Document</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {app.sessions && app.sessions.length > 0 ? (
                                            app.sessions.map((sess, sIdx) => (
                                              <tr key={sIdx} style={{ borderBottom: "1px solid rgba(255, 255, 255, 0.03)" }}>
                                                <td style={{ padding: "8px 12px", color: "var(--text-muted)", fontWeight: 600 }}>
                                                  #{sIdx + 1}
                                                </td>
                                                <td
                                                  style={{
                                                    padding: "8px 12px",
                                                    color: "var(--accent-cyan)",
                                                    fontFamily: "monospace",
                                                    fontSize: "0.78rem",
                                                  }}
                                                >
                                                  {formatTimeWithSeconds(sess.start)} – {formatTimeWithSeconds(sess.end)}
                                                </td>
                                                <td style={{ padding: "8px 12px", fontWeight: 700, color: "var(--accent-emerald)" }}>
                                                  {formatSeconds(sess.duration_seconds)}
                                                </td>
                                                <td
                                                  style={{
                                                    padding: "8px 12px",
                                                    color: "var(--text-main)",
                                                    maxWidth: "400px",
                                                    overflow: "hidden",
                                                    textOverflow: "ellipsis",
                                                    whiteSpace: "nowrap",
                                                  }}
                                                  title={sess.window_title}
                                                >
                                                  {sess.window_title ? (
                                                    `"${sess.window_title}"`
                                                  ) : (
                                                    <span style={{ color: "var(--text-subtle)", fontStyle: "italic" }}>
                                                      Default window focus
                                                    </span>
                                                  )}
                                                </td>
                                              </tr>
                                            ))
                                          ) : (
                                            <tr>
                                              <td colSpan={4} style={{ padding: "12px", textAlign: "center", color: "var(--text-muted)" }}>
                                                No discrete sessions recorded.
                                              </td>
                                            </tr>
                                          )}
                                        </tbody>
                                      </table>
                                    </div>
                                  </div>

                                  {/* 3. In-Browser Tabs & Pages (if applicable) */}
                                  {hasTabs && (
                                    <div>
                                      <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--accent-cyan)", marginBottom: "8px" }}>
                                        🌐 Active Browser Tabs &amp; Pages ({app.tabs.length})
                                      </div>
                                      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                                        {app.tabs.map((tab, idx) => (
                                          <div
                                            key={idx}
                                            style={{
                                              display: "flex",
                                              justifyContent: "space-between",
                                              alignItems: "center",
                                              background: "rgba(255, 255, 255, 0.03)",
                                              padding: "8px 12px",
                                              borderRadius: "6px",
                                              border: "1px solid rgba(255, 255, 255, 0.04)",
                                            }}
                                          >
                                            <div style={{ display: "flex", alignItems: "center", gap: "8px", maxWidth: "70%" }}>
                                              <span
                                                style={{
                                                  fontSize: "0.75rem",
                                                  padding: "2px 6px",
                                                  borderRadius: "4px",
                                                  background: "rgba(6, 182, 212, 0.15)",
                                                  color: "var(--accent-cyan)",
                                                  fontWeight: 600,
                                                }}
                                              >
                                                {tab.domain}
                                              </span>
                                              <span
                                                style={{
                                                  fontSize: "0.84rem",
                                                  color: "var(--text-main)",
                                                  whiteSpace: "nowrap",
                                                  overflow: "hidden",
                                                  textOverflow: "ellipsis",
                                                }}
                                                title={tab.tab_title}
                                              >
                                                {tab.tab_title}
                                              </span>
                                            </div>

                                            <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
                                              <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                                                {tab.category}
                                              </span>
                                              <span style={{ fontWeight: 700, fontSize: "0.85rem", color: "var(--accent-emerald)" }}>
                                                {formatSeconds(tab.total_seconds)}
                                              </span>
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan={7} style={{ textAlign: "center", padding: "2rem", color: "var(--text-muted)" }}>
                        No applications matched your search query.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
