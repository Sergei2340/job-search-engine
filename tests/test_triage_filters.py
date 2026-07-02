"""Engine filter tests — ported from pipeline/tests/test_triage_filters.py
(2026-07-02) to the parameterized apply_filters signature:

- blocked_domains (paywall/dead-link resources)
- unreliable-date domains -> date_posted=None + date_suspect=True
- role dedup by (company + noise-stripped title), location ignored

Run:  python -m tests.test_triage_filters
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.main import apply_filters, _title_key, load_blocked_domains  # noqa: E402
from engine.profile import TITLE_NOISE_TOKENS, UNRELIABLE_DATE_DOMAINS  # noqa: E402
from engine.sources import Posting  # noqa: E402

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)
FRESH = NOW - timedelta(hours=2)
STALE = NOW - timedelta(days=40)


def make(link: str, title: str = "UI/UX Designer", company: str = "Acme",
         location: str = "Remote", date_posted: datetime | None = FRESH) -> Posting:
    return Posting(
        title=title, company=company, board="GoogleJobs", location=location,
        remote_type="Remote", salary="Not listed", link=link,
        date_posted=date_posted,
    )


def filters(postings, seen_urls, now, max_age, role_seen=None, blocked=None):
    """apply_filters with the engine defaults a profile would carry."""
    return apply_filters(
        postings, seen_urls, now, max_age, role_seen, blocked,
        excluded_companies=frozenset(),
        unreliable_date_domains=UNRELIABLE_DATE_DOMAINS,
        title_noise_tokens=TITLE_NOISE_TOKENS,
        role_seen_window_days=30,
    )


def tkey(title: str) -> str:
    return _title_key(title, TITLE_NOISE_TOKENS)


class BlockedDomainTest(unittest.TestCase):
    BLOCKED = {"paywalled.example": "paywall", "deadlinks.example": "dead links"}

    def _run(self, link: str) -> tuple[int, int]:
        kept, counts = filters([make(link)], set(), NOW, 24, None, self.BLOCKED)
        return len(kept), counts["blocked_domain"]

    def test_blocked_domain_dropped(self):
        self.assertEqual(self._run("https://paywalled.example/jobs/x-remote"), (0, 1))

    def test_subdomain_matches(self):
        self.assertEqual(self._run("https://www.paywalled.example/jobs/x"), (0, 1))

    def test_unrelated_domain_passes(self):
        self.assertEqual(self._run("https://boards.greenhouse.io/acme/jobs/1"), (1, 0))

    def test_no_false_suffix_match(self):
        # mypaywalled.example is NOT paywalled.example
        self.assertEqual(self._run("https://mypaywalled.example/jobs/x"), (1, 0))

    def test_loader_skips_comment_keys(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"_comment": "curated blocklist", "paywalled.example": "paywall"}, fh)
        domains = load_blocked_domains(Path(fh.name))
        self.assertIn("paywalled.example", domains)
        self.assertFalse(any(k.startswith("_") for k in domains))


class UnreliableDateTest(unittest.TestCase):
    def test_aggregator_stale_date_not_dropped_but_flagged(self):
        p = make("https://bebee.com/us/jobs/sr-ux-designer-1", date_posted=STALE)
        kept, counts = filters([p], set(), NOW, 24)
        self.assertEqual(len(kept), 1)
        self.assertEqual(counts["too_old"], 0)
        self.assertTrue(kept[0].date_suspect)
        self.assertIsNone(kept[0].date_posted)
        self.assertTrue(kept[0].to_candidate(NOW)["date_suspect"])

    def test_aggregator_subdomain(self):
        p = make("https://talents.studysmarter.co.uk/companies/x/job-1", date_posted=STALE)
        kept, _ = filters([p], set(), NOW, 24)
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0].date_suspect)

    def test_normal_domain_still_age_filtered(self):
        p = make("https://boards.greenhouse.io/acme/jobs/2", date_posted=STALE)
        kept, counts = filters([p], set(), NOW, 24)
        self.assertEqual(len(kept), 0)
        self.assertEqual(counts["too_old"], 1)

    def test_normal_fresh_not_flagged(self):
        p = make("https://boards.greenhouse.io/acme/jobs/3")
        kept, _ = filters([p], set(), NOW, 24)
        self.assertFalse(kept[0].date_suspect)


class TitleKeyTest(unittest.TestCase):
    def test_noise_stripped(self):
        self.assertEqual(tkey("Remote UI Designer – Freelance Role"), "ui designer")
        self.assertEqual(tkey("UI Designer (Remote)"), "ui designer")
        self.assertEqual(tkey("UI/UX Designer (m/f/x)"), "ui ux designer")

    def test_seniority_preserved(self):
        self.assertNotEqual(tkey("Senior UI Designer"), tkey("Junior UI Designer"))

    def test_all_noise_falls_back(self):
        self.assertEqual(tkey("Remote Freelance"), "remote freelance")


class RoleDedupTest(unittest.TestCase):
    def test_intra_run_same_role_different_location_and_noise(self):
        p1 = make("https://a.example.com/jobs/1", title="UI Designer (Remote)",
                  company="AcmeStudio", location="Remote")
        p2 = make("https://b.example.com/jobs/2", title="Remote UI Designer – Freelance Role",
                  company="AcmeStudio", location="United States")
        kept, counts = filters([p1, p2], set(), NOW, 24)
        self.assertEqual(len(kept), 1)
        self.assertEqual(counts["duplicate_role"], 1)

    def test_cross_run_role_seen_location_ignored(self):
        role_seen = {"acmestudio|remote ui designer freelance role|remote": "2026-06-30"}
        p = make("https://c.example.com/jobs/3", title="UI Designer",
                 company="AcmeStudio", location="Germany, Berlin")
        kept, counts = filters([p], set(), NOW, 24, role_seen)
        self.assertEqual(len(kept), 0)
        self.assertEqual(counts["duplicate_role"], 1)

    def test_cross_run_expired_window_resurfaces(self):
        role_seen = {"acmestudio|ui designer|remote": "2026-05-01"}
        p = make("https://d.example.com/jobs/4", title="UI Designer", company="AcmeStudio")
        kept, counts = filters([p], set(), NOW, 24, role_seen)
        self.assertEqual(len(kept), 1)
        self.assertEqual(counts["duplicate_role"], 0)

    def test_different_seniority_not_deduped(self):
        p1 = make("https://e.example.com/jobs/5", title="Senior UI Designer", company="AcmeStudio")
        p2 = make("https://f.example.com/jobs/6", title="Junior UI Designer", company="AcmeStudio")
        kept, counts = filters([p1, p2], set(), NOW, 24)
        self.assertEqual(len(kept), 2)
        self.assertEqual(counts["duplicate_role"], 0)

    def test_unknown_company_not_deduped(self):
        p1 = make("https://g.example.com/jobs/7", company="Unknown (agency)")
        p2 = make("https://h.example.com/jobs/8", company="Unknown (agency)")
        kept, counts = filters([p1, p2], set(), NOW, 24)
        self.assertEqual(len(kept), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
