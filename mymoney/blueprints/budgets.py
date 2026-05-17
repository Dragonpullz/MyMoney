"""Budgets: wraps banksync_analysis.commands.budget_status."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from banksync_analysis import commands  # type: ignore[import-not-found]

from ..auth import requires_login
from ..data import account_choices, cache_available, default_account_id, safe_error, truthy


bp = Blueprint("budgets", __name__)


def _run():
    month = request.args.get("month") or None
    account_id = request.args.get("account_id") or default_account_id()
    all_accounts = truthy(request.args.get("all_accounts"))
    if not cache_available():
        return None, "No cache yet. Run a refresh first."
    try:
        return commands.budget_status(
            month=month,
            account_id=None if all_accounts else account_id,
            all_accounts=all_accounts,
        ), None
    except (FileNotFoundError, ValueError) as exc:
        return None, safe_error(exc)


@bp.route("/budgets")
@requires_login
def index():
    result, error = _run()
    if request.args.get("format") == "json":
        if error:
            return jsonify({"error": error}), 400
        return jsonify(result or {})
    return render_template(
        "budgets.html",
        result=result,
        error=error,
        accounts=account_choices(),
        defaults={
            "month": request.args.get("month", ""),
            "account_id": request.args.get("account_id") or default_account_id(),
            "all_accounts": truthy(request.args.get("all_accounts")),
        },
    )
