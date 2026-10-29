import React from "react";
import { useAuth } from "../context/AuthContext";

export const Header: React.FC = () => {
  const {
    tenants,
    activeTenant,
    setActiveTenant,
    role,
    timezonePref,
    setTimezonePref,
    userName,
    userEmail,
    logout,
    user,
  } = useAuth();

  return (
    <header className="app-header">
      <div className="brand-section">
        <div className="brand-icon">
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#ffffff"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
            <line x1="8" y1="21" x2="16" y2="21" />
            <line x1="12" y1="17" x2="12" y2="21" />
          </svg>
        </div>
        <span className="brand-title">LaptopMon</span>
        <span className="role-badge" style={{ textTransform: "uppercase" }}>{role}</span>
        {user?.is_superuser && (
          <span
            style={{
              fontSize: "0.65rem",
              background: "rgba(245, 158, 11, 0.2)",
              color: "var(--accent-amber)",
              border: "1px solid rgba(245, 158, 11, 0.4)",
              borderRadius: "4px",
              padding: "2px 6px",
              fontWeight: 700,
            }}
          >
            SUPERUSER
          </span>
        )}
      </div>

      <div className="header-controls">
        {/* Multi-Tenant Switcher */}
        {tenants.length > 1 ? (
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "0.8rem", color: "var(--text-subtle)", fontWeight: 600 }}>
              ORGANIZATION:
            </span>
            <select
              className="tenant-select"
              value={activeTenant?.id || ""}
              onChange={(e) => {
                const selected = tenants.find((t) => t.id === e.target.value);
                if (selected) setActiveTenant(selected);
              }}
            >
              {tenants.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ fontSize: "0.8rem", color: "var(--text-subtle)", fontWeight: 600 }}>
              ORG:
            </span>
            <span
              style={{
                fontSize: "0.85rem",
                color: "var(--text-main)",
                fontWeight: 600,
                background: "rgba(255, 255, 255, 0.05)",
                padding: "4px 10px",
                borderRadius: "6px",
                border: "1px solid var(--border-subtle)",
              }}
            >
              {activeTenant?.name || "Primary Organization"}
            </span>
          </div>
        )}

        {/* Timezone Preference (E74) */}
        <button
          className="btn btn-secondary"
          style={{ fontSize: "0.8rem", padding: "6px 12px" }}
          onClick={() => setTimezonePref(timezonePref === "local" ? "UTC" : "local")}
          title="Toggle display timezone between Local Browser Time and UTC (E74)"
        >
          🌐 {timezonePref === "local" ? "Local Time" : "UTC"}
        </button>



        {/* Authenticated User Profile */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginLeft: "8px" }}>
          <div
            style={{
              width: "34px",
              height: "34px",
              borderRadius: "50%",
              background: "linear-gradient(135deg, var(--accent-indigo), var(--accent-cyan))",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 700,
              fontSize: "0.85rem",
              color: "#ffffff",
            }}
          >
            {(userName || "U")[0].toUpperCase()}
          </div>
          <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2 }}>
            <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>{userName}</span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>{userEmail}</span>
          </div>
        </div>

        {/* Sign Out Button */}
        <button
          onClick={logout}
          className="btn btn-secondary"
          style={{
            fontSize: "0.8rem",
            padding: "6px 12px",
            color: "var(--accent-rose)",
            borderColor: "rgba(244, 63, 94, 0.3)",
            display: "flex",
            alignItems: "center",
            gap: "6px",
            marginLeft: "6px",
          }}
          title="Sign out and revoke active browser session"
        >
          <span>🚪</span>
          <span>Sign Out</span>
        </button>
      </div>
    </header>
  );
};
