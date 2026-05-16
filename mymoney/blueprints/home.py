"""Home: KPIs + refresh button."""

from __future__ import annotations

from flask import Blueprint, render_template

from ..auth import requires_login
from ..data import cache_available, headline_kpis, last_refreshed


bp = Blueprint("home", __name__)


@bp.route("/")
@requires_login
def index():
    return render_template(
        "home.html",
        kpis=headline_kpis(),
        last_refreshed=last_refreshed(),
        cache_available=cache_available(),
    )
