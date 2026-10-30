"""URL routes for Reports, Exports, Self-View, and Disputes API adhering to §8.4 and §11.3."""
from __future__ import annotations

from django.urls import path
from apps.analytics.views import (
    AppUsageSummaryView,
    DailyReportsView,
    DataExportCreateView,
    DataExportDetailView,
    DisputeDetailView,
    DisputeListCreateView,
    ProductivitySummaryView,
    SelfViewReportView,
    TimelineReportsView,
)

urlpatterns = [
    path("reports/daily", DailyReportsView.as_view(), name="report-daily"),
    path("reports/timeline", TimelineReportsView.as_view(), name="report-timeline"),
    path("reports/app-usage", AppUsageSummaryView.as_view(), name="report-app-usage"),
    path("reports/productivity-summary", ProductivitySummaryView.as_view(), name="report-productivity-summary"),
    path("reports/self-view", SelfViewReportView.as_view(), name="report-self-view"),
    path("disputes", DisputeListCreateView.as_view(), name="dispute-list-create"),
    path("disputes/<uuid:pk>", DisputeDetailView.as_view(), name="dispute-detail"),
    path("exports", DataExportCreateView.as_view(), name="export-create"),
    path("exports/<uuid:pk>", DataExportDetailView.as_view(), name="export-detail"),
]
