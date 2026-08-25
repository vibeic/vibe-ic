#!/usr/bin/env python3
"""every_required_metric_key_has_a_producer.py — an axis proves from a metric
somebody actually emits.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
WHY THIS EXISTS
===============
MEASURED, and recorded in the feasibility module's own source: across all six
STA artefacts of a real sign-off run, both `timing.setup.wns_ns` and
`timing.hold.wns_ns` were NOT_MEASURED on every view — because the two
multi-corner sign-off emitters, the ones that decide setup at the slow corner and
hold at the fast one, call `report_worst_slack` and `report_tns` and never call
`report_wns` at all.

The hold axis was therefore STRUCTURALLY UNPROVABLE: no run of this flow could
produce the evidence it proved from, on any design, ever. And the failure was
silent in the worst way — each run appeared to blame its own evidence ("the
artefact carries no wns line for this view") rather than the wiring.

This is the same shape `l_doc_field_producer_check` already blocks for DOCUMENT
fields, and its docstring records five separate measurements of it. Metric keys
are the population that gate does not cover. This is that gate, for this
population.

THE TWO VERDICTS, WHICH ARE NOT THE SAME
========================================
The axis table is an OR of ANDs: an axis is satisfied when every proof in at
least ONE group is satisfied. So a key with no producer is not automatically
fatal, and reporting it as fatal would be wrong.

    FINDING (rc 1)   an AXIS no group of which can be fully produced. Nothing
                     this flow emits can ever prove it. This is the measured
                     defect, and it is what blocks.
    DISCLOSED        a single proof key with no producer, where another group of
                     the same axis IS producible. The axis still works; that
                     proof path is dead weight that silently narrows it, and it
                     is printed with its count so it cannot accumulate unseen.

WHY THIS IS EMPIRICAL AND NOT A SOURCE SCAN — MEASURED, AND IT MATTERED
======================================================================
This was FIRST written as a static cross-reference: metric-name literals in the
producers' source against the axis table's keys. Swept, it declared the whole
`drv` axis STRUCTURALLY UNPROVABLE and named four keys as having no producer.

That verdict was FALSE, and false in the blocking direction — it would have
stopped a flow that works. The evidence was one directory away: those keys appear
under `"metric":` in real emitted run records. The producers build their names by
FORMAT, not by literal:

    _ppa/timing.py:651   metric = "timing.%s.%s_ns" % (check, kind)
    _ppa/timing.py:837   "timing.%s.worst_slack_ns" % decl["check"]

so no scan for literals can ever see them, and every key produced that way reads
as unproduced. A gate whose failure mode is "correct wiring looks broken" is
worse than no gate.

The population is therefore what was actually EMITTED: the `metric` names in
canonical metric records under the tree being examined. That is the same choice
`l_doc_field_producer_check` makes for document fields, and its docstring is
explicit that the check is EMPIRICAL rather than static, for this reason.

The consequence is honest and stated: this gate answers only about runs it can
see. With no records it returns NOT CHECKED, never PASS.

    rc 0   N>0 axes, each provable by at least one fully-produced group.
    rc 1   an axis has no MEASURED evidence in any run this gate can see.
    rc 2   NOT CHECKED — the axis table could not be read, declares no axis,
           or NO metric record was found to judge it against.
    rc 3   bad invocation.
"""
from __future__ import annotations

import argparse
import ast
import collections
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

NAME = "every_required_metric_key_has_a_producer"
PROGRAMS_REL = Path("vibe-ic-marketplace/plugins/vibe-ic/programs")
AXIS_MODULE_REL = Path("_ppa/feasibility.py")
SKIP_DIRS = {".git", "docs/capture", "node_modules", "__pycache__"}


def axis_table(programs: Path):
    """The DEFAULT_AXES table, imported from the module that owns it."""
    import importlib
    p = str(programs)
    if p not in sys.path:
        sys.path.insert(0, p)
    feas = importlib.import_module("_ppa.feasibility")
    return feas.DEFAULT_AXES


