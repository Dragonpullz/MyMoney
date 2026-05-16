#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from banksync_analysis.commands import build_monthly_report
from banksync_analysis.core import get_rules


def main() -> int:
    rules = get_rules()
    parser = argparse.ArgumentParser(description="Build a Markdown monthly report.")
    parser.add_argument("-Month", default=None)
    parser.add_argument("-AccountId", default=rules["defaultAccountId"])
    parser.add_argument("-AllAccounts", action="store_true")
    parser.add_argument("-OutDir", type=Path, default=None)
    parser.add_argument("-SummaryPath", type=Path, default=None)
    parser.add_argument("-CachePath", type=Path, default=None)
    args = parser.parse_args()
    out_file = build_monthly_report(args.Month, args.AccountId, args.AllAccounts, args.OutDir, args.SummaryPath, args.CachePath)
    print(f"Report written: {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
