import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "local-development-only-change-before-deployment",
)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "django_htmx",
    "workflows",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "reliability_lab.middleware.RequestTraceMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "reliability_lab.middleware.DemonstrationGuardMiddleware",
]

ROOT_URLCONF = "reliability_lab.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.static",
            ],
        },
    }
]

WSGI_APPLICATION = "reliability_lab.wsgi.application"
ASGI_APPLICATION = "reliability_lab.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(os.environ.get("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3")),
        "OPTIONS": {"timeout": 10},
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "reliability-lab-results",
        "TIMEOUT": 300,
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
