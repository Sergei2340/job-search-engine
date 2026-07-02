"""Config-driven title/role relevance gate.

The engine compiles the 5-step decision procedure from the profile's
`relevance_gate` block, so a department ships lists of patterns, not code.

Decision order (first hit wins):
  1. deny_titles    — TITLE matches → irrelevant. Checked first so an explicit
                      out-of-scope title beats any loose allow match.
  2. disambiguate   — TITLE matches an ambiguous pattern (e.g. "Product
                      Designer" digital-vs-physical): reject only when
                      reject_context hits the BODY and accept_context does NOT
                      hit title+body; otherwise accept (recall-favouring).
  3. allow_titles   — TITLE matches → relevant.
  4. weak_titles    — TITLE matches (e.g. bare "Designer" / "Engineer") →
                      relevant only with accept_context in title+body,
                      irrelevant otherwise (does NOT fall through).
  5. default        — irrelevant.

All regexes compile case-insensitive. The gate is a recall-favouring
precision backstop: it drops only postings that cannot be in scope; borderline
cases pass to Phase 2, which does the real 1-5 scoring.

Public API:
    RelevanceGate.from_config(cfg) -> RelevanceGate
    gate.classify(title, body="") -> Verdict(relevant: bool, reason: str)
    gate.is_relevant(title, body="") -> bool
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class GateConfigError(ValueError):
    """Raised when the profile's relevance_gate block is invalid."""


@dataclass(frozen=True)
class Verdict:
    relevant: bool
    reason: str

    def __bool__(self) -> bool:  # allow `if gate.classify(...):`
        return self.relevant


@dataclass(frozen=True)
class _Disambiguation:
    title: re.Pattern
    accept_context: re.Pattern | None
    reject_context: re.Pattern | None
    accept_reason: str
    reject_reason: str


@dataclass(frozen=True)
class _WeakTitle:
    title: re.Pattern
    accept_context: re.Pattern
    accept_reason: str
    reject_reason: str


def _compile(pattern: str, where: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.I)
    except re.error as exc:
        raise GateConfigError(f"relevance_gate.{where}: bad regex {pattern!r}: {exc}") from exc


class RelevanceGate:
    def __init__(
        self,
        deny: list[re.Pattern],
        disambiguate: list[_Disambiguation],
        allow: list[re.Pattern],
        weak: list[_WeakTitle],
        default_reason: str,
        allow_reason: str = "in-scope title",
    ) -> None:
        self._deny = deny
        self._disamb = disambiguate
        self._allow = allow
        self._weak = weak
        self._default_reason = default_reason
        self._allow_reason = allow_reason

    @classmethod
    def from_config(cls, cfg: dict) -> "RelevanceGate":
        if not isinstance(cfg, dict):
            raise GateConfigError("relevance_gate must be a mapping")
        deny = [_compile(p, "deny_titles") for p in cfg.get("deny_titles") or []]
        allow = [_compile(p, "allow_titles") for p in cfg.get("allow_titles") or []]

        disamb: list[_Disambiguation] = []
        for i, d in enumerate(cfg.get("disambiguate") or []):
            if "title" not in d:
                raise GateConfigError(f"disambiguate[{i}]: 'title' is required")
            disamb.append(_Disambiguation(
                title=_compile(d["title"], f"disambiguate[{i}].title"),
                accept_context=_compile(d["accept_context"], f"disambiguate[{i}].accept_context")
                if d.get("accept_context") else None,
                reject_context=_compile(d["reject_context"], f"disambiguate[{i}].reject_context")
                if d.get("reject_context") else None,
                accept_reason=d.get("accept_reason", "ambiguous title, accepted"),
                reject_reason=d.get("reject_reason", "ambiguous title, reject context"),
            ))

        weak: list[_WeakTitle] = []
        for i, w in enumerate(cfg.get("weak_titles") or []):
            if "title" not in w or "accept_context" not in w:
                raise GateConfigError(
                    f"weak_titles[{i}]: 'title' and 'accept_context' are required")
            weak.append(_WeakTitle(
                title=_compile(w["title"], f"weak_titles[{i}].title"),
                accept_context=_compile(w["accept_context"], f"weak_titles[{i}].accept_context"),
                accept_reason=w.get("accept_reason", "weak title with accept context"),
                reject_reason=w.get("reject_reason", "weak title without accept context"),
            ))

        if not (deny or allow or disamb or weak):
            raise GateConfigError(
                "relevance_gate defines no rules — every posting would be dropped")

        return cls(
            deny=deny,
            disambiguate=disamb,
            allow=allow,
            weak=weak,
            default_reason=cfg.get("default_reason", "no in-scope role signal in title"),
            allow_reason=cfg.get("allow_reason", "in-scope title"),
        )

    def classify(self, title: str, body: str = "") -> Verdict:
        t = (title or "").strip()
        low = t.lower()
        b = body or ""
        title_and_body = t + "\n" + b

        # 1) Explicit out-of-scope title wins outright.
        for pat in self._deny:
            m = pat.search(low)
            if m:
                return Verdict(False, f"out-of-scope title: {m.group(0)}")

        # 2) Ambiguous titles — disambiguate via body context.
        for d in self._disamb:
            if d.title.search(low):
                has_reject = bool(d.reject_context.search(b)) if d.reject_context else False
                has_accept = bool(d.accept_context.search(title_and_body)) if d.accept_context else False
                if has_reject and not has_accept:
                    return Verdict(False, d.reject_reason)
                return Verdict(True, d.accept_reason)

        # 3) Explicit in-scope titles.
        for pat in self._allow:
            if pat.search(low):
                return Verdict(True, self._allow_reason)

        # 4) Weak titles — require a supporting signal in title or body.
        for w in self._weak:
            if w.title.search(low):
                if w.accept_context.search(title_and_body):
                    return Verdict(True, w.accept_reason)
                return Verdict(False, w.reject_reason)

        # 5) No in-scope signal at all.
        return Verdict(False, self._default_reason)

    def is_relevant(self, title: str, body: str = "") -> bool:
        return self.classify(title, body).relevant
