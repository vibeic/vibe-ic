#!/usr/bin/env python3
"""
waiver_growth_check.py — v0.112 release-gate (BACKLOG-v10 P0 follow-up).

Compares current `<project>/waivers.json` against a baseline (frozen at
the previous release tag). Fails CI if:
  - waiver count grew without explicit `growth_rationale` in waivers.json, or
  - a previously-closed waiver re-appeared, or
  - a waiver's evidence pointer became stale (referenced file deleted).

Why this exists: the v0.108 <benchmark> benchmark showed waivers grew from 6
(Round 3 digital) → 9 (Round 4 + analog) without anyone tracking the
delta. Without this gate, "PASS_WITH_WAIVERS" can silently rot — every
release accumulates one more waiver until the chip has more deferred
work than executed.

Cascading entries (root + cascades_to) count ONCE for growth purposes —
the cascade is bookkeeping, not new deferred work. A `cascades_to` TARGET is
only resolved in the dialect whose target vocabulary is defined; in the other,
an entry declares its own derivation with `cascade_source`. See
:func:`_cascade_target_name` for why guessing the other vocabulary loses
waivers.

BOTH WAIVER DIALECTS ARE COUNTED
================================
A waivers.json carries its entry list under one of two top-level keys, and
this gate used to read ``waived_steps`` only — with a ``{"waived_steps": []}``
default that turned "I cannot see this dialect" into "there are no waivers".
Measured over the tracked corpus, 6 of 11 projects and 8 of 19 entries were
invisible to it: it reported 0, compared 0 against 0, and passed. A growth
gate that cannot see the dialect its own runner emits is not measuring growth,
and a project could have accumulated that dialect indefinitely without ever
moving the number. Same shape as the gate that reported "0 problems" because
it could not find the data.

The entry list now comes from ``_waiver_entries`` — the ONE reader of "where a
project's waiver entries live" — so this gate cannot drift from the other
waiver gates about what a waivers.json contains.

Parsing stays local rather than using ``_waiver_entries.read_document``,
deliberately: that helper fail-softs an unparseable file to None, and this gate
must keep exiting 2 on a corrupt document. Turning a corrupt waivers.json into
"0 waivers, PASS" would reintroduce the exact defect above one layer down. The
shared module blesses this split — callers that must distinguish "no entries"
from "malformed" use ``entries_by_key`` plus ``malformed_keys``, which is what
happens here.

WHAT IDENTIFIES A WAIVER, FOR GROWTH ACCOUNTING
==============================================
Growth is a set difference across runs, so every entry needs a key that is
(a) STABLE — the same deferred obligation must produce the same key on the
next run, or the gate reports a phantom close plus a phantom open; and
(b) DISCRIMINATING — two genuinely different obligations must produce
different keys, or real growth hides inside a collision.

The two dialects name themselves differently, so each is keyed by the fields
it actually carries:

  * ``waived_steps`` entries carry a canonical flow-step ``id``. Their key is
    ``repr(id)`` — byte-for-byte what this gate has always used, so adopting
    the shared reader cannot move a verdict this dialect already decided.
  * ``waivers`` entries carry no ``id``. They carry ``step`` (a runner-local
    role name), ``phase`` and ``ticket``, and their key is the triple.

Three fields are deliberately EXCLUDED from the key, each for a reason that
would otherwise break stability:

  * ``rationale``, ``evidence`` and ``reviewer_action`` are prose, and the
    auto-generated form of ``reviewer_action`` embeds the emitting runner's
    VERSION STRING. Keying on them would make one runner upgrade look like
    every waiver closed and an equal number opened — churn reported as
    turnover, on a gate whose whole job is to notice real turnover.
  * ``verdict_tier`` moves when an obligation is re-graded (deferred →
    partially satisfied). That is the SAME obligation changing severity, not
    one closing and another opening. Growth counts how many, not how bad.

And the step name is compared AS WRITTEN, never resolved through
``_waiver_entries.STEP_NAME_TO_ID``. That map is MANY-TO-ONE — several
physical-verification role names share one canonical step id — so resolving
first would fuse a project that separately waives two of those roles, which is
the shape the runner actually emits, into a single counted waiver. On the
tracked corpus that alone would have under-counted 8 entries as 6. The shared
module states this constraint explicitly; this gate obeys it.

The key is rendered as a string because the two dialects' identities are not
mutually orderable, and the report sorts them. The renderings cannot collide:
a ``waivers`` key is prefixed ``waivers:``, while a ``waived_steps`` key is
``repr()`` of its id — which for a string id always begins with a quote.

THE BASELINE IS NEVER REWRITTEN BY THIS GATE
============================================
Making the second dialect visible means projects carrying it now compare a
real count against whatever baseline they have. This gate does NOT re-baseline
them, and does not write a baseline at all — a gate that edits its own
reference to stay green is issuing a certificate about itself.

When no baseline file exists there is nothing frozen to preserve: the
comparison is against an EMPTY document, and entries then read as growth. That
is not a new policy invented here — it is the behaviour this gate already
applies, and already has a shipped test for, on the dialect it could see. The
escape hatches are the ones that were always there and are all operator-driven
and recorded in the data: a substantive top-level ``growth_rationale``, an
explicit ``--baseline``, or ``--tolerance``.

Because "compared against an absent baseline" and "compared against a recorded
baseline of zero" produce the same number and very different meanings, the
report now says which one happened, in both the text and the JSON
(``baseline_present``).

Usage:
  python3 waiver_growth_check.py <project_dir> \\
      [--baseline <path>] [--tolerance N] [--json [PATH]]

Default baseline: `<project>/.vibe-ic-state/waivers_baseline.json`
Default tolerance: 0 (any net growth without rationale fails)
Exit codes:
  0  PASS — waiver count flat or shrinking, OR growth has explicit rationale
  1  FAIL — waiver grew unjustifiably
  2  IO error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _waiver_entries as _we  # noqa: E402  (after sys.path bootstrap)

#: Fields that identify a ``waivers``-dialect entry, in key order. See the
#: module docstring for why prose, version-bearing and severity fields are not
#: among them.
_WAIVERS_IDENTITY_FIELDS: Tuple[str, ...] = ("step", "phase", "ticket")


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


def _load(path: Path) -> Tuple[Dict[str, Any], bool]:
    """``(document, present)``.

    An ABSENT file yields an empty document and ``present=False`` — the caller
    must be able to say so, because "no baseline was ever frozen" and "the
    frozen baseline held zero waivers" are the same number and different
    facts. An UNPARSEABLE file still exits 2: a corrupt waiver list must never
    be silently downgraded to "no waivers"."""
    if not path.exists():
        return {}, False
    try:
        return json.loads(path.read_text()), True
    except Exception as exc:
        print(f"[ERROR] cannot parse {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)


def _identity(dialect: str, entry: Any) -> str:
    """The stable, discriminating key for one waiver entry.

    ``!r`` is used on every field value so that an absent field (``None``) can
    never be confused with the literal string ``"None"``, nor an integer step
    with its decimal spelling — an identity that is ambiguous about its own
    inputs cannot support a set difference."""
    if not isinstance(entry, dict):
        # Malformed, but it is still an entry. Counting it keeps a shape this
        # gate does not understand from silently reading as zero.
        return f"{dialect}:<non-dict>{entry!r}"
    if dialect == "waived_steps" and "id" in entry:
        return repr(entry["id"])
    fields = ";".join(f"{f}={entry.get(f)!r}" for f in _WAIVERS_IDENTITY_FIELDS)
    return f"{dialect}:{fields}"


def _cascade_target_name(dialect: str, entry: Dict[str, Any]) -> Any:
    """The value another entry's ``cascades_to`` list would name this entry by,
    or None when this dialect has no defined target vocabulary.

    Only ``waived_steps`` has one: its targets are canonical step ids, unique
    within a document. The attestation dialect names itself by a step ROLE, and
    a role is NOT unique — a project can defer the same role twice under two
    tickets, which is the corpus shape. Treating a ``cascades_to`` target as a
    role name would suppress EVERY entry sharing that role: measured, one such
    declaration hid two genuinely distinct obligations, turning real growth
    into a PASS. A growth gate must not guess a vocabulary in the direction
    that loses waivers, so in that dialect derivation is only ever taken from
    the entry's OWN ``cascade_source``, which cannot over-reach."""
    return entry.get("id") if dialect == "waived_steps" else None


