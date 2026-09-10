import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "apply_daily_patch", ROOT / "scripts" / "apply_daily_patch.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

VERIFY_SPEC = importlib.util.spec_from_file_location(
    "verify_pages", ROOT / "scripts" / "verify_pages.py"
)
VERIFY_MODULE = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY_MODULE)

ARCHIVE_SPEC = importlib.util.spec_from_file_location(
    "create_daily_archives", ROOT / "scripts" / "create_daily_archives.py"
)
ARCHIVE_MODULE = importlib.util.module_from_spec(ARCHIVE_SPEC)
ARCHIVE_SPEC.loader.exec_module(ARCHIVE_MODULE)

FALLBACK_SPEC = importlib.util.spec_from_file_location(
    "prepare_daily_fallback", ROOT / "scripts" / "prepare_daily_fallback.py"
)
FALLBACK_MODULE = importlib.util.module_from_spec(FALLBACK_SPEC)
FALLBACK_SPEC.loader.exec_module(FALLBACK_MODULE)


def patch_for(paths):
    sections = []
    for path in paths:
        sections.append(
            "diff --git a/{0} b/{0}\n"
            "--- a/{0}\n"
            "+++ b/{0}\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n".format(path)
        )
    return "".join(sections)


class DailyPatchValidationTests(unittest.TestCase):
    def setUp(self):
        self.report_date = date(2026, 9, 10)
        self.paths = MODULE.expected_paths(self.report_date)

    def test_accepts_exact_daily_file_boundary(self):
        MODULE.validate_patch(patch_for(sorted(self.paths)), self.report_date)

    def test_accepts_diff_markdown_fence_from_model(self):
        raw = "```diff\n{}\n```".format(patch_for(sorted(self.paths)).rstrip())
        extracted = MODULE.extract_patch(raw)
        MODULE.validate_patch(extracted, self.report_date)

    def test_rejects_extra_file(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            MODULE.validate_patch(
                patch_for(sorted(self.paths | {".github/workflows/daily-update.yml"})),
                self.report_date,
            )

    def test_rejects_missing_archive(self):
        paths = self.paths - {"index.html"}
        with self.assertRaisesRegex(ValueError, "missing"):
            MODULE.validate_patch(patch_for(sorted(paths)), self.report_date)

    def test_rejects_rename_and_mode_changes(self):
        unsafe = patch_for(sorted(self.paths)) + "new mode 100755\n"
        with self.assertRaisesRegex(ValueError, "forbidden"):
            MODULE.validate_patch(unsafe, self.report_date)

    def test_rejects_css_changes(self):
        old_home = "<style>body { color: black; }</style><p>old</p>"
        new_home = "<style>body { color: red; }</style><p>new</p>"
        with self.assertRaisesRegex(ValueError, "CSS or script"):
            MODULE.validate_html_safety(old_home, new_home, new_home, "report")

    def test_rejects_active_html(self):
        old_home = "<style>body { color: black; }</style><p>old</p>"
        new_home = "<style>body { color: black; }</style><p onclick='x()'>new</p>"
        with self.assertRaisesRegex(ValueError, "active HTML"):
            MODULE.validate_html_safety(old_home, new_home, new_home, "report")

    def test_accepts_content_only_html_changes(self):
        old_home = "<style>body { color: black; }</style><p>old</p>"
        new_home = "<style>body { color: black; }</style><p>new</p>"
        MODULE.validate_html_safety(old_home, new_home, new_home, "report")


class PageVerificationTests(unittest.TestCase):
    def test_builds_all_four_urls(self):
        urls = VERIFY_MODULE.report_urls(
            "https://example.test/policy-daily", date(2026, 9, 10)
        )
        self.assertEqual(
            urls,
            (
                "https://example.test/policy-daily/",
                "https://example.test/policy-daily/daily/20260910.html",
                "https://example.test/policy-daily/appliance-trends/",
                "https://example.test/policy-daily/appliance-trends/daily/20260910.html",
            ),
        )

    def test_formats_unpadded_chinese_date(self):
        self.assertEqual(
            VERIFY_MODULE.display_marker(date(2026, 9, 10)), "2026年9月10日"
        )


class ArchiveCreationTests(unittest.TestCase):
    def test_creates_policy_copy_and_repairs_appliance_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "appliance-trends").mkdir()
            (root / "index.html").write_text("<p>policy</p>", encoding="utf-8")
            (root / "appliance-trends" / "index.html").write_text(
                '<a href="./daily/20260909.html">previous</a>', encoding="utf-8"
            )

            policy_path, appliance_path = ARCHIVE_MODULE.create_archives(
                date(2026, 9, 10), root
            )

            self.assertEqual(policy_path.read_text(encoding="utf-8"), "<p>policy</p>")
            self.assertEqual(
                appliance_path.read_text(encoding="utf-8"),
                '<a href="./20260909.html">previous</a>',
            )


class DailyFallbackTests(unittest.TestCase):
    def test_prepares_new_date_and_is_idempotent_after_archiving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "appliance-trends").mkdir()
            (root / "index.html").write_text(
                (ROOT / "index.html").read_text(encoding="utf-8"), encoding="utf-8"
            )
            (root / "appliance-trends" / "index.html").write_text(
                (ROOT / "appliance-trends" / "index.html").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            report_date = date(2026, 9, 11)
            self.assertTrue(FALLBACK_MODULE.prepare_fallback(report_date, root))
            policy = (root / "index.html").read_text(encoding="utf-8")
            appliance = (root / "appliance-trends" / "index.html").read_text(
                encoding="utf-8"
            )

            self.assertIn("2026年9月11日（星期五）", policy)
            self.assertIn("自动联网研究未在时限内完成", policy)
            self.assertIn("2026年9月11日（星期五）", appliance)
            self.assertIn("自动联网研究未在时限内完成", appliance)
            self.assertIn('href="./daily/20260911.html"', appliance)
            self.assertIn('<span class="month-stats">11天</span>', appliance)

            ARCHIVE_MODULE.create_archives(report_date, root)
            self.assertFalse(FALLBACK_MODULE.prepare_fallback(report_date, root))

    def test_rejects_unrecognised_page_structure(self):
        with self.assertRaisesRegex(ValueError, "policy title"):
            FALLBACK_MODULE.update_policy("<html></html>", date(2026, 9, 11))


if __name__ == "__main__":
    unittest.main()
