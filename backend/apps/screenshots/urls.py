"""URL routes for screenshot endpoints adhering to §8.3 and §8.4."""
from __future__ import annotations

from django.urls import path
from apps.screenshots.views import (
    AgentScreenshotCompleteView,
    AgentScreenshotUploadIntentView,
    ScreenshotLegalDeleteView,
    ScreenshotLegalHoldView,
    ScreenshotListView,
    ScreenshotRetroactiveExclusionView,
    ScreenshotViewUrlView,
)

urlpatterns = [
    # Agent endpoints (§8.3)
    path(
        "agent/screenshots/upload-intents",
        AgentScreenshotUploadIntentView.as_view(),
        name="agent-screenshot-upload-intent",
    ),
    path(
        "agent/screenshots/complete",
        AgentScreenshotCompleteView.as_view(),
        name="agent-screenshot-complete",
    ),
    # Dashboard endpoints (§8.4)
    path(
        "screenshots",
        ScreenshotListView.as_view(),
        name="screenshot-list",
    ),
    path(
        "screenshots/<uuid:pk>/view-url",
        ScreenshotViewUrlView.as_view(),
        name="screenshot-view-url",
    ),
    path(
        "screenshots/legal-hold",
        ScreenshotLegalHoldView.as_view(),
        name="screenshot-legal-hold",
    ),
    path(
        "screenshots/legal-delete",
        ScreenshotLegalDeleteView.as_view(),
        name="screenshot-legal-delete",
    ),
    path(
        "screenshots/retroactive-exclusion",
        ScreenshotRetroactiveExclusionView.as_view(),
        name="screenshot-retroactive-exclusion",
    ),
]
