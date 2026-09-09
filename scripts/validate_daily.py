#!/usr/bin/env python3
"""Validate the two daily static reports before publishing."""

import argparse
import re
import sys
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


class DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.fragment_links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        href = values.get("href", "")
        if href.startswith("#") and len(href) > 1:
            self.fragment_links.append(href[1:])


def read(path):
    if not path.exists():
        raise ValueError("缺少文件: {}".format(path.relative_to(ROOT)))
    return path.read_text(encoding="utf-8")


def section(html, section_id):
    escaped = re.escape(section_id)
    match = re.search(
        r'<section\b[^>]*\bid=["\']{}["\'][^>]*>(.*?)(?=<section\b[^>]*\bid=["\']|<footer\b|</main>)'.format(escaped),
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        match = re.search(
            r'<div\b[^>]*class=["\'][^"\']*section-block[^"\']*["\'][^>]*\bid=["\']{}["\'][^>]*>(.*?)(?=<div\b[^>]*class=["\'][^"\']*section-block|<footer\b|</main>)'.format(escaped),
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    if not match:
        raise ValueError("缺少栏目 #{}".format(section_id))
    return match.group(1)


def nav_count(html, section_id):
    match = re.search(
        r'<a\b[^>]*href=["\']#{}["\'][^>]*>.*?<span\b[^>]*class=["\'][^"\']*nav-count[^"\']*["\'][^>]*>\s*(\d+)'.format(
            re.escape(section_id)
        ),
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise ValueError("缺少 #{} 的侧栏计数".format(section_id))
    return int(match.group(1))


def stat_count(html, css_class):
    match = re.search(
        r'class=["\'][^"\']*stat-chip\s+{}[^"\']*["\'][^>]*>\s*<span\b[^>]*class=["\']stat-num["\'][^>]*>\s*(\d+)'.format(
            re.escape(css_class)
        ),
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise ValueError("缺少统计卡 .{}".format(css_class))
    return int(match.group(1))


def validate_common(path, html, target_date, required_ids, errors):
    display_date = "{}年{}月{}日".format(target_date.year, target_date.month, target_date.day)
    weekday = WEEKDAYS[target_date.weekday()]
    if display_date not in html:
        errors.append("{}: 未显示 {}".format(path, display_date))
    short_weekday = weekday.replace("星期", "周")
    if weekday not in html and short_weekday not in html:
        errors.append("{}: 星期应为 {} 或 {}".format(path, weekday, short_weekday))
    for token in (".archive-title {{", "section-blo    <", "<<<<<<<", ">>>>>>>"):
        if token in html:
            errors.append("{}: 发现损坏标记 {!r}".format(path, token))

    parser = DocumentParser()
    try:
        parser.feed(html)
    except Exception as exc:
        errors.append("{}: HTML 解析失败: {}".format(path, exc))
        return
    missing = set(required_ids) - parser.ids
    if missing:
        errors.append("{}: 缺少 id {}".format(path, ", ".join(sorted(missing))))
    broken = sorted(set(parser.fragment_links) - parser.ids)
    if broken:
        errors.append("{}: 站内锚点无目标 {}".format(path, ", ".join(broken)))


def validate_policy(html, errors):
    expected = {
        "executive-summary": len(re.findall(r"<li\b", section(html, "executive-summary"), re.I)),
        "platform": len(re.findall(r'class=["\'][^"\']*policy-card[^"\']*["\']', section(html, "platform"), re.I)),
        "compliance-tax": len(re.findall(r'class=["\'][^"\']*policy-card[^"\']*["\']', section(html, "compliance-tax"), re.I)),
        "logistics": len(re.findall(r'class=["\'][^"\']*policy-card[^"\']*["\']', section(html, "logistics"), re.I)),
        "timeline": len(re.findall(r'class=["\'][^"\']*timeline-item[^"\']*["\']', section(html, "timeline"), re.I)),
    }
    expected["compliance"] = expected["executive-summary"]
    for section_id, actual in expected.items():
        try:
            shown = nav_count(html, section_id)
        except ValueError as exc:
            errors.append("index.html: {}".format(exc))
            continue
        if shown != actual:
            errors.append("index.html: #{} 侧栏计数 {}，实际 {}".format(section_id, shown, actual))

    severity = {
        "danger": len(re.findall(r'class=["\'][^"\']*severity-badge\s+danger[^"\']*["\']', html, re.I)),
        "warn": len(re.findall(r'class=["\'][^"\']*severity-badge\s+warning[^"\']*["\']', html, re.I)),
        "info": len(re.findall(r'class=["\'][^"\']*severity-badge\s+info[^"\']*["\']', html, re.I)),
    }
    for css_class, actual in severity.items():
        try:
            shown = stat_count(html, css_class)
        except ValueError as exc:
            errors.append("index.html: {}".format(exc))
            continue
        if shown != actual:
            errors.append("index.html: .{} 统计 {}，实际 {}".format(css_class, shown, actual))


def validate_appliance(html, errors):
    opportunities = len(re.findall(r'class=["\'][^"\']*opportunity-card[^"\']*["\']', section(html, "quick-report"), re.I))
    rows = len(re.findall(r"<tr\b", re.search(r"<tbody\b[^>]*>(.*?)</tbody>", section(html, "detail-analysis"), re.I | re.S).group(1), re.I))
    watches = len(re.findall(r'class=["\'][^"\']*watch-item[^"\']*["\']', section(html, "watchlist"), re.I))
    for section_id, actual in (("quick-report", opportunities), ("detail-analysis", rows), ("watchlist", watches)):
        try:
            shown = nav_count(html, section_id)
        except ValueError as exc:
            errors.append("appliance-trends/index.html: {}".format(exc))
            continue
        if shown != actual:
            errors.append("appliance-trends/index.html: #{} 侧栏计数 {}，实际 {}".format(section_id, shown, actual))
    try:
        tracked = stat_count(html, "hot")
        if tracked != rows:
            errors.append("appliance-trends/index.html: 追踪机会点 {}，表格实际 {}".format(tracked, rows))
    except ValueError as exc:
        errors.append("appliance-trends/index.html: {}".format(exc))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Expected report date in YYYY-MM-DD format")
    args = parser.parse_args()
    target_date = date.fromisoformat(args.date) if args.date else datetime.now().astimezone().date()
    stamp = target_date.strftime("%Y%m%d")
    errors = []

    targets = (
        ("index.html", ROOT / "index.html", ("executive-summary", "compliance", "platform", "compliance-tax", "logistics", "timeline", "sources")),
        ("daily/{}.html".format(stamp), ROOT / "daily" / "{}.html".format(stamp), ("executive-summary", "compliance", "platform", "compliance-tax", "logistics", "timeline", "sources")),
        ("appliance-trends/index.html", ROOT / "appliance-trends" / "index.html", ("quick-report", "detail-analysis", "watchlist")),
        ("appliance-trends/daily/{}.html".format(stamp), ROOT / "appliance-trends" / "daily" / "{}.html".format(stamp), ("quick-report", "detail-analysis")),
    )

    contents = {}
    for label, path, required_ids in targets:
        try:
            html = read(path)
            contents[label] = html
            validate_common(label, html, target_date, required_ids, errors)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))

    if "index.html" in contents:
        try:
            validate_policy(contents["index.html"], errors)
        except (AttributeError, ValueError) as exc:
            errors.append("index.html: {}".format(exc))
    if "appliance-trends/index.html" in contents:
        try:
            validate_appliance(contents["appliance-trends/index.html"], errors)
        except (AttributeError, ValueError) as exc:
            errors.append("appliance-trends/index.html: {}".format(exc))

    if errors:
        for error in errors:
            print("ERROR: {}".format(error))
        return 1
    print("OK: {} 两份日报及归档通过校验".format(target_date.isoformat()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
