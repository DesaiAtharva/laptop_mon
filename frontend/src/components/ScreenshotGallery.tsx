import React, { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import { ScreenshotItem } from "../types";

// Persistent thumbnail component with automatic retry and auto-refresh on expiration
const ScreenshotThumbnail: React.FC<{
  screenshotId: string;
  initialUrl?: string;
  alt: string;
  style?: React.CSSProperties;
  onClick?: () => void;
}> = ({ screenshotId, initialUrl, alt, style, onClick }) => {
  const [url, setUrl] = useState<string | null>(initialUrl || null);
  const [loading, setLoading] = useState(false);
  const [hasError, setHasError] = useState(false);

  const fetchUrl = (silent = false) => {
    if (!silent) setLoading(true);
    api
      .getScreenshotViewUrl(screenshotId)
      .then((res) => {
        if (res && res.view_url) {
          setUrl(res.view_url);
          setHasError(false);
        }
      })
      .catch(() => {
        setHasError(true);
      })
      .finally(() => {
        if (!silent) setLoading(false);
      });
  };

  useEffect(() => {
    if (!initialUrl) {
      fetchUrl();
    }
  }, [screenshotId, initialUrl]);

  const handleImageError = () => {
    // If image URL fails or expires, auto-fetch a fresh S3 presigned URL seamlessly
    fetchUrl(true);
  };

  if (loading && !url) {
    return (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #1e293b, #0f172a)",
          color: "var(--text-subtle)",
          fontSize: "0.75rem",
          ...style,
        }}
      >
        <span className="pulse">Loading...</span>
      </div>
    );
  }

  if (hasError && !url) {
    return (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#1e1e24",
          color: "var(--accent-rose)",
          fontSize: "0.75rem",
          ...style,
        }}
        onClick={onClick}
      >
        <span>Preview unavailable</span>
      </div>
    );
  }

  return (
    <img
      src={url || ""}
      alt={alt}
      onError={handleImageError}
      onClick={onClick}
      style={{
        objectFit: "cover",
        display: "block",
        cursor: onClick ? "pointer" : "default",
        ...style,
      }}
    />
  );
};

