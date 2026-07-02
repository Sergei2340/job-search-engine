"""RemoteOK — jobs via the public JSON API, tag from the profile.

    sources:
      remoteok:
        enabled: true
        tag: "design"        # https://remoteok.com/api?tag=<tag>

No key; REQUIRES a User-Agent (403 without one). Returns ~100 recent jobs
carrying the tag. Tags are BROAD (the "design" tag also marks Customer
Support / Video Editor roles — 2026-06-30 live check), so every job runs
through the profile's relevance gate on title + tags + description.
Element [0] of the payload is a legal/metadata object (skipped).
Remote-only board → remote_type is "Remote".

Job fields (confirmed live 2026-06-30): slug, id, epoch, date, company,
company_logo, position, tags, description, location, apply_url, salary_min,
salary_max, url.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import requests
from dateutil import parser as dateparser

from . import Posting

log = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; job-search-engine/1.0)"}
MAX_ITEMS = 100

_TAG = re.compile(r"<[^>]+>")


def _text(html: str) -> str:
    s = _TAG.sub(" ", html or "")
    s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
    return re.sub(r"\s+", " ", s).strip()


def _salary(item: dict) -> str:
    try:
        lo = int(item.get("salary_min") or 0)
        hi = int(item.get("salary_max") or 0)
    except (TypeError, ValueError):
        lo = hi = 0
    if lo and hi:
        return f"${lo:,}-${hi:,}/yr"
    if lo or hi:
        return f"${(lo or hi):,}/yr"
    return "Not listed"


def _parse_jobs(arr: list, now: datetime, gate) -> list[Posting]:
    """Pure parser (no network) so it can be unit-tested with a literal list."""
    jobs = [x for x in arr if isinstance(x, dict) and not x.get("legal")
            and (x.get("position") or x.get("id"))]
    out: list[Posting] = []
    for item in jobs[:MAX_ITEMS]:
        title = (item.get("position") or "").strip()
        tags = item.get("tags") or []
        desc_text = _text(item.get("description") or "")
        body = desc_text + " " + " ".join(str(t) for t in tags)
        if not gate.is_relevant(title, body):
            continue

        link = (item.get("url") or "").strip()
        if not link:
            slug = item.get("slug") or item.get("id")
            link = f"https://remoteok.com/remote-jobs/{slug}" if slug else ""
        if not link:
            continue

        date_posted = None
        raw_date = item.get("date") or item.get("epoch")
        if raw_date is not None:
            try:
                if isinstance(raw_date, (int, float)) or (isinstance(raw_date, str) and raw_date.isdigit()):
                    date_posted = datetime.fromtimestamp(int(raw_date), tz=timezone.utc)
                else:
                    dt = dateparser.parse(str(raw_date))
                    if dt:
                        date_posted = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError, OverflowError, OSError):
                pass

        location = (item.get("location") or "").strip() or "Remote"
        salary = _salary(item)
        header = (f"Company: {item.get('company') or 'Unknown'}\nLocation: {location}\n"
                  f"Tags: {' '.join(str(t) for t in tags)}\nSalary: {salary}\n\n")
        out.append(Posting(
            title=title,
            company=(item.get("company") or "Unknown").strip(),
            board="RemoteOK",
            location=location,
            remote_type="Remote",
            salary=salary,
            link=link,
            date_posted=date_posted,
            raw={"tags": tags},
            raw_type="html",
            raw_content=(header + desc_text)[:30000],
        ))
    log.info("RemoteOK: %d jobs -> %d in-scope postings", len(jobs), len(out))
    return out


def fetch(profile) -> list[Posting]:
    cfg = profile.source_cfg("remoteok")
    tag = cfg.get("tag") or "design"
    try:
        r = requests.get(API_URL, headers=HEADERS, params={"tag": tag}, timeout=30)
        r.raise_for_status()
        arr = r.json()
    except (requests.RequestException, ValueError) as exc:
        log.error("RemoteOK API failed: %s", exc)
        return []
    if not isinstance(arr, list):
        log.error("RemoteOK API: unexpected payload type %s", type(arr).__name__)
        return []
    return _parse_jobs(arr, datetime.now(timezone.utc), profile.gate)
