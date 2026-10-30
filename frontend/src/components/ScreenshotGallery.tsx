import React, { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import { ScreenshotItem } from "../types";

const ScreenshotThumbnail: React.FC<{
  item: ScreenshotItem;
  onClick?: () => void;
}> = ({ item, onClick }) => {
  const [src, setSrc] = useState<string | null>(item.thumbnail_url || item.view_url || null);
  const [loading, setLoading] = useState<boolean>(!item.thumbnail_url && !item.view_url);
  const [failed, setFailed] = useState<boolean>(false);
  const [retried, setRetried] = useState<boolean>(false);

  useEffect(() => {
    if (!item.thumbnail_url && !item.view_url) {
      setLoading(true);
      api
        .getScreenshotViewUrl(item.id)
        .then((res) => {
          if (res && res.view_url) {
            setSrc(res.view_url);
            setFailed(false);
          } else {
            setFailed(true);
          }
        })
        .catch(() => setFailed(true))
        .finally(() => setLoading(false));
    } else {
      setSrc(item.thumbnail_url || item.view_url || null);
      setFailed(false);
    }
  }, [item.id, item.thumbnail_url, item.view_url]);

  const handleError = () => {
    if (!retried) {
      setRetried(true);
      api
        .getScreenshotViewUrl(item.id)
        .then((res) => {
          if (res && res.view_url) {
            setSrc(res.view_url);
          } else {
            setFailed(true);
          }
        })
        .catch(() => setFailed(true));
    } else {
      setFailed(true);
    }
  };

  if (loading) {
    return (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0f172a",
          color: "var(--text-subtle)",
          fontSize: "0.7rem",
        }}
      >
        <span>Loading...</span>
      </div>
    );
  }

  if (failed || !src) {
    return (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "#1e1e24",
          color: "var(--text-subtle)",
          fontSize: "0.68rem",
          gap: "2px",
          textAlign: "center",
          padding: "2px",
        }}
        onClick={onClick}
      >
        <span>🖼️</span>
        <span style={{ fontSize: "0.65rem", color: "var(--text-subtle)" }}>Storage Migrated</span>
      </div>
    );
  }

  return (
    <img
      src={src}
      alt="Capture thumbnail"
      style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
      onError={handleError}
    />
  );
};

