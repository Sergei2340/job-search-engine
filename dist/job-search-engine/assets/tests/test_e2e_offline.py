"""Offline end-to-end smoke test: full Phase 1 run() against a temp profile
with a stubbed source — no network. Verifies the wiring: profile state
loading (incl. resilient seen_urls parse + canonical-URL dedup), filters,
fair cap, candidates.json and last_run_report.json output shapes.

Run:  python -m tests.test_e2e_offline
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine.main as engine_main  # noqa: E402
from engine.profile import Profile  # noqa: E402
from engine.relevance import RelevanceGate  # noqa: E402
from engine.sources import Posting  # noqa: E402

NOW = datetime.now(timezone.utc)


def _gate() -> RelevanceGate:
    return RelevanceGate.from_config({
        "allow_titles": [r"\bpython\b"],
        "default_reason": "no python signal",
    })


def _profile(tmp: Path) -> Profile:
    return Profile(
        dept="testdept",
        display_name="Test Dept",
        id_prefix="TST",
        sheet={"spreadsheet_id": "fake", "tab": "Sheet1"},
        profile_dir=tmp,
        gate=_gate(),
        sources={"fake": {"enabled": True}},
        candidate_cap=3,
    )


def _fake_postings() -> list[Posting]:
    fresh = NOW - timedelta(hours=1)
    return [
        Posting(title="Python Developer", company="Acme", board="FakeBoard",
                location="Remote", remote_type="Remote", salary="Not listed",
                link="https://jobs.example.com/python-dev-1", date_posted=fresh),
        # duplicate URL (encoding variant) of the first
        Posting(title="Python Developer", company="Acme", board="FakeBoard",
                location="Remote", remote_type="Remote", salary="Not listed",
                link="https://jobs.example.com/python%2Ddev%2D1", date_posted=fresh),
        # role duplicate: same company + noise-stripped title, new URL
        Posting(title="Python Developer (Remote)", company="Acme", board="FakeBoard",
                location="Berlin", remote_type="Remote", salary="Not listed",
                link="https://jobs.example.com/python-dev-2", date_posted=fresh),
        # already seen in a prior run (in seen_urls.json)
        Posting(title="Senior Python Engineer", company="Beta", board="FakeBoard",
                location="Remote", remote_type="Remote", salary="Not listed",
                link="https://jobs.example.com/seen-before", date_posted=fresh),
        # too old
        Posting(title="Python Backend Engineer", company="Gamma", board="FakeBoard",
                location="Remote", remote_type="Remote", salary="Not listed",
                link="https://jobs.example.com/old-1", date_posted=NOW - timedelta(days=3)),
        # search-page link -> no_link
        Posting(title="Python Guru", company="Delta", board="FakeBoard",
                location="Remote", remote_type="Remote", salary="Not listed",
                link="https://jobs.example.com/", date_posted=fresh),
        # fine
        Posting(title="Python Team Lead", company="Epsilon", board="FakeBoard",
                location="Remote", remote_type="Remote", salary="Not listed",
                link="https://jobs.example.com/lead-1", date_posted=fresh),
    ]


class EndToEndOffline(unittest.TestCase):
    def test_full_run(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile = _profile(tmp)
            # Pre-seed state: seen_urls with slug-form corruption (two glued
            # arrays) to exercise the resilient loader, incl. one URL the fake
            # source re-surfaces today.
            profile.state_dir.mkdir(parents=True)
            profile.seen_urls_file.write_text(
                '["https://jobs.example.com/seen-before"]\n'
                '["https://other.example.com/x1"]'
            )

            original = engine_main.SOURCE_REGISTRY
            engine_main.SOURCE_REGISTRY = {"fake": lambda p: _fake_postings()}
            try:
                report = engine_main.run(profile)
            finally:
                engine_main.SOURCE_REGISTRY = original

            # Filter accounting
            self.assertEqual(report["dept"], "testdept")
            self.assertEqual(report["source_counts"], {"fake": 7})
            fc = report["filter_counts"]
            # encoding variant (intra-run) + seen-before (cross-run seen_urls)
            self.assertEqual(fc["duplicate"], 2)
            self.assertEqual(fc["duplicate_role"], 1)   # Acme repost
            self.assertEqual(fc["too_old"], 1)
            self.assertEqual(fc["no_link"], 1)
            self.assertEqual(report["candidate_count"], 2)  # dev-1 + lead-1
            self.assertFalse(report["capped"])

            candidates = json.loads(profile.candidates_file.read_text())
            self.assertEqual(len(candidates), 2)
            links = {c["link"] for c in candidates}
            self.assertIn("https://jobs.example.com/python-dev-1", links)
            self.assertIn("https://jobs.example.com/lead-1", links)
            for c in candidates:
                for key in ("id", "board", "link", "title_guess", "company_guess",
                            "date_found_iso", "date_posted_iso", "raw_type",
                            "raw_content", "company_size", "date_suspect"):
                    self.assertIn(key, c)
                # No company_url on the fake postings -> enrichment leaves null.
                self.assertIsNone(c["company_size"])

            # Enrichment ran (and self-skipped: no enrichment block in profile).
            self.assertIn("company_enrichment", report)

            saved_report = json.loads(profile.report_file.read_text())
            self.assertEqual(saved_report["candidate_count"], 2)

    def test_fair_cap_applies(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile = _profile(tmp)  # cap = 3
            fresh = NOW - timedelta(hours=1)
            many = [Posting(title=f"Python Dev {i}", company=f"Co{i}", board="A" if i % 2 else "B",
                            location="Remote", remote_type="Remote", salary="Not listed",
                            link=f"https://jobs.example.com/{i}", date_posted=fresh)
                    for i in range(10)]
            original = engine_main.SOURCE_REGISTRY
            engine_main.SOURCE_REGISTRY = {"fake": lambda p: many}
            try:
                report = engine_main.run(profile)
            finally:
                engine_main.SOURCE_REGISTRY = original
            self.assertTrue(report["capped"])
            self.assertEqual(report["candidate_count"], 3)
            # fairness: both boards represented in the cap
            boards = {c["board"] for c in json.loads(profile.candidates_file.read_text())}
            self.assertEqual(boards, {"A", "B"})

    def test_duplicate_seen_urls_counted(self):
        """The seen-before URL must land in `duplicate`, sanity-checking the
        canonicalized state load path."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            profile = _profile(tmp)
            profile.state_dir.mkdir(parents=True)
            profile.seen_urls_file.write_text(json.dumps(
                ["https://jobs.example.com/seen-before"]))
            fresh = NOW - timedelta(hours=1)
            postings = [Posting(title="Python Dev", company="Beta", board="X",
                                location="Remote", remote_type="Remote",
                                salary="Not listed",
                                link="https://jobs.example.com/seen-before",
                                date_posted=fresh)]
            original = engine_main.SOURCE_REGISTRY
            engine_main.SOURCE_REGISTRY = {"fake": lambda p: postings}
            try:
                report = engine_main.run(profile)
            finally:
                engine_main.SOURCE_REGISTRY = original
            self.assertEqual(report["filter_counts"]["duplicate"], 1)
            self.assertEqual(report["candidate_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
