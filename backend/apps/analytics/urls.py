"""URL routes for Reports and Exports API adhering to §8.4."""
from __future__ import annotations

from django.urls import path
from apps.analytics.views import (
    AppUsageSummaryView,
    DailyReportsView,
    DataExportCreateView,
    DataExportDetailView,
    TimelineReportsView,
)

urlpatterns = [
    path("reports/daily", DailyReportsView.as_view(), name="report-daily"),
    path("reports/timeline", TimelineReportsView.as_view(), name="report-timeline"),
    path("reports/app-usage", AppUsageSummaryView.as_view(), name="report-app-usage"),
    path("exports", DataExportCreateView.as_view(), name="export-create"),
    path("exports/<uuid:pk>", DataExportDetailView.as_view(), name="export-detail"),
]
