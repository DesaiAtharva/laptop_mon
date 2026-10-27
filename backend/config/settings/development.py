"""Development settings."""
from .base import *  # noqa: F403

DEBUG = True

# Allow easy local development with SQLite if MySQL is not running locally
if os.environ.get("USE_MYSQL", "false").lower() != "true":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "dev_db.sqlite3",  # noqa: F405
        }
    }