export const ScreenshotGallery: React.FC = () => {
  const [screenshots, setScreenshots] = useState<ScreenshotItem[]>([]);
  const [devices, setDevices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedScreenshot, setSelectedScreenshot] = useState<ScreenshotItem | null>(null);
  const [viewUrl, setViewUrl] = useState<string | null>(null);
  const [loadingUrl, setLoadingUrl] = useState(false);

  // Filters & View Mode
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("all");
  const [viewMode, setViewMode] = useState<"table" | "grid">("table");
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

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

  // Map of device_id -> Device details
  const deviceMap = useMemo(() => {
    const map = new Map<string, any>();
    devices.forEach((d) => {
      map.set(d.id, d);
    });
    return map;
  }, [devices]);

  // Unique devices present in current screenshots
  const uniqueDeviceIds = useMemo(() => {
    const ids = new Set<string>();
    screenshots.forEach((s) => {
      if (s.device_id) ids.add(s.device_id);
    });
    return Array.from(ids);
  }, [screenshots]);

  // Filtered Screenshots
  const filteredScreenshots = useMemo(() => {
    return screenshots.filter((sc) => {
      // Device filter
      if (selectedDeviceId !== "all" && sc.device_id !== selectedDeviceId) {
        return false;
      }
      // Status filter
      if (statusFilter !== "all") {
        if (statusFilter === "finalized" && sc.status !== "finalized") return false;
        if (statusFilter === "pending" && sc.status === "finalized") return false;
      }
      // Search query (matches device hostname, device id, or screenshot id)
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const hostname = sc.device_hostname || deviceMap.get(sc.device_id)?.hostname || "";
        const match =
          sc.id.toLowerCase().includes(q) ||
          sc.device_id.toLowerCase().includes(q) ||
          hostname.toLowerCase().includes(q);
        if (!match) return false;
      }
      return true;
    });
  }, [screenshots, selectedDeviceId, statusFilter, searchQuery, deviceMap]);

  async function handleOpenScreenshot(item: ScreenshotItem) {
    setSelectedScreenshot(item);
    setLoadingUrl(true);
    setViewUrl(null);
    try {
      const res = await api.getScreenshotViewUrl(item.id);
      setViewUrl(res.view_url);
    } catch (err) {
      alert(`Could not request secure view URL: ${err}`);
    } finally {
      setLoadingUrl(false);
    }
  }

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return "N/A";
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
          Connecting to AWS S3 Screenshot Vault...
        </div>
        <p style={{ fontSize: "0.85rem" }}>Retrieving device-partitioned captures from s3://captain8959/Monitor/</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* Header & Stats Banner */}
      <div
        className="card"
        style={{
          padding: "1.5rem 2rem",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "1.5rem",
          background: "linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.9))",
          borderColor: "rgba(56, 189, 248, 0.2)",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "6px" }}>
            <h2 style={{ fontSize: "1.6rem", margin: 0, fontWeight: 700 }}>
              Device Screenshot Vault
            </h2>
            <span
              style={{
                fontSize: "0.75rem",
                padding: "2px 8px",
                borderRadius: "12px",
                background: "rgba(16, 185, 129, 0.15)",
                color: "#10b981",
                border: "1px solid rgba(16, 185, 129, 0.3)",
                fontWeight: 600,
              }}
            >
              🔒 Admin Exclusive
            </span>
            <span
              style={{
                fontSize: "0.75rem",
                padding: "2px 8px",
                borderRadius: "12px",
                background: "rgba(56, 189, 248, 0.15)",
                color: "#38bdf8",
                border: "1px solid rgba(56, 189, 248, 0.3)",
                fontWeight: 600,
              }}
            >
              AWS S3 Active
            </span>
          </div>
          <p style={{ color: "var(--text-subtle)", fontSize: "0.85rem", margin: 0 }}>
            Device-wise audit telemetry stored in <code>s3://captain8959/Monitor/</code>.
            Signed URLs are persistent (7-day validity) and auto-refreshed seamlessly.
          </p>
        </div>

        {/* Quick Metrics */}
        <div style={{ display: "flex", gap: "1.5rem" }}>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: "0.75rem", color: "var(--text-subtle)", textTransform: "uppercase" }}>
              Total Captures
            </div>
            <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--text-main)" }}>
              {screenshots.length}
            </div>
          </div>
          <div style={{ borderLeft: "1px solid var(--border-subtle)" }} />
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: "0.75rem", color: "var(--text-subtle)", textTransform: "uppercase" }}>
              Enrolled Devices
            </div>
            <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--accent-cyan)" }}>
              {uniqueDeviceIds.length || devices.length}
            </div>
          </div>
        </div>
      </div>

      {/* Device Filter Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "10px",
          flexWrap: "wrap",
          padding: "10px 14px",
          background: "var(--bg-surface)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border-subtle)",
        }}
      >
        <span style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-subtle)", marginRight: "6px" }}>
          DEVICE FILTER:
        </span>

        {/* All Devices Pill */}
        <button
          className={`btn ${selectedDeviceId === "all" ? "btn-primary" : "btn-secondary"}`}
          style={{ padding: "5px 14px", fontSize: "0.8rem", borderRadius: "20px" }}
          onClick={() => setSelectedDeviceId("all")}
        >
          All Devices ({screenshots.length})
        </button>

        {/* Individual Device Pills */}
        {uniqueDeviceIds.map((devId) => {
          const dev = deviceMap.get(devId);
          const devName = dev?.hostname || scHostname(devId) || `Device ${devId.slice(0, 8)}`;
          const count = screenshots.filter((s) => s.device_id === devId).length;
          const isSelected = selectedDeviceId === devId;

          return (
            <button
              key={devId}
              className={`btn ${isSelected ? "btn-primary" : "btn-secondary"}`}
              style={{ padding: "5px 14px", fontSize: "0.8rem", borderRadius: "20px" }}
              onClick={() => setSelectedDeviceId(devId)}
            >
              🖥️ {devName} ({count})
            </button>
          );
        })}

        {/* Right side controls: Search & Layout Toggle */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "10px" }}>
          <input
            type="text"
            placeholder="Search hostname / ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              padding: "6px 12px",
              fontSize: "0.8rem",
              borderRadius: "var(--radius-sm)",
              background: "rgba(15, 23, 42, 0.6)",
              border: "1px solid var(--border-subtle)",
              color: "#fff",
              width: "180px",
            }}
          />

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            style={{
              padding: "6px 10px",
              fontSize: "0.8rem",
              borderRadius: "var(--radius-sm)",
              background: "rgba(15, 23, 42, 0.6)",
              border: "1px solid var(--border-subtle)",
              color: "#fff",
            }}
          >
            <option value="all">All Status</option>
            <option value="finalized">Verified (S3)</option>
            <option value="pending">Pending</option>
          </select>

          <div style={{ display: "flex", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)" }}>
            <button
              className={`btn ${viewMode === "table" ? "btn-primary" : "btn-secondary"}`}
              style={{ padding: "6px 10px", fontSize: "0.75rem", border: "none", borderRadius: "var(--radius-sm) 0 0 var(--radius-sm)" }}
              onClick={() => setViewMode("table")}
              title="Detailed Table View"
            >
              Table View
            </button>
            <button
              className={`btn ${viewMode === "grid" ? "btn-primary" : "btn-secondary"}`}
              style={{ padding: "6px 10px", fontSize: "0.75rem", border: "none", borderRadius: "0 var(--radius-sm) var(--radius-sm) 0" }}
              onClick={() => setViewMode("grid")}
              title="Grid Card View"
            >
              Grid View
            </button>
          </div>
        </div>
      </div>

      {/* Main View Area: Table or Grid */}
      {filteredScreenshots.length === 0 ? (
        <div
          className="card"
          style={{
            padding: "4rem 2rem",
            textAlign: "center",
            color: "var(--text-subtle)",
          }}
        >
          <div style={{ fontSize: "1.1rem", fontWeight: 600, color: "var(--text-main)", marginBottom: "6px" }}>
            No screenshots found
          </div>
          <p style={{ fontSize: "0.85rem", maxWidth: "480px", margin: "0 auto" }}>
            {searchQuery || selectedDeviceId !== "all"
              ? "No captures match the current search or device filter."
              : "Screenshots captured by connected agents will appear here automatically."}
          </p>
        </div>
      ) : viewMode === "table" ? (
        /* Detailed Table Structure */
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
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
                  <th style={{ padding: "12px 16px", width: "110px" }}>Preview</th>
                  <th style={{ padding: "12px 16px" }}>Device / Hostname</th>
                  <th style={{ padding: "12px 16px" }}>Captured (UTC / Local)</th>
                  <th style={{ padding: "12px 16px" }}>Resolution</th>
                  <th style={{ padding: "12px 16px" }}>Size</th>
                  <th style={{ padding: "12px 16px" }}>Storage &amp; Status</th>
                  <th style={{ padding: "12px 16px", textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredScreenshots.map((sc, idx) => {
                  const dev = deviceMap.get(sc.device_id);
                  const hostname = sc.device_hostname || dev?.hostname || "DESKTOP-CLIENT";
                  const isFinalized = sc.status === "finalized";
                  const capturedDate = new Date(sc.captured_at);

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
                      <td style={{ padding: "10px 16px" }}>
                        <div
                          style={{
                            width: "90px",
                            height: "54px",
                            borderRadius: "var(--radius-sm)",
                            overflow: "hidden",
                            border: "1px solid var(--border-subtle)",
                            position: "relative",
                            background: "#000",
                            boxShadow: "0 2px 4px rgba(0,0,0,0.4)",
                          }}
                        >
                          <ScreenshotThumbnail
                            screenshotId={sc.id}
                            alt="Capture thumbnail"
                            style={{ width: "100%", height: "100%" }}
                            onClick={() => handleOpenScreenshot(sc)}
                          />
                        </div>
                      </td>

                      {/* 2. Device / Hostname */}
                      <td style={{ padding: "10px 16px" }}>
                        <div style={{ fontWeight: 600, color: "var(--text-main)", display: "flex", alignItems: "center", gap: "6px" }}>
                          <span>🖥️</span>
                          <span>{hostname}</span>
                        </div>
                        <div style={{ fontSize: "0.72rem", color: "var(--text-subtle)", fontFamily: "monospace" }}>
                          {sc.device_id}
                        </div>
                      </td>

                      {/* 3. Captured Time */}
                      <td style={{ padding: "10px 16px" }}>
                        <div style={{ color: "var(--text-main)", fontWeight: 500 }}>
                          {capturedDate.toLocaleTimeString()}
                        </div>
                        <div style={{ fontSize: "0.72rem", color: "var(--text-subtle)" }}>
                          {capturedDate.toLocaleDateString()} ({formatTimeAgo(sc.captured_at)})
                        </div>
                      </td>

                      {/* 4. Resolution */}
                      <td style={{ padding: "10px 16px" }}>
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
                          {sc.width ? `${sc.width} × ${sc.height}` : "1080p"}
                        </span>
                      </td>

                      {/* 5. Size */}
                      <td style={{ padding: "10px 16px", color: "var(--text-subtle)", fontSize: "0.8rem" }}>
                        {formatFileSize(sc.file_size)}
                      </td>

                      {/* 6. Storage & Status */}
                      <td style={{ padding: "10px 16px" }}>
                        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: "4px",
                              fontSize: "0.72rem",
                              fontWeight: 600,
                              color: isFinalized ? "#10b981" : "#f59e0b",
                            }}
                          >
                            <span>{isFinalized ? "● S3 Verified" : "○ Pending Upload"}</span>
                          </span>
                          <span style={{ fontSize: "0.7rem", color: "var(--text-subtle)" }}>
                            captain8959/Monitor/
                          </span>
                        </div>
                      </td>

                      {/* 7. Actions */}
                      <td style={{ padding: "10px 16px", textAlign: "right" }}>
                        <button
                          className="btn btn-primary"
                          style={{ padding: "5px 12px", fontSize: "0.75rem" }}
                          onClick={() => handleOpenScreenshot(sc)}
                        >
                          Inspect Full
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* Grid Card View */
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: "1.5rem",
          }}
        >
          {filteredScreenshots.map((sc) => {
            const dev = deviceMap.get(sc.device_id);
            const hostname = sc.device_hostname || dev?.hostname || "DESKTOP-CLIENT";
            const isFinalized = sc.status === "finalized";

            return (
              <div
                key={sc.id}
                className="card"
                style={{
                  padding: "1rem",
                  cursor: "pointer",
                  display: "flex",
                  flexDirection: "column",
                  gap: "10px",
                }}
                onClick={() => handleOpenScreenshot(sc)}
              >
                <div
                  style={{
                    height: "160px",
                    borderRadius: "var(--radius-sm)",
                    background: "#000",
                    position: "relative",
                    overflow: "hidden",
                    border: "1px solid var(--border-subtle)",
                  }}
                >
                  <ScreenshotThumbnail
                    screenshotId={sc.id}
                    alt="Capture preview"
                    style={{ width: "100%", height: "100%" }}
                  />
                  <span
                    style={{
                      position: "absolute",
                      bottom: "8px",
                      right: "8px",
                      fontSize: "0.7rem",
                      background: "rgba(0,0,0,0.8)",
                      padding: "2px 6px",
                      borderRadius: "4px",
                      color: "#cbd5e1",
                    }}
                  >
                    {sc.width ? `${sc.width}×${sc.height}` : "1080p"}
                  </span>
                  <span
                    style={{
                      position: "absolute",
                      top: "8px",
                      left: "8px",
                      fontSize: "0.68rem",
                      background: isFinalized ? "rgba(16, 185, 129, 0.9)" : "rgba(245, 158, 11, 0.9)",
                      padding: "2px 6px",
                      borderRadius: "4px",
                      color: "#fff",
                      fontWeight: 600,
                    }}
                  >
                    {isFinalized ? "S3 Verified" : "Pending"}
                  </span>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontSize: "0.85rem", fontWeight: 600 }}>{hostname}</div>
                    <div style={{ fontSize: "0.72rem", color: "var(--text-subtle)" }}>
                      {new Date(sc.captured_at).toLocaleTimeString()} · {formatFileSize(sc.file_size)}
                    </div>
                  </div>
                  <button
                    className="btn btn-secondary"
                    style={{ padding: "4px 10px", fontSize: "0.75rem" }}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleOpenScreenshot(sc);
                    }}
                  >
                    Inspect
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* High-Resolution Modal Inspector */}
      {selectedScreenshot && (
        <div className="modal-backdrop" onClick={() => setSelectedScreenshot(null)}>
          <div
            className="modal-window"
            style={{ maxWidth: "960px", width: "95vw" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <h3 style={{ fontSize: "1.15rem", margin: 0 }}>
                  High-Resolution Screenshot Inspector
                </h3>
                <div style={{ fontSize: "0.8rem", color: "var(--text-subtle)", marginTop: "4px" }}>
                  Device:{" "}
                  <strong>
                    {selectedScreenshot.device_hostname ||
                      deviceMap.get(selectedScreenshot.device_id)?.hostname ||
                      selectedScreenshot.device_id}
                  </strong>{" "}
                  | Captured at: {new Date(selectedScreenshot.captured_at).toLocaleString()}
                </div>
              </div>
              <button
                className="btn btn-secondary"
                onClick={() => setSelectedScreenshot(null)}
                style={{ padding: "4px 10px" }}
              >
                ✕
              </button>
            </div>

            {loadingUrl ? (
              <div style={{ padding: "5rem 2rem", textAlign: "center" }}>
                <div style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "8px" }}>
                  Retrieving high-resolution S3 object...
                </div>
                <div style={{ fontSize: "0.8rem", color: "var(--text-subtle)" }}>
                  Connecting to AWS S3 bucket: captain8959/Monitor/
                </div>
              </div>
            ) : viewUrl ? (
              <div>
                <div
                  style={{
                    borderRadius: "var(--radius-sm)",
                    overflow: "hidden",
                    border: "1px solid var(--border-glow)",
                    background: "#000",
                    marginBottom: "1rem",
                    maxHeight: "68vh",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <img
                    src={viewUrl}
                    alt="High-resolution audited capture"
                    style={{ maxWidth: "100%", maxHeight: "68vh", objectFit: "contain", display: "block" }}
                  />
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "8px 12px",
                    borderRadius: "var(--radius-sm)",
                    background: "rgba(15, 23, 42, 0.6)",
                    fontSize: "0.78rem",
                    color: "var(--text-subtle)",
                  }}
                >
                  <div style={{ display: "flex", gap: "16px" }}>
                    <span>
                      Resolution: <strong>{selectedScreenshot.width || 1920} × {selectedScreenshot.height || 1080}</strong>
                    </span>
                    <span>
                      Size: <strong>{formatFileSize(selectedScreenshot.file_size)}</strong>
                    </span>
                    <span>
                      Storage: <strong>AWS S3 (Persistent)</strong>
                    </span>
                  </div>
                  <div>
                    <a
                      href={viewUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-secondary"
                      style={{ padding: "4px 10px", fontSize: "0.75rem", textDecoration: "none" }}
                    >
                      Open Full Screen ↗
                    </a>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ padding: "3rem", color: "var(--accent-rose)", textAlign: "center" }}>
                Failed to load screenshot view URL.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

function scHostname(devId: string): string {
  if (devId.startsWith("b1a31985")) return "DESKTOP-GO4TUDQ";
  return "";
}
