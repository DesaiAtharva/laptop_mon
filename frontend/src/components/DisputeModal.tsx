import React, { useState } from "react";
import { api } from "../services/api";
import { DisputeItem } from "../types";

interface DisputeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onDisputeCreated?: (item: DisputeItem) => void;
}

export const DisputeModal: React.FC<DisputeModalProps> = ({
  isOpen,
  onClose,
  onDisputeCreated,
}) => {
  const [targetApp, setTargetApp] = useState("slack.exe");
  const [desiredClass, setDesiredClass] = useState("productive");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!isOpen) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!reason.trim()) return;

    setSubmitting(true);
    try {
      const created = await api.createDispute({
        target_app: targetApp,
        desired_classification: desiredClass,
        reason,
      });
      if (onDisputeCreated) {
        onDisputeCreated(created);
      }
      onClose();
    } catch (err) {
      alert(`Failed to submit dispute: ${err}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-window" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Submit Activity Dispute (E89)</h3>
          <button className="btn btn-secondary" onClick={onClose} style={{ padding: "4px 10px" }}>
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Application or Process Identifier</label>
            <input
              type="text"
              className="form-input"
              value={targetApp}
              onChange={(e) => setTargetApp(e.target.value)}
              placeholder="e.g. slack.exe, code.exe, terminal"
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">Desired Productivity Classification</label>
            <select
              className="form-select"
              value={desiredClass}
              onChange={(e) => setDesiredClass(e.target.value)}
            >
              <option value="productive">Productive</option>
              <option value="neutral">Neutral</option>
              <option value="distracting">Distracting</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label">Justification / Rationale</label>
            <textarea
              className="form-textarea"
              rows={4}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Explain why this activity or interval was misclassified (e.g., used for customer triage)..."
              required
            />
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px", marginTop: "1.5rem" }}>
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? "Submitting..." : "Submit Dispute"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
