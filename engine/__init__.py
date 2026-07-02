"""job-search-engine — department-agnostic lead-gen pipeline engine.

Two-phase architecture:
Phase 1 (this package, Python, Windows Task Scheduler) fetches and mechanically
filters job postings into profiles/<dept>/candidates.json; Phase 2 (Claude in
Cowork, engine/SKILL.md) scores them against profiles/<dept>/rubric.md and
writes kept rows to the department's Google Sheet.
"""