def _dialect_entries(waivers_doc: Any) -> List[Tuple[str, Any]]:
    """``[(dialect, entry)]`` for every entry under either list key, in the
    shared reader's documented order."""
    out: List[Tuple[str, Any]] = []
    for dialect, entries in _we.entries_by_key(waivers_doc).items():
        out.extend((dialect, entry) for entry in entries)
    return out


def _root_identities(waivers_doc: Any) -> List[str]:
    """Identities of root waivers — entries that are NOT cascades.

    A 'root' is any entry that is neither the target of another entry's
    ``cascades_to`` list nor self-declared derived via ``cascade_source``.
    Cascade targets are resolved WITHIN a dialect, never across one, and only
    in the dialect whose target vocabulary is defined — see
    :func:`_cascade_target_name`."""
    pairs = _dialect_entries(waivers_doc)

    cascade_targets: Dict[str, set] = {}
    for dialect, entry in pairs:
        targets = cascade_targets.setdefault(dialect, set())
        if not isinstance(entry, dict):
            continue
        for child in entry.get("cascades_to") or []:
            try:
                targets.add(child)
            except TypeError:
                continue  # unhashable target cannot name any entry

    roots: List[str] = []
    for dialect, entry in pairs:
        if isinstance(entry, dict):
            target_name = _cascade_target_name(dialect, entry)
            try:
                is_child = (target_name is not None
                            and target_name in cascade_targets.get(dialect, set()))
            except TypeError:
                # An unhashable identifier cannot be named by any target, and a
                # traceback is not a verdict — the entry is simply a root.
                is_child = False
            if is_child:
                continue  # this entry is a cascaded child, not a root
            if entry.get("cascade_source") is not None:
                continue  # explicitly marked as derived
        roots.append(_identity(dialect, entry))
    return roots


