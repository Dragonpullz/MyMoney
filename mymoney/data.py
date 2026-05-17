"""Cache loaders + helpers shared by every blueprint.

Wraps the read functions from banksync_analysis.core with mtime-based
invalidation so the home page is snappy without long-lived in-process state.
Every loader returns ``None`` (or empty) when the cache is missing — the
templates render an empty-state instead of 500ing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import current_app

# These imports work because mymoney/__init__.py adds .banksync-analysis to
# sys.path before any blueprint is imported.
from banksync_analysis import core  # type: ignore[import-not-found]


_TRUTHY = {"1", "true", "on", "yes"}


def truthy(value: str | None) -> bool:
    """Shared boolean parsing for query-string flags like ``?all_accounts=1``."""
    return str(value or "").lower() in _TRUTHY


def safe_error(exc: BaseException, fallback: str = "Could not load data.") -> str:
    """Log the full exception server-side, return a generic message for the UI.

    Avoids leaking stack traces / internal paths to the browser even though
    we only run on localhost today.
    """
    # logger.exception() auto-captures the current exception's traceback.
    current_app.logger.exception("Request failed")
    if isinstance(exc, FileNotFoundError):
        return "Required cache file is missing. Run a refresh first."
    if isinstance(exc, ValueError):
        return "Invalid input. Check the filters and try again."
    return fallback


_summary_cache: dict[str, Any] = {"mtime": None, "payload": None}
_rules_cache: dict[str, Any] = {"mtime": None, "payload": None}


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None


def load_summary() -> dict[str, Any] | None:
    path: Path = current_app.config["SUMMARY_PATH"]
    mtime = _mtime(path)
    if mtime is None:
        return None
    if _summary_cache["mtime"] != mtime:
        _summary_cache["mtime"] = mtime
        _summary_cache["payload"] = core.load_json(path)
    return _summary_cache["payload"]


def load_rules() -> dict[str, Any]:
    path: Path = current_app.config["ANALYSIS_DIR"] / "rules.json"
    mtime = _mtime(path)
    if _rules_cache["mtime"] != mtime:
        _rules_cache["mtime"] = mtime
        _rules_cache["payload"] = core.get_rules(path)
    return _rules_cache["payload"]


def default_account_id() -> str:
    """Read defaultAccountId from rules.json at runtime — never hard-code."""
    return load_rules().get("defaultAccountId") or core.DEFAULT_ACCOUNT_ID


def account_choices() -> list[tuple[str, str]]:
    """List of (account_id, display_name) for select widgets.

    Returns at least the default account even when the cache is empty.
    """
    summary = load_summary()
    if summary and summary.get("accounts"):
        items = [
            (acct_id, info.get("accountName") or acct_id)
            for acct_id, info in summary["accounts"].items()
        ]
        items.sort(key=lambda row: row[1])
        return items
    rules = load_rules()
    return [(rules.get("defaultAccountId") or core.DEFAULT_ACCOUNT_ID,
             rules.get("defaultAccountName") or core.DEFAULT_ACCOUNT_NAME)]


def last_refreshed() -> str | None:
    """ISO timestamp of the most recent cache update, or None if no cache."""
    summary_mtime = _mtime(current_app.config["SUMMARY_PATH"])
    normalized_mtime = _mtime(current_app.config["NORMALIZED_PATH"])
    candidates = [m for m in (summary_mtime, normalized_mtime) if m]
    if not candidates:
        return None
    return datetime.fromtimestamp(max(candidates), tz=timezone.utc).isoformat()


def cache_available() -> bool:
    return _mtime(current_app.config["SUMMARY_PATH"]) is not None


def invalidate_cache() -> None:
    """Drop in-process caches. Call after a successful refresh."""
    _summary_cache["mtime"] = None
    _summary_cache["payload"] = None
    _rules_cache["mtime"] = None
    _rules_cache["payload"] = None


def headline_kpis() -> dict[str, Any]:
    """KPI row for the Home page: this-month spend / income / net for the
    default account, or zeros when the cache is empty."""
    summary = load_summary()
    if not summary:
        return {"month": None, "spend": 0.0, "income": 0.0, "net": 0.0, "scope": None}
    account_id = default_account_id()
    account = (summary.get("accounts") or {}).get(account_id) or {}
    monthly = account.get("monthly") or {}
    if not monthly:
        return {"month": None, "spend": 0.0, "income": 0.0, "net": 0.0,
                "scope": account.get("accountName") or account_id}
    month = sorted(monthly.keys())[-1]
    value = monthly[month] or {}
    return {
        "month": month,
        "spend": float(value.get("spend") or 0),
        "income": float(value.get("income") or 0),
        "net": float(value.get("net") or 0),
        "scope": account.get("accountName") or account_id,
    }