def producers(tree_root: Path, keys: Set[str]) -> Dict[str, Set[str]]:
    """`{metric key: {record files that EMITTED it}}` — what runs really wrote.

    Any JSON under the tree may hold canonical metric records; they are found by
    shape (an object carrying a `metric` name) rather than by filename, because
    the emitters spread them across several artefacts per run.
    """
    found: Dict[str, Set[str]] = collections.defaultdict(set)

    def _is_evidence(obj) -> bool:
        """True only when this row shows a PRODUCER emitted the key.

        MEASURED FAIL-OPEN, and found by composing with another lane whose gate
        reached the opposite verdict on the same axis. The consumer writes its
        OWN report listing every proof name it looked for, including the ones it
        could not find:

            {"metric": "timing.drv.violations",
             "state": "NO_RECORD",
             "reason": "no record in this candidate names this metric"}

        Counting that as a producer makes the adjudicator its own evidence — the
        exact defect this rule exists to catch, committed by the rule. It is why
        this gate answered PASS on a tree whose `drv` axis is structurally
        unprovable, across 205+ record files that all trace back to the
        consumer.

        A row counts when it is a canonical metric record (it carries the metric
        SCHEMA), or when an adjudication row reports it as actually seen —
        state not NO_RECORD, and at least one backing record.
        """
        state = str(obj.get("state", obj.get("status", ""))).upper()
        if str(obj.get("schema", "")).startswith("vibeic.ppa.metric"):
            # A canonical record still cannot prove an axis it never measured.
            #
            # MEASURED: `signoff_bridge_records.json` emits a canonical
            # `timing.drv.violations` record with status NOT_MEASURED, in 61
            # files. Accepting it here made this gate say the drv axis is
            # provable while its SIBLING gate,
            # `measurement_only_artefact_is_not_a_verdict_source`, refuses a
            # NOT_MEASURED record as verdict evidence by name. Two gates in one
            # family, the same records, opposite treatment — and the flattering
            # one winning.
            #
            # The wiring question and the provability question are different and
            # both are answered here: a producer DOES emit the name (so this is
            # not the "no producer at all" shape), and it has never once
            # measured it (so no group containing it can be satisfied).
            return state not in ("NOT_MEASURED", "NO_RECORD")
        
        if state in ("NO_RECORD", "NOT_MEASURED", ""):
            return False
        recs = obj.get("records")
        return recs is None or (isinstance(recs, int) and recs > 0)

    def walk_json(obj, where: str) -> None:
        if isinstance(obj, dict):
            name = obj.get("metric")
            if isinstance(name, str) and name in keys and _is_evidence(obj):
                found[name].add(where)
            for v in obj.values():
                walk_json(v, where)
        elif isinstance(obj, list):
            for v in obj:
                walk_json(v, where)

    for dirpath, dirnames, filenames in os.walk(tree_root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS
                       and not os.path.islink(os.path.join(dirpath, d))]
        for fn in sorted(filenames):
            if not fn.endswith(".json"):
                continue
            path = Path(dirpath) / fn
            try:
                import json
                obj = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            try:
                rel = path.relative_to(tree_root).as_posix()
            except ValueError:
                rel = str(path)
            walk_json(obj, rel)
    return found


