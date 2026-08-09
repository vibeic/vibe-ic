#!/usr/bin/env python3
"""l7_debug_access_grounding_check.py — L7 SEMANTIC gate (ADVISORY).

READ THIS FIRST — WHY THIS GATE IS DELIBERATELY WEAK
====================================================
The principle every layer gate here embodies is:

    A layer is complete when the requirement is present IN THE LAYER
    THAT CONSUMES IT, in an actionable form — not when a token appears
    somewhere.

Applied honestly to L7, that principle says something uncomfortable:
**L7_TEST_DEBUG.json has no downstream consumer.** Every reader is
phase1-internal bookkeeping — ``phase1_doc_presence_check``,
``phase1_consistency_check``, ``l_doc_parity_diff``,
``phase1_doc_one_shot_runner``. It was verified that
``dft_signoff_check``, ``dft_atpg_coverage_check`` and the ``eda_dft``
MCP tool do NOT read L7. Nothing in Phase 2 or Phase 3 dereferences it.

So there is no consumer contract to enforce, and a gate that demanded
"L7 must contain a JTAG TAP pin list" would gate nothing: it could not
protect any artifact, and on a design with no test/debug content in its
input it would demand fabrication — the opposite of §4.05.

WHAT IS LEFT THAT IS REAL
=========================
One thing. L7 does not FEED anything, but it makes CLAIMS about the
design, and those claims can be checked against the layers that DO feed
the backend. An L7 that names a debug-access signal which exists in no
pin table and no port list is either (a) evidence that L1/L9 are missing
a port the design actually needs — a real backend gap, because a test
pin absent from the pin table never gets a port or a pad — or (b) an
extractor hallucination. Both are worth surfacing; neither justifies
stopping a run.

RULES (derived from the design's own L-docs; no design name, PDK name,
vendor part number or pin literal appears anywhere in this file)
=====================================================================

L7_DEBUG_SIGNAL_UNGROUNDED  (WARN)
    A signal L7 names as a test/debug ACCESS POINT
    (``debug_observability[].signals``, ``test_modes[].pins|signals|
    entry_pins``, ``formal_interfaces[].signals``, ``test_scenarios[]
    .pins|signals``) resolves in NONE of the layers that actually
    implement pins: L9 ``top_module_pins``/``top_ports``/``ports``, L1
    ``pin_table``, L9 ``internal_wires`` nets, or the L17 channel signal
    catalogue. Matching is case-insensitive and bus-subscript tolerant.
    Only runs when at least one of those namespaces is non-empty —
    otherwise there is nothing to ground against and the rule skips.

L7_DEBUG_REGISTER_UNGROUNDED  (WARN)
    A ``debug_registers[].name`` resolves in neither the L4 register
    namespace nor L9 ``registers``. Only runs when L4 declares a
    non-empty register namespace.

L7_TEST_MODE_NOT_ENTERABLE  (WARN)
    A declared ``test_modes[]`` entry has no entry pins, no entry
    signals and no entry sequence — a mode nobody can enter is prose,
    not a requirement.

DOES IT BLOCK? — AND THE DEFECT THAT ANSWER USED TO HIDE
========================================================
**IT ADVISES — because of the SLOT it is wired into, not because of its
exit code.**

It is wired at flow step D1 as::

    - advisory_program_exit_zero: "l7_debug_access_grounding_check ."

``flow_compliance_check._evaluate_gate``'s advisory branch RUNS the
program, RECORDS the verdict, and returns ``True`` unconditionally — it
cannot fail a step. That slot, and nothing else, is what makes this gate
non-blocking.

THE DEFECT (fixed here). Every earlier version returned 0 unless
``--strict`` was passed, and NO caller passes it: the flow wiring above
is the program's only invocation and carries neither ``--strict`` nor
``--json``. The advisory slot reads ONLY the exit code — rc 0 records
``ADVISORY: ok:`` and DISCARDS the program's stdout entirely; rc 1
records ``ADVISORY: FINDING: <cmd> :: <output>``; rc 2 records
``ADVISORY: n/a (input not present)``. So of the three outcomes that slot
can record, this gate could only ever produce the first. A project whose
L7 named a dozen debug pins that exist in no pin table was recorded
``GATE_RAN l7_debug_access_grounding_check rc=0 PASS``, identical to one
that was examined and found correct, and the ``ADVISE — N finding(s)``
line the program printed reached nothing. The ``FAIL`` verdict it
printed under ``--strict``, and the ``blocks: true`` it wrote, were
reachable only from its own unit test.

WHY THE FIX IS THE DEFAULT AND NOT THE CALL SITE. Suppressing the exit
code never prevented blocking — the slot does that — it prevented
REPORTING. Adding ``--strict`` to the one flow line would have fixed one
call site and left the program lying to every other caller and to anyone
running it by hand. So the exit code is now always the verdict, which is
also what every peer per-layer gate in the same advisory slot already
did (``l16_``, ``l17_``, ``l21_macro_supply_rail_declared``,
``l8_sta_clock_period_design_owned``, ``l9_floorplan_contract``,
``l8_clock_period_actionability`` all return 1 on findings by default).
This gate was the odd one out.

The findings stay WARN and their consequence still lives in L1/L9, which
have their own blocking gates (``l9_rtl_pin_consistency_check`` is the
one that actually diffs the port set against the RTL top). Nothing here
makes a run red: the advisory slot cannot fail a step.

TWO FURTHER VERDICT CHANNELS THAT WERE ALSO DEAD
================================================
* The genuine skip branches (no L7 document, unparseable L7, waiver)
  wrote ``skipped_reason``, printed ``skipped:`` and returned 0 — the
  ``structured-skip-not-read-back`` shape ``_vacuous_exit`` exists for.
  A project with NO L7 at all was credited the same green as one that
  was examined. They now route through ``_vacuous_exit.exit_code`` to
  rc 2, so the slot records ``n/a`` instead of ``ok``.
* "L7 names access points but no pin-bearing layer declares anything"
  used to set the SAME ``skipped_reason``, and ``main`` returned 0 on it
  BEFORE printing any finding — so a project in that state could not
  report an ungrounded debug register or a non-enterable test mode
  either, even though both rules had already run and both had put their
  findings in the report. That state is now recorded as a per-rule
  ``rules_not_applicable`` note; it no longer speaks for the program.

SWEEP / FALSE POSITIVES
=======================
Swept over every ``phase1/generated_docs`` tree reachable on the fleet.
Zero false positives. The negative-control smoke test proves every
direction on synthesized neutral fixtures (no real design's files are
copied), and drives the real flow-engine advisory clause so that
"reachable" is asserted where the verdict is actually read.

Usage:
    python3 l7_debug_access_grounding_check.py <project_dir> \
        [--json report.json]

Exit codes: 0 PASS (examined the design, every claim grounded)
            | 1 findings (recorded; the advisory slot does not block)
            | 2 examined nothing (no/unparseable L7, or waived)
            | 2 project not found
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _vacuous_exit as _vx  # noqa: E402  (needs the sys.path insert above)

WAIVER_ID = "l7_debug_access_grounding_override"
WAIVER_MIN_CHARS = 40

# Where L7 states a test/debug ACCESS POINT. (array_key, field_keys)
_ACCESS_POINT_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("debug_observability", ("signals", "pins", "ports")),
    ("test_modes", ("pins", "signals", "entry_pins", "ports")),
    ("formal_interfaces", ("signals", "pins", "ports")),
    ("test_scenarios", ("pins", "signals")),
    ("debug_access", ("signals", "pins", "ports")),
    ("tap_pins", ()),
    ("jtag_pins", ()),
)

_BUS_SUFFIX_RE = re.compile(r"\s*\[[^\]]*\]\s*$")

# Keys that explicitly state how a test mode is entered.
_TEST_MODE_ENTRY_KEYS: tuple[str, ...] = (
    "pins", "signals", "entry_pins", "ports", "entry_sequence", "sequence",
    "entry", "unlock_sequence", "entry_condition", "trigger", "triggers",
    "activation", "enable", "select", "condition", "entry_bit", "opcode",
    "command", "register", "reg",
)

# A test mode whose own prose names the register / bit / assignment that
# enters it IS enterable, even without a dedicated entry key.
_ENTRY_IN_PROSE_RE = re.compile(
    r"(\[[^\]]*\])|(=)|(\bbits?\b)|(\breg(?:ister)?\b)|(0x[0-9a-fA-F]+)",
    re.IGNORECASE)


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    where: str = ""

    def as_dict(self) -> dict:
        return {"severity": self.severity, "rule": self.rule,
                "message": self.message, "where": self.where}


def _read_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _generated_docs_dir(project: Path) -> Path:
    return project / "phase1" / "generated_docs"


def _layer(project: Path, stem: str) -> dict:
    gd = _generated_docs_dir(project)
    exact = gd / f"{stem}.json"
    if exact.is_file():
        return _read_json(exact)
    prefix = stem.split("_", 1)[0]
    for cand in sorted(gd.glob(f"{prefix}_*.json")):
        doc = _read_json(cand)
        if doc:
            return doc
    return {}


def _norm(name: str) -> str:
    """Case-insensitive, bus-subscript tolerant identifier key."""
    return _BUS_SUFFIX_RE.sub("", str(name).strip()).strip().lower()


def _names_from(arr: Any, keys: tuple[str, ...] = ("name",)) -> set[str]:
    out: set[str] = set()
    if not isinstance(arr, list):
        return out
    for e in arr:
        if isinstance(e, str) and e.strip():
            out.add(_norm(e))
        elif isinstance(e, dict):
            for k in keys:
                v = e.get(k)
                if isinstance(v, str) and v.strip():
                    out.add(_norm(v))
    return out


def _pin_namespace(project: Path) -> tuple[set[str], dict]:
    """Every identifier the design's pin-bearing layers actually declare."""
    ns: set[str] = set()
    prov: dict = {}

    l9 = _layer(project, "L9_INTEGRATION_SPEC")
    for key in ("top_module_pins", "top_ports", "ports"):
        got = _names_from(l9.get(key))
        prov[f"L9.{key}"] = len(got)
        ns |= got
    iw = l9.get("internal_wires")
    if isinstance(iw, list):
        got = set()
        for e in iw:
            if isinstance(e, dict):
                for k in ("net", "child_port", "name"):
                    v = e.get(k)
                    if isinstance(v, str) and v.strip():
                        got.add(_norm(v))
        prov["L9.internal_wires"] = len(got)
        ns |= got

    l1 = _layer(project, "L1_DATASHEET")
    got = _names_from(l1.get("pin_table"), ("name", "rtl_name", "board_name"))
    prov["L1.pin_table"] = len(got)
    ns |= got
    for e in (l1.get("pin_table") or []):
        if isinstance(e, dict):
            for a in (e.get("aliases") or []):
                if isinstance(a, str) and a.strip():
                    ns.add(_norm(a))

    l17 = _layer(project, "L17_CHANNEL_SIGNAL_CATALOG")
    fields = l17.get("fields") if isinstance(l17.get("fields"), dict) else l17
    for key in ("signals", "signal_catalog", "channel_signals", "catalog"):
        got = _names_from(fields.get(key) if isinstance(fields, dict) else None)
        if got:
            prov[f"L17.{key}"] = len(got)
            ns |= got

    return ns, prov


