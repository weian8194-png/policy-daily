#!/usr/bin/env python3
"""Prepare transparent dated homepages when the research gateway is unavailable."""

import argparse
import re
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def replace_once(text, pattern, replacement, label, flags=0):
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise ValueError("cannot locate exactly one {}".format(label))
    return updated


def update_policy(html, report_date):
    display = "{}年{}月{}日".format(report_date.year, report_date.month, report_date.day)
    weekday = WEEKDAYS[report_date.weekday()]
    html = replace_once(
        html,
        r"<title>跨境政策日报 · \d{4}年\d{1,2}月\d{1,2}日（星期.）</title>",
        "<title>跨境政策日报 · {}（{}）</title>".format(display, weekday),
        "policy title",
    )
    html = replace_once(
        html, r'<div class="date">\d{4}年\d{1,2}月\d{1,2}日</div>',
        '<div class="date">{}</div>'.format(display), "policy sidebar date"
    )
    html = replace_once(
        html, r'<div class="weekday">星期.</div>',
        '<div class="weekday">{}</div>'.format(weekday), "policy weekday"
    )
    html = replace_once(
        html, r'<span class="date-val">\d{4}年\d{1,2}月\d{1,2}日（星期.）</span>',
        '<span class="date-val">{}（{}）</span>'.format(display, weekday),
        "policy header date",
    )
    html = replace_once(
        html, r'<span class="update-time">.*?</span>',
        '<span class="update-time">云端保底 07:00</span>', "policy update time"
    )
    html = replace_once(
        html,
        r'<li><span class="date-tag">今日</span>.*?</li>',
        '<li><span class="date-tag">今日</span> 自动联网研究未在时限内完成；以下事项沿用最近一次核验，未计为今日新增</li>',
        "policy fallback notice",
    )
    html = replace_once(
        html,
        r'<p>更新时间：\d{4}年\d{1,2}月\d{1,2}日 .*?</p>',
        '<p>更新时间：{} 07:00 · 云端保底（34个信息源配置）</p>'.format(display),
        "policy footer date",
    )
    return html


def add_appliance_archive_link(html, report_date):
    stamp = report_date.strftime("%Y%m%d")
    if 'href="./daily/{}.html"'.format(stamp) in html:
        return html

    iso_date = report_date.isoformat()
    weekday = WEEKDAYS[report_date.weekday()].replace("星期", "周")
    table_body = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", html, re.IGNORECASE | re.DOTALL)
    if not table_body:
        raise ValueError("cannot locate appliance tracking table")
    tracked = len(re.findall(r"<tr\b", table_body.group(1), re.IGNORECASE))
    link = (
        '          <a class="archive-day" href="./daily/{}.html">{}（{}）'
        '<span class="day-count">{}个</span></a>\n'
    ).format(stamp, iso_date, weekday, tracked)

    month_label = "{}年{:02d}月".format(report_date.year, report_date.month)
    month_pattern = re.compile(
        r'<details class="archive-month"[^>]*>\s*<summary><span class="month-info">'
        + re.escape(month_label)
        + r'</span><span class="month-stats">\d+天</span></summary>.*?</details>',
        re.DOTALL,
    )
    month = month_pattern.search(html)
    if month:
        block = month.group(0)
        days = len(re.findall(r'href="\./daily/{}\d{{2}}\.html"'.format(report_date.strftime("%Y%m")), block)) + 1
        block = re.sub(r'<span class="month-stats">\d+天</span>',
                       '<span class="month-stats">{}天</span>'.format(days), block, count=1)
        block = block.replace("</summary>\n", "</summary>\n" + link, 1)
        return html[:month.start()] + block + html[month.end():]

    marker = '<div class="archive-section-title">📅 历史归档</div>\n'
    if html.count(marker) != 1:
        raise ValueError("cannot locate appliance archive section")
    block = (
        '        <details class="archive-month" open>\n'
        '          <summary><span class="month-info">{}</span>'
        '<span class="month-stats">1天</span></summary>\n'
        '{}'
        '        </details>\n'
    ).format(month_label, link)
    return html.replace(marker, marker + block, 1)


def update_appliance(html, report_date):
    display = "{}年{}月{}日".format(report_date.year, report_date.month, report_date.day)
    weekday = WEEKDAYS[report_date.weekday()]
    html = replace_once(
        html, r'<span class="date-val">\d{4}年\d{1,2}月\d{1,2}日（星期.）</span>',
        '<span class="date-val">{}（{}）</span>'.format(display, weekday),
        "appliance header date",
    )
    html = replace_once(
        html, r'<span class="update-time">.*?</span>',
        '<span class="update-time">云端保底 07:00</span>', "appliance update time"
    )
    html = replace_once(
        html,
        r'<div class="hl-text">.*?</div>',
        '<div class="hl-text"><strong>自动联网研究未在时限内完成</strong>——今日未发布未经核验的新机会；历史机会继续按最近一次核验状态展示。</div>',
        "appliance fallback notice",
        flags=re.DOTALL,
    )
    quick_report_pattern = re.compile(
        r'(<div class="section-block" id="quick-report">.*?'
        r'<div class="watch-text">)(.*?)(</div>)',
        re.DOTALL,
    )
    html = replace_once(
        html, quick_report_pattern,
        r'\1自动联网研究未完成；无经核验新增，继续展示既有品类。\3',
        "appliance quick report",
    )
    return add_appliance_archive_link(html, report_date)


def prepare_fallback(report_date, root=ROOT):
    stamp = report_date.strftime("%Y%m%d")
    policy_path = root / "index.html"
    appliance_path = root / "appliance-trends" / "index.html"
    policy_archive = root / "daily" / "{}.html".format(stamp)
    appliance_archive = root / "appliance-trends" / "daily" / "{}.html".format(stamp)

    policy = policy_path.read_text(encoding="utf-8")
    appliance = appliance_path.read_text(encoding="utf-8")
    display = "{}年{}月{}日".format(report_date.year, report_date.month, report_date.day)
    if policy_archive.exists() and appliance_archive.exists() and display in policy and display in appliance:
        return False

    policy_path.write_text(update_policy(policy, report_date), encoding="utf-8")
    appliance_path.write_text(update_appliance(appliance, report_date), encoding="utf-8")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Report date in YYYY-MM-DD format")
    args = parser.parse_args()
    try:
        report_date = date.fromisoformat(args.date)
        changed = prepare_fallback(report_date)
    except (OSError, ValueError) as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1
    print("OK: {} fallback for {}".format("prepared" if changed else "already present", report_date))
    return 0


if __name__ == "__main__":
    sys.exit(main())
