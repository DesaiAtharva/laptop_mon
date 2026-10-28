import React, { useEffect, useState } from "react";
import { api } from "../services/api";
import { AuditLogItem } from "../types";

export const AuditLogViewer: React.FC = () => {
  const [logs, setLogs] = useState<AuditLogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterAction, setFilterAction] = useState("");

  useEffect(() => {
    async function loadLogs() {
      try {
        const list = await api.getAuditLogs();
        setLogs(list);
      } catch (err) {
        console.error("Failed to load audit logs", err);
      } finally {
        setLoading(false);
      }
    }
    loadLogs();
  }, []);

  const filteredLogs = filterAction
    ? logs.filter((l) => l.action.toLowerCase().includes(filterAction.toLowerCase()))
    : logs;

  if (loading) {
    return <div style={{ padding: "3rem", textAlign: "center" }}>Loading audit records...</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.75rem", marginBottom: "0.4rem" }}>Immutable Audit Log Explorer</h2>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
          Append-only security and access logs. Modification and deletion are blocked at the ORM and database level.
        </p>
      </div>

      <div className="card">
        <div className="card-title">
          <span>Security Audit Trail</span>
          <input
            type="text"
            className="form-input"
            style={{ width: "240px", padding: "6px 12px", fontSize: "0.85rem" }}
            placeholder="Filter by action..."
            value={filterAction}
            onChange={(e) => setFilterAction(e.target.value)}
          />
        </div>

        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Resource</th>
                <th>Request ID</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {filteredLogs.map((log) => (
                <tr key={log.id}>
                  <td style={{ fontSize: "0.8rem", color: "var(--text-subtle)", whiteSpace: "nowrap" }}>
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                  <td>
                    <div style={{ fontWeight: 600 }}>{log.actor_name}</div>
                    <div style={{ fontSize: "0.75rem", color: "var(--text-subtle)" }}>{log.actor_email}</div>
                  </td>
                  <td>
                    <span className="badge-status status-active" style={{ fontFamily: "var(--font-mono)" }}>
                      {log.action}
                    </span>
                  </td>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.85rem" }}>
                    {log.resource_type}:{log.resource_id}
                  </td>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", color: "var(--text-subtle)" }}>
                    {log.request_id}
                  </td>
                  <td style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                    {JSON.stringify(log.metadata)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
