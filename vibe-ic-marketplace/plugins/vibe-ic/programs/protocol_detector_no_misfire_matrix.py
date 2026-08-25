#!/usr/bin/env python3
"""Bidirectional protocol-detector no-misfire + gold cross-contamination matrix.

Promoted from benchmark_phase1/_no_misfire_matrix.py (v0.2.13) into a first-class
plugin program. Runs EVERY module-level ``is_<stem>`` detector exported by a
``<stem>_protocol_synth.py`` against EVERY benchmark's content blob and asserts
each detector fires ONLY on its own benchmark (modulo the documented
DERIVED_SIBLING_CROSS_FIRES allowlist).

This single program serves two close-loop purposes via ``--blob``:

  --blob generated   (default) : detector vs each benchmark's generated L1-L3.
  --blob superset              : detector vs input_doc + ALL generated L-docs
                                 (the strictest blob; matches the pytest guard).
  --blob input_doc             : detector vs the raw source spec only.
  --blob gold                  : detector vs each benchmark's claude_extracted
                                 L1-L3 (the GOLD). A FOREIGN detector firing on a
                                 gold flags likely CROSS-CONTAMINATION of that
                                 gold — e.g. the Tier-G batch left SENT content
                                 in the io_link gold and Ethernet content in the
                                 mdio docs, which gated-parity-0 cannot see
                                 (v0.1.89 lesson, applied to benchmark-data
                                 fidelity).

Both DIRECTIONS of cross-fire are covered automatically because every detector
is run against every benchmark: FORWARD (new detector on an existing benchmark)
and REVERSE (existing detector on a new benchmark) are the same matrix.

Exit 0 = clean (only own-fires + allowlisted derived siblings); exit 1 = at
least one un-allowlisted foreign fire (a misfire / contamination); exit 2 = NOT
CHECKED — the benchmark directory is absent, or either axis of the matrix
(detectors, benchmarks) is EMPTY. A zero population is not observed and never
reports ALL_PASS.
"""
from __future__ import annotations

import argparse
import glob
import importlib
import json
import sys
from pathlib import Path

PROGRAMS_DIR = Path(__file__).resolve().parent
# repo root: .../vibe-ic-marketplace/plugins/vibe-ic/programs -> up 4
# flow #486: on the flattened install cache there are no monorepo ancestors,
# so guard against IndexError at import; DEFAULT_BP then points under the
# plugin root (non-existent benchmark_phase1/), and callers fall back to the
# synthetic fixture / skip when the real corpus is absent.
try:
    REPO_ROOT = PROGRAMS_DIR.parents[3]
except IndexError:
    REPO_ROOT = PROGRAMS_DIR.parent  # plugin root (cache tree)
DEFAULT_BP = REPO_ROOT / "benchmark-data" / "evaluation" / "phase1_parity"

# THE ALLOWLIST IS LOAD-BEARING, SO ITS ABSENCE MUST NOT BE SILENT.
# `protocol_detector_lib.DERIVED_SIBLING_CROSS_FIRES` is the ONE canonical
# record of the (base, derived) pairs where the base detector firing on the
# derived benchmark is CORRECT base-class detection rather than a misfire — the
# module's own header calls itself that single source and forbids duplicating
# it. Substituting an empty mapping when the import fails does not disable a
# convenience: it silently deletes every documented exemption, so the matrix
# reports allowlisted pairs as findings and a corpus that exercises none of them
# (the eight shipped synthetic benchmarks exercise none) cannot tell the two
# states apart. `main` refuses with the NOT-CHECKED tier instead — see the guard
# beside the zero-denominator refusal.
_ALLOWLIST_IMPORT_ERROR = ""
try:
    from protocol_detector_lib import DERIVED_SIBLING_CROSS_FIRES
except Exception as _exc:  # pragma: no cover - exercised by the CLI guard
    DERIVED_SIBLING_CROSS_FIRES = {}
    _ALLOWLIST_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

