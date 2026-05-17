"""Cashflow: wraps banksync_analysis.commands.monthly_cashflow."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from banksync_analysis import commands  # type: ignore[import-not-found]

from ..auth import requires_login
from ..data import account_choices, cache_available, default_account_id, safe_error, truthy


bp = Blueprint("cashflow", __name__)


def _run():
    months = int(request.args.get("months", "12"))
    account_id = request.args.get("account_id") or default_account_id()
    all_accounts = truthy(request.args.get("all_accounts"))
    if not cache_available():
        return None, "No cache yet. Run a refresh first."
    try:
        return commands.monthly_cashflow(
            months=months,
            account_id=None if all_accounts else account_id,
            all_accounts=all_accounts,
        ), None
    except (FileNotFoundError, ValueError) as exc:
        return None, safe_error(exc)


@bp.route("/cashflow")
@requires_login
def index():
    result, error = _run()
    if request.args.get("format") == "json":
        if error:
            return jsonify({"error": error}), 400
        return jsonify(result or {})
    return render_template(
        "cashflow.html",
        result=result,
        error=error,
        accounts=account_choices(),
        defaults={
            "months": int(request.args.get("months", "12")),
            "account_id": request.args.get("account_id") or default_account_id(),
            "all_accounts": truthy(request.args.get("all_accounts")),
        },
    )
