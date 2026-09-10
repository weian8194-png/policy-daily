#!/usr/bin/env python3
"""Create dated archives deterministically from the two generated homepages."""

import argparse
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def create_archives(report_date, root=ROOT):
    stamp = report_date.strftime("%Y%m%d")
    policy = (root / "index.html").read_text(encoding="utf-8")
    appliance = (root / "appliance-trends" / "index.html").read_text(encoding="utf-8")

    # Appliance archive pages live one directory deeper than the homepage.
    appliance_archive = appliance.replace('href="./daily/', 'href="./').replace(
        "href='./daily/", "href='./"
    )

    policy_path = root / "daily" / "{}.html".format(stamp)
    appliance_path = root / "appliance-trends" / "daily" / "{}.html".format(stamp)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    appliance_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(policy, encoding="utf-8")
    appliance_path.write_text(appliance_archive, encoding="utf-8")
    return policy_path, appliance_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Report date in YYYY-MM-DD format")
    args = parser.parse_args()
    try:
        report_date = date.fromisoformat(args.date)
        paths = create_archives(report_date)
    except (OSError, ValueError) as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1
    print("OK: created {} and {}".format(paths[0].relative_to(ROOT), paths[1].relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
