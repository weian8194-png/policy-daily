#!/usr/bin/env python3
"""Wait for GitHub Pages to serve both reports and their daily archives."""

import argparse
import sys
import time
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def report_urls(base_url, report_date):
    stamp = report_date.strftime("%Y%m%d")
    root = base_url.rstrip("/") + "/"
    return (
        root,
        urljoin(root, "daily/{}.html".format(stamp)),
        urljoin(root, "appliance-trends/"),
        urljoin(root, "appliance-trends/daily/{}.html".format(stamp)),
    )


def display_marker(report_date):
    return "{}年{}月{}日".format(report_date.year, report_date.month, report_date.day)


def fetch(url, timeout):
    request = Request(url, headers={"User-Agent": "policy-daily-deploy-check/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("HTTP {}".format(response.status))
        return response.read().decode("utf-8", errors="replace")


def check_once(urls, marker, timeout):
    failures = []
    for url in urls:
        try:
            body = fetch(url, timeout)
            if marker not in body:
                failures.append("{} does not show {}".format(url, marker))
        except (HTTPError, URLError, OSError, ValueError) as exc:
            failures.append("{}: {}".format(url, exc))
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Report date in YYYY-MM-DD format")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--attempts", type=int, default=20)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()

    try:
        report_date = date.fromisoformat(args.date)
        if args.attempts < 1 or args.interval < 0 or args.timeout <= 0:
            raise ValueError("attempts and timeouts must be positive")
    except ValueError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 2

    urls = report_urls(args.base_url, report_date)
    marker = display_marker(report_date)
    for attempt in range(1, args.attempts + 1):
        failures = check_once(urls, marker, args.timeout)
        if not failures:
            print("OK: GitHub Pages serves all four reports for {}".format(args.date))
            return 0
        print("Attempt {}/{}: {}".format(attempt, args.attempts, "; ".join(failures)))
        if attempt < args.attempts:
            time.sleep(args.interval)

    print("ERROR: GitHub Pages did not publish all reports in time", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
