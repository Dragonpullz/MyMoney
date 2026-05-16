from __future__ import annotations

import json
import re
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable


ANALYSIS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ANALYSIS_ROOT.parent
DEFAULT_ACCOUNT_ID = "P45rzOvVJ7uA59M1o3REU5gvZvmzQ7Igk6yM9"
DEFAULT_ACCOUNT_NAME = "House Checking"


def money(value: float | int | None) -> float:
    return round(float(value or 0), 2)


def metric(value: float | int | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        if compact:
            json.dump(payload, handle, separators=(",", ":"))
        else:
            json.dump(payload, handle, indent=2)
            handle.write("\n")


def default_rules() -> dict[str, Any]:
    return {
        "defaultAccountId": DEFAULT_ACCOUNT_ID,
        "defaultAccountName": DEFAULT_ACCOUNT_NAME,
        "virtualCategories": {},
        "excludeFromHouseholdSpend": [
            "Transfer In",
            "Transfer Out",
            "Loan Payments Credit Card Payment",
        ],
        "merchantAliases": {},
    }


def get_rules(path: Path | None = None) -> dict[str, Any]:
    rules_path = path or ANALYSIS_ROOT / "rules.json"
    defaults = default_rules()
    if not rules_path.exists():
        return defaults

    try:
        rules = load_json(rules_path)
    except Exception:
        return defaults

    for key, value in defaults.items():
        rules.setdefault(key, value)
    return rules


def get_merchant_alias_map(rules: dict[str, Any]) -> list[dict[str, str]]:
    aliases = rules.get("merchantAliases") or {}
    return [{"pattern": pattern, "name": name} for pattern, name in aliases.items()]


def excluded_from_spend(transaction: dict[str, Any], rules: dict[str, Any]) -> bool:
    category = str(transaction.get("category") or "")
    return any(category.startswith(pattern) for pattern in rules.get("excludeFromHouseholdSpend") or [])


def virtual_category_hits(transaction: dict[str, Any], rules: dict[str, Any]) -> list[str]:
    category = str(transaction.get("category") or "")
    hits: list[str] = []
    for virtual_category, prefixes in (rules.get("virtualCategories") or {}).items():
        if any(category.startswith(prefix) for prefix in prefixes):
            hits.append(virtual_category)
    return hits


def normalize_merchant(merchant_name: str | None, description: str | None, aliases: Iterable[dict[str, str]]) -> str:
    candidate = merchant_name.strip() if merchant_name else ""
    if not candidate and description:
        candidate = re.split(r"\s{2,}|DES:|ID:", description)[0].strip()
    for alias in aliases:
        if re.search(alias["pattern"], candidate, flags=re.IGNORECASE):
            return alias["name"]
    return candidate


def merchant_key(transaction: dict[str, Any]) -> str:
    return transaction.get("normalizedMerchant") or transaction.get("merchantName") or "(none)"


def read_transactions(path: Path | None = None) -> list[dict[str, Any]]:
    cache_path = path or REPO_ROOT / ".banksync-cache" / "normalized.jsonl"
    if not cache_path.exists():
        raise FileNotFoundError(f"Transaction cache not found at {cache_path}. Run Import-BankSyncDump.py first.")

    transactions: list[dict[str, Any]] = []
    with cache_path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if line:
                transactions.append(json.loads(line))
    return transactions


def read_summary(path: Path | None = None) -> dict[str, Any]:
    summary_path = path or REPO_ROOT / ".banksync-cache" / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary not found at {summary_path}. Run Build-Summary.py first.")
    return load_json(summary_path)


def unique_by_id(transactions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for transaction in sorted(transactions, key=lambda item: str(item.get("id") or "")):
        by_id.setdefault(str(transaction.get("id") or ""), transaction)
    return list(by_id.values())


def ensure_local_dates(transactions: Iterable[dict[str, Any]]) -> None:
    for transaction in transactions:
        if not transaction.get("localDate"):
            local_date = str(transaction.get("date") or "")[:10]
            transaction["localDate"] = local_date
            transaction["month"] = local_date[:7]


def category_presets() -> OrderedDict[str, str]:
    return OrderedDict(
        [
            ("gas", "Transportation Gas"),
            ("groceries", "Food And Drink Groceries"),
            ("restaurants", "Food And Drink Restaurant"),
            ("fastfood", "Food And Drink Fast Food"),
            ("coffee", "Food And Drink Coffee"),
            ("dining", "Food And Drink (Restaurant|Fast Food|Coffee)"),
            ("utilities", "Rent And Utilities"),
            ("electricity", "Rent And Utilities Gas And Electricity"),
            ("internet", "Rent And Utilities Telephone|Rent And Utilities Internet"),
            ("mortgage", "Loan Payments Mortgage Payment"),
            ("ccpayments", "Loan Payments Credit Card Payment"),
            ("insurance", "General Services Insurance"),
            ("pharmacy", "Medical Pharmacies And Supplements"),
            ("vet", "Medical Veterinary Services"),
            ("amazon", "General Merchandise Online Marketplaces"),
            ("subscriptions", "General Services Other General Services|Entertainment"),
            ("transfers", "Transfer (In|Out)"),
            ("income", "Income |Transfer In"),
        ]
    )


def resolve_category_preset(category: str) -> str:
    return category_presets().get(category.lower(), category)


def compact_json(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"))


def parse_yyyy_mm(month: str) -> date:
    year, month_number = month.split("-")
    return date(int(year), int(month_number), 1)


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def month_range_ending_current(months_back: int, today: date | None = None) -> tuple[str, str]:
    current = today or date.today()
    month_start = date(current.year, current.month, 1)
    start = add_months(month_start, -(months_back - 1))
    end = add_months(month_start, 1)
    return start.isoformat(), end.isoformat()


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def default_from_to(from_value: str | None, to_value: str | None) -> tuple[str, str]:
    today = date.today()
    return (
        from_value or (today - timedelta(days=90)).isoformat(),
        to_value or (today + timedelta(days=1)).isoformat(),
    )
