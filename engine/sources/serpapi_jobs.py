"""SerpAPI Google Jobs fetcher — queries come from the department profile.

Primary volume source. Everything department-specific (queries, date chip) lives in profile.yaml:

    sources:
      serpapi:
        enabled: true
        date_posted_chip: "date_posted:3days"   # null disables the server-side chip
        queries:
          - {q: "Product Designer remote"}
          - {q: "UX Designer", location: "United Kingdom", gl: "gb"}

Budget: SerpAPI's 250-requests/month tariff at a daily cadence allows up to
8 queries/run (8 x 31 = 248 < 250). EACH department needs its OWN SERPAPI_KEY
(in the profile's .env) — keys are per-department budgets.

Relevance: every result runs through the profile's relevance gate (title +
description) before becoming a Posting. Phase 2 still does the real 1-5
scoring on what survives.

Date chip: a bandwidth/cost lever, not a correctness lever — main.py enforces
the precise max-age cut client-side.

Docs: https://serpapi.com/google-jobs-api
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import requests
from dateutil import parser as dateparser

from . import Posting

log = logging.getLogger(__name__)


def _relative_to_date(s: str, now: datetime) -> datetime | None:
    """'3 hours ago' / '2 days ago' / 'Just posted' -> absolute datetime."""
    if not s:
        return None
    s = s.strip().lower()
    if "just" in s or "hour" in s or "minute" in s:
        return now
    if "today" in s:
        return now
    if "yesterday" in s:
        return now - timedelta(days=1)
    parts = s.split()
    if len(parts) >= 2 and parts[0].isdigit():
        n = int(parts[0])
        if "day" in parts[1]:
            return now - timedelta(days=n)
        if "week" in parts[1]:
            return now - timedelta(weeks=n)
        if "month" in parts[1]:
            return now - timedelta(days=n * 30)
    try:
        return dateparser.parse(s)
    except (ValueError, TypeError):
        return None


def _posting_from_result(item: dict, qdef: dict, now: datetime,
                         gate, excluded_hosts: tuple[str, ...]) -> Posting | None:
    title = item.get("title", "").strip()
    company = item.get("company_name", "").strip()
    location = item.get("location", "").strip() or "Remote"
    description = item.get("description") or ""

    # Relevance gate (title + description) — drops out-of-scope roles up front
    # so Phase 2 only scores plausible leads for this department.
    if not gate.is_relevant(title, description):
        return None

    # Link resolution. Google Jobs lists several apply_options. Scan ALL of
    # them and take the first whose host is NOT excluded — the primary option
    # is frequently LinkedIn (excluded; covered by the Bright Data source) or a
    # cloaker while a LATER option is the real direct posting (2026-06-30:
    # several genuine leads had LinkedIn as apply[0] and the real link later).
    def _host(u: str) -> str:
        return u.split("/")[2] if u and "://" in u else ""

    link = ""
    for opt in item.get("apply_options") or []:
        u = opt.get("link", "")
        if u and not any(h in _host(u) for h in excluded_hosts):
            link = u
            break
    if not link:
        return None

    host = _host(link)
    board = "Indeed" if "indeed" in host else "GoogleJobs"

    ext = item.get("detected_extensions", {}) or {}
    posted_raw = ext.get("posted_at") or item.get("posted_at")
    if not posted_raw:
        for s in item.get("extensions") or []:
            s_low = s.lower()
            if "ago" in s_low or "today" in s_low or "yesterday" in s_low or "just" in s_low:
                posted_raw = s
                break
    date_posted = _relative_to_date(posted_raw, now)

    schedule = ext.get("schedule_type", "") or ""
    salary = ext.get("salary") or item.get("salary") or "Not listed"

    desc_low = description.lower()
    if ext.get("work_from_home") or "remote" in location.lower() or "remote" in desc_low[:300]:
        remote_type = "Remote"
    elif "hybrid" in desc_low[:300]:
        remote_type = "Hybrid"
    else:
        remote_type = "Unknown"

    raw_content = json.dumps(item, default=str)[:30000]

    return Posting(
        title=title,
        company=company,
        board=board,
        location=location,
        remote_type=remote_type,
        salary=str(salary),
        link=link,
        date_posted=date_posted,
        raw={"query": qdef, "schedule": schedule},
        raw_type="serpapi_json",
        raw_content=raw_content,
    )


def fetch(profile, max_per_query: int = 30) -> list[Posting]:
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        log.warning("SERPAPI_KEY not set; skipping SerpAPI source")
        return []

    cfg = profile.source_cfg("serpapi")
    queries: list[dict] = cfg.get("queries") or []
    if not queries:
        log.warning("serpapi enabled but profile defines no queries; skipping")
        return []
    date_chip = cfg.get("date_posted_chip", "date_posted:3days")
    excluded_hosts = profile.serpapi_excluded_hosts

    now = datetime.now(timezone.utc)
    out: list[Posting] = []
    for qdef in queries:
        params = {
            "engine": "google_jobs",
            "q": qdef["q"],
            "hl": qdef.get("hl", "en"),
            "api_key": key,
        }
        if qdef.get("location"):
            params["location"] = qdef["location"]
        if qdef.get("gl"):
            params["gl"] = qdef["gl"]
        if date_chip:
            params["chips"] = date_chip

        try:
            r = requests.get("https://serpapi.com/search.json", params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as exc:
            log.error("SerpAPI query failed: q=%r location=%r err=%s",
                      qdef["q"], qdef.get("location"), exc)
            continue

        jobs = data.get("jobs_results") or []
        if not jobs:
            log.info("SerpAPI: q=%r location=%r returned 0 jobs (status=%s)",
                     qdef["q"], qdef.get("location"),
                     (data.get("search_metadata") or {}).get("status"))
            continue

        kept_this_query = 0
        for item in jobs[:max_per_query]:
            p = _posting_from_result(item, qdef, now, profile.gate, excluded_hosts)
            if p:
                out.append(p)
                kept_this_query += 1
        log.info("SerpAPI: q=%r location=%r raw=%d kept=%d",
                 qdef["q"], qdef.get("location"), len(jobs), kept_this_query)
    log.info("SerpAPI: %d postings across %d queries", len(out), len(queries))
 