# Scoring rubric — <Department> (Innowise)

Department-specific half of Phase 2. The mechanics (chunking, queue, sheet
write, reports) live in `engine/SKILL.md`. Keep the section structure below
so fixes port cleanly across departments.

## Business context

Innowise sells **<service> outsourcing / staff augmentation**. A lead is a
company hiring a <role> — Innowise responds by placing a specialist
(contractor / staff-aug) or pitching a team engagement. Score each posting as a
**potential client**; the role must be one Innowise can answer with a
**specialist's CV** ("vacancy → prepare CV → apply").

<!-- Vendor exclusion: does this domain have an "engine vendor" that can never
be a lead (e.g. the platform's own vendor)? If yes, state it here AND add it to
profile.yaml filters.excluded_companies. If no, say so explicitly. -->

## Score 1 — disqualified. Not written.

Use only when clearly disqualified:

- Role is out of scope per the Role-type policy below.
- Announced salary clearly < $50k USD equivalent per year.
- Pure on-site outside the wealthy-region list below.
- Hobbyist / unpaid / rev-share-only / internship with no pay.
- Internal-only or employee-referral-only posting.
- Duplicate of another candidate in the same chunk (same company + normalized
  title — ignore location differences).
- **Cumulative triage rule:** TWO OR MORE hard negative signals stack up. One
  hard negative alone NEVER gives score 1 — it downgrades (see below).

## Hard negative signals

Each costs **−1 from the base score (floor 2)** and must be recorded in
`risk_flags`. Two or more together → score 1 (cumulative rule above).

| Signal | What to detect in `raw_content` | risk_flag |
|---|---|---|
| Strict on-site | "on-site only", "no remote", ≥4 office days/week | `on-site-strict` |
| Remote-but-geo | "US only", "must reside in …", "no visa sponsorship" | `geo:<cc>` |
| Local language required | native/fluent/C1+ non-English (see DACH rule) | `lang:<code>` |
| Hybrid skill demands | <role must ALSO do a second unrelated specialism — define per department> | `hybrid-skills` |
| Mandatory credentials | required degree, background/credit check, clearance | `degree` / `clearance` |
| Suspect posting date | `"date_suspect": true` from Phase 1 | `date-suspect` |

Soft negatives (−1, do NOT count toward score 1): hybrid ≤3 office days;
org-level purely managerial "star" roles; fixed-term/maternity covers.

Downgrades apply AFTER the base score (2–5) is set by the positive rubric.

## DACH language rule

Any posting with `m/w/d`, `m/f/x`, `d/f/m`, `w/m/d` markers, a German-language
body, or a DACH company/location: actively scan for a German requirement.
Body written in German → `lang:de` automatically.

## Score 2 — minimum bar

- **Role:** in scope per the Role-type policy (any seniority unless stated).
- **Work model:** Remote OR Hybrid (pure on-site disqualifies unless in a
  wealthy region).
- **Region:** EU, UK, US, Canada, Australia/NZ, Nordics, Switzerland, Israel,
  Singapore, Japan, South Korea, Gulf states, or similar wealthy economies.
- **Salary:** ≥ $50k USD equivalent, OR not announced (absent salary is fine —
  never reject for missing salary).

## Score 3

Meets all score-2 criteria, no red flags. Baseline "fine lead."

## Score 4

Score-3 + a concrete positive signal: well-funded or well-known company,
senior/lead role, clear scope, mature engineering org.

## Score 5

Score-3 + an **outsourcing / staff-aug / agency signal**: contract / freelance /
contract-to-hire / "open to contractors" / "external partners welcome" /
staffing-pattern language; OR the employer is an agency / dev-shop /
consultancy hiring in-house (they may subcontract). Highest-priority leads.

## Role-type policy (precision backstop after the Phase-1 gate)

| Role family | Examples | Verdict |
|---|---|---|
| <core in-scope roles> | ... | Full lead — score 2–5 |
| <hands-on lead roles> | ... | Full lead |
| <org-level managerial> | ... | **Cap at score 2**, reason notes `company-signal` |
| <adjacent-but-out roles> | ... | **Score 1** |
| Non-<domain> | PM, marketer, recruiter | **Score 1** |

The agency score-5 rule applies **only to Full-lead roles**.

## Explicit bias instruction

**When uncertain about a qualifying attribute, score 2 or 3 rather than 1.**
Recall > precision. If `raw_content` is thin, default to 2 with reason
"insufficient signal, flagged for human review". This bias does NOT override
the Role-type policy — a clearly out-of-scope role is score 1.
