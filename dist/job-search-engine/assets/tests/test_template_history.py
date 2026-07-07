"""Release-discipline guard: the current version's template snapshot and engine
manifest must exist and be in sync.

The update-to-latest-version skill 3-way-merges a deployed profile/rubric
against the template of ITS version (shipped in profiles/_template_history/).
For that base to exist for every future upgrade, each release must snapshot the
current template and ship a manifest. This test enforces it.

This test file ships into working folders too (make_plugin globs tests/*.py and
setup copies them), where none of the repo layout exists — so it SELF-SKIPS
outside the repo.

Run:  python -m tests.test_template_history
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN_JSON = REPO / "plugin" / ".claude-plugin" / "plugin.json"
HISTORY = REPO / "profiles" / "_template_history"
TEMPLATE = REPO / "profiles" / "_template"
MANIFESTS = REPO / "manifests"

# Only meaningful inside the plugin repo. In a deployed working folder these
# paths don't exist; skip cleanly rather than fail.
IN_REPO = PLUGIN_JSON.exists() and HISTORY.exists() and TEMPLATE.exists()


def _lf(p: Path) -> bytes:
    return p.read_bytes().replace(b"\r\n", b"\n")


@unittest.skipUnless(IN_REPO, "not in the plugin repo (shipped test, working-folder copy)")
class TemplateHistoryDiscipline(unittest.TestCase):
    def setUp(self):
        self.version = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]

    def test_current_version_snapshot_exists_and_matches_template(self):
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
                        f"missing manifests/{self.version}.sha256 — regenerate it "
                        f"(python scripts/make_plugin.py writes the shipped copy)")

    def test_manifests_are_wellformed(self):
        for m in MANIFESTS.glob("*.sha256"):
            for line in m.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                digest, _, path = line.partition("  ")
                self.assertRegex(digest, r"^[0-9a-f]{64}$", f"{m.name}: bad digest")
                self.assertTrue(path, f"{m.name}: missing path")


if __name__ == "__main__":
    unittest.main(verbosity=2)
