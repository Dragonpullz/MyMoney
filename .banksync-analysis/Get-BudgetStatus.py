#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from banksync_analysis.commands import budget_status
from banksync_analysis.core import compact_json, get_rules


def main() -> int:
    rules = get_rules()
    parser = argparse.ArgumentParser(description="Shows budget progress by virtual category for one month.")
    parser.add_argument("-Month", default=None)
    parser.add_argument("-AccountId", default=rules["defaultAccountId"])
    parser.add_argument("-AllAccounts", action="store_true")
    parser.add_argument("-Format", choices=["text", "json"], default="text")
    parser.add_argument("-BudgetPath", type=Path, default=None)
    parser.add_argument("-SummaryPath", type=Path, default=None)
    args = parser.parse_args()
    result = budget_status(args.Month, args.AccountId, args.AllAccounts, args.BudgetPath, args.SummaryPath)
    if args.Format == "json":
        print(compact_json(result))
    else:
        print(f"=== Budget Status | {result['scope']} | {result['month']} ({result['daysElapsed']}/{result['daysInMonth']} days) ===")
        for row in result["categories"]:
            print(f"{row['category']} budget=${row['budget']} actual=${row['actual']} projected=${row['projected']} status={row['status']}")
        totals = result["totals"]
        print(f"Totals: budget=${totals['budget']} actual=${totals['actual']} projected=${totals['projected']} priorMonth=${totals['priorMonth']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
