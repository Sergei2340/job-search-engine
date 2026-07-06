"""Regression guard for serpapi_jobs.fetch().

The engine/SKILL.md + serpapi_jobs.py pair shipped truncated once: the final
`return out` of fetch() was lost, so fetch() returned None and SerpAPI — the
primary volume source — silently contributed zero postings (None -> [] in
fetch_all). The offline e2e test stubs the whole source, so it never exercised
the real fetch body and did not catch this.

This test drives the real fetch() with a mocked SerpAPI HTTP response and
asserts it returns a populated list[Posting]. It fails hard if fetch() ever
loses its return again.

Run:  python -m tests.test_serpapi_fetch_returns_list
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.profile import Profile  # noqa: E402
from engine.relevance import RelevanceGate  # noqa: E402
from engine.sources import Posting  # noqa: E402
from engine.sources import serpapi_jobs  # noqa: E402


def _gate() -> RelevanceGate:
    return RelevanceGate.from_config({
        "allow_titles": [r"\b3d\b"],
        "default_reason": "no 3d signal",
    })


def _profile() -> Profile:
    return Profile(
        dept="testdept",
        display_name="Test Dept",
        id_prefix="TST",
        sheet={"spreadsheet_id": "fake", "tab": "Sheet1"},
        profile_dir=Path("."),  # fetch() never touches the filesystem
        gate=_gate(),
        sources={"serpapi": {
            "enabled": True,
            "queries": [{"q": "3D Artist remote"}],
            "date_posted_chip": None,
        }},
    )


def _fake_serpapi_response() -> dict:
    """One in-scope job result that survives the gate and yields a Posting."""
    return {
        "jobs_results": [{
            "title": "3D Artist",
            "company_name": "Acme Studio",
            "location": "Remote",
            "description": "We are hiring a 3D artist for games.",
            "detected_extensions": {"posted_at": "2 days ago", "schedule_type": "Full-time"},
            "apply_options": [{"link": "https://jobs.example.com/3d-artist-1"}],
        }]
    }


class SerpapiFetchReturnsList(unittest.TestCase):
    def test_fetch_returns_populated_list(self):
        resp = mock.Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = _fake_serpapi_response()

        with mock.patch.dict(os.environ, {"SERPAPI_KEY": "test-key"}), \
                mock.patch.object(serpapi_jobs.requests, "get", return_value=resp):
            result = serpapi_jobs.fetch(_profile())

        # The regression: a missing `return out` made this None.
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        p = result[0]
        self.assertIsInstance(p, Posting)
        self.assertEqual(p.title, "3D Artist")
        self.assertEqual(p.company, "Acme Studio")
        self.assertEqual(p.board, "GoogleJobs")
        self.assertEqual(p.link, "https://jobs.example.com/3d-artist-1")

    def test_fetch_without_key_returns_empty_list(self):
        """No SERPAPI_KEY -> fetch degrades to [] (never None, never raises)."""
        env = {k: v for k, v in os.environ.items() if k != "SERPAPI_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            result = serpapi_jobs.fetch(_profile())
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
