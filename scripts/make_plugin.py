"""Assemble the distributable job-search-engine .plugin from this repo.

Single source of truth: engine code and engine/SKILL.md live once in the repo;
this script stages them into the plugin layout, runs a PRIVACY GUARD, and zips.

    python scripts/make_plugin.py [--out /path/to/dir]

Staged layout:
    .claude-plugin/plugin.json
    README.md
    skills/setup-search-engine/{SKILL.md,references/*}
    skills/run-pipeline/SKILL.md      = _frontmatter.md + engine/SKILL.md
    skills/troubleshoot-pipeline/SKILL.md
    assets/engine/**                  (code + SKILL.md + run_fetch.ps1)
    assets/scripts/get_oauth_token.py
    assets/profiles/_template/**
    assets/tests/*.py                 (all tracked tests)
    assets/requirements.txt, assets/.gitignore, assets/README.md
    assets/ENGINE_VERSION

Privacy guard: fails the build if any staged text file contains a forbidden
token (department-private data), or if profiles other than _template, .env,
oauth files, or state/ leak into staging.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Department-private tokens that must NEVER ship. Extend when new departments'
# specifics enter the repo. Case-insensitive.
FORBIDDEN = [
    "1hqUYl5rVjdh",          # uiux spreadsheet id (prefix)
    "siarhei", "malchanau",   # owner email
    "moneybox", "twine", "tailscale", "compliancequest", "azumo",  # lead companies
    "LEAD-0191", "LEAD-0104", "LEAD-0105", "LEAD-0003", "LEAD-0087",
    "LEAD-0091", "LEAD-0130", "LEAD-0161",  # concrete lead ids
    "ixdf.org", "remotejobs.org",            # curated blocklist entries (dept state)
]

TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".ps1", ".txt", ".gitignore", ""}


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def stage(staging: Path) -> None:
    # 1) Plugin skeleton (skills, manifest, README) — except merge helpers.
    for src in (REPO / "plugin").rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(REPO / "plugin")
        if rel.parts[0] == "assets-extra" or src.name == "_frontmatter.md":
            continue
        _copy(src, staging / rel)

    # 2) run-pipeline skill = frontmatter + engine/SKILL.md (verbatim).
    front = (REPO / "plugin/skills/run-pipeline/_frontmatter.md").read_text(encoding="utf-8")
    body = (REPO / "engine/SKILL.md").read_text(encoding="utf-8")
    out = staging / "skills/run-pipeline/SKILL.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(front.rstrip() + "\n\n" + body, encoding="utf-8", newline="\n")

    # 3) Assets: engine code (no pycache), scripts, template profile, tests.
    for src in (REPO / "engine").rglob("*"):
        if src.is_file() and "__pycache__" not in src.parts:
            _copy(src, staging / "assets/engine" / src.relative_to(REPO / "engine"))
    _copy(REPO / "scripts/get_oauth_token.py", staging / "assets/scripts/get_oauth_token.py")
    for src in (REPO / "profiles/_template").rglob("*"):
        if src.is_file():
            _copy(src, staging / "assets/profiles/_template" / src.relative_to(REPO / "profiles/_template"))
    for src in sorted((REPO / "tests").glob("*.py")):
        _copy(src, staging / "assets/tests" / src.name)
    _copy(REPO / "requirements.txt", staging / "assets/requirements.txt")
    _copy(REPO / ".gitignore", staging / "assets/.gitignore")
    _copy(REPO / "plugin/assets-extra/README.md", staging / "assets/README.md")

    version = json.loads((REPO / "plugin/.claude-plugin/plugin.json").read_text())["version"]
    (staging / "assets/ENGINE_VERSION").write_text(
        f"{version} ({date.today().isoformat()})\n", encoding="utf-8", newline="\n"
    )


def privacy_guard(staging: Path) -> list[str]:
    problems: list[str] = []
    pat = re.compile("|".join(re.escape(t) for t in FORBIDDEN), re.I)
    for f in staging.rglob("*"):
        if not f.is_file():
            continue
        rel = str(f.relative_to(staging))
        # Structural leaks
        if f.name == ".env" or f.name.startswith("oauth_"):
            problems.append(f"secret file staged: {rel}")
        if "/state/" in rel.replace("\\", "/"):
            problems.append(f"state dir staged: {rel}")
        if re.search(r"assets/profiles/(?!_template)", rel.replace("\\", "/")):
            problems.append(f"non-template profile staged: {rel}")
        # Content leaks
        if f.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in pat.finditer(text):
                problems.append(f"forbidden token {m.group(0)!r} in {rel}")
    return problems


def validate(staging: Path) -> list[str]:
    errs: list[str] = []
    manifest = staging / ".claude-plugin/plugin.json"
    if not manifest.exists():
        return ["missing .claude-plugin/plugin.json"]
    data = json.loads(manifest.read_text())
    name = data.get("name", "")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
        errs.append(f"plugin name not kebab-case: {name!r}")
    for skill_dir in (staging / "skills").iterdir():
        if skill_dir.is_dir() and not (skill_dir / "SKILL.md").exists():
            errs.append(f"skill without SKILL.md: {skill_dir.name}")
        elif skill_dir.is_dir():
            text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            if not text.startswith("---"):
                errs.append(f"SKILL.md missing frontmatter: {skill_dir.name}")
                continue
            fm = text.split("---", 2)[1]
            m = re.search(r"^description:\s*(.+)$", fm, re.M)
            if not m:
                errs.append(f"SKILL.md missing description: {skill_dir.name}")
            elif re.search(r"<[^>]+>", m.group(1)):
                # Cowork's installer rejects XML-tag-looking text in descriptions
                errs.append(f"SKILL.md description contains XML-like tags: {skill_dir.name}")
            nm = re.search(r"^name:\s*(.+)$", fm, re.M)
            if nm and nm.group(1).strip() != skill_dir.name:
                errs.append(f"frontmatter name {nm.group(1).strip()!r} != dir {skill_dir.name!r}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=REPO)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as td:
        staging = Path(td) / "job-search-engine"
        stage(staging)

        problems = privacy_guard(staging)
        if problems:
            print("PRIVACY GUARD FAILED:")
            for p in problems:
                print("  -", p)
            return 1
        errs = validate(staging)
        if errs:
            print("VALIDATION FAILED:")
            for e in errs:
                print("  -", e)
            return 1

        out_file = args.out / "job-search-engine.plugin"
        tmp_zip = Path(td) / "job-search-engine.plugin"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(staging.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(staging))
        shutil.copy2(tmp_zip, out_file)
        n_files = sum(1 for f in staging.rglob("*") if f.is_file())
        print(f"OK: {out_file} ({n_files} files, {out_file.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
