import os
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()


def _bool_env(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('true', '1', 'yes', 'on')


def _decimal_env(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return Decimal(str(default))
    try:
        return Decimal(raw.strip())
    except Exception:
        return Decimal(str(default))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # MySQL Configuration
    MYSQL_HOST = os.environ.get('MYSQL_HOST') or 'localhost'
    MYSQL_USER = os.environ.get('MYSQL_USER') or 'root'
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD') or ''
    MYSQL_DB = os.environ.get('MYSQL_DB') or 'expendicure'
    MYSQL_PORT = int(os.environ.get('MYSQL_PORT') or 3306)

    # Flask Configuration
    DEBUG = _bool_env('FLASK_DEBUG', default=False)

    # Financial defaults (used by the deterministic finance engine from Phase 3 onwards).
    # Kept here so there is a single documented fallback when an account has no
    # account-level safety buffer configured.
    SAFETY_BUFFER = _decimal_env('SAFETY_BUFFER', default='2000')
