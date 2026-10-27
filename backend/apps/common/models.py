"""Common base models for Laptop Productivity Monitoring SaaS."""
import uuid
from django.db import models


class BaseUUIDModel(models.Model):
    """Abstract base model with a UUID v4 primary key."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    class Meta:
        abstract = True


class BaseTimestampedModel(BaseUUIDModel):
    """Abstract base model with UTC created_at and updated_at timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
