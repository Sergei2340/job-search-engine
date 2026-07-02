"""job-search-engine — candidate collector (Phase 1), department-agnostic.

ALL department specifics — search queries, the
relevance gate, sheet, caps — come from a profile (see engine/profile.py);
this module owns only the shared mechanics.

Relevance judgment is split in two:
  - a cheap *title/role* gate (engine/relevance.py, compiled from the
    profile) runs inside each source and drops obviously out-of-scope roles;
  - the real 1-5 lead scoring happens in Phase 2 (Claude in Cowork), which
    reads the emitted candidates.json against the profile's rubric.md and
    writes kept rows to the department's Google Sheet.

What this script does (cheap mechanical filters only):
- Fetch from the profile's enabled sources in parallel
- Drop postings with no link / a search-page link
- Drop postings on blocked domains (state/blocked_domains.json, curated from
  specialists' column-K feedback)
- Drop postings already in state/seen_urls.json (dedup, cross-run + intra-run,
  canonical-URL based)
- Drop role-level duplicates (company + noise-stripped title; location
  ignored) within the batch and against state/role_seen.json
- Null the date (+ mark date_suspect) for unreliable-date aggregator domains
- Drop postings older than max_age_hours IF a date was extractable (no-date
  postings are kept and passed to Claude to decide)
- Cap candidates with per-source fairness

Output (into the profile dir):
- candidates.json      — array of candidate dicts (see Posting.to_candidate)
- last_run_report.json — run_at, per-source counts, filter hits, cap info

Usage:
    python -m engine.main --profile <dept>
    python -m engine.main --profile profiles/<dept> --max-age 48

Writes nothing to the sheet. The writer phase runs in Cowork via engine/SKILL.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

if __package__ in (None, ""):  # `python engine/main.py` fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from engine.profile import Profile, load_profile  # noqa: E402
    from engine.sources import Posting, canonical_url  # noqa: E402
    from engine.sources import serpapi_jobs, linkedin_brightdata  # noqa: E402
else:
    from .profile import Profile, load_profile
    from .sources import Posting, canonical_url
    from .sources import serpapi_jobs, linkedin_brightdata

log = logging.getLogger("job-search-engine")

# Registry of available source connectors. A profile enables a subset via
# `sources.<name>.enabled` and supplies per-source config. Every fetch takes
# the profile and returns list[Posting].
SOURCE_REGISTRY = {
    "serpapi": serpapi_jobs.fetch,                  # Google Jobs aggregate
    "linkedin_brightdata": linkedin_brightdata.fetch,  # LinkedIn via Bright Data (async, 1x/day)
}


def fetch_all(profile: Profile) -> tuple[list[Posting], dict[str, int]]:
    """Run every enabled source in parallel. Returns (postings, per_source_counts)."""
    enabled = {name: fn for name, fn in SOURCE_REGISTRY.items()
               if profile.source_enabled(name)}
    unknown = set(profile.sources) - set(SOURCE_REGISTRY)
    if unknown:
        log.warning("Profile lists unknown sources (ignored): %s", ", ".join(sorted(unknown)))
    results: list[Posting] = []
    counts: dict[str, int] = {}
    if not enabled:
        log.warning("No sources enabled in profile %r", profile.dept)
        return results, counts
    with ThreadPoolExecutor(max_workers=max(1, len(enabled))) as ex:
        futures = {ex.submit(fn, profile): name for name, fn in enabled.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                items = fut.result() or []
            except Exception as exc:  # noqa: BLE001
                log.exception("Source %s crashed: %s", name, exc)
                items = []
            counts[name] = len(items)
            results.extend(items)
    return results, counts


# ---------------------------------------------------------------------------
# Cheap mechanical filters (relevance scoring moves to Claude in Phase 2)
# ---------------------------------------------------------------------------

def load_blocked_domains(path: Path) -> dict[str, str]:
    """Load the paywall/dead-link domain blocklist. Keys starting with '_' are
    comments. Returns {} on absence/corruption — the filter degrades gracefully."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k.lower(): str(v) for k, v in data.items() if not k.startswith("_")}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("blocked_domains.json unreadable (%s) — domain blocklist disabled", exc)
        return {}


