# Google Sheet template (Step 3.3)

One spreadsheet per department. Header in row 1, data from row 2. The user
pastes this exact row into A1 (tab-separated — paste as one line into A1 and
it will spread across A1:P1):

```
ID	Date Found	Title	Company	Board	Region	Remote	Salary/Rate	Risk flags	Link	Comment/CV link	SM/PM	Status	Date Posted	Score	Reason
```

## Column semantics

| Col | Header | Written by | Notes |
|---|---|---|---|
| A | ID | pipeline | `<PREFIX>-NNNN`, sequential, never reused |
| B | Date Found | pipeline | `YYYY-MM-DD HH:MM` |
| C | Title | pipeline | canonical role title |
| D | Company | pipeline | never blank (`Unknown` as last resort) |
| E | Board | pipeline | GoogleJobs / Indeed / LinkedIn / WeWorkRemotely / RemoteOK |
| F | Region | pipeline | `Country, City` format |
| G | Remote | pipeline | Remote / Hybrid / On-site / Unknown |
| H | Salary/Rate | pipeline | never blank — `Not listed` if absent |
| I | Risk flags | pipeline | `;`-joined closed vocabulary |
| J | Link | pipeline | direct listing URL |
| K | Comment/CV link | **specialists (manual)** | pipeline NEVER touches |
| L | SM/PM | **specialists (manual)** | pipeline NEVER touches |
| M | Status | pipeline | `New` on write; humans update after |
| N | Date Posted | pipeline | `YYYY-MM-DD` or empty |
| O | Score | pipeline | integer 2–5 (score-1 never written) |
| P | Reason | pipeline | one sentence, ≤ 15 words |

Column K doubles as the feedback loop: specialists note "paywall", "dead
link", "reposted stale job", "needs native German" there — during calibration
those feed `state/blocked_domains.json` and the rubric's negative signals.
