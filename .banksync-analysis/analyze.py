#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from banksync_analysis.commands import analyze_raw
from banksync_analysis.core import compact_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze raw BankSync transaction dumps.")
    parser.add_argument("-Files", nargs="+", type=Path, required=True)
    parser.add_argument("-Format", choices=["text", "json"], default="text")
    args = parser.parse_args()
    result = analyze_raw(args.Files)
    if args.Format == "json":
        print(compact_json(result))
    else:
        print("===== OVERVIEW =====")
        print(f"Total unique txns: {result['txnCount']}")
        print(f"Range: {result['range']['from']} -> {result['range']['to']}")
        print(f"Total debits (out): ${result['totalDebits']}")
        print(f"Total credits (in): ${result['totalCredits']}")
        print(f"Net: ${result['net']}")
        print("===== TOP CATEGORIES (by spend) =====")
        for row in result["topCategories"]:
            print(f"{row['category']} {row['count']} ${row['total']}")
        print("===== TOP MERCHANTS (by spend) =====")
        for row in result["topMerchants"]:
            print(f"{row['merchant']} {row['count']} ${row['total']} avg=${row['avg']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