def _register_namespace(project: Path) -> tuple[set[str], dict]:
    ns: set[str] = set()
    prov: dict = {}
    l4 = _layer(project, "L4_REGMAP")
    for key in ("registers", "regmap", "register_map", "fields", "entries"):
        v = l4.get(key)
        got = _names_from(v, ("name", "reg_name", "register"))
        if got:
            prov[f"L4.{key}"] = len(got)
            ns |= got
    l9 = _layer(project, "L9_INTEGRATION_SPEC")
    got = _names_from(l9.get("registers"))
    if got:
        prov["L9.registers"] = len(got)
        ns |= got
    return ns, prov


def _access_points(l7: dict) -> list[tuple[str, str]]:
    """[(signal_name, where)] for every test/debug access point L7 names."""
    out: list[tuple[str, str]] = []
    for arr_key, field_keys in _ACCESS_POINT_SOURCES:
        arr = l7.get(arr_key)
        if not isinstance(arr, list):
            continue
        for i, e in enumerate(arr):
            if isinstance(e, str) and e.strip():
                out.append((e.strip(), f"L7.{arr_key}[{i}]"))
                continue
            if not isinstance(e, dict):
                continue
            for fk in field_keys:
                v = e.get(fk)
                if isinstance(v, str) and v.strip():
                    out.append((v.strip(), f"L7.{arr_key}[{i}].{fk}"))
                elif isinstance(v, list):
                    for s in v:
                        if isinstance(s, str) and s.strip():
                            out.append((s.strip(), f"L7.{arr_key}[{i}].{fk}"))
    return out


