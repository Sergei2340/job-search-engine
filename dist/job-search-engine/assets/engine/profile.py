"""Department profile: one YAML per department + engine-level defaults.

A profile directory (profiles/<dept>/) contains everything department-specific:

    profile.yaml   — search queries, relevance gate, sheet, caps, schedule
    rubric.md      — Phase 2 scoring rubric (read by the Cowork SKILL, not here)
    .env           — SERPAPI_KEY / BRIGHTDATA_API_KEY / SHEET_URL
    oauth_client.json / oauth_token.json — Sheets write auth (Phase 2)
    state/         — seen_urls.json, role_seen.json, write_queue.json,
                     linkedin_state.json, blocked_domains.json
    candidates.json / last_run_report.json — Phase 1 output (runtime)
    reports/, logs/ — Phase 2 execution reports, Phase 1 fetch logs

Everything NOT in the profile (filter mechanics, source connectors, Phase 2
write mechanics) lives in engine/ and is shared by all departments — fix once,
every department gets it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .relevance import RelevanceGate

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = REPO_ROOT / "profiles"


class ProfileError(ValueError):
    """Raised when profile.yaml is missing required fields or malformed."""


# ---------------------------------------------------------------------------
# Engine-level defaults (department-neutral). Profiles may EXTEND the lists
# via `extra_*` keys; they should not need to override them.
# ---------------------------------------------------------------------------

# Noise tokens stripped from titles during role-level dedup: reposts of one
# role come out as "UI Designer (Remote)" / "Remote UI Designer - Freelance
# Role". Seniority is NOT stripped — junior and senior are different
# vacancies. m/w/d, m/f/x, d/f/m leftovers included.
TITLE_NOISE_TOKENS: frozenset[str] = frozenset({
    "remote", "fully", "freelance", "contract", "contractor", "role",
    "position", "job", "opportunity", "urgent", "hiring", "wanted",
    "m", "w", "d", "f", "x",
})

# Aggregators whose posting dates can't be trusted: they repost month-old jobs
# with fresh-looking dates ("1/10 month old" in specialists' K-comments despite
# the <=24h rule; 2026-07-02 review). Their postings get date_posted=None +
# date_suspect=True.
UNRELIABLE_DATE_DOMAINS: frozenset[str] = frozenset({
    "bebee.com",
    "nafezly.com",
    "up2staff.com",
    "studysmarter.co.uk",       # talents.studysmarter.co.uk
    "womenforhire.com",         # jobs.womenforhire.com
})

# Hosts dropped from SerpAPI results regardless of how legit the title looks.
# linkedin: covered by the Bright Data source (Google can't crawl it reliably).
# upwork: freelance rates an order below outsourcing pricing; login-gated.
# liveblog365/metaintro/up.railway.app: job-spam cloaking network (2026-06-30).
# cosmoquick: serves aggregator category pages, never a single posting.
SERPAPI_EXCLUDED_HOSTS: tuple[str, ...] = (
    "linkedin", "upwork", "liveblog365", "metaintro", "up.railway.app", "cosmoquick",
)


def load_env_file(path: Path) -> None:
    """Stdlib-only .env loader (no python-dotenv dep). setdefault semantics."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Profile:
    dept: str
    display_name: str
    id_prefix: str
    sheet: dict
    profile_dir: Path
    gate: RelevanceGate
    sources: dict
    candidate_cap: int = 100
    max_age_hours: int = 24
    role_seen_window_days: int = 30
    alert_email: str = ""
    excluded_companies: frozenset[str] = frozenset()
    title_noise_tokens: frozenset[str] = TITLE_NOISE_TOKENS
    unreliable_date_domains: frozenset[str] = UNRELIABLE_DATE_DOMAINS
    serpapi_excluded_hosts: tuple[str, ...] = SERPAPI_EXCLUDED_HOSTS
    raw: dict = field(default_factory=dict)

    # --- Paths (single source of truth for both phases) -------------------
    @property
    def state_dir(self) -> Path:
        return self.profile_dir / "state"

    @property
    def seen_urls_file(self) -> Path:
        return Path(os.environ.get("SEEN_URLS_FILE") or (self.state_dir / "seen_urls.json"))

    @property
    def role_seen_file(self) -> Path:
        return self.state_dir / "role_seen.json"

    @property
    def blocked_domains_file(self) -> Path:
        return self.state_dir / "blocked_domains.json"

    @property
    def linkedin_state_file(self) -> Path:
        return self.state_dir / "linkedin_state.json"

    @property
    def candidates_file(self) -> Path:
        return self.profile_dir / "candidates.json"

    @property
    def report_file(self) -> Path:
        return self.profile_dir / "last_run_report.json"

    def source_cfg(self, name: str) -> dict:
        return self.sources.get(name) or {}

    def source_enabled(self, name: str) -> bool:
        cfg = self.source_cfg(name)
        return bool(cfg) and bool(cfg.get("enabled", True))


def resolve_profile_dir(name_or_path: str) -> Path:
    """Accept a bare department name ('python') or a path to a profile dir."""
    p = Path(name_or_path)
    if p.is_dir() and (p / "profile.yaml").exists():
        return p.resolve()
    candidate = PROFILES_DIR / name_or_path
    if (candidate / "profile.yaml").exists():
        return candidate.resolve()
    raise ProfileError(
        f"Profile {name_or_path!r} not found: no profile.yaml in {p} or {candidate}")


def load_profile(name_or_path: str, *, load_env: bool = True) -> Profile:
    profile_dir = resolve_profile_dir(name_or_path)
    yaml_path = profile_dir / "profile.yaml"
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProfileError(f"{yaml_path}: invalid YAML: {exc}") from exc

    for req in ("dept", "id_prefix", "sheet", "relevance_gate", "sources"):
        if req not in data:
            raise ProfileError(f"{yaml_path}: required key {req!r} is missing")
    if not (data["sheet"] or {}).get("spreadsheet_id"):
        raise ProfileError(f"{yaml_path}: sheet.spreadsheet_id is required")

    gate = RelevanceGate.from_config(data["relevance_gate"])

    if load_env:
        load_env_file(profile_dir / ".env")

    filters = data.get("filters") or {}
    return Profile(
        dept=str(data["dept"]),
        display_name=str(data.get("display_name") or data["dept"]),
        id_prefix=str(data["id_prefix"]).rstrip("-"),
        sheet=data["sheet"],
        profile_dir=profile_dir,
        gate=gate,
        sources=data["sources"] or {},
        candidate_cap=int(data.get("candidate_cap", 100)),
        max_age_hours=int(data.get("max_age_hours", 24)),
        role_seen_window_days=int(data.get("role_seen_window_days", 30)),
        alert_email=str(data.get("alert_email") or ""),
        excluded_companies=frozenset(
            str(c).strip().lower() for c in (filters.get("excluded_companies") or [])),
        title_noise_tokens=TITLE_NOISE_TOKENS | frozenset(
            str(t).lower() for t in (filters.get("extra_title_noise_tokens") or [])),
        unreliable_date_domains=UNRELIABLE_DATE_DOMAINS | frozenset(
            str(d).lower() for d in (filters.get("extra_unreliable_date_domains") or [])),
        serpapi_excluded_hosts=SERPAPI_EXCLUDED_HOSTS + tuple(
            str(h).lower() for h in (filters.get("extra_serpapi_excluded_hosts") or [])),
        raw=data,
    )
