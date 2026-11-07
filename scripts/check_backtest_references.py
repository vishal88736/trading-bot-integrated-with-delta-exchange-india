"""Recheck exported statistics or run the independent Backtrader broker scenarios."""

import argparse
import json
from pathlib import Path

from bot.reference_checks import REFERENCES, validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path, nargs="?")
    parser.add_argument("--runtime", type=Path, default=Path(".runtime"))
    parser.add_argument("--only", nargs="+", choices=[name for name, _, _ in REFERENCES])
    args = parser.parse_args()
    if args.result is None and args.only != ["Backtrader"]:
        parser.error("An exported result is required for the statistics checks")
    result = json.loads(args.result.read_text()) if args.result else {}
    report = validate(result, args.runtime / "references", only=args.only)
    print(json.dumps(report, indent=2, allow_nan=False))
    if any(check["status"] != "passed" for check in report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
