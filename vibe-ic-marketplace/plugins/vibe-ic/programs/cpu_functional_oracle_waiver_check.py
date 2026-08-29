#!/usr/bin/env python3
"""cpu_functional_oracle_waiver_check.py — Step 4 connectivity-PASS /
functional-DEFERRED capability-gap gate (ORGANIC #654).

The audited residual: for the no-oracle CPU/SoC verification track
(verification_track=generic_full_stack — processor/SoC classes with no
command/opcode oracle and no L10 golden vectors), the AID reference TB is
WAIVED (it cannot bind a data/memory-bus top) and the only available TB is a
CONNECTIVITY-ONLY full-stack skeleton. The oracle-sim bridge that writes the
canonical phase2/stage1/sim/{results.xml,pass.flag} fires ONLY when a
functional oracle ran with vectors_passed == vectors_total > 0 — which this
class can never satisfy — so the canonical sim/ dir stayed EMPTY and Step 4's
gate ('phase2/stage1/sim/results.xml OR pass.flag') hard-FAILed by
construction for EVERY such IC, independent of RTL quality. Functional
verification was structurally unreachable, halting the whole chain at the
first mid-chain FAIL.

Fix (class-driven, NOT chip-specific): the runner now emits a CONNECTIVITY
bridge to the canonical sim/ path (verdict CONNECTIVITY_PASS,
functional_verified=false, capability_gap cap:cpu_functional_oracle, evidence
backlink to the full_stack.log transcript). This gate verifies that bridge is
a HONEST connectivity-PASS waiver — not a forged functional PASS — and signals
PASS_WITH_WAIVERS so flow_compliance_check promotes Step 4 to WAIVED-DEFERRED
(Overall PASS_WITH_WAIVERS) instead of either a bare PASS or an opaque
missing-file FAIL.

Verdicts / exit codes (chip-AGNOSTIC — structural artifacts only):
  0 = N/A for this gate: sim/results.xml is a genuine functional PASS (an
      oracle / non-connectivity verdict). This gate makes no claim about it;
      the existing functional gates own it.  (Also 0 when no connectivity
      marker is present at all and the verdict is a plain functional PASS.)
  2 = VACUOUS: no sim/results.xml at all — nothing for this gate to assess
      (the absence is the standard missing-file FAIL the files_exist gate
      reports; this gate stays out of the way).
  3 = PASS_WITH_WAIVERS: sim/results.xml is the connectivity-PASS /
      functional-DEFERRED capability-gap bridge with a dereferenceable
      evidence pointer — prints the PASS_WITH_WAIVERS sentinel so the step
      is promoted to WAIVED-DEFERRED.
  1 = FAIL: the bridge claims a connectivity-PASS waiver but the evidence is
      not substantiated (missing/empty transcript, or functional_verified is
      asserted true while claiming the capability gap) — a forged waiver is
      not honoured.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402
import _sim_results_bridge as _srb  # noqa: E402

# The capability-gap token the runner stamps on a connectivity-PASS waiver.
# A chip-AGNOSTIC capability identifier, NOT a chip/vendor/SKU literal.
CAP_CPU_FUNCTIONAL_ORACLE = "cap:cpu_functional_oracle"
CONNECTIVITY_VERDICT = "CONNECTIVITY_PASS"


def _read_xml_field(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.IGNORECASE | re.DOTALL)
    return (m.group(1).strip() if m else "")


def _waiver_track_class_label(xml: str) -> str:
    """ORGANIC #779 — derive the human-readable '<track> no-oracle <ic_class>
    class' label from the STRUCTURED results.xml, instead of the hardcoded
    'generic_full_stack no-oracle CPU/SoC class' literal that MISLABELS non-CPU
    classes. After #745 made arith_oracle_tb_gen DEFER for serial-parallel
    multipliers, `digital_arithmetic_primitive` ICs route into this same #654
    gate — and the hardcoded 'CPU/SoC' string then mis-described them, even
    though every structured field (verdict / capability_gap /
    functional_verified / waiver_reason) was already correct. Pure
    message-accuracy: the verdict logic and exit code are unchanged.

    The connectivity bridge writes <verification_track> directly (e.g.
    'generic_full_stack') and embeds the real ic_class in <waiver_reason> as a
    `class '<name>'` token (from _class_uses_aid_reference_tb). Reads a dedicated
    <ic_class> tag first if a future schema adds one; falls back to a generic
    label when a field is absent (older artifact). chip-AGNOSTIC — reads the
    class from structured output, never a chip/vendor/SKU literal."""
    track = _read_xml_field(xml, "verification_track") or "generic_full_stack"
    ic_class = _read_xml_field(xml, "ic_class")
    if not ic_class:
        m = re.search(r"\bclass\s+'([A-Za-z0-9_]+)'",
                      _read_xml_field(xml, "waiver_reason"))
        ic_class = m.group(1) if m else ""
    if ic_class:
        return f"{track} no-oracle {ic_class} class"
    return f"{track} no-oracle class"


def _evaluate(project: Path) -> "tuple[int, str]":
    """Return (exit_code, message)."""
    sim_dir = _pl.sim_dir(project)
    results = sim_dir / "results.xml"
    if not results.is_file():
        return 2, ("VACUOUS_PASS: no phase2/stage1/sim/results.xml — "
                   "cpu_functional_oracle_waiver_check has nothing to assess.")
    try:
        xml = results.read_text(errors="replace")
    except OSError as exc:
        return 1, f"FAIL: could not read sim/results.xml: {exc}"

    verdict = _read_xml_field(xml, "verdict").upper().replace("_", "-")
    cap = _read_xml_field(xml, "capability_gap")
    func_verified = _read_xml_field(xml, "functional_verified").lower()

    is_connectivity = (
        verdict == CONNECTIVITY_VERDICT.replace("_", "-")
        or cap == CAP_CPU_FUNCTIONAL_ORACLE)
    if not is_connectivity:
        # A genuine functional PASS (oracle bridge) or any non-connectivity
        # verdict — not this gate's concern. The functional gates own it.
        return 0, ("PASS: sim/results.xml is not a cpu-functional-oracle "
                   "connectivity waiver (functional verdict owned by the "
                   "functional gates); cpu_functional_oracle_waiver_check N/A.")

    # It claims the connectivity-PASS capability-gap waiver. Substantiate it:
    #   (1) the capability-gap marker must be the cpu-functional-oracle one,
    #   (2) functional_verified must NOT be asserted true (a connectivity
    #       waiver that ALSO claims functional verification is a forgery),
    #   (3) the <evidence> pointer must dereference to a non-empty transcript
    #       that actually reached FULL_STACK_TB_DONE.
    if cap != CAP_CPU_FUNCTIONAL_ORACLE:
        return 1, (f"FAIL: connectivity verdict but capability_gap is "
                   f"{cap!r}, not {CAP_CPU_FUNCTIONAL_ORACLE!r} — "
                   f"unrecognised waiver class.")
    if func_verified == "true":
        return 1, ("FAIL: connectivity-PASS waiver also asserts "
                   "functional_verified=true — a connectivity waiver MUST "
                   "NOT claim functional verification (forged waiver).")
    evidence = _read_xml_field(xml, "evidence")
    if not evidence:
        return 1, ("FAIL: connectivity-PASS waiver carries no <evidence> "
                   "pointer — an unreviewable waiver is not honoured.")
    ev_path = (project / evidence)
    if not ev_path.is_file() or ev_path.stat().st_size == 0:
        return 1, (f"FAIL: connectivity-PASS waiver <evidence> pointer "
                   f"{evidence!r} does not dereference to a non-empty "
                   f"transcript — waiver evidence broken.")
    try:
        ev_txt = ev_path.read_text(errors="replace")
    except OSError as exc:
        return 1, f"FAIL: could not read evidence transcript: {exc}"
    if "FULL_STACK_TB_DONE" not in ev_txt:
        return 1, ("FAIL: connectivity-PASS waiver evidence transcript did "
                   "not reach FULL_STACK_TB_DONE — connectivity binding to "
                   "rtl/ was NOT actually demonstrated.")

    # 2026-07-13 — real-functional-PASS SUPERSEDES the connectivity DEFERRAL.
    # The connectivity bridge above is an HONEST waiver: it says functional
    # verification was DEFERRED because the AID reference TB cannot bind this
    # interface family. But for a class whose oracle IS derivable, the NEW TB
    # path (professional_tb_gen) may have ALREADY closed functional
    # verification — a real cocotb streaming-scoreboard against the real rtl/
    # with failures=0 (phase2/stage1/sim_professional/<top>/results.xml). When
    # that real PASS is present, functional verification was ACHIEVED, not
    # deferred: step aside (rc=0) so Step 4 is credited as a genuine functional
    # PASS instead of WAIVED-DEFERRED. chip-AGNOSTIC (keys on the JUnit result
    # structure, not any chip name) and anti-fabrication-safe (a missing /
    # failing / vacuous professional result returns None → the honest waiver
    # below is issued exactly as before).
    pro = _srb.find_professional_tb_pass(project)
    if pro:
        return 0, (
            "PASS: functional verification ACHIEVED by the professional cocotb "
            f"testbench (professional_tb_gen) — {pro['rel_path']}: tests="
            f"{pro['tests']} passed={pro['passed']} failures={pro['failures']} "
            f"errors={pro['errors']}. The connectivity-PASS / functional-"
            f"DEFERRED capability-gap waiver ({CAP_CPU_FUNCTIONAL_ORACLE}) is "
            "SUPERSEDED by this real functional PASS; Step 4 is a genuine "
            "functional simulation PASS, not WAIVED-DEFERRED.")

    return 3, (
        f"PASS_WITH_WAIVERS: {_waiver_track_class_label(xml)} — "
        "connectivity-PASS / functional-DEFERRED capability-gap waiver "
        f"({CAP_CPU_FUNCTIONAL_ORACLE}). The connectivity full-stack TB "
        "compiled + ran to FULL_STACK_TB_DONE against the real rtl/ "
        f"(evidence: {evidence}); functional verification is DEFERRED to a "
        "per-IC oracle TB (skill testbench-gen). Step 4 WAIVED-DEFERRED, "
        "not a missing-file FAIL.")


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Step-4 connectivity-PASS / functional-DEFERRED "
                    "capability-gap waiver gate (ORGANIC #654).")
    ap.add_argument("project", nargs="?", default=".",
                    help="project root (default: .)")
    ap.add_argument("--json", default=None,
                    help="optional path to write the JSON verdict report")
    ns = ap.parse_args(argv)
    project = Path(ns.project).resolve()

    code, msg = _evaluate(project)
    print(msg)
    if ns.json:
        verdict = {0: "PASS", 1: "FAIL", 2: "VACUOUS_PASS",
                   3: "PASS_WITH_WAIVERS"}.get(code, "FAIL")
        out = {"verdict": verdict, "exit_code": code, "message": msg,
               "capability_gap": CAP_CPU_FUNCTIONAL_ORACLE,
               "gate": "cpu_functional_oracle_waiver_check"}
        try:
            jp = Path(ns.json)
            jp.parent.mkdir(parents=True, exist_ok=True)
            jp.write_text(json.dumps(out, indent=2))
        except OSError:
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
