"""Production settings."""
import os
from .base import *  # noqa: F403

DEBUG = False

# Fallback ensures SECRET_KEY is never empty if environment variable is blank
SECRET_KEY = (
    os.environ.get("DJANGO_SECRET_KEY")
    or os.environ.get("SECRET_KEY")
    or "prod-laptop-mon-saas-secret-key-2026-saptasurya"
)

# SSL & Proxy Termination settings
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = False  # Enforced directly by edge Nginx reverse proxy
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
