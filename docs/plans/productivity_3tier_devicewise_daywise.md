# Plan: 3-Tier Device-Wise & Day-Wise 24h Productivity Suite

## Objectives
1. **Backend Enhancement (`backend/apps/analytics/views.py`)**:
   - Update `ProductivitySummaryView` to include device fleet aggregations (`total_days`, `total_active_seconds`, `avg_productive_share`, `total_screenshots`) for each device in `available_devices`.
   - Aggregate all active calendar dates and daily metrics for the requested device into `device_days` (date, active_seconds, idle_seconds, productive_seconds, productive_share, total_screenshots).
2. **Frontend Type Updates (`frontend/src/types/index.ts`)**:
   - Update `ProductivitySummaryData` and add `DeviceDaySummary` interface.
3. **Frontend 3-Tier Drill-Down UI (`frontend/src/components/ProductivityDashboard.tsx`)**:
   - Match the exact 3-level pattern used in `ScreenshotGallery.tsx`:
     - **Level 1 (`devices`)**: Monitored Devices Table with Hostname, OS, Monitored Days, Cumulative Active Hours, Average Focus Share, Screenshot Proofs, Last Active, and `[View Activity Calendar →]` action.
     - **Level 2 (`days`)**: Day-Wise Calendar Table for the selected device with Date, Active Work Time bar, Idle Time, Focus Score badge, Screenshot Count, and `[View 24h Breakdown →]` action.
     - **Level 3 (`detail`)**: Full 24-Hour Detailed Productivity Breakdown with KPI tiles, continuous 24h Gantt bar (00:00 to 23:59), interactive time scrubber, 24 hourly activity curve, application leaderboard, and expandable in-browser tab & domain analytics.
     - Breadcrumbs and `← Back` buttons at every level for seamless navigation.
4. **Testing & Build Verification**:
   - Run backend test suite `python backend/manage.py test tests.test_p4_analytics_timeline_reports`.
   - Run `npm run build` in `frontend/` to ensure zero TypeScript errors.
   - Update `TRACEABILITY.md`.
