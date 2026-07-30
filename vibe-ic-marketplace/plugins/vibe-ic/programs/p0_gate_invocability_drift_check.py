#!/usr/bin/env python3
"""A gate registered in the P0 umbrella that the umbrella cannot invoke.

WHY THIS EXISTS
===============
`_STRUCTURAL_RTL_GATES` registers 243 checkers. 33 of them reject the argv the
umbrella builds — argparse exits 2 before the check runs — so they return no
verdict at all. `_gate_invocation` records that faithfully as `NOT_INVOCABLE`,
and its docstring is emphatic that this is a VERDICT and not a marker, because
folding it into `SKIP` is what made 39 registered gates read as benign in #492.

Then `_p0_buckets_from_records` folds it into `SKIP` anyway:

    elif v in ("SKIP", "NOT_INVOCABLE"):
        skips.append(_p0_skip_entry(r))

and `_run_structural_rtl_gates` returns `(len(fails) == 0)` as the umbrella's
pass flag. So the separation exists in the reporting and is lost in the verdict:
a project where 33 registered checkers produced nothing still gets
`status = "PASS"` from P0 (vibe-ic#559).

THIS PROGRAM DOES NOT FIX THAT. Making `NOT_INVOCABLE` fail today would turn P0
red everywhere and a gate that blocks every landing gets deleted, not fixed. It
stops the number GROWING while the 33 are triaged, which is the part that can be
done without a judgement call about any individual gate.

WHY A SUBSET AND NOT A COUNT
============================
The predicate is `measured ⊆ recorded`, deliberately:

* a **count** ratchet lets a newly-silent gate hide behind a fixed one — the
  total is unchanged and the check passes;
* an allow-list that only ever GROWS is the register shape that outlives its own
  truth: it suppresses by name, so it keeps suppressing after the name stops
  describing anything.

Subset gives the useful asymmetry. Fixing a gate leaves the set a subset and
passes. Registering a 34th un-invocable gate does not, and fails.

REMOVAL CONDITION, stated so it is observable rather than intended: as the 33 are
triaged — classified into `_ZERO_DENOMINATOR_CLASSIFICATION` with a re-derived
#492 measurement, wired, or de-registered — `KNOWN_NOT_INVOCABLE` shrinks. When it
reaches zero this file is `git rm`-ed and `NOT_INVOCABLE` is made to enter the
umbrella's pass flag. Emptying it instead of deleting it would leave a place to
put the next one without thinking.

THE DISCRIMINATOR, and why the obvious one is wrong
===================================================
"argparse rejected the argv" is `rc == 2` AND `usage:` on stderr.

`rc == 2` alone is not it, measured: 181 of 243 gates exit 2 against a throwaway
project directory, because most of them use exit 2 for their own "input not
found". Only argparse prints its `usage:` line on rejection; a gate's hand-written
error never does. Filtering on the error WORDING is also wrong — it only finds
the phrasings you thought of.

Exit: 0 subset holds, 1 a new un-invocable gate appeared, 2 could not measure.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Set, Tuple

RC_OK, RC_DRIFT, RC_CANNOT_MEASURE = 0, 1, 2

#: Per-gate wall clock. A gate that TIMES OUT accepted the argv and reached real
#: work, so it is not a rejection — the timeout is a measurement floor, not a
#: verdict.
GATE_TIMEOUT_S = 25

#: The 33 measured on 2026-07-30 at v1.8.58. Of these, exactly 8 carry a recorded
#: decision in `_ZERO_DENOMINATOR_CLASSIFICATION`; four more are decided in the
#: prose above `_STRUCTURAL_GATE_ARGV_ADAPTERS` (`testbench_exists_check` would
#: redden the corpus 102/107) and are invisible to any program because that
#: decision was written as a comment. The rest have no record of anyone having
#: decided. This list does not endorse any of them — it pins the size of the
#: problem so it cannot grow silently.
KNOWN_NOT_INVOCABLE: Tuple[str, ...] = (
    "backlog_sanitize_check",
    "bit_count_modulo_check",
    "cmd_arg_range_validation_check",
    "crc_bitorder_check",
    "crc_seed_consistency_check",
    "cross_constant_invariant_check",
    "fpga_qsf_lint",
    "fpga_wrapper_input_polluter_check",
    "fresh_agent_provenance_check",
    "interface_encoding_audit",
    "json_schema_check",
    "l12_sequence_implementation_check",
    "l9_completeness_check",
    "module_port_audit",
    "oe_pattern_check",
    "openroad_tcl_deprecation_check",
    "otp_write_lock_gate_check",
    "output_artifact_check",
    "packet_length_check_present",
    "phase1_gate_contract_check",
    "practical_notes_specificity_check",
    "pre_awake_silence_check",
    "protocol_gap_check",
    "pulse_decoder_edge_check",
    "response_payload_template_check",
    "rtl_precheck_gate",
    "scope_periodic_pulse_check",
    "testbench_exists_check",
    "tester_oracle_health_check",
    "transient_signal_latch_check",
    "tristate_bus_check",
    "tristate_self_rx_mask_check",
    "warn_acceptance_policy_check",
)


def _rejects_the_umbrella_argv(argv: List[str]) -> bool:
    """True when argparse refused this argv, as opposed to the gate refusing its
    input. See the module docstring for why both halves are load-bearing."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=GATE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False          # got past parsing into real work
    except (OSError, subprocess.SubprocessError):
        return False          # a launch failure is not a parse verdict
    return r.returncode == 2 and "usage:" in (r.stderr or "")


