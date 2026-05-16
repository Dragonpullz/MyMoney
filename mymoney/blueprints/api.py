"""JSON API mirror of the HTML routes.

These are convenience aliases so a future SPA / mobile client can hit
``/api/<resource>`` instead of ``/<resource>?format=json``. They reuse the
exact same blueprint handlers under the hood.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import requires_login
from ..data import (
    cache_available,
    default_account_id,
    headline_kpis,
    last_refreshed,
    load_rules,
)


bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/status")
@requires_login
def status():
    return jsonify({
        "cacheAvailable": cache_available(),
        "lastRefreshed": last_refreshed(),
        "defaultAccountId": default_account_id(),
    })


@bp.route("/kpis")
@requires_login
def kpis():
    return jsonify(headline_kpis())


@bp.route("/rules")
@requires_login
def rules():
    # rules.json is local config — safe to return to the same-origin browser.
    return jsonify(load_rules())


# For any deeper resource, the existing HTML routes already honor
# ?format=json. Adding dedicated /api/<resource> aliases is straightforward:
#
#   @bp.route("/cashflow")
#   def _cashflow():
#       from . import cashflow
#       return cashflow.index()  # honors ?format=json
#
# Intentionally left for Step 7+ rather than duplicating wiring per page.
