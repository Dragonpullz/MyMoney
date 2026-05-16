#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from banksync_analysis.commands import find_opportunities
from banksync_analysis.core import compact_json, get_rules


def main() -> int:
    rules = get_rules()
    parser = argparse.ArgumentParser(description="Rank potential savings opportunities.")
    parser.add_argument("-LookbackMonths", type=int, default=6)
    parser.add_argument("-AccountId", default=rules["defaultAccountId"])
    parser.add_argument("-AllAccounts", action="store_true")
    parser.add_argument("-Format", choices=["text", "json"], default="text")
    parser.add_argument("-SummaryPath", type=Path, default=None)
    parser.add_argument("-CachePath", type=Path, default=None)
    args = parser.parse_args()
    rows = find_opportunities(args.LookbackMonths, args.AccountId, args.AllAccounts, args.SummaryPath, args.CachePath)
    if args.Format == "json":
        print(compact_json(rows))
    else:
        if not rows:
            print("No notable opportunities found.")
        for row in rows:
            print(f"${row['estimatedMonthlyImpact']}/mo {row['confidence']} - {row['opportunity']} ({row['evidence']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