export const ScreenshotGallery: React.FC = () => {
  const [screenshots, setScreenshots] = useState<ScreenshotItem[]>([]);
  const [devices, setDevices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // Drill-down State:
  // Level 1: selectedDevice = null -> Shows Devices Table
  // Level 2: selectedDevice != null, selectedDate = null -> Shows Day-wise Table
  // Level 3: selectedDevice != null, selectedDate != null -> Shows Time-wise Screenshots Table
  const [selectedDevice, setSelectedDevice] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  // Modal State for Full Resolution Inspector
  const [activeModalScreenshot, setActiveModalScreenshot] = useState<ScreenshotItem | null>(null);
  const [modalViewUrl, setModalViewUrl] = useState<string | null>(null);
  const [loadingModalUrl, setLoadingModalUrl] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [scRes, devRes] = await Promise.all([
        api.getScreenshots(),
        api.getDevices().catch(() => []),
      ]);
      setScreenshots(scRes.results || []);
      setDevices(devRes || []);
    } catch (err) {
      console.error("Failed to load screenshots or devices", err);
    } finally {
      setLoading(false);
    }
  }

  // Device Map for fast metadata lookup
  const deviceMap = useMemo(() => {
    const map = new Map<string, any>();
    devices.forEach((d) => map.set(d.id, d));
    return map;
  }, [devices]);

  const getDeviceName = (deviceId: string) => {
    const dev = deviceMap.get(deviceId);
    if (dev?.hostname) return dev.hostname;
    const fromSc = screenshots.find((s) => s.device_id === deviceId)?.device_hostname;
    if (fromSc) return fromSc;
    if (deviceId.startsWith("b1a31985")) return "DESKTOP-GO4TUDQ";
    return `Device-${deviceId.slice(0, 8)}`;
  };

  // Group screenshots by Device
  const deviceGroups = useMemo(() => {
    const groups: Record<
      string,
      {
        deviceId: string;
        hostname: string;
        os: string;
        screenshots: ScreenshotItem[];
        firstCapture: string;
        lastCapture: string;
        totalBytes: number;
      }
    > = {};

    screenshots.forEach((sc) => {
      const dId = sc.device_id || "unknown";
      if (!groups[dId]) {
        const dev = deviceMap.get(dId);
        groups[dId] = {
          deviceId: dId,
          hostname: getDeviceName(dId),
          os: dev?.os || "windows",
          screenshots: [],
          firstCapture: sc.captured_at,
          lastCapture: sc.captured_at,
          totalBytes: 0,
        };
      }
      groups[dId].screenshots.push(sc);
      groups[dId].totalBytes += sc.file_size || 0;
      if (new Date(sc.captured_at) < new Date(groups[dId].firstCapture)) {
        groups[dId].firstCapture = sc.captured_at;
      }
      if (new Date(sc.captured_at) > new Date(groups[dId].lastCapture)) {
        groups[dId].lastCapture = sc.captured_at;
      }
    });

    return Object.values(groups);
  }, [screenshots, deviceMap]);

  // Group screenshots for the selected device by Date (YYYY-MM-DD)
  const dayGroups = useMemo(() => {
    if (!selectedDevice) return [];

    const deviceScreenshots = screenshots.filter((s) => s.device_id === selectedDevice);
    const days: Record<
      string,
      {
        dateStr: string; // YYYY-MM-DD
        displayDate: string;
        screenshots: ScreenshotItem[];
        firstTime: string;
        lastTime: string;
        totalBytes: number;
      }
    > = {};

    deviceScreenshots.forEach((sc) => {
      const d = new Date(sc.captured_at);
      const dateStr = d.toISOString().split("T")[0]; // YYYY-MM-DD
      if (!days[dateStr]) {
        days[dateStr] = {
          dateStr,
          displayDate: d.toLocaleDateString(undefined, {
            weekday: "long",
            year: "numeric",
            month: "long",
            day: "numeric",
          }),
          screenshots: [],
          firstTime: sc.captured_at,
          lastTime: sc.captured_at,
          totalBytes: 0,
        };
      }
      days[dateStr].screenshots.push(sc);
      days[dateStr].totalBytes += sc.file_size || 0;
      if (d < new Date(days[dateStr].firstTime)) {
        days[dateStr].firstTime = sc.captured_at;
      }
      if (d > new Date(days[dateStr].lastTime)) {
        days[dateStr].lastTime = sc.captured_at;
      }
    });

    // Sort days descending (most recent day first)
    return Object.values(days).sort((a, b) => b.dateStr.localeCompare(a.dateStr));
  }, [selectedDevice, screenshots]);

  // Time-wise screenshots for selected device & date (sorted chronological)
  const timeScreenshots = useMemo(() => {
    if (!selectedDevice || !selectedDate) return [];
    return screenshots
      .filter((s) => {
        if (s.device_id !== selectedDevice) return false;
        const dStr = new Date(s.captured_at).toISOString().split("T")[0];
        return dStr === selectedDate;
      })
      .sort((a, b) => new Date(b.captured_at).getTime() - new Date(a.captured_at).getTime());
  }, [selectedDevice, selectedDate, screenshots]);

  // Inspect Modal
  async function handleOpenModal(item: ScreenshotItem) {
    setActiveModalScreenshot(item);
    setLoadingModalUrl(true);
    setModalViewUrl(null);
    try {
      if (item.view_url) {
        setModalViewUrl(item.view_url);
      } else {
        const res = await api.getScreenshotViewUrl(item.id);
        setModalViewUrl(res.view_url);
      }
    } catch (err) {
      alert(`Could not load full resolution image: ${err}`);
    } finally {
      setLoadingModalUrl(false);
    }
  }

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return "0 B";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  const formatTimeAgo = (dateStr: string) => {
    try {
      const diffSec = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
      if (diffSec < 60) return "Just now";
      if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
      if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
      return `${Math.floor(diffSec / 86400)}d ago`;
    } catch {
      return dateStr;
    }
  };

  if (loading) {
    return (
      <div style={{ padding: "4rem 2rem", textAlign: "center", color: "var(--text-subtle)" }}>
        <div style={{ fontSize: "1.2rem", fontWeight: 600, marginBottom: "8px" }}>
          Loading S3 Screenshot Vault...
        </div>
        <p style={{ fontSize: "0.85rem" }}>
          Reading device telemetry &amp; captures from <code>s3://captain8959/Monitor/</code>
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      {/* Top Breadcrumbs & Header Bar */}
      <div
        className="card"
        style={{
          padding: "1.2rem 1.6rem",
          background: "linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.9))",
          border: "1px solid rgba(56, 189, 248, 0.25)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
          <div>
            {/* Interactive Breadcrumb Trail */}
            <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.85rem", color: "var(--text-subtle)", marginBottom: "4px" }}>
              <span
                style={{
                  cursor: selectedDevice ? "pointer" : "default",
                  color: selectedDevice ? "var(--accent-cyan)" : "var(--text-main)",
                  fontWeight: selectedDevice ? 600 : 700,
                }}
                onClick={() => {
                  setSelectedDevice(null);
                  setSelectedDate(null);
                }}
              >
                🖥️ All Devices
              </span>

              {selectedDevice && (
                <>
                  <span>/</span>
                  <span
                    style={{
                      cursor: selectedDate ? "pointer" : "default",
                      color: selectedDate ? "var(--accent-cyan)" : "var(--text-main)",
                      fontWeight: selectedDate ? 600 : 700,
                    }}
                    onClick={() => setSelectedDate(null)}
                  >
                    {getDeviceName(selectedDevice)}
                  </span>
                </>
              )}

              {selectedDate && (
                <>
                  <span>/</span>
                  <span style={{ color: "var(--text-main)", fontWeight: 700 }}>
                    📅 {dayGroups.find((d) => d.dateStr === selectedDate)?.displayDate || selectedDate}
                  </span>
                </>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <h2 style={{ fontSize: "1.4rem", margin: 0, fontWeight: 700 }}>
                {!selectedDevice
                  ? "Monitored Devices"
                  : !selectedDate
                  ? `Activity Calendar — ${getDeviceName(selectedDevice)}`
                  : `Captures on ${dayGroups.find((d) => d.dateStr === selectedDate)?.displayDate || selectedDate}`}
              </h2>
              <span
                style={{
                  fontSize: "0.7rem",
                  padding: "2px 8px",
                  borderRadius: "12px",
                  background: "rgba(16, 185, 129, 0.15)",
                  color: "#10b981",
                  border: "1px solid rgba(16, 185, 129, 0.3)",
                  fontWeight: 600,
                }}
              >
                🔒 Admin Only
              </span>
              <span
                style={{
                  fontSize: "0.7rem",
                  padding: "2px 8px",
                  borderRadius: "12px",
                  background: "rgba(56, 189, 248, 0.15)",
                  color: "#38bdf8",
                  border: "1px solid rgba(56, 189, 248, 0.3)",
                  fontWeight: 600,
                }}
              >
                S3: captain8959/Monitor/
              </span>
            </div>
          </div>

          {/* Back Navigation Button */}
          <div>
            {selectedDate ? (
              <button
                className="btn btn-secondary"
                style={{ fontSize: "0.8rem", padding: "6px 14px" }}
                onClick={() => setSelectedDate(null)}
              >
                ← Back to Dates
              </button>
            ) : selectedDevice ? (
              <button
                className="btn btn-secondary"
                style={{ fontSize: "0.8rem", padding: "6px 14px" }}
                onClick={() => setSelectedDevice(null)}
              >
                ← Back to All Devices
              </button>
            ) : (
              <button
                className="btn btn-secondary"
                style={{ fontSize: "0.8rem", padding: "6px 14px" }}
                onClick={loadData}
              >
                ↻ Refresh Telemetry
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ======================================================== */}
      {/* LEVEL 1: DEVICES TABLE                                   */}
      {/* ======================================================== */}
      {!selectedDevice && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)", background: "rgba(15, 23, 42, 0.5)" }}>
            <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-subtle)", textTransform: "uppercase" }}>
              Select a device to view its day-wise activity calendar
            </span>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "0.85rem" }}>
              <thead>
                <tr
                  style={{
                    background: "rgba(15, 23, 42, 0.8)",
                    borderBottom: "1px solid var(--border-subtle)",
                    color: "var(--text-subtle)",
                    fontWeight: 600,
                    textTransform: "uppercase",
                    fontSize: "0.75rem",
                    letterSpacing: "0.05em",
                  }}
                >
                  <th style={{ padding: "12px 18px" }}>Device / Hostname</th>
                  <th style={{ padding: "12px 18px" }}>Operating System</th>
                  <th style={{ padding: "12px 18px" }}>Total Captures</th>
                  <th style={{ padding: "12px 18px" }}>Latest Capture</th>
                  <th style={{ padding: "12px 18px" }}>Storage Total</th>
                  <th style={{ padding: "12px 18px" }}>S3 Status</th>
                  <th style={{ padding: "12px 18px", textAlign: "right" }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {deviceGroups.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ padding: "3rem", textAlign: "center", color: "var(--text-subtle)" }}>
                      No active devices with screenshots found.
                    </td>
                  </tr>
                ) : (
                  deviceGroups.map((dg, idx) => (
                    <tr
                      key={dg.deviceId}
                      style={{
                        borderBottom: "1px solid var(--border-subtle)",
                        cursor: "pointer",
                        background: idx % 2 === 0 ? "transparent" : "rgba(255, 255, 255, 0.015)",
                        transition: "background 0.15s",
                      }}
                      onClick={() => setSelectedDevice(dg.deviceId)}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = "rgba(56, 189, 248, 0.05)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = idx % 2 === 0 ? "transparent" : "rgba(255, 255, 255, 0.015)";
                      }}
                    >
                      <td style={{ padding: "14px 18px" }}>
                        <div style={{ fontWeight: 600, color: "var(--text-main)", fontSize: "0.95rem", display: "flex", alignItems: "center", gap: "8px" }}>
                          <span>🖥️</span>
                          <span>{dg.hostname}</span>
                        </div>
                        <div style={{ fontSize: "0.72rem", color: "var(--text-subtle)", fontFamily: "monospace", marginTop: "2px" }}>
                          {dg.deviceId}
                        </div>
                      </td>

                      <td style={{ padding: "14px 18px" }}>
                        <span
                          style={{
                            padding: "3px 8px",
                            borderRadius: "4px",
                            background: "rgba(255, 255, 255, 0.06)",
                            fontSize: "0.75rem",
                            textTransform: "capitalize",
                          }}
                        >
                          {dg.os}
                        </span>
                      </td>

                      <td style={{ padding: "14px 18px" }}>
                        <span style={{ fontWeight: 700, color: "var(--accent-cyan)", fontSize: "0.95rem" }}>
                          {dg.screenshots.length}
                        </span>{" "}
                        <span style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>Captures</span>
                      </td>

                      <td style={{ padding: "14px 18px" }}>
                        <div style={{ color: "var(--text-main)", fontWeight: 500 }}>
                          {new Date(dg.lastCapture).toLocaleTimeString()}
                        </div>
                        <div style={{ fontSize: "0.72rem", color: "var(--text-subtle)" }}>
                          {new Date(dg.lastCapture).toLocaleDateString()} ({formatTimeAgo(dg.lastCapture)})
                        </div>
                      </td>

                      <td style={{ padding: "14px 18px", color: "var(--text-subtle)", fontSize: "0.8rem" }}>
                        {formatFileSize(dg.totalBytes)}
                      </td>

                      <td style={{ padding: "14px 18px" }}>
                        <span style={{ color: "#10b981", fontWeight: 600, fontSize: "0.75rem", display: "inline-flex", alignItems: "center", gap: "4px" }}>
                          ● Active S3 Sync
                        </span>
                      </td>

                      <td style={{ padding: "14px 18px", textAlign: "right" }}>
                        <button
                          className="btn btn-primary"
                          style={{ fontSize: "0.8rem", padding: "6px 14px" }}
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedDevice(dg.deviceId);
                          }}
                        >
                          View Days ➔
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* LEVEL 2: DAY-WISE TABLE FOR SELECTED DEVICE              */}
      {/* ======================================================== */}
      {selectedDevice && !selectedDate && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)", background: "rgba(15, 23, 42, 0.5)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-subtle)", textTransform: "uppercase" }}>
                Select a day to view time-wise screenshots
              </span>
              <div style={{ fontSize: "0.8rem", color: "var(--accent-cyan)", marginTop: "2px" }}>
                Device: {getDeviceName(selectedDevice)} ({selectedDevice})
              </div>
            </div>
            <button
              className="btn btn-secondary"
              style={{ fontSize: "0.75rem", padding: "4px 12px" }}
              onClick={() => setSelectedDevice(null)}
            >
              ← Change Device
            </button>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "0.85rem" }}>
              <thead>
                <tr
                  style={{
                    background: "rgba(15, 23, 42, 0.8)",
                    borderBottom: "1px solid var(--border-subtle)",
                    color: "var(--text-subtle)",
                    fontWeight: 600,
                    textTransform: "uppercase",
                    fontSize: "0.75rem",
                    letterSpacing: "0.05em",
                  }}
                >
                  <th style={{ padding: "12px 18px" }}>Date</th>
                  <th style={{ padding: "12px 18px" }}>Screenshot Count</th>
                  <th style={{ padding: "12px 18px" }}>Active Time Range</th>
                  <th style={{ padding: "12px 18px" }}>Total Volume</th>
                  <th style={{ padding: "12px 18px" }}>Storage Location</th>
                  <th style={{ padding: "12px 18px", textAlign: "right" }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {dayGroups.length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ padding: "3rem", textAlign: "center", color: "var(--text-subtle)" }}>
                      No daily records found for this device.
                    </td>
                  </tr>
                ) : (
                  dayGroups.map((day, idx) => {
                    const firstTime = new Date(day.firstTime).toLocaleTimeString();
                    const lastTime = new Date(day.lastTime).toLocaleTimeString();

                    return (
                      <tr
                        key={day.dateStr}
                        style={{
                          borderBottom: "1px solid var(--border-subtle)",
                          cursor: "pointer",
                          background: idx % 2 === 0 ? "transparent" : "rgba(255, 255, 255, 0.015)",
                          transition: "background 0.15s",
                        }}
                        onClick={() => setSelectedDate(day.dateStr)}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "rgba(56, 189, 248, 0.05)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = idx % 2 === 0 ? "transparent" : "rgba(255, 255, 255, 0.015)";
                        }}
                      >
                        <td style={{ padding: "14px 18px" }}>
                          <div style={{ fontWeight: 600, color: "var(--text-main)", fontSize: "0.95rem", display: "flex", alignItems: "center", gap: "8px" }}>
                            <span>📅</span>
                            <span>{day.displayDate}</span>
                          </div>
                          <div style={{ fontSize: "0.72rem", color: "var(--text-subtle)", fontFamily: "monospace", marginTop: "2px" }}>
                            Partition: {day.dateStr}
                          </div>
                        </td>

                        <td style={{ padding: "14px 18px" }}>
                          <span style={{ fontWeight: 700, color: "var(--accent-cyan)", fontSize: "0.95rem" }}>
                            {day.screenshots.length}
                          </span>{" "}
                          <span style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>Captures</span>
                        </td>

                        <td style={{ padding: "14px 18px" }}>
                          <div style={{ color: "var(--text-main)", fontWeight: 500 }}>
                            {firstTime} — {lastTime}
                          </div>
                          <div style={{ fontSize: "0.72rem", color: "var(--text-subtle)" }}>
                            Day span coverage
                          </div>
                        </td>

                        <td style={{ padding: "14px 18px", color: "var(--text-subtle)", fontSize: "0.8rem" }}>
                          {formatFileSize(day.totalBytes)}
                        </td>

                        <td style={{ padding: "14px 18px" }}>
                          <span style={{ fontSize: "0.75rem", color: "var(--text-subtle)", fontFamily: "monospace" }}>
                            captain8959/Monitor/.../{day.dateStr.replace(/-/g, "/")}
                          </span>
                        </td>

                        <td style={{ padding: "14px 18px", textAlign: "right" }}>
                          <button
                            className="btn btn-primary"
                            style={{ fontSize: "0.8rem", padding: "6px 14px" }}
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedDate(day.dateStr);
                            }}
                          >
                            Open Time-wise SS ➔
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* LEVEL 3: TIME-WISE SCREENSHOTS FOR SELECTED DAY          */}
      {/* ======================================================== */}
      {selectedDevice && selectedDate && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div
            style={{
              padding: "14px 20px",
              borderBottom: "1px solid var(--border-subtle)",
              background: "rgba(15, 23, 42, 0.5)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "10px",
            }}
          >
            <div>
              <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-subtle)", textTransform: "uppercase" }}>
                Time-Wise Screenshots ({timeScreenshots.length} Captures)
              </span>
              <div style={{ fontSize: "0.8rem", color: "var(--accent-cyan)", marginTop: "2px" }}>
                Device: <strong>{getDeviceName(selectedDevice)}</strong> · Date: <strong>{selectedDate}</strong>
              </div>
            </div>
            <button
              className="btn btn-secondary"
              style={{ fontSize: "0.75rem", padding: "4px 12px" }}
              onClick={() => setSelectedDate(null)}
            >
              ← Back to Calendar Days
            </button>
          </div>

          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "0.85rem" }}>
              <thead>
                <tr
                  style={{
                    background: "rgba(15, 23, 42, 0.8)",
                    borderBottom: "1px solid var(--border-subtle)",
                    color: "var(--text-subtle)",
                    fontWeight: 600,
                    textTransform: "uppercase",
                    fontSize: "0.75rem",
                    letterSpacing: "0.05em",
                  }}
                >
                  <th style={{ padding: "12px 18px", width: "140px" }}>Preview</th>
                  <th style={{ padding: "12px 18px" }}>Time (UTC / Local)</th>
                  <th style={{ padding: "12px 18px" }}>Resolution</th>
                  <th style={{ padding: "12px 18px" }}>File Size</th>
                  <th style={{ padding: "12px 18px" }}>S3 Status</th>
                  <th style={{ padding: "12px 18px", textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {timeScreenshots.length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ padding: "3rem", textAlign: "center", color: "var(--text-subtle)" }}>
                      No captures found for this date.
                    </td>
                  </tr>
                ) : (
                  timeScreenshots.map((sc, idx) => {
                    const capturedDate = new Date(sc.captured_at);
                    const isFinalized = sc.status === "finalized";

                    return (
                      <tr
                        key={sc.id}
                        style={{
                          borderBottom: "1px solid var(--border-subtle)",
                          background: idx % 2 === 0 ? "transparent" : "rgba(255, 255, 255, 0.015)",
                          transition: "background 0.15s",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "rgba(56, 189, 248, 0.04)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = idx % 2 === 0 ? "transparent" : "rgba(255, 255, 255, 0.015)";
                        }}
                      >
                        {/* 1. Preview Thumbnail */}
                        <td style={{ padding: "10px 18px" }}>
                          <div
                            style={{
                              width: "120px",
                              height: "70px",
                              borderRadius: "var(--radius-sm)",
                              overflow: "hidden",
                              border: "1px solid var(--border-subtle)",
                              position: "relative",
                              background: "#000",
                              boxShadow: "0 2px 6px rgba(0,0,0,0.5)",
                              cursor: "pointer",
                            }}
                            onClick={() => handleOpenModal(sc)}
                          >
                            <ScreenshotThumbnail item={sc} onClick={() => handleOpenModal(sc)} />
                            <div
                              style={{
                                position: "absolute",
                                bottom: "4px",
                                right: "4px",
                                background: "rgba(0,0,0,0.75)",
                                fontSize: "0.65rem",
                                padding: "1px 5px",
                                borderRadius: "3px",
                                color: "#cbd5e1",
                              }}
                            >
                              🔍 Zoom
                            </div>
                          </div>
                        </td>

                        {/* 2. Timestamp */}
                        <td style={{ padding: "10px 18px" }}>
                          <div style={{ color: "var(--text-main)", fontWeight: 600, fontSize: "0.95rem" }}>
                            {capturedDate.toLocaleTimeString()}
                          </div>
                          <div style={{ fontSize: "0.72rem", color: "var(--text-subtle)", marginTop: "2px" }}>
                            {formatTimeAgo(sc.captured_at)} · {capturedDate.toISOString()}
                          </div>
                        </td>

                        {/* 3. Resolution */}
                        <td style={{ padding: "10px 18px" }}>
                          <span
                            style={{
                              padding: "3px 8px",
                              borderRadius: "4px",
                              background: "rgba(255, 255, 255, 0.06)",
                              fontFamily: "monospace",
                              fontSize: "0.75rem",
                              color: "#cbd5e1",
                            }}
                          >
                            {sc.width ? `${sc.width} × ${sc.height}` : "1920 × 1080"}
                          </span>
                        </td>

                        {/* 4. File Size */}
                        <td style={{ padding: "10px 18px", color: "var(--text-subtle)", fontSize: "0.8rem" }}>
                          {formatFileSize(sc.file_size)}
                        </td>

                        {/* 5. S3 Status */}
                        <td style={{ padding: "10px 18px" }}>
                          <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                            <span
                              style={{
                                color: isFinalized ? "#10b981" : "#f59e0b",
                                fontWeight: 600,
                                fontSize: "0.75rem",
                                display: "inline-flex",
                                alignItems: "center",
                                gap: "4px",
                              }}
                            >
                              <span>{isFinalized ? "● Stored in S3" : "○ Pending Verification"}</span>
                            </span>
                            <span style={{ fontSize: "0.7rem", color: "var(--text-subtle)" }}>
                              Persistent (7-day validity)
                            </span>
                          </div>
                        </td>

                        {/* 6. Actions */}
                        <td style={{ padding: "10px 18px", textAlign: "right" }}>
                          <button
                            className="btn btn-primary"
                            style={{ fontSize: "0.75rem", padding: "6px 14px" }}
                            onClick={() => handleOpenModal(sc)}
                          >
                            Inspect Full SS 🔍
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* HIGH RESOLUTION SCREENSHOT INSPECTOR MODAL               */}
      {/* ======================================================== */}
      {activeModalScreenshot && (
        <div className="modal-backdrop" onClick={() => setActiveModalScreenshot(null)}>
          <div
            className="modal-window"
            style={{ maxWidth: "1080px", width: "95vw" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <h3 style={{ fontSize: "1.15rem", margin: 0 }}>
                  High-Resolution Screenshot Inspector
                </h3>
                <div style={{ fontSize: "0.8rem", color: "var(--text-subtle)", marginTop: "4px" }}>
                  Device: <strong>{getDeviceName(activeModalScreenshot.device_id)}</strong> | Captured:{" "}
                  <strong>{new Date(activeModalScreenshot.captured_at).toLocaleString()}</strong>
                </div>
              </div>
              <button
                className="btn btn-secondary"
                onClick={() => setActiveModalScreenshot(null)}
                style={{ padding: "4px 10px" }}
              >
                ✕
              </button>
            </div>

            {loadingModalUrl ? (
              <div style={{ padding: "6rem 2rem", textAlign: "center" }}>
                <div style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "8px" }}>
                  Retrieving high-resolution S3 object...
                </div>
                <div style={{ fontSize: "0.8rem", color: "var(--text-subtle)" }}>
                  Connecting to AWS S3 bucket: captain8959/Monitor/
                </div>
              </div>
            ) : modalViewUrl ? (
              <div>
                <div
                  style={{
                    borderRadius: "var(--radius-sm)",
                    overflow: "hidden",
                    border: "1px solid var(--border-glow)",
                    background: "#000",
                    marginBottom: "1rem",
                    maxHeight: "70vh",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <img
                    src={modalViewUrl}
                    alt="Audited capture"
                    style={{ maxWidth: "100%", maxHeight: "70vh", objectFit: "contain", display: "block" }}
                  />
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "10px 14px",
                    borderRadius: "var(--radius-sm)",
                    background: "rgba(15, 23, 42, 0.7)",
                    fontSize: "0.8rem",
                    color: "var(--text-subtle)",
                  }}
                >
                  <div style={{ display: "flex", gap: "20px" }}>
                    <span>
                      Resolution: <strong>{activeModalScreenshot.width || 1920} × {activeModalScreenshot.height || 1080}</strong>
                    </span>
                    <span>
                      Size: <strong>{formatFileSize(activeModalScreenshot.file_size)}</strong>
                    </span>
                    <span>
                      Storage: <strong>AWS S3 (Persistent 7-day URL)</strong>
                    </span>
                  </div>
                  <div>
                    <a
                      href={modalViewUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-secondary"
                      style={{ padding: "5px 12px", fontSize: "0.75rem", textDecoration: "none" }}
                    >
                      Open Full Screen ↗
                    </a>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ padding: "4rem", color: "var(--accent-rose)", textAlign: "center" }}>
                Failed to load screenshot view URL from S3.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
