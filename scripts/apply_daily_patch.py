#!/usr/bin/env python3
"""Validate the cloud agent's patch boundary before applying it."""

import argparse
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


DIFF_HEADER = re.compile(r"^diff --git a/([^\n]+) b/([^\n]+)$", re.MULTILINE)
FORBIDDEN_HEADERS = (
    "deleted file mode ",
    "old mode ",
    "new mode ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
    "GIT binary patch",
    "Binary files ",
)
ROOT = Path(__file__).resolve().parents[1]
ASSET_BLOCK = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
ACTIVE_HTML = re.compile(
    r"<\s*(script|iframe|object|embed|form|base)\b|"
    r"\son[a-z]+\s*=|javascript\s*:",
    re.IGNORECASE,
)


def expected_paths(report_date):
    return {
        "index.html",
        "appliance-trends/index.html",
    }


def extract_patch(raw):
    text = raw.replace("\r\n", "\n").strip()
    if text.startswith("```diff\n") and text.endswith("\n```"):
        text = text[len("```diff\n") : -len("\n```")].strip()
    if not text.startswith("diff --git "):
        raise ValueError("agent did not return a raw unified patch")
    return text + "\n"


def validate_patch(patch, report_date):
    if "\x00" in patch:
        raise ValueError("patch contains a NUL byte")
    if any(marker in patch for marker in FORBIDDEN_HEADERS):
        raise ValueError("patch contains a forbidden file operation")

    headers = DIFF_HEADER.findall(patch)
    if not headers:
        raise ValueError("patch has no diff headers")

    paths = []
    for old_path, new_path in headers:
        if old_path != new_path:
            raise ValueError("renames are not allowed: {} -> {}".format(old_path, new_path))
        if old_path.startswith("/") or "\\" in old_path or ".." in old_path.split("/"):
            raise ValueError("unsafe patch path: {}".format(old_path))
        paths.append(old_path)

    if len(paths) != len(set(paths)):
        raise ValueError("patch contains duplicate file sections")

    expected = expected_paths(report_date)
    actual = set(paths)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing: {}".format(", ".join(missing)))
        if extra:
            details.append("not allowed: {}".format(", ".join(extra)))
        raise ValueError("patch file boundary mismatch ({})".format("; ".join(details)))


def asset_blocks(html):
    return [match.group(0) for match in ASSET_BLOCK.finditer(html)]


def validate_html_safety(old_home, new_home, archive, label):
    if asset_blocks(old_home) != asset_blocks(new_home):
        raise ValueError("{} changes CSS or script blocks".format(label))
    if asset_blocks(new_home) != asset_blocks(archive):
        raise ValueError("{} archive does not preserve the homepage assets".format(label))
    for page_name, html in (("homepage", new_home), ("archive", archive)):
        match = ACTIVE_HTML.search(html)
        if match:
            raise ValueError(
                "{} {} contains forbidden active HTML: {}".format(
                    label, page_name, match.group(0)
                )
            )


def read_head(path):
    result = subprocess.run(
        ("git", "show", "HEAD:{}".format(path)),
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise ValueError("cannot read trusted HEAD version of {}".format(path))
    return result.stdout


def validate_applied_html(report_date):
    stamp = report_date.strftime("%Y%m%d")
    pairs = (
        ("index.html", "daily/{}.html".format(stamp), "policy report"),
        (
            "appliance-trends/index.html",
            "appliance-trends/daily/{}.html".format(stamp),
            "appliance report",
        ),
    )
    for home_path, archive_path, label in pairs:
        old_home = read_head(home_path)
        new_home = (ROOT / home_path).read_text(encoding="utf-8")
        archive = (ROOT / archive_path).read_text(encoding="utf-8")
        validate_html_safety(old_home, new_home, archive, label)


def run_git_apply(patch, report_date):
    for args in (("git", "apply", "--check", "--whitespace=error-all", "-"), ("git", "apply", "--whitespace=error-all", "-")):
        result = subprocess.run(
            args,
            input=patch,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode:
            message = result.stderr.strip() or result.stdout.strip()
            raise ValueError("{} failed: {}".format(" ".join(args[:-1]), message))

    archive_result = subprocess.run(
        (
            sys.executable,
            str(ROOT / "scripts" / "create_daily_archives.py"),
            "--date",
            report_date.isoformat(),
        ),
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if archive_result.returncode:
        message = archive_result.stderr.strip() or archive_result.stdout.strip()
        raise ValueError("archive generation failed: {}".format(message))
    validate_applied_html(report_date)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Report date in YYYY-MM-DD format")
    parser.add_argument("--env", required=True, help="Environment variable containing the patch")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    try:
        report_date = date.fromisoformat(args.date)
        raw_patch = os.environ.get(args.env, "")
        patch = extract_patch(raw_patch)
        validate_patch(patch, report_date)
        if not args.validate_only:
            run_git_apply(patch, report_date)
    except (OSError, ValueError) as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1

    action = "validated" if args.validate_only else "validated and applied"
    print("OK: cloud patch {} for {}".format(action, report_date.isoformat()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
