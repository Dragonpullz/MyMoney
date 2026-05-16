#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from banksync_analysis.commands import find_anomalies
from banksync_analysis.core import compact_json, get_rules


def main() -> int:
    rules = get_rules()
    parser = argparse.ArgumentParser(description="Find unusual transactions.")
    parser.add_argument("-WindowMonths", type=int, default=6)
    parser.add_argument("-OutlierSigma", type=float, default=2.0)
    parser.add_argument("-MinNewMerchantAmount", type=float, default=100.0)
    parser.add_argument("-AccountId", default=rules["defaultAccountId"])
    parser.add_argument("-AllAccounts", action="store_true")
    parser.add_argument("-Format", choices=["text", "json"], default="text")
    parser.add_argument("-CachePath", type=Path, default=None)
    args = parser.parse_args()
    rows = find_anomalies(args.WindowMonths, args.OutlierSigma, args.MinNewMerchantAmount, args.AccountId, args.AllAccounts, args.CachePath)
    if args.Format == "json":
        print(compact_json(rows))
    else:
        if not rows:
            print("No anomalies detected.")
        for row in rows:
            print(f"{row['severity']} {row['date']} {row['merchant']} ${row['amount']} - {row['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
