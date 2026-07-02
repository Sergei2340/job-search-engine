"""Per-source fetchers. Each module exposes a fetch(profile) -> list[Posting].

Posting and canonical_url are department-neutral and MUST stay in sync with
the Phase 2 SKILL contract (candidate schema) and the `_norm_role_part`
bookkeeping in engine/main.py.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import unquote, urlsplit, urlunsplit

_LINKEDIN_JOB_ID = re.compile(r"(\d{6,})")


def canonical_url(u: str) -> str:
    """Stable dedup key for a listing URL.

    Motivation: the same LinkedIn job leaked past
    `seen_urls` exact-match dedup because LinkedIn returns the slug with an
    en-dash sometimes stripped and sometimes percent-encoded. The trailing
    numeric job id is the only stable part, so LinkedIn job URLs collapse to
    `https://www.linkedin.com/jobs/view/<id>`. Other hosts get a light
    normalization (lowercase host, drop query/fragment, percent-decode the
    path, strip trailing slash) so encoding/casing variants match too.

    Used by main.py's dedup (applied to BOTH incoming links and the loaded
    seen_urls set, so historical slug-form entries collapse and still match).
    """
    if not u:
        return ""
    u = u.strip()
    try:
        parts = urlsplit(u)
    except ValueError:
        return u.lower()
    host = (parts.netloc or "").lower()
    path = parts.path or ""
    if "linkedin.com" in host and "/jobs/view/" in path:
        seg = path.split("/jobs/view/", 1)[1].rstrip("/")
        m = re.search(r"(\d{6,})$", seg) or _LINKEDIN_JOB_ID.search(seg)
        if m:
            return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    scheme = (parts.scheme or "https").lower()
    norm_path = unquote(path).rstrip("/")
    return urlunsplit((scheme, host, norm_path, "", "")) or u.lower()


@dataclass
class Posting:
    """Normalized job posting, one per listing."""
    title: str
    company: str
    board: str              # "GoogleJobs" / "WeWorkRemotely" / "LinkedIn" / ...
    location: str           # city/country or "Remote"
    remote_type: str        # "Remote" / "Hybrid" / "On-site" / "Unknown"
    salary: str             # raw string; "Not listed" if absent
    link: str               # direct URL to the listing
    date_posted: Optional[datetime]  # original publication date; None if unknown
    risk_flags: str = ""    # e.g. language requirements
    raw: Optional[dict] = None  # source payload for debugging
    # Content handed to the LLM scorer in Phase 2:
    raw_type: str = "html"  # "html" / "serpapi_json" / "linkedin_json"
    raw_content: str = ""   # cleaned HTML body or JSON-dumped source item; <=30KB
    # Set by main.py when the link host is a known job-aggregator whose posting
    # dates are unreliable (fresh-looking reposts of stale jobs). Phase 2 must
    # treat freshness as unknown and add the `date-suspect` risk flag.
    date_suspect: bool = False

    def to_candidate(self, date_found: datetime) -> dict:
        """Candidate shape emitted to candidates.json for Phase 2 LLM scoring."""
        return {
            "id": hashlib.sha1(self.link.encode("utf-8")).hexdigest()[:12],
            "board": self.board,
            "link": self.link,
            "title_guess": self.title,
            "company_guess": self.company,
            "date_found_iso": date_found.isoformat(),
            "date_posted_iso": self.date_posted.isoformat() if self.date_posted else None,
            "raw_type": self.raw_type,
            "raw_content": (self.raw_content or "")[:30000],
            "date_suspect": self.date_suspect,
        }
