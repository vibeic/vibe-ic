#!/usr/bin/env python3
"""Fail-closed guard against a P0 gate the umbrella cannot invoke.

WHY THIS EXISTS
===============
At the #1968 base, `_STRUCTURAL_RTL_GATES` registered 246 checkers. 36 of them
rejected the argv the umbrella builds — argument parsing exits 2 before the
check runs — so they
return no verdict at all. `_gate_invocation` records that faithfully as
`NOT_INVOCABLE`, and its docstring is emphatic that this is a VERDICT and not a
marker, because folding it into `SKIP` is what made 39 registered gates read as
benign in #492.

Then `_p0_buckets_from_records` folds it into `SKIP` anyway:

    elif v in ("SKIP", "NOT_INVOCABLE"):
        skips.append(_p0_skip_entry(r))

and `_run_structural_rtl_gates` returns `(len(fails) == 0)` as the umbrella's
pass flag. So the separation exists in the reporting and is lost in the verdict:
a project where 36 registered checkers produced nothing still gets
`status = "PASS"` from P0 (vibe-ic#559). P0's true coverage is 210 of 246.

Issue #1968 fixes that with per-gate invocation contracts and explicit
declaration-derived N/A records. This program now holds the repaired frontier
at zero: any future parser rejection is a new blocking silence.

WHY A SUBSET AND NOT A COUNT
============================
The predicate is `measured ⊆ recorded`, deliberately:

* a **count** ratchet lets a newly-silent gate hide behind a fixed one — the
  total is unchanged and the check passes;
* an allow-list that only ever GROWS is the register shape that outlives its own
  truth: it suppresses by name, so it keeps suppressing after the name stops
  describing anything.

Subset gives the useful asymmetry. Fixing a gate leaves the set a subset and
passes. Registering a 37th un-invocable gate does not, and fails.

CURRENT INVARIANT: `KNOWN_NOT_INVOCABLE` is empty. It stays explicit rather
than becoming an undocumented count so a future parser rejection cannot trade
places with a repaired gate or be accepted by accident.

THE DISCRIMINATOR, and why the obvious one is wrong
===================================================
"the umbrella's argv was rejected" is NOT `rc == 2` alone, measured: 181 of 243
gates exit 2 against a throwaway project directory, because most of them use
exit 2 for their own "input not found". Filtering on the error WORDING is also
wrong — it only finds the phrasings you thought of.

THIS FILE USED TO RE-TYPE THE PREDICATE, AND THE RE-TYPED ONE WAS NARROWER.
Until vibe-ic#559 (round 7) the line here read

    return r.returncode == 2 and "usage:" in (r.stderr or "")

which is `_gate_invocation`'s RULE A and only Rule A. The umbrella itself has
always used `_gate_invocation.classify_not_invocable`, which is Rule A **plus**
RULE B: a gate that hand-rolls its own required-argument check prints an
``error:`` line NAMING a long option the caller never supplied, and argparse
never runs, so no `usage:` block is ever printed. `_gate_invocation`'s own
docstring names the four gates that only Rule B catches.

Measured at v1.9.74 over the 246 registered gates, both arms driven from
`_structural_gate_argv` against the same empty probe directory:

    the umbrella (Rule A + Rule B)   36 NOT_INVOCABLE
    this file    (Rule A only)       32

The gap was not four stale names — it was a whole RULE. The consequence is the
one this ratchet exists to prevent: a NEW gate that hand-rolls its
required-argument check goes permanently silent under P0 and this check still
prints `[PASS] ... No new silent gate`. A ratchet blind to half the mechanism it
ratchets is the "silence reads as benign" defect at one remove.

The fix is the #492 fix applied to the predicate instead of to the argv: the
argv already comes from the umbrella's own builder rather than a re-typed
literal (`_structural_gate_argv`), and the classification now comes from the
umbrella's own classifier rather than a re-typed literal
(`_gate_invocation.classify_not_invocable`), called with the same
``supplied_flags`` the umbrella passes. One predicate, one owner.

Exit: 0 subset holds, 1 a new un-invocable gate appeared, 2 could not measure.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gate_invocation                                        # noqa: E402

RC_OK, RC_DRIFT, RC_CANNOT_MEASURE = 0, 1, 2

#: Per-gate wall clock. A gate that TIMES OUT accepted the argv and reached real
#: work, so it is not a rejection — the timeout is a measurement floor, not a
#: verdict.
GATE_TIMEOUT_S = 25

#: What `_required_flags` returns when argparse named no flag (a rejected
#: positional, an unrecognised argument). Its own token so it can be a member
#: of UMBRELLA_SUPPLIABLE rather than a special case at every use.
POSITIONAL_MARKER = "<positional/unrecognized>"

#: Measured 33 on 2026-07-30 at v1.8.58; 32 after #559 converted
#: `fpga_wrapper_input_polluter_check` (v1.8.82); **36 at v1.9.74**, once the
#: discriminator stopped re-typing Rule A and started calling the umbrella's own
#: classifier. The four that appear here for the first time —
#: `fpga_async_input_synchronizer_check`, `mask_application_check`,
#: `payload_bit_position_check`, `periodic_signal_required_check` — are not new
#: silences. They have rejected the umbrella's argv since #492 measured them
#: (they are the four `_gate_invocation`'s docstring names as Rule-B-only), and
#: this file could not see any of them. A name is DELETED here rather than kept
#: with a note: the predicate is `measured ⊆ recorded`, so a fixed gate left in
#: the list would let a newly-silent one take its place without changing the
#: total. This list does not endorse any of them — it pins the size of the
#: problem so it cannot grow silently, and it was pinning the WRONG SIZE.
# Issue #1968 closed the measured 36 with declared invocation contracts plus
# declaration-derived N/A records.  Keep the empty pin as a fail-closed drift
# guard: any future parser rejection is immediately a new, blocking silence.
KNOWN_NOT_INVOCABLE: Tuple[str, ...] = ()


def _why_rejected(argv: List[str]) -> Optional[str]:
    """The umbrella's OWN reason string for this argv, or ``None``.

    Delegates to `_gate_invocation.classify_not_invocable` — the same function
    `flow_compliance_check._eval_gate_worker` calls, with the same
    ``supplied_flags`` derived from the same argv. Re-typing the predicate here
    is what made this ratchet blind to Rule B (see the module docstring): the
    umbrella recorded 36 NOT_INVOCABLE while this file measured 32, and the four
    it could not see were not a stale list but a whole rule.
    """
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=GATE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None           # got past parsing into real work
    except (OSError, subprocess.SubprocessError):
        return None           # a launch failure is not a parse verdict
    if r.returncode != 2:
        # `classify_not_invocable` is documented as valid for rc 2 ONLY — the
        # two meanings of rc 2 are the whole thing it separates. Calling it on
        # an rc 0/1 result would read a gate's own findings prose as an
        # invocation defect.
        return None
    return _gate_invocation.classify_not_invocable(
        r.stdout, r.stderr,
        supplied_flags=[a for a in argv if a.startswith("--")])


def _rejects_the_umbrella_argv(argv: List[str]) -> bool:
    """True when the gate never got past argument parsing on this argv, as
    opposed to the gate refusing its input.

    Kept as a boolean predicate because that is what `measure` and the
    regression tests want; the classification itself lives in `_why_rejected`,
    which owns nothing and delegates everything.
    """
    return _why_rejected(argv) is not None


def measure(jobs: int = 8) -> Dict[str, object]:
    """Registered gates that reject the production dispatch contract.

    The argv comes from `flow_compliance_check._structural_gate_argv`, never from
    a re-typed literal: a re-typed argv agrees with the umbrella by coincidence,
    which is the reason that function was named in the first place (#492).
    A gate whose required declaration is absent is counted as a derived N/A,
    matching production dispatch, and is never executed with placeholders.
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
            derived_na = {
                g for g in gates
                if F._p0_contract_na_reason(g, probe, probe) is not None
            }
        except Exception as exc:                               # noqa: BLE001
            return {"error": f"argv builder raised: {exc}"}
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            runnable = [g for g in gates if g not in derived_na]
            rejected_runnable = list(ex.map(
                _rejects_the_umbrella_argv, (argvs[g] for g in runnable)))

    rejected_by_gate = dict(zip(runnable, rejected_runnable))
    verdicts = [rejected_by_gate.get(g, False) for g in gates]

    measured = {g for g, rejected in zip(gates, verdicts) if rejected}
    return {"registered": len(gates), "measured": sorted(measured),
            "derived_na": sorted(derived_na)}


#: Flags the umbrella ALREADY computes — a project path, an RTL directory, an
#: output directory, a top-module name. A gate needing only these is an ordinary
#: wiring gap. A gate needing a design-specific SEMANTIC value (a CRC signal
#: name, a tristate bus's drivers) cannot be driven by any generic umbrella, and
#: handing it a placeholder would turn an honest NOT_INVOCABLE into a WRONG
#: verdict — strictly worse than the silence (vibe-ic#559).
UMBRELLA_SUPPLIABLE: frozenset = frozenset({
    "--rtl-dir", "--rtl-files", "--out-dir", "--project-dir", "--base-dir",
    "--top-module", "--json-file", "--l9-file", "--config", "--qsf-file",
    "reference_dir", POSITIONAL_MARKER,
})


def _required_flags(argv: List[str]) -> List[str]:
    """What the gate says it requires, or the positional marker.

    TWO SOURCES, because there are two rejection protocols and this function
    used to know only one. argparse writes ``the following arguments are
    required: --a, --b``; a gate that hand-rolls the check (Rule B) never
    reaches argparse's required-argument machinery and writes its own line, e.g.
    ``error: top module not resolved (give --top or --qsf)``.

    Reading only the first meant EVERY Rule-B gate fell through to
    `POSITIONAL_MARKER`, which is a member of `UMBRELLA_SUPPLIABLE`, so
    `_split_undecided` filed all of them as an ordinary `wiring_gap` — the pile
    labelled "mechanical work". Three of the four measured at v1.9.74 need a
    value that is a fact about the DESIGN (an AND-mask table, a periodic-signal
    manifest, a payload bitmap); calling that mechanical is precisely the
    mis-split the two piles exist to prevent.

    The second source is the SAME text Rule B keyed on, and it is scoped the
    same way: a flag the caller DID supply is the gate's verdict about the
    value, not a statement about what it needs.
    """
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=GATE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return [POSITIONAL_MARKER]
    m = re.search(r"required:\s*(.+)", r.stderr or "")
    if m:
        return [s.strip() for s in m.group(1).split(",") if s.strip()]
    named = _gate_invocation.rule_b_named_options(
        r.stdout, r.stderr,
        supplied_flags=[a for a in argv if a.startswith("--")])
    return named or [POSITIONAL_MARKER]


def _licensed_gates() -> Set[str]:
    """Gates whose silence carries a RECORDED measurement.

    An absent record is NOT a licence — a failed import yields the empty set, so
    every gate reads as undecided rather than as quietly approved. That is the
    fail-safe direction: over-reporting work to do, never under-reporting it."""
    try:
        import flow_compliance_check as _F   # noqa: PLC0415
    except Exception:                        # noqa: BLE001
        return set()
    return (set(getattr(_F, "P0_RTL_DIR_GROUP_MEASUREMENT", ()))
            | set(getattr(_F, "_ZERO_DENOMINATOR_CLASSIFICATION", ()))
            | set(getattr(_F, "_STRUCTURAL_GATE_ARGV_ADAPTERS", ()))
            # #559: gates whose missing argument is a fact about the DESIGN, so
            # no umbrella can supply it. Their silence is decided, not pending.
            | set(getattr(_F, "_SEMANTIC_ARGV_UNDRIVABLE", ()))
            # #559: gates registered in the per-project umbrella that examine
            # the plugin itself, or need a bench instrument. Wrong umbrella,
            # not missing wiring.
            | set(getattr(_F, "_NOT_A_PROJECT_GATE", ()))
            # #559 (round 6): the last 12 undecided silences, each measured with
            # the umbrella's own argv over the corpus and decided (reddens the
            # corpus / zero decidable denominator / design-value / later-flow
            # artifact / post-gate policy / caller-supplied utility / governance).
            # This is what lets `undecided_silence` reach 0 and become a HARD
            # ERROR instead of a report.
            | set(getattr(_F, "_UNDRIVABLE_BY_STRUCTURAL_UMBRELLA", ())))


def _split_undecided(gates: List[str]) -> Dict[str, List[str]]:
    """Undecided gates split into wiring gaps and undrivable-by-design.

    The argv comes from the umbrella's own builder, so a gate that rejects it
    here rejects it in production too."""
    if not gates:
        return {"wiring_gap": [], "needs_design_value": []}
    programs = Path(__file__).resolve().parent
    if str(programs) not in sys.path:
        sys.path.insert(0, str(programs))
    try:
        import flow_compliance_check as _F   # noqa: PLC0415
    except Exception:                        # noqa: BLE001
        # Cannot build the argv, so cannot classify. Everything reads as a
        # wiring gap: it over-states the mechanical pile rather than quietly
        # shrinking the one that needs a human decision.
        return {"wiring_gap": list(gates), "needs_design_value": []}
    wiring, design = [], []
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp)
        for g in gates:
            need = _required_flags(
                _F._structural_gate_argv(g, probe, rtl_dir=probe))
            (wiring if set(need) <= UMBRELLA_SUPPLIABLE else design).append(g)
    return {"wiring_gap": wiring, "needs_design_value": design}


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
            # vibe-ic#559 — WHICH silences are licensed. Until the #492
            # measurement moved into `flow_compliance_check`, this program could
            # only COUNT un-invocable gates; it could not tell a silence somebody
            # measured and decided to keep from one nobody ever looked at. Those
            # are different facts and only the second is a defect.
            #
            # Reported, never failed on: the first count is legitimately non-zero,
            # and failing on it would make licensed decisions look like debt. The
            # subset predicate above still decides rc.
            "licensed_silence": sorted(measured & _licensed_gates()),
            "undecided_silence": sorted(measured - _licensed_gates()),
            # The undecided pile split by whether the umbrella COULD drive the
            # gate. Measured per gate from its own argparse output, not judged:
            # 17 of the 21 need only paths the umbrella already computes, and 4
            # need a design-specific semantic value no umbrella can synthesise.
            # Those two piles have different fixes, so counting them together
            # hides which work is mechanical and which is a de-registration.
            **_split_undecided(sorted(measured - _licensed_gates())),
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
    # #559 (round 6) — UNDECIDED SILENCE IS NOW A HARD ERROR, not a report.
    # Until every un-invocable gate carried a recorded decision, this count was
    # legitimately non-zero and could only be printed (the licensed pile and the
    # nobody-looked pile were not yet separable to zero). Round 6 measured and
    # recorded the last 12, so undecided_silence reaches 0 — and a check that can
    # reach 0 must FAIL when it does not, or it is the very "silence reads as
    # benign" defect #492/#559 exist to kill. A newly-registered gate that
    # rejects the umbrella's argv with NO recorded decision now fails HERE
    # instead of returning nothing while P0 reports PASS. BLOCKING.
    undecided = res.get("undecided_silence") or []
    if undecided:
        print(f"[FAIL] {len(undecided)} gate(s) reject the umbrella's argv with "
              f"NO recorded decision anywhere: {', '.join(undecided)}. Each "
              f"returns no verdict while P0 reports PASS, so what it audits is "
              f"UNAUDITED and the silence reads as benign. Wire it (clearing "
              f"#492's bar), de-register it, or record why it cannot be driven "
              f"in one of the licensed-silence tables in flow_compliance_check.",
              file=sys.stderr)
        return RC_DRIFT
    print(f"[PASS] {len(res['measured'])} of {res['registered']} registered P0 "
          f"gates reject the umbrella's argv; all are recorded. No new silent "
          f"gate.", file=sys.stderr)
    und = res.get("undecided_silence") or []
    lic = res.get("licensed_silence") or []
    print(f"       of those, {len(lic)} carry a recorded #492/#496 measurement "
          f"and {len(und)} carry no decision anywhere — the second number is "
          f"what #559 has left to triage.", file=sys.stderr)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
