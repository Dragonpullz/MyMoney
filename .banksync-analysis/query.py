#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

from banksync_analysis.core import (
    DEFAULT_ACCOUNT_ID,
    compact_json,
    default_from_to,
    ensure_local_dates,
    merchant_key,
    money,
    read_transactions,
    resolve_category_preset,
    unique_by_id,
)


def load_raw_files(files: list[str]) -> list[dict]:
    import json

    transactions: list[dict] = []
    for file_name in files:
        path = Path(file_name)
        if not path.exists():
            print(f"WARNING: Missing file: {file_name}")
            continue
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        transactions.extend(payload.get("transactions") or [])
    return transactions


def build_query(args: argparse.Namespace) -> dict:
    category_regex = resolve_category_preset(args.Category)
    from_value, to_value = default_from_to(args.From, args.To)
    transactions = load_raw_files(args.Files) if args.Files else read_transactions()
    transactions = unique_by_id(transactions)
    ensure_local_dates(transactions)

    amount_field = "creditAmount" if args.Income else "debitAmount"
    direction = "IN" if args.Income else "OUT"
    category_pattern = re.compile(category_regex, flags=re.IGNORECASE)

    hits = [
        transaction
        for transaction in transactions
        if category_pattern.search(str(transaction.get("category") or ""))
        and float(transaction.get(amount_field) or 0) > 0
        and str(transaction.get("localDate") or "") >= from_value
        and str(transaction.get("localDate") or "") < to_value
        and (args.AllAccounts or not args.AccountId or transaction.get("accountId") == args.AccountId)
    ]

    total = money(sum(float(transaction.get(amount_field) or 0) for transaction in hits))
    account_name = next((t.get("accountName") for t in transactions if t.get("accountId") == args.AccountId), None)
    scope = "ALL accounts" if args.AllAccounts or not args.AccountId else account_name or args.AccountId

    month_groups: dict[str, list[dict]] = {}
    for transaction in hits:
        month_groups.setdefault(transaction.get("month") or "", []).append(transaction)
    by_month = [
        {
            "month": month,
            "count": len(rows),
            "total": money(sum(float(row.get(amount_field) or 0) for row in rows)),
        }
        for month, rows in sorted(month_groups.items())
    ]

    merchant_groups: dict[str, list[dict]] = {}
    for transaction in hits:
        merchant_groups.setdefault(merchant_key(transaction), []).append(transaction)
    by_merchant = sorted(
        (
            {
                "merchant": merchant,
                "count": len(rows),
                "total": money(sum(float(row.get(amount_field) or 0) for row in rows)),
                "avg": money(sum(float(row.get(amount_field) or 0) for row in rows) / len(rows)),
            }
            for merchant, rows in merchant_groups.items()
        ),
        key=lambda row: row["total"],
        reverse=True,
    )[: args.Top]

    output = {
        "category": args.Category,
        "categoryRegex": category_regex,
        "direction": direction,
        "from": from_value,
        "to": to_value,
        "scope": scope,
        "accountId": None if args.AllAccounts else args.AccountId,
        "total": total,
        "count": len(hits),
        "byMonth": by_month,
    }
    if args.ByMerchant:
        output["byMerchant"] = by_merchant
    if args.Detailed:
        output["transactions"] = [
            {
                "date": transaction.get("localDate"),
                "amount": transaction.get(amount_field),
                "merchant": merchant_key(transaction),
                "category": transaction.get("category"),
                "account": transaction.get("accountName"),
                "id": transaction.get("id"),
            }
            for transaction in sorted(hits, key=lambda item: str(item.get("localDate") or ""))
        ]
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="General BankSync spend query.")
    parser.add_argument("-Files", nargs="*", default=[])
    parser.add_argument("-Category", default=".")
    parser.add_argument("-From")
    parser.add_argument("-To")
    parser.add_argument("-AccountId", default=DEFAULT_ACCOUNT_ID)
    parser.add_argument("-AllAccounts", action="store_true")
    parser.add_argument("-Top", type=int, default=20)
    parser.add_argument("-Income", action="store_true")
    parser.add_argument("-ByMerchant", action="store_true")
    parser.add_argument("-Detailed", action="store_true")
    parser.add_argument("-Format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    output = build_query(args)
    if args.Format == "json":
        print(compact_json(output))
    else:
        print(f"=== {args.Category} [{output['direction']}] | {output['from']} -> {output['to']} | {output['scope']} ===")
        print(f"Total: ${output['total']}  ({output['count']} txns)")
        if output["byMonth"]:
            print("By month:")
            for row in output["byMonth"]:
                print(f"  {row['month']}  {row['count']}  ${row['total']}")
        if args.ByMerchant:
            print("By merchant:")
            for row in output.get("byMerchant", []):
                print(f"  {row['merchant']}  {row['count']}  ${row['total']}  avg ${row['avg']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
