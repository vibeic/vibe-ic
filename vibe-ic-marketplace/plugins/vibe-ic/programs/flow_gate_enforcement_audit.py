#!/usr/bin/env python3
"""
flow_gate_enforcement_audit.py — which flow gates can actually STOP a run, and
which only get to complain afterwards (#306).

The defect
----------
`cts_quality_check` exists, is wired into `flow/phase1_phase2_phase3.yaml`, has
tests, and FAILed correctly on the SAME cell across three consecutive plugin
versions. The flow ran to completion every time: post_cts.def 44 MB,
routed.def 181 MB, post_hold.def 44 MB. It is the one gate that could have
caught #300 (the clock port bound to a 0-sink decoy) at source. It caught it
three times and stopped nothing. Eleven gates FAILed in that same run.

Root cause, measured by this program: the step runners execute the flow's
`program_exit_zero` gates NOWHERE. The gates are evaluated only by
`flow_compliance_check`, which the runner invokes as `final_audit` — the LAST
step, after every artefact has already been written. So a gate cannot block the
step it guards; it can only describe, afterwards, a run that already happened.

A gate that FAILs but cannot block differs from no gate at all only in that the
failure is searchable later.

What this audits
----------------
For every `program_exit_zero` gate in the flow definition:

  ENFORCED    a runner invokes it inline, so it can stop the step it guards
  AUDIT_ONLY  reached only through the final compliance audit — it describes,
              it does not block
  DECLARED    the gate program declares its own intent in its docstring via
              `ENFORCEMENT: blocking` or `ENFORCEMENT: advisory`
  UNDECLARED  no declaration — the intent is unknown, which is how 66 of 72
              gates ended up de-facto advisory without anyone deciding that

This program DESCRIBES; it does not change flow behaviour. Turning audit-only
gates into blocking ones is a deliberate product decision with real blast
radius (11 gates FAILing in one run means those runs start failing — correctly,
but that is an owner's call, not a side effect of an audit tool).

Exit codes:
    0  audit completed
    1  a gate DECLARING `ENFORCEMENT: blocking` is only AUDIT_ONLY — a
       contradiction between stated intent and wiring
    2  I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_RUNNERS = ("phase3_one_shot_runner.py", "design_one_shot_runner.py",
            "vibe_ic_one_shot_runner.py", "phase23_one_shot_runner.py",
            "phase1_one_shot_runner.py", "analog_one_shot_runner.py")
_GATE_RE = re.compile(
    # #306 — `advisory_` is the non-blocking slot; a gate wired there IS wired.
    r"(?:optional_|advisory_)?program_exit_zero:\s*[\"']?([\w./-]+)")
_DECL_RE = re.compile(r"ENFORCEMENT:\s*(blocking|advisory)", re.IGNORECASE)
# The second channel: intent stated in the JSON the gate emits. Captures the
# WHOLE right-hand side, not just a leading string literal — see
# `declared_intent` for why a value-only match reads a conditional expression
# as an unconditional declaration.
_VERDICT_MODE_RE = re.compile(r'"verdict_mode":\s*([^,\n}]+)')
_LONE_MODE_RE = re.compile(r'^"(BLOCKS|ADVISES)"$')


def _flow_def(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit)
    return _HERE.parent / "flow" / "phase1_phase2_phase3.yaml"


def gates_in_flow(flow: Path) -> List[str]:
    return sorted(set(_GATE_RE.findall(flow.read_text(errors="replace"))))


def runner_source(programs: Path) -> str:
    out = []
    for r in _RUNNERS:
        p = programs / r
        if p.is_file():
            out.append(p.read_text(errors="replace"))
    return "\n".join(out)


def _invoked(src: str, gate: str) -> bool:
    """A runner INVOKES the gate — as a subprocess command string or as an
    imported call. A bare mention in a comment does not count."""
    stem = gate[:-3] if gate.endswith(".py") else gate
    if re.search(r"[\"'][^\"'\n]*\b" + re.escape(stem) + r"\.py\b", src):
        return True
    return bool(re.search(r"\b" + re.escape(stem) + r"\s*\.\s*(?:main|check|audit)\s*\(", src))


def declared_intent(programs: Path, gate: str) -> Optional[str]:
    stem = gate if gate.endswith(".py") else gate + ".py"
    p = programs / stem
    if not p.is_file():
        return None
    text = p.read_text(errors="replace")
    m = _DECL_RE.search(text[:4000])
    if m:
        return m.group(1).lower()
    # SECOND DECLARATION CHANNEL, measured 2026-07-26. Some gates state their
    # intent in the JSON they EMIT (`"verdict_mode": "BLOCKS" / "ADVISES"`)
    # rather than in an `ENFORCEMENT:` docstring line. This audit read only
    # the docstring, so it reported those gates as UNDECLARED and a wiring
    # decision could be made without ever seeing what they said about
    # themselves.
    #
    # A CONDITIONAL mode is deliberately NOT read as a declaration:
    # `"BLOCKS" if strict else "ADVISES"` says the intent depends on a flag,
    # so claiming either would be inventing a declaration the program did not
    # make. Those stay UNDECLARED, which is the truth.
    modes = set()
    for rhs in _VERDICT_MODE_RE.findall(text):
        m2 = _LONE_MODE_RE.match(rhs.strip())
        if not m2:
            # A conditional / computed value (`"BLOCKS" if strict else
            # "ADVISES"`) is NOT a declaration. The first version of this
            # guard failed on exactly the case it was written for: matching
            # only the string VALUE after the key saw `"BLOCKS"` and nothing
            # else, so a gate whose default mode is ADVISES was reported as
            # declaring blocking. Capture the whole RHS and require it to be
            # a lone literal.
            return None
        modes.add(m2.group(1))
    if len(modes) == 1:
        return {"BLOCKS": "blocking", "ADVISES": "advisory"}[modes.pop()]
    return None


def audit(flow: Path, programs: Path) -> dict:
    gates = gates_in_flow(flow)
    src = runner_source(programs)
    rows = []
    for g in gates:
        enforced = _invoked(src, g)
        rows.append({
            "gate": g,
            "enforcement": "ENFORCED" if enforced else "AUDIT_ONLY",
            "declared": declared_intent(programs, g),
        })
    # ORPHANED: a gate program that DECLARES an enforcement intent but is not
    # referenced by the flow definition at all. Worse than AUDIT_ONLY — not
    # even the final compliance audit reaches it, so it runs only if someone
    # invokes it by hand. Found this way: two gates added earlier in this
    # campaign were never wired into the flow, so they could not fire at all.
    in_flow = {r["gate"] for r in rows}
    orphaned = []
    for f in sorted(programs.glob("*_check.py")) + sorted(programs.glob("*_disclosure.py")):
        stem = f.stem
        if stem in in_flow or f"{stem}.py" in in_flow:
            continue
        intent = declared_intent(programs, stem)
        if intent:
            orphaned.append({"gate": stem, "declared": intent,
                             "enforcement": "ORPHANED"})
    contradictions = [r for r in rows
                      if r["declared"] == "blocking"
                      and r["enforcement"] == "AUDIT_ONLY"]
    return {
        "total_gates": len(rows),
        "enforced": sum(1 for r in rows if r["enforcement"] == "ENFORCED"),
        "audit_only": sum(1 for r in rows if r["enforcement"] == "AUDIT_ONLY"),
        "declared": sum(1 for r in rows if r["declared"]),
        "undeclared": sum(1 for r in rows if not r["declared"]),
        "contradictions": contradictions,
        "orphaned": orphaned,
        "gates": rows,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit which flow gates can actually stop a run.")
    ap.add_argument("--flow", help="flow definition YAML")
    ap.add_argument("--programs", help="programs dir (default: this one)")
    ap.add_argument("--json", help="write the report here")
    ap.add_argument("--baseline", help="known-debt file; NEW contradictions "
                    "and NEW orphans fail, the recorded ones do not")
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the CURRENT set; it may only ever shrink")
    ap.add_argument("--scope-expanded", metavar="REASON",
                    help="permit a GROWING baseline for this write, because "
                         "the audit now LOOKS at more than it did (>=30 chars; "
                         "recorded in the baseline beside the previous size)")
    a = ap.parse_args(argv)
    flow = _flow_def(a.flow)
    programs = Path(a.programs) if a.programs else _HERE
    if not flow.is_file():
        print(f"IO_ERROR: no flow definition at {flow}", file=sys.stderr)
        return 2
    rep = audit(flow, programs)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    pct = 100 * rep["audit_only"] // max(1, rep["total_gates"])
    print("=== flow gate enforcement audit ===")
    print(f"gates in flow definition : {rep['total_gates']}")
    print(f"  ENFORCED (can block)   : {rep['enforced']}")
    print(f"  AUDIT_ONLY (describes) : {rep['audit_only']}  ({pct}%)")
    print(f"declared intent          : {rep['declared']} "
          f"({rep['undeclared']} UNDECLARED)")
    if rep.get("orphaned"):
        print("\nORPHANED — declare an intent but are NOT in the flow definition,\n"
              "so not even the final audit reaches them:")
        for o in rep["orphaned"]:
            print(f"  {o['gate']}  (declared {o['declared']})")
    # A gate that DECLARES blocking and is wired audit-only, or that declares
    # an intent and is not in the flow at all, is the very defect this audit
    # names — measured in a gate's own terms. Four such gates exist today, two
    # of them added during this campaign: declaring an intent is not wiring
    # it. Fixing them changes what a real run BLOCKS on, which is the flow
    # owner's decision, not this audit's. So the four are recorded as DEBT and
    # this audit blocks anything NEW — the class stops growing without the
    # audit quietly deciding enforcement policy on its own.
    now = sorted([f"contradiction::{c['gate']}" for c in rep["contradictions"]]
                 + [f"orphan::{o['gate']}" for o in (rep.get("orphaned") or [])])
    bl_path = Path(a.baseline) if a.baseline else (
        _HERE / "flow_gate_enforcement_baseline.json")
    prev = None
    if bl_path.is_file():
        try:
            prev = sorted(str(x) for x in
                          (json.loads(bl_path.read_text()).get("known") or []))
        except (OSError, ValueError):
            prev = None
    if a.write_baseline:
        if a.scope_expanded is not None and len(a.scope_expanded.strip()) < 30:
            print("\n[FAIL] --scope-expanded needs a real reason (>=30 chars) "
                  "naming what the audit now looks at that it did not before.")
            return 1
        if (prev is not None and len(now) > len(prev)
                and a.scope_expanded is None):
            print(f"\n[FAIL] refusing to GROW the baseline "
                  f"({len(prev)} -> {len(now)}): this register records debt "
                  f"that must be paid down, never permission to add more. If "
                  f"the audit now LOOKS at more than it did, say so with "
                  f"--scope-expanded '<why>' — a wider scope finding "
                  f"pre-existing debt is not a regression, but it must be "
                  f"recorded, not assumed.")
            return 1
        bl_path.write_text(json.dumps(
            {"_comment": ("Gates that declare an intent they are not wired "
                          "for (vibe-ic#306/#316). MAY ONLY SHRINK. Fixing "
                          "one changes what a real run blocks on — a flow-"
                          "owner decision — so they are recorded, not "
                          "silently enforced here."),
             "previous_size": None if prev is None else len(prev),
             "scope_expanded": a.scope_expanded,
             "known": now}, indent=2, ensure_ascii=False) + "\n")
        print(f"\nwrote {bl_path} ({len(now)} entr(ies))")
        return 0
    if prev is None:
        return 1 if now else 0
    new = [k for k in now if k not in set(prev)]
    paid = [k for k in prev if k not in set(now)]
    if paid:
        print(f"\n[FAIL] {len(paid)} recorded entr(ies) no longer contradict "
              f"— the debt was paid; shrink the baseline so it cannot become "
              f"standing permission:")
        for k in paid:
            print(f"   (resolved) {k}")
    if new:
        print(f"\n[FAIL] {len(new)} NEW gate(s) declare an intent they are "
              f"not wired for:")
        for k in new:
            print(f"   {k}")
    if new or paid:
        return 1
    print(f"\n[PASS] no NEW enforcement contradiction "
          f"({len(now)} recorded as debt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
