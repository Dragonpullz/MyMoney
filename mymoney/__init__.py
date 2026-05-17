"""MyMoney Flask app factory.

Production-shaped from day one (app factory + blueprints + config classes)
even though it currently only runs locally on 127.0.0.1. See INTERFACE_PLAN.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask

from .config import DevConfig, ProdConfig, TestConfig
from .extensions import csrf


# Make the .banksync-analysis package importable so blueprints can call into
# banksync_analysis.commands directly (one source of truth for analytics).
_ANALYSIS_DIR = Path(__file__).resolve().parent.parent / ".banksync-analysis"
if str(_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS_DIR))


def _pick_config(name: str | None):
    name = (name or os.environ.get("MYMONEY_ENV") or "dev").lower()
    if name in ("prod", "production"):
        return ProdConfig
    if name in ("test", "testing"):
        return TestConfig
    return DevConfig


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(_pick_config(config_name)())

    # Extensions
    csrf.init_app(app)

    # Security headers on every response
    @app.after_request
    def _set_security_headers(response):
        # CSP: no inline scripts; allow self + pinned Chart.js CDN (loaded with
        # SRI from base.html). Vendoring under static/vendor/ is also fine.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    # Blueprints
    from .blueprints import (
        anomalies,
        api,
        budgets,
        cashflow,
        home,
        opportunities,
        projection,
        query,
        refresh,
        report,
        subscriptions,
    )

    app.register_blueprint(home.bp)
    app.register_blueprint(query.bp)
    app.register_blueprint(cashflow.bp)
    app.register_blueprint(budgets.bp)
    app.register_blueprint(subscriptions.bp)
    app.register_blueprint(anomalies.bp)
    app.register_blueprint(opportunities.bp)
    app.register_blueprint(projection.bp)
    app.register_blueprint(report.bp)
    app.register_blueprint(refresh.bp)
    app.register_blueprint(api.bp)

    # Currency formatter for templates
    @app.template_filter("money")
    def _money(value):
        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return "$0.00"

    return app
