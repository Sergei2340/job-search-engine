"""Phase-1 company-size enrichment (0.6.0).

After the fetch/filter/cap pipeline, this module attaches a headcount bucket
(e.g. "51-200") to LinkedIn candidates by looking their company page up in
Bright Data's "LinkedIn companies — collect by URL" dataset
(gd_l1vikfnt1wgvvqz95w) via the same Datasets v3 trigger/poll API the jobs
source uses. Results feed the sheet's Headcount column (E) and the rubric's
Company-size rule.

DESIGN CONTRACT (do not regress — enforced by tests/test_company_enrich.py and
tests/test_e2e_offline.py):
- Never raises. Missing key / disabled / API failure / timeout → every posting
  keeps company_size=None and Phase 1 proceeds.
- Runs AFTER the fair cap, so only billed-worthy candidates trigger lookups.
- Persistent cache (state/company_size_cache.json) is the re-billing guard:
  a fresh cache hit is applied even without an API key, and a same-day re-run
  re-fetches only still-uncached companies. Company size changes slowly, so
  positive entries live ttl_days (default 180); companies that returned no
  data get a shorter negative-cache window (negative_ttl_days, default 30) so
  a dead/renamed page is not re-billed daily but is eventually retried.
- Staleness over blindness: when a refetch of an EXPIRED entry doesn't happen
  (no key, capped out, trigger/poll failure), the expired bucket is still
  applied as a fallback — a months-old size beats "Unknown"; it refreshes on
  the next successful fetch.
- Billing happens at TRIGGER time (like the jobs source). To avoid re-billing
  when a poll times out, the snapshot id is written to the cache as `_pending`
  the moment it is triggered; the next run polls that snapshot first and
  merges its (already-paid) records before triggering anything new.
- When no candidate carries a company_url, it returns immediately WITHOUT
  reading the environment, the cache file, or the network — this early return
  is what keeps the offline e2e test hermetic.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

from ._util import atomic_write_json
from .sources import canonical_url, linkedin_brightdata

log = logging.getLogger(__name__)

# "LinkedIn companies — collect by URL"
DEFAULT_DATASET_ID = "gd_l1vikfnt1wgvvqz95w"

# Defaults (a profile's enrichment.company_size block overrides these).
MAX_PER_RUN = 50            # cost guard: max UNCACHED companies fetched per run
TTL_DAYS = 180              # positive entries trusted this long
NEGATIVE_TTL_DAYS = 30      # no-data entries retried after this long
POLL_INTERVAL_SECONDS = 10
# Tighter than the jobs source's 900s: collect-by-URL of <=50 known pages is
# structurally faster than a live keyword discovery, and Phase 2 starts 30 min
# after Phase 1 — a 900s jobs poll + this must still land inside that window.
MAX_POLL_SECONDS = 240

_CACHE_NOTE = ("LinkedIn company-size cache (0.6.0). Safe to delete — the only "
               "cost is re-billing lookups ($1.5/1K records, 5K/month free).")

# Matches "51-200 employees", "5,001-10,000 employees", "10,001+ employees".
_BUCKET_RE = re.compile(r"^\s*([\d,]+\s*-\s*[\d,]+|[\d,]+\s*\+)\s*employees?\s*\.?\s*$", re.I)
# Fallback mapping from a raw employee count to the canonical LinkedIn buckets.
_EMP_BUCKETS = [(10, "1-10"), (50, "11-50"), (200, "51-200"), (500, "201-500"),
                (1000, "501-1,000"), (5000, "1,001-5,000"), (10000, "5,001-10,000")]


def _normalize_bucket(size, employees) -> str | None:
    """Bright Data `company_size` string (preferred) or `employees_in_linkedin`
    count → canonical bucket, or None. The size string is passed through
    verbatim (span only) rather than snapped to a whitelist, so LinkedIn label
    variants stay forward-compatible."""
    if size:
        m = _BUCKET_RE.match(str(size))
        if m:
            return re.sub(r"\s", "", m.group(1))   # "5,001-10,000 employees" -> "5,001-10,000"
    try:
        n = int(employees)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    for hi, label in _EMP_BUCKETS:
        if n <= hi:
            return label
    return "10,001+"


def _canonical_company_url(u: str) -> str:
    """Cache/join key for a LinkedIn company page. Collapses country subdomains
    (il.linkedin.com) and tracking query junk to a stable slug URL; falls back
    to the generic canonical_url for non-LinkedIn hosts."""
    parts = urlsplit((u or "").strip())
    host, path = (parts.netloc or "").lower(), parts.path or ""
    if host.endswith("linkedin.com") and "/company/" in path:
        slug = path.split("/company/", 1)[1].strip("/").split("/")[0].lower()
        if slug:
            return f"https://www.linkedin.com/company/{slug}"
    return canonical_url(u)


def _load_cache(path: Path) -> dict:
    """Resilient load (NUL-strip, {} on corruption — worst case one run
    re-bills), mirroring load_role_seen in main.py."""
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes().rstrip(b"\x00").decode("utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError) as exc:
        log.warning("company_size_cache.json unreadable (%s) — re-fetching this run", exc)
        return {}


def _cfg_int(cfg: dict, key: str, default: int) -> int:
    """Read an integer knob defensively: a garbage YAML value (ttl_days: abc)
    must degrade to the default with a warning, never crash the run."""
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        log.warning("enrichment.company_size.%s is not an integer (%r) — using %d",
                    key, cfg.get(key), default)
        return default


def _record_url(item: dict) -> str:
    inp = item.get("input")
    if isinstance(inp, dict) and inp.get("url"):
        return str(inp["url"])
    return str(item.get("url") or item.get("company_url") or "")


def _entry_from_record(item: dict, now: datetime) -> tuple[str, dict] | tuple[None, None]:
    cu = _canonical_company_url(_record_url(item))
    if not cu:
        return None, None
    today = now.date().isoformat()
    if (item.get("error") or item.get("warning")) and not item.get("company_size") \
            and not item.get("name"):
        return cu, {"bucket": None, "negative": True, "fetched_at": today}
    bucket = _normalize_bucket(item.get("company_size"), item.get("employees_in_linkedin"))
    if bucket:
        return cu, {"bucket": bucket,
                    "employees_in_linkedin": item.get("employees_in_linkedin"),
                    "name": item.get("name"),
                    "fetched_at": today}
    return cu, {"bucket": None, "negative": True, "fetched_at": today}


def _merge_records(records: list, entries: dict, now: datetime,
                   requested: set[str]) -> tuple[int, int]:
    """Update `entries` from snapshot records. URLs that were requested but
    absent from the snapshot get a negative entry (the dataset ran and skipped
    them). Returns (positive_count, negative_count)."""
    seen: set[str] = set()
    pos = neg = 0
    for item in records:
        if not isinstance(item, dict):
            continue
        cu, entry = _entry_from_record(item, now)
        if not cu:
            continue
        seen.add(cu)
        entries[cu] = entry
        if entry.get("bucket"):
            pos += 1
        else:
            neg += 1
    today = now.date().isoformat()
    for cu in requested - seen:
        # Don't clobber a good prior entry with a negative on a partial snapshot.
        if entries.get(cu, {}).get("bucket"):
            continue
        entries[cu] = {"bucket": None, "negative": True, "fetched_at": today}
        neg += 1
    return pos, neg


def _trigger_collect(key: str, dataset_id: str, urls: list[str]) -> str | None:
    params = {"dataset_id": dataset_id, "include_errors": "true"}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = [{"url": u} for u in urls]
    try:
        r = requests.post(linkedin_brightdata.TRIGGER_URL, headers=headers,
                          params=params, json=payload, timeout=30)
        r.raise_for_status()
        snap = (r.json() or {}).get("snapshot_id")
    except requests.RequestException as exc:
        log.error("Bright Data company trigger failed: %s", exc)
        return None
    except ValueError:
        log.error("Bright Data company trigger returned non-JSON body")
        return None
    if not snap:
        log.error("Bright Data company trigger returned no snapshot_id")
        return None
    log.info("Bright Data companies: triggered snapshot %s (%d urls)", snap, len(urls))
    return snap


def enrich_company_sizes(profile, postings: list, now: datetime | None = None) -> dict:
    """Attach LinkedIn company-size buckets to `postings` IN PLACE.

    Sets p.company_size on every posting whose company_url resolves in the
    cache or a fresh fetch; leaves it None otherwise. Never raises. Returns a
    stats dict for last_run_report.json.
    """
    now = now or datetime.now(timezone.utc)
    cfg = profile.enrichment_cfg("company_size")
    stats = {"enabled": bool(cfg.get("enabled", False)),  # default OFF when block absent
             "companies": 0, "cache_hits": 0, "cache_expired": 0,
             "fetched": 0, "no_data": 0, "capped_out": 0, "failed": None}
    if not stats["enabled"]:
        return stats

    # 1. Gather wanted companies. Early return (before env/cache/network) when
    #    nothing carries a company_url — keeps the offline e2e test hermetic.
    wanted: dict[str, list] = {}
    for p in postings:
        cu = _canonical_company_url(getattr(p, "company_url", "") or "")
        if cu:
            wanted.setdefault(cu, []).append(p)
    stats["companies"] = len(wanted)
    if not wanted:
        return stats

    cache_path = profile.company_size_cache_file
    cache = _load_cache(cache_path)
    cache.setdefault("_note", _CACHE_NOTE)
    entries: dict = cache.setdefault("entries", {})
    ttl_days = _cfg_int(cfg, "ttl_days", TTL_DAYS)
    neg_ttl_days = _cfg_int(cfg, "negative_ttl_days", NEGATIVE_TTL_DAYS)
    max_per_run = _cfg_int(cfg, "max_per_run", MAX_PER_RUN)
    max_poll = _cfg_int(cfg, "max_poll_seconds", MAX_POLL_SECONDS)
    dataset_id = cfg.get("dataset_id") or DEFAULT_DATASET_ID

    def _fresh(entry: dict) -> bool:
        ttl = neg_ttl_days if entry.get("negative") else ttl_days
        try:
            return (now.date() - date.fromisoformat(entry["fetched_at"])).days <= ttl
        except (KeyError, TypeError, ValueError):
            return False

    # 2. Apply fresh cache hits; collect misses. (Works without an API key.)
    misses: list[str] = []
    for cu, ps in wanted.items():
        entry = entries.get(cu)
        if entry and _fresh(entry):
            stats["cache_hits"] += 1
        else:
            if entry:
                stats["cache_expired"] += 1
            misses.append(cu)

    pending = cache.get("_pending") or {}
    if not misses and not pending.get("snapshot_id"):
        _apply(wanted, entries)
        return stats

    # 3. Everything past here needs the API key.
    key = os.environ.get("BRIGHTDATA_API_KEY") or os.environ.get("BRIGHT_DATA_API_KEY")
    if not key:
        log.warning("BRIGHTDATA_API_KEY not set; company-size enrichment skipped "
                    "(cache hits applied)")
        stats["failed"] = "no_key"
        _apply(wanted, entries)
        return stats

    changed = False

    # 3a. Recover an already-billed pending snapshot from a previous run first.
    if pending.get("snapshot_id"):
        recs = linkedin_brightdata._poll_snapshot(
            key, pending["snapshot_id"],
            poll_interval=POLL_INTERVAL_SECONDS, max_poll_seconds=max_poll)
        if recs:
            pos, neg = _merge_records(recs, entries, now, set(pending.get("urls") or []))
            stats["fetched"] += pos + neg
            stats["no_data"] += neg
            cache.pop("_pending", None)
            changed = True
            misses = [cu for cu in misses if not (entries.get(cu) and _fresh(entries[cu]))]
        else:
            # Still not ready — do NOT trigger a new snapshot (would stack /
            # re-bill). Persist nothing, retry the same snapshot next run.
            log.warning("Company-size: pending snapshot %s still not ready; "
                        "deferring new lookups", pending["snapshot_id"])
            stats["failed"] = "pending_not_ready"
            _apply(wanted, entries)
            return stats

    # 3b. Trigger the fresh misses (cost-capped, most-referenced companies first).
    if misses:
        misses.sort(key=lambda cu: len(wanted[cu]), reverse=True)
        batch = misses[:max_per_run]
        stats["capped_out"] = len(misses) - len(batch)
        snap = _trigger_collect(key, dataset_id, batch)
        if not snap:
            stats["failed"] = stats["failed"] or "trigger"
        else:
            # Trigger-time accounting: record the snapshot BEFORE polling so a
            # poll timeout is recovered (not re-billed) next run.
            cache["_pending"] = {"snapshot_id": snap, "triggered_at": now.isoformat(),
                                 "urls": batch}
            _save(cache_path, cache)
            changed = True
            recs = linkedin_brightdata._poll_snapshot(
                key, snap, poll_interval=POLL_INTERVAL_SECONDS, max_poll_seconds=max_poll)
            if recs:
                pos, neg = _merge_records(recs, entries, now, set(batch))
                stats["fetched"] += pos + neg
                stats["no_data"] += neg
                cache.pop("_pending", None)
            else:
                stats["failed"] = stats["failed"] or "poll_timeout"

    if changed:
        _save(cache_path, cache)
    _apply(wanted, entries)
    return stats


def _apply(wanted: dict, entries: dict) -> None:
    for cu, ps in wanted.items():
        bucket = (entries.get(cu) or {}).get("bucket")
        if bucket:
            for p in ps:
                p.company_size = bucket


def _save(path: Path, cache: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, cache)
    except OSError as exc:
        log.warning("Could not write company_size cache: %s", exc)
