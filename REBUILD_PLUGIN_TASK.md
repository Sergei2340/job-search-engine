# Task: verify the 2026-07-06 engine changes and rebuild the plugin

Instruction for Claude Code. Working directory: this repo
(`C:\Users\user\Documents\Claude\Projects\job-search-engine`). Windows host —
use the `py` launcher (fall back to `python` if `py` is missing). Run all
commands from the repo root.

## Scope

Verify the engine changes made on 2026-07-06, bump the plugin version,
rebuild `job-search-engine.plugin`, verify the artifact, commit. Nothing else.

**Do NOT:**
- edit the substance of `engine/SKILL.md` or `engine/main.py` (they are the
  verified source of truth; if a check below fails, STOP and report — do not
  "fix" silently);
- touch the live pipeline projects (`uiux-lead-generation`, `Unity Lead
  Generation`) or the Cowork scheduled tasks;
- add department profiles: `profiles/` intentionally contains ONLY
  `_template` (privacy posture — private profiles must never enter this repo);
- push to any remote.

## Context — what changed on 2026-07-06 (see CHANGELOG.md)

1. `engine/main.py`: new `atomic_write_json()` (temp file + fsync +
   `os.replace`) replaced both `write_text` calls (candidates.json,
   last_run_report.json); `import os` added.
2. `engine/SKILL.md` Step 3.9: write_queue rotation rule (rotate at >~120 KB
   or >~400 entries; archive written/dropped >7 days; ONE entry per line;
   optional `_note`/`_archive` top-level keys; journal via file tools only).
3. `CHANGELOG.md`: new file with the 2026-07-06 entry.

The plugin build (`scripts/make_plugin.py`) merges `engine/SKILL.md` verbatim
into `skills/run-pipeline/SKILL.md` and ships `engine/` under
`assets/engine/`, so the current `job-search-engine.plugin` (built 2026-07-03,
v0.4.0) is stale on both counts.

## Step 1 — Review the diff

```
git status
git diff --stat
git diff engine/main.py engine/SKILL.md
```

Expected working-tree changes vs the last commit, and nothing else:
- `engine/main.py` — modified: `import os`; `atomic_write_json()` defined
  after the `log = logging.getLogger(...)` line; exactly two call sites
  (`atomic_write_json(out, candidates)` and
  `atomic_write_json(report_out, report)`); no `write_text` left on those
  two lines.
- `engine/SKILL.md` — modified: a "Rotation (added 2026-07-06)" block plus a
  `_note`/`_archive` paragraph inserted in "Step 3.9", before the
  "Before any write:" list. No other sections touched.
- `CHANGELOG.md` — new file.
- `REBUILD_PLUGIN_TASK.md` — new file (this instruction).

Any OTHER modified file, or unexpected content inside these diffs → STOP,
report what you see, ask before proceeding.

## Step 2 — Static checks

```
py -m py_compile engine\main.py
py -c "import ast,sys; t=ast.parse(open('engine/main.py',encoding='utf-8').read()); c=[n for n in ast.walk(t) if isinstance(n,ast.Call) and getattr(n.func,'id','')=='atomic_write_json']; w=[n for n in ast.walk(t) if isinstance(n,ast.Attribute) and n.attr=='write_text']; print('calls',len(c),'write_text',len(w)); sys.exit(0 if (len(c)==2 and len(w)==0) else 1)"
```

Pass criteria: compiles clean; output `calls 2 write_text 0`.

## Step 3 — Tests (offline, no network needed)

```
py -m tests.test_triage_filters
py -m tests.test_e2e_offline
py -m tests.test_serpapi_fetch_returns_list
```

(Equivalent: `py -m pytest -q tests` if pytest is installed.)

Pass criteria: all green. `test_e2e_offline` exercises the full Phase 1
`run()` including the new atomic writer — a regression there is a hard stop.
If a test needs a missing optional dep, install per `requirements.txt` into
the current environment; if `test_serpapi_fetch_returns_list` turns out to
require a live key, report that and treat the other two as gating.

## Step 4 — Version bump