# Gold-blob ONLY: (sub_clause_detector, parent_benchmark) pairs where the
# parent benchmark's spec is a LARGER STANDARD that genuinely CONTAINS the
# sub-clause protocol, so a faithful gold legitimately carries the sub-clause's
# content. This is NOT contamination — it is correct extraction of the bigger
# spec. Distinguished from real contamination (e.g. SENT in the io_link gold)
# by the fact that the parent's gold ic_name names the parent standard and the
# sub-clause appears as a documented clause of it. RUNTIME is unaffected: the
# generated/superset matrix is ALL_PASS because the parent's GENERATED head
# leads with the parent subject, so subject-dominance defers the sub-clause
# detector at dispatch time (no clobber).
ACCEPTABLE_GOLD_SUBCLAUSE_FIRES = {
    # IEEE 802.3 (ethernet / 800G ethernet) genuinely defines MDIO management
    # in Clause 22/45 — the ethernet gold ic_name is literally
    # "IEEE 802.3 ... (Clauses 4 / 22 / 35 / 45)".
    ("mdio", "ethernet"),
    ("mdio", "ethernet_800g"),
    # The ace_chi benchmark's GOLD subject is the ACE coherency protocol itself
    # (its gold carries the full AMBA AXI 5-channel baseline + ACE coherency:
    # ReadShared/ReadUnique/snoop AC-CR-CD, MOESI), so is_ace fires CORRECTLY —
    # this is detection of the gold's true subject, not contamination. In the
    # GENERATED/superset model the ace_chi input_doc is the comprehensive AMBA
    # AXI Protocol Specification, so is_ace's AXI-spec-primary defer (added v0.2.34)
    # correctly suppresses it there; only the ACE-subject gold legitimately fires.
    ("ace", "ace_chi"),
}


def discover_detectors():
    """{stem: callable} for every <stem>_protocol_synth.py exposing is_<stem>."""
    found = {}
    for p in sorted(PROGRAMS_DIR.glob("*_protocol_synth.py")):
        stem = p.name[: -len("_protocol_synth.py")]
        try:
            mod = importlib.import_module(f"{stem}_protocol_synth")
        except Exception:
            continue
        fn = getattr(mod, f"is_{stem}", None)
        if callable(fn):
            found[stem] = fn
    return found


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def doc_sequence(bp: Path, b: str, source: str):
    """The ordered document sequence ``blob_for`` concatenates, as
    ``(head_group, tail_group)`` — both name-sorted (vibe-ic#1444).

    THE ORDERING MODEL, stated once so the guards can bracket it instead of
    sampling it. The blob is the concatenation of TWO groups: the input_doc
    source spec(s), then the generated/gold L-docs. A directory read may return
    the members of a group in ANY order, but it can never interleave the two —
    so the blob HEAD (what a subject-dominance ``low[:N]`` check reads) is drawn
    from whichever group comes first and is non-empty, and the whole reachable
    head space is enumerated by letting each member of that group LEAD.

    Both groups are returned sorted, which is the layout ``blob_for`` pins: a
    head-window predicate over an unsorted concatenation answers a question
    about readdir order, not about the documents.
    """
    head: list[Path] = []
    tail: list[Path] = []
    idir = bp / b / "phase1" / "input_doc"
    if source in ("input_doc", "superset") and idir.is_dir():
        head = sorted(idir.glob("*.txt")) + sorted(idir.glob("*.md"))
    docdir_name = "claude_extracted" if source == "gold" else "generated_docs"
    if source != "input_doc":
        gd = bp / b / "phase1" / docdir_name
        names = (sorted(gd.glob("*.json")) if source == "superset"
                 else [gd / n for n in ("L1_DATASHEET.json", "L2_FRS.json",
                                        "L3_CMD_PROTOCOL.json")])
        tail = [f for f in names if f.is_file()]
    if not head:
        # No input_doc: the generated L-docs ARE the head group, and the blob
        # head is whichever of them readdir happens to return first. For the
        # benchmarks in this state the "input_doc-FIRST, so the head is the
        # source spec's title/abstract" premise the detectors cite is ABSENT.
        head, tail = tail, []
    return head, tail


