from __future__ import annotations

import calendar
import json
import math
import re
import shutil
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from .core import (
    ANALYSIS_ROOT,
    REPO_ROOT,
    add_months,
    compact_json,
    excluded_from_spend,
    get_merchant_alias_map,
    get_rules,
    load_json,
    merchant_key,
    metric,
    money,
    normalize_merchant,
    parse_yyyy_mm,
    read_summary,
    read_transactions,
    unique_by_id,
    virtual_category_hits,
    write_json,
)


def _sum(rows: Iterable[dict[str, Any]], field: str) -> float:
    return sum(float(row.get(field) or 0) for row in rows)


def _avg(values: Iterable[float]) -> float | None:
    items = [float(value) for value in values]
    if not items:
        return None
    return sum(items) / len(items)


def _stddev(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) * (value - mean) for value in values) / (len(values) - 1))


def _group(rows: Iterable[dict[str, Any]], key_func) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(key_func(row), []).append(row)
    return grouped


def _sorted_months(months: Iterable[str]) -> list[str]:
    return sorted(month for month in months if month)


def _account_month(summary: dict[str, Any], account_id: str, month: str) -> dict[str, Any] | None:
    account = (summary.get("accounts") or {}).get(account_id)
    if not account:
        return None
    return (account.get("monthly") or {}).get(month)


def _month_start_today() -> date:
    today = date.today()
    return date(today.year, today.month, 1)


def _current_month() -> str:
    return date.today().strftime("%Y-%m")


def _scope_label(summary: dict[str, Any], account_id: str | None, all_accounts: bool) -> str:
    if all_accounts or not account_id:
        return "ALL accounts"
    account = (summary.get("accounts") or {}).get(account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found in summary.")
    return account.get("accountName") or account_id


def build_summary(cache_root: Path | None = None, top_merchants: int = 10) -> dict[str, Any]:
    rules = get_rules()
    root = cache_root or REPO_ROOT / ".banksync-cache"
    cache_path = root / "normalized.jsonl"
    transactions = unique_by_id(read_transactions(cache_path))

    default_account_id = rules["defaultAccountId"]
    default_account = next((t for t in transactions if t.get("accountId") == default_account_id), None)

    accounts: OrderedDict[str, Any] = OrderedDict()
    for account_id, account_rows in sorted(_group(transactions, lambda row: row.get("accountId") or "").items()):
        first = account_rows[0]
        monthly: OrderedDict[str, Any] = OrderedDict()
        for month, month_rows in sorted(_group(account_rows, lambda row: row.get("month") or "").items()):
            spend_rows = [
                row
                for row in month_rows
                if float(row.get("debitAmount") or 0) > 0 and not excluded_from_spend(row, rules)
            ]
            income_rows = [
                row
                for row in month_rows
                if float(row.get("creditAmount") or 0) > 0 and not row.get("isTransfer")
            ]
            spend = money(_sum(spend_rows, "debitAmount"))
            income = money(_sum(income_rows, "creditAmount"))
            net = money(income - spend)
            savings_rate = metric(net / income, 4) if income > 0 else None

            by_category = OrderedDict()
            category_groups = _group(spend_rows, lambda row: row.get("category") or "")
            for category, rows in sorted(category_groups.items(), key=lambda item: _sum(item[1], "debitAmount"), reverse=True):
                by_category[category] = money(_sum(rows, "debitAmount"))

            vc_totals: dict[str, float] = {}
            for row in spend_rows:
                for hit in virtual_category_hits(row, rules):
                    vc_totals[hit] = vc_totals.get(hit, 0.0) + float(row.get("debitAmount") or 0)
            by_virtual_category = OrderedDict(
                (key, money(value)) for key, value in sorted(vc_totals.items(), key=lambda item: item[1], reverse=True)
            )

            merchant_groups = _group(spend_rows, merchant_key)
            top = []
            for merchant, rows in sorted(merchant_groups.items(), key=lambda item: _sum(item[1], "debitAmount"), reverse=True)[:top_merchants]:
                top.append({"merchant": merchant, "total": money(_sum(rows, "debitAmount")), "count": len(rows)})

            monthly[month] = {
                "spend": spend,
                "income": income,
                "net": net,
                "savingsRate": savings_rate,
                "txnCount": len(month_rows),
                "spendTxnCount": len(spend_rows),
                "byCategory": by_category,
                "byVirtualCategory": by_virtual_category,
                "topMerchants": top,
            }

        local_dates = sorted({str(row.get("localDate") or "") for row in account_rows if row.get("localDate")})
        accounts[account_id] = {
            "accountId": account_id,
            "accountName": first.get("accountName"),
            "bankId": first.get("bankId"),
            "txnCount": len(account_rows),
            "firstSeen": local_dates[0] if local_dates else None,
            "lastSeen": local_dates[-1] if local_dates else None,
            "monthly": monthly,
        }

    all_dates = sorted({str(row.get("localDate") or "") for row in transactions if row.get("localDate")})
    summary = {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "source": str(cache_path.resolve()),
        "txnCount": len(transactions),
        "range": {"from": all_dates[0] if all_dates else None, "to": all_dates[-1] if all_dates else None},
        "scopeDefaults": {
            "accountId": default_account_id,
            "accountName": (default_account or {}).get("accountName") or rules.get("defaultAccountName"),
        },
        "rules": {
            "excludeFromHouseholdSpend": rules.get("excludeFromHouseholdSpend"),
            "virtualCategories": list((rules.get("virtualCategories") or {}).keys()),
        },
        "accounts": accounts,
    }
    write_json(root / "summary.json", summary)
    return summary


def monthly_cashflow(months: int = 12, account_id: str | None = None, all_accounts: bool = False, summary_path: Path | None = None) -> dict[str, Any]:
    rules = get_rules()
    account_id = account_id or rules["defaultAccountId"]
    summary = read_summary(summary_path)
    rows_by_month: dict[str, dict[str, Any]] = {}

    if all_accounts:
        scope = "ALL accounts"
        for account in (summary.get("accounts") or {}).values():
            for month, value in (account.get("monthly") or {}).items():
                row = rows_by_month.setdefault(month, {"month": month, "spend": 0.0, "income": 0.0, "net": 0.0})
                row["spend"] += float(value.get("spend") or 0)
                row["income"] += float(value.get("income") or 0)
    else:
        account = (summary.get("accounts") or {}).get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found in summary.")
        scope = account.get("accountName") or account_id
        for month, value in (account.get("monthly") or {}).items():
            rows_by_month[month] = {
                "month": month,
                "spend": float(value.get("spend") or 0),
                "income": float(value.get("income") or 0),
                "net": float(value.get("net") or 0),
            }

    rows = [rows_by_month[month] for month in sorted(rows_by_month)][-months:]
    for index, row in enumerate(rows):
        row["spend"] = money(row["spend"])
        row["income"] = money(row["income"])
        row["net"] = money(row["income"] - row["spend"])
        row["savingsRate"] = metric(row["net"] / row["income"], 4) if row["income"] > 0 else None
        window = rows[max(0, index - 2) : index + 1]
        row["spend3mAvg"] = money(_avg([item["spend"] for item in window]))
        row["income3mAvg"] = money(_avg([item["income"] for item in window]))
        row["net3mAvg"] = money(_avg([item["net"] for item in window]))

    latest_year = rows[-1]["month"][:4] if rows else None
    ytd_rows = [row for row in rows if latest_year and row["month"].startswith(latest_year)]
    ytd = None
    if ytd_rows:
        ytd = {
            "year": latest_year,
            "spend": money(_sum(ytd_rows, "spend")),
            "income": money(_sum(ytd_rows, "income")),
            "net": money(_sum(ytd_rows, "net")),
        }
    return {"scope": scope, "months": rows, "ytd": ytd}


def budget_status(month: str | None = None, account_id: str | None = None, all_accounts: bool = False, budget_path: Path | None = None, summary_path: Path | None = None) -> dict[str, Any]:
    rules = get_rules()
    account_id = account_id or rules["defaultAccountId"]
    month = month or _current_month()
    if not re.match(r"^\d{4}-\d{2}$", month):
        raise ValueError(f"Month must be yyyy-MM, got '{month}'.")

    budgets = load_json(budget_path or ANALYSIS_ROOT / "budgets.json")
    if not budgets.get("monthly"):
        raise ValueError("Budget file has no 'monthly' object.")
    summary = read_summary(summary_path)

    month_start = parse_yyyy_mm(month)
    days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]
    today = date.today()
    this_month_start = date(today.year, today.month, 1)
    if today.strftime("%Y-%m") == month:
        days_elapsed = min(days_in_month, max(1, today.day))
    elif month_start < this_month_start:
        days_elapsed = days_in_month
    else:
        days_elapsed = 1

    def add_category_amounts(target: dict[str, float], month_value: dict[str, Any] | None) -> None:
        if not month_value:
            return
        for category, value in (month_value.get("byVirtualCategory") or {}).items():
            target[category] = target.get(category, 0.0) + float(value or 0)

    actuals: dict[str, float] = {}
    prior_actuals: dict[str, float] = {}
    prior_month = add_months(month_start, -1).strftime("%Y-%m")

    if all_accounts:
        scope = "ALL accounts"
        for account in (summary.get("accounts") or {}).values():
            monthly = account.get("monthly") or {}
            add_category_amounts(actuals, monthly.get(month))
            add_category_amounts(prior_actuals, monthly.get(prior_month))
    else:
        account = (summary.get("accounts") or {}).get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found in summary.")
        scope = account.get("accountName") or account_id
        monthly = account.get("monthly") or {}
        add_category_amounts(actuals, monthly.get(month))
        add_category_amounts(prior_actuals, monthly.get(prior_month))

    valid_virtual_categories = set((rules.get("virtualCategories") or {}).keys())
    invalid_budget_keys: list[str] = []
    rows: list[dict[str, Any]] = []
    for category, value in (budgets.get("monthly") or {}).items():
        if valid_virtual_categories and category not in valid_virtual_categories:
            invalid_budget_keys.append(category)
        budget = float(value or 0)
        if budget <= 0:
            continue
        actual = float(actuals.get(category, 0.0))
        prior_actual = float(prior_actuals.get(category, 0.0))
        pct_consumed = actual / budget if budget > 0 else None
        projected = actual / days_elapsed * days_in_month if days_elapsed > 0 else actual
        projected_pct = projected / budget if budget > 0 else None
        remaining = budget - actual
        status = "over" if actual > budget else "on-pace-over" if projected > budget else "under"
        rows.append(
            {
                "category": category,
                "budget": money(budget),
                "actual": money(actual),
                "remaining": money(remaining),
                "pctConsumed": metric(pct_consumed, 4),
                "projected": money(projected),
                "projectedPct": metric(projected_pct, 4),
                "priorMonth": money(prior_actual),
                "status": status,
            }
        )

    status_order = {"over": 0, "on-pace-over": 1, "under": 2}
    rows.sort(key=lambda row: (status_order.get(row["status"], 3), -(row.get("projectedPct") or 0), row["category"]))
    return {
        "scope": scope,
        "month": month,
        "daysElapsed": days_elapsed,
        "daysInMonth": days_in_month,
        "totals": {
            "budget": money(_sum(rows, "budget")),
            "actual": money(_sum(rows, "actual")),
            "projected": money(_sum(rows, "projected")),
            "priorMonth": money(_sum(rows, "priorMonth")),
        },
        "invalidBudgetKeys": invalid_budget_keys,
        "categories": rows,
    }


