"""Recheck an exported dashboard report using the optional external statistics."""

import argparse
import json
from pathlib import Path

from bot.reference_checks import validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--runtime", type=Path, default=Path(".runtime"))
    args = parser.parse_args()
    report = validate(json.loads(args.result.read_text()), args.runtime / "references")
    print(json.dumps(report, indent=2, allow_nan=False))
    if any(check["status"] != "passed" for check in report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