def _waiver_rationale(project: Path, waiver_id: str) -> str:
    cands = [project / "waivers.json"] + sorted(project.glob("**/waivers.json"))
    for cand in cands:
        if not cand.is_file():
            continue
        try:
            data = json.loads(cand.read_text(encoding="utf-8",
                                             errors="replace") or "{}")
        except (OSError, json.JSONDecodeError):
            continue
        entries: Any = data if isinstance(data, list) else (
            data.get("waivers") or data.get("waived_steps") or [])
        if not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, dict) and e.get("id") == waiver_id:
                rat = e.get("rationale") or e.get("reason") or ""
                if isinstance(rat, str) and len(rat.strip()) >= WAIVER_MIN_CHARS:
                    return rat.strip()
    return ""


def _mark_vacuous(summary: dict, token: str, sentence: str) -> None:
    """Record that the gate examined NOTHING, in the shape `_vacuous_exit`
    reads back. `token` is the machine-readable reason; `sentence` is the
    human one. Only the three genuine early returns may call this — a rule
    that could not judge is `rules_not_applicable`, not this."""
    summary["skipped"] = True
    summary["reason"] = token
    summary["skipped_reason"] = sentence


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "access_points": 0,
        "pin_namespace_size": 0,
        "pin_namespace_provenance": {},
        "debug_registers": 0,
        "register_namespace_size": 0,
        "test_modes": 0,
        # `skipped` / `reason` are the pair `_vacuous_exit` routes: they mean
        # "this gate examined NOTHING", and only the three early returns below
        # may set them. `skipped_reason` stays as the human sentence.
        "skipped": False,
        "reason": "",
        "skipped_reason": "",
        # A rule that had no namespace to judge against. NOT a program-level
        # skip: the other rules still ran and their findings still count. It
        # used to share `skipped_reason`, which made `main` return before
        # printing them — see the module docstring.
        "rules_not_applicable": [],
        "waiver": "",
        "consumer_note": (
            "L7 has no downstream consumer; this gate cross-checks L7's "
            "claims against the layers that DO implement pins/registers."),
    }

    gd = _generated_docs_dir(project)
    l7_path = gd / "L7_TEST_DEBUG.json"
    if not l7_path.is_file():
        cands = sorted(gd.glob("L7_*.json"))
        if not cands:
            _mark_vacuous(summary, "no-l7-document",
                          "no L7 document in project")
            return findings, summary
        l7_path = cands[0]
    l7 = _read_json(l7_path)
    if not l7:
        _mark_vacuous(summary, "l7-unreadable",
                      f"{l7_path.name} is empty or unparseable")
        return findings, summary

    waiver = _waiver_rationale(project, WAIVER_ID)
    summary["waiver"] = waiver
    if waiver:
        _mark_vacuous(summary, "waived",
                      f"waiver {WAIVER_ID}: {waiver[:80]}")
        return findings, summary

    points = _access_points(l7)
    summary["access_points"] = len(points)

    pin_ns, pin_prov = _pin_namespace(project)
    summary["pin_namespace_size"] = len(pin_ns)
    summary["pin_namespace_provenance"] = {k: v for k, v in pin_prov.items() if v}

    # ── L7_DEBUG_SIGNAL_UNGROUNDED ──
    if points and pin_ns:
        dangling: dict[str, list[str]] = {}
        for name, where in points:
            if _norm(name) not in pin_ns:
                dangling.setdefault(name, []).append(where)
        for name, wheres in sorted(dangling.items()):
            findings.append(Finding(
                severity="WARN",
                rule="L7_DEBUG_SIGNAL_UNGROUNDED",
                message=(
                    f"L7 names '{name}' as a test/debug access point but it "
                    f"resolves in none of the layers that actually implement "
                    f"pins (L9 top ports / L9 internal_wires / L1 pin_table / "
                    f"L17 catalogue; {len(pin_ns)} identifiers, provenance "
                    f"{summary['pin_namespace_provenance']}). Either L1/L9 is "
                    f"missing a port the design needs — a debug pin absent "
                    f"from the pin table never gets a port or a pad — or L7 "
                    f"invented it. L7 itself feeds nothing, so this is "
                    f"reported against L1/L9."),
                where=", ".join(wheres),
            ))
    elif points and not pin_ns:
        # ONE RULE cannot judge. That is not the program examining nothing:
        # the register rule and the test-mode rule below still run, and a
        # finding from either is a real finding. Writing this into
        # `skipped_reason` (as this branch used to) made `main` print
        # `skipped:` and return 0 BEFORE those findings were ever printed.
        summary["rules_not_applicable"].append({
            "rule": "L7_DEBUG_SIGNAL_UNGROUNDED",
            "reason": ("L7 names access points but no pin-bearing layer "
                       "declares any identifier to ground them against — "
                       "nothing to check"),
        })

    # ── L7_DEBUG_REGISTER_UNGROUNDED ──
    dbg_regs = [e for e in (l7.get("debug_registers") or [])
                if isinstance(e, dict) and isinstance(e.get("name"), str)
                and e["name"].strip()]
    summary["debug_registers"] = len(dbg_regs)
    reg_ns, reg_prov = _register_namespace(project)
    summary["register_namespace_size"] = len(reg_ns)
    summary["register_namespace_provenance"] = {
        k: v for k, v in reg_prov.items() if v}
    if dbg_regs and not reg_ns:
        summary["rules_not_applicable"].append({
            "rule": "L7_DEBUG_REGISTER_UNGROUNDED",
            "reason": ("L7 declares debug registers but neither L4 nor L9 "
                       "declares a register namespace to ground them "
                       "against — nothing to check"),
        })
    if dbg_regs and reg_ns:
        for i, e in enumerate(dbg_regs):
            nm = e["name"].strip()
            if _norm(nm) not in reg_ns:
                findings.append(Finding(
                    severity="WARN",
                    rule="L7_DEBUG_REGISTER_UNGROUNDED",
                    message=(
                        f"L7 declares debug register '{nm}' but it resolves in "
                        f"neither the L4 register namespace nor L9.registers "
                        f"({len(reg_ns)} names, provenance "
                        f"{summary['register_namespace_provenance']}). A debug "
                        f"register with no address is not addressable."),
                    where=f"L7.debug_registers[{i}]",
                ))

    # ── L7_TEST_MODE_NOT_ENTERABLE ──
    modes = [e for e in (l7.get("test_modes") or []) if isinstance(e, dict)]
    summary["test_modes"] = len(modes)
    for i, m in enumerate(modes):
        has_entry = False
        for k in _TEST_MODE_ENTRY_KEYS:
            v = m.get(k)
            if isinstance(v, list) and v:
                has_entry = True
            elif isinstance(v, str) and v.strip():
                has_entry = True
        # Sweep-driven narrowing: many real docs state the entry INSIDE the
        # mode's own prose — a register/bit reference ("bit 0.14", "reg 9"),
        # a bus subscript, or an explicit assignment ("CTRL[0]=1"). A mode
        # that carries any of those IS enterable; firing on it would be a
        # false positive. Only a mode that is pure description is flagged.
        if not has_entry:
            blob = " ".join(str(v) for v in m.values()
                            if isinstance(v, (str, int, float)))
            if _ENTRY_IN_PROSE_RE.search(blob):
                has_entry = True
        if not has_entry:
            findings.append(Finding(
                severity="WARN",
                rule="L7_TEST_MODE_NOT_ENTERABLE",
                message=(
                    f"L7 declares test mode "
                    f"'{m.get('name') or m.get('mode') or '<unnamed>'}' with no "
                    f"entry pins, entry signals or entry sequence. A mode "
                    f"nobody can enter cannot be implemented or tested — it is "
                    f"prose, not a requirement."),
                where=f"L7.test_modes[{i}]",
            ))

    return findings, summary


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="l7_debug_access_grounding_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    # DEPRECATED and deliberately a NO-OP, not deleted. It used to be the only
    # way to reach exit 1, and no caller passed it, which is the defect this
    # program was fixed for; the exit code is now always the verdict. It stays
    # ACCEPTED because removing it would make any straggler invocation exit 2
    # from argparse, and in the advisory slot rc 2 reads as
    # "n/a (input not present)" — the removal would fail silently.
    ap.add_argument("--strict", action="store_true",
                    help="DEPRECATED, no effect: the exit code always "
                         "reflects the verdict (0 clean / 1 findings / "
                         "2 examined nothing). Enforcement is decided by the "
                         "flow SLOT this gate is wired into, not here.")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2
    if args.strict:
        print("[note] --strict is deprecated and has no effect: this gate's "
              "exit code already reports findings as rc 1.", file=sys.stderr)

    findings, summary = inspect(project)
    passed = not findings
    skipped = _vx.summary_is_skipped(summary)
    rc = _vx.exit_code(passed, skipped)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "program": "l7_debug_access_grounding_check",
            # The three-way conclusion, and the exit code it produced, from
            # the SAME (passed, skipped) pair the printed verdict uses — so a
            # reader of the report and a reader of the rc cannot disagree.
            "passed": passed,
            "skipped": skipped,
            "exit_code": rc,
            "verdict": ("FINDINGS" if not passed
                        else "VACUOUS" if skipped else "PASS"),
            "summary": summary,
            "findings": [f.as_dict() for f in findings],
        }, indent=2), encoding="utf-8")

    print(f"=== l7_debug_access_grounding_check ({project.name}) ===")
    # A rule that could not judge is DISCLOSED and does not silence the rest.
    for na in summary.get("rules_not_applicable") or []:
        print(f"[n/a] {na['rule']}: {na['reason']}")
    if skipped:
        # Nothing was examined. rc 2 puts it in the VACUOUS tier instead of
        # letting it be credited as a pass over a design nobody read.
        print(_vx.verdict_line("l7_debug_access_grounding_check",
                               passed, skipped,
                               _vx.skip_reason(summary)))
        _vx.announce_vacuous("l7_debug_access_grounding_check",
                             _vx.skip_reason(summary))
        return rc
    print(f"access points: {summary['access_points']}  "
          f"pin namespace: {summary['pin_namespace_size']} "
          f"{summary['pin_namespace_provenance']}")
    print(f"debug registers: {summary['debug_registers']}  "
          f"register namespace: {summary['register_namespace_size']}")
    for f in findings:
        print(f"[{f.severity}] {f.rule}: {f.message}")
    if passed:
        print("PASS — every test/debug access point L7 claims is grounded in "
              "a layer that actually implements it")
        return rc
    # WHICH RULES fired goes on its OWN line, and a fixed-width sentence
    # follows it. The advisory slot records `output_snippet(...)[:200]`, and
    # `output_snippet` keeps the LAST 300 characters — so what survives is the
    # window 300..100 characters from the end. A verdict line written last
    # falls OUTSIDE it and the record names no rule at all (measured). The
    # trailing sentence below is the spacer that puts the tally inside the
    # window. Same technique `flow_compliance_check` uses to keep its crash
    # hint ahead of the same cut.
    tally: dict[str, int] = {}
    for f in findings:
        tally[f.rule] = tally.get(f.rule, 0) + 1
    rules = " ".join(f"{r} x{n}" for r, n in sorted(tally.items()))
    print(f"FINDINGS — {rules} ({len(findings)} finding(s), exit {rc})")
    print("recorded by the flow's ADVISORY slot: this verdict is RECORDED and "
          "does NOT fail the step; the repair lives in L1/L9, which have "
          "their own blocking gates.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