def find_subscriptions(months_back: int = 6, min_months: int = 3, account_id: str | None = None, all_accounts: bool = False, min_total: float = 5.0, cache_path: Path | None = None) -> list[dict[str, Any]]:
    rules = get_rules()
    account_id = account_id or rules["defaultAccountId"]
    transactions = unique_by_id(read_transactions(cache_path))
    month_start = _month_start_today()
    from_value = add_months(month_start, -(months_back - 1)).isoformat()
    to_value = add_months(month_start, 1).isoformat()
    scope = [
        row
        for row in transactions
        if float(row.get("debitAmount") or 0) > 0
        and not excluded_from_spend(row, rules)
        and str(row.get("localDate") or "") >= from_value
        and str(row.get("localDate") or "") < to_value
        and (all_accounts or row.get("accountId") == account_id)
    ]
    rows: list[dict[str, Any]] = []
    for merchant, group_rows in _group(scope, merchant_key).items():
        distinct_months = sorted({row.get("month") for row in group_rows if row.get("month")})
        if len(distinct_months) < min_months:
            continue
        total = money(_sum(group_rows, "debitAmount"))
        if total < min_total:
            continue
        avg_monthly = money(total / len(distinct_months))
        sorted_rows = sorted(group_rows, key=lambda row: str(row.get("localDate") or ""))
        amounts = [float(row.get("debitAmount") or 0) for row in group_rows]
        charges = len(group_rows)
        ratio = charges / len(distinct_months)
        cadence = "weekly?" if ratio >= 3.5 else "multiple/mo" if ratio >= 1.5 else "monthly"
        first = float(sorted_rows[0].get("debitAmount") or 0)
        last = float(sorted_rows[-1].get("debitAmount") or 0)
        last_txn = sorted_rows[-1]
        rows.append(
            {
                "merchant": merchant,
                "months": len(distinct_months),
                "charges": charges,
                "total": total,
                "avgMonthly": avg_monthly,
                "annualized": money(avg_monthly * 12),
                "avgCharge": money(_avg(amounts)),
                "minCharge": money(min(amounts)),
                "maxCharge": money(max(amounts)),
                "cadence": cadence,
                "priceJump": first > 0 and (last / first) >= 1.10,
                "lastCharge": last_txn.get("localDate"),
                "category": last_txn.get("category"),
            }
        )
    rows.sort(key=lambda row: row["annualized"], reverse=True)
    return rows


def find_anomalies(window_months: int = 6, outlier_sigma: float = 2.0, min_new_merchant_amount: float = 100.0, account_id: str | None = None, all_accounts: bool = False, cache_path: Path | None = None) -> list[dict[str, Any]]:
    rules = get_rules()
    account_id = account_id or rules["defaultAccountId"]
    transactions = unique_by_id(read_transactions(cache_path))
    month_start = _month_start_today()
    win_from = add_months(month_start, -(window_months - 1)).isoformat()
    win_to = add_months(month_start, 1).isoformat()
    recent_from = month_start.isoformat()
    scope = [
        row
        for row in transactions
        if str(row.get("localDate") or "") >= win_from
        and str(row.get("localDate") or "") < win_to
        and (all_accounts or row.get("accountId") == account_id)
    ]
    findings: list[dict[str, Any]] = []

    debit_rows = [row for row in scope if float(row.get("debitAmount") or 0) > 0]
    for merchant, group_rows in _group(debit_rows, merchant_key).items():
        if len(group_rows) < 3:
            continue
        amounts = [float(row.get("debitAmount") or 0) for row in group_rows]
        mean = sum(amounts) / len(amounts)
        threshold = mean + outlier_sigma * _stddev(amounts)
        for row in group_rows:
            amount = float(row.get("debitAmount") or 0)
            if amount > threshold and amount > mean * 1.2:
                findings.append(
                    {
                        "severity": "medium",
                        "date": row.get("localDate"),
                        "merchant": merchant,
                        "amount": money(amount),
                        "reason": f"Charge {amount:.2f} exceeds merchant baseline (mean {mean:.2f}, threshold {threshold:.2f})",
                        "action": "Verify the charge with the merchant.",
                        "id": row.get("id"),
                    }
                )

    duplicate_groups = _group(debit_rows, lambda row: (merchant_key(row), row.get("localDate"), row.get("debitAmount")))
    for group_rows in duplicate_groups.values():
        if len(group_rows) <= 1:
            continue
        row = group_rows[0]
        findings.append(
            {
                "severity": "high",
                "date": row.get("localDate"),
                "merchant": merchant_key(row),
                "amount": money(row.get("debitAmount")),
                "reason": f"Same merchant + amount {len(group_rows)} times on {row.get('localDate')}",
                "action": "Possible duplicate charge - review and request refund if confirmed.",
                "id": ",".join(str(item.get("id")) for item in group_rows),
            }
        )

    for row in debit_rows:
        if str(row.get("category") or "").startswith("Bank Fees"):
            findings.append(
                {
                    "severity": "low",
                    "date": row.get("localDate"),
                    "merchant": merchant_key(row),
                    "amount": money(row.get("debitAmount")),
                    "reason": f"Bank fee / interest charge ({row.get('category')})",
                    "action": "Avoidable - investigate whether a different account/card avoids this.",
                    "id": row.get("id"),
                }
            )

    first_seen: dict[str, str] = {}
    for row in sorted(debit_rows, key=lambda item: str(item.get("localDate") or "")):
        first_seen.setdefault(merchant_key(row), str(row.get("localDate") or ""))
    for row in debit_rows:
        if float(row.get("debitAmount") or 0) > min_new_merchant_amount and str(row.get("localDate") or "") >= recent_from:
            merchant = merchant_key(row)
            if first_seen.get(merchant, "") >= recent_from:
                findings.append(
                    {
                        "severity": "medium",
                        "date": row.get("localDate"),
                        "merchant": merchant,
                        "amount": money(row.get("debitAmount")),
                        "reason": f"First charge from {merchant} this window; amount > ${min_new_merchant_amount:g}",
                        "action": "Confirm this is an intended purchase.",
                        "id": row.get("id"),
                    }
                )

    debit_by_merchant = _group(debit_rows, merchant_key)
    credit_by_merchant = _group([row for row in scope if float(row.get("creditAmount") or 0) > 0], merchant_key)
    for merchant, debits in debit_by_merchant.items():
        for debit in debits:
            for credit in credit_by_merchant.get(merchant, []):
                if abs(float(debit.get("debitAmount") or 0) - float(credit.get("creditAmount") or 0)) < 0.01:
                    delta = abs((date.fromisoformat(str(debit.get("localDate"))) - date.fromisoformat(str(credit.get("localDate")))).days)
                    if delta <= 7:
                        findings.append(
                            {
                                "severity": "low",
                                "date": credit.get("localDate"),
                                "merchant": merchant,
                                "amount": money(debit.get("debitAmount")),
                                "reason": f"Refund of ${float(debit.get('debitAmount') or 0):g} matched a debit on {debit.get('localDate')}",
                                "action": "Refund or failed-charge pattern - typically benign.",
                                "id": f"{debit.get('id')},{credit.get('id')}",
                            }
                        )

    severity_order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda row: (severity_order.get(row.get("severity"), 3), row.get("date") or ""), reverse=False)
    findings = sorted(findings, key=lambda row: row.get("date") or "", reverse=True)
    findings.sort(key=lambda row: severity_order.get(row.get("severity"), 3))
    return findings


