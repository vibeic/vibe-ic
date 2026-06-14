#!/usr/bin/env python3
"""
ic_class_consistency_check.py — gate (Wave 42, v0.119.70 / SF6).

Wave 42 / SF6 — fault-injection hardening for facts.yaml.

Background
==========
The third-round fault-injection audit (agent
`a38d56dfe53d7bd11`) demonstrated that an attacker could write
mis-leading scalars into `facts.yaml` (e.g. claim
`ic_class: pure_analog` on a UART-driven digital chip, or set
`no_command_protocol: true` on an AID-class device) and silence
the matching gates. None of the Wave 36 / Wave 37 gates
cross-checked the asserted facts.yaml fields against what the L
docs / RTL actually said.

This gate closes that gap. It is the canonical owner of the
facts.yaml ↔ L-docs ↔ RTL three-way consistency contract.

Behaviour
=========
1. Parse `<project>/facts.yaml` with PyYAML (top-level only).
2. Run `detect_ic_class(<project>)` — returns the inferred profile
   from L1..L13 + RTL.
3. Compare:
     - If facts.yaml carries a top-level `ic_class:` value, it must
       equal the inferred class. Any mismatch → FAIL.
     - For each escape boolean (`no_command_protocol`, `no_fsm`,
       `no_calibration`, `no_analog`), if the boolean is set
       `true` but the inferred profile says the feature IS present,
       FAIL.
     - If facts.yaml claims `phase1_skipped_path_a: true` but
       `<project>/input/docs/` contains vendor docs, FAIL.
4. If facts.yaml is missing or empty AND no L docs / RTL exist,
   the gate emits a silent SKIP (bare-skeleton project).
5. Otherwise PASS — emit a one-line confirmation including the
   detected class.

Usage
-----
    python3 ic_class_consistency_check.py <project_dir>

Exit codes: 0 = PASS / SKIP, 1 = FAIL, 2 = input error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import _path_layout as _pl

# Wave 42 — programs/ on sys.path so sibling imports work no matter
# how this script is invoked.
_PROG_DIR = str(Path(__file__).resolve().parent)
if _PROG_DIR not in sys.path:
    sys.path.insert(0, _PROG_DIR)

from _facts_yaml import read_facts_yaml, get_top_level_truthy  # noqa: E402
from ic_class_profile import detect_ic_class  # noqa: E402


_VENDOR_DOC_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".xlsx", ".pptx", ".txt", ".csv",
    ".json", ".xml", ".md",
}
_VENDOR_DOC_NAME_BLACKLIST = {
    "readme.md", ".gitkeep", ".keep", ".placeholder",
}


def _vendor_docs_in_input(project: Path) -> list[Path]:
    docs_dir = project / "input" / "docs"
    if not docs_dir.is_dir():
        return []
    out: list[Path] = []
    for f in docs_dir.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in _VENDOR_DOC_SUFFIXES:
            continue
        if f.name.lower() in _VENDOR_DOC_NAME_BLACKLIST:
            continue
        out.append(f)
    return out


_L_DOC_SUBDIRS = ("phase1/generated_docs", "generated_docs", "l_docs")


def _stamped_l_doc_classes(project: Path) -> list[tuple[str, str]]:
    """Return [(relative_path, stamped_ic_class), ...] for every L*.json
    generated doc that carries a non-empty top-level ``ic_class`` string.

    ORGANIC-20260614 (#635): the L14-L23 skeletons emitted by
    ``phase1_post_process.emit_l_doc_skeleton`` stamp an ``ic_class`` field.
    Because the skeletons are stamped during phase1 — BEFORE phase2 persists
    the authoritative ``reports/ic_class.json`` — the stamped value can be a
    fail-closed fallback that diverges from the true class and is never
    re-stamped. This gate is the canonical owner of the per-L-doc ic_class
    stamp, so it must read it.

    Docs that legitimately omit ``ic_class`` (or carry a non-string/empty
    value) are skipped — only a CONCRETE divergent stamp is a violation.
    chip-AGNOSTIC: a structural field comparison, never a chip/SKU literal.
    """
    out: list[tuple[str, str]] = []
    seen: set[Path] = set()
    for sub in _L_DOC_SUBDIRS:
        d = project / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("L*.json")):
            rp = f.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Unreadable / malformed doc — not this gate's concern.
                continue
            if not isinstance(doc, dict):
                continue
            stamped = doc.get("ic_class")
            if not isinstance(stamped, str) or not stamped.strip():
                # Legitimately omits ic_class → SKIP this doc.
                continue
            try:
                rel = str(f.relative_to(project))
            except ValueError:
                rel = f.name
            out.append((rel, stamped.strip()))
    return out


def inspect(project_dir: Path) -> tuple[int, list[str]]:
    """Return (exit_code, message_lines)."""
    project = Path(project_dir)
    if not project.is_dir():
        return 2, [f"FAIL — project dir not found: {project}"]

    profile = detect_ic_class(project)
    facts = read_facts_yaml(project)

    issues: list[str] = []

    # 1. Bare-skeleton silent skip.
    has_l_docs = any(
        (project / sub).is_dir()
        and any((project / sub).glob("L*.json"))
        for sub in ("phase1/generated_docs", "generated_docs", "l_docs")
    )
    has_rtl = (_pl.rtl_dir(project)).is_dir() and bool(
        list((_pl.rtl_dir(project)).rglob("*.v"))
        + list((_pl.rtl_dir(project)).rglob("*.sv"))
    )
    if not facts and not has_l_docs and not has_rtl:
        return 0, [
            "ic_class_consistency_check: SKIP — bare-skeleton project "
            "(no facts.yaml / generated_docs / RTL)"
        ]

    inferred_class = profile.get("ic_class", "unknown")
    downgrade = profile.get("class_downgrade_reason")

    # 2. Claimed ic_class consistency.
    claimed_class = facts.get("ic_class")
    if isinstance(claimed_class, str) and claimed_class.strip():
        if claimed_class.strip() != inferred_class:
            extra = f" ({downgrade})" if downgrade else ""
            issues.append(
                f"facts.yaml ic_class={claimed_class!r} but "
                f"detect_ic_class() inferred {inferred_class!r}"
                f"{extra}"
            )

    # 3. Escape boolean consistency.
    escape_to_feature = (
        ("no_command_protocol", "has_command_protocol",
         "command protocol"),
        ("no_fsm", "has_fsm", "FSM"),
        ("no_calibration", "has_calibration", "calibration"),
        ("no_analog", "has_analog", "analog block"),
    )
    for esc, feat, label in escape_to_feature:
        if get_top_level_truthy(facts, esc, default=False):
            if profile.get(feat) is True:
                issues.append(
                    f"facts.yaml {esc}=true but profile reports "
                    f"{label} IS present (profile.{feat}=True). "
                    f"Either the escape is wrong, or the L docs / "
                    f"RTL are wrong."
                )

    # 4. phase1_skipped_path_a marker — must not have vendor docs.
    if get_top_level_truthy(
            facts, "phase1_skipped_path_a", default=False):
        vendor_docs = _vendor_docs_in_input(project)
        if vendor_docs:
            rels = []
            for vd in vendor_docs[:5]:
                try:
                    rels.append(str(vd.relative_to(project)))
                except ValueError:
                    rels.append(vd.name)
            more = (f" (+{len(vendor_docs) - 5} more)"
                    if len(vendor_docs) > 5 else "")
            issues.append(
                f"facts.yaml `phase1_skipped_path_a: true` but "
                f"input/docs/ has {len(vendor_docs)} vendor "
                f"file(s){more}: {', '.join(rels)}. Path A means "
                f"no vendor docs."
            )

    # 5. Per-L-doc ic_class stamp consistency (ORGANIC-20260614 #635).
    #    The L14-L23 skeletons stamp an ic_class field at phase1 emission
    #    time, BEFORE phase2 persists the authoritative reports/ic_class.json.
    #    If the stamped value diverges from the inferred/persisted class it is
    #    a frozen phase1-before-phase2 artifact that must FAIL here — the
    #    canonical consistency gate owns this stamp. Only flag when we have a
    #    concrete inferred class to compare against (an `unknown` inference is
    #    fail-closed / not-yet-resolved, so it cannot prove drift; docs that
    #    omit ic_class are already skipped by _stamped_l_doc_classes).
    if isinstance(inferred_class, str) and inferred_class not in (
            "", "unknown"):
        for rel, stamped in _stamped_l_doc_classes(project):
            if stamped != inferred_class:
                issues.append(
                    f"{rel} stamped ic_class={stamped!r} but "
                    f"detect_ic_class()/reports/ic_class.json resolves "
                    f"{inferred_class!r} — frozen phase1-before-phase2 "
                    f"L-doc stamp diverged from the authoritative class."
                )

    if issues:
        out: list[str] = [
            f"FAIL — Wave 42 / SF6: facts.yaml ↔ L docs / RTL "
            f"inconsistency ({len(issues)} issue(s)):"
        ]
        for s in issues:
            out.append(f"  - {s}")
        out.append("")
        out.append(
            "facts.yaml is the IC class source of truth ONLY when "
            "it agrees with the L docs and RTL. Fix the false "
            "asserted field, or align the L docs / RTL.")
        return 1, out

    return 0, [
        f"PASS — facts.yaml consistent with detect_ic_class() + "
        f"L docs (ic_class={inferred_class})"
    ]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pos = [a for a in argv if not a.startswith("--")]
    if not pos:
        print("Usage: ic_class_consistency_check.py <project_dir>")
        return 2
    project = Path(pos[0]).resolve()
    code, lines = inspect(project)
    for ln in lines:
        print(ln)
    return code


if __name__ == "__main__":
    sys.exit(main())
