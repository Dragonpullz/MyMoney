#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from banksync_analysis.commands import find_subscriptions
from banksync_analysis.core import compact_json, get_rules


def main() -> int:
    rules = get_rules()
    parser = argparse.ArgumentParser(description="Detect recurring subscription-like charges.")
    parser.add_argument("-MonthsBack", type=int, default=6)
    parser.add_argument("-MinMonths", type=int, default=3)
    parser.add_argument("-AccountId", default=rules["defaultAccountId"])
    parser.add_argument("-AllAccounts", action="store_true")
    parser.add_argument("-MinTotal", type=float, default=5.0)
    parser.add_argument("-Format", choices=["text", "json"], default="text")
    parser.add_argument("-CachePath", type=Path, default=None)
    args = parser.parse_args()
    rows = find_subscriptions(args.MonthsBack, args.MinMonths, args.AccountId, args.AllAccounts, args.MinTotal, args.CachePath)
    if args.Format == "json":
        print(compact_json(rows))
    else:
        if not rows:
            print("No recurring merchants found.")
        for row in rows:
            print(f"{row['merchant']} months={row['months']} avgMonthly=${row['avgMonthly']} annualized=${row['annualized']} cadence={row['cadence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