def _looks_like_path(tok: str) -> bool:
    return "/" in tok and not tok.startswith(("http://", "https://"))


def _strip_locator(tok: str) -> str:
    """A trailing ``#fragment`` locates a position INSIDE the referenced file.
    It is not part of the filename, and leaving it attached would report every
    precise pointer as stale."""
    return tok.split("#", 1)[0].strip().rstrip(",.;")


def _evidence_files(entry: Dict[str, Any]) -> List[str]:
    """File paths an entry's ``evidence`` points at.

    ``evidence`` appears in two shapes and the gate used to read only one of
    them: ``isinstance(ev, str)`` and otherwise nothing. Across the tracked
    corpus EVERY entry carries the list shape, so this check examined zero
    pointers and had never once fired — the same "cannot read it, so report
    nothing" failure as the entry-list key itself, one field further down.

    The two shapes are mined differently because they mean different things:

      * a STRING evidence field is free text that may CONTAIN paths, so it is
        split into tokens and every path-looking token is checked (unchanged
        historical behaviour);
      * a LIST is a sequence of discrete pointer slots, so each element is ONE
        candidate pointer. An element containing whitespace is prose occupying
        a pointer slot, not a pointer — token-mining it yields fragments of
        sentences reported as missing files, which trains readers to ignore
        the finding. A real pointer is its own element.
    """
    ev = entry.get("evidence", "")
    files: List[str] = []
    if isinstance(ev, str):
        for tok in ev.replace(";", " ").split():
            if _looks_like_path(tok):
                files.append(_strip_locator(tok))
    elif isinstance(ev, (list, tuple)):
        for element in ev:
            if not isinstance(element, str):
                continue
            tokens = element.split()
            if len(tokens) != 1:
                continue  # empty, or prose rather than a single pointer
            if _looks_like_path(tokens[0]):
                files.append(_strip_locator(tokens[0]))
    return [f for f in files if f]


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Block CI when waivers grow unjustifiably. Reduces accumulation "
            "of deferred work across releases."
        )
    )
    ap.add_argument("project_dir", help="Project directory containing waivers.json")
    ap.add_argument("--baseline", default=None,
                    help="Baseline waivers.json (default: <project>/.vibe-ic-state/waivers_baseline.json)")
    ap.add_argument("--tolerance", type=int, default=0,
                    help="Allowed net growth without rationale (default 0)")
    ap.add_argument("--stale-warn-days", type=int, default=90,
                    help="Waivers older than N days approved_at → WARN (default 90)")
    ap.add_argument("--stale-error-days", type=int, default=180,
                    help="Waivers older than N days approved_at → ERROR (default 180)")
    ap.add_argument("--json", nargs="?", const="-", default=None,
                    help="Emit JSON. Bare flag → stdout, with PATH → file")
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    cur_path = project / "waivers.json"
    base_path = Path(args.baseline) if args.baseline else (
        project / ".vibe-ic-state" / "waivers_baseline.json"
    )

    cur_doc, _cur_present = _load(cur_path)
    base_doc, base_present = _load(base_path)

    cur_roots = set(_root_identities(cur_doc))
    base_roots = set(_root_identities(base_doc))

    new_waivers = cur_roots - base_roots
    removed_waivers = base_roots - cur_roots
    net_growth = len(new_waivers) - len(removed_waivers)

    findings: List[Finding] = []

    # A document whose top level is not a JSON object carries no readable keys
    # at all. The shared reader fail-softs it to "no entries" — correct for a
    # caller asking "is this step waived", and a silent PASS for this one. It
    # is reported, in both documents: a growth number computed from a document
    # the gate could not read is not a measurement of anything.
    # An ABSENT file is not unreadable — `_load` gives it an empty object, and
    # its absence is disclosed separately.
    for label, doc, path in (("current", cur_doc, cur_path),
                             ("baseline", base_doc, base_path)):
        if not isinstance(doc, dict):
            findings.append(Finding(
                severity="ERROR",
                category="WAIVER_DOCUMENT_UNREADABLE",
                message=(
                    f"the {label} waiver document is a JSON "
                    f"{type(doc).__name__}, not an object, so it carries no "
                    f"readable entry list: {path}"
                ),
                details=(
                    "Counting an unreadable document as zero waivers is the "
                    "failure this gate was fixed for. Repair the document."
                ),
            ))

    # A list key that is PRESENT but does not hold a list contributes no
    # entries. Reading that as "no waivers" is the defect this gate was fixed
    # for, so the unreadable shape is reported instead of counted as zero.
    for key in _we.malformed_keys(cur_doc):
        findings.append(Finding(
            severity="ERROR",
            category="WAIVER_LIST_UNREADABLE",
            message=(
                f"{cur_path.name} has a top-level `{key}` that is not a list "
                f"(found {type(cur_doc.get(key)).__name__}). Its entries "
                f"cannot be counted, so the growth number below is computed "
                f"over an incomplete list."
            ),
            details=(
                "A growth verdict computed over entries the gate could not "
                "read is not a verdict. Fix the shape or remove the key."
            ),
        ))

    # Stale evidence check — referenced files must still exist. Every dialect
    # is walked: an unchecked evidence pointer is an unchecked waiver.
    for _dialect, entry in _dialect_entries(cur_doc):
        if not isinstance(entry, dict):
            continue
        for f in _evidence_files(entry):
            f_path = (project / f).resolve() if not f.startswith("/") else Path(f)
            try:
                f_path.relative_to(project)
            except ValueError:
                continue  # outside project, skip
            if not f_path.exists():
                # Heuristic — only WARN, since evidence may reference foundry-side
                # tools or future artefacts.
                findings.append(Finding(
                    severity="WARN",
                    category="STALE_EVIDENCE",
                    message=(
                        f"waiver {_identity(_dialect, entry)} evidence references "
                        f"{f} which does not exist in the project."
                    ),
                ))

    # v0.113 (BACKLOG-v10 P1.3): staleness-by-age. Waivers with an
    # `approved_at` field older than --stale-warn-days WARN; older than
    # --stale-error-days ERROR. Forces deferred work to actually progress
    # rather than rotting under "review_required: true" forever.
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for _dialect, entry in _dialect_entries(cur_doc):
        if not isinstance(entry, dict):
            continue
        approved_at = entry.get("approved_at", "")
        if not approved_at:
            continue
        if not isinstance(approved_at, str):
            # Widening this loop to every dialect must not widen a crash: a
            # non-string timestamp is a reportable defect, not a traceback.
            findings.append(Finding(
                severity="WARN",
                category="APPROVED_AT_INVALID",
                message=(f"waiver {_identity(_dialect, entry)} has non-string "
                         f"approved_at: {approved_at!r}"),
            ))
            continue
        try:
            ts = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        except ValueError:
            findings.append(Finding(
                severity="WARN",
                category="APPROVED_AT_INVALID",
                message=(f"waiver {_identity(_dialect, entry)} has malformed "
                         f"approved_at: {approved_at!r}"),
            ))
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = (now - ts).days
        if age_days >= args.stale_error_days:
            findings.append(Finding(
                severity="ERROR",
                category="WAIVER_STALE_ERROR",
                message=(
                    f"waiver {_identity(_dialect, entry)} approved {age_days} days ago "
                    f"(>= {args.stale_error_days} day error threshold). "
                    f"Either close it (run the deferred check on the foundry "
                    f"deck and remove the waiver) or update approved_at with "
                    f"explicit `staleness_extension_rationale`."
                ),
            ))
        elif age_days >= args.stale_warn_days:
            findings.append(Finding(
                severity="WARN",
                category="WAIVER_STALE_WARN",
                message=(
                    f"waiver {_identity(_dialect, entry)} approved {age_days} days ago "
                    f"(>= {args.stale_warn_days} day warn threshold)."
                ),
            ))

    # Growth check.
    rationale = cur_doc.get("growth_rationale", "") if isinstance(cur_doc, dict) else ""
    growth_justified = (
        isinstance(rationale, str)
        and len(rationale.strip()) >= 30  # minimum substantive justification
    )

    if net_growth > args.tolerance and not growth_justified:
        findings.append(Finding(
            severity="ERROR",
            category="UNJUSTIFIED_WAIVER_GROWTH",
            message=(
                f"Net waiver count grew by {net_growth} (> tolerance "
                f"{args.tolerance}) without `growth_rationale` in waivers.json. "
                f"New waivers: {sorted(new_waivers)}. "
                + ("" if base_present else
                   "No baseline file exists at the path below, so the "
                   "comparison was made against an EMPTY document and every "
                   "current waiver counts as new. Freeze a baseline (or pass "
                   "--baseline) to measure growth against a real reference. ")
                + f"Either close one of the new waivers, OR add a top-level "
                f"`growth_rationale` field to waivers.json explaining why "
                f"net growth is acceptable for this release."
            ),
            details=(
                "Repeated growth without rationale leads to silent rot: every "
                "release accumulates more deferred work until the project has "
                "more open waivers than executed steps. This gate enforces "
                "that growth is a deliberate, documented decision."
            ),
        ))

    pass_flag = not any(f.severity == "ERROR" for f in findings)

    result = {
        "program": "waiver_growth_check",
        "version": "1.0.0",
        "project": str(project),
        "baseline_path": str(base_path),
        "baseline_present": base_present,
        "summary": {
            "current_root_waivers": len(cur_roots),
            "baseline_root_waivers": len(base_roots),
            "current_waivers_by_key": {k: len(v) for k, v in
                                       _we.entries_by_key(cur_doc).items()},
            "net_growth": net_growth,
            "tolerance": args.tolerance,
            "growth_justified": growth_justified,
            "baseline_present": base_present,
            "new_waivers": sorted(new_waivers),
            "removed_waivers": sorted(removed_waivers),
            "pass": pass_flag,
        },
        "findings": [asdict(f) for f in findings],
    }

    if args.json is None:
        verdict = "PASS" if pass_flag else "FAIL"
        print(f"[{verdict}] waiver_growth_check")
        print(f"  current: {len(cur_roots)} root waivers")
        # "no baseline was ever frozen" and "the frozen baseline held zero"
        # print the same number, so the report says which one this was.
        if base_present:
            print(f"  baseline: {len(base_roots)} root waivers ({base_path})")
        else:
            print(f"  baseline: ABSENT — no file at {base_path}; compared "
                  f"against an empty document (0 root waivers)")
        print(f"  net growth: {net_growth} (tolerance {args.tolerance})")
        if new_waivers:
            print(f"  new this release: {sorted(new_waivers)}")
        if removed_waivers:
            print(f"  closed since baseline: {sorted(removed_waivers)}")
        for f in findings:
            print(f"  [{f.severity}] {f.category}: {f.message}")
    elif args.json == "-":
        print(json.dumps(result, indent=2))
    else:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"json: {args.json}")

    return 0 if pass_flag else 1


if __name__ == "__main__":
    sys.exit(main())