def _link_host(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _host_matches(host: str, domain: str) -> bool:
    """Suffix match: 'talents.studysmarter.co.uk' matches 'studysmarter.co.uk'."""
    return host == domain or host.endswith("." + domain)


def _norm_role_part(s: str) -> str:
    """Normalization shared with Phase 2's role_seen bookkeeping.
    Keep in sync with engine/SKILL.md (role_seen.json)."""
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9а-яё#+ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _title_key(title: str, noise_tokens: frozenset[str]) -> str:
    """Dedup key for a role title: _norm_role_part + noise tokens stripped.
    Used ONLY for comparison — role_seen.json keys keep the raw normalized
    title. Falls back to the plain normalized title if stripping empties it."""
    norm = _norm_role_part(title)
    stripped = " ".join(t for t in norm.split() if t not in noise_tokens)
    return stripped or norm


def _is_search_or_root(url: str) -> bool:
    """True if the URL is a bare domain / search page rather than a specific
    listing (no path beyond '/')."""
    if not url:
        return True
    try:
        path = (urlparse(url).path or "").rstrip("/")
    except ValueError:
        return False
    return path == ""


def apply_filters(
    postings: list[Posting],
    seen_urls: set[str],
    now: datetime,
    max_age_hours: int,
    role_seen: dict[str, str] | None = None,
    blocked_domains: dict[str, str] | None = None,
    *,
    excluded_companies: frozenset[str] = frozenset(),
    unreliable_date_domains: frozenset[str] = frozenset(),
    title_noise_tokens: frozenset[str] = frozenset(),
    role_seen_window_days: int = 30,
) -> tuple[list[Posting], dict[str, int]]:
    """Apply cheap mechanical filters. Returns (kept, rejection_counts)."""
    counts = {"no_link": 0, "blocked_domain": 0, "duplicate": 0,
              "duplicate_role": 0, "excluded": 0, "too_old": 0}
    kept: list[Posting] = []
    cutoff = now - timedelta(hours=max_age_hours)
    # Intra-run dedup. Different sources can surface the same posting, and
    # seen_urls only knows about prior-run writes.
    intra_run_seen: set[str] = set()
    # Intra-run role-level dedup: same (company, title) posted under several
    # URLs in one batch is noise. Location is IGNORED (2026-07-02) —
    # specialists flagged reposts of one role across cities/titles as dups.
    # Only applies when the company is actually known — "Unknown (…)"
    # placeholders could collapse distinct jobs.
    intra_run_roles: set[tuple[str, str]] = set()
    # Cross-run index from role_seen.json (3-part keys): (company, title_key)
    # -> latest seen date. Location part of the stored key is dropped here.
    role_seen_idx: dict[tuple[str, str], str] = {}
    for flat_key, seen_date in (role_seen or {}).items():
        parts = flat_key.split("|")
        if len(parts) >= 2:
            idx_key = (parts[0], _title_key(parts[1], title_noise_tokens))
            prev = role_seen_idx.get(idx_key)
            role_seen_idx[idx_key] = max(prev, seen_date) if prev else seen_date

    for p in postings:
        # Rule 1: direct listing URL required
        if _is_search_or_root(p.link):
            counts["no_link"] += 1
            continue
        host = _link_host(p.link)
        # Rule 1b: blocked resources (paywall / dead links) — curated per
        # profile in state/blocked_domains.json from specialists' feedback.
        if blocked_domains and any(_host_matches(host, d) for d in blocked_domains):
            counts["blocked_domain"] += 1
            continue
        # Rule 2: dedup against prior runs AND within this batch. Compare
        # canonical (slug-independent) URLs so encoding variants of the same
        # posting collapse — see canonical_url() in sources/__init__.py.
        cl = canonical_url(p.link)
        if cl in seen_urls or cl in intra_run_seen:
            counts["duplicate"] += 1
            continue
        intra_run_seen.add(cl)
        # Rule 2b: role-level dedup — within this batch AND against recently
        # written sheet rows (cross-run state in role_seen.json, written by
        # Phase 2 per successful row). Entries older than role_seen_window_days
        # are ignored so a genuinely re-opened position resurfaces.
        company_norm = _norm_role_part(p.company)
        if company_norm and not company_norm.startswith("unknown"):
            role_key = (company_norm, _title_key(p.title, title_noise_tokens))
            seen_date = role_seen_idx.get(role_key)
            recent = False
            if seen_date:
                try:
                    recent = (now - datetime.fromisoformat(seen_date).replace(
                        tzinfo=timezone.utc)).days <= role_seen_window_days
                except ValueError:
                    recent = True  # unparseable date — be conservative, treat as dup
            if role_key in intra_run_roles or recent:
                counts["duplicate_role"] += 1
                continue
            intra_run_roles.add(role_key)
        # Rule 3: excluded-company filter. Empty for most departments; useful
        # when a platform vendor's own postings must never become leads.
        if p.company and p.company.strip().lower() in excluded_companies:
            counts["excluded"] += 1
            continue
        # Rule 3b: aggregators with unreliable dates — null the date (they sort
        # last and fall out of fair_cap first), Phase 2 gets date_suspect=True
        # and adds the `date-suspect` risk flag.
        if any(_host_matches(host, d) for d in unreliable_date_domains):
            p.date_posted = None
            p.date_suspect = True
        # Rule 4: too_old — only filter if we have a date. No-date postings
        # pass through and Claude decides.
        if p.date_posted is not None:
            dp = p.date_posted
            if dp.tzinfo is None:
                dp = dp.replace(tzinfo=timezone.utc)
            if dp < cutoff:
                counts["too_old"] += 1
                continue
        kept.append(p)

    # Newest first (no-date postings sort last)
    kept.sort(
        key=lambda x: x.date_posted or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return kept, counts


def fair_cap(kept: list[Posting], cap: int) -> tuple[list[Posting], list[Posting]]:
    """Cap candidates with per-source fairness. Round-robin across boards,
    newest-first within each board, so one bulk-posting board can't crowd
    every other source out of the batch.

    Returns (selected, dropped). `kept` must already be sorted newest-first.
    """
    if len(kept) <= cap:
        return kept, []
    by_board: dict[str, list[Posting]] = {}
    for p in kept:
        by_board.setdefault(p.board, []).append(p)
    queues = list(by_board.values())
    selected: list[Posting] = []
    while len(selected) < cap:
        progressed = False
        for q in queues:
            if q and len(selected) < cap:
                selected.append(q.pop(0))
                progressed = True
        if not progressed:
            break
    dropped = [p for q in queues for p in q]
    # Restore global newest-first order for the output file.
    selected.sort(
        key=lambda x: x.date_posted or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return selected, dropped


# ---------------------------------------------------------------------------
# State loading (resilient to corruption — a bad byte must never reset dedup)
# ---------------------------------------------------------------------------

def load_seen_urls(seen_path: Path) -> set[str]:
    if not seen_path.exists():
        return set()
    # Resilient parse: strip Windows null-byte padding before decoding, and
    # recover from concatenated/trailing-data corruption so a single bad
    # append can never reset dedup state or crash the run.
    raw = seen_path.read_bytes().rstrip(b"\x00").decode("utf-8", errors="replace").rstrip()
    try:
        return set(json.loads(raw))
    except json.JSONDecodeError:
        seen: set[str] = set()
        dec = json.JSONDecoder()
        idx, n = 0, len(raw)
        while idx < n:
            while idx < n and raw[idx] in " \t\r\n,":
                idx += 1
            if idx >= n:
                break
            try:
                val, end = dec.raw_decode(raw, idx)
            except json.JSONDecodeError:
                break
            if isinstance(val, list):
                seen.update(str(u) for u in val)
            elif isinstance(val, str):
                seen.add(val)
            if end <= idx:
                break
            idx = end
        log.warning("seen_urls.json was malformed; recovered %d entries via resilient decode",
                    len(seen))
        return seen


def load_role_seen(role_seen_path: Path) -> dict[str, str]:
    if not role_seen_path.exists():
        return {}
    try:
        raw = role_seen_path.read_bytes().rstrip(b"\x00").decode("utf-8", errors="replace")
        return json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("role_seen.json unreadable (%s) — cross-run role dedup disabled this run", exc)
        return {}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(profile: Profile, max_age_hours: int | None = None,
        out: Path | None = None, report_out: Path | None = None) -> dict:
    """Full Phase 1 run for one department profile. Returns the report dict."""
    max_age = max_age_hours if max_age_hours is not None else profile.max_age_hours
    out = out or profile.candidates_file
    report_out = report_out or profile.report_file

    seen_urls = load_seen_urls(profile.seen_urls_file)
    # Canonicalize dedup keys (slug-independent) so even historical slug-form
    # entries match today's canonical links.
    seen_urls = {canonical_url(u) for u in seen_urls}
    role_seen = load_role_seen(profile.role_seen_file)

    now = datetime.now(timezone.utc)
    postings, source_counts = fetch_all(profile)
    log.info("[%s] Fetched %d raw postings across %d sources",
             profile.dept, len(postings), len(source_counts))

    blocked_domains = load_blocked_domains(profile.blocked_domains_file)
    kept, filter_counts = apply_filters(
        postings, seen_urls, now, max_age, role_seen, blocked_domains,
        excluded_companies=profile.excluded_companies,
        unreliable_date_domains=profile.unreliable_date_domains,
        title_noise_tokens=profile.title_noise_tokens,
        role_seen_window_days=profile.role_seen_window_days,
    )
    log.info(
        "[%s] After filters: %d kept (rejected: no_link=%d, blocked_domain=%d, duplicate=%d, "
        "duplicate_role=%d, excluded=%d, too_old=%d)",
        profile.dept, len(kept), filter_counts["no_link"], filter_counts["blocked_domain"],
        filter_counts["duplicate"], filter_counts["duplicate_role"],
        filter_counts["excluded"], filter_counts["too_old"],
    )

    capped = len(kept) > profile.candidate_cap
    kept, capped_out = fair_cap(kept, profile.candidate_cap)
    capped_out_counts: dict[str, int] = {}
    if capped:
        for p in capped_out:
            capped_out_counts[p.board] = capped_out_counts.get(p.board, 0) + 1
        log.warning("[%s] Capping candidates: %d -> %d (fair per-source). Dropped: %s",
                    profile.dept, len(kept) + len(capped_out), profile.candidate_cap,
                    ", ".join(f"{b}={n}" for b, n in sorted(capped_out_counts.items())))

    candidates = [p.to_candidate(now) for p in kept]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(candidates, indent=2))
    log.info("[%s] Wrote %d candidates to %s", profile.dept, len(candidates), out)

    report = {
        "dept": profile.dept,
        "profile_dir": str(profile.profile_dir),
        "run_at": now.isoformat(),
        "max_age_hours": max_age,
        "source_counts": source_counts,
        "filter_counts": filter_counts,
        "candidate_count": len(candidates),
        "capped": capped,
        "candidate_cap": profile.candidate_cap,
        "capped_out_counts": capped_out_counts,
        "candidates_file": str(out),
    }
    report_out.write_text(json.dumps(report, indent=2))
    log.info("[%s] Wrote run report to %s", profile.dept, report_out)
    return report


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    parser = argparse.ArgumentParser(description="job-search-engine Phase 1 (fetch)")
    parser.add_argument("--profile", required=True,
                        help="Department profile: a name under profiles/ or a path")
    parser.add_argument("--max-age", type=int, default=None,
                        help="Max posting age in hours (default: profile.max_age_hours)")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--report-out", type=Path, default=None)
    args = parser.parse_args()

    profile = load_profile(args.profile)
    report = run(profile, args.max_age, args.out, args.report_out)
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
