"""Base Django settings for Laptop Productivity Monitoring SaaS."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent
import sys
for p in [str(BASE_DIR), str(REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-laptop-mon-saas-2026-strict-rulebook")

DEBUG = False

ALLOWED_HOSTS: List[str] = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
    if h.strip()
]

# Application definition
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "rest_framework",
    # Monolith modular apps
    "apps.common",
    "apps.accounts",
    "apps.tenancy",
    "apps.rbac",
    "apps.audit",
    "apps.support_access",
    "apps.devices",
    "apps.policies",
    "apps.ingestion",
    "apps.screenshots",
]

MIDDLEWARE = [
    "apps.common.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.SessionRevocationMiddleware",
    "apps.tenancy.middleware.TenantContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.audit.middleware.AuditLogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES: List[dict[str, Any]] = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Custom User Model
AUTH_USER_MODEL = "accounts.User"

# Database Configuration
# Default to MySQL 8 InnoDB utf8mb4 when configured, fallback to sqlite3 for lightweight tests
DB_ENGINE = os.environ.get("DB_ENGINE", "django.db.backends.mysql")
DB_NAME = os.environ.get("MYSQL_DATABASE", "laptop_mon")
DB_USER = os.environ.get("MYSQL_USER", "laptop_mon_user")
DB_PASSWORD = os.environ.get("MYSQL_PASSWORD", "laptop_mon_secret")
DB_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
DB_PORT = os.environ.get("MYSQL_PORT", "3306")

if os.environ.get("USE_SQLITE", "false").lower() == "true":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": DB_NAME,
            "USER": DB_USER,
            "PASSWORD": DB_PASSWORD,
            "HOST": DB_HOST,
            "PORT": DB_PORT,
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET default_storage_engine=INNODB, character_set_connection=utf8mb4, collation_connection=utf8mb4_unicode_ci",
            }
            if "mysql" in DB_ENGINE
            else {},
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization & UTC Timestamps
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache Configuration
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/1")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "laptop-mon-cache",
    }
}

# Django REST Framework Configuration (§8.1 error contracts)
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.BearerTokenAuthentication",
        "apps.devices.authentication.DeviceBearerAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "apps.common.exceptions.custom_exception_handler",
    "UNAUTHENTICATED_USER": None,
}

# Security Headers
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_BROWSER_XSS_FILTER = True

# Support Access Defaults
SUPPORT_ACCESS_MAX_HOURS = 8

# Object Storage Configuration (§10.2, REQ-10-1)
SCREENSHOT_STORAGE_BACKEND = os.environ.get(
    "SCREENSHOT_STORAGE_BACKEND", "apps.screenshots.storage.MemoryObjectStorageBackend"
)
SCREENSHOT_STORAGE_BUCKET = os.environ.get("SCREENSHOT_STORAGE_BUCKET", "laptop-mon-screenshots")
SCREENSHOT_STORAGE_ENDPOINT = os.environ.get("SCREENSHOT_STORAGE_ENDPOINT", "http://127.0.0.1:9000")
SCREENSHOT_STORAGE_ACCESS_KEY = os.environ.get("SCREENSHOT_STORAGE_ACCESS_KEY", "minioadmin")
SCREENSHOT_STORAGE_SECRET_KEY = os.environ.get("SCREENSHOT_STORAGE_SECRET_KEY", "minioadmin")
SCREENSHOT_STORAGE_REGION = os.environ.get("SCREENSHOT_STORAGE_REGION", "us-east-1")
SCREENSHOT_VIEW_URL_EXPIRY_SECONDS = int(os.environ.get("SCREENSHOT_VIEW_URL_EXPIRY_SECONDS", "300"))
SCREENSHOT_UPLOAD_INTENT_EXPIRY_SECONDS = int(os.environ.get("SCREENSHOT_UPLOAD_INTENT_EXPIRY_SECONDS", "900"))
SCREENSHOT_MAX_FILE_SIZE_BYTES = int(os.environ.get("SCREENSHOT_MAX_FILE_SIZE_BYTES", str(10 * 1024 * 1024)))
SCREENSHOT_MAX_WIDTH = 7680
SCREENSHOT_MAX_HEIGHT = 4320
