"""Projection: wraps banksync_analysis.commands.project_spend."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from banksync_analysis import commands  # type: ignore[import-not-found]

from ..auth import requires_login
from ..data import account_choices, cache_available, default_account_id, safe_error, truthy


bp = Blueprint("projection", __name__)

CATEGORIES = ["Spend", "Income", "Net"]


def _run():
    if not cache_available():
        return None, "No cache yet. Run a refresh first."
    try:
        return commands.project_spend(
            category=request.args.get("category", "Spend"),
            months_back=int(request.args.get("months_back", "12")),
            months_forward=int(request.args.get("months_forward", "6")),
            account_id=request.args.get("account_id") or default_account_id(),
            all_accounts=truthy(request.args.get("all_accounts")),
        ), None
    except (FileNotFoundError, ValueError) as exc:
        return None, safe_error(exc)


@bp.route("/projection")
@requires_login
def index():
    result, error = _run()
    if request.args.get("format") == "json":
        if error:
            return jsonify({"error": error}), 400
        return jsonify(result or {})
    return render_template(
        "projection.html",
        result=result,
        error=error,
        accounts=account_choices(),
        categories=CATEGORIES,
        defaults={
            "category": request.args.get("category", "Spend"),
            "months_back": int(request.args.get("months_back", "12")),
            "months_forward": int(request.args.get("months_forward", "6")),
            "account_id": request.args.get("account_id") or default_account_id(),
            "all_accounts": truthy(request.args.get("all_accounts")),
        },
    )
