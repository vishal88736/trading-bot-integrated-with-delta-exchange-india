"""Download the two user-selected references at their reviewed commits.

Their source stays under ignored .runtime/references; no third-party code is
copied into the distributed application. Install research dependencies with uv.
"""

import argparse
import subprocess
from pathlib import Path

from bot.reference_checks import REFERENCES, verify_checkout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=Path(".runtime"))
    args = parser.parse_args()
    root = args.runtime / "references"
    root.mkdir(parents=True, exist_ok=True)
    for name, url, commit in REFERENCES:
        target = root / name
        if not target.exists():
            subprocess.run(["git", "init", str(target)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(target), "remote", "add", "origin", url + ".git"], check=True
            )
            subprocess.run(
                ["git", "-C", str(target), "fetch", "--depth", "1", "origin", commit], check=True
            )
            subprocess.run(
                ["git", "-C", str(target), "checkout", "--detach", "FETCH_HEAD"], check=True
            )
        verify_checkout(target, commit)
        print(f"Ready: {name} at {commit}")


if __name__ == "__main__":
    main()