In `plugin/.claude-plugin/plugin.json` bump `"version": "0.4.0"` → `"0.4.1"`
(patch: behavior-compatible hardening + doc rule). Leave everything else in
the manifest unchanged. The build stamps `assets/ENGINE_VERSION` from this
field automatically.

## Step 5 — Build

```
py scripts\make_plugin.py
```

Expected: a single line like
`OK: C:\...\job-search-engine\job-search-engine.plugin (NN files, ~65-75 KB)`.

- If it prints `PRIVACY GUARD FAILED` or `VALIDATION FAILED`: STOP. Report
  the listed problems verbatim. Do not strip or reword flagged content
  yourself — the guard list (`FORBIDDEN` in scripts/make_plugin.py) and the
  texts both change only with Sergei's sign-off.

## Step 6 — Verify the artifact

The `.plugin` file is a zip. Inspect WITHOUT unpacking over the repo:

```
py -c "
import zipfile, re, sys, datetime
z = zipfile.ZipFile('job-search-engine.plugin')
names = z.namelist()
def read(n): return z.read(n).decode('utf-8')
errs = []
# 1) merged run-pipeline skill carries the new rotation rule
rp = read('skills/run-pipeline/SKILL.md')
if 'Rotation (added 2026-07-06)' not in rp: errs.append('rotation rule missing in run-pipeline SKILL.md')
if not rp.startswith('---'): errs.append('run-pipeline frontmatter missing')
if '_note' not in rp: errs.append('_note/_archive convention missing')
# 2) shipped engine has the atomic writer
em = read('assets/engine/main.py')
if em.count('atomic_write_json') < 3: errs.append('atomic_write_json missing in assets/engine/main.py')
if 'out.write_text(json.dumps' in em: errs.append('old write_text still in assets/engine/main.py')
# 3) version stamp
ev = read('assets/ENGINE_VERSION')
if not ev.startswith('0.4.1'): errs.append('ENGINE_VERSION not 0.4.1: ' + ev.strip())
# 4) structural privacy re-check
bad = [n for n in names if n.endswith('.env') or n.split('/')[-1].startswith('oauth_') or '/state/' in n or (n.startswith('assets/profiles/') and not n.startswith('assets/profiles/_template'))]
if bad: errs.append('leaked paths: ' + ', '.join(bad))
print(len(names), 'files in zip')
print('FAIL:\n- ' + '\n- '.join(errs)) if errs else print('ARTIFACT OK')
sys.exit(1 if errs else 0)
"
```

Pass criteria: `ARTIFACT OK`.

Optional: refresh the unpacked inspection copy in `dist/job-search-engine/`
(it is not used by the build): delete its contents and extract the new zip
there.

## Step 7 — Commit and report

```
git add engine/main.py engine/SKILL.md CHANGELOG.md REBUILD_PLUGIN_TASK.md plugin/.claude-plugin/plugin.json job-search-engine.plugin dist/
git commit -m "Atomic Phase 1 writes + write_queue rotation rule; plugin 0.4.1

- engine/main.py: atomic_write_json (temp+fsync+os.replace) replaces write_text
- engine/SKILL.md Step 3.9: journal rotation rule (>~120KB/~400 entries),
  _note/_archive keys, one-entry-per-line dumps, file-tools-only journaling
- rebuild job-search-engine.plugin (0.4.0 -> 0.4.1), verified via zip inspection
- mirrors the 2026-07-06 fixes in the live uiux/Unity pipelines (see CHANGELOG)"
```

Final report to the user, short: diff review result, test results, build
line, artifact check result, commit hash. Remind them that the updated
`.plugin` must be re-installed in Cowork (Settings → Plugins) to take effect —
installed copies do not auto-update.

## Acceptance criteria (all must hold)

1. Diff contains only the expected changes (Step 1).
2. `py_compile` + AST check pass (Step 2).
3. Offline tests green (Step 3).
4. Version is 0.4.1; build prints `OK:`; privacy guard silent (Steps 4–5).
5. Zip inspection prints `ARTIFACT OK` (Step 6).
6. One commit containing exactly the files listed in Step 7.
