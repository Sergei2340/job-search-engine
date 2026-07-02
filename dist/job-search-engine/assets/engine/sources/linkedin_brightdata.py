"""LinkedIn jobs fetcher via the Bright Data Datasets v3 API.

WHY THIS EXISTS
    LinkedIn is excluded from the SerpAPI source (Google can't reliably index
    it; public job pages 999 anonymous fetches), yet it is the richest source
    of agency / studio / staff-aug signals — exactly the Phase-2 rubric's
    highest-value (score-5) lead type. This module pulls LinkedIn listings
    through Bright Data's managed "LinkedIn job listings — discover by
    keyword" dataset. Bright Data runs the search on its own infrastructure
    (proxies + anti-bot + parsing) and returns clean structured JSON.

DEPARTMENT CONFIG (profile.yaml)
    sources:
      linkedin_brightdata:
        enabled: true
        time_range: "Past 24 hours"     # LinkedIn UI labels, title-case enum
        run_once_per_day: true
        inputs:                          # cost lever: billed per record
          - {keyword: "UX Designer", location: "United States", country: "US"}

ASYNC FLOW (Datasets v3 — this dataset is NOT synchronous)
    1. POST {TRIGGER_URL}?dataset_id=...&type=discover_new&discover_by=keyword
       body: [ {keyword, location, country, time_range}, ... ] -> {"snapshot_id"}
    2. GET {SNAPSHOT_URL}/<snapshot_id>?format=json
       -> 202 => still running, wait and retry; 200 => JSON array of records.

COST NOTES
    - BOTH limit_per_input AND limit_multiple_results are IGNORED by this
      dataset's discover mode. time_range is the real volume cap.
    - Billed per record → keep inputs lean and run once/day. BRIGHTDATA_API_KEY
      may be shared across departments (stagger schedules; see profile docs).

Docs: https://docs.brightdata.com/api-reference/web-scraper-api/social-media-apis/linkedin#discover-by-keyword
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dateutil import parser as dateparser

from . import Posting, canonical_url

log = logging.getLogger(__name__)

# --- Bright Data endpoints / dataset --------------------------------------
DEFAULT_DATASET_ID = "gd_lpfll7v5hcqtkxl6l"  # "LinkedIn job listings - discover by keyword"
TRIGGER_URL = "https://api.brightdata.com/datasets/v3/trigger"
SNAPSHOT_URL = "https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}"

# Sent but ignored by discover mode (see COST NOTES). Harmless.
LIMIT_PER_INPUT = 20
LIMIT_TOTAL = 50

# Snapshot polling. The dataset builds asynchronously; cap the wait so a stuck
# snapshot can't hang the Phase-1 thread pool. Raised 300 -> 900 on 2026-07-01:
# with 10 inputs the build time blew past 300s (returned 0 for the day).
# Schedule Phase 2 >= 30 min after Phase 1 so a 15-min poll still lands in time.
# If a snapshot ever exceeds 15 min, that day's LinkedIn is skipped (rare) —
# the robust alternative is decoupling trigger/collect across runs.
POLL_INTERVAL_SECONDS = 15
MAX_POLL_SECONDS = 900


def _ran_today(profile, now: datetime, run_once: bool) -> bool:
    if not run_once or os.environ.get("LINKEDIN_RUN_ALWAYS"):
        return False
    try:
        data = json.loads(profile.linkedin_state_file.read_text())
        return data.get("last_run_date") == now.date().isoformat()
    except (OSError, ValueError):
        return False


def _mark_ran(profile, now: datetime) -> None:
    try:
        profile.linkedin_state_file.parent.mkdir(parents=True, exist_ok=True)
        profile.linkedin_state_file.write_text(json.dumps(
            {"last_run_date": now.date().isoformat(), "last_run_iso": now.isoformat()}))
    except OSError as exc:
        log.warning("Could not write LinkedIn state file: %s", exc)


def _canonical_link(url: str, job_posting_id: str) -> str:
    """Slug-independent canonical URL so dedup is stable across runs. LinkedIn
    slugs vary (en-dash stripped vs %-encoded), which let the same job leak
    past exact-match dedup (2026-07-01). Prefer the numeric job id."""
    if job_posting_id and str(job_posting_id).strip():
        return f"https://www.linkedin.com/jobs/view/{str(job_posting_id).strip()}"
    return canonical_url(url or "")


def _relative_to_date(s: str, now: datetime) -> datetime | None:
    if not s:
        return None
    s = str(s).strip().lower()
    if "just" in s or "moment" in s or "hour" in s or "minute" in s or "today" in s:
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
        if "year" in parts[1]:
            return now - timedelta(days=n * 365)
    return None


def _parse_date(item: dict, now: datetime) -> datetime | None:
    absolute = item.get("job_posted_date") or item.get("posted_date")
    if absolute:
        try:
            dt = dateparser.parse(str(absolute))
            if dt:
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, OverflowError):
            pass
    return _relative_to_date(item.get("job_posted_time") or item.get("posted_time"), now)


def _salary(item: dict) -> str:
    for key in ("base_salary", "salary_standards"):
        val = item.get(key)
        if isinstance(val, dict):
            lo = val.get("min_amount") or val.get("min")
            hi = val.get("max_amount") or val.get("max")
            cur = val.get("currency") or ""
            period = val.get("payment_period") or val.get("period") or ""
            if lo or hi:
                span = "-".join(str(x) for x in (lo, hi) if x)
                return " ".join(p for p in (f"{cur}{span}".strip(), period) if p).strip()
        elif isinstance(val, str) and val.strip():
            return val.strip()
    return "Not listed"


def _remote_type(item: dict) -> str:
    explicit = str(
        item.get("job_work_type") or item.get("workplace_type") or item.get("remote") or ""
    ).lower()
    haystack = " ".join(
        str(item.get(k) or "")
        for k in ("job_location", "job_title", "job_summary", "job_employment_type")
    ).lower()
    blob = explicit + " " + haystack[:400]
    if "hybrid" in blob:
        return "Hybrid"
    if "remote" in blob or "work from home" in blob:
        return "Remote"
    if "on-site" in blob or "onsite" in blob or "on site" in blob:
        return "On-site"
    return "Unknown"


def _is_relevant(item: dict, gate, require_match: bool) -> bool:
    """Phase-1 relevance safety-net. LinkedIn keyword discovery is LOOSE: a
    search for a role term also returns roles where the term only appears in
    the body. Gate on title + description (NOT company name)."""
    if not require_match:
        return True
    title = str(item.get("job_title") or "")
    body = " ".join(str(item.get(k) or "") for k in
                    ("job_summary", "job_description_formatted"))
    return gate.is_relevant(title, body)


def _posting_from_record(item: dict, now: datetime, dataset_id: str) -> Posting | None:
    title = (item.get("job_title") or "").strip()
    company = (item.get("company_name") or "").strip()
    location = (item.get("job_location") or "").strip() or "Remote"

    link = _canonical_link(item.get("url") or "", str(item.get("job_posting_id") or ""))
    if not link:
        return None  # a direct listing URL is required

    raw_content = json.dumps(item, default=str)[:30000]

    return Posting(
        title=title,
        company=company,
        board="LinkedIn",
        location=location,
        remote_type=_remote_type(item),
        salary=_salary(item),
        link=link,
        date_posted=_parse_date(item, now),
        risk_flags="",
        raw={"source": "brightdata", "dataset": dataset_id,
             "job_posting_id": item.get("job_posting_id"),
             "seniority": item.get("job_seniority_level")},
        raw_type="linkedin_json",
        raw_content=raw_content,
    )


def _build_payload(inputs: list[dict], time_range: str) -> list[dict]:
    payload = []
    for spec in inputs:
        item = {k: v for k, v in spec.items() if v}
        if time_range:
            item["time_range"] = time_range
        payload.append(item)
    return payload


def _trigger(key: str, dataset_id: str, payload: list[dict]) -> str | None:
    params = {
        "dataset_id": dataset_id,
        "type": "discover_new",
        "discover_by": "keyword",
        "include_errors": "true",
        "limit_per_input": str(LIMIT_PER_INPUT),
        "limit_multiple_results": str(LIMIT_TOTAL),
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        r = requests.post(TRIGGER_URL, headers=headers, params=params,
                          json=payload, timeout=30)
        r.raise_for_status()
        snap = (r.json() or {}).get("snapshot_id")
    except requests.RequestException as exc:
        log.error("Bright Data trigger failed: %s", exc)
        return None
    except ValueError:
        log.error("Bright Data trigger returned non-JSON body")
        return None
    if not snap:
        log.error("Bright Data trigger returned no snapshot_id")
        return None
    log.info("Bright Data LinkedIn: triggered snapshot %s (%d inputs)", snap, len(payload))
    return snap


def _poll_snapshot(key: str, snapshot_id: str) -> list[dict]:
    url = SNAPSHOT_URL.format(snapshot_id=snapshot_id)
    headers = {"Authorization": f"Bearer {key}"}
    deadline = time.monotonic() + MAX_POLL_SECONDS
    while time.monotonic() < deadline:
        try:
            r = requests.get(url, headers=headers, params={"format": "json"}, timeout=60)
        except requests.RequestException as exc:
            log.error("Bright Data snapshot poll error: %s", exc)
            return []

        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                data = [json.loads(ln) for ln in r.text.splitlines() if ln.strip()]
            if isinstance(data, dict):
                status = str(data.get("status") or "").lower()
                if status in ("running", "building", "pending", "collecting"):
                    log.info("Bright Data snapshot %s status=%s; retry in %ds",
                             snapshot_id, status, POLL_INTERVAL_SECONDS)
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue
                data = data.get("data") or data.get("results") or []
            return data if isinstance(data, list) else []

        if r.status_code in (202, 404):
            log.info("Bright Data snapshot %s not ready (HTTP %s); retry in %ds",
                     snapshot_id, r.status_code, POLL_INTERVAL_SECONDS)
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        log.error("Bright Data snapshot poll failed: HTTP %s - %s",
                  r.status_code, r.text[:200])
        return []

    log.warning("Bright Data snapshot %s not ready after %ds; skipping this run",
                snapshot_id, MAX_POLL_SECONDS)
    return []


def fetch(profile) -> list[Posting]:
    """Entry point used by main.py. Gracefully degrades to [] (logged) when the
    key is missing or the collection fails/times out — Phase 1 must never
    crash on one source."""
    key = os.environ.get("BRIGHTDATA_API_KEY") or os.environ.get("BRIGHT_DATA_API_KEY")
    if not key:
        log.warning("BRIGHTDATA_API_KEY not set; skipping LinkedIn (Bright Data) source")
        return []

    cfg = profile.source_cfg("linkedin_brightdata")
    inputs: list[dict] = cfg.get("inputs") or []
    if not inputs:
        log.warning("linkedin_brightdata enabled but profile defines no inputs; skipping")
        return []
    dataset_id = cfg.get("dataset_id") or DEFAULT_DATASET_ID
    time_range = cfg.get("time_range", "Past 24 hours")
    run_once = bool(cfg.get("run_once_per_day", True))
    require_match = bool(cfg.get("require_gate_match", True))

    now = datetime.now(timezone.utc)
    if _ran_today(profile, now, run_once):
        log.info("LinkedIn (Bright Data): already triggered today (UTC) — skipping to "
                 "avoid re-paying the 24h window (set LINKEDIN_RUN_ALWAYS=1 to override)")
        return []

    snapshot_id = _trigger(key, dataset_id, _build_payload(inputs, time_range))
    if not snapshot_id:
        return []
    _mark_ran(profile, now)  # billed at trigger time; a poll timeout must not un-gate

    records = _poll_snapshot(key, snapshot_id)
    if not records:
        log.info("Bright Data LinkedIn: snapshot returned 0 records")
        return []

    out: list[Posting] = []
    skipped_err = 0
    skipped_irrelevant = 0
    for item in records:
        if not isinstance(item, dict):
            continue
        if (item.get("error") or item.get("warning")) and not item.get("job_title"):
            skipped_err += 1
            continue
        if not _is_relevant(item, profile.gate, require_match):
            skipped_irrelevant += 1
            continue
        p = _posting_from_record(item, now, dataset_id)
        if p:
            out.append(p)
    log.info("Bright Data LinkedIn: %d records -> %d postings "
             "(%d error/empty, %d out-of-scope skipped)",
             len(records), len(out), skipped_err, skipped_irrelevant)
    return out
