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
from ic_class_profile import infer_ic_class_uncached  # noqa: E402


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

_PERSISTED_REL = "reports/ic_class.json"


def _has_persisted_snapshot(project: Path) -> bool:
    """Sample BEFORE ``detect_ic_class()`` — that call creates the file."""
    return (project / "reports" / "ic_class.json").is_file()


def _class_source_label(had_snapshot: bool) -> str:
    """Name the layer that actually supplied the class this gate compares to.

    re #495 Stage 1 — this gate calls ``detect_ic_class(project)``, whose
    documented contract (#435 persist-once) is to return the PERSISTED
    ``reports/ic_class.json`` verbatim whenever that file exists and to run the
    classifier only when it does not. So on any project that has been through
    a runner, the string this gate compares against is a CACHE READ, not a
    classification — but every message it emitted said "detect_ic_class()",
    naming a computation that had not happened. Attributing a cached value to
    a live classifier is the kind of false provenance that makes a stale
    number look freshly measured, so say which layer was read.
    """
    return (f"{_PERSISTED_REL} (persisted snapshot)" if had_snapshot
            else "detect_ic_class() live inference")


def _persisted_snapshot_staleness(project: Path,
                                  effective_class: str,
                                  had_snapshot: bool) -> str | None:
    """DISCLOSURE (never a verdict): has the persisted snapshot gone stale?

    re #495 Stage 1. The L-doc stamp is not the only frozen layer — so is
    ``reports/ic_class.json``. Measured over the 103 tracked projects carrying
    a persisted profile: 3 have a stamp that disagrees with the snapshot (what
    this gate already FAILs on) and **24** have a snapshot that disagrees with
    what the classifier produces today. The larger divergence was the invisible
    one, because nothing could reach the classifier without persisting over the
    very value it wanted to compare.

    Deliberately NOT a FAIL, and the reason is measured rather than
    conservative: of those 24, at least 7 are protocol-specification
    extractions that today's classifier calls ``crypto_accelerator``, and one
    regresses from a real class INTO the ``digital_arithmetic_primitive``
    catch-all. Failing on snapshot drift would therefore turn a classifier
    over-fire into 24 red projects — manufacturing exactly the spurious red
    that #495's own measurement warns against. Re-classifying on every read is
    equally excluded: that is the fork #435's persist-once contract exists to
    prevent. Disclosure is the honest third option — the number stops being
    invisible without anything being scored on it.

    Returns the disclosure line, or None when there is nothing to disclose.
    chip-AGNOSTIC: a string comparison between two profile fields.
    """
    if not had_snapshot:
        return None      # nothing cached → detect_ic_class() already inferred
    try:
        live = (infer_ic_class_uncached(project) or {}).get("ic_class")
    except Exception:
        return None      # fail-open: a disclosure must never break the gate
    if not isinstance(live, str) or live in ("", "unknown"):
        return None      # fail-closed inference cannot prove drift
    if live == effective_class:
        return None
    return (
        f"DISCLOSURE (not a failure) — {_PERSISTED_REL} holds "
        f"{effective_class!r}, but re-running the classifier now on this same "
        f"project yields {live!r}. The persisted class is a snapshot frozen at "
        f"the last refresh, and it is what this gate compared the L-doc stamps "
        f"against. Re-run the runner's detect step (refresh=True) to adopt the "
        f"new class deliberately; this gate will not adopt it for you."
    )


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

    # re #495 Stage 1 — the label MUST be sampled before detect_ic_class(),
    # which CREATES reports/ic_class.json when the project has none. Sampling
    # it afterwards would report every project as reading a persisted
    # snapshot, including the ones this call had just persisted itself.
    had_snapshot = _has_persisted_snapshot(project)
    class_source = _class_source_label(had_snapshot)

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
                f"{class_source} holds {inferred_class!r}"
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
                    f"{class_source} holds {inferred_class!r} — frozen "
                    f"phase1-before-phase2 L-doc stamp diverged from the "
                    f"authoritative class."
                )

    # 6. DISCLOSURE — the layer this gate compared against is itself a frozen
    #    snapshot. Reported on BOTH verdicts and scored on NEITHER; see
    #    _persisted_snapshot_staleness for the measured reason it is not a
    #    FAIL. re #495 Stage 1.
    notes: list[str] = []
    stale = _persisted_snapshot_staleness(project, inferred_class,
                                          had_snapshot)
    if stale:
        notes.append(stale)

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
        out.extend(notes)
        return 1, out

    return 0, [
        f"PASS — facts.yaml consistent with {class_source} + "
        f"L docs (ic_class={inferred_class})"
    ] + notes


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
