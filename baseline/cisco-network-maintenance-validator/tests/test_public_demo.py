from __future__ import annotations

import unittest
from pathlib import Path

from network_prepost_check.report_builder import render_html_report

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PublicReportTests(unittest.TestCase):
    def test_template_uses_public_teal_palette(self) -> None:
        template = (PROJECT_ROOT / "reports" / "prepost_report.html.j2").read_text(encoding="utf-8")
        self.assertIn("--teal: #0F766E", template)
        self.assertIn("--teal-dark: #134E4A", template)
        self.assertNotIn("red-cross", template.lower())

    def test_template_escapes_report_values(self) -> None:
        report = {
            "hostname": "<script>alert(1)</script>",
            "connection_target": "192.0.2.10",
            "device_type": "switch",
            "report_generated_at": "2026-08-14 10:00:00 AEST",
            "delay_minutes": 50,
            "precheck_file": "samples/pre.json",
            "postcheck_file": "samples/post.json",
            "summary": {
                "overall_status": "ok",
                "total_checks": 0,
                "ok_count": 0,
                "expected_count": 0,
                "warning_count": 0,
                "critical_count": 0,
            },
            "results": [],
            "diff_details": [],
        }
        html = render_html_report(
            report,
            PROJECT_ROOT / "reports" / "prepost_report.html.j2",
        )
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)


if __name__ == "__main__":
    unittest.main()
