import React, { createContext, useContext, useEffect, useState } from "react";
import { api, clearApiAuth, setApiAuth } from "../services/api";
import { MembershipRole, Tenant } from "../types";

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: MembershipRole;
  is_superuser: boolean;
}

interface AuthContextType {
  isAuthenticated: boolean;
  user: AuthUser | null;
  tenants: Tenant[];
  activeTenant: Tenant | null;
  setActiveTenant: (t: Tenant) => void;
  role: MembershipRole;
  setRole: (r: MembershipRole) => void;
  timezonePref: "local" | "UTC";
  setTimezonePref: (tz: "local" | "UTC") => void;
  userName: string;
  userEmail: string;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(() => {
    return Boolean(localStorage.getItem("laptopmon_token"));
  });
  const [user, setUser] = useState<AuthUser | null>(() => {
    const saved = localStorage.getItem("laptopmon_user");
    return saved ? JSON.parse(saved) : null;
  });
  const [tenants, setTenants] = useState<Tenant[]>(() => {
    const saved = localStorage.getItem("laptopmon_tenants");
    return saved ? JSON.parse(saved) : [];
  });
  const [activeTenant, setActiveTenant] = useState<Tenant | null>(() => {
    const saved = localStorage.getItem("laptopmon_tenant");
    return saved ? JSON.parse(saved) : null;
  });
  const [role, setRole] = useState<MembershipRole>(() => {
    const saved = localStorage.getItem("laptopmon_user");
    if (saved) {
      try {
        const u = JSON.parse(saved);
        return u.role || "employee";
      } catch {
        return "employee";
      }
    }
    return "employee";
  });
  const [timezonePref, setTimezonePref] = useState<"local" | "UTC">("local");
  const [isLoading, setIsLoading] = useState<boolean>(false);

  // Initialize API headers from stored session on mount
  useEffect(() => {
    const token = localStorage.getItem("laptopmon_token");
    if (token) {
      setApiAuth(token, activeTenant?.id || "");
    }
  }, [activeTenant]);

  // Load latest tenant memberships if authenticated
  useEffect(() => {
    if (!isAuthenticated) return;
    async function refreshTenants() {
      try {
        const list = await api.getUserTenants();
        if (list && list.length > 0) {
          setTenants(list);
          localStorage.setItem("laptopmon_tenants", JSON.stringify(list));
          if (!activeTenant || !list.some((t) => t.id === activeTenant.id)) {
            setActiveTenant(list[0]);
            localStorage.setItem("laptopmon_tenant", JSON.stringify(list[0]));
          }
        }
      } catch (err) {
        console.warn("Could not refresh user tenants:", err);
      }
    }
    refreshTenants();
  }, [isAuthenticated]);

  const handleSetActiveTenant = (tenant: Tenant) => {
    setActiveTenant(tenant);
    localStorage.setItem("laptopmon_tenant", JSON.stringify(tenant));
    const token = localStorage.getItem("laptopmon_token") || "";
    setApiAuth(token, tenant.id);
  };

  const login = async (email: string, password: string): Promise<void> => {
    setIsLoading(true);
    try {
      const resp = await api.login(email, password);
      const token = resp.token;
      const loggedUser: AuthUser = {
        id: resp.user.id,
        email: resp.user.email,
        name: resp.user.name || resp.user.email.split("@")[0],
        role: (resp.user.role as MembershipRole) || "employee",
        is_superuser: Boolean(resp.user.is_superuser),
      };

      localStorage.setItem("laptopmon_token", token);
      localStorage.setItem("laptopmon_user", JSON.stringify(loggedUser));

      setUser(loggedUser);
      setRole(loggedUser.role);
      setIsAuthenticated(true);

      if (resp.tenant) {
        setActiveTenant(resp.tenant);
        localStorage.setItem("laptopmon_tenant", JSON.stringify(resp.tenant));
        setApiAuth(token, resp.tenant.id);
      } else {
        setApiAuth(token, "");
      }

      if (resp.tenants && resp.tenants.length > 0) {
        setTenants(resp.tenants);
        localStorage.setItem("laptopmon_tenants", JSON.stringify(resp.tenants));
      }
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async (): Promise<void> => {
    try {
      await api.logout();
    } catch {
      // Ignore network errors on logout
    }
    localStorage.removeItem("laptopmon_token");
    localStorage.removeItem("laptopmon_user");
    localStorage.removeItem("laptopmon_tenant");
    localStorage.removeItem("laptopmon_tenants");
    clearApiAuth();
    setIsAuthenticated(false);
    setUser(null);
    setActiveTenant(null);
    setTenants([]);
    setRole("employee");
  };

  const userName = user?.name || "User";
  const userEmail = user?.email || "";

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated,
        user,
        tenants,
        activeTenant,
        setActiveTenant: handleSetActiveTenant,
        role,
        setRole,
        timezonePref,
        setTimezonePref,
        userName,
        userEmail,
        login,
        logout,
        isLoading,
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
