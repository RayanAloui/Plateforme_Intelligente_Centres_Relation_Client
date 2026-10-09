"""Configuration Django de la plateforme.

La base de donnees est la meme que celle du moteur (PostgreSQL) : les tables de
l'application vivent dans le schema "app", a cote de raw, core et ref.
Les commandes se lancent depuis la RACINE du projet (les chemins data/, models/,
outputs/ du moteur sont relatifs a ce dossier).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

from crc.config import get_settings

BASE_DIR = Path(__file__).resolve().parent.parent          # webapp/
PROJECT_DIR = BASE_DIR.parent                              # racine du projet
load_dotenv(PROJECT_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
if not DEBUG and (SECRET_KEY.startswith(("dev-only", "change-me")) or len(SECRET_KEY) < 32):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("En production (DJANGO_DEBUG=0), definir DJANGO_SECRET_KEY : 32 caracteres ou plus.")
# Mode demonstration : comptes affiches a la connexion, bouton "jour suivant" (etape C).
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [f"{scheme}://{h}{port}" for h in ALLOWED_HOSTS
                        for scheme in ("http", "https") for port in ("", ":8000")]

# Derriere un proxy HTTPS (DJANGO_HTTPS=1) : cookies securises, HSTS, redirection vers HTTPS.
if os.environ.get("DJANGO_HTTPS", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django_htmx",
    "accounts",
    "engine",
    "planning",
    "alerts",
    "assistant",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "portal.context_processors.navigation",
    ]},
}]

_db = get_settings()
RANDOM_SEED = _db.random_seed
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": _db.postgres_db, "USER": _db.postgres_user, "PASSWORD": _db.postgres_password,
    "HOST": _db.postgres_host, "PORT": _db.postgres_port,
    # Les tables Django sont creees dans le schema "app" ; raw/core/ref restent accessibles.
    "OPTIONS": {"options": "-c search_path=app,public"},
}}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
]

# Les donnees du centre sont en heure locale naive, sans changement d'heure (convention de
# l'etape 1.2). On declare donc UTC, qui n'a pas de changement d'heure : un horodatage comme
# 30/03/2025 02:30 est stocke tel quel, alors qu'en Europe/Paris il n'existerait pas.
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = False

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = PROJECT_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

SESSION_COOKIE_AGE = 12 * 3600                 # une journee de travail
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{asctime} {levelname} {name} : {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO" if not DEBUG else "WARNING"},
    "loggers": {"planning": {"level": "INFO"}, "assistant": {"level": "INFO"}},
}
