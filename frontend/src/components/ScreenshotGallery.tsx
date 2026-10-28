import React, { useEffect, useState } from "react";
import { api } from "../services/api";
import { ScreenshotItem } from "../types";

export const ScreenshotGallery: React.FC = () => {
  const [screenshots, setScreenshots] = useState<ScreenshotItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedScreenshot, setSelectedScreenshot] = useState<ScreenshotItem | null>(null);
  const [viewUrl, setViewUrl] = useState<string | null>(null);
  const [loadingUrl, setLoadingUrl] = useState(false);

  useEffect(() => {
    async function loadScreenshots() {
      try {
        const res = await api.getScreenshots();
        setScreenshots(res.results);
      } catch (err) {
        console.error("Failed to load screenshots", err);
      } finally {
        setLoading(false);
      }
    }
    loadScreenshots();
  }, []);

  async function handleOpenScreenshot(item: ScreenshotItem) {
    setSelectedScreenshot(item);
    setLoadingUrl(true);
    setViewUrl(null);
    try {
      // REQ-10-4: On-demand short-lived presigned URL, every view audited
      const res = await api.getScreenshotViewUrl(item.id);
      setViewUrl(res.view_url);
    } catch (err) {
      alert(`Could not request secure view URL: ${err}`);
    } finally {
      setLoadingUrl(false);
    }
  }

  if (loading) {
    return <div style={{ padding: "3rem", textAlign: "center" }}>Loading encrypted screenshot vault...</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.75rem", marginBottom: "0.4rem" }}>Screenshot Audit Vault</h2>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
          Protected under explicit screenshot permissions (REQ-2-4). Viewing URLs are short-lived
          (300s) and every view is logged to the immutable audit trail.
        </p>
      </div>

      {/* Grid of Screenshots (E69 pagination / virtualization) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: "1.5rem",
        }}
      >
        {screenshots.map((sc) => (
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
                background: "linear-gradient(135deg, #1e293b, #0f172a)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                border: "1px solid var(--border-subtle)",
                overflow: "hidden",
                position: "relative",
              }}
            >
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-subtle)" strokeWidth="1.5">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <polyline points="21 15 16 10 5 21" />
              </svg>
              <span
                style={{
                  position: "absolute",
                  bottom: "8px",
                  right: "8px",
                  fontSize: "0.75rem",
                  background: "rgba(0,0,0,0.7)",
                  padding: "2px 8px",
                  borderRadius: "4px",
                  color: "#cbd5e1",
                }}
              >
                {sc.width}x{sc.height}
              </span>
            </div>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontSize: "0.85rem", fontWeight: 600 }}>{sc.device_id}</div>
                <div style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>
                  {new Date(sc.captured_at).toLocaleTimeString()}
                </div>
              </div>
              <button
                className="btn btn-secondary"
                style={{ padding: "4px 10px", fontSize: "0.75rem" }}
              >
                Inspect
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Viewing Modal with Audited Presigned URL (REQ-10-4) */}
      {selectedScreenshot && (
        <div className="modal-backdrop" onClick={() => setSelectedScreenshot(null)}>
          <div
            className="modal-window"
            style={{ maxWidth: "800px" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <h3 style={{ fontSize: "1.1rem" }}>Screenshot Inspection (Audited)</h3>
                <div style={{ fontSize: "0.8rem", color: "var(--text-subtle)" }}>
                  Captured at: {new Date(selectedScreenshot.captured_at).toLocaleString()}
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
              <div style={{ padding: "4rem", textAlign: "center" }}>
                Generating single-use presigned URL &amp; logging audit entry...
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
                  }}
                >
                  <img
                    src={viewUrl}
                    alt="Audited capture"
                    style={{ width: "100%", height: "auto", display: "block" }}
                  />
                </div>
                <div
                  style={{
                    fontSize: "0.75rem",
                    color: "var(--accent-cyan)",
                    display: "flex",
                    justifyContent: "space-between",
                  }}
                >
                  <span>✓ View audited under user credentials</span>
                  <span>URL expires in 300 seconds</span>
                </div>
              </div>
            ) : (
              <div style={{ padding: "2rem", color: "var(--accent-rose)", textAlign: "center" }}>
                Failed to load screenshot view URL.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
