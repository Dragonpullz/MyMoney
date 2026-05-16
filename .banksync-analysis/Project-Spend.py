#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from banksync_analysis.commands import project_spend
from banksync_analysis.core import compact_json, get_rules


def main() -> int:
    rules = get_rules()
    parser = argparse.ArgumentParser(description="Project future spend/income for a category.")
    parser.add_argument("-Category", default="Spend")
    parser.add_argument("-MonthsBack", type=int, default=12)
    parser.add_argument("-MonthsForward", type=int, default=6)
    parser.add_argument("-AccountId", default=rules["defaultAccountId"])
    parser.add_argument("-AllAccounts", action="store_true")
    parser.add_argument("-Format", choices=["text", "json"], default="text")
    parser.add_argument("-SummaryPath", type=Path, default=None)
    parser.add_argument("-CachePath", type=Path, default=None)
    args = parser.parse_args()
    result = project_spend(args.Category, args.MonthsBack, args.MonthsForward, args.AccountId, args.AllAccounts, args.SummaryPath, args.CachePath)
    if args.Format == "json":
        print(compact_json(result))
    else:
        print(f"=== Projection | {result['category']} | {result['scope']} ===")
        print(f"Averages: 3-mo ${result['avg3']}  12-mo ${result['avg12']}  stddev ${result['stddev']}")
        for row in result["forecast"]:
            print(f"{row['month']} forecast=${row['forecast']} low=${row['low']} high=${row['high']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
