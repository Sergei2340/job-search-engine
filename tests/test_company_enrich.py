"""Unit tests for Phase-1 company-size enrichment (engine/company_enrich.py).

No network: the Bright Data trigger (`requests.post`) and the snapshot poll
(`linkedin_brightdata._poll_snapshot`) are mocked. Covers the design contract:
cache hits work keyless and skip triggers, URL canonicalization/join, bucket
normalization, TTL + negative cache, per-run cap, poll-timeout degradation
with `_pending` recovery, and the zero-company early return.

Run:  python -m tests.test_company_enrich
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import engine.company_enrich as ce  # noqa: E402
from engine.profile import Profile  # noqa: E402
from engine.relevance import RelevanceGate  # noqa: E402
from engine.sources import Posting  # noqa: E402

NOW = datetime(2026, 7, 6, tzinfo=timezone.utc)
NO_KEYS = {k: v for k, v in os.environ.items()
           if k not in ("BRIGHTDATA_API_KEY", "BRIGHT_DATA_API_KEY",
                        "COMPANY_SIZE_CACHE_FILE")}


def _profile(tmp: Path, **cfg) -> Profile:
    enrichment = {"company_size": {"enabled": True, **cfg}}
    return Profile(
        dept="testdept", display_name="Test", id_prefix="TST",
        sheet={"spreadsheet_id": "fake", "tab": "Sheet1"},
        profile_dir=tmp,
        gate=RelevanceGate.from_config({"allow_titles": [r"\bx\b"], "default_reason": "x"}),
        sources={}, enrichment=enrichment,
    )


def _posting(company_url: str, company: str = "Co") -> Posting:
    return Posting(title="Role", company=company, board="LinkedIn", location="Remote",
                   remote_type="Remote", salary="Not listed",
                   link=f"https://www.linkedin.com/jobs/view/{abs(hash(company_url)) % 10**9}",
                   date_posted=NOW, company_url=company_url)


def _trigger_ok(snapshot_id="snap1"):
    resp = mock.Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"snapshot_id": snapshot_id}
    return mock.Mock(return_value=resp)


def _seed_cache(profile: Profile, entries: dict, pending: dict | None = None):
    profile.state_dir.mkdir(parents=True, exist_ok=True)
    obj = {"_note": "x", "entries": entries}
    if pending:
        obj["_pending"] = pending
    profile.company_size_cache_file.write_text(json.dumps(obj), encoding="utf-8")


class NormalizeBucket(unittest.TestCase):
    def test_normalization(self):
        f = ce._normalize_bucket
        self.assertEqual(f("5,001-10,000 employees", None), "5,001-10,000")
        self.assertEqual(f("10,001+ employees", None), "10,001+")
        self.assertEqual(f("51-200 Employees", None), "51-200")
        self.assertEqual(f("2-10 employees", None), "2-10")   # off-list span passes through
        self.assertEqual(f(None, 87), "51-200")
        self.assertEqual(f(None, 20000), "10,001+")
        self.assertEqual(f(None, 3), "1-10")
        self.assertIsNone(f(None, None))
        self.assertIsNone(f("garbage", None))
        self.assertIsNone(f(None, 0))


class CacheHits(unittest.TestCase):
    def test_no_key_no_cache_all_null(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, NO_KEYS, clear=True), \
                mock.patch.object(ce.requests, "post") as post:
            profile = _profile(Path(td))
            p = _posting("https://www.linkedin.com/company/acme")
            stats = ce.enrich_company_sizes(profile, [p], NOW)
            post.assert_not_called()
            self.assertIsNone(p.company_size)
            self.assertEqual(stats["failed"], "no_key")
            self.assertEqual(stats["companies"], 1)

    def test_no_key_but_fresh_cache_is_applied(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, NO_KEYS, clear=True), \
                mock.patch.object(ce.requests, "post") as post:
            profile = _profile(Path(td))
            _seed_cache(profile, {"https://www.linkedin.com/company/acme":
                                  {"bucket": "51-200", "fetched_at": NOW.date().isoformat()}})
            p = _posting("https://www.linkedin.com/company/acme")
            stats = ce.enrich_company_sizes(profile, [p], NOW)
            post.assert_not_called()
            self.assertEqual(p.company_size, "51-200")
            self.assertEqual(stats["cache_hits"], 1)
            self.assertIsNone(stats["failed"])

    def test_cache_hit_skips_trigger(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "k"}), \
                mock.patch.object(ce.requests, "post") as post:
            profile = _profile(Path(td))
            _seed_cache(profile, {"https://www.linkedin.com/company/acme":
                                  {"bucket": "51-200", "fetched_at": NOW.date().isoformat()}})
            p = _posting("https://www.linkedin.com/company/acme")
            stats = ce.enrich_company_sizes(profile, [p], NOW)
            post.assert_not_called()
            self.assertEqual(p.company_size, "51-200")
            self.assertEqual(stats["cache_hits"], 1)
            self.assertEqual(stats["fetched"], 0)


class FetchPaths(unittest.TestCase):
    def test_trigger_join_and_url_canonicalization(self):
        records = [
            {"input": {"url": "https://www.linkedin.com/company/acme"},
             "company_size": "51-200 employees", "name": "Acme", "employees_in_linkedin": 87},
            {"input": {"url": "https://www.linkedin.com/company/beta"},
             "company_size": "11-50 employees", "name": "Beta"},
        ]
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "k"}), \
                mock.patch.object(ce.requests, "post", _trigger_ok()) as post, \
                mock.patch.object(ce.linkedin_brightdata, "_poll_snapshot",
                                  return_value=records):
            profile = _profile(Path(td))
            a1 = _posting("https://il.linkedin.com/company/acme/?trk=x", "AcmeA")
            a2 = _posting("https://www.linkedin.com/company/acme", "AcmeB")
            b = _posting("https://www.linkedin.com/company/beta", "Beta")
            stats = ce.enrich_company_sizes(profile, [a1, a2, b], NOW)
            # one trigger, payload deduped to 2 canonical urls (acme first: 2 postings)
            payload = post.call_args.kwargs["json"]
            self.assertEqual([d["url"] for d in payload],
                             ["https://www.linkedin.com/company/acme",
                              "https://www.linkedin.com/company/beta"])
            self.assertEqual(a1.company_size, "51-200")
            self.assertEqual(a2.company_size, "51-200")
            self.assertEqual(b.company_size, "11-50")
            self.assertEqual(stats["companies"], 2)
            self.assertEqual(stats["fetched"], 2)
            cache = json.loads(profile.company_size_cache_file.read_text())
            self.assertEqual(len(cache["entries"]), 2)
            self.assertNotIn("_pending", cache)

    def test_ttl_expiry_refetches(self):
        old = (NOW - timedelta(days=181)).date().isoformat()
        fresh = NOW.date().isoformat()
        records = [{"input": {"url": "https://www.linkedin.com/company/stale"},
                    "company_size": "201-500 employees"}]
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "k"}), \
                mock.patch.object(ce.requests, "post", _trigger_ok()) as post, \
                mock.patch.object(ce.linkedin_brightdata, "_poll_snapshot",
                                  return_value=records):
            profile = _profile(Path(td))
            _seed_cache(profile, {
                "https://www.linkedin.com/company/stale": {"bucket": "51-200", "fetched_at": old},
                "https://www.linkedin.com/company/fresh": {"bucket": "11-50", "fetched_at": fresh},
            })
            stale = _posting("https://www.linkedin.com/company/stale", "Stale")
            freshp = _posting("https://www.linkedin.com/company/fresh", "Fresh")
            stats = ce.enrich_company_sizes(profile, [stale, freshp], NOW)
            payload = [d["url"] for d in post.call_args.kwargs["json"]]
            self.assertEqual(payload, ["https://www.linkedin.com/company/stale"])
            self.assertEqual(stats["cache_expired"], 1)
            self.assertEqual(stats["cache_hits"], 1)
            self.assertEqual(stale.company_size, "201-500")  # refetched
            self.assertEqual(freshp.company_size, "11-50")   # from cache

    def test_negative_cache(self):
        records = [{"input": {"url": "https://www.linkedin.com/company/ghost"},
                    "warning": "not found"}]
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "k"}):
            profile = _profile(Path(td))
            g = _posting("https://www.linkedin.com/company/ghost", "Ghost")
            with mock.patch.object(ce.requests, "post", _trigger_ok()), \
                    mock.patch.object(ce.linkedin_brightdata, "_poll_snapshot",
                                      return_value=records):
                stats1 = ce.enrich_company_sizes(profile, [g], NOW)
            self.assertIsNone(g.company_size)
            self.assertEqual(stats1["no_data"], 1)
            cache = json.loads(profile.company_size_cache_file.read_text())
            self.assertTrue(cache["entries"]["https://www.linkedin.com/company/ghost"]["negative"])
            # second call within 30d: no re-trigger
            with mock.patch.object(ce.requests, "post") as post2, \
                    mock.patch.object(ce.linkedin_brightdata, "_poll_snapshot",
                                      return_value=records):
                ce.enrich_company_sizes(profile, [_posting(
                    "https://www.linkedin.com/company/ghost", "Ghost")], NOW)
                post2.assert_not_called()
            # 31 days later: negative TTL expired -> re-triggers
            later = NOW + timedelta(days=31)
            with mock.patch.object(ce.requests, "post", _trigger_ok()) as post3, \
                    mock.patch.object(ce.linkedin_brightdata, "_poll_snapshot",
                                      return_value=records):
                ce.enrich_company_sizes(profile, [_posting(
                    "https://www.linkedin.com/company/ghost", "Ghost")], later)
                post3.assert_called_once()

    def test_poll_timeout_degrades_and_records_pending(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "k"}), \
                mock.patch.object(ce.requests, "post", _trigger_ok("snapX")), \
                mock.patch.object(ce.linkedin_brightdata, "_poll_snapshot", return_value=[]):
            profile = _profile(Path(td))
            p = _posting("https://www.linkedin.com/company/acme")
            stats = ce.enrich_company_sizes(profile, [p], NOW)
            self.assertIsNone(p.company_size)
            self.assertEqual(stats["failed"], "poll_timeout")
            cache = json.loads(profile.company_size_cache_file.read_text())
            self.assertEqual(cache["_pending"]["snapshot_id"], "snapX")

    def test_pending_recovered_next_run(self):
        records = [{"input": {"url": "https://www.linkedin.com/company/acme"},
                    "company_size": "51-200 employees"}]
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "k"}), \
                mock.patch.object(ce.requests, "post") as post, \
                mock.patch.object(ce.linkedin_brightdata, "_poll_snapshot",
                                  return_value=records):
            profile = _profile(Path(td))
            _seed_cache(profile, {}, pending={
                "snapshot_id": "snapX", "triggered_at": NOW.isoformat(),
                "urls": ["https://www.linkedin.com/company/acme"]})
            p = _posting("https://www.linkedin.com/company/acme")
            stats = ce.enrich_company_sizes(profile, [p], NOW)
            post.assert_not_called()          # recovered, no new trigger needed
            self.assertEqual(p.company_size, "51-200")
            cache = json.loads(profile.company_size_cache_file.read_text())
            self.assertNotIn("_pending", cache)

    def test_per_run_cap(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "k"}), \
                mock.patch.object(ce.requests, "post", _trigger_ok()) as post, \
                mock.patch.object(ce.linkedin_brightdata, "_poll_snapshot", return_value=[]):
            profile = _profile(Path(td), max_per_run=50)
            postings = [_posting(f"https://www.linkedin.com/company/c{i}", f"C{i}")
                        for i in range(60)]
            stats = ce.enrich_company_sizes(profile, postings, NOW)
            payload = post.call_args.kwargs["json"]
            self.assertEqual(len(payload), 50)
            self.assertEqual(stats["capped_out"], 10)

    def test_non_linkedin_postings_ignored(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "k"}), \
                mock.patch.object(ce.requests, "post") as post:
            profile = _profile(Path(td))
            p = _posting("", "NoUrl")   # no company_url
            stats = ce.enrich_company_sizes(profile, [p], NOW)
            post.assert_not_called()
            self.assertEqual(stats["companies"], 0)
            self.assertIsNone(p.company_size)
            self.assertFalse(profile.company_size_cache_file.exists())

    def test_disabled_returns_immediately(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "k"}), \
                mock.patch.object(ce.requests, "post") as post:
            profile = _profile(Path(td), enabled=False)
            profile.enrichment["company_size"]["enabled"] = False
            p = _posting("https://www.linkedin.com/company/acme")
            stats = ce.enrich_company_sizes(profile, [p], NOW)
            post.assert_not_called()
            self.assertFalse(stats["enabled"])
            self.assertIsNone(p.company_size)

    def test_garbage_config_values_degrade_to_defaults(self):
        """ttl_days: abc etc. must warn and use defaults, never crash the run."""
        records = [{"input": {"url": "https://www.linkedin.com/company/acme"},
                    "company_size": "51-200 employees"}]
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"BRIGHTDATA_API_KEY": "k"}), \
                mock.patch.object(ce.requests, "post", _trigger_ok()), \
                mock.patch.object(ce.linkedin_brightdata, "_poll_snapshot",
                                  return_value=records):
            profile = _profile(Path(td), ttl_days="abc", max_per_run=None,
                               negative_ttl_days=[1], max_poll_seconds="x")
            p = _posting("https://www.linkedin.com/company/acme")
            stats = ce.enrich_company_sizes(profile, [p], NOW)
            self.assertEqual(p.company_size, "51-200")
            self.assertIsNone(stats["failed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
