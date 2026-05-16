"""Configuration classes for the MyMoney Flask app.

Selection is env-driven via MYMONEY_ENV (dev|prod|test). DevConfig is the
default and is suitable for `flask --app mymoney run` on localhost. ProdConfig
is wired but intentionally not exercised yet — see INTERFACE_PLAN.md's
"If/When You Decide To Make It Public" checklist.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".banksync-cache"
ANALYSIS_DIR = REPO_ROOT / ".banksync-analysis"

# 32 MB cap on uploaded MCP dump JSON. Real dumps are well under this.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


class BaseConfig:
    # Filled in by env in subclasses; never trust this default in production.
    SECRET_KEY: str = "dev-only-not-for-production"

    # Where to bind when running via flask run. Code reads this; the CLI flag
    # `--host` still wins if passed explicitly.
    BIND_ADDRESS: str = os.environ.get("MYMONEY_BIND", "127.0.0.1")
    BIND_PORT: int = int(os.environ.get("MYMONEY_PORT", "5000"))

    # Auth: off in dev (single-user localhost). Set MYMONEY_AUTH=on later.
    AUTH_ENABLED: bool = os.environ.get("MYMONEY_AUTH", "off").lower() == "on"

    # Paths
    CACHE_DIR: Path = CACHE_DIR
    ANALYSIS_DIR: Path = ANALYSIS_DIR
    SUMMARY_PATH: Path = CACHE_DIR / "summary.json"
    NORMALIZED_PATH: Path = CACHE_DIR / "normalized.jsonl"

    # Upload limits enforced by Flask
    MAX_CONTENT_LENGTH: int = MAX_UPLOAD_BYTES

    # Cookies: harden by default. Secure flag flipped on in ProdConfig.
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    SESSION_COOKIE_SECURE: bool = False

    # WTF / CSRF
    WTF_CSRF_ENABLED: bool = True

    # If behind a reverse proxy in prod, set MYMONEY_BEHIND_PROXY=1 and wire
    # ProxyFix in wsgi.py (not active yet).
    BEHIND_PROXY: bool = os.environ.get("MYMONEY_BEHIND_PROXY", "0") == "1"


class DevConfig(BaseConfig):
    DEBUG = True
    # Generate a fresh per-process key so CSRF tokens are valid within a run.
    # Override with MYMONEY_SECRET_KEY for stable sessions across restarts.
    SECRET_KEY = os.environ.get("MYMONEY_SECRET_KEY") or secrets.token_hex(32)


class ProdConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True

    def __init__(self) -> None:
        # Flask's app.config.from_object() reads uppercase attributes via dir(),
        # which includes instance attributes set here. We instantiate ProdConfig
        # in create_app() before calling from_object(), so this runs first.
        key = os.environ.get("MYMONEY_SECRET_KEY")
        if not key or key == BaseConfig.SECRET_KEY:
            raise RuntimeError(
                "MYMONEY_SECRET_KEY must be set to a real secret in production."
            )
        self.SECRET_KEY = key


class TestConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    SECRET_KEY = "test-secret-key"
    # CSRF off in tests so we don't have to mint tokens for every smoke test;
    # a dedicated test re-enables it to verify the wiring works.
    WTF_CSRF_ENABLED = False
