#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from banksync_analysis.commands import import_dump


def main() -> int:
    parser = argparse.ArgumentParser(description="Import BankSync MCP transaction dumps into the local cache.")
    parser.add_argument("-Files", nargs="+", type=Path, required=True)
    parser.add_argument("-FetchLabel", default=None)
    parser.add_argument("-CacheRoot", type=Path, default=None)
    args = parser.parse_args()
    result = import_dump(args.Files, args.FetchLabel, args.CacheRoot)
    print(f"Imported {result['totalIn']} transactions across {len(args.Files)} file(s)")
    print(f"  New: {result['new']}  Updated/seen: {result['updated']}  Cache total: {result['cacheTotal']}")
    print(f"  Cache: {result['cacheRoot']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
