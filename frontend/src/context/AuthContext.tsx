import React, { createContext, useContext, useEffect, useState } from "react";
import { api, setApiAuth } from "../services/api";
import { MembershipRole, Tenant } from "../types";

interface AuthContextType {
  tenants: Tenant[];
  activeTenant: Tenant | null;
  setActiveTenant: (t: Tenant) => void;
  role: MembershipRole;
  setRole: (r: MembershipRole) => void;
  timezonePref: "local" | "UTC";
  setTimezonePref: (tz: "local" | "UTC") => void;
  userName: string;
  userEmail: string;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [tenants, setTenants] = useState<Tenant[]>([
    { id: "ten-01", name: "Acme Cybernetics", status: "active" },
    { id: "ten-02", name: "Wayne Enterprises", status: "active" },
    { id: "ten-03", name: "Stark Industries", status: "active" },
  ]);
  const [activeTenant, setActiveTenant] = useState<Tenant | null>(tenants[0] || null);
  const [role, setRole] = useState<MembershipRole>("employee");
  const [timezonePref, setTimezonePref] = useState<"local" | "UTC">("local");
  const [userName] = useState("Alex Vance");
  const [userEmail] = useState("alex@enterprise.com");

  useEffect(() => {
    async function loadTenants() {
      try {
        const list = await api.getUserTenants();
        if (list && list.length > 0) {
          setTenants(list);
          if (!activeTenant) {
            setActiveTenant(list[0]);
          }
        }
      } catch (err) {
        console.warn("Could not fetch remote tenants, using default list", err);
      }
    }
    loadTenants();
  }, []);

  useEffect(() => {
    if (activeTenant) {
      setApiAuth("mock-bearer-token", activeTenant.id);
    }
  }, [activeTenant]);

  return (
    <AuthContext.Provider
      value={{
        tenants,
        activeTenant,
        setActiveTenant,
        role,
        setRole,
        timezonePref,
        setTimezonePref,
        userName,
        userEmail,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
