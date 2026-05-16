"""Opportunities: wraps banksync_analysis.commands.find_opportunities."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from banksync_analysis import commands  # type: ignore[import-not-found]

from ..auth import requires_login
from ..data import account_choices, cache_available, default_account_id, safe_error, truthy


bp = Blueprint("opportunities", __name__)


def _run():
    if not cache_available():
        return None, "No cache yet. Run a refresh first."
    try:
        return commands.find_opportunities(
            lookback_months=int(request.args.get("lookback_months", "6")),
            account_id=request.args.get("account_id") or default_account_id(),
            all_accounts=truthy(request.args.get("all_accounts")),
        ), None
    except (FileNotFoundError, ValueError) as exc:
        return None, safe_error(exc)


@bp.route("/opportunities")
@requires_login
def index():
    result, error = _run()
    if request.args.get("format") == "json":
        if error:
            return jsonify({"error": error}), 400
        return jsonify({"opportunities": result or []})
    return render_template(
        "opportunities.html",
        result=result,
        error=error,
        accounts=account_choices(),
        defaults={
            "lookback_months": int(request.args.get("lookback_months", "6")),
            "account_id": request.args.get("account_id") or default_account_id(),
            "all_accounts": truthy(request.args.get("all_accounts")),
        },
    )
