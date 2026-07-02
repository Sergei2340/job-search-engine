"""We Work Remotely — jobs via a category RSS feed (from the profile).

WWR publishes a per-category RSS feed; the profile picks the category:

    sources:
      weworkremotely:
        enabled: true
        feed_url: "https://weworkremotely.com/categories/remote-design-jobs.rss"

Category feeds are BROAD (the Design feed carries engineering/construction
"design" roles too — 2026-06-30 live check), so every item runs through the
profile's relevance gate on title + description + skills. Remote-only board →
remote_type is always "Remote".

Item fields (confirmed live 2026-06-30): title ("Company: Role"), region,
country, state, skills, category, type, description (HTML), pubDate, link.
No salary element → "Not listed".
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
from dateutil import parser as dateparser

from . import Posting

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; job-search-engine/1.0)"}
MAX_ITEMS = 60

_TAG = re.compile(r"<[^>]+>")


def _text(html: str) -> str:
    """Strip tags / collapse whitespace from an HTML description."""
    s = _TAG.sub(" ", html or "")
    s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
    return re.sub(r"\s+", " ", s).strip()


def _split_company_title(raw_title: str) -> tuple[str, str]:
    """WWR <title> is 'Company: Role'. Split on the first ':'."""
    if ":" in raw_title:
        co, _, role = raw_title.partition(":")
        return co.strip(), role.strip()
    return "", raw_title.strip()


def _parse_items(xml_bytes: bytes, now: datetime, gate) -> list[Posting]:
    """Pure parser (no network) so it can be unit-tested with literal XML."""
    root = ET.fromstring(xml_bytes)
    items = root.findall(".//item")
    out: list[Posting] = []
    for it in items[:MAX_ITEMS]:
        def g(tag: str) -> str:
            e = it.find(tag)
            return (e.text or "") if e is not None else ""

        raw_title = (g("title") or "").strip()
        company, role = _split_company_title(raw_title)
        desc_text = _text(g("description"))
        skills = (g("skills") or "").strip()
        if not gate.is_relevant(role, desc_text + " " + skills):
            continue
        link = (g("link") or "").strip()
        if not link:
            continue

        date_posted = None
        pub = g("pubDate")
        if pub:
            try:
                dt = dateparser.parse(pub)
                if dt:
                    date_posted = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError, OverflowError):
                pass

        location = next((v.strip() for v in (g("country"), g("region"), g("state")) if v and v.strip()), "Remote")
        header = (f"Company: {company or 'Unknown'}\nRegion: {location}\n"
                  f"Type: {g('type')}\nSkills: {skills}\n\n")
        out.append(Posting(
            title=role or raw_title,
            company=company or "Unknown",
            board="WeWorkRemotely",
            location=location,
            remote_type="Remote",
            salary="Not listed",
            link=link,
            date_posted=date_posted,
            raw={"category": g("category"), "type": g("type")},
            raw_type="html",
            raw_content=(header + desc_text)[:30000],
        ))
    log.info("WeWorkRemotely: %d items -> %d in-scope postings", len(items), len(out))
    return out


def fetch(profile) -> list[Posting]:
    cfg = profile.source_cfg("weworkremotely")
    feed_url = cfg.get("feed_url")
    if not feed_url:
        log.warning("weworkremotely enabled but profile defines no feed_url; skipping")
        return []
    try:
        r = requests.get(feed_url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except requests.RequestException as exc:
        log.error("WeWorkRemotely feed failed: %s", exc)
        return []
    try:
        return _parse_items(r.content, datetime.now(timezone.utc), profile.gate)
    except ET.ParseError as exc:
        log.error("WeWorkRemotely feed parse error: %s", exc)
        return []
