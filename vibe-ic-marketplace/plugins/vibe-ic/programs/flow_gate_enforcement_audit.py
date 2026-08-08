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

A note on what counts as a declaration (#886): the two lines above MENTION the
token in prose. Until #886 this audit read them as a declaration about ITSELF,
because the pattern was unanchored. A declaration must OPEN its line; a mention
inside a sentence is not one. Several gates say in prose that they carry no
declaration, and the old pattern read each of those as declaring one.

Silence is not a decision (#886)
--------------------------------
UNDECLARED + AUDIT_ONLY was, until #886, the one state this audit could never
fail on. The only failing shape was "DECLARES blocking, wired AUDIT_ONLY", so
the audit could only fail a gate that had already gone to the trouble of
stating an intent — and saying nothing was the reliable way to stay clean.
Measured on this tree after #885: 113 of 150 gates are in that state while the
audit prints PASS. The class is now RECORDED in its own shrink-only register
and any NEW member fails.

Its OWN register, deliberately. `known` is documented — in this file, in
`flow_gate_enforcement_baseline.json` and in `test_316_the_recorded_debt_is_
named_not_hidden` — as "gates that DECLARE an intent they are not wired for".
A gate that declares NOTHING is not a member of that set, and merging the two
grew a shrink-only register from 0 to 86 entries in one commit, which
`test_306_register_never_grows` correctly refused. Different debt, different
paydown (state an intent, or invoke it inline), so: two registers, one file.

This program DESCRIBES; it does not change flow behaviour. Turning audit-only
gates into blocking ones is a deliberate product decision with real blast
radius (11 gates FAILing in one run means those runs start failing — correctly,
but that is an owner's call, not a side effect of an audit tool).

How the flow definition is read (ORGANIC #885, fixed 2026-08-09)
---------------------------------------------------------------
Until #885 this audit found gates by matching a REGEX over the flow YAML's raw
text. `\\s*` in that pattern spans newlines, so against the NESTED clause form
the flow uses for every conditional gate the match ran off the end of the line
and captured the next YAML key: 31 clauses collapsed into one literal gate
named `command`. The audit reported 120 gates where 150 are wired, so 31 real
gate programs were audited by nothing — and `post_route_signoff_corner_check`,
which IS invoked inline and CAN block, was credited with nothing.

The flow definition is now PARSED with PyYAML — the same loader
`flow_compliance_check` uses to execute these clauses — and walked
structurally, so this audit reads the grammar the engine runs rather than an
approximation of it. A flow it cannot parse is a hard error (rc 2), never a
shorter gate list: an under-count here is indistinguishable from a flow with
fewer gates, which is the exact class of lie this program exists to catch.

Where this audit itself runs
---------------------------
`tools/ci/repo_hygiene_gates.sh` invokes it BLOCKING (since v1.6.29, whose
subject was "a checker only its own TEST runs has judged nothing"), and
`tools/gatekeeper-land.sh` invokes that suite before any landing. Two tests
also execute it against the shipped tree. It reports the whole gap on every run
and still exits 0, because the gap is RECORDED below rather than silently
enforced — which is what lets a loud finding ride in a blocking gate without
turning the tree red on debt nobody has decided to pay yet.

Exit codes:
    0  audit completed
    1  a finding NEW since the recorded baseline, in EITHER register:
         `known`             contradiction  declares blocking, wired AUDIT_ONLY
                             orphan         declares an intent and is reachable
                                            from nothing at all
         `undeclared_known`  undeclared     AUDIT_ONLY and declares nothing
                                            (#886). Before #886 only the first
                                            two shapes could fail, so a gate
                                            that said nothing was exempt by
                                            construction — 113 of 150 gates
                                            were in that state while this audit
                                            printed PASS.
       — or a recorded entry that no longer holds, which must be paid down out
       of its register rather than left standing as permission.
    2  I/O error, or the flow definition could not be parsed
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    yaml = None  # type: ignore[assignment]

_HERE = Path(__file__).resolve().parent
_RUNNERS = ("phase3_one_shot_runner.py", "design_one_shot_runner.py",
            "vibe_ic_one_shot_runner.py", "phase23_one_shot_runner.py",
            "phase1_one_shot_runner.py", "analog_one_shot_runner.py")
# The three gate slots `flow_compliance_check._evaluate_gate` actually
# dispatches on. This audit must read the SAME grammar the flow engine reads —
# see `gates_in_flow` for the defect that motivated parsing instead of matching.
# #306 — `advisory_` is the non-blocking slot; a gate wired there IS wired.
_GATE_SLOTS = ("program_exit_zero", "optional_program_exit_zero",
               "advisory_program_exit_zero")
# A DECLARATION is a line that IS the declaration — `ENFORCEMENT:` opens the
# line, allowing only what can legitimately precede it: indentation, a `#`
# comment marker, or the quote that opens a one-line docstring
# (`"""ENFORCEMENT: advisory"""`). A MENTION of the token inside prose is not a
# declaration. Backticks are deliberately NOT in that prefix set: in this repo
# they are how a docstring quotes the token while talking ABOUT it.
#
# #886: the unanchored form read PROSE as intent. The worst case was this very
# file: the sentence above documenting the convention names both values, and
# the audit read it as a declaration ABOUT ITSELF. It stayed hidden only
# because the orphan glob could not reach a `*_audit.py`; widening that glob
# made the audit report itself as an ORPHAN declaring blocking. Same false
# positive in `analog_corner_margin_check`, `drc_report_check`,
# `lvs_report_check`, `professional_tb_check` and `phase3_one_shot_runner`,
# all of which discuss the token in backticks — several of them precisely to
# say they carry NO declaration.
#
# `[ \t]` and not `\s`: `\s` crosses newlines, so a bare `ENFORCEMENT:` at the
# end of one line would bind to a `blocking` that is prose on the next.
# Measured over all 120 in-flow gates: anchoring changes no gate's verdict.
_DECL_RE = re.compile(
    r"""^[ \t]*(?:\#[ \t]*)?(?:["']{1,3}[ \t]*)?"""
    r"""ENFORCEMENT:[ \t]*(blocking|advisory)\b""",
    re.IGNORECASE | re.MULTILINE)
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


class FlowGrammarError(RuntimeError):
    """The flow definition could not be read with the flow engine's own
    grammar. Never downgraded to a partial gate list: a shorter list reads as
    `fewer gates exist`, which is the exact lie this audit was written to
    catch."""


def _first_token(cmd: str) -> Optional[str]:
    """The gate PROGRAM name is the first whitespace-delimited token of the
    command, exactly as `_check_program_exit_zero` shlex-splits it."""
    parts = cmd.split()
    return parts[0] if parts else None


def _walk_clauses(node, out: List[dict]) -> None:
    """Collect every gate clause in the document, at any nesting depth.

    The flow definition nests gates under `gate:`, `all_of:`, `any_of:` and
    per-step lists, so the walk is recursive and structural rather than
    positional — a gate is wherever one of `_GATE_SLOTS` is a mapping key.
    """
    if isinstance(node, dict):
        for key, val in node.items():
            if key in _GATE_SLOTS:
                # Both shapes the flow engine accepts (see
                # `flow_compliance_check._evaluate_gate`): a bare command
                # STRING, or a MAPPING carrying `command:` (plus optional
                # `condition_files_exist:`).
                cmd = val.get("command") if isinstance(val, dict) else val
                name = _first_token(cmd) if isinstance(cmd, str) else None
                out.append({"slot": key, "gate": name, "command": cmd})
            _walk_clauses(val, out)
    elif isinstance(node, list):
        for item in node:
            _walk_clauses(item, out)


def clauses_in_flow(flow: Path) -> List[dict]:
    """Every gate clause the flow engine would dispatch on, in document order.

    THE DEFECT THIS REPLACED (ORGANIC #885, measured 2026-08-09). The previous
    implementation matched
    `(?:optional_|advisory_)?program_exit_zero:\\s*["']?([\\w./-]+)` over the
    RAW TEXT. `\\s*` spans newlines, so against the nested clause form the flow
    definition uses everywhere for conditional gates:

        - optional_program_exit_zero:
            command: "spare_cell_preservation_check . --json ..."
            condition_files_exist: [...]

    the match ran past the end of the line and captured the NEXT YAML key. All
    31 such clauses collapsed into one literal gate named `command`, so the
    audit reported 120 gates instead of 150 and 31 real gate programs — among
    them `post_route_signoff_corner_check`, which IS wired inline and blocking
    — were audited by nothing at all. An enforcement audit that cannot see a
    gate cannot report that gate is unenforced, so the gap it exists to measure
    was under-reported by 31.

    Parsing with PyYAML — the same loader `flow_compliance_check` uses — means
    the audit reads the grammar the engine executes, not an approximation of
    it, so a future clause shape cannot silently drop out again.
    """
    if yaml is None:
        raise FlowGrammarError(
            "PyYAML required to read the flow definition (pip install pyyaml)")
    try:
        doc = yaml.safe_load(flow.read_text(errors="replace"))
    except yaml.YAMLError as exc:
        raise FlowGrammarError(f"cannot parse {flow}: {exc}") from exc
    out: List[dict] = []
    _walk_clauses(doc, out)
    return out


def gates_in_flow(flow: Path) -> List[str]:
    """Unique gate program names wired into the flow definition."""
    return sorted({c["gate"] for c in clauses_in_flow(flow) if c["gate"]})


def runner_source(programs: Path) -> str:
    out = []
    for r in _RUNNERS:
        p = programs / r
        if p.is_file():
            out.append(p.read_text(errors="replace"))
    return "\n".join(out)


def repo_gate_source(programs: Path) -> str:
    """The repo-wide hygiene gate suite, if the tree under audit has one.

    THE SECOND PLACE A DECLARATION CAN BE WIRED (#886). `orphan` asserts
    something strong — "declares an intent and NOTHING runs it, so it fires
    only if somebody types it by hand". Until this function existed the audit
    knew ONE venue, the flow definition, so it made that claim about any
    program absent from a flow YAML, including programs that were never meant
    to appear in one.

    It cost a false positive the moment the orphan glob widened past
    `*_check.py`. `silent_decline_audit` declares `ENFORCEMENT: advisory`, is
    absent from the flow definition, and runs BLOCKING on every landing at
    `tools/ci/repo_hygiene_gates.sh:646` with `--ratchet`. Reporting it as
    unreachable is false, and it would have been recorded as debt nobody could
    pay: it is not a flow gate, so the only way to clear the entry would have
    been to wire it somewhere it does not belong.

    Derived from the tree UNDER AUDIT, never from this file's own location: a
    synthetic tree in a temp dir has no `tools/ci`, gets the empty string, and
    is judged only on what it actually contains.

    COMMENT LINES ARE STRIPPED, for the same reason `_invoked` refuses a bare
    mention in a runner comment: this suite documents heavily, and several
    gates are named in prose explaining why they are NOT wired here. Counting
    that as wiring would be the false negative that mirrors the false positive
    this function removes.
    """
    for base in (programs, *programs.parents[:4]):
        ci = base / "tools" / "ci"
        if ci.is_dir():
            text = "\n".join(p.read_text(errors="replace")
                             for p in sorted(ci.glob("*.sh")))
            return "\n".join(ln for ln in text.splitlines()
                             if not ln.lstrip().startswith("#"))
    return ""


def _invoked_by_suite(ci_src: str, gate: str) -> bool:
    """The shell suite invokes a program by PATH, quoted or not (`python3
    "$PG/x.py"` and `python3 programs/x.py` both occur). `ci_src` has already
    had its comment lines removed, so a bare token match is sound here in a way
    it is not in Python source."""
    stem = gate[:-3] if gate.endswith(".py") else gate
    return bool(re.search(r"\b" + re.escape(stem) + r"\.py\b", ci_src))


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
    clauses = clauses_in_flow(flow)
    # A clause the walk reached but could not name is NOT dropped. Silently
    # discarding it would reintroduce #885 in a new shape: an unnamed gate
    # would once again be a gate the audit does not report on. It is surfaced
    # so the flow author sees an unrunnable clause rather than a short tally.
    malformed = [{"slot": c["slot"], "command": c["command"]}
                 for c in clauses if not c["gate"]]
    gates = sorted({c["gate"] for c in clauses if c["gate"]})
    slots: Dict[str, set] = {}
    for c in clauses:
        if c["gate"]:
            slots.setdefault(c["gate"], set()).add(c["slot"])
    src = runner_source(programs)
    rows = []
    for g in gates:
        enforced = _invoked(src, g)
        rows.append({
            "gate": g,
            "enforcement": "ENFORCED" if enforced else "AUDIT_ONLY",
            "declared": declared_intent(programs, g),
            "slots": sorted(slots[g]),
        })
    # #886: a gate that is AUDIT_ONLY and declares NOTHING. This class was
    # structurally exempt from every failing branch below, which is the defect
    # in one line: the audit could only fail on gates that had already gone to
    # the trouble of stating an intent, so NOT stating one was the reliable way
    # to stay clean. 85 of 120 gates were in this class while the audit exited
    # 0 with a PASS. Silence is not a decision — it is the absence of one.
    undeclared_audit_only = [
        {"gate": r["gate"], "enforcement": "AUDIT_ONLY", "declared": None}
        for r in rows
        if r["enforcement"] == "AUDIT_ONLY" and not r["declared"]]
    # ORPHANED: a gate program that DECLARES an enforcement intent but is not
    # referenced by the flow definition at all. Worse than AUDIT_ONLY — not
    # even the final compliance audit reaches it, so it runs only if someone
    # invokes it by hand. Found this way: two gates added earlier in this
    # campaign were never wired into the flow, so they could not fire at all.
    in_flow = {r["gate"] for r in rows}
    orphaned = []
    # #886, TWO changes that are only sound together.
    #
    # (1) The glob used to be `*_check.py` + `*_disclosure.py`, which decided
    # what could be an orphan by FILENAME. A declaration is the signal, not the
    # suffix, and that suffix list could not reach a `*_audit.py` or a `*_lint.py`
    # at all. Every `*.py` is now offered to `declared_intent`; it decides.
    #
    # (2) Widening the POPULATION without widening "what counts as wired" is how
    # a scan turns into noise. Measured over all 1127 `*.py` in this directory,
    # the wider glob surfaces exactly ONE new orphan candidate —
    # `silent_decline_audit` — and it is a FALSE POSITIVE: it runs blocking on
    # every landing from the repo-hygiene suite. An earlier draft of this change
    # recorded it as debt on the strength of not appearing in a flow YAML it was
    # never meant to appear in. `repo_gate_source` is that second venue.
    src_ci = repo_gate_source(programs)
    for f in sorted(programs.glob("*.py")):
        stem = f.stem
        if stem in in_flow or f"{stem}.py" in in_flow:
            continue
        if _invoked_by_suite(src_ci, stem):
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
        "total_clauses": len(clauses),
        "enforced": sum(1 for r in rows if r["enforcement"] == "ENFORCED"),
        "audit_only": sum(1 for r in rows if r["enforcement"] == "AUDIT_ONLY"),
        "declared": sum(1 for r in rows if r["declared"]),
        "undeclared": sum(1 for r in rows if not r["declared"]),
        "contradictions": contradictions,
        "orphaned": orphaned,
        "malformed_clauses": malformed,
        "undeclared_audit_only": undeclared_audit_only,
        "gates": rows,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit which flow gates can actually stop a run.")
    ap.add_argument("--flow", help="flow definition YAML")
    ap.add_argument("--programs", help="programs dir (default: this one)")
    ap.add_argument("--json", help="write the report here")
    ap.add_argument("--baseline", help="known-debt file carrying BOTH "
                    "registers: `known` (contradiction/orphan) and "
                    "`undeclared_known` (#886). NEW entries in either fail, "
                    "the recorded ones do not. A register the file does not "
                    "mention is UNRECORDED, which is not the same as empty")
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
    try:
        rep = audit(flow, programs)
    except FlowGrammarError as exc:
        # NEVER degrade to a partial read. A gate list that is short because
        # the parser failed is indistinguishable from a flow with fewer gates,
        # and this audit exists to stop exactly that confusion.
        print(f"IO_ERROR: {exc}", file=sys.stderr)
        return 2
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    pct = 100 * rep["audit_only"] // max(1, rep["total_gates"])
    print("=== flow gate enforcement audit ===")
    print(f"gate clauses in flow def : {rep['total_clauses']}")
    print(f"gates in flow definition : {rep['total_gates']}")
    print(f"  ENFORCED (can block)   : {rep['enforced']}")
    print(f"  AUDIT_ONLY (describes) : {rep['audit_only']}  ({pct}%)")
    print(f"declared intent          : {rep['declared']} "
          f"({rep['undeclared']} UNDECLARED)")
    if rep.get("malformed_clauses"):
        print("\nMALFORMED — a gate slot with no runnable `command`. It runs "
              "nothing,\nso it certifies nothing:")
        for m in rep["malformed_clauses"]:
            print(f"  {m['slot']}: {m['command']!r}")
    if rep.get("orphaned"):
        print("\nORPHANED — declare an intent, are NOT in the flow definition,\n"
              "and no repo-gate suite invokes them either, so not even the\n"
              "final audit reaches them:")
        for o in rep["orphaned"]:
            print(f"  {o['gate']}  (declared {o['declared']})")
    if rep.get("undeclared_audit_only"):
        print(f"\nUNDECLARED and AUDIT_ONLY — {len(rep['undeclared_audit_only'])} "
              f"gate(s): no runner invokes them inline, and nothing in the gate "
              f"says\nthat was intended. Until #886 this class could not fail "
              f"this audit at all,\nso not declaring an intent was the reliable "
              f"way to stay clean.")
    # A gate that DECLARES blocking and is wired audit-only, or that declares
    # an intent and is reachable from nothing at all, is the very defect this
    # audit names — measured in a gate's own terms. The register held four when
    # #306 opened it and holds ZERO today, all four paid down. Fixing one
    # changes what a real run BLOCKS on, which is the flow owner's decision and
    # not this audit's, so they are recorded as DEBT while this audit blocks
    # anything NEW — the class stops growing without the audit quietly deciding
    # enforcement policy on its own.
    #
    # TWO REGISTERS, NOT ONE (#886). `known`'s stated contract — in this file,
    # in the baseline's own `_comment`, and asserted by
    # `test_316_the_recorded_debt_is_named_not_hidden` — is "gates that DECLARE
    # an intent they are not wired for". A gate that declares NOTHING cannot
    # join that set without making the register's own description false, and an
    # earlier draft that merged them grew a SHRINK-ONLY register from 0 to 86
    # entries in a single commit, which `test_306_register_never_grows`
    # correctly refused. The undeclared class is real debt and must ratchet,
    # but it is DIFFERENT debt, paid down differently: by the gate stating an
    # intent, or by a runner invoking it inline, where a `contradiction::` is
    # paid by reconciling a declaration that already exists.
    now = sorted([f"contradiction::{c['gate']}" for c in rep["contradictions"]]
                 + [f"orphan::{o['gate']}" for o in (rep.get("orphaned") or [])])
    now_u = sorted(f"undeclared::{u['gate']}"
                   for u in (rep.get("undeclared_audit_only") or []))
    bl_path = Path(a.baseline) if a.baseline else (
        _HERE / "flow_gate_enforcement_baseline.json")
    doc: dict = {}
    if bl_path.is_file():
        try:
            loaded = json.loads(bl_path.read_text())
            doc = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            doc = {}

    def _recorded(key: str) -> Optional[List[str]]:
        """A register that is ABSENT is UNRECORDED, not empty. The two differ:
        an empty register asserts "no debt", an absent one asserts nothing at
        all, and reading absence as emptiness would report every pre-existing
        entry as `paid` the first time a baseline written by an older version
        of this program is read."""
        if key not in doc:
            return None
        return sorted(str(x) for x in (doc.get(key) or []))

    prev = _recorded("known")
    prev_u = _recorded("undeclared_known")
    if a.write_baseline:
        if a.scope_expanded is not None and len(a.scope_expanded.strip()) < 30:
            print("\n[FAIL] --scope-expanded needs a real reason (>=30 chars) "
                  "naming what the audit now looks at that it did not before.")
            return 1
        widened = {}
        for label, p, n in (("known", prev, now),
                            ("undeclared_known", prev_u, now_u)):
            # A register that GREW, or that is being CREATED non-empty, is a
            # claim about scope and needs the reason recorded against IT. A
            # register that did not move records `null`, so a reason given for
            # one can never read afterwards as standing permission for the
            # other — which is how a single flag would have silently licensed
            # future growth in a register it was never about.
            widened[label] = ((p is None and bool(n))
                              or (p is not None and len(n) > len(p)))
            if widened[label] and a.scope_expanded is None:
                print(f"\n[FAIL] refusing to GROW the baseline `{label}` "
                      f"({'unrecorded' if p is None else len(p)} -> {len(n)}): "
                      f"this register records debt that must be paid down, "
                      f"never permission to add more. If the audit now LOOKS "
                      f"at more than it did, say so with --scope-expanded "
                      f"'<why>' — a wider scope finding pre-existing debt is "
                      f"not a regression, but it must be recorded, not "
                      f"assumed.")
                return 1
        bl_path.write_text(json.dumps(
            {"_comment": ("Gates that declare an intent they are not wired "
                          "for (vibe-ic#306/#316). MAY ONLY SHRINK. Fixing "
                          "one changes what a real run blocks on — a flow-"
                          "owner decision — so they are recorded, not "
                          "silently enforced here."),
             "previous_size": None if prev is None else len(prev),
             "scope_expanded": a.scope_expanded if widened["known"] else None,
             "known": now,
             "undeclared_comment": (
                 "Gates that are AUDIT_ONLY and declare NO intent at all "
                 "(vibe-ic#886) — enforcement was never decided, which is a "
                 "DIFFERENT defect from declaring one thing and being wired "
                 "another, so it is a SEPARATE shrink-only register. Paid down "
                 "by the gate stating `ENFORCEMENT:` / `verdict_mode`, or by a "
                 "runner invoking it inline. NOT by deleting the entry: the "
                 "audit recomputes this set on every run, so a deleted line "
                 "comes straight back as NEW and fails."),
             "undeclared_previous_size": (
                 None if prev_u is None else len(prev_u)),
             "undeclared_scope_expanded": (
                 a.scope_expanded if widened["undeclared_known"] else None),
             "undeclared_known": now_u}, indent=2, ensure_ascii=False) + "\n")
        print(f"\nwrote {bl_path} ({len(now)} contradiction/orphan, "
              f"{len(now_u)} undeclared)")
        return 0
    rc = 0
    # An UNRECORDED register with findings exits 1 and SAYS why. The previous
    # shape returned 1 here and printed nothing at all, so the one caller that
    # can hit it — a baseline written before the register existed — got a bare
    # non-zero exit from a program whose whole subject is verdicts that do not
    # explain themselves.
    if prev is None:
        if now:
            print(f"\n[FAIL] `known` is UNRECORDED in {bl_path.name} and "
                  f"{len(now)} finding(s) stand. Record them with "
                  f"--write-baseline --scope-expanded '<why>':")
            for k in now:
                print(f"   {k}")
            rc = 1
    else:
        new = [k for k in now if k not in set(prev)]
        paid = [k for k in prev if k not in set(now)]
        if paid:
            print(f"\n[FAIL] {len(paid)} recorded entr(ies) no longer "
                  f"contradict — the debt was paid; shrink the baseline so it "
                  f"cannot become standing permission:")
            for k in paid:
                print(f"   (resolved) {k}")
        if new:
            print(f"\n[FAIL] {len(new)} NEW gate(s) declare an intent they are "
                  f"not wired for:")
            for k in new:
                print(f"   {k}")
        if new or paid:
            rc = 1
    # The #886 register reports in its OWN words. The sentence above is FALSE
    # about this class — an `undeclared::` gate declares nothing, so it cannot
    # "declare an intent it is not wired for" — and reusing it would have made
    # this audit's own report a small lie about the defect it had just found.
    if prev_u is None:
        if now_u:
            print(f"\n[FAIL] `undeclared_known` is UNRECORDED in "
                  f"{bl_path.name} and {len(now_u)} gate(s) are AUDIT_ONLY "
                  f"while declaring no intent at all. This class was exempt "
                  f"from this audit by construction until #886; it is debt, "
                  f"not absence of debt. Record it with --write-baseline "
                  f"--scope-expanded '<why>'.")
            rc = 1
    else:
        new_u = [k for k in now_u if k not in set(prev_u)]
        paid_u = [k for k in prev_u if k not in set(now_u)]
        if paid_u:
            print(f"\n[FAIL] {len(paid_u)} recorded undeclared gate(s) now "
                  f"state an intent or are invoked inline — the debt was paid; "
                  f"shrink `undeclared_known` so it cannot become standing "
                  f"permission:")
            for k in paid_u:
                print(f"   (resolved) {k}")
        if new_u:
            print(f"\n[FAIL] {len(new_u)} NEW gate(s) are AUDIT_ONLY and "
                  f"declare no intent at all — nothing invokes them where they "
                  f"could block, and nothing in the gate says that was the "
                  f"decision:")
            for k in new_u:
                print(f"   {k}")
        if new_u or paid_u:
            rc = 1
    if rc:
        return rc
    print(f"\n[PASS] no NEW enforcement contradiction "
          f"({len(now)} recorded as debt; {len(now_u)} gate(s) recorded as "
          f"UNDECLARED and audit-only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
