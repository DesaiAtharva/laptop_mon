# Plan: End-to-End One-Click Installer with Employee/Student ID & Permissions

## Context
Admins need to deploy the desktop monitoring agent to employees or students without requiring them to use command-line terminals or type manual Python commands. When the application is installed on a laptop, it must present an onboarding setup wizard that:
1. Displays clear, transparent First-Run Privacy Notices (REQ-2-2, spec §2.3) and captures permission consent.
2. Collects the Employee / Student ID (e.g. `EMP-102` or `STU-4501`) and Full Name.
3. Enrolls the device with the organization's SaaS backend and starts monitoring in the background with auto-startup.
4. Allows admins to easily download the pre-configured installer and clearly differentiate laptops by Employee/Student ID and Organization across all dashboard views.

## Architecture & Implementation Steps

### 1. Backend (`backend/apps/devices/` and `backend/apps/analytics/`)
- Add `employee_id` (indexed) and `employee_name` to `Device` model.
- Create and execute database migration.
- Update `AgentEnrollSerializer`, `DeviceSerializer`, and `enroll_device` service to accept and store `employee_id` and `employee_name`.
- Update `ProductivitySummaryView` and `DeviceListView` to include `employee_id` and `employee_name` in responses.
- Add endpoint to download pre-configured one-click installer batch script (`/api/devices/installer/download`).

### 2. Desktop Agent Installer (`agent/installer/`)
- Create `agent/installer/gui_installer.py`:
  - Built using standard Python `tkinter` (lightweight, built-in, 0 additional dependency weight per AGENTS.md).
  - Clean GUI layout with Organization branding, Employee/Student ID input, Employee Name input, and First-Run Privacy & Permission Notice consent (REQ-2-2).
  - Handles enrollment API call, generates credentials, registers Windows startup, and starts agent.
  - Falls back to CLI interactive prompt if running in headless environments.
- Create `agent/installer/install_windows.bat`:
  - One-click Windows runner that launches the installer wizard seamlessly.

### 3. Frontend Dashboard (`frontend/src/`)
- Update `types/index.ts` to include `employee_id` and `employee_name` on device interfaces.
- Update "Deploy Laptop Agent" modal in `ProductivityDashboard.tsx` and `Dashboard.tsx`:
  - Provide direct one-click Download Installer button.
  - Clean, user-friendly 3-step guide for employees/students.
- Update Level 1 table, Level 2 header, Level 3 summary, and Screenshot Vault to display Employee/Student ID & Full Name prominently.

### 4. Tests & Validation
- Unit & integration tests for device enrollment with `employee_id` and `employee_name`.
- Verify TypeScript compilation (`npm run build`) and Django check/tests.
