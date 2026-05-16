"""Query: form + results. Wraps the CLI ``query.py`` build_query() function.

This is the workhorse page — replaces ~80% of CLI usage.
"""

from __future__ import annotations

from argparse import Namespace

from flask import Blueprint, jsonify, render_template, request

import query as cli_query  # type: ignore[import-not-found]

from ..auth import requires_login
from ..data import account_choices, cache_available, default_account_id, safe_error, truthy


bp = Blueprint("query", __name__)

CATEGORY_PRESETS = [
    "gas", "groceries", "restaurants", "fastfood", "coffee", "dining",
    "utilities", "electricity", "internet", "mortgage", "ccpayments",
    "insurance", "pharmacy", "vet", "amazon", "subscriptions", "transfers",
    "income",
]


def _build_args() -> Namespace:
    return Namespace(
        Files=[],  # web layer always uses the cache, never raw dump paths
        Category=request.args.get("category", "."),
        From=request.args.get("from") or None,
        To=request.args.get("to") or None,
        AccountId=request.args.get("account_id") or default_account_id(),
        AllAccounts=truthy(request.args.get("all_accounts")),
        Top=int(request.args.get("top", "20")),
        Income=truthy(request.args.get("income")),
        ByMerchant=truthy(request.args.get("by_merchant", "1")),
        Detailed=truthy(request.args.get("detailed")),
        Format="json",
    )


def _run_query():
    if not cache_available():
        return None, "No cache yet. Click 'Refresh data' on the Home page first."
    try:
        return cli_query.build_query(_build_args()), None
    except FileNotFoundError as exc:
        return None, safe_error(exc)
    except ValueError as exc:
        return None, safe_error(exc)


@bp.route("/query")
@requires_login
def index():
    # Default behavior: if the user hasn't submitted, show an empty form.
    submitted = bool(request.args)
    result, error = (_run_query() if submitted else (None, None))

    if request.args.get("format") == "json":
        if error:
            return jsonify({"error": error}), 400
        return jsonify(result or {})

    return render_template(
        "query.html",
        result=result,
        error=error,
        submitted=submitted,
        presets=CATEGORY_PRESETS,
        accounts=account_choices(),
        defaults={
            "category": request.args.get("category", "."),
            "from": request.args.get("from", ""),
            "to": request.args.get("to", ""),
            "account_id": request.args.get("account_id") or default_account_id(),
            "all_accounts": truthy(request.args.get("all_accounts")),
            "income": truthy(request.args.get("income")),
            "by_merchant": truthy(request.args.get("by_merchant", "1")),
            "detailed": truthy(request.args.get("detailed")),
        },
    )
