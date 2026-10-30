import React, { useEffect, useState, useMemo } from "react";
import { api } from "../services/api";
import { ProductivitySummaryData, AppLeaderboardItem } from "../types";

export const ProductivityDashboard: React.FC = () => {
  const [data, setData] = useState<ProductivitySummaryData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("");
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
      if (res.device_id && !selectedDeviceId) {
        setSelectedDeviceId(res.device_id);
      }
    } catch (err) {
      console.error("Failed to load 24h productivity summary:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProductivity(selectedDeviceId || undefined, selectedDate);
  }, [selectedDeviceId, selectedDate]);

  const toggleExpand = (appId: string) => {
    setExpandedApps((prev) => ({ ...prev, [appId]: !prev[appId] }));
  };

  const formatSeconds = (sec: number): string => {
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* 1. Header & Controls */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "1rem",
          background: "var(--bg-card)",
          padding: "1.25rem 1.5rem",
          borderRadius: "12px",
          border: "1px solid var(--border-color)",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ fontSize: "1.6rem" }}>📊</span>
            <div>
              <h2 style={{ fontSize: "1.4rem", margin: 0, fontWeight: 700 }}>
                24-Hour Productivity &amp; Screen Time Hub
              </h2>
              <p
                style={{
                  margin: "3px 0 0",
                  fontSize: "0.85rem",
                  color: "var(--text-muted)",
                }}
              >
                Second-by-second application focus, browser tab analytics, and activity timeline.
              </p>
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
          {/* Device selector */}
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>Device:</span>
            <select
              value={selectedDeviceId}
              onChange={(e) => setSelectedDeviceId(e.target.value)}
              style={{
                background: "var(--bg-main)",
                color: "var(--text-main)",
                border: "1px solid var(--border-color)",
                padding: "8px 12px",
                borderRadius: "8px",
                fontSize: "0.88rem",
                cursor: "pointer",
              }}
            >
              {data?.available_devices?.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.hostname} ({d.os})
                </option>
              ))}
            </select>
          </div>

          {/* Quick Date Pills */}
          <div style={{ display: "flex", gap: "4px" }}>
            {quickDates.map((q) => (
              <button
                key={q.value}
                onClick={() => setSelectedDate(q.value)}
                style={{
                  padding: "6px 12px",
                  borderRadius: "6px",
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  cursor: "pointer",
                  background:
                    selectedDate === q.value
                      ? "var(--accent-cyan)"
                      : "rgba(255, 255, 255, 0.05)",
                  color: selectedDate === q.value ? "#0a0e17" : "var(--text-main)",
                  border: "1px solid var(--border-color)",
                  transition: "all 0.15s ease",
                }}
              >
                {q.label}
              </button>
            ))}
          </div>

          {/* Date Picker Input */}
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            style={{
              background: "var(--bg-main)",
              color: "var(--text-main)",
              border: "1px solid var(--border-color)",
              padding: "7px 10px",
              borderRadius: "8px",
              fontSize: "0.85rem",
              cursor: "pointer",
            }}
          />

          {/* Refresh Button */}
          <button
            onClick={() => loadProductivity(selectedDeviceId, selectedDate)}
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

      {/* 2. Key Productivity KPI Metric Tiles */}
      <div className="grid-5" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem" }}>
        {/* Active Time */}
        <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(16, 185, 129, 0.2)" }}>
          <div className="stat-label">🟢 Total Active Work</div>
          <div className="stat-value" style={{ color: "var(--accent-emerald)" }}>
            {formatSeconds(data?.summary?.active_seconds || 0)}
          </div>
          <div className="stat-subtext">Direct keyboard &amp; window focus</div>
        </div>

        {/* Idle Time */}
        <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(245, 158, 11, 0.2)" }}>
          <div className="stat-label">🟡 Inactivity / Idle</div>
          <div className="stat-value" style={{ color: "var(--accent-amber)" }}>
            {formatSeconds(data?.summary?.idle_seconds || 0)}
          </div>
          <div className="stat-subtext">Away from keyboard / breaks</div>
        </div>

        {/* Productive Focus Share */}
        <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(6, 182, 212, 0.2)" }}>
          <div className="stat-label">🎯 Focus Share</div>
          <div className="stat-value" style={{ color: "var(--accent-cyan)" }}>
            {data?.summary?.productive_share ?? 0}%
          </div>
          <div className="stat-subtext">Classified work application time</div>
        </div>

        {/* Top App */}
        <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(139, 92, 246, 0.2)" }}>
          <div className="stat-label">🏆 Leading App</div>
          <div className="stat-value" style={{ color: "var(--accent-indigo)", fontSize: "1.3rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {topApp ? topApp.display_name : "None"}
          </div>
          <div className="stat-subtext">
            {topApp ? `${formatSeconds(topApp.total_seconds)} (${topApp.percentage}%)` : "No activity recorded"}
          </div>
        </div>

        {/* Screenshots */}
        <div className="stat-tile" style={{ background: "var(--bg-card)", border: "1px solid rgba(255, 255, 255, 0.1)" }}>
          <div className="stat-label">📷 Verified Proofs</div>
          <div className="stat-value" style={{ color: "var(--text-main)" }}>
            {data?.summary?.total_screenshots || 0}
          </div>
          <div className="stat-subtext">S3 stored screenshot captures</div>
        </div>
      </div>

      {/* 3. Interactive Continuous 24-Hour Timeline Bar (00:00 to 23:59) */}
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

              let bgColor = "#1f293d"; // default offline/system
              if (inv.state === "idle") {
                bgColor = "#f59e0b"; // yellow
              } else if (inv.state === "active") {
                if (inv.classification === "productive") bgColor = "#10b981"; // green
                else if (inv.classification === "distracting") bgColor = "#ef4444"; // red
                else bgColor = "#3b82f6"; // blue neutral
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

      {/* 4. Hourly Productivity Curve (24 Bar Columns) */}
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

      {/* 5. Application Leaderboard & Browser Tab Breakdown */}
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
                <th style={{ padding: "10px" }}>% of Day</th>
                <th style={{ padding: "10px" }}>Classification</th>
                <th style={{ padding: "10px", textAlign: "right" }}>Tabs / Windows</th>
              </tr>
            </thead>
            <tbody>
              {filteredApps.length > 0 ? (
                filteredApps.map((app) => {
                  const isExpanded = !!expandedApps[app.app_identifier];
                  const hasTabs = app.tabs && app.tabs.length > 0;

                  return (
                    <React.Fragment key={app.app_identifier}>
                      <tr
                        style={{
                          borderBottom: "1px solid rgba(255, 255, 255, 0.05)",
                          cursor: hasTabs ? "pointer" : "default",
                          background: isExpanded ? "rgba(255, 255, 255, 0.02)" : "transparent",
                        }}
                        onClick={() => hasTabs && toggleExpand(app.app_identifier)}
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

                        <td style={{ padding: "12px 10px", width: "160px" }}>
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
                          {hasTabs ? (
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
                                padding: "4px 10px",
                                fontSize: "0.78rem",
                                fontWeight: 600,
                                cursor: "pointer",
                              }}
                            >
                              {isExpanded ? `▲ Hide (${app.tabs.length})` : `▼ View Tabs (${app.tabs.length})`}
                            </button>
                          ) : (
                            <span style={{ fontSize: "0.78rem", color: "var(--text-subtle)" }}>—</span>
                          )}
                        </td>
                      </tr>

                      {/* Expandable Tabs Sub-table */}
                      {isExpanded && hasTabs && (
                        <tr>
                          <td colSpan={6} style={{ padding: "0 10px 14px 40px", background: "rgba(0, 0, 0, 0.2)" }}>
                            <div
                              style={{
                                borderLeft: "2px solid var(--accent-cyan)",
                                paddingLeft: "15px",
                                marginTop: "8px",
                              }}
                            >
                              <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--accent-cyan)", marginBottom: "8px" }}>
                                Active Browser Tabs &amp; Pages in {app.display_name}:
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
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={6} style={{ textAlign: "center", padding: "2rem", color: "var(--text-muted)" }}>
                    No applications matched your search query.
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
