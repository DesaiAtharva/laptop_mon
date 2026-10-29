import React, { useState } from "react";
import { AdminDashboard } from "./components/AdminDashboard";
import { AuditLogViewer } from "./components/AuditLogViewer";
import { EmployeeSelfView } from "./components/EmployeeSelfView";
import { Header } from "./components/Header";
import { Login } from "./components/Login";
import { ManagerTeamView } from "./components/ManagerTeamView";
import { ScreenshotGallery } from "./components/ScreenshotGallery";
import { useAuth } from "./context/AuthContext";

type TabKey = "self-view" | "team-view" | "admin" | "screenshots" | "audit";

export const App: React.FC = () => {
  const { isAuthenticated, role } = useAuth();
  const [activeTab, setActiveTab] = useState<TabKey>("self-view");

  // Automatically adjust default view when role switcher changes
  React.useEffect(() => {
    if (role === "employee") setActiveTab("self-view");
    else if (role === "manager") setActiveTab("team-view");
    else if (role === "admin") setActiveTab("admin");
    else if (role === "auditor") setActiveTab("audit");
  }, [role]);

  // If unauthenticated, present production login portal
  if (!isAuthenticated) {
    return <Login />;
  }

  return (
    <div className="app-container">
      <Header />

      <div className="main-layout">
        <aside className="sidebar">
          <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--text-subtle)", padding: "0 10px 8px" }}>
            WORKSPACE NAVIGATION
          </div>

          <button
            className={`nav-item ${activeTab === "self-view" ? "active" : ""}`}
            onClick={() => setActiveTab("self-view")}
          >
            <span>👤</span>
            <span>My Self-View</span>
          </button>

          {(role === "manager" || role === "admin") && (
            <button
              className={`nav-item ${activeTab === "team-view" ? "active" : ""}`}
              onClick={() => setActiveTab("team-view")}
            >
              <span>👥</span>
              <span>Team Dashboard</span>
            </button>
          )}

          {role === "admin" && (
            <button
              className={`nav-item ${activeTab === "admin" ? "active" : ""}`}
              onClick={() => setActiveTab("admin")}
            >
              <span>⚙️</span>
              <span>Admin Console</span>
            </button>
          )}

          {(role === "admin" || role === "manager") && (
            <button
              className={`nav-item ${activeTab === "screenshots" ? "active" : ""}`}
              onClick={() => setActiveTab("screenshots")}
            >
              <span>🖼️</span>
              <span>Screenshot Vault</span>
            </button>
          )}

          {(role === "admin" || role === "auditor") && (
            <button
              className={`nav-item ${activeTab === "audit" ? "active" : ""}`}
              onClick={() => setActiveTab("audit")}
            >
              <span>📜</span>
              <span>Audit Trail</span>
            </button>
          )}

          <div style={{ marginTop: "auto", padding: "10px", fontSize: "0.75rem", color: "var(--text-subtle)" }}>
            <div>Client Version: 1.0.0-p8</div>
            <div>Strict RBAC &amp; UTC Timestamps</div>
          </div>
        </aside>

        <main className="content-area">
          {activeTab === "self-view" && <EmployeeSelfView />}
          {activeTab === "team-view" && <ManagerTeamView />}
          {activeTab === "admin" && <AdminDashboard />}
          {activeTab === "screenshots" && <ScreenshotGallery />}
          {activeTab === "audit" && <AuditLogViewer />}
        </main>
      </div>
    </div>
  );
};
