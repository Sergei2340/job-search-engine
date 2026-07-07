"""Release-discipline guard: the current version's template snapshot, engine
manifest, and (when the template changed) migrations.md entry must exist and be
in sync.

The update-to-latest-version skill 3-way-merges a deployed profile/rubric
against the template of ITS version (shipped in profiles/_template_history/)
and selects pending migrations from its references/migrations.md. For those
inputs to exist for every future upgrade, each release must snapshot the
template, ship a manifest, and register its migration. This test enforces it.

This test file ships into working folders too (make_plugin globs tests/*.py and
setup copies them), where the plugin repo layout does not exist — so it
SELF-SKIPS there. The skip keys ONLY on plugin/.claude-plugin/plugin.json
(never present in a working folder): a missing profiles/_template_history/ or
profiles/_template/ inside the repo is a FAILURE this test exists to catch,
not a reason to skip.

Run:  python -m tests.test_template_history
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN_JSON = REPO / "plugin" / ".claude-plugin" / "plugin.json"
HISTORY = REPO / "profiles" / "_template_history"
TEMPLATE = REPO / "profiles" / "_template"
MANIFESTS = REPO / "manifests"
MIGRATIONS = (REPO / "plugin" / "skills" / "update-to-latest-version"
              / "references" / "migrations.md")


def _lf(p: Path) -> bytes:
    return p.read_bytes().replace(b"\r\n", b"\n")


def _ver_key(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


@unittest.skipUnless(PLUGIN_JSON.exists(),
                     "not in the plugin repo (shipped test, working-folder copy)")
class TemplateHistoryDiscipline(unittest.TestCase):
    def setUp(self):
        self.version = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]

    def test_current_version_snapshot_exists_and_matches_template(self):
        self.assertTrue(TEMPLATE.is_dir(), "profiles/_template/ is missing")
        self.assertTrue(HISTORY.is_dir(),
                        "profiles/_template_history/ is missing — the update "
                        "skill's 3-way merge bases live there")
        snap = HISTORY / self.version
        self.assertTrue(snap.is_dir(),
                        f"missing profiles/_template_history/{self.version}/ — "
                        f"snapshot the template when bumping the version")
        for src in TEMPLATE.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(TEMPLATE)
            snap_file = snap / rel
            self.assertTrue(snap_file.is_file(), f"snapshot missing {rel}")
            self.assertEqual(_lf(snap_file), _lf(src),
                             f"snapshot {self.version}/{rel} differs from the live template")

    def test_current_version_manifest_exists(self):
        self.assertTrue((MANIFESTS / f"{self.version}.sha256").is_file(),
                        f"missing manifests/{self.version}.sha256 — run "
                        f"python scripts/make_plugin.py (it creates the missing "
                        f"copy) and commit it")

    def test_manifests_are_wellformed(self):
        self.assertTrue(MANIFESTS.is_dir(), "manifests/ is missing")
        for m in MANIFESTS.glob("*.sha256"):
            for line in m.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                digest, _, path = line.partition("  ")
                self.assertRegex(digest, r"^[0-9a-f]{64}$", f"{m.name}: bad digest")
                self.assertTrue(path, f"{m.name}: missing path")

    def test_migrations_entry_exists_when_template_changed(self):
        """A template change with no migrations.md entry is self-erasing data
        loss: U2 never proposes it, and after the version stamps, later merge
        bases contain the change so its absence reads as a user deletion."""
        self.assertTrue(HISTORY.is_dir(), "profiles/_template_history/ is missing")
        vers = sorted((d.name for d in HISTORY.iterdir() if d.is_dir()), key=_ver_key)
        self.assertIn(self.version, vers, "current snapshot missing (see other test)")
        idx = vers.index(self.version)
        if idx == 0:
            self.skipTest("no previous snapshot to compare against")
        prev, cur = HISTORY / vers[idx - 1], HISTORY / self.version
        prev_names = {p.name for p in prev.iterdir() if p.is_file()}
        cur_names = {p.name for p in cur.iterdir() if p.is_file()}
        changed = prev_names != cur_names or any(
            _lf(cur / n) != _lf(prev / n) for n in cur_names)
        if not changed:
            self.skipTest(f"template unchanged since {vers[idx - 1]}")
        self.assertTrue(MIGRATIONS.is_file(), "migrations.md is missing")
        self.assertIn(f"→ {self.version}",
                      MIGRATIONS.read_text(encoding="utf-8"),
                      f"template changed since {vers[idx - 1]} but "
                      f"migrations.md has no '→ {self.version}' entry — the "
                      f"change would be invisible to every future upgrade")


if __name__ == "__main__":
    unittest.main(verbosity=2)
