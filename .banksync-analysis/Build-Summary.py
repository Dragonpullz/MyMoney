#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from banksync_analysis.commands import build_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build .banksync-cache/summary.json from normalized transactions.")
    parser.add_argument("-CacheRoot", type=Path, default=None)
    parser.add_argument("-TopMerchants", type=int, default=10)
    args = parser.parse_args()
    summary = build_summary(args.CacheRoot, args.TopMerchants)
    account_count = len(summary["accounts"])
    default_account_id = summary["scopeDefaults"]["accountId"]
    default_months = len((summary["accounts"].get(default_account_id) or {}).get("monthly") or {})
    print(f"Summary written: {(args.CacheRoot or Path('.banksync-cache')) / 'summary.json'}")
    print(f"  Accounts: {account_count}  |  Default-account months: {default_months}  |  Txn total: {summary['txnCount']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