def _monthly_rows_for_scope(summary: dict[str, Any], account_id: str | None, all_accounts: bool) -> tuple[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    if all_accounts:
        by_month: dict[str, dict[str, Any]] = {}
        for account in (summary.get("accounts") or {}).values():
            for month, value in (account.get("monthly") or {}).items():
                row = by_month.setdefault(month, {"month": month, "spend": 0.0, "income": 0.0, "byVirtualCategory": {}})
                row["spend"] += float(value.get("spend") or 0)
                row["income"] += float(value.get("income") or 0)
                for category, amount in (value.get("byVirtualCategory") or {}).items():
                    row["byVirtualCategory"][category] = row["byVirtualCategory"].get(category, 0.0) + float(amount or 0)
        rows = [by_month[month] for month in sorted(by_month)]
        return "ALL accounts", rows

    account = (summary.get("accounts") or {}).get(account_id or "")
    if not account:
        raise ValueError(f"Account {account_id} not found in summary.")
    for month, value in (account.get("monthly") or {}).items():
        rows.append(
            {
                "month": month,
                "spend": float(value.get("spend") or 0),
                "income": float(value.get("income") or 0),
                "byVirtualCategory": dict(value.get("byVirtualCategory") or {}),
            }
        )
    return account.get("accountName") or str(account_id), sorted(rows, key=lambda row: row["month"])


def find_opportunities(lookback_months: int = 6, account_id: str | None = None, all_accounts: bool = False, summary_path: Path | None = None, cache_path: Path | None = None) -> list[dict[str, Any]]:
    rules = get_rules()
    account_id = account_id or rules["defaultAccountId"]
    summary = read_summary(summary_path)
    transactions = unique_by_id(read_transactions(cache_path))
    _, rows = _monthly_rows_for_scope(summary, account_id, all_accounts)
    rows = rows[-lookback_months:]
    if len(rows) < 2:
        return []

    opportunities: list[dict[str, Any]] = []
    current = rows[-1]
    baseline = rows[:-1]
    virtual_categories = sorted({key for row in rows for key in (row.get("byVirtualCategory") or {}).keys()})
    for category in virtual_categories:
        latest = float((current.get("byVirtualCategory") or {}).get(category) or 0)
        if not latest:
            continue
        history = [float((row.get("byVirtualCategory") or {}).get(category) or 0) for row in baseline]
        average = _avg(history)
        if not average or average <= 0:
            continue
        if latest > average * 1.25 and (latest - average) >= 25:
            delta = money(latest - average)
            opportunities.append(
                {
                    "opportunity": f"Trim {category} spend back to baseline",
                    "evidence": f"{latest:g} this month vs. {average:.2f}/mo trailing avg",
                    "estimatedMonthlyImpact": delta,
                    "confidence": "medium" if len(rows) >= 4 else "low",
                    "suggestedNextAction": f"Open this category in query.py: python .banksync-analysis/query.py -Category '{category}' -ByMerchant",
                }
            )

    dining_avg = _avg([float((row.get("byVirtualCategory") or {}).get("Dining Out") or 0) for row in rows]) or 0
    grocery_avg = _avg([float((row.get("byVirtualCategory") or {}).get("Groceries") or 0) for row in rows]) or 0
    if grocery_avg > 0 and dining_avg / grocery_avg > 0.75:
        opportunities.append(
            {
                "opportunity": "Shift some dining-out spend to groceries",
                "evidence": f"Dining out averages ${dining_avg:.2f}/mo vs. groceries ${grocery_avg:.2f}/mo (ratio {dining_avg / grocery_avg:.2f})",
                "estimatedMonthlyImpact": money(dining_avg * 0.2),
                "confidence": "low",
                "suggestedNextAction": "Target a 20% reduction in restaurant/fast-food spend for one month.",
            }
        )

    win_from = rows[0]["month"] + "-01"
    win_to = add_months(parse_yyyy_mm(rows[-1]["month"]), 1).isoformat()
    fees = [
        row
        for row in transactions
        if float(row.get("debitAmount") or 0) > 0
        and str(row.get("category") or "").startswith("Bank Fees")
        and str(row.get("localDate") or "") >= win_from
        and str(row.get("localDate") or "") < win_to
        and (all_accounts or row.get("accountId") == account_id)
    ]
    if fees:
        total = money(_sum(fees, "debitAmount"))
        opportunities.append(
            {
                "opportunity": "Eliminate recurring bank fees",
                "evidence": f"{len(fees)} fee transactions totaling ${total:g} in window",
                "estimatedMonthlyImpact": money(total / len(rows)),
                "confidence": "high",
                "suggestedNextAction": "Run Find-Anomalies.py to list each fee; switch products or call to waive.",
            }
        )

    subscriptions = find_subscriptions(
        months_back=lookback_months,
        min_months=max(2, lookback_months - 2),
        account_id=account_id,
        all_accounts=all_accounts,
        cache_path=cache_path,
    )
    for subscription in [row for row in subscriptions if row["annualized"] >= 120][:3]:
        opportunities.append(
            {
                "opportunity": f"Audit subscription: {subscription['merchant']}",
                "evidence": f"${subscription['avgMonthly']}/mo avg, ${subscription['annualized']}/yr annualized over {subscription['months']} months",
                "estimatedMonthlyImpact": money(subscription["avgMonthly"]),
                "confidence": "high" if subscription["months"] >= 4 else "medium",
                "suggestedNextAction": "Confirm you still use it; consider downgrading or canceling.",
            }
        )

    opportunities.sort(key=lambda row: row["estimatedMonthlyImpact"], reverse=True)
    return opportunities


def _month_value(month_value: dict[str, Any], mode: str, key: str) -> float:
    if mode == "Total":
        return float(month_value.get(key.lower()) or 0)
    if mode == "Virtual":
        return float((month_value.get("byVirtualCategory") or {}).get(key) or 0)
    total = 0.0
    pattern = re.compile(key, flags=re.IGNORECASE)
    for category, amount in (month_value.get("byCategory") or {}).items():
        if pattern.search(category):
            total += float(amount or 0)
    return total


def project_spend(category: str = "Spend", months_back: int = 12, months_forward: int = 6, account_id: str | None = None, all_accounts: bool = False, summary_path: Path | None = None, cache_path: Path | None = None) -> dict[str, Any]:
    rules = get_rules()
    account_id = account_id or rules["defaultAccountId"]
    summary = read_summary(summary_path)
    virtual_names = set((rules.get("virtualCategories") or {}).keys())
    mode = "Total" if category in {"Spend", "Income", "Net"} else "Virtual" if category in virtual_names else "Regex"

    rows: list[dict[str, Any]] = []
    if all_accounts:
        months = _sorted_months(month for account in (summary.get("accounts") or {}).values() for month in (account.get("monthly") or {}).keys())
        for month in months:
            value = 0.0
            for account in (summary.get("accounts") or {}).values():
                month_value = (account.get("monthly") or {}).get(month)
                if month_value:
                    value += _month_value(month_value, mode, category)
            rows.append({"month": month, "value": money(value)})
        scope = "ALL accounts"
    else:
        account = (summary.get("accounts") or {}).get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found in summary.")
        for month, month_value in (account.get("monthly") or {}).items():
            rows.append({"month": month, "value": money(_month_value(month_value, mode, category))})
        rows.sort(key=lambda row: row["month"])
        scope = account.get("accountName") or account_id

    current_month = _current_month()
    completed = [row for row in rows if row["month"] < current_month][-months_back:]
    if not completed:
        raise ValueError(f"No completed months available for {category} in scope {scope}.")
    values = [float(row["value"] or 0) for row in completed]
    avg12 = money(_avg(values))
    avg3 = money(_avg(values[-3:])) if len(values) >= 3 else avg12
    stddev = money(_stddev(values))

    trend_window = values[-6:]
    n = len(trend_window)
    if n >= 2:
        xs = list(range(n))
        sum_x = sum(xs)
        sum_y = sum(trend_window)
        sum_xy = sum(xs[index] * trend_window[index] for index in range(n))
        sum_xx = sum(x * x for x in xs)
        denom = n * sum_xx - sum_x * sum_x
        if denom:
            slope_raw = (n * sum_xy - sum_x * sum_y) / denom
            intercept = (sum_y - slope_raw * sum_x) / n
        else:
            slope_raw = 0.0
            intercept = sum_y / n
    else:
        slope_raw = 0.0
        intercept = values[-1] if values else 0.0
    slope = money(slope_raw)
    trend_next = money(intercept + slope * n)

    current_start = parse_yyyy_mm(current_month)
    forecast: list[dict[str, Any]] = []
    for index in range(months_forward):
        future_month = add_months(current_start, index + 1).strftime("%Y-%m")
        trend_y = money(intercept + slope * (n + index))
        point = money((avg3 + avg12 + trend_y) / 3.0)
        forecast.append(
            {
                "month": future_month,
                "forecast": point,
                "low": money(max(0.0, point - 2 * stddev)),
                "high": money(point + 2 * stddev),
                "trendOnly": trend_y,
            }
        )

    mtd_actual = None
    mtd_projected = None
    days_elapsed = 0
    days_in_month = 0
    cache = cache_path or REPO_ROOT / ".banksync-cache" / "normalized.jsonl"
    if cache.exists():
        transactions = read_transactions(cache)
        next_month = add_months(current_start, 1).isoformat()
        days_in_month = calendar.monthrange(date.today().year, date.today().month)[1]
        days_elapsed = date.today().day
        scope_rows = [
            row
            for row in transactions
            if str(row.get("localDate") or "") >= current_start.isoformat()
            and str(row.get("localDate") or "") < next_month
            and (all_accounts or row.get("accountId") == account_id)
        ]
        use_credit = category == "Income"
        field = "creditAmount" if use_credit else "debitAmount"
        pattern = re.compile(category, flags=re.IGNORECASE)
        matches = []
        for row in scope_rows:
            if float(row.get(field) or 0) <= 0:
                continue
            if excluded_from_spend(row, rules) and not use_credit:
                continue
            if mode == "Total" or (mode == "Regex" and pattern.search(str(row.get("category") or ""))) or (mode == "Virtual" and category in virtual_category_hits(row, rules)):
                matches.append(row)
        mtd_actual = money(_sum(matches, field))
        mtd_projected = money(mtd_actual * days_in_month / days_elapsed) if days_elapsed > 0 else None

    return {
        "category": category,
        "mode": mode,
        "scope": scope,
        "history": completed,
        "avg3": avg3,
        "avg12": avg12,
        "stddev": stddev,
        "trend": {"slope": slope, "nextMonth": trend_next},
        "forecast": forecast,
        "mtd": {
            "month": current_month,
            "actual": mtd_actual,
            "projected": mtd_projected,
            "daysElapsed": days_elapsed,
            "daysInMonth": days_in_month,
        },
    }


def import_dump(files: list[Path], fetch_label: str | None = None, cache_root: Path | None = None) -> dict[str, Any]:
    root = cache_root or REPO_ROOT / ".banksync-cache"
    raw_root = root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    normalized_path = root / "normalized.jsonl"
    manifest_path = root / "manifest.json"
    fetch_label = fetch_label or date.today().isoformat()

    rules = get_rules()
    aliases = get_merchant_alias_map(rules)
    existing = {row.get("id"): row for row in read_transactions(normalized_path)} if normalized_path.exists() else {}
    manifest = load_json(manifest_path) if manifest_path.exists() else {"accounts": {}, "fetches": []}
    accounts = dict(manifest.get("accounts") or {})
    fetches = list(manifest.get("fetches") or [])

    total_in = 0
    new_count = 0
    updated_count = 0
    for file_path in files:
        if not file_path.exists():
            continue
        payload = load_json(file_path)
        transactions = payload.get("transactions") or []
        if not transactions:
            continue
        total_in += len(transactions)

        for account_id, rows in _group(transactions, lambda row: row.get("accountId") or "").items():
            destination = raw_root / account_id
            destination.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(file_path, destination / f"{stamp}_{file_path.stem}.json")
            first = rows[0]
            local_dates = sorted({str(row.get("date") or "")[:10] for row in rows})
            if account_id not in accounts:
                accounts[account_id] = {
                    "accountName": first.get("accountName"),
                    "bankId": first.get("bankId"),
                    "firstSeen": local_dates[0],
                    "lastSeen": local_dates[-1],
                }
            else:
                accounts[account_id]["firstSeen"] = min(accounts[account_id].get("firstSeen") or local_dates[0], local_dates[0])
                accounts[account_id]["lastSeen"] = max(accounts[account_id].get("lastSeen") or local_dates[-1], local_dates[-1])

        for transaction in transactions:
            date_str = str(transaction.get("date") or "")
            local_date = date_str[:10]
            transaction_id = transaction.get("id")
            normalized = OrderedDict(
                [
                    ("id", transaction_id),
                    ("date", transaction.get("date")),
                    ("localDate", local_date),
                    ("month", local_date[:7]),
                    ("year", local_date[:4]),
                    ("description", transaction.get("description")),
                    ("merchantName", transaction.get("merchantName")),
                    ("normalizedMerchant", normalize_merchant(transaction.get("merchantName"), transaction.get("description"), aliases)),
                    ("category", transaction.get("category")),
                    ("amount", transaction.get("amount")),
                    ("debitAmount", transaction.get("debitAmount")),
                    ("creditAmount", transaction.get("creditAmount")),
                    ("direction", "IN" if float(transaction.get("creditAmount") or 0) > 0 else "OUT"),
                    ("accountId", transaction.get("accountId")),
                    ("accountName", transaction.get("accountName")),
                    ("bankId", transaction.get("bankId")),
                    ("pending", transaction.get("pending")),
                    ("isTransfer", bool(re.search(r"Transfer In|Transfer Out", str(transaction.get("category") or ""), flags=re.IGNORECASE))),
                    ("isCcPayment", bool(re.search(r"Credit Card Payment", str(transaction.get("category") or ""), flags=re.IGNORECASE))),
                ]
            )
            if transaction_id in existing:
                updated_count += 1
            else:
                new_count += 1
            existing[transaction_id] = normalized

        fetches.append({"file": str(file_path.resolve()), "fetchLabel": fetch_label, "importedAt": datetime.now().astimezone().isoformat(), "txnCount": len(transactions)})

    sorted_rows = sorted(existing.values(), key=lambda row: (str(row.get("localDate") or ""), str(row.get("id") or "")), reverse=True)
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    with normalized_path.open("w", encoding="utf-8") as handle:
        for row in sorted_rows:
            handle.write(compact_json(row) + "\n")
    write_json(manifest_path, {"accounts": accounts, "fetches": fetches})
    return {"totalIn": total_in, "new": new_count, "updated": updated_count, "cacheTotal": len(existing), "cacheRoot": str(root)}


def build_monthly_report(month: str | None = None, account_id: str | None = None, all_accounts: bool = False, out_dir: Path | None = None, summary_path: Path | None = None, cache_path: Path | None = None) -> Path:
    rules = get_rules()
    account_id = account_id or rules["defaultAccountId"]
    summary = read_summary(summary_path)
    scope = _scope_label(summary, account_id, all_accounts)

    def month_values(selected_month: str) -> dict[str, Any] | None:
        if all_accounts:
            aggregate = {"spend": 0.0, "income": 0.0, "net": 0.0, "txnCount": 0, "spendTxnCount": 0, "byCategory": {}, "byVirtualCategory": {}, "topMerchants": {}}
            for account in (summary.get("accounts") or {}).values():
                value = (account.get("monthly") or {}).get(selected_month)
                if not value:
                    continue
                for key in ["spend", "income", "net"]:
                    aggregate[key] += float(value.get(key) or 0)
                aggregate["txnCount"] += int(value.get("txnCount") or 0)
                aggregate["spendTxnCount"] += int(value.get("spendTxnCount") or 0)
                for key, amount in (value.get("byCategory") or {}).items():
                    aggregate["byCategory"][key] = aggregate["byCategory"].get(key, 0.0) + float(amount or 0)
                for key, amount in (value.get("byVirtualCategory") or {}).items():
                    aggregate["byVirtualCategory"][key] = aggregate["byVirtualCategory"].get(key, 0.0) + float(amount or 0)
                for merchant in value.get("topMerchants") or []:
                    row = aggregate["topMerchants"].setdefault(merchant.get("merchant"), {"total": 0.0, "count": 0})
                    row["total"] += float(merchant.get("total") or 0)
                    row["count"] += int(merchant.get("count") or 0)
            return aggregate

        value = _account_month(summary, account_id or "", selected_month)
        if not value:
            return None
        return {
            "spend": float(value.get("spend") or 0),
            "income": float(value.get("income") or 0),
            "net": float(value.get("net") or 0),
            "txnCount": int(value.get("txnCount") or 0),
            "spendTxnCount": int(value.get("spendTxnCount") or 0),
            "byCategory": dict(value.get("byCategory") or {}),
            "byVirtualCategory": dict(value.get("byVirtualCategory") or {}),
            "topMerchants": {item.get("merchant"): {"total": float(item.get("total") or 0), "count": int(item.get("count") or 0)} for item in value.get("topMerchants") or []},
        }

    if all_accounts:
        months = _sorted_months(month for account in (summary.get("accounts") or {}).values() for month in (account.get("monthly") or {}).keys())
    else:
        account = (summary.get("accounts") or {}).get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found in summary.")
        months = _sorted_months((account.get("monthly") or {}).keys())

    completed_months = [item for item in months if item < _current_month()]
    if not month:
        if not completed_months:
            raise ValueError("No completed months available. Wait for next month, or pass -Month explicitly.")
        month = completed_months[-1]
    if month not in months:
        raise ValueError(f"Month {month} not found in summary.")
    current = month_values(month)
    if not current:
        raise ValueError(f"No data for {month}.")

    prior_months = [item for item in completed_months if item < month][-3:]
    prior_data = [value for value in (month_values(item) for item in prior_months) if value]

    def average_map(field: str) -> dict[str, float]:
        if not prior_data:
            return {}
        sums: dict[str, float] = {}
        for row in prior_data:
            for key, amount in row[field].items():
                sums[key] = sums.get(key, 0.0) + float(amount or 0)
        return {key: money(value / len(prior_data)) for key, value in sums.items()}

    prior_category_avg = average_map("byCategory")
    prior_vc_avg = average_map("byVirtualCategory")
    all_categories = set(current["byCategory"].keys()) | set(prior_category_avg.keys())
    category_deltas = []
    for key in all_categories:
        now = float(current["byCategory"].get(key) or 0)
        base = float(prior_category_avg.get(key) or 0)
        if now == 0 and base == 0:
            continue
        category_deltas.append({"category": key, "current": money(now), "priorAvg": money(base), "delta": money(now - base), "pct": metric(((now - base) / base) * 100, 1) if base > 0 else None})
    category_deltas.sort(key=lambda row: abs(row["delta"]), reverse=True)
    top_merchants = sorted(({"merchant": key, "total": money(value["total"]), "count": value["count"]} for key, value in current["topMerchants"].items()), key=lambda row: row["total"], reverse=True)[:10]

    subscriptions = find_subscriptions(6, 3, account_id, all_accounts, cache_path=cache_path)
    anomalies = find_anomalies(3, account_id=account_id, all_accounts=all_accounts, cache_path=cache_path)
    projection = project_spend("Spend", 12, 3, account_id, all_accounts, summary_path, cache_path)
    opportunities = find_opportunities(6, account_id, all_accounts, summary_path, cache_path)

    lines: list[str] = []
    lines.extend([f"# Monthly Report - {month}", "", f"_Scope: **{scope}** | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_", ""])
    savings_rate = f"{current['net'] / current['income']:.1%}" if current["income"] > 0 else "n/a"
    lines.extend(["## Cashflow", "", "| Income | Spend | Net | Savings Rate | Txn Count |", "|---:|---:|---:|---:|---:|", f"| ${current['income']:.2f} | ${current['spend']:.2f} | ${current['net']:.2f} | {savings_rate} | {current['txnCount']} |", ""])
    if prior_data:
        lines.extend([f"_Trailing {len(prior_data)}-month avg - income ${money(_avg([row['income'] for row in prior_data])):.2f}, spend ${money(_avg([row['spend'] for row in prior_data])):.2f}, net ${money(_avg([row['net'] for row in prior_data])):.2f}._", ""])

    lines.extend(["## Top Category Changes vs. Prior Avg", ""])
    if not category_deltas:
        lines.append("_No prior months available for comparison._")
    else:
        lines.extend(["| Category | This Month | Prior Avg | Delta | % |", "|---|---:|---:|---:|---:|"])
        for row in category_deltas[:10]:
            pct = "n/a" if row["pct"] is None else f"{row['pct']:.1f}%"
            lines.append(f"| {row['category']} | ${row['current']:.2f} | ${row['priorAvg']:.2f} | ${row['delta']:.2f} | {pct} |")
    lines.append("")

    lines.extend(["## Virtual Categories", ""])
    if not current["byVirtualCategory"]:
        lines.append("_No virtual categories defined or matched._")
    else:
        lines.extend(["| Category | Spend | Prior Avg |", "|---|---:|---:|"])
        for key, amount in sorted(current["byVirtualCategory"].items(), key=lambda item: float(item[1]), reverse=True):
            lines.append(f"| {key} | ${float(amount):.2f} | ${float(prior_vc_avg.get(key) or 0):.2f} |")
    lines.append("")

    lines.extend(["## Top Merchants", ""])
    if not top_merchants:
        lines.append("_No merchant data._")
    else:
        lines.extend(["| Merchant | Total | Count |", "|---|---:|---:|"])
        for row in top_merchants:
            lines.append(f"| {row['merchant']} | ${row['total']:.2f} | {row['count']} |")
    lines.append("")

    lines.extend(["## Subscription Audit", ""])
    if not subscriptions:
        lines.append("_No recurring merchants detected in the trailing window._")
    else:
        lines.extend(["| Merchant | Months | Avg/mo | Annualized | Price Jump |", "|---|---:|---:|---:|:---:|"])
        for row in subscriptions[:15]:
            lines.append(f"| {row['merchant']} | {row['months']} | ${row['avgMonthly']:.2f} | ${row['annualized']:.2f} | {'yes' if row['priceJump'] else ''} |")
    lines.append("")

    lines.extend(["## Anomalies", ""])
    if not anomalies:
        lines.append("_No anomalies detected._")
    else:
        lines.extend(["| Sev | Date | Merchant | Amount | Reason |", "|---|---|---|---:|---|"])
        for row in anomalies[:20]:
            reason = str(row["reason"]).replace("|", "\\|")
            lines.append(f"| {row['severity']} | {row['date']} | {row['merchant']} | ${float(row['amount']):.2f} | {reason} |")
    lines.append("")

    lines.extend(["## Projection (Spend, next 3 months)", ""])
    if not projection.get("forecast"):
        lines.append("_Not enough history to project._")
    else:
        lines.append(f"Averages - 3-mo **${projection['avg3']:.2f}**, 12-mo **${projection['avg12']:.2f}**, stddev **${projection['stddev']:.2f}**. Trend slope **${projection['trend']['slope']:.2f}/mo**.")
        if projection["mtd"]["daysElapsed"] > 0:
            mtd = projection["mtd"]
            lines.append(f"MTD {mtd['month']}: **${float(mtd['actual'] or 0):.2f}** ({mtd['daysElapsed']}/{mtd['daysInMonth']} days), projected end-of-month **${float(mtd['projected'] or 0):.2f}**.")
        lines.extend(["", "| Month | Forecast | Low (-2s) | High (+2s) |", "|---|---:|---:|---:|"])
        for row in projection["forecast"]:
            lines.append(f"| {row['month']} | ${row['forecast']:.2f} | ${row['low']:.2f} | ${row['high']:.2f} |")
    lines.append("")

    lines.extend(["## Suggested Actions", ""])
    if not opportunities:
        lines.append("_No notable opportunities flagged._")
    else:
        for row in opportunities[:6]:
            lines.append(f"- **${float(row['estimatedMonthlyImpact']):.2f}/mo - {row['confidence']}** - {row['opportunity']}")
            lines.append(f"  - Evidence: {row['evidence']}")
            lines.append(f"  - Next: {row['suggestedNextAction']}")
    lines.append("")

    last_months = [item for item in completed_months if item <= month][-6:]
    if len(last_months) >= 2:
        spend_series = [month_values(item)["spend"] for item in last_months]
        income_series = [month_values(item)["income"] for item in last_months]
        lines.extend(["## Trend (last 6 months)", "", "```mermaid", "xychart-beta", f"  title \"Spend vs Income - {scope}\"", "  x-axis [" + ", ".join(f'\"{item}\"' for item in last_months) + "]", "  y-axis \"USD\"", "  bar    [" + ", ".join(f"{float(item):.2f}" for item in spend_series) + "]", "  line   [" + ", ".join(f"{float(item):.2f}" for item in income_series) + "]", "```", ""])

    if current["byVirtualCategory"]:
        lines.extend(["## Category Mix", "", "```mermaid", "pie showData", f"  title \"{month} - virtual category spend\""])
        for key, amount in sorted(current["byVirtualCategory"].items(), key=lambda item: float(item[1]), reverse=True)[:8]:
            if float(amount) > 0:
                lines.append(f"  \"{key}\" : {float(amount):.2f}")
        lines.extend(["```", ""])

    destination = out_dir or ANALYSIS_ROOT / "reports"
    destination.mkdir(parents=True, exist_ok=True)
    out_file = destination / f"{month}.md"
    out_file.write_text("\r\n".join(lines), encoding="utf-8")
    return out_file


def analyze_raw(files: list[Path]) -> dict[str, Any]:
    transactions: list[dict[str, Any]] = []
    for file_path in files:
        payload = load_json(file_path)
        transactions.extend(payload.get("transactions") or [])
    transactions = unique_by_id(transactions)
    debit_rows = [row for row in transactions if float(row.get("debitAmount") or 0) > 0]
    by_category = [
        {"category": key, "count": len(rows), "total": money(_sum(rows, "debitAmount"))}
        for key, rows in _group(debit_rows, lambda row: row.get("category") or "").items()
    ]
    by_category.sort(key=lambda row: row["total"], reverse=True)
    by_merchant = [
        {"merchant": key, "count": len(rows), "total": money(_sum(rows, "debitAmount")), "avg": money(_avg([float(row.get("debitAmount") or 0) for row in rows]))}
        for key, rows in _group([row for row in debit_rows if row.get("merchantName")], lambda row: row.get("merchantName")).items()
    ]
    by_merchant.sort(key=lambda row: row["total"], reverse=True)
    return {
        "txnCount": len(transactions),
        "range": {
            "from": min((str(row.get("date") or "") for row in transactions), default=None),
            "to": max((str(row.get("date") or "") for row in transactions), default=None),
        },
        "totalDebits": money(_sum(transactions, "debitAmount")),
        "totalCredits": money(_sum(transactions, "creditAmount")),
        "net": money(_sum(transactions, "creditAmount") - _sum(transactions, "debitAmount")),
        "topCategories": by_category[:20],
        "topMerchants": by_merchant[:30],
    }

import math
import re
import shutil
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .core import (
    ANALYSIS_ROOT,
    DEFAULT_ACCOUNT_ID,
    REPO_ROOT,
    add_months,
    compact_json,
    current_month,
    excluded_from_spend,
    get_merchant_alias_map,
    get_rules,
    load_json,
    merchant_key,
    metric,
    money,
    normalize_merchant,
    parse_yyyy_mm,
    read_summary,
    read_transactions,
    unique_by_id,
    virtual_category_hits,
    write_json,
)


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def sample_stddev(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = average(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def days_in_month(value: date) -> int:
    next_month = add_months(value, 1)
    return (next_month - value).days


def month_scope(summary: dict[str, Any], account_id: str, all_accounts: bool) -> tuple[str, list[dict[str, Any]]]:
    rows_by_month: dict[str, dict[str, Any]] = {}
    accounts = summary.get("accounts") or {}
    if all_accounts:
        for account in accounts.values():
            for month, value in (account.get("monthly") or {}).items():
                row = rows_by_month.setdefault(
                    month,
                    {"month": month, "spend": 0.0, "income": 0.0, "net": 0.0, "byVirtualCategory": {}},
                )
                row["spend"] += float(value.get("spend") or 0)
                row["income"] += float(value.get("income") or 0)
                row["net"] = row["income"] - row["spend"]
                for key, amount in (value.get("byVirtualCategory") or {}).items():
                    row["byVirtualCategory"][key] = row["byVirtualCategory"].get(key, 0.0) + float(amount or 0)
        return "ALL accounts", [rows_by_month[key] for key in sorted(rows_by_month)]

    account = accounts.get(account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found in summary.")
    rows = []
    for month, value in (account.get("monthly") or {}).items():
        rows.append(
            {
                "month": month,
                "spend": float(value.get("spend") or 0),
                "income": float(value.get("income") or 0),
                "net": float(value.get("net") or 0),
                "byVirtualCategory": dict(value.get("byVirtualCategory") or {}),
            }
        )
    return account.get("accountName") or account_id, sorted(rows, key=lambda item: item["month"])


def month_values_for_scope(summary: dict[str, Any], account_id: str, all_accounts: bool, month: str) -> dict[str, Any] | None:
    accounts = summary.get("accounts") or {}
    if all_accounts:
        aggregate = {
            "spend": 0.0,
            "income": 0.0,
            "net": 0.0,
            "txnCount": 0,
            "spendTxnCount": 0,
            "byCategory": {},
            "byVirtualCategory": {},
            "topMerchants": {},
        }
        for account in accounts.values():
            value = (account.get("monthly") or {}).get(month)
            if not value:
                continue
            aggregate["spend"] += float(value.get("spend") or 0)
            aggregate["income"] += float(value.get("income") or 0)
            aggregate["net"] += float(value.get("net") or 0)
            aggregate["txnCount"] += int(value.get("txnCount") or 0)
            aggregate["spendTxnCount"] += int(value.get("spendTxnCount") or 0)
            for key, amount in (value.get("byCategory") or {}).items():
                aggregate["byCategory"][key] = aggregate["byCategory"].get(key, 0.0) + float(amount or 0)
            for key, amount in (value.get("byVirtualCategory") or {}).items():
                aggregate["byVirtualCategory"][key] = aggregate["byVirtualCategory"].get(key, 0.0) + float(amount or 0)
            for merchant in value.get("topMerchants") or []:
                item = aggregate["topMerchants"].setdefault(merchant.get("merchant"), {"total": 0.0, "count": 0})
                item["total"] += float(merchant.get("total") or 0)
                item["count"] += int(merchant.get("count") or 0)
        return aggregate

    account = accounts.get(account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found in summary.")
    value = (account.get("monthly") or {}).get(month)
    if not value:
        return None
    return {
        "spend": float(value.get("spend") or 0),
        "income": float(value.get("income") or 0),
        "net": float(value.get("net") or 0),
        "txnCount": int(value.get("txnCount") or 0),
        "spendTxnCount": int(value.get("spendTxnCount") or 0),
        "byCategory": dict(value.get("byCategory") or {}),
        "byVirtualCategory": dict(value.get("byVirtualCategory") or {}),
        "topMerchants": {
            item.get("merchant"): {"total": float(item.get("total") or 0), "count": int(item.get("count") or 0)}
            for item in value.get("topMerchants") or []
        },
    }


def import_dump(files: list[str], fetch_label: str, cache_root: Path | None = None) -> dict[str, Any]:
    root = cache_root or REPO_ROOT / ".banksync-cache"
    raw_root = root / "raw"
    root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    normalized_path = root / "normalized.jsonl"
    manifest_path = root / "manifest.json"

    rules = get_rules()
    aliases = get_merchant_alias_map(rules)
    existing: dict[str, dict[str, Any]] = {}
    if normalized_path.exists():
        for transaction in read_transactions(normalized_path):
            existing[str(transaction.get("id"))] = transaction

    manifest = load_json(manifest_path) if manifest_path.exists() else {"accounts": {}, "fetches": []}
    accounts = dict(manifest.get("accounts") or {})
    fetches = list(manifest.get("fetches") or [])
    total_in = new_count = updated_count = 0

    for file_name in files:
        path = Path(file_name)
        if not path.exists():
            continue
        payload = load_json(path)
        transactions = payload.get("transactions") or []
        if not transactions:
            continue
        total_in += len(transactions)
        groups: dict[str, list[dict[str, Any]]] = {}
        for transaction in transactions:
            groups.setdefault(str(transaction.get("accountId") or ""), []).append(transaction)

        for account_id, rows in groups.items():
            destination = raw_root / account_id
            destination.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(path, destination / f"{stamp}_{path.stem}.json")
            local_dates = sorted({str(row.get("date") or "")[:10] for row in rows})
            first = rows[0]
            if account_id not in accounts:
                accounts[account_id] = {
                    "accountName": first.get("accountName"),
                    "bankId": first.get("bankId"),
                    "firstSeen": local_dates[0],
                    "lastSeen": local_dates[-1],
                }
            else:
                account = accounts[account_id]
                account["firstSeen"] = min(account.get("firstSeen") or local_dates[0], local_dates[0])
                account["lastSeen"] = max(account.get("lastSeen") or local_dates[-1], local_dates[-1])

        for transaction in transactions:
            date_text = str(transaction.get("date") or "")
            local_date = date_text[:10]
            normalized = OrderedDict(
                [
                    ("id", transaction.get("id")),
                    ("date", transaction.get("date")),
                    ("localDate", local_date),
                    ("month", local_date[:7]),
                    ("year", local_date[:4]),
                    ("description", transaction.get("description")),
                    ("merchantName", transaction.get("merchantName")),
                    ("normalizedMerchant", normalize_merchant(transaction.get("merchantName"), transaction.get("description"), aliases)),
                    ("category", transaction.get("category")),
                    ("amount", transaction.get("amount")),
                    ("debitAmount", transaction.get("debitAmount")),
                    ("creditAmount", transaction.get("creditAmount")),
                    ("direction", "IN" if float(transaction.get("creditAmount") or 0) > 0 else "OUT"),
                    ("accountId", transaction.get("accountId")),
                    ("accountName", transaction.get("accountName")),
                    ("bankId", transaction.get("bankId")),
                    ("pending", transaction.get("pending")),
                    ("isTransfer", bool(re.search(r"Transfer In|Transfer Out", str(transaction.get("category") or ""), re.IGNORECASE))),
                    ("isCcPayment", bool(re.search(r"Credit Card Payment", str(transaction.get("category") or ""), re.IGNORECASE))),
                ]
            )
            transaction_id = str(transaction.get("id"))
            if transaction_id in existing:
                updated_count += 1
            else:
                new_count += 1
            existing[transaction_id] = dict(normalized)

        fetches.append(
            {
                "file": str(path.resolve()),
                "fetchLabel": fetch_label,
                "importedAt": datetime.now().astimezone().isoformat(),
                "txnCount": len(transactions),
            }
        )

    sorted_transactions = sorted(existing.values(), key=lambda item: (str(item.get("localDate") or ""), str(item.get("id") or "")), reverse=True)
    with normalized_path.open("w", encoding="utf-8") as handle:
        for transaction in sorted_transactions:
            handle.write(compact_json(transaction) + "\n")
    write_json(manifest_path, {"accounts": accounts, "fetches": fetches})
    return {"input": total_in, "new": new_count, "updated": updated_count, "total": len(existing), "cacheRoot": str(root)}


def build_summary(cache_root: Path | None = None, top_merchants: int = 10) -> dict[str, Any]:
    root = cache_root or REPO_ROOT / ".banksync-cache"
    cache_path = root / "normalized.jsonl"
    rules = get_rules()
    transactions = unique_by_id(read_transactions(cache_path))
    default_account_id = rules.get("defaultAccountId") or DEFAULT_ACCOUNT_ID

    accounts: OrderedDict[str, Any] = OrderedDict()
    account_groups: dict[str, list[dict[str, Any]]] = {}
    for transaction in transactions:
        account_groups.setdefault(str(transaction.get("accountId") or ""), []).append(transaction)

    for account_id in sorted(account_groups):
        account_transactions = account_groups[account_id]
        first = account_transactions[0]
        monthly: OrderedDict[str, Any] = OrderedDict()
        month_groups: dict[str, list[dict[str, Any]]] = {}
        for transaction in account_transactions:
            month_groups.setdefault(str(transaction.get("month") or ""), []).append(transaction)

        for month in sorted(month_groups):
            rows = month_groups[month]
            spend_txns = [row for row in rows if float(row.get("debitAmount") or 0) > 0 and not excluded_from_spend(row, rules)]
            income_txns = [row for row in rows if float(row.get("creditAmount") or 0) > 0 and not row.get("isTransfer")]
            spend = money(sum(float(row.get("debitAmount") or 0) for row in spend_txns))
            income = money(sum(float(row.get("creditAmount") or 0) for row in income_txns))
            net = money(income - spend)

            category_totals: dict[str, float] = {}
            for transaction in spend_txns:
                key = transaction.get("category") or ""
                category_totals[key] = category_totals.get(key, 0.0) + float(transaction.get("debitAmount") or 0)
            by_category = OrderedDict((key, money(value)) for key, value in sorted(category_totals.items(), key=lambda item: item[1], reverse=True))

            virtual_totals: dict[str, float] = {}
            for transaction in spend_txns:
                for hit in virtual_category_hits(transaction, rules):
                    virtual_totals[hit] = virtual_totals.get(hit, 0.0) + float(transaction.get("debitAmount") or 0)
            by_virtual = OrderedDict((key, money(value)) for key, value in sorted(virtual_totals.items(), key=lambda item: item[1], reverse=True))

            merchant_totals: dict[str, dict[str, float | int]] = {}
            for transaction in spend_txns:
                item = merchant_totals.setdefault(merchant_key(transaction), {"total": 0.0, "count": 0})
                item["total"] = float(item["total"]) + float(transaction.get("debitAmount") or 0)
                item["count"] = int(item["count"]) + 1
            top = [
                {"merchant": key, "total": money(value["total"]), "count": value["count"]}
                for key, value in sorted(merchant_totals.items(), key=lambda item: float(item[1]["total"]), reverse=True)[:top_merchants]
            ]

            monthly[month] = {
                "spend": spend,
                "income": income,
                "net": net,
                "savingsRate": metric(net / income) if income > 0 else None,
                "txnCount": len(rows),
                "spendTxnCount": len(spend_txns),
                "byCategory": by_category,
                "byVirtualCategory": by_virtual,
                "topMerchants": top,
            }

        local_dates = sorted({str(transaction.get("localDate") or "") for transaction in account_transactions})
        accounts[account_id] = {
            "accountId": account_id,
            "accountName": first.get("accountName"),
            "bankId": first.get("bankId"),
            "txnCount": len(account_transactions),
            "firstSeen": local_dates[0],
            "lastSeen": local_dates[-1],
            "monthly": monthly,
        }

    all_dates = sorted({str(transaction.get("localDate") or "") for transaction in transactions})
    default_account = next((transaction for transaction in transactions if transaction.get("accountId") == default_account_id), None)
    summary = {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "source": str(cache_path.resolve()),
        "txnCount": len(transactions),
        "range": {"from": all_dates[0], "to": all_dates[-1]},
        "scopeDefaults": {
            "accountId": default_account_id,
            "accountName": (default_account or {}).get("accountName") or rules.get("defaultAccountName"),
        },
        "rules": {
            "excludeFromHouseholdSpend": rules.get("excludeFromHouseholdSpend") or [],
            "virtualCategories": list((rules.get("virtualCategories") or {}).keys()),
        },
        "accounts": accounts,
    }
    write_json(root / "summary.json", summary)
    return summary


def cashflow(months: int, account_id: str | None = None, all_accounts: bool = False, summary_path: Path | None = None) -> dict[str, Any]:
    rules = get_rules()
    account_id = account_id or rules.get("defaultAccountId") or DEFAULT_ACCOUNT_ID
    summary = read_summary(summary_path)
    scope, rows = month_scope(summary, account_id, all_accounts)
    rows = rows[-months:]
    for index, row in enumerate(rows):
        row["spend"] = money(row["spend"])
        row["income"] = money(row["income"])
        row["net"] = money(row["income"] - row["spend"])
        row["savingsRate"] = metric(row["net"] / row["income"]) if row["income"] > 0 else None
        window = rows[max(0, index - 2) : index + 1]
        row["spend3mAvg"] = money(average([float(item["spend"]) for item in window]))
        row["income3mAvg"] = money(average([float(item["income"]) for item in window]))
        row["net3mAvg"] = money(average([float(item["net"]) for item in window]))
    latest_year = rows[-1]["month"][:4] if rows else None
    ytd_rows = [row for row in rows if latest_year and row["month"].startswith(latest_year)]
    ytd = None
    if ytd_rows:
        ytd = {
            "year": latest_year,
            "spend": money(sum(row["spend"] for row in ytd_rows)),
            "income": money(sum(row["income"] for row in ytd_rows)),
            "net": money(sum(row["net"] for row in ytd_rows)),
        }
    return {"scope": scope, "months": rows, "ytd": ytd}


def budget_status(month: str, account_id: str | None = None, all_accounts: bool = False, budget_path: Path | None = None, summary_path: Path | None = None) -> dict[str, Any]:
    if not re.match(r"^\d{4}-\d{2}$", month):
        raise ValueError(f"Month must be yyyy-MM, got '{month}'.")
    rules = get_rules()
    account_id = account_id or rules.get("defaultAccountId") or DEFAULT_ACCOUNT_ID
    budgets = load_json(budget_path or ANALYSIS_ROOT / "budgets.json")
    summary = read_summary(summary_path)
    monthly_budgets = budgets.get("monthly") or {}
    month_start = parse_yyyy_mm(month)
    today = date.today()
    month_days = days_in_month(month_start)
    current_start = date(today.year, today.month, 1)
    if today.strftime("%Y-%m") == month:
        days_elapsed = min(month_days, max(1, today.day))
    elif month_start < current_start:
        days_elapsed = month_days
    else:
        days_elapsed = 1

    def add_category_amounts(target: dict[str, float], month_value: dict[str, Any] | None) -> None:
        if not month_value:
            return
        for key, amount in (month_value.get("byVirtualCategory") or {}).items():
            target[key] = target.get(key, 0.0) + float(amount or 0)

    actuals: dict[str, float] = {}
    prior_actuals: dict[str, float] = {}
    prior_month = add_months(month_start, -1).strftime("%Y-%m")
    accounts = summary.get("accounts") or {}
    if all_accounts:
        scope = "ALL accounts"
        for account in accounts.values():
            add_category_amounts(actuals, (account.get("monthly") or {}).get(month))
            add_category_amounts(prior_actuals, (account.get("monthly") or {}).get(prior_month))
    else:
        account = accounts.get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found in summary.")
        scope = account.get("accountName") or account_id
        add_category_amounts(actuals, (account.get("monthly") or {}).get(month))
        add_category_amounts(prior_actuals, (account.get("monthly") or {}).get(prior_month))

    valid = set((rules.get("virtualCategories") or {}).keys())
    rows = []
    invalid_keys = []
    for category, budget_value in monthly_budgets.items():
        if valid and category not in valid:
            invalid_keys.append(category)
        budget = float(budget_value or 0)
        if budget <= 0:
            continue
        actual = float(actuals.get(category, 0.0))
        projected = actual / days_elapsed * month_days if days_elapsed > 0 else actual
        status = "over" if actual > budget else "on-pace-over" if projected > budget else "under"
        rows.append(
            {
                "category": category,
                "budget": money(budget),
                "actual": money(actual),
                "remaining": money(budget - actual),
                "pctConsumed": metric(actual / budget) if budget > 0 else None,
                "projected": money(projected),
                "projectedPct": metric(projected / budget) if budget > 0 else None,
                "priorMonth": money(prior_actuals.get(category, 0.0)),
                "status": status,
            }
        )
    status_order = {"over": 0, "on-pace-over": 1, "under": 2}
    rows.sort(key=lambda row: (status_order.get(row["status"], 3), -(row["projectedPct"] or 0), row["category"]))
    return {
        "scope": scope,
        "month": month,
        "daysElapsed": days_elapsed,
        "daysInMonth": month_days,
        "totals": {
            "budget": money(sum(row["budget"] for row in rows)),
            "actual": money(sum(row["actual"] for row in rows)),
            "projected": money(sum(row["projected"] for row in rows)),
            "priorMonth": money(sum(row["priorMonth"] for row in rows)),
        },
        "invalidBudgetKeys": invalid_keys,
        "categories": rows,
    }


def subscriptions(months_back: int = 6, min_months: int = 3, account_id: str | None = None, all_accounts: bool = False, min_total: float = 5.0, cache_path: Path | None = None) -> list[dict[str, Any]]:
    rules = get_rules()
    account_id = account_id or rules.get("defaultAccountId") or DEFAULT_ACCOUNT_ID
    transactions = unique_by_id(read_transactions(cache_path))
    window_from, window_to = _trailing_window(months_back)
    scope = [
        transaction
        for transaction in transactions
        if float(transaction.get("debitAmount") or 0) > 0
        and not excluded_from_spend(transaction, rules)
        and str(transaction.get("localDate") or "") >= window_from
        and str(transaction.get("localDate") or "") < window_to
        and (all_accounts or transaction.get("accountId") == account_id)
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for transaction in scope:
        groups.setdefault(merchant_key(transaction), []).append(transaction)
    rows = []
    for merchant, group in groups.items():
        months = sorted({str(item.get("month") or "") for item in group})
        if len(months) < min_months:
            continue
        total = money(sum(float(item.get("debitAmount") or 0) for item in group))
        if total < min_total:
            continue
        amounts = [float(item.get("debitAmount") or 0) for item in group]
        last_transaction = sorted(group, key=lambda item: str(item.get("localDate") or ""), reverse=True)[0]
        sorted_group = sorted(group, key=lambda item: str(item.get("localDate") or ""))
        first_amount = float(sorted_group[0].get("debitAmount") or 0)
        last_amount = float(sorted_group[-1].get("debitAmount") or 0)
        ratio = len(group) / len(months)
        cadence = "weekly?" if ratio >= 3.5 else "multiple/mo" if ratio >= 1.5 else "monthly"
        avg_monthly = money(total / len(months))
        rows.append(
            {
                "merchant": merchant,
                "months": len(months),
                "charges": len(group),
                "total": total,
                "avgMonthly": avg_monthly,
                "annualized": money(avg_monthly * 12),
                "avgCharge": money(average(amounts)),
                "minCharge": money(min(amounts)),
                "maxCharge": money(max(amounts)),
                "cadence": cadence,
                "priceJump": bool(first_amount > 0 and last_amount / first_amount >= 1.10),
                "lastCharge": last_transaction.get("localDate"),
                "category": last_transaction.get("category"),
            }
        )
    return sorted(rows, key=lambda row: row["annualized"], reverse=True)


def anomalies(window_months: int = 6, outlier_sigma: float = 2.0, min_new_merchant_amount: float = 100.0, account_id: str | None = None, all_accounts: bool = False, cache_path: Path | None = None) -> list[dict[str, Any]]:
    rules = get_rules()
    account_id = account_id or rules.get("defaultAccountId") or DEFAULT_ACCOUNT_ID
    transactions = unique_by_id(read_transactions(cache_path))
    window_from, window_to = _trailing_window(window_months)
    recent_from = date.today().replace(day=1).isoformat()
    scope = [
        transaction
        for transaction in transactions
        if str(transaction.get("localDate") or "") >= window_from
        and str(transaction.get("localDate") or "") < window_to
        and (all_accounts or transaction.get("accountId") == account_id)
    ]
    findings: list[dict[str, Any]] = []
    debit_groups: dict[str, list[dict[str, Any]]] = {}
    for transaction in scope:
        if float(transaction.get("debitAmount") or 0) > 0:
            debit_groups.setdefault(merchant_key(transaction), []).append(transaction)

    for merchant, group in debit_groups.items():
        if len(group) >= 3:
            amounts = [float(item.get("debitAmount") or 0) for item in group]
            mean = average(amounts)
            threshold = mean + outlier_sigma * sample_stddev(amounts)
            for transaction in group:
                amount = float(transaction.get("debitAmount") or 0)
                if amount > threshold and amount > mean * 1.2:
                    findings.append(
                        {
                            "severity": "medium",
                            "date": transaction.get("localDate"),
                            "merchant": merchant,
                            "amount": money(amount),
                            "reason": f"Charge {amount:.2f} exceeds merchant baseline (mean {mean:.2f}, threshold {threshold:.2f})",
                            "action": "Verify the charge with the merchant.",
                            "id": transaction.get("id"),
                        }
                    )

    duplicate_groups: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    for transaction in scope:
        amount = float(transaction.get("debitAmount") or 0)
        if amount > 0:
            duplicate_groups.setdefault((merchant_key(transaction), str(transaction.get("localDate") or ""), amount), []).append(transaction)
    for (merchant, local_date, amount), group in duplicate_groups.items():
        if len(group) > 1:
            findings.append(
                {
                    "severity": "high",
                    "date": local_date,
                    "merchant": merchant,
                    "amount": money(amount),
                    "reason": f"Same merchant + amount {len(group)} times on {local_date}",
                    "action": "Possible duplicate charge - review and request refund if confirmed.",
                    "id": ",".join(str(item.get("id")) for item in group),
                }
            )

    for transaction in scope:
        amount = float(transaction.get("debitAmount") or 0)
        if amount > 0 and str(transaction.get("category") or "").startswith("Bank Fees"):
            findings.append(
                {
                    "severity": "low",
                    "date": transaction.get("localDate"),
                    "merchant": merchant_key(transaction),
                    "amount": money(amount),
                    "reason": f"Bank fee / interest charge ({transaction.get('category')})",
                    "action": "Avoidable - investigate whether a different account/card avoids this.",
                    "id": transaction.get("id"),
                }
            )

    first_seen: dict[str, str] = {}
    for transaction in sorted(scope, key=lambda item: str(item.get("localDate") or "")):
        if float(transaction.get("debitAmount") or 0) > 0:
            first_seen.setdefault(merchant_key(transaction), str(transaction.get("localDate") or ""))
    for transaction in scope:
        amount = float(transaction.get("debitAmount") or 0)
        merchant = merchant_key(transaction)
        if amount > min_new_merchant_amount and str(transaction.get("localDate") or "") >= recent_from and first_seen.get(merchant, "") >= recent_from:
            findings.append(
                {
                    "severity": "medium",
                    "date": transaction.get("localDate"),
                    "merchant": merchant,
                    "amount": money(amount),
                    "reason": f"First charge from {merchant} this window; amount > ${min_new_merchant_amount:g}",
                    "action": "Confirm this is an intended purchase.",
                    "id": transaction.get("id"),
                }
            )

    credit_groups: dict[str, list[dict[str, Any]]] = {}
    for transaction in scope:
        if float(transaction.get("creditAmount") or 0) > 0:
            credit_groups.setdefault(merchant_key(transaction), []).append(transaction)
    for merchant, debits in debit_groups.items():
        for debit in debits:
            for credit in credit_groups.get(merchant, []):
                if abs(float(debit.get("debitAmount") or 0) - float(credit.get("creditAmount") or 0)) < 0.01:
                    delta = abs((date.fromisoformat(str(debit.get("localDate"))) - date.fromisoformat(str(credit.get("localDate")))).days)
                    if delta <= 7:
                        findings.append(
                            {
                                "severity": "low",
                                "date": credit.get("localDate"),
                                "merchant": merchant,
                                "amount": money(float(debit.get("debitAmount") or 0)),
                                "reason": f"Refund of ${float(debit.get('debitAmount') or 0):g} matched a debit on {debit.get('localDate')}",
                                "action": "Refund or failed-charge pattern - typically benign.",
                                "id": f"{debit.get('id')},{credit.get('id')}",
                            }
                        )
    severity_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda row: (severity_order.get(row["severity"], 3), str(row.get("date") or "")), reverse=False)


def opportunities(lookback_months: int = 6, account_id: str | None = None, all_accounts: bool = False, summary_path: Path | None = None, cache_path: Path | None = None) -> list[dict[str, Any]]:
    rules = get_rules()
    account_id = account_id or rules.get("defaultAccountId") or DEFAULT_ACCOUNT_ID
    summary = read_summary(summary_path)
    scope, rows = month_scope(summary, account_id, all_accounts)
    rows = rows[-lookback_months:]
    if len(rows) < 2:
        return []
    transactions = unique_by_id(read_transactions(cache_path))
    current = rows[-1]
    baseline = rows[:-1]
    opps: list[dict[str, Any]] = []
    virtual_names = sorted({key for row in rows for key in row.get("byVirtualCategory", {}).keys()})
    for virtual_name in virtual_names:
        latest = float(current.get("byVirtualCategory", {}).get(virtual_name) or 0)
        if latest <= 0:
            continue
        history = [float(row.get("byVirtualCategory", {}).get(virtual_name) or 0) for row in baseline]
        avg = average(history)
        if avg > 0 and latest > avg * 1.25 and latest - avg >= 25:
            impact = money(latest - avg)
            opps.append(
                {
                    "opportunity": f"Trim {virtual_name} spend back to baseline",
                    "evidence": f"{latest:g} this month vs. {avg:.2f}/mo trailing avg",
                    "estimatedMonthlyImpact": impact,
                    "confidence": "medium" if len(rows) >= 4 else "low",
                    "suggestedNextAction": f"Open this category in query.py: python .banksync-analysis/query.py -Category '{virtual_name}' -ByMerchant",
                }
            )
    dining_avg = average([float(row.get("byVirtualCategory", {}).get("Dining Out") or 0) for row in rows])
    grocery_avg = average([float(row.get("byVirtualCategory", {}).get("Groceries") or 0) for row in rows])
    if grocery_avg > 0 and dining_avg / grocery_avg > 0.75:
        opps.append(
            {
                "opportunity": "Shift some dining-out spend to groceries",
                "evidence": f"Dining out averages ${dining_avg:.2f}/mo vs. groceries ${grocery_avg:.2f}/mo (ratio {dining_avg / grocery_avg:.2f})",
                "estimatedMonthlyImpact": money(dining_avg * 0.2),
                "confidence": "low",
                "suggestedNextAction": "Target a 20% reduction in restaurant/fast-food spend for one month.",
            }
        )

    window_from = rows[0]["month"] + "-01"
    window_to = add_months(parse_yyyy_mm(rows[-1]["month"]), 1).isoformat()
    fees = [
        transaction
        for transaction in transactions
        if float(transaction.get("debitAmount") or 0) > 0
        and str(transaction.get("category") or "").startswith("Bank Fees")
        and str(transaction.get("localDate") or "") >= window_from
        and str(transaction.get("localDate") or "") < window_to
        and (all_accounts or transaction.get("accountId") == account_id)
    ]
    if fees:
        total = sum(float(transaction.get("debitAmount") or 0) for transaction in fees)
        opps.append(
            {
                "opportunity": "Eliminate recurring bank fees",
                "evidence": f"{len(fees)} fee transactions totaling ${money(total)} in window",
                "estimatedMonthlyImpact": money(total / len(rows)),
                "confidence": "high",
                "suggestedNextAction": "Run Find-Anomalies.py to list each fee; switch products or call to waive.",
            }
        )
    for subscription in subscriptions(lookback_months, max(2, lookback_months - 2), account_id, all_accounts, cache_path=cache_path)[:3]:
        if float(subscription.get("annualized") or 0) >= 120:
            opps.append(
                {
                    "opportunity": f"Audit subscription: {subscription['merchant']}",
                    "evidence": f"${subscription['avgMonthly']}/mo avg, ${subscription['annualized']}/yr annualized over {subscription['months']} months",
                    "estimatedMonthlyImpact": money(subscription["avgMonthly"]),
                    "confidence": "high" if subscription["months"] >= 4 else "medium",
                    "suggestedNextAction": "Confirm you still use it; consider downgrading or canceling.",
                }
            )
    return sorted(opps, key=lambda row: row["estimatedMonthlyImpact"], reverse=True)


def project_spend(category: str = "Spend", months_back: int = 12, months_forward: int = 6, account_id: str | None = None, all_accounts: bool = False, summary_path: Path | None = None, cache_path: Path | None = None) -> dict[str, Any]:
    rules = get_rules()
    account_id = account_id or rules.get("defaultAccountId") or DEFAULT_ACCOUNT_ID
    summary = read_summary(summary_path)
    virtual_names = set((rules.get("virtualCategories") or {}).keys())
    mode = "Total" if category in {"Spend", "Income", "Net"} else "Virtual" if category in virtual_names else "Regex"

    def month_value(month_data: dict[str, Any], key: str) -> float:
        if mode == "Total":
            return float(month_data.get(key.lower()) or 0)
        if mode == "Virtual":
            return float((month_data.get("byVirtualCategory") or {}).get(key) or 0)
        return sum(float(value or 0) for name, value in (month_data.get("byCategory") or {}).items() if re.search(key, name, re.IGNORECASE))

    accounts = summary.get("accounts") or {}
    rows: list[dict[str, Any]] = []
    if all_accounts:
        months = sorted({month for account in accounts.values() for month in (account.get("monthly") or {}).keys()})
        for month in months:
            total = 0.0
            for account in accounts.values():
                data = (account.get("monthly") or {}).get(month)
                if data:
                    total += month_value(data, category)
            rows.append({"month": month, "value": money(total)})
        scope = "ALL accounts"
    else:
        account = accounts.get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found in summary.")
        for month, data in (account.get("monthly") or {}).items():
            rows.append({"month": month, "value": money(month_value(data, category))})
        rows.sort(key=lambda row: row["month"])
        scope = account.get("accountName") or account_id

    month_now = current_month()
    completed = [row for row in rows if row["month"] < month_now][-months_back:]
    if not completed:
        raise ValueError(f"No completed months available for {category} in scope {scope}.")
    values = [float(row["value"]) for row in completed]
    avg12 = money(average(values))
    avg3 = money(average(values[-3:])) if len(values) >= 3 else avg12
    stddev = money(sample_stddev(values))
    trend_window = values[-6:]
    n = len(trend_window)
    if n >= 2:
        xs = list(range(n))
        sum_x = sum(xs)
        sum_y = sum(trend_window)
        sum_xy = sum(x * y for x, y in zip(xs, trend_window))
        sum_xx = sum(x * x for x in xs)
        denom = n * sum_xx - sum_x * sum_x
        slope = ((n * sum_xy) - (sum_x * sum_y)) / denom if denom else 0.0
        intercept = (sum_y - slope * sum_x) / n
    else:
        slope = 0.0
        intercept = values[-1]
    slope = money(slope)
    trend_next = money(intercept + slope * n)

    month_start = parse_yyyy_mm(month_now)
    forecast = []
    for index in range(months_forward):
        future_month = add_months(month_start, index + 1).strftime("%Y-%m")
        trend_y = money(intercept + slope * (n + index))
        point = money((avg3 + avg12 + trend_y) / 3.0)
        forecast.append(
            {
                "month": future_month,
                "forecast": point,
                "low": money(max(0.0, point - 2 * stddev)),
                "high": money(point + 2 * stddev),
                "trendOnly": trend_y,
            }
        )

    mtd_actual = mtd_projected = None
    days_elapsed = month_days = 0
    cache = cache_path or REPO_ROOT / ".banksync-cache" / "normalized.jsonl"
    if cache.exists():
        transactions = read_transactions(cache)
        next_month = add_months(month_start, 1).isoformat()
        days_elapsed = date.today().day
        month_days = days_in_month(month_start)
        field = "creditAmount" if category == "Income" else "debitAmount"
        use_credit = category == "Income"
        matches = []
        for transaction in transactions:
            if not (str(transaction.get("localDate") or "") >= month_start.isoformat() and str(transaction.get("localDate") or "") < next_month):
                continue
            if not (all_accounts or transaction.get("accountId") == account_id):
                continue
            if float(transaction.get(field) or 0) <= 0:
                continue
            if excluded_from_spend(transaction, rules) and not use_credit:
                continue
            if mode == "Total" or (mode == "Regex" and re.search(category, str(transaction.get("category") or ""), re.IGNORECASE)) or (mode == "Virtual" and category in virtual_category_hits(transaction, rules)):
                matches.append(transaction)
        mtd_actual = money(sum(float(transaction.get(field) or 0) for transaction in matches))
        mtd_projected = money(mtd_actual * month_days / days_elapsed) if days_elapsed > 0 else None

    return {
        "category": category,
        "mode": mode,
        "scope": scope,
        "history": completed,
        "avg3": avg3,
        "avg12": avg12,
        "stddev": stddev,
        "trend": {"slope": slope, "nextMonth": trend_next},
        "forecast": forecast,
        "mtd": {"month": month_now, "actual": mtd_actual, "projected": mtd_projected, "daysElapsed": days_elapsed, "daysInMonth": month_days},
    }


def build_monthly_report(month: str | None = None, account_id: str | None = None, all_accounts: bool = False, out_dir: Path | None = None, summary_path: Path | None = None, cache_path: Path | None = None) -> Path:
    rules = get_rules()
    account_id = account_id or rules.get("defaultAccountId") or DEFAULT_ACCOUNT_ID
    summary = read_summary(summary_path)
    accounts = summary.get("accounts") or {}
    if all_accounts:
        months = sorted({name for account in accounts.values() for name in (account.get("monthly") or {}).keys()})
        scope = "ALL accounts"
    else:
        account = accounts.get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found in summary.")
        months = sorted((account.get("monthly") or {}).keys())
        scope = account.get("accountName") or account_id
    completed_months = [name for name in months if name < current_month()]
    if not month:
        if not completed_months:
            raise ValueError("No completed months available. Pass -Month explicitly.")
        month = completed_months[-1]
    if month not in months:
        raise ValueError(f"Month {month} not found in summary.")

    current = month_values_for_scope(summary, account_id, all_accounts, month)
    if not current:
        raise ValueError(f"Month {month} not found in selected scope.")
    prior_months = [name for name in completed_months if name < month][-3:]
    prior_data = [month_values_for_scope(summary, account_id, all_accounts, name) for name in prior_months]
    prior_data = [item for item in prior_data if item]

    def category_average(field: str) -> dict[str, float]:
        if not prior_data:
            return {}
        totals: dict[str, float] = {}
        for item in prior_data:
            for key, value in (item.get(field) or {}).items():
                totals[key] = totals.get(key, 0.0) + float(value or 0)
        return {key: money(value / len(prior_data)) for key, value in totals.items()}

    prior_category_average = category_average("byCategory")
    prior_virtual_average = category_average("byVirtualCategory")
    category_deltas = []
    for key in sorted(set(current.get("byCategory", {}).keys()) | set(prior_category_average.keys())):
        now = float(current.get("byCategory", {}).get(key) or 0)
        base = float(prior_category_average.get(key) or 0)
        if now == 0 and base == 0:
            continue
        category_deltas.append({"category": key, "current": money(now), "priorAvg": money(base), "delta": money(now - base), "pct": metric((now - base) / base * 100, 1) if base > 0 else None})
    category_deltas = sorted(category_deltas, key=lambda item: abs(item["delta"]), reverse=True)[:10]
    top_merchants = [
        {"merchant": key, "total": money(value["total"]), "count": value["count"]}
        for key, value in sorted((current.get("topMerchants") or {}).items(), key=lambda item: item[1]["total"], reverse=True)[:10]
    ]
    subs = subscriptions(6, 3, account_id, all_accounts, cache_path=cache_path)
    anoms = anomalies(3, account_id=account_id, all_accounts=all_accounts, cache_path=cache_path)
    projection = project_spend("Spend", 12, 3, account_id, all_accounts, summary_path, cache_path)
    opps = opportunities(6, account_id, all_accounts, summary_path, cache_path)

    def dollars(value: Any) -> str:
        return f"${float(value or 0):,.2f}"

    lines: list[str] = []
    lines.extend([f"# Monthly Report - {month}", "", f"_Scope: **{scope}** | Generated: {datetime.now():%Y-%m-%d %H:%M}_", ""])
    savings_rate = f"{(current['net'] / current['income']) * 100:.1f}%" if current["income"] > 0 else "n/a"
    lines.extend(["## Cashflow", "", "| Income | Spend | Net | Savings Rate | Txn Count |", "|---:|---:|---:|---:|---:|", f"| {dollars(current['income'])} | {dollars(current['spend'])} | {dollars(current['net'])} | {savings_rate} | {current['txnCount']} |", ""])
    if prior_data:
        lines.extend([f"_Trailing {len(prior_data)}-month avg - income {dollars(average([item['income'] for item in prior_data]))}, spend {dollars(average([item['spend'] for item in prior_data]))}, net {dollars(average([item['net'] for item in prior_data]))}._", ""])

    lines.extend(["## Top Category Changes vs. Prior Avg", ""])
    if category_deltas:
        lines.extend(["| Category | This Month | Prior Avg | Delta | % |", "|---|---:|---:|---:|---:|"])
        for item in category_deltas:
            pct = "n/a" if item["pct"] is None else f"{item['pct']:.1f}%"
            lines.append(f"| {item['category']} | {dollars(item['current'])} | {dollars(item['priorAvg'])} | {dollars(item['delta'])} | {pct} |")
    else:
        lines.append("_No prior months available for comparison._")
    lines.append("")

    lines.extend(["## Virtual Categories", ""])
    if current.get("byVirtualCategory"):
        lines.extend(["| Category | Spend | Prior Avg |", "|---|---:|---:|"])
        for key, value in sorted(current["byVirtualCategory"].items(), key=lambda item: float(item[1]), reverse=True):
            lines.append(f"| {key} | {dollars(value)} | {dollars(prior_virtual_average.get(key, 0))} |")
    else:
        lines.append("_No virtual categories defined or matched._")
    lines.append("")

    lines.extend(["## Top Merchants", ""])
    if top_merchants:
        lines.extend(["| Merchant | Total | Count |", "|---|---:|---:|"])
        for item in top_merchants:
            lines.append(f"| {item['merchant']} | {dollars(item['total'])} | {item['count']} |")
    else:
        lines.append("_No merchant data._")
    lines.append("")

    lines.extend(["## Subscription Audit", ""])
    if subs:
        lines.extend(["| Merchant | Months | Avg/mo | Annualized | Price Jump |", "|---|---:|---:|---:|:---:|"])
        for item in subs[:15]:
            lines.append(f"| {item['merchant']} | {item['months']} | {dollars(item['avgMonthly'])} | {dollars(item['annualized'])} | {'yes' if item['priceJump'] else ''} |")
    else:
        lines.append("_No recurring merchants detected in the trailing window._")
    lines.append("")

    lines.extend(["## Anomalies", ""])
    if anoms:
        lines.extend(["| Sev | Date | Merchant | Amount | Reason |", "|---|---|---|---:|---|"])
        for item in anoms[:20]:
            lines.append(f"| {item['severity']} | {item['date']} | {item['merchant']} | {dollars(item['amount'])} | {str(item['reason']).replace('|', '\\|')} |")
    else:
        lines.append("_No anomalies detected._")
    lines.append("")

    lines.extend(["## Projection (Spend, next 3 months)", ""])
    if projection.get("forecast"):
        lines.append(f"Averages - 3-mo **{dollars(projection['avg3'])}**, 12-mo **{dollars(projection['avg12'])}**, stddev **{dollars(projection['stddev'])}**. Trend slope **{dollars(projection['trend']['slope'])}/mo**.")
        if projection["mtd"].get("daysElapsed", 0) > 0:
            mtd = projection["mtd"]
            lines.append(f"MTD {mtd['month']}: **{dollars(mtd['actual'])}** ({mtd['daysElapsed']}/{mtd['daysInMonth']} days), projected end-of-month **{dollars(mtd['projected'])}**.")
        lines.extend(["", "| Month | Forecast | Low (-2s) | High (+2s) |", "|---|---:|---:|---:|"])
        for item in projection["forecast"]:
            lines.append(f"| {item['month']} | {dollars(item['forecast'])} | {dollars(item['low'])} | {dollars(item['high'])} |")
    else:
        lines.append("_Not enough history to project._")
    lines.append("")

    lines.extend(["## Suggested Actions", ""])
    if opps:
        for item in opps[:6]:
            lines.append(f"- **{dollars(item['estimatedMonthlyImpact'])}/mo - {item['confidence']}** - {item['opportunity']}")
            lines.append(f"  - Evidence: {item['evidence']}")
            lines.append(f"  - Next: {item['suggestedNextAction']}")
    else:
        lines.append("_No notable opportunities flagged._")
    lines.append("")

    last_months = [name for name in completed_months if name <= month][-6:]
    if len(last_months) >= 2:
        lines.extend(["## Trend (last 6 months)", "", "```mermaid", "xychart-beta", f"  title \"Spend vs Income - {scope}\"", f"  x-axis [{', '.join(chr(34) + name + chr(34) for name in last_months)}]", '  y-axis "USD"'])
        spend_series = [month_values_for_scope(summary, account_id, all_accounts, name)["spend"] for name in last_months]
        income_series = [month_values_for_scope(summary, account_id, all_accounts, name)["income"] for name in last_months]
        lines.append(f"  bar    [{', '.join(f'{value:.2f}' for value in spend_series)}]")
        lines.append(f"  line   [{', '.join(f'{value:.2f}' for value in income_series)}]")
        lines.extend(["```", ""])

    if current.get("byVirtualCategory"):
        lines.extend(["## Category Mix", "", "```mermaid", "pie showData", f"  title \"{month} - virtual category spend\""])
        for key, value in sorted(current["byVirtualCategory"].items(), key=lambda item: float(item[1]), reverse=True)[:8]:
            if float(value) > 0:
                lines.append(f"  \"{key}\" : {float(value):.2f}")
        lines.extend(["```", ""])

    destination = out_dir or ANALYSIS_ROOT / "reports"
    destination.mkdir(parents=True, exist_ok=True)
    out_file = destination / f"{month}.md"
    out_file.write_text("\n".join(lines), encoding="utf-8")
    return out_file


def _trailing_window(months_back: int) -> tuple[str, str]:
    today = date.today()
    month_start = date(today.year, today.month, 1)
    return add_months(month_start, -(months_back - 1)).isoformat(), add_months(month_start, 1).isoformat()