def evaluate(programs: Path, tree_root: Path):
    """(unprovable axes, dead proof keys, axis count, key count, emitted)."""
    axes = axis_table(programs)
    keys: Dict[str, str] = collections.OrderedDict()
    for ax in axes:
        for group in ax.groups:
            for proof in group:
                keys.setdefault(proof.metric, ax.name)
    prod = producers(tree_root, set(keys))
    unprovable: List[Tuple[str, List[List[str]]]] = []
    dead: List[Tuple[str, str]] = []
    for ax in axes:
        satisfiable = [all(prod.get(p.metric) for p in group)
                       for group in ax.groups]
        if not any(satisfiable):
            unprovable.append(
                (ax.name, [[p.metric for p in g] for g in ax.groups]))
            continue
        for group in ax.groups:
            for proof in group:
                if not prod.get(proof.metric):
                    dead.append((proof.metric, ax.name))
    return unprovable, sorted(set(dead)), len(axes), len(keys), len(prod)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".")
    try:
        args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit:
        return 3
    root = Path(args.root)
    if not root.is_dir():
        print(f"[{NAME}] BAD INVOCATION — {args.root!r} is not a directory.",
              file=sys.stderr)
        return 3
    programs = root / PROGRAMS_REL
    if not programs.is_dir():
        programs = root                  # allow pointing straight at programs/
    try:
        unprovable, dead, axis_count, key_count, emitted = evaluate(
            programs, root)
    except Exception as exc:                        # noqa: BLE001
        print(f"[{NAME}] NOT CHECKED — the axis table could not be read, so no "
              f"axis was judged: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    # THE EMPTY-CORPUS CHECK COMES FIRST, AND THAT ORDER IS THE RULE.
    #
    # Over a tree with no metric records EVERY axis is trivially unprovable, so
    # computing the findings first and returning NOT CHECKED afterwards printed
    # nine "STRUCTURALLY UNPROVABLE ... forever" lines about a corpus nobody had
    # looked at. The exit code was right and the output was an unearned claim —
    # absence rendered as a finding, which is the exact error this whole family
    # of rules exists to refuse. A caller reading stdout would have acted on it.
    if emitted == 0:
        print(f"[{NAME}] NOT CHECKED — no canonical metric record was found "
              f"under {str(root)!r}, so no axis was judged and NO finding is "
              f"reported: over an empty corpus every axis is unprovable for the "
              f"same reason. This gate answers only about runs it can see.",
              file=sys.stderr)
        print(f"examined {axis_count} axis/axes over {key_count} canonical "
              f"metric key(s); 0 key(s) observed in emitted records")
        return 2
    for name, groups in unprovable:
        print(f"axis {name!r} IS NOT PROVEN BY ANY RUN IN THIS CORPUS — no "
              f"group of its proofs has a MEASURED record anywhere under this "
              f"tree: {groups}. Every run reports its own evidence as missing "
              f"rather than the wiring. This gate is EMPIRICAL, so it says what "
              f"the runs it can see did; whether the flow COULD ever measure it "
              f"is a source question, and `gate_proof_vocabulary_has_a_producer` "
              f"is the instrument for that.")
    for key, axis in dead:
        print(f"DISCLOSED — {key!r} (axis {axis!r}) has no producer; the axis is "
              f"still provable by another group, so this proof path is dead "
              f"weight that silently narrows it.", file=sys.stderr)
    print(f"examined {axis_count} axis/axes over {key_count} canonical metric "
          f"key(s); {emitted} key(s) observed in emitted records; "
          f"{len(dead)} dead proof path(s) disclosed")
    if axis_count == 0:
        print(f"[{NAME}] NOT CHECKED — the axis table declares no axis, so this "
              f"gate walked an empty set. Not a pass.", file=sys.stderr)
        return 2
    if unprovable:
        # SAY WHAT WAS FOUND, NOT WHAT THE FILENAME ASKS.
        #
        # This line used to read "an axis proves from a metric nothing emits",
        # and that is FALSE of what this gate actually finds. Both flagged axes
        # HAVE live producers — `_ppa/signoff.py` and `ppa-e2e/tools/
        # signoff_records.py` declare `reliability.em.violations` and
        # `equivalence.verdict` by name. What is true is that no run has ever
        # MEASURED them: 0 MEASURED against 370 NOT_MEASURED apiece.
        #
        # The wiring question ("is there a producer") and the evidence question
        # ("did any run measure it") are different, and a verdict line that
        # answers one while naming the other is the same defect this lane
        # diagnosed in another lane's gate an hour earlier. The filename asks
        # the wiring question; the finding is about evidence; the line now says
        # evidence.
        print(f"[{NAME}] FAIL — an axis has no MEASURED evidence in any run "
              f"this gate can see (a producer may exist and never have measured "
              f"it; see the per-axis lines above)")
        return 1
    print(f"[{NAME}] PASS — every axis has at least one proof group MEASURED in "
          f"some run this gate can see")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