def measure(jobs: int = 8) -> Dict[str, object]:
    """The set of registered gates that reject the umbrella's own argv.

    The argv comes from `flow_compliance_check._structural_gate_argv`, never from
    a re-typed literal: a re-typed argv agrees with the umbrella by coincidence,
    which is the reason that function was named in the first place (#492).
    """
    programs = Path(__file__).resolve().parent
    if str(programs) not in sys.path:
        sys.path.insert(0, str(programs))
    try:
        import flow_compliance_check as F
    except Exception as exc:                                   # noqa: BLE001
        return {"error": f"cannot import flow_compliance_check: {exc}"}

    gates = tuple(getattr(F, "_STRUCTURAL_RTL_GATES", ()))
    if not gates:
        return {"error": "_STRUCTURAL_RTL_GATES is empty or absent; the "
                         "measurement would report a vacuous zero"}

    with tempfile.TemporaryDirectory() as tmp:
        # A directory that exists but holds nothing. It must EXIST so a gate's own
        # "not a directory" path is not what we measure, and be EMPTY so no gate
        # does real work.
        probe = Path(tmp)
        try:
            argvs = {g: F._structural_gate_argv(g, probe, rtl_dir=probe)
                     for g in gates}
        except Exception as exc:                               # noqa: BLE001
            return {"error": f"argv builder raised: {exc}"}
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            verdicts = list(ex.map(_rejects_the_umbrella_argv,
                                   (argvs[g] for g in gates)))

    measured = {g for g, rejected in zip(gates, verdicts) if rejected}
    return {"registered": len(gates), "measured": sorted(measured)}


def check(jobs: int = 8) -> Dict[str, object]:
    res = measure(jobs=jobs)
    if "error" in res:
        return res
    measured: Set[str] = set(res["measured"])          # type: ignore[arg-type]
    recorded: Set[str] = set(KNOWN_NOT_INVOCABLE)
    return {
        **res,
        "recorded": sorted(recorded),
        "new": sorted(measured - recorded),
        "now_invocable": sorted(recorded - measured),
    }


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args(argv)

    try:
        res = check(jobs=a.jobs)
    except Exception as exc:                                   # noqa: BLE001
        # A crash is not a finding. rc 1 means "a new un-invocable gate exists";
        # letting an exception reach the caller would publish that claim from a
        # program that measured nothing.
        print(f"[NOT MEASURED] {type(exc).__name__}: {exc}", file=sys.stderr)
        return RC_CANNOT_MEASURE

    if a.json_out:
        p = Path(a.json_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"program": "p0_gate_invocability_drift_check",
                                 **res}, indent=2) + "\n", encoding="utf-8")

    if "error" in res:
        print(f"[NOT MEASURED] {res['error']}", file=sys.stderr)
        return RC_CANNOT_MEASURE

    new = res["new"]
    freed = res["now_invocable"]
    if freed:
        print(f"[INFO] {len(freed)} recorded gate(s) now accept the umbrella's "
              f"argv — remove them from KNOWN_NOT_INVOCABLE: "
              f"{', '.join(freed)}", file=sys.stderr)
    if new:
        print(f"[FAIL] {len(new)} gate(s) registered in the P0 umbrella reject "
              f"its argv and are NOT in KNOWN_NOT_INVOCABLE: {', '.join(new)}. "
              f"They return no verdict, and P0 still reports PASS (vibe-ic#559), "
              f"so what they audit is UNAUDITED. Wire the gate, de-register it, "
              f"or record the #492 measurement that licenses its silence.",
              file=sys.stderr)
        return RC_DRIFT
    print(f"[PASS] {len(res['measured'])} of {res['registered']} registered P0 "
          f"gates reject the umbrella's argv; all are recorded. No new silent "
          f"gate.", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