def blob_for(bp: Path, b: str, source: str, lead: Path | str | None = None,
             reverse: bool = False) -> str:
    """Build a benchmark's detection blob from the chosen source.

    Mirrors the runner's auto-dispatch ([14e2b/15]) ordering: input_doc FIRST,
    then the generated/gold L-docs, so a subject-dominance head check sees the
    source spec's title exactly as it does at dispatch time.

    ``lead`` hoists one document of the HEAD group to the front — the single
    degree of freedom a directory read has over the blob head (vibe-ic#1444).
    ``reverse`` reads both groups in descending name order. Both keep the file
    SET identical; only the byte layout moves.
    """
    head, tail = doc_sequence(bp, b, source)
    if reverse:
        head, tail = head[::-1], tail[::-1]
    if lead is not None:
        lead = Path(lead)
        if lead in head:
            head = [lead] + [f for f in head if f != lead]
    return "\n".join(_read(f) for f in head + tail)


# ---------------------------------------------------------------------------
# WHICH DETECTORS CAN EVEN NOTICE THE ORDER (vibe-ic#1444)
# ---------------------------------------------------------------------------
# A detector that only asks "is this token anywhere in the blob" cannot tell
# two orderings apart — the file SET is the same in every ordering, so its
# verdict is permutation-invariant and one canonical ordering covers it.
# A detector that asks about a POSITION — ``low[:3500]``, ``find(...) < n``,
# ``startswith``, an anchored pattern — answers a different question per
# ordering, and is the family that has to be bracketed exhaustively.
#
# This is decided by reading the detector's BYTECODE, not its prose: the
# classification must not depend on a comment staying true. The default is
# SENSITIVE — anything unresolvable (an opaque callable, a call into a module
# we cannot follow) is bracketed rather than trusted.
_POSITIONAL_OPCODES = {"BINARY_SLICE", "BUILD_SLICE", "STORE_SLICE"}
# Position-revealing str/re members. ``search``/``finditer`` are deliberately
# ABSENT: an UNANCHORED pattern matched over the whole blob answers the same
# question in every ordering. An anchor smuggles the position back in, so
# anchor marks in the code's own string constants are caught separately.
_POSITIONAL_ATTRS = {
    "find", "rfind", "index", "rindex", "startswith", "endswith",
    "partition", "rpartition", "split", "rsplit", "splitlines",
    "start", "end", "span",
}
_ANCHOR_MARKS = ("^", "$", "\\A", "\\Z")
_SCAN_MAX_DEPTH = 4


def positional_reason(fn, module=None, _depth: int = 0, _seen=None) -> str:
    """Why ``fn``'s verdict may depend on WHERE content sits in the blob.

    Returns a short reason string, or ``""`` when the function is
    permutation-invariant as far as this scan can tell. Unresolvable =>
    a reason (fail SENSITIVE), never a silent clean.
    """
    import dis
    import types

    if _seen is None:
        _seen = set()
    key = getattr(fn, "__qualname__", None) or repr(fn)
    if key in _seen or _depth > _SCAN_MAX_DEPTH:
        return ""
    _seen.add(key)
    code = getattr(fn, "__code__", None)
    if code is None:
        return "opaque callable (no bytecode to read)"
    if module is None:
        module = sys.modules.get(getattr(fn, "__module__", ""), None)
    # Resolve callees through the function's OWN globals first — a detector
    # imported into the guard under a different module object must still be
    # followed — then fall back to the module we were handed.
    namespace = dict(getattr(fn, "__globals__", {}) or {})
    if module is not None:
        for n in dir(module):
            namespace.setdefault(n, getattr(module, n, None))

    bodies = [code] + [c for c in code.co_consts
                       if isinstance(c, types.CodeType)]
    for body in bodies:
        for ins in dis.get_instructions(body):
            if ins.opname in _POSITIONAL_OPCODES:
                return f"slices the blob ({ins.opname} in {body.co_name})"
            if (ins.opname in ("LOAD_METHOD", "LOAD_ATTR")
                    and ins.argval in _POSITIONAL_ATTRS):
                return f".{ins.argval}() in {body.co_name}"
        for const in body.co_consts:
            if isinstance(const, str) and any(a in const
                                              for a in _ANCHOR_MARKS):
                return f"anchor-marked literal {const!r} in {body.co_name}"
    # Module-level / imported callees, plus anything captured in a closure cell
    # (a detector built by a factory is still a detector).
    callees = [(n, namespace.get(n)) for n in code.co_names]
    for cell in (getattr(fn, "__closure__", None) or ()):
        try:
            callees.append((f"<closure {code.co_name}>", cell.cell_contents))
        except ValueError:  # pragma: no cover - empty cell
            continue
    for name, callee in callees:
        if isinstance(callee, types.FunctionType):
            sub = positional_reason(
                callee, sys.modules.get(callee.__module__, module),
                _depth + 1, _seen)
            if sub:
                return f"via {name}(): {sub}"
    return ""


