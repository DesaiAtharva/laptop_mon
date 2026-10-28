import React from "react";
import { useAuth } from "../context/AuthContext";
import { MembershipRole } from "../types";

export const Header: React.FC = () => {
  const {
    tenants,
    activeTenant,
    setActiveTenant,
    role,
    setRole,
    timezonePref,
    setTimezonePref,
    userName,
    userEmail,
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
        <span className="role-badge">{role}</span>
      </div>

      <div className="header-controls">
        {/* Tenant Switcher (E46) */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ fontSize: "0.8rem", color: "var(--text-subtle)", fontWeight: 600 }}>
            TENANT:
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

        {/* Timezone Preference (E74) */}
        <button
          className="btn btn-secondary"
          style={{ fontSize: "0.8rem", padding: "6px 12px" }}
          onClick={() => setTimezonePref(timezonePref === "local" ? "UTC" : "local")}
          title="Toggle display timezone between Local Browser Time and UTC (E74)"
        >
          🌐 {timezonePref === "local" ? "Local Time" : "UTC"}
        </button>

        {/* Interactive Role Switcher */}
        <select
          className="tenant-select"
          style={{ borderColor: "var(--border-glow)", color: "var(--accent-cyan)" }}
          value={role}
          onChange={(e) => setRole(e.target.value as MembershipRole)}
          title="Switch view perspective for pairs and demoing"
        >
          <option value="employee">Role: Employee</option>
          <option value="manager">Role: Manager</option>
          <option value="admin">Role: Org Admin</option>
          <option value="auditor">Role: Auditor</option>
        </select>

        {/* User Profile */}
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
            }}
          >
            {userName[0]}
          </div>
          <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2 }}>
            <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>{userName}</span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>{userEmail}</span>
          </div>
        </div>
      </div>
    </header>
  );
};
