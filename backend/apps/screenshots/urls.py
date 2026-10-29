"""URL routes for screenshot endpoints adhering to §8.3 and §8.4."""
from __future__ import annotations

from django.urls import path, re_path
from apps.screenshots.views import (
    AgentScreenshotCompleteView,
    AgentScreenshotUploadIntentView,
    ScreenshotLegalDeleteView,
    ScreenshotLegalHoldView,
    ScreenshotListView,
    ScreenshotRetroactiveExclusionView,
    ScreenshotViewUrlView,
    StorageUploadView,
    StorageViewView,
)

urlpatterns = [
    # Agent endpoints (§8.3)
    re_path(
        r"^agent/screenshots/upload-intents/?$",
        AgentScreenshotUploadIntentView.as_view(),
        name="agent-screenshot-upload-intent",
    ),
    re_path(
        r"^agent/screenshots/complete/?$",
        AgentScreenshotCompleteView.as_view(),
        name="agent-screenshot-complete",
    ),
    re_path(
        r"^agent/screenshots/storage-upload/?$",
        StorageUploadView.as_view(),
        name="storage-upload",
    ),
    # Dashboard endpoints (§8.4)
    re_path(
        r"^screenshots/storage-view/?$",
        StorageViewView.as_view(),
        name="storage-view",
    ),
    re_path(
        r"^screenshots/?$",
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