def positional_detectors(detectors) -> dict:
    """{stem: reason} for every detector whose verdict can move with the order."""
    out = {}
    for stem, fn in detectors.items():
        reason = positional_reason(fn)
        if reason:
            out[stem] = reason
    return out


def bracket_leads(bp: Path, source: str = "superset", detectors=None):
    """Every foreign fire reachable by SOME directory order, for the detectors
    that can notice the order at all.

    Returns ``{(detector, benchmark): [leading doc name, ...]}``. An entry means
    the sweep's verdict on that pair is decided by which document a directory
    read happens to return first — a lottery, not a measurement.
    """
    if detectors is None:
        detectors = discover_detectors()
    positional = positional_detectors(detectors)
    benches = sorted(d.name for d in bp.iterdir()
                     if d.is_dir() and (d / "phase1").is_dir())
    reachable: dict = {}
    for b in benches:
        head, _tail = doc_sequence(bp, b, source)
        if len(head) < 2:
            continue  # one candidate => no freedom => the canonical sweep covers it
        for f in head:
            blob = blob_for(bp, b, source, lead=f)
            if not blob:
                continue
            for stem in positional:
                if stem == b or (stem, b) in DERIVED_SIBLING_CROSS_FIRES:
                    continue
                try:
                    hit = bool(detectors[stem](blob))
                except Exception:
                    hit = False
                if hit:
                    reachable.setdefault((stem, b), []).append(f.name)
    return positional, benches, reachable


