#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from banksync_analysis.commands import monthly_cashflow
from banksync_analysis.core import compact_json, get_rules


def main() -> int:
    rules = get_rules()
    parser = argparse.ArgumentParser(description="Monthly cashflow / savings-rate report.")
    parser.add_argument("-Months", type=int, default=12)
    parser.add_argument("-AccountId", default=rules["defaultAccountId"])
    parser.add_argument("-AllAccounts", action="store_true")
    parser.add_argument("-Format", choices=["text", "json"], default="text")
    parser.add_argument("-SummaryPath", type=Path, default=None)
    args = parser.parse_args()
    result = monthly_cashflow(args.Months, args.AccountId, args.AllAccounts, args.SummaryPath)
    if args.Format == "json":
        print(compact_json(result))
    else:
        print(f"=== Cashflow | {result['scope']} | last {len(result['months'])} months ===")
        for row in result["months"]:
            print(f"{row['month']} income=${row['income']} spend=${row['spend']} net=${row['net']} savingsRate={row['savingsRate']}")
        if result["ytd"]:
            ytd = result["ytd"]
            print(f"YTD {ytd['year']}: income=${ytd['income']} spend=${ytd['spend']} net=${ytd['net']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
