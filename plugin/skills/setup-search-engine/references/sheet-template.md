# Google Sheet template (Step 3.3)

One spreadsheet per department. Header in row 1, data from row 2. The user
pastes this exact row into A1 (tab-separated — paste as one line into A1 and
it will spread across A1:Q1, 17 columns):

```
ID	Date Found	Title	Company	Headcount	Board	Region	Remote	Salary/Rate	Risk flags	Link	Comment/CV link	SM/PM	Status	Date Posted	Score	Reason
```

## Column semantics

| Col | Header | Written by | Notes |
|---|---|---|---|
| A | ID | pipeline | `<PREFIX>-NNNN`, sequential, never reused |
| B | Date Found | pipeline | `YYYY-MM-DD HH:MM` |
| C | Title | pipeline | canonical role title |
| D | Company | pipeline | never blank (`Unknown` as last resort) |
| E | Headcount | pipeline | employee-count bucket (`51-200`); `≈`-prefixed = model estimate (giants only); `Unknown` when unenriched — never blank |
| F | Board | pipeline | GoogleJobs / Indeed / LinkedIn |
| G | Region | pipeline | `Country, City` format |
| H | Remote | pipeline | Remote / Hybrid / On-site / Unknown |
| I | Salary/Rate | pipeline | never blank — `Not listed` if absent |
| J | Risk flags | pipeline | `;`-joined closed vocabulary |
| K | Link | pipeline | direct listing URL |
| L | Comment/CV link | **specialists (manual)** | pipeline NEVER touches |
| M | SM/PM | **specialists (manual)** | pipeline NEVER touches |
| N | Status | pipeline | `New` on write; humans update after |
| O | Date Posted | pipeline | `YYYY-MM-DD` or empty |
| P | Score | pipeline | integer 2–5 (score-1 never written) |
| Q | Reason | pipeline | one sentence, ≤ 15 words |

Headcount (E) is the sales-rep attractiveness signal at a glance: 11–500
answer outreach far more often (sweet spot 50–200); giants (`10,001+`,
`≈`-buckets) almost never answer. It surfaces the same fact the score already
prices in, so reps can prioritize without decoding the score. `≈`-prefixed
values are Phase-2 estimates for recognized giants, not enrichment output.

Column L doubles as the feedback loop: specialists note "paywall", "dead
link", "reposted stale job", "needs native German" there — during calibration
those feed `state/blocked_domains.json` and the rubric's negative signals.

## Migrating a pre-0.6.0 sheet (16 columns, A1:P1)

A sheet created before 0.6.0 has no Headcount column. The Phase-2 writer
refuses to write until E1 reads `Headcount` (it would otherwise shift every
value one column and clobber the manual columns), so migrate BEFORE the next
scheduled run — ideally in one window:

1. **Pause** the `<dept>-jobs-pipeline` scheduled Phase-2 task (and hold the
   Phase-1 Task Scheduler run) so no write lands mid-migration.
2. Right-click the column-E header (currently **Board**) → **Insert 1 column
   left**. Existing data from Board onward shifts right automatically —
   Sheets rewrites filters/references itself; no data is touched. The manual
   columns move from K/L to L/M; their contents ride along.
3. Type `Headcount` into the new empty `E1`.
4. Update the plugin to 0.6.0 (so the run-pipeline skill writes the A–Q
   layout) and re-enable the schedules.
5. Nothing else changes: state files (`seen_urls`, `role_seen`,
   `write_queue`) key on URLs and roles, not column letters — leave them
   alone. Lead IDs in column A are unaffected. Rows already written keep a
   blank E (history); any still-`pending` pre-0.6.0 `write_queue` entries are
   written with `Unknown` in E on the next run.