def run_matrix(bp: Path, source: str):
    detectors = discover_detectors()
    benches = sorted(d.name for d in bp.iterdir()
                     if d.is_dir() and (d / "phase1").is_dir())
    blobs = {b: blob_for(bp, b, source) for b in benches}
    rows, misfires = [], []
    own_fires = set()
    for stem, fn in detectors.items():
        fired = []
        for b in benches:
            if not blobs.get(b):
                continue
            try:
                hit = bool(fn(blobs[b]))
            except Exception:
                hit = False
            if hit:
                if b == stem:
                    own_fires.add(stem)
                elif (stem, b) in DERIVED_SIBLING_CROSS_FIRES:
                    pass  # documented derived-sibling, resolved by synth order
                elif source == "gold" and (stem, b) in ACCEPTABLE_GOLD_SUBCLAUSE_FIRES:
                    pass  # parent standard genuinely contains this sub-clause
                else:
                    fired.append(b)
        if fired:
            misfires.extend((stem, b) for b in fired)
        rows.append({"detector": stem, "own_fire": stem in own_fires,
                     "foreign_fires": fired})
    return detectors, benches, rows, misfires, own_fires


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blob", choices=["generated", "superset", "input_doc", "gold"],
                    default="generated")
    ap.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BP)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--bracket-leads", action="store_true",
                    help="report every foreign fire reachable by SOME directory "
                         "order (vibe-ic#1444), instead of the single canonical "
                         "ordering the sweep pins")
    args = ap.parse_args(argv)

    if not args.benchmark_dir.is_dir():
        print(f"ERROR: benchmark dir not found: {args.benchmark_dir}",
              file=sys.stderr)
        return 2
    if _ALLOWLIST_IMPORT_ERROR:
        print(f"NOT CHECKED: the canonical derived-sibling allowlist "
              f"`protocol_detector_lib.DERIVED_SIBLING_CROSS_FIRES` could not "
              f"be imported ({_ALLOWLIST_IMPORT_ERROR}). Running without it "
              f"would report every documented base-on-derived pair as a "
              f"misfire, and a corpus exercising none of them would look "
              f"identical to one that had the allowlist.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(PROGRAMS_DIR))

    if args.bracket_leads:
        positional, benches, reachable = bracket_leads(
            args.benchmark_dir, args.blob)
        print(f"[lead-bracket] blob={args.blob}  benchmarks={len(benches)}  "
              f"order-sensitive detectors={len(positional)}")
        if not benches:
            print(f"NOT CHECKED: no benchmark under {args.benchmark_dir} — a "
                  f"population of zero is NOT OBSERVED, and a verdict over it "
                  f"is indistinguishable from one earned against a real corpus.",
                  file=sys.stderr)
            return 2
        for stem, why in sorted(positional.items()):
            print(f"    is_{stem}: {why}")
        for (stem, b), leads in sorted(reachable.items()):
            print(f"  [REACHABLE] is_{stem} fires on {b} when any of "
                  f"{len(leads)} document(s) leads: {sorted(leads)}")
        if args.json:
            args.json.write_text(json.dumps(
                {"blob": args.blob, "positional": positional,
                 "reachable": {f"{s}|{b}": v
                               for (s, b), v in reachable.items()}}, indent=2))
        if reachable:
            print(f"\n{len(reachable)} order-reachable foreign fire(s)")
            return 1
        print("\nALL_PASS")
        return 0

    detectors, benches, rows, misfires, own_fires = run_matrix(
        args.benchmark_dir, args.blob)

    label = ("CROSS-CONTAMINATION" if args.blob == "gold" else "no-misfire")
    print(f"[{label}] blob={args.blob}  detectors={len(detectors)}  "
          f"benchmarks={len(benches)}")
    # A ZERO POPULATION IS NOT A RESULT (docs/findings/2026-08-22-a-zero-
    # denominator-green-outside-the-gate-that-forbids-it.md). Measured before
    # this refusal existed: `--benchmark-dir <EMPTY DIR>` printed
    # `benchmarks=0` and then `ALL_PASS` at rc 0 — the zero WAS disclosed, and
    # the verdict word still said 86 detectors had been checked against real
    # benchmarks and passed. `gate_zero_denominator_refuses_check` already
    # forbids this shape and could not see this program, whose filename does
    # not end in `_check.py`. Both halves of the matrix refuse it now: rc 2 is
    # the same NOT-CHECKED tier a missing `--benchmark-dir` already returns.
    if not benches or not detectors:
        print(f"NOT CHECKED: {len(detectors)} detector(s) and {len(benches)} "
              f"benchmark(s) under {args.benchmark_dir} — a population of zero "
              f"on either axis is NOT OBSERVED, and ALL_PASS over it is "
              f"indistinguishable from a verdict earned against a real corpus.",
              file=sys.stderr)
        return 2
    for r in rows:
        if r["foreign_fires"]:
            print(f"  [FAIL] is_{r['detector']}: foreign_fires={r['foreign_fires']}")
    if args.json:
        args.json.write_text(json.dumps(
            {"blob": args.blob, "misfires": misfires, "rows": rows}, indent=2))
    if misfires:
        kind = ("gold cross-contamination" if args.blob == "gold"
                else "detector mis-fire")
        print(f"\n{len(misfires)} {kind} finding(s): {misfires}")
        return 1
    print("\nALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
