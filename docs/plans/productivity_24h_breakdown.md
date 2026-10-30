# Plan: 24-Hour Productivity & Application Screen Time Suite

## Objectives
1. **Agent Telemetry Upgrade**:
   - Detect both application switch and browser tab/window title changes in `agent/core/scheduler.py`.
   - Ensure transitions inside Chrome, Edge, Brave, Firefox, etc., generate discrete `app.active` events with clean app names and window/tab titles.
2. **Backend Timeline Engine & Data Model**:
   - Add `window_title` to `AppUsageInterval` model and migration.
   - Update `TimelineReconstructionEngine` (`backend/apps/analytics/timeline.py`) and `IntervalDraft` to track active window titles and tab names across intervals.
   - Update `backend/apps/analytics/metrics.py` to persist `window_title` in intervals.
   - Create `ProductivitySummaryView` (`GET /api/reports/productivity-summary`) delivering a rich, dynamic 24-hour payload:
     - 24h summary metrics (active, idle, productive, neutral, distracting, offline seconds, productive share %).
     - 24-hour continuous timeline intervals (for Gantt scrubber).
     - Application leaderboard (total seconds, share %, classification, icon type).
     - Browser tab & domain breakdown (e.g. `chrome.exe` -> `github.com`, `youtube.com`, `docs.google.com` with respective durations).
     - Hourly activity distribution (Hour 0 to Hour 23).
3. **Frontend 24-Hour Productivity Dashboard**:
   - Create `frontend/src/components/ProductivityDashboard.tsx`:
     - Device selector & date picker (with Quick Date buttons: Today, Yesterday, etc.).
     - Stat KPI cards (Active time, Idle time, Productive Share %, Top App, Screenshots).
     - Interactive 24-hour Gantt Timeline bar (00:00 to 23:59) with hover tooltips and scrubber.
     - 24-hour hourly bar graph showing focus curve throughout the day.
     - Application Leaderboard with duration bars and classification badges.
     - In-browser Tab Breakdown displaying active websites/tabs and time spent.
   - Integrate into `frontend/src/App.tsx` sidebar navigation ("Productivity & Apps").
4. **Testing & Quality Assurance**:
   - Backend unit tests for `ProductivitySummaryView`, `TimelineReconstructionEngine` with window titles, and domain extraction.
   - TypeScript strict compilation and lint verification.
   - Update `TRACEABILITY.md`.
