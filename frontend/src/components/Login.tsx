import React, { useState } from "react";
import { useAuth } from "../context/AuthContext";

export const Login: React.FC = () => {
  const { login, isLoading } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [rememberMe, setRememberMe] = useState(true);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setErrorMessage("Please enter both email and password.");
      return;
    }

    setErrorMessage(null);
    try {
      await login(email.trim(), password);
    } catch (err: any) {
      const msg = err?.data?.message || err?.message || "Invalid credentials. Please verify your email and password.";
      setErrorMessage(msg);
    }
  };

  const fillCredentials = (quickEmail: string, quickPass: string) => {
    setEmail(quickEmail);
    setPassword(quickPass);
    setErrorMessage(null);
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "20px",
        background: "radial-gradient(ellipse at 50% 20%, #151e36 0%, #0a0d14 70%)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Decorative ambient background glows */}
      <div
        style={{
          position: "absolute",
          top: "10%",
          left: "20%",
          width: "450px",
          height: "450px",
          background: "radial-gradient(circle, rgba(56, 189, 248, 0.12) 0%, transparent 70%)",
          filter: "blur(60px)",
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: "10%",
          right: "20%",
          width: "500px",
          height: "500px",
          background: "radial-gradient(circle, rgba(99, 102, 241, 0.12) 0%, transparent 70%)",
          filter: "blur(60px)",
          pointerEvents: "none",
        }}
      />

      <div
        style={{
          width: "100%",
          maxWidth: "460px",
          background: "rgba(16, 21, 34, 0.85)",
          backdropFilter: "blur(20px)",
          border: "1px solid rgba(56, 189, 248, 0.25)",
          borderRadius: "20px",
          padding: "40px 36px",
          boxShadow: "0 20px 50px rgba(0, 0, 0, 0.6), 0 0 30px rgba(56, 189, 248, 0.1)",
          position: "relative",
          zIndex: 1,
        }}
      >
        {/* Brand Header */}
        <div style={{ textAlign: "center", marginBottom: "32px" }}>
          <div
            style={{
              width: "56px",
              height: "56px",
              borderRadius: "16px",
              background: "linear-gradient(135deg, #0284c7 0%, #6366f1 100%)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "0 auto 16px",
              boxShadow: "0 8px 24px rgba(2, 132, 199, 0.4)",
            }}
          >
            <svg
              width="30"
              height="30"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#ffffff"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
          </div>
          <h1
            style={{
              fontSize: "1.75rem",
              fontWeight: 800,
              fontFamily: "var(--font-display)",
              letterSpacing: "-0.03em",
              color: "#ffffff",
              marginBottom: "6px",
            }}
          >
            LaptopMon <span style={{ color: "var(--accent-cyan)", fontSize: "1.1rem" }}>Enterprise</span>
          </h1>
          <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
            Sign in to access your organization's telemetry console
          </p>
        </div>

        {/* Error Alert */}
        {errorMessage && (
          <div
            style={{
              backgroundColor: "rgba(244, 63, 94, 0.15)",
              border: "1px solid rgba(244, 63, 94, 0.4)",
              color: "#fecdd3",
              padding: "12px 16px",
              borderRadius: "10px",
              marginBottom: "20px",
              fontSize: "0.85rem",
              display: "flex",
              alignItems: "center",
              gap: "10px",
            }}
          >
            <span style={{ fontSize: "1.1rem" }}>⚠️</span>
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          <div>
            <label
              htmlFor="login-email"
              style={{
                display: "block",
                fontSize: "0.82rem",
                fontWeight: 600,
                color: "var(--text-main)",
                marginBottom: "8px",
                letterSpacing: "0.02em",
              }}
            >
              WORK EMAIL
            </label>
            <div style={{ position: "relative" }}>
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.com"
                required
                autoComplete="email"
                style={{
                  width: "100%",
                  padding: "13px 16px 13px 42px",
                  backgroundColor: "rgba(10, 13, 20, 0.8)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "10px",
                  color: "#ffffff",
                  fontSize: "0.95rem",
                  outline: "none",
                  transition: "border-color 0.2s, box-shadow 0.2s",
                }}
                onFocus={(e) => {
                  e.currentTarget.style.borderColor = "var(--accent-cyan)";
                  e.currentTarget.style.boxShadow = "0 0 12px var(--accent-cyan-glow)";
                }}
                onBlur={(e) => {
                  e.currentTarget.style.borderColor = "var(--border-subtle)";
                  e.currentTarget.style.boxShadow = "none";
                }}
              />
              <span
                style={{
                  position: "absolute",
                  left: "14px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: "var(--text-subtle)",
                  fontSize: "1rem",
                }}
              >
                ✉️
              </span>
            </div>
          </div>

          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <label
                htmlFor="login-password"
                style={{
                  fontSize: "0.82rem",
                  fontWeight: 600,
                  color: "var(--text-main)",
                  letterSpacing: "0.02em",
                }}
              >
                PASSWORD
              </label>
            </div>
            <div style={{ position: "relative" }}>
              <input
                id="login-password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                required
                autoComplete="current-password"
                style={{
                  width: "100%",
                  padding: "13px 44px 13px 42px",
                  backgroundColor: "rgba(10, 13, 20, 0.8)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "10px",
                  color: "#ffffff",
                  fontSize: "0.95rem",
                  outline: "none",
                  transition: "border-color 0.2s, box-shadow 0.2s",
                }}
                onFocus={(e) => {
                  e.currentTarget.style.borderColor = "var(--accent-cyan)";
                  e.currentTarget.style.boxShadow = "0 0 12px var(--accent-cyan-glow)";
                }}
                onBlur={(e) => {
                  e.currentTarget.style.borderColor = "var(--border-subtle)";
                  e.currentTarget.style.boxShadow = "none";
                }}
              />
              <span
                style={{
                  position: "absolute",
                  left: "14px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: "var(--text-subtle)",
                  fontSize: "1rem",
                }}
              >
                🔒
              </span>
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                style={{
                  position: "absolute",
                  right: "12px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  background: "transparent",
                  border: "none",
                  color: "var(--text-subtle)",
                  cursor: "pointer",
                  fontSize: "1rem",
                  padding: "4px",
                }}
                title={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? "👁️" : "👁️‍🗨️"}
              </button>
            </div>
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer", fontSize: "0.85rem", color: "var(--text-muted)" }}>
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                style={{ accentColor: "var(--accent-cyan)", cursor: "pointer" }}
              />
              Remember on this device
            </label>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            style={{
              width: "100%",
              padding: "14px",
              background: "linear-gradient(135deg, #0284c7 0%, #6366f1 100%)",
              color: "#ffffff",
              border: "none",
              borderRadius: "10px",
              fontWeight: 700,
              fontSize: "0.95rem",
              cursor: isLoading ? "wait" : "pointer",
              boxShadow: "0 4px 16px rgba(2, 132, 199, 0.4)",
              transition: "transform 0.15s, opacity 0.15s",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "8px",
            }}
          >
            {isLoading ? (
              <>
                <span className="spinner" style={{ width: "16px", height: "16px" }} />
                <span>Authenticating...</span>
              </>
            ) : (
              <span>Sign In to Console</span>
            )}
          </button>
        </form>

        {/* Quick Fill Helper for production testing */}
        <div style={{ marginTop: "28px", paddingTop: "20px", borderTop: "1px solid var(--border-subtle)" }}>
          <div style={{ fontSize: "0.75rem", color: "var(--text-subtle)", marginBottom: "10px", textTransform: "uppercase", letterSpacing: "0.04em", textAlign: "center" }}>
            Quick-Fill Credentials (Demo / Admin)
          </div>
          <div style={{ display: "flex", gap: "8px", justifyContent: "center", flexWrap: "wrap" }}>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: "0.75rem", padding: "6px 10px" }}
              onClick={() => fillCredentials("desaiatharv20@gmail.com", "Captain8959")}
            >
              👑 Superuser (desaiatharv20)
            </button>
          </div>
        </div>

        {/* Transparent Compliance Note */}
        <div
          style={{
            marginTop: "24px",
            textAlign: "center",
            fontSize: "0.75rem",
            color: "var(--text-subtle)",
            lineHeight: 1.4,
          }}
        >
          🛡️ Transparent, policy-driven monitoring.<br />
          Keystroke logging and password inspection are strictly forbidden.
        </div>
      </div>
    </div>
  );
};
