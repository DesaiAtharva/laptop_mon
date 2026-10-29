# Plan: Production Login & Authentication Implementation

## Problem Statement
The user notes that the current frontend uses a demo role-switcher ("Role: Employee", "Wayne Enterprises", "Alex Vance") and lacks a real production-grade login page where users can authenticate with their real credentials (e.g. `desaiatharv20@gmail.com` / `Captain8959`). They requested an actual login page with password authentication that works like a production-level project.

## Requirements
1. **Backend Password Authentication Endpoint (`/api/auth/login`)**:
   - `PasswordLoginSerializer` taking `email` and `password`.
   - `PasswordLoginView`:
     - Verifies user exists, checks password using Django's secure password hashers (`check_password`).
     - Rejects disabled or invalid accounts.
     - Resolves user's active tenant memberships (auto-links superuser to active tenant with admin role if no membership exists yet).
     - Generates a cryptographically secure `UserSession` and returns raw bearer token, user profile, active tenant, and tenant list.
     - Writes durable audit log (`auth.password_sign_in`).
   - Wire route `api/auth/login` in `backend/apps/accounts/urls.py`.

2. **Frontend Authentication Architecture**:
   - Update `frontend/src/services/api.ts`:
     - Add `login(email, password)` and `logout()`.
     - Update token and tenant handling so real tokens and tenant IDs are attached to HTTP headers (`Authorization: Bearer <token>`, `X-Tenant-ID: <tenantId>`).
   - Update `frontend/src/context/AuthContext.tsx`:
     - Store authentication state (`isAuthenticated`, `token`, `user`, `activeTenant`, `tenants`, `role`).
     - Persist `authToken`, `activeTenant`, `currentUser` in `localStorage` so page reload stays logged in.
     - Provide `login(email, password)` and `logout()` functions.
   - Build `frontend/src/components/Login.tsx`:
     - High-end enterprise design aligned with dark theme (`--bg-primary: #0a0e17`, `--accent-cyan: #00e5ff`, `--accent-indigo: #6366f1`).
     - Includes organization logo, title, email/password form, loading spinner, error banners, and "remember me".
     - Includes testing quick-fill hints for production/seed accounts (`desaiatharv20@gmail.com`, `admin@acme.com`).
   - Update `frontend/src/App.tsx`:
     - If not authenticated, render `<Login />`.
     - If authenticated, render full application with sidebar and workspace navigation based on user's real role.
   - Update `frontend/src/components/Header.tsx`:
     - Show actual logged-in user name and email.
     - Show actual organization name.
     - Replace demo role dropdown with user's actual role badge.
     - Add a "Sign Out" button that triggers `logout()` and revokes the session on backend.

3. **Testing & Quality Assurance**:
   - Add unit/integration tests for `/api/auth/login` (valid login, invalid password, nonexistent user, disabled user).
   - Verify frontend builds cleanly with `npm run build`.
   - Verify all test suites pass.
   - Verify traceability check passes.
