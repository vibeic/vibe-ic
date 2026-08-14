"""DIMENSION 6 of the 63x8 matrix — skip discipline.

    Is SKIP / VACUOUS_PASS being ABUSED?

A gate that skips is not automatically dishonest. A gate that skips *and is
counted as having passed* is. This module asks, of every one of the 63 flow
steps, the two halves of that question:

  (a) **Is the skip conditioned on a runtime fact?**  A skip branch that is
      taken on every input is a gate switched off while still counting as run.
      The proof required here is constructive: find an input under which the
      step does NOT skip.

  (b) **Is the skip reported at a non-PASS tier?**  A skip folded into the PASS
      bucket is the highest-leverage lie in the flow, because it is invisible
      in exactly the summary line a reviewer reads.

plus the disclosure channel itself: a waiver must be declared in
machine-readable form. A justification that lives only in a code comment is
not a disclosure — silence is never disclosure.

====================================================================
HOW THIS IS MEASURED — AND WHY IT IS NOT A SOURCE SCAN
====================================================================
Nothing below greps program source for ``sys.exit(2)`` or ``"VACUOUS_PASS"``.
That would be the mistake PR #460 shipped: this codebase dispatches through
``__import__(f"{name}_protocol_synth")``, glob+importlib and
``spec_from_file_location``, so a text scan sees neither the call sites nor the
branches. It would also confuse a comment for a call site.

Instead every predicate is a **behavioural measurement of the real consumer**:

  * A one-step flow yaml is generated from the LIVE
    ``flow/phase1_phase2_phase3.yaml`` (the step dict verbatim, ``blocks_on``
    dropped so the step is not deferred by absent upstreams).
  * ``programs/flow_compliance_check.py`` — the actual gate runner, invoked as
    a subprocess exactly as the flow invokes it — is pointed at that yaml and
    at a synthetic project, and its ``--json`` report is read back for the
    step's resolved **status tier**.
  * The gate programs' OWN JSON reports (the ``--json <path>`` target named in
    each gate command) are read back out of the project afterwards. Their
    top-level ``verdict`` / ``status`` / ``summary.skipped`` fields are this
    repo's documented verdict-self-report contract (§4.05 / #433c), not a
    string heuristic invented here.

Two synthetic projects per step (three where noted), all built from the
step's own declarations:

  EMPTY   nothing on disk at all.
  SEEDED  every path the step's own yaml names — ``condition.files_exist``,
          every gate ``files_exist`` leg, every
          ``optional_program_exit_zero.condition_files_exist``, and every
          ``required_outputs`` entry (``" OR "``-split) — materialised, with
          ``*``/``**``/``?``/``[...]`` concretised to the literal ``x``.

  SAFETY_RTL  built only for steps whose gate passes ``--rtl-dir`` (read off
          the live yaml, not a pinned step id): SEEDED plus RTL that DECLARES
          an ECC safety mechanism. The path-seeder can only materialise
          ``phase2/stage1/rtl`` as a BARE DIRECTORY, so a gate that reads RTL
          CONTENT skips on every input it can build — which left FS1 with no
          non-skipping input for leg L2 to find once an over-eager
          empty-directory FAIL was removed from the gate. See
          ``_SAFETY_RTL_FILES``.

Three seeding rules are content-aware, and each reads a documented contract
rather than guessing a schema:

  * ``analog_block_list.json`` is written ``{"blocks": ["x"]}``. The shape is
    ``_analog_a_check_common.load_block_list``'s own contract, and the block is
    named ``x`` so it lines up with the glob concretisation, which is what
    makes ``phase1/analog/*/spec.json`` resolve to a directory the A-track
    gates actually look in. It is written at every root in
    ``_analog_a_check_common._BLOCK_LIST_ROOTS`` plus ``analog/``, because
    different A-gates carry different candidate-root lists and seeding only
    one root measures the root mismatch instead of the skip discipline.
  * The safety-mechanism RTL of the SAFETY_RTL scenario is built from
    ``fmeda_fault_injection_coverage.detect_safety_mechanism``'s own stated
    recognition rule (a widest protected input, a narrower corrected-data
    output, and a paired detection port whose NAME declares detection; an
    encoder whose output is wider than its input).
  * P0 — the structural-RTL umbrella — declares no paths at all in the yaml
    (its skip lives inside ``flow_compliance_check``, conditioned on an RTL
    directory), so it gets one extra scenario with a real
    ``phase2/stage1/rtl/top.v``. Without it P0's skip could not be shown
    conditional and this module would have to report an honest gap.

====================================================================
THE LEGS (five numbered, eight measured)
====================================================================
L1  NO UNCONDITIONAL PASS.  status(EMPTY) != "PASS". A step that certifies a
    plain PASS on a project containing nothing has a gate that is satisfied by
    no evidence whatsoever.

L1b THE GATE ALONE DOES NOT PASS ON NOTHING.  The real
    ``flow_compliance_check._evaluate_gate`` is called on a project containing
    nothing, ISOLATED from the required_outputs presence check, and must not
    return ``passed=True`` unless (i) it recorded a ``__VACUOUS_HINT__`` /
    ``__SKIP_HINT__`` / ``__WAIVER_HINT__`` reason, or (ii) every BLOCKING
    clause is an ``optional_program_exit_zero`` whose ``condition_files_exist``
    is genuinely unmet. Added 2026-07-27 because L1 above is structurally
    incapable on the 61 steps that declare ``required_outputs`` — those resolve
    to MISSING regardless of the gate, so L1's green was bought by
    dimension-3 machinery. L1b is the leg that gives EVERY gated step a
    predicate that can fire; it charges exactly one step today (FS1, waived).

L2  THE SKIP IS CONDITIONAL.  At least one probed scenario resolves the step to
    something OUTSIDE {SKIPPED-CONDITION, VACUOUS_PASS, SKIPPED-SETUP-REQUIRED}.
    This is the constructive proof (a) demands: an input under which the step
    does not skip. FAIL and MISSING both count — a gate that FAILs is a gate
    that ran.

L3  A SELF-DECLARED SKIP IS NEVER FOLDED INTO A PLAIN PASS.  In every scenario,
    if any BLOCKING gate clause's own report self-declares inapplicability,
    the step's resolved tier must not be ``"PASS"``. VACUOUS_PASS,
    SKIPPED-CONDITION, WAIVED, FAIL and MISSING are all acceptable — each is a
    distinct label in the per-step listing and a distinct counter in the
    summary. ``advisory_program_exit_zero`` clauses are excluded: the advisory
    slot's contract (#306) is "runs, records, never blocks", and the runner
    does record their n/a verdict on the step line.

L3b A SELF-DECLARED SKIP IS NEVER FOLDED INTO A PLAIN PASS — for the clauses
    that write NO report.  L3 reads its evidence out of each gate's ``--json``
    target, so for a blocking clause whose yaml command declares none it had
    nothing to read and returned ``[]`` unconditionally. Measured: 10 of the
    flow's 117 blocking exec clauses have no report target, and D1 is the one
    step where EVERY blocking clause is one of them — so L3 was structurally
    incapable there, and shimming D1's two gate programs to print
    ``[SKIP] ...`` and exit 0 moved the step FAIL -> PASS with all five legs
    silent. L3b RUNS those clauses and charges the step when it resolves to a
    plain PASS while such a clause exited 0 having self-declared inapplicability
    through the only channels it has: a line-start prose declaration, a JSON
    document on stdout carrying the repo's verdict-self-report contract, or a
    ``VACUOUS_PASS`` / ``PASS_WITH_WAIVERS`` sentinel that
    ``_check_program_exit_zero``'s 300-character stdout window truncated away.

L3c A SELF-DECLARED SKIP IS NOT INSIDE THE EXECUTED-PASS NUMERATOR.  L3 and
    L3b both stop at the LABEL. They are satisfied the moment a skip is moved
    off the plain PASS bucket onto its own tier — and ``flow_compliance_check``
    used to fold that tier straight back into the published metric
    (``pass_count = counts["PASS"] + counts["VACUOUS_PASS"]``), so a step could
    change label without the headline ``X/Y executed PASS`` moving by one.
    Measured: giving FS1 and step 30 their own tier left
    ``Steps: 1 total (1/1 executed PASS …)`` byte-identical before and after.
    L3c reads the PUBLISHED X off the consumer's own stdout and charges a step
    whose resolved tier is ``VACUOUS_PASS`` while X exceeds the plain-PASS
    counter from the same run.

    CLOSED 2026-07-28 by the fix, not by a waiver: the owner ruled the tier out
    of the numerator and ``pass_count = counts["PASS"]``. The tier stays in the
    DENOMINATOR — a gate that ran and found nothing to audit is an unmet
    requirement, not an inapplicable step — and it is still not a failure. The
    leg charged 4 cells (4, 14, 30, FS1) on the host that measured it; three
    were waived and step 4, waived nowhere, was the red on ``main``. It charges
    0 today and stays armed: it re-reads the published X every run, so restoring
    ``+ counts["VACUOUS_PASS"]`` reddens every cell that lands on the tier.

L4  YAML SKIP SURFACES ARE RUNTIME-CONDITIONED AND REACHABLE.
    Every ``optional_program_exit_zero`` declares a non-empty
    ``condition_files_exist`` (an "optional" clause with no condition is an
    unconditional switch-off), and a LIVE run of
    ``programs/flow_condition_reachability_check.py`` against the current yaml
    reports neither a ``holes`` nor a ``known_open_holes`` entry for the step.

L5  THE WAIVER CHANNEL IS MACHINE-READABLE.  For every step bound to an
    ENV_UNAVAILABLE role name, a waivers.json entry carrying only PROSE (a long
    ``rationale`` but no ``ticket`` / ``review_required`` / ``evidence``) must
    NOT change the step's tier, and must surface a named rejection advisory —
    while the same waiver with the machine-readable attestation fields DOES
    promote a FAIL/MISSING to WAIVED. Prose is not a waiver; the refusal is not
    silent. Steps with no role binding assert the NA precondition live: they
    have no binding *yet*, and gain one the moment someone adds it.

====================================================================
WHAT THIS CANNOT SEE
====================================================================
Stated plainly so nobody mistakes a green run for a stronger claim:

  * WHY a step is on the VACUOUS_PASS tier. L3c charges the AGGREGATION — the
    skip being inside the X of X/Y — and takes the tier itself as given. It
    cannot tell a legitimately-inapplicable step (step 14 with no .ys script)
    from one that should have measured something and did not. The fix does not
    need that discrimination — both are unmeasured, and neither belongs in a
    number that says "measured and passed" — but nothing in this module tells
    the two apart, so a step wrongly parked on the tier still looks the same
    here as one honestly parked there.
  * A skip path that neither EMPTY nor SEEDED reaches is not measured. The
    seeding is derived from the step's own declarations; a gate whose skip
    hinges on an artefact the step never names (step 30's SPEF is one — it is
    why step 30 is waived, not why it is missed) can hide a branch from this
    module.
  * ``advisory_program_exit_zero`` verdicts (L3 exclusion, above).
  * L1 (as distinct from L1b) fires on 0 of 63 steps on the current tree and is
    structurally incapable on the 61 that declare ``required_outputs``. It is
    kept because it is the honest floor for the two that do not; it is L1b that
    carries the dimension.
  * L2 is inert for the 40 steps whose EMPTY status is MISSING (MISSING is not
    in ``SKIP_TIERS``), and the SEEDED fixture materialises the step's own
    condition paths, so a step-level condition can essentially never make
    SEEDED a SKIPPED-CONDITION. Both are measured, not assumed:
    ``test_d6_every_cell_has_at_least_one_capable_leg`` computes per-cell leg
    capability live and fails if any cell has none.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import yaml

from matrix_63x8 import flowref as F
from matrix_63x8 import waivers as W
from matrix_63x8.cells import cells_for

DIM = 6

FCC_PY = F.PLUGIN_ROOT / "programs" / "flow_compliance_check.py"
REACH_PY = F.PLUGIN_ROOT / "programs" / "flow_condition_reachability_check.py"

#: Tiers that mean "this step did not do its work". Taken verbatim from
#: flow_compliance_check's own `counts` dict / `_label` table, not invented.
SKIP_TIERS: Tuple[str, ...] = (
    "SKIPPED-CONDITION",
    "VACUOUS_PASS",
    "SKIPPED-SETUP-REQUIRED",
)

#: Normalised gate-report verdict/status values that are a self-declared
#: inapplicability. Every one of these was OBSERVED being emitted by a gate
#: program in this tree during a probe run; none is speculative.
SELF_SKIP_VERDICTS: Tuple[str, ...] = (
    "SKIP",
    "SKIPPED",
    "SKIPPED-CONDITION",
    "VACUOUS-PASS",
    "VACUOUS-PASS-UNCONFIRMED",
    "NOT-APPLICABLE",
    "N/A",
    "NA",
    "NO-BUILD",
    "NOT-RUN",
    "DISCLOSED-SKIP",
    "INAPPLICABLE",
)

#: Documented candidate roots for the analog block list. `_BLOCK_LIST_ROOTS`
#: is read live from the shared helper so a root added there is seeded here
#: without this file changing.
_FALLBACK_ANALOG_ROOTS = ("phase3/analog", "phase1/analog", "analog")

P0_RTL_FILE = "phase2/stage1/rtl/top.v"
P0_RTL_BODY = "module top; endmodule\n"

#: The probe scenarios whose resolved STATUS the legs read. `W_PROSE` /
#: `W_FORMED` are L5's own and are deliberately not here.
_STATUS_SCENARIOS: Tuple[str, ...] = ("EMPTY", "SEEDED", "RTL", "SAFETY_RTL")

#: RTL that DECLARES an ECC safety mechanism — a Hamming(7,4) encoder plus a
#: decoder with a working syndrome check.
#:
#: THIRD content-aware seeding rule, and the same justification as the other
#: two: it is built from a documented contract, not a guessed schema.
#: `fmeda_fault_injection_coverage.detect_safety_mechanism`'s docstring states
#: the positive structure it recognises — "a module with a protected (widest)
#: input port AND a narrower corrected-DATA output that is PAIRED WITH an
#: error-detection port whose NAME declares detection", plus an encoder
#: producing a WIDER output than its input.
#:
#: WHY IT IS NEEDED. The path-seeder materialises `phase2/stage1/rtl` as a
#: BARE DIRECTORY, and every RTL-consuming gate that reads CONTENT then skips
#: on it. For FS1 that made every constructible input a skip tier, so leg L2 —
#: the constructive proof that the skip is conditional — had no non-skipping
#: input to find. That gap was previously MASKED by an over-eager guard in the
#: gate itself (an empty `--rtl-dir` hard-FAILed, so L2 saw a non-skip tier and
#: called the skip conditional). Removing the over-reach exposed the gap; this
#: scenario closes it with a real input under which the step genuinely
#: measures. chip-AGNOSTIC: generic Hamming SEC, no design name, no cell.
_SAFETY_RTL_FILES: Dict[str, str] = {
    "phase2/stage1/rtl/ham_enc.v": (
        "module ham_enc(input [3:0] data_in, output [6:0] code_out);\n"
        "assign code_out[2]=data_in[0]; assign code_out[4]=data_in[1];\n"
        "assign code_out[5]=data_in[2]; assign code_out[6]=data_in[3];\n"
        "assign code_out[0]=data_in[0]^data_in[1]^data_in[3];\n"
        "assign code_out[1]=data_in[0]^data_in[2]^data_in[3];\n"
        "assign code_out[3]=data_in[1]^data_in[2]^data_in[3]; endmodule\n"),
    "phase2/stage1/rtl/ham_dec.v": (
        "module ham_dec(input [6:0] code_in, output [3:0] data_out,"
        " output syndrome_err);\n"
        "wire s0=code_in[0]^code_in[2]^code_in[4]^code_in[6];\n"
        "wire s1=code_in[1]^code_in[2]^code_in[5]^code_in[6];\n"
        "wire s2=code_in[3]^code_in[4]^code_in[5]^code_in[6];\n"
        "assign data_out={code_in[6],code_in[5],code_in[4],code_in[2]};\n"
        "assign syndrome_err=s0|s1|s2; endmodule\n"),
}

#: The gate-command token that says "this step reads an RTL DIRECTORY's
#: contents". Read off the live yaml, so the SAFETY_RTL scenario is built for
#: whichever steps declare it rather than for a hard-coded step id.
_RTL_DIR_FLAG = "--rtl-dir"

_SUBPROCESS_TIMEOUT_S = 60

#: Line-start markers by which a gate program self-declares inapplicability in
#: PROSE on stdout. Used ONLY by leg L3b, and ONLY for a blocking clause that
#: writes no machine-readable report — for those, stdout is the only channel
#: there is. Matched at LINE START (optionally inside `[...]`, optionally after
#: a `<program-name>:` prefix), never as a bare substring, and never when the
#: marker is immediately followed by a count (`skipped: 0` is a statistic, not
#: a disclosure). Every one of these was OBSERVED in this tree's own gate
#: output during the 2026-07-27 probe sweep.
_PROSE_SKIP_WORD = (
    r"(?:SKIPPED-CONDITION|SKIPPED|SKIPPING|SKIP"
    r"|NOT[ _-]APPLICABLE|NOT-APPLICABLE|INAPPLICABLE|N/A"
    r"|VACUOUS[_-]?PASS|DISCLOSED[_-]SKIP|NO[_-]BUILD|NOT[_-]RUN)"
)
_PROSE_SKIP_RE = re.compile(
    r"^\s*(?:\[\s*)?(?:[A-Za-z_][\w.\-]*\s*[:=]\s*)?"
    + _PROSE_SKIP_WORD
    + r"(?![\w-])(?!\s*[:=]?\s*\d)",
    re.IGNORECASE,
)

#: The headline metric line `flow_compliance_check` prints. Leg L3c reads X
#: out of it — the published numerator, not a re-derivation of it.
_HEADLINE_RE = re.compile(r"^Steps: \d+ total \((\d+)/(-?\d+) executed PASS",
                          re.MULTILINE)


# ─────────────────────────────────────────────────────────────────────
# Waivers — ONE registry, the one that is consumed
# ─────────────────────────────────────────────────────────────────────
# This module used to carry a `_PENDING_WAIVERS` mirror of its two dimension-6
# waivers, added while eight agents shared one worktree and a concurrent edit to
# `matrix_63x8.waivers.WAIVERS` could lose an entry. The orchestrator has since
# landed both centrally, so `_waiver_for` and `_mark_for` read the central copy
# and ignored the local one.
#
# The two copies HAD ALREADY DRIFTED by the time the mirror was removed. The
# central FS1 entry said "no consumer ever opens the report file" and named the
# plain PASS as the DEFAULT outcome for every non-safety chip; the local one
# said "no consumer reads the report file" and called it merely "the default
# outcome". The central FS1 evidence reproduced through
# `python3 programs/flow_compliance_check.py`; the local one named a bare
# `flow_compliance_check`, which is not a runnable command. The central DT2
# evidence carried the owner's "PRODUCER + CONSUMER halves LANDED; flow-YAML
# wire BLOCKED" note and named cut_netlist.v and *_pnr.v as the non-surviving
# triggers; the local one carried neither. Two accounts of one gap, with `or`
# silently choosing.
#
# Dimension 5 compared its two copies on every run and stayed identical; this
# module never compared them, which is why the drift went unnoticed. The mirror
# is deleted rather than re-synchronised: a waiver is a public admission, and it
# can have exactly one text.


def dim_waivers() -> Tuple[W.Waiver, ...]:
    """This dimension's waivers, from the one registry that is consumed."""
    return tuple(W.waivers_for_dim(DIM))


# The two waivers it used to carry for the LABEL half of the question (FS1 and
# 30) are gone, together with their central-registry entries, because the
# defects they named were fixed:
#   * FS1  — `fmeda_fault_injection_coverage` / `fmeda_coverage_check` now
#     print a LINE-START `VACUOUS_PASS:` token on their rc-0 inapplicability
#     branches (the only rc-0 disclosure channel `_check_program_exit_zero`
#     reads), bounded in length so it survives the consumer's 300-char stdout
#     window, and the producer no longer answers NOT_APPLICABLE from an
#     --rtl-dir it never opened.
#   * 30   — closed independently, and EARLIER, by #521 (v1.7.84): the gate
#     routes its own `summary["skipped"]` through `_vacuous_exit.exit_code`
#     and answers rc 2, which is how `flow_compliance_check` decides tier
#     membership, plus the rc-independent `VACUOUS_PASS:` sentinel. That
#     waiver was deleted from the central registry there, not here.
#
# DT2's LABEL-half waiver is NOT gone. The obvious repair — re-arm the
# self-disabling ALL-of condition on the PRODUCER'S OWN OUTPUTS — was written,
# measured and WITHDRAWN at the 2026-07-28 convergence merge: it moves the
# self-disable from the input side to the output side, where deleting the one
# artefact DT2 exists to report on turns the step from MISSING/rc 1 into
# SKIPPED-CONDITION/rc 0 and out of the executed-PASS denominator. The yaml is
# back to the ALL-of spelling, the `flow_condition_reachability_baseline.json`
# entry is restored, and DT2 stays waived — for leg L4, not L3c.
#
# What this module carried until 2026-07-28 was the ARITHMETIC half, charged by
# leg L3c, on the steps that measurably land on the VACUOUS_PASS tier under its
# own probes: FS1, 30 and 14 held waivers against one pending OWNER DECISION,
# and step 4 was charged on hosts where its gate lands on that tier rather than
# on FAIL — which is what turned main red, because step 4 had no waiver.
#
# THE DECISION IS TAKEN, AND THE DEFECT IS FIXED, so those waivers are gone from
# the central registry rather than restated here. `flow_compliance_check` now
# computes `pass_count = counts["PASS"]`: a step on the VACUOUS_PASS tier has
# left the published `X/Y executed PASS` numerator. It has NOT left the
# denominator — `total_required` still counts it, because a gate that ran and
# found nothing to audit is an unmet requirement, not an inapplicable step (that
# is SKIPPED-CONDITION, which is subtracted). And it has NOT become a failure:
# the tier appears in none of `failing` / `missing` / `setup_required_skipped` /
# `oss_blocked_skipped`, so it still cannot make a run non-green.
#
# LEG L3c IS NOT RETIRED WITH THE WAIVERS. It is the guard that keeps the
# arithmetic honest: it re-reads the PUBLISHED X off the consumer's own stdout
# every run, so re-adding `+ counts["VACUOUS_PASS"]` reddens every cell that
# lands on the tier.
#
# `_mark_for` prefers the central registry, so a waiver applied centrally makes
# a local copy inert rather than duplicated.



#: Which LEG each locally-waived cell is excused for.
#:
#: A waiver excuses ONE measured gap; `test_d6_skip_discipline` is
#: ``xfail(strict=True)`` for the WHOLE cell, so without this map a waived cell
#: would also stop reporting a NEW defect on a DIFFERENT leg — the waiver would
#: silently widen from "the aggregation is undecided" to "this step is exempt
#: from skip discipline". Measured concretely: with FS1 waived for L3c,
#: reverting the FMEDA disclosure token makes L3 fire again and the cell stays
#: xfailed, i.e. green. ``test_d6_waived_cells_are_clean_on_every_other_leg``
#: runs the remaining legs UNWAIVED so that regression is loud.
#:
#: EVERY dim-6 waiver must name its leg HERE. There is deliberately no
#: fallback any more. Until 2026-07-28 the default was ``"L3c"``, which was
#: accurate while three of the four dim-6 waivers were L3c aggregation waivers.
#: With the aggregation FIXED and those three removed, a default of ``"L3c"``
#: would have silently excused a future waiver from the one leg this change
#: just armed — a blanket exemption arriving by omission. A waiver whose leg is
#: not declared here now excuses NOTHING: every leg runs, and
#: ``test_d6_waived_cells_are_clean_on_every_other_leg`` says so by name.
_WAIVED_LEG_OVERRIDE: Dict[Tuple[str, int], str] = {
    # DT2 is the one dim-6 waiver that is NOT about the L3c aggregation. It is
    # excused for L4 only: its step condition is ALL-of over three paths, two
    # of which are artefacts whose absence DT2 exists to detect, and that is
    # carried as a known-open hole in
    # flow/flow_condition_reachability_baseline.json. Every OTHER leg still
    # runs unwaived here, so DT2 cannot quietly become exempt from the label,
    # the counter or the aggregation checks while this one gap is open.
    ("DT2", DIM): "L4",
}
#: Not a leg name — the sentinel a cell gets when nobody declared one.
_WAIVED_LEG_UNDECLARED = "(none declared)"


def _waived_leg(step_id) -> str:
    key = (F.normalize_id(step_id), DIM)
    return _WAIVED_LEG_OVERRIDE.get(key, _WAIVED_LEG_UNDECLARED)


def _waived_step_ids() -> Tuple[str, ...]:
    """Every dim-6 cell that carries an xfail mark. One registry, no mirror."""
    return tuple(sorted(F.normalize_id(sid) for sid in F.step_ids()
                        if W.xfail_mark(sid, DIM) is not None))


def _waiver_for(step_id) -> Optional[W.Waiver]:
    """The waiver for this cell, or ``None``. Single source: the registry."""
    return W.waiver_for(step_id, DIM)


def _mark_for(step_id):
    """`strict=True` xfail mark for a waived cell, or ``None``."""
    return W.xfail_mark(step_id, DIM)


# ──────────────────────────────────────────────────────────────────────
# Project synthesis
# ──────────────────────────────────────────────────────────────────────
def _ensure_programs_on_path() -> None:
    programs = str(F.PLUGIN_ROOT / "programs")
    if programs not in sys.path:
        sys.path.insert(0, programs)


@lru_cache(maxsize=1)
def _analog_roots() -> Tuple[str, ...]:
    """Block-list candidate roots, read from the shared analog helper."""
    try:
        _ensure_programs_on_path()
        import _analog_a_check_common as _ac  # type: ignore

        roots = tuple(str(r).strip("/") for r in _ac._BLOCK_LIST_ROOTS)
    except Exception:  # pragma: no cover - helper absent on a partial install
        roots = ()
    return tuple(dict.fromkeys(roots + _FALLBACK_ANALOG_ROOTS))


def declared_paths(step_id) -> Tuple[str, ...]:
    """Every path the STEP'S OWN yaml names, `" OR "`-split, order preserved."""
    raw: List[str] = []
    cond = F.step_condition(step_id)
    if cond:
        raw += [str(x) for x in (cond.get("files_exist") or [])]
    for clause in F.gate_clauses(step_id):
        raw += list(clause.files)
        raw += list(clause.condition_files)
        if clause.json_file:
            raw.append(clause.json_file)
    for entry in F.required_outputs(step_id):
        raw += list(F.split_any_of(entry))

    out: List[str] = []
    for pat in raw:
        for alt in F.split_any_of(str(pat)):
            if alt and alt not in out:
                out.append(alt)
    return tuple(out)


def concretise(pattern: str) -> str:
    """Turn a glob into one concrete relative path by collapsing wildcards to
    the literal ``x``. ``**`` first so it does not become ``xx``."""
    p = pattern.replace("**/", "x/").replace("**", "x")
    p = re.sub(r"\[[^\]]*\]", "x", p)
    return p.replace("*", "x").replace("?", "x")


def _seed(project: Path, patterns) -> None:
    pats = list(patterns)
    if any("analog_block_list.json" in p for p in pats):
        pats += [f"{root}/analog_block_list.json" for root in _analog_roots()]
    for pat in pats:
        target = project / concretise(pat)
        try:
            if target.suffix:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    continue
                if target.name == "analog_block_list.json":
                    # _analog_a_check_common.load_block_list's contract; block
                    # named "x" so per-block dirs match the glob concretisation.
                    target.write_text('{"blocks": ["x"]}\n', encoding="utf-8")
                elif target.suffix == ".json":
                    target.write_text("{}\n", encoding="utf-8")
                elif target.suffix in (".v", ".sv"):
                    target.write_text("module stub_top; endmodule\n",
                                      encoding="utf-8")
                else:
                    target.write_text("stub\n", encoding="utf-8")
            else:
                target.mkdir(parents=True, exist_ok=True)
        except OSError:  # pragma: no cover - defensive
            continue


def _one_step_flow(step_id, path: Path) -> None:
    """Write a flow yaml containing ONLY this step, verbatim from the live one.

    ``blocks_on`` is dropped: the step is being measured on its own gate, and
    an unsatisfied upstream would resolve it to DEFERRED-BY-UPSTREAM, which
    measures the cascade rather than the skip.
    """
    doc = F.load_flow()
    top = {k: v for k, v in doc.items() if k != "steps"}
    step = dict(F.step_by_id(step_id))
    step.pop("blocks_on", None)
    top["steps"] = [step]
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(top, fh, allow_unicode=True, sort_keys=False)


def _gate_json_targets(step_id) -> Tuple[Tuple[str, str, Optional[str]], ...]:
    """``(clause_kind, program_basename, --json target or None)`` per exec clause."""
    out: List[Tuple[str, str, Optional[str]]] = []
    for clause in F.gate_clauses(step_id):
        if not clause.command:
            continue
        parts = clause.command.split()
        target = None
        for i, tok in enumerate(parts):
            if tok in ("--json", "--out") and i + 1 < len(parts):
                target = parts[i + 1]
                break
        out.append((clause.kind, parts[0], target))
    return tuple(out)


def _targetless_blocking_clauses(step_id) -> Tuple[Tuple[str, str, Tuple[str, ...]], ...]:
    """``(kind, program, argv-tail)`` for BLOCKING exec clauses with no report.

    2026-07-27, adversarial finding (FATAL): leg L3 collected its self-skip
    evidence exclusively from ``_gate_json_targets``, whose per-clause target is
    ``None`` whenever the yaml command carries no ``--json`` / ``--out`` — and
    the loop then did ``if not target: continue``. Measured on this tree: 10 of
    the 117 BLOCKING exec clauses have no report target, and **D1 is the one
    step where EVERY blocking clause is one of them**, so L3 was structurally
    incapable of firing there. Replacing both of D1's gate programs with a shim
    that printed ``[SKIP] <name>: nothing to check`` and exited 0 moved the step
    from FAIL to PASS and left all five legs returning ``[]``.

    For these clauses the ONLY disclosure channel the consumer reads is the
    return code plus the two line-start sentinels
    (``VACUOUS_PASS`` / ``PASS_WITH_WAIVERS``). Leg L3b therefore RUNS the
    program itself and measures what it said, which is the same behavioural
    instrument the rest of the module uses — not a source scan.
    """
    out: List[Tuple[str, str, Tuple[str, ...]]] = []
    for kind, program, target in _gate_json_targets(step_id):
        if target:
            continue
        if kind == F.K_ADVISORY:
            continue
        for clause in F.gate_clauses(step_id):
            if clause.command and clause.command.split()[0] == program \
                    and clause.kind == kind:
                out.append((kind, program, tuple(clause.command.split()[1:])))
                break
    return tuple(out)


def _prose_skip_line(text: str) -> Optional[str]:
    """The first line of *text* that self-declares a skip, or ``None``."""
    for line in (text or "").splitlines():
        if _PROSE_SKIP_RE.match(line):
            return line.strip()[:200]
    return None


def _consumer_snippet(stdout: str, stderr: str) -> str:
    """Exactly the snippet ``_check_program_exit_zero`` builds for a gate.

    ASKS THE CONSUMER rather than reproducing its arithmetic. L3b's whole job
    is to tell a disclosure the consumer SAW from one its window threw away,
    and a local copy of the window width answers that question about a
    consumer that no longer exists the day the width or the shape moves. The
    copy was here until 2026-07-28, when `flow_compliance_check` grew the
    named `output_snippet` / `_OUTPUT_SNIPPET_CHARS` seam.
    """
    _ensure_programs_on_path()
    import flow_compliance_check as _fcc  # type: ignore

    return _fcc.output_snippet(stdout, stderr)


@dataclass(frozen=True)
class OrphanRun:
    """One BLOCKING gate clause with no report file, run for real."""

    kind: str
    program: str
    rc: int
    #: Line-start prose self-declaration of a skip, if any.
    prose_skip: Optional[str] = None
    #: Self-declared skip inside a JSON document printed on stdout, if any.
    stdout_json_skip: Optional[str] = None
    #: True when the program DID emit a sentinel the consumer honours but the
    #: consumer's 300-char snippet no longer carries it.
    sentinel_truncated: bool = False


def _normalise_verdict(value: Any) -> str:
    return re.sub(r"[_ ]", "-", str(value).strip().upper())


def _self_declared_skip(doc: Any) -> Optional[str]:
    """The machine-readable self-declared-skip signal in a gate's own report.

    Returns a human-readable description of the signal, or ``None``. Reads only
    the fields this repo's verdict-self-report contract defines — never prose.
    """
    if not isinstance(doc, dict):
        return None
    for key in ("verdict", "status"):
        value = doc.get(key)
        if value is not None and _normalise_verdict(value) in SELF_SKIP_VERDICTS:
            return f"{key}={value!r}"
    summary = doc.get("summary")
    if isinstance(summary, dict) and summary.get("skipped") is True:
        return f"summary.skipped=True (reason={summary.get('reason')!r})"
    if doc.get("skipped") is True:
        return "skipped=True"
    if doc.get("applicable") is False:
        return "applicable=False"
    return None


# ──────────────────────────────────────────────────────────────────────
# One measured scenario
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Scenario:
    name: str
    status: Optional[str]
    reasons: Tuple[str, ...] = ()
    advisories: Tuple[str, ...] = ()
    #: ``(clause_kind, program, signal)`` for every gate report that
    #: self-declared inapplicability.
    self_skips: Tuple[Tuple[str, str, str], ...] = ()
    stderr: str = ""
    #: Real runs of the BLOCKING clauses that write no report at all (L3b).
    orphan_runs: Tuple[OrphanRun, ...] = ()
    #: X from the headline ``Steps: N total (X/Y executed PASS …)`` line, read
    #: off the consumer's own stdout — the number a reviewer reads.
    numerator: Optional[int] = None
    #: The report's ``counts`` dict, so X can be compared against the discrete
    #: per-tier counters instead of being re-derived here.
    counts: Optional[Dict[str, int]] = None

    @property
    def blocking_self_skips(self):
        return tuple(s for s in self.self_skips
                     if s[0] != F.K_ADVISORY)


#: A well-formed ENV_UNAVAILABLE waiver: every attestation field _load_waivers
#: requires (ticket, review_required, non-empty evidence, >=40-char rationale).
_GOOD_WAIVER: Dict[str, Any] = {
    "verdict_tier": "ENV_UNAVAILABLE",
    "ticket": "matrix-d6-probe",
    "review_required": True,
    "evidence": ["`which <tool>` -> rc=1 on the matrix-d6 probe host"],
    "rationale": (
        "the required sign-off tool is not installed on this host; the flow "
        "searched PATH and the PDK bridge dir and found nothing to execute"
    ),
}

#: The SAME claim with the machine-readable attestation stripped out — prose
#: only. This is the "a code comment / a paragraph is not a disclosure" probe.
_PROSE_ONLY_WAIVER: Dict[str, Any] = {
    "verdict_tier": "ENV_UNAVAILABLE",
    "rationale": _GOOD_WAIVER["rationale"],
}


def _run_targetless_clauses(step_id, project: Path) -> Tuple[OrphanRun, ...]:
    """Run every BLOCKING gate clause that writes no report, in *project*.

    Invoked AFTER flow_compliance_check has walked the same project, so the
    program sees the tree the consumer left behind — the same state the real
    flow would hand it.
    """
    clauses = _targetless_blocking_clauses(step_id)
    if not clauses:
        return ()
    _ensure_programs_on_path()
    import flow_compliance_check as _fcc  # type: ignore

    out: List[OrphanRun] = []
    for kind, program, tail in clauses:
        prog_py = F.PROGRAMS_DIR / f"{program}.py"
        if not prog_py.is_file():
            continue
        try:
            proc = subprocess.run(
                [sys.executable, str(prog_py), *tail],
                cwd=project, capture_output=True, text=True,
                timeout=_SUBPROCESS_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        full = (proc.stdout or "") + "\n" + (proc.stderr or "")
        snippet = _consumer_snippet(proc.stdout, proc.stderr)
        # Did the program emit a sentinel the consumer honours, and did the
        # consumer's 300-char window still carry it?
        emitted = (_fcc._stdout_signals_vacuous(full)
                   or _fcc._stdout_signals_waiver(full))
        seen = (_fcc._stdout_signals_vacuous(snippet)
                or _fcc._stdout_signals_waiver(snippet))
        stdout_json_skip = None
        try:
            doc = json.loads((proc.stdout or "").strip())
        except (ValueError, TypeError):
            doc = None
        if doc is not None:
            stdout_json_skip = _self_declared_skip(doc)
        out.append(OrphanRun(
            kind=kind,
            program=program,
            rc=proc.returncode,
            prose_skip=_prose_skip_line(full),
            stdout_json_skip=stdout_json_skip,
            sentinel_truncated=bool(emitted and not seen),
        ))
    return tuple(out)


def _run_scenario(step_id, name: str, *, seeded: bool, rtl: bool = False,
                  safety_rtl: bool = False, flow_complete: bool = False,
                  waiver: Optional[Dict[str, Any]] = None,
                  role: Optional[str] = None) -> Scenario:
    tmp = Path(tempfile.mkdtemp(prefix="matrix_d6_"))
    try:
        flow = tmp / "_flow.yaml"
        _one_step_flow(step_id, flow)
        project = tmp / "proj"
        project.mkdir()
        if seeded:
            _seed(project, declared_paths(step_id))
        if flow_complete:
            # everything the FLOW declares, not only this step's own
            own = set(declared_paths(step_id))
            _seed(project, [p for p in flow_declared_outputs()
                            if p not in own])
        if rtl:
            rtl_path = project / P0_RTL_FILE
            rtl_path.parent.mkdir(parents=True, exist_ok=True)
            rtl_path.write_text(P0_RTL_BODY, encoding="utf-8")
        if safety_rtl:
            for rel, body in _SAFETY_RTL_FILES.items():
                f = project / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(body, encoding="utf-8")
        if waiver is not None:
            (project / "waivers.json").write_text(
                json.dumps({"waived_steps": [],
                            "waivers": [dict(waiver, step=role)]}),
                encoding="utf-8",
            )
        report = tmp / "_report.json"
        proc = subprocess.run(
            [sys.executable, str(FCC_PY), str(project),
             "--flow-def", str(flow), "--json", str(report)],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S,
        )
        status: Optional[str] = None
        reasons: Tuple[str, ...] = ()
        advisories: Tuple[str, ...] = ()
        counts: Optional[Dict[str, int]] = None
        if report.is_file():
            doc = json.loads(report.read_text(encoding="utf-8"))
            advisories = tuple(str(a) for a in (doc.get("advisories") or []))
            raw_counts = doc.get("counts")
            if isinstance(raw_counts, dict):
                counts = {str(k): int(v) for k, v in raw_counts.items()}
            for entry in doc.get("steps") or []:
                if str(entry.get("id")) == F.normalize_id(step_id):
                    status = entry.get("status")
                    reasons = tuple(str(r) for r in (entry.get("reasons") or []))
        # The headline X/Y is printed, not reported: L3c compares the number a
        # reviewer READS against the discrete per-tier counters, so it has to
        # come off the same stdout the reviewer sees.
        numerator: Optional[int] = None
        _m = _HEADLINE_RE.search(proc.stdout or "")
        if _m:
            numerator = int(_m.group(1))
        self_skips: List[Tuple[str, str, str]] = []
        for kind, program, target in _gate_json_targets(step_id):
            if not target:
                continue
            path = project / target
            if not path.is_file():
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            signal = _self_declared_skip(doc)
            if signal:
                self_skips.append((kind, program, signal))
        orphan_runs = _run_targetless_clauses(step_id, project)
        return Scenario(
            name=name,
            status=status,
            reasons=reasons,
            advisories=advisories,
            self_skips=tuple(self_skips),
            stderr=proc.stderr[-800:],
            orphan_runs=orphan_runs,
            numerator=numerator,
            counts=counts,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────
# Per-step probe (computed once for the whole session)
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class GateOnlyEval:
    """The step's gate, evaluated in isolation on a project containing nothing."""

    passed: bool
    reasons: Tuple[str, ...]
    #: The pass carries a tier-bearing disclosure hint.
    disclosed: bool
    all_kinds: Tuple[str, ...]
    blocking_kinds: Tuple[str, ...]
    #: Every blocking clause is an optional whose condition is unmet here.
    all_blocking_conditions_unmet: bool
    error: Optional[str] = None


#: Reason prefixes flow_compliance_check uses to move a passing gate OUT of the
#: plain PASS bucket. Read live from the module so a renamed prefix is noticed.
def _disclosure_prefixes() -> Tuple[str, ...]:
    _ensure_programs_on_path()
    import flow_compliance_check as _fcc  # type: ignore

    return (_fcc._VACUOUS_HINT_PREFIX,
            _fcc._SKIP_HINT_PREFIX,
            _fcc._WAIVER_HINT_PREFIX)


def _gate_only_on_empty(step_id) -> Optional[GateOnlyEval]:
    """Run the REAL `_evaluate_gate` for this step's gate on an empty project."""
    if not F.has_gate(step_id):
        return None
    _ensure_programs_on_path()
    import flow_compliance_check as _fcc  # type: ignore

    clauses = F.gate_clauses(step_id)
    all_kinds = tuple(c.kind for c in clauses)
    blocking = tuple(c for c in clauses if c.kind != F.K_ADVISORY)
    tmp = Path(tempfile.mkdtemp(prefix="matrix_d6_gateonly_"))
    try:
        project = tmp / "proj"
        project.mkdir()
        try:
            passed, reasons = _fcc._evaluate_gate(project, F.gate(step_id))
        except Exception as exc:  # pragma: no cover - harness failure path
            return GateOnlyEval(False, (), False, all_kinds,
                                tuple(c.kind for c in blocking), False,
                                error=repr(exc))
        reasons = tuple(str(r) for r in (reasons or ()))
        prefixes = _disclosure_prefixes()
        disclosed = any(r.startswith(p) for r in reasons for p in prefixes)
        unmet = [
            c for c in blocking
            if c.kind == F.K_OPTIONAL and c.condition_files
            and not all((project / p).exists() for p in c.condition_files)
        ]
        return GateOnlyEval(
            passed=bool(passed),
            reasons=reasons,
            disclosed=disclosed,
            all_kinds=all_kinds,
            blocking_kinds=tuple(c.kind for c in blocking),
            all_blocking_conditions_unmet=(
                bool(blocking) and len(unmet) == len(blocking)),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)



# ══════════════════════════════════════════════════════════════════════
# L6 — WAS THE SKIP LEGITIMATE, not merely disclosed
# ══════════════════════════════════════════════════════════════════════
#: Every path ANY step declares as a `required_outputs` alternative: the flow's
#: own statement of what a COMPLETE run contains. 162 alternatives on the tree
#: that added this leg.
#:
#: This is the discriminator this module's own "WHAT THIS CANNOT SEE" section
#: says it lacks: "It cannot tell a legitimately-inapplicable step (step 14
#: with no .ys script) from one that should have measured something and did
#: not." L1-L5 all ask whether a skip is DISCLOSED. None asks whether it was
#: ALLOWED. A disclosed skip that should never have been permitted is still a
#: hole, and it is invisible here precisely because the disclosure is correct.
#:
#: THE RULE: a skip is legitimate only when it is keyed on something the flow
#: NEVER PROMISES. If no step declares the artefact as a `required_outputs`
#: entry, its absence is a genuine design fact — this IC has no analog blocks,
#: no OTP, no .ys script — and skipping is the right answer. If some step DOES
#: declare it, the flow asserts every complete run contains it, so its absence
#: is a broken pipeline and "skip" converts a pipeline failure into a
#: non-event on a tier that is not a failure.
@lru_cache(maxsize=1)
def flow_declared_outputs() -> Tuple[str, ...]:
    out: List[str] = []
    for sid in F.step_ids():
        for entry in F.required_outputs(sid):
            for alt in F.split_any_of(str(entry)):
                if alt and alt not in out:
                    out.append(alt)
    return tuple(out)


#: SHRINK-ONLY, and every entry carries the MEASURED tier it moves to once the
#: flow's declared artefacts are present — which is the evidence that the skip
#: was hiding something rather than reporting one.
#:
#: Landed armed rather than charging, on the same sequencing ground as
#: vibe-ic#1070: `main` is red on 49 pytest failures with five agents
#: repairing it, and three more red cells subtract from the only delta they
#: have to read. A NEW member fails immediately; these three are named with
#: their evidence and may only be DELETED, never added to.
_DEFERRED_L6_SKIPS: Dict[str, str] = {
    "12": "VACUOUS_PASS -> FAIL once the flow's declared artefacts exist — "
          "the skip is standing in for a real failure",
    "30": "VACUOUS_PASS -> PASS — keyed on an artefact step 30 never names but "
          "another step declares (the SPEF; cf. this module's own note that "
          "step 30's skip 'hinges on an artefact the step never names')",
    "P0": "SKIPPED-CONDITION -> FAIL — the structural-RTL umbrella skips for "
          "want of an artefact the flow guarantees",
}


@dataclass
class Probe:
    step_id: Any
    scenarios: Dict[str, Scenario] = field(default_factory=dict)
    roles: Tuple[str, ...] = ()
    gate_only_empty: Optional[GateOnlyEval] = None

    def status(self, name: str) -> Optional[str]:
        s = self.scenarios.get(name)
        return s.status if s else None


@lru_cache(maxsize=1)
def _role_map() -> Dict[str, Any]:
    """``{role_name: step_id}`` read LIVE from flow_compliance_check."""
    _ensure_programs_on_path()
    import flow_compliance_check as _fcc  # type: ignore

    return dict(_fcc._ENV_UNAVAILABLE_STEP_NAME_TO_ID)


def roles_for(step_id) -> Tuple[str, ...]:
    key = F.normalize_id(step_id)
    return tuple(sorted(name for name, sid in _role_map().items()
                        if F.normalize_id(sid) == key))


def _reads_an_rtl_directory(step_id) -> bool:
    """True if any gate clause of this step passes `--rtl-dir`.

    Read off the LIVE yaml rather than pinned to a step id, so a second step
    that starts consuming an RTL directory gains the scenario without this
    file changing.
    """
    for clause in F.gate_clauses(step_id):
        if _RTL_DIR_FLAG in (clause.command or ""):
            return True
    return False


def _probe_step(step_id) -> Probe:
    probe = Probe(step_id=step_id, roles=roles_for(step_id))
    probe.gate_only_empty = _gate_only_on_empty(step_id)
    probe.scenarios["EMPTY"] = _run_scenario(step_id, "EMPTY", seeded=False)
    probe.scenarios["SEEDED"] = _run_scenario(step_id, "SEEDED", seeded=True)
    probe.scenarios["FLOW_COMPLETE"] = _run_scenario(
        step_id, "FLOW_COMPLETE", seeded=True, flow_complete=True)
    if _reads_an_rtl_directory(step_id):
        # A step that reads RTL CONTENT cannot be shown anything by the
        # path-seeder, which materialises `phase2/stage1/rtl` as a bare
        # directory. Give it RTL that declares a safety mechanism, so the
        # constructive proof leg L2 demands has an input to find.
        probe.scenarios["SAFETY_RTL"] = _run_scenario(
            step_id, "SAFETY_RTL", seeded=True, safety_rtl=True)
    if not declared_paths(step_id):
        # P0 and anything else that declares no path of its own: SEEDED is
        # byte-identical to EMPTY, so the conditionality leg would have no
        # second input to compare against. Give it a project with real RTL —
        # the flow's universal precondition — so the umbrella's skip has
        # something to be conditional ON.
        probe.scenarios["RTL"] = _run_scenario(
            step_id, "RTL", seeded=True, rtl=True)
    for name, waiver in (("W_PROSE", _PROSE_ONLY_WAIVER),
                         ("W_FORMED", _GOOD_WAIVER)):
        if probe.roles:
            probe.scenarios[name] = _run_scenario(
                step_id, name, seeded=True, waiver=waiver, role=probe.roles[0])
    return probe


@lru_cache(maxsize=1)
def _all_probes() -> Dict[str, Probe]:
    ids = list(F.step_ids())
    with ThreadPoolExecutor(max_workers=8) as pool:
        probes = list(pool.map(_probe_step, ids))
    return {F.normalize_id(p.step_id): p for p in probes}


def probe_for(step_id) -> Probe:
    return _all_probes()[F.normalize_id(step_id)]


@lru_cache(maxsize=1)
def _reachability() -> Dict[str, Any]:
    """One LIVE run of flow_condition_reachability_check over the current yaml."""
    tmp = Path(tempfile.mkdtemp(prefix="matrix_d6_reach_"))
    try:
        out = tmp / "reach.json"
        subprocess.run(
            [sys.executable, str(REACH_PY), str(F.FLOW_YAML), "--json", str(out)],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S,
        )
        if not out.is_file():  # pragma: no cover - defensive
            return {}
        return json.loads(out.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _reach_entries(step_id, bucket: str) -> Tuple[Dict[str, Any], ...]:
    key = F.normalize_id(step_id)
    return tuple(e for e in (_reachability().get(bucket) or [])
                 if F.normalize_id(e.get("step")) == key)


# ──────────────────────────────────────────────────────────────────────
# The five legs
# ──────────────────────────────────────────────────────────────────────
def _leg1_no_unconditional_pass(probe: Probe) -> List[str]:
    empty = probe.scenarios["EMPTY"]
    if empty.status == "PASS":
        return [
            f"L1 UNCONDITIONAL PASS: on a project containing NOTHING the real "
            f"flow_compliance_check resolves this step to status "
            f"{empty.status!r}. A gate satisfied by no evidence at all is "
            f"switched off while still counting as run. Reasons it gave: "
            f"{list(empty.reasons) or '[]'}"
        ]
    return []


def _leg1b_gate_alone_does_not_pass_on_nothing(probe: Probe) -> List[str]:
    """L1b — the GATE, in isolation, must not pass an empty project undisclosed.

    2026-07-27, adversarial finding (HIGH): L1 above asks whether the STEP
    resolves to PASS on an empty project, and it is structurally incapable of
    firing on the 61 steps that declare ``required_outputs`` — those resolve to
    MISSING via the outputs-presence check no matter what the gate does.
    Measured over all 63 steps: the EMPTY status histogram is
    ``{MISSING: 40, SKIPPED-CONDITION: 23}`` and L1 fires on 0. The verifier's
    break — replacing step 20's whole blocking gate with a single
    ``advisory_program_exit_zero`` clause, i.e. a gate switched off while still
    counting as run — left L1 green, because L1's green was bought by
    dimension-3 machinery.

    L1b isolates the gate: it calls the REAL
    ``flow_compliance_check._evaluate_gate`` on a project containing nothing
    and asks whether the gate ALONE says pass. Two answers are legitimate:

      * the gate recorded a DISCLOSURE HINT (``__VACUOUS_HINT__`` /
        ``__SKIP_HINT__`` / ``__WAIVER_HINT__``) — the pass carries a tier that
        is not the plain PASS bucket, which is exactly what L3 asks for; or
      * every BLOCKING clause is an ``optional_program_exit_zero`` whose
        ``condition_files_exist`` is genuinely unmet on the empty tree — the
        flow's declared conditional-skip mechanism, whose reachability is L4's
        subject.

    Anything else is a gate satisfied by no evidence at all. Measured on this
    tree the leg fires on exactly one step (FS1, already waived at this
    dimension) and the advisory-only break above reddens it, because a gate
    with ZERO blocking clauses satisfies neither escape.
    """
    ev = probe.gate_only_empty
    if ev is None or ev.error is not None or not ev.passed:
        return []
    if ev.disclosed:
        return []
    if ev.blocking_kinds and ev.all_blocking_conditions_unmet:
        return []
    return [
        f"L1b GATE PASSES ON NOTHING, UNDISCLOSED: the real "
        f"flow_compliance_check._evaluate_gate returns passed=True for this "
        f"step's gate on a project containing NOTHING, and the pass carries no "
        f"__VACUOUS_HINT__ / __SKIP_HINT__ / __WAIVER_HINT__ reason "
        f"(reasons={list(ev.reasons)[:3] or '[]'}). "
        + (
            "The gate declares no BLOCKING clause at all "
            f"(clause kinds: {list(ev.all_kinds)}), so nothing about this step "
            "can ever be enforced."
            if not ev.blocking_kinds else
            f"Its blocking clauses are {list(ev.blocking_kinds)}, so the pass "
            f"is not explained by the flow's conditional-skip mechanism "
            f"either. A gate satisfied by no evidence is switched off while "
            f"still counting as run."
        )
    ]


def _leg3b_targetless_clause_skip_is_not_folded(probe: Probe) -> List[str]:
    """L3b — a blocking clause with NO report file must not skip into a PASS.

    Companion to L3 for the 10 blocking exec clauses (over 8 steps) whose yaml
    command carries no ``--json`` / ``--out``. L3 read self-skip evidence only
    out of a gate's report file, so for those clauses it had no evidence to
    read and returned ``[]`` unconditionally — on D1, where every blocking
    clause is target-less, that made L3 structurally incapable.

    Each such clause is RUN for real against the same project, and the step is
    charged when its resolved tier is the plain PASS bucket while the clause
    exited 0 and said, through the only channels it has, that it did not do its
    work:

      * a line-start prose self-declaration (``[SKIP] ...``, ``N/A: ...``);
      * a JSON document on stdout carrying the repo's verdict-self-report
        contract (step 24's ``dynamic_ir_drop_check`` prints one); or
      * a sentinel the consumer DOES honour that its own 300-character
        stdout window truncated away — the disclosure was made and lost.
    """
    problems: List[str] = []
    for name in _STATUS_SCENARIOS:
        sc = probe.scenarios.get(name)
        if sc is None or sc.status != "PASS":
            continue
        for run in sc.orphan_runs:
            if run.rc != 0:
                continue
            signals = []
            if run.prose_skip:
                signals.append(f"stdout line {run.prose_skip!r}")
            if run.stdout_json_skip:
                signals.append(f"stdout JSON {run.stdout_json_skip}")
            if run.sentinel_truncated:
                signals.append(
                    "a VACUOUS_PASS / PASS_WITH_WAIVERS sentinel that "
                    "_check_program_exit_zero's 300-char stdout window "
                    "truncated away")
            if not signals:
                continue
            problems.append(
                f"L3b TARGET-LESS SKIP FOLDED INTO PASS [{name}]: the step's "
                f"resolved tier is 'PASS' while its BLOCKING clause "
                f"{run.program} ({run.kind}) exited 0 and self-declared "
                f"inapplicability via {', '.join(signals)}. That clause writes "
                f"no --json/--out report, so this is the ONLY channel it has, "
                f"and flow_compliance_check reads only the return code plus a "
                f"line-start VACUOUS_PASS / PASS_WITH_WAIVERS sentinel — so "
                f"the declaration cannot reach the tier and the skip is "
                f"counted as a pass."
            )
    return problems


def _leg2_skip_is_conditional(probe: Probe) -> List[str]:
    observed = {name: sc.status for name, sc in probe.scenarios.items()
                if name in _STATUS_SCENARIOS}
    non_skip = {n: s for n, s in observed.items() if s not in SKIP_TIERS}
    if non_skip:
        return []
    return [
        f"L2 SKIP NOT SHOWN CONDITIONAL: every constructed input resolves this "
        f"step to a skip tier — {observed}. Skip tiers are {list(SKIP_TIERS)}. "
        f"No input was found under which the step does NOT skip, so the skip "
        f"branch is indistinguishable from one taken on every input. Paths "
        f"seeded from the step's own declarations: "
        f"{list(declared_paths(probe.step_id)) or '[] (step declares none)'}"
    ]


def _leg3_skip_not_folded_into_pass(probe: Probe) -> List[str]:
    problems = []
    for name in _STATUS_SCENARIOS:
        sc = probe.scenarios.get(name)
        if sc is None:
            continue
        blocking = sc.blocking_self_skips
        if sc.status == "PASS" and blocking:
            rendered = "; ".join(
                f"{prog} ({kind}) self-declares {signal}"
                for kind, prog, signal in blocking
            )
            problems.append(
                f"L3 SKIP FOLDED INTO PASS [{name}]: the step's resolved tier is "
                f"{sc.status!r} — the plain PASS bucket — while {len(blocking)} "
                f"BLOCKING gate program(s) self-declared inapplicability in their "
                f"own machine-readable report: {rendered}. A skip counted as a "
                f"pass is invisible in the summary line. Step reasons carried: "
                f"{list(sc.reasons) or '[]'}"
            )
    return problems


def _leg3c_skip_not_inside_the_executed_pass_numerator(
        probe: Probe) -> List[str]:
    """L3c — a step on a skip tier must not be INSIDE the X of ``X/Y``.

    L3 stops at the LABEL: it charges a step that lands in the plain PASS
    bucket while a blocking gate self-declared inapplicability. It says nothing
    about the ARITHMETIC, and `flow_compliance_check` folds the VACUOUS_PASS
    tier straight back into the published numerator
    (``pass_count = counts["PASS"] + counts["VACUOUS_PASS"]``). So a step could
    be moved off the PASS label and the headline number a reviewer reads would
    not move by one — which is exactly what happened when FS1 and step 30 were
    given their own tier: `Steps: 1 total (1/1 executed PASS …)` was
    byte-identical before and after.

    This leg measures the PUBLISHED X, off the consumer's own stdout, against
    the discrete PASS counter from the same run. It charges a step whose own
    resolved tier is VACUOUS_PASS while X exceeds the number of plain PASSes —
    i.e. its skip is inside the numerator.

    The owner has since ruled and the consumer has moved:
    ``pass_count = counts["PASS"]``. This leg is therefore the STANDING guard
    on that arithmetic rather than a report of an open gap — it charges 0 cells
    today, and re-adding ``+ counts["VACUOUS_PASS"]`` makes every cell that
    lands on the tier red again. Falsifiability is measured, both directions,
    by ``test_d6_l3c_fires_when_the_numerator_folds_the_tier_back_in``.
    """
    problems = []
    for name in _STATUS_SCENARIOS:
        sc = probe.scenarios.get(name)
        if sc is None or sc.status != "VACUOUS_PASS":
            continue
        if sc.numerator is None or sc.counts is None:
            problems.append(
                f"L3c UNMEASURED [{name}]: the step resolved to VACUOUS_PASS "
                f"but the headline `X/Y executed PASS` line could not be read "
                f"off the consumer's stdout, so whether the skip is inside X "
                f"is UNKNOWN. Unmeasured is not zero."
            )
            continue
        plain = int(sc.counts.get("PASS", 0))
        if sc.numerator > plain:
            problems.append(
                f"L3c SKIP INSIDE THE EXECUTED-PASS NUMERATOR [{name}]: the "
                f"step resolved to VACUOUS_PASS — its own label and its own "
                f"counter — but the published headline reads "
                f"{sc.numerator}/… executed PASS while only {plain} step(s) "
                f"are on the plain PASS tier. The skip is inside the X a "
                f"reviewer reads: counts={sc.counts}. Moving the label "
                f"without moving the count leaves the metric saying the step "
                f"was measured."
            )
    return problems


def _leg4_yaml_surfaces(probe: Probe) -> List[str]:
    sid = probe.step_id
    problems = []
    for clause in F.gate_clauses(sid):
        if clause.kind == F.K_OPTIONAL and not clause.condition_files:
            problems.append(
                f"L4 UNCONDITIONAL 'OPTIONAL' CLAUSE: "
                f"{clause.program or clause.command!r} is wired as "
                f"{F.K_OPTIONAL} but declares condition_files_exist="
                f"{list(clause.condition_files)} (empty). An optional clause "
                f"with no runtime condition is a gate switched off by "
                f"declaration. Raw clause: {clause.raw}"
            )
    for entry in _reach_entries(sid, "holes"):
        problems.append(
            f"L4 SELF-DISABLING CONDITION (undisclosed): "
            f"flow_condition_reachability_check classifies this step's "
            f"condition on {entry.get('paths')} "
            f"(surface={entry.get('surface')!r}, program={entry.get('program')!r}) "
            f"as {entry.get('verdict')!r} and it is NOT in "
            f"flow_condition_reachability_baseline.json. Detail: "
            f"{entry.get('detail')}"
        )
    for entry in _reach_entries(sid, "known_open_holes"):
        problems.append(
            f"L4 SELF-DISABLING CONDITION (baseline-disclosed): this step's "
            f"condition on {entry.get('paths')} is classified "
            f"{entry.get('verdict')!r} by flow_condition_reachability_check and "
            f"carried as a known-open hole in "
            f"flow_condition_reachability_baseline.json. The disclosure is "
            f"proper and machine-readable, but the condition still vanishes in "
            f"the scenario the step exists to detect. Detail: "
            f"{entry.get('detail')}"
        )
    return problems


def _leg5_waiver_channel(probe: Probe) -> List[str]:
    sid = probe.step_id
    problems: List[str] = []
    if not probe.roles:
        # NA for this step: no ENV_UNAVAILABLE role name in
        # flow_compliance_check's LIVE map binds to it, so there is no waiver
        # channel here to abuse. The map is re-read from the module every
        # session and the precondition is asserted in the test body, so the day
        # someone adds a binding this branch is simply not taken and the three
        # checks below start applying. That is the self-invalidation — an NA
        # that cannot rot into silence.
        return problems

    natural = probe.scenarios["SEEDED"]
    prose = probe.scenarios["W_PROSE"]
    formed = probe.scenarios["W_FORMED"]
    role = probe.roles[0]

    if prose.status != natural.status:
        problems.append(
            f"L5 PROSE ACCEPTED AS A WAIVER: a waivers.json ENV_UNAVAILABLE "
            f"entry for role {role!r} carrying ONLY a rationale paragraph (no "
            f"ticket, no review_required, no evidence) changed the step's tier "
            f"from {natural.status!r} to {prose.status!r}. A waiver must be "
            f"declared in machine-readable form; prose is not a disclosure."
        )
    rejections = [a for a in prose.advisories
                  if "ENV_UNAVAILABLE" in a and role in a]
    if not rejections:
        problems.append(
            f"L5 SILENT WAIVER REFUSAL: the prose-only ENV_UNAVAILABLE waiver "
            f"for role {role!r} was not applied (tier stayed {prose.status!r}) "
            f"but no advisory names it, so the report cannot tell anyone a "
            f"waiver was even attempted. Advisories emitted: "
            f"{list(prose.advisories) or '[]'}"
        )
    if natural.status in ("FAIL", "MISSING") and formed.status != "WAIVED":
        problems.append(
            f"L5 WAIVER CHANNEL DEAD: with every attestation field present "
            f"(ticket + review_required + evidence + >=40-char rationale) the "
            f"ENV_UNAVAILABLE waiver for role {role!r} left the step at "
            f"{formed.status!r} instead of promoting {natural.status!r} to "
            f"'WAIVED'. The prose refusal above would then be measuring a dead "
            f"channel rather than the form of the claim."
        )
    return problems



def _leg6_skip_is_keyed_on_something_the_flow_never_promises(
        probe: Probe) -> List[str]:
    """L6 — WAS THE SKIP ALLOWED?  (not: was it disclosed)

    L1-L5 all ask whether a skip is reported honestly. This asks whether it
    should have been permitted at all, which is a different question and the
    one this module's own "WHAT THIS CANNOT SEE" section says it cannot
    answer: it "cannot tell a legitimately-inapplicable step (step 14 with no
    .ys script) from one that should have measured something and did not".

    Both fixtures name the SAME step and differ only in what is on disk:

      SEEDED         every path the STEP'S OWN yaml names.
      FLOW_COMPLETE  the same, plus every `required_outputs` alternative ANY
                     step declares — the flow's own statement of what a
                     complete run contains.

    A step that skips under SEEDED and STOPS skipping under FLOW_COMPLETE was
    skipping for want of an artefact the flow GUARANTEES. In a healthy run
    that artefact exists, so the branch is reachable only when an upstream
    step failed to deliver — and "skip" is then precisely the wrong verdict,
    because it parks a broken pipeline on a tier that is not a failure.

    A step that skips under BOTH is keyed on something the flow never
    promises, which is a real design fact and a legitimate skip. Measured, and
    it agrees with this module's own worked example without being told to:
    step 14 skips under both and is LEGITIMATE; step 4 and FS1 likewise.
    """
    problems: List[str] = []
    seeded = probe.scenarios.get("SEEDED")
    full = probe.scenarios.get("FLOW_COMPLETE")
    if not seeded or not full:
        return problems
    if seeded.status not in SKIP_TIERS:
        return problems
    if full.status in SKIP_TIERS:
        return problems                       # legitimate: keyed on a non-promise
    sid = F.normalize_id(probe.step_id)
    if sid in _DEFERRED_L6_SKIPS:
        return problems                       # named in the shrink-only register
    problems.append(
        f"L6 SKIP WAS NOT ALLOWED: step {sid} resolves to {seeded.status!r} "
        f"with only its own declared paths present, but to {full.status!r} "
        f"once the artefacts the FLOW declares are present. The skip is keyed "
        f"on something some step promises to produce, so it is reachable only "
        f"when the pipeline is already broken — and it reports that as a "
        f"non-failure. A disclosed skip that should never have been allowed "
        f"is still a hole."
    )
    return problems


_LEGS = (
    ("L1 no unconditional pass", _leg1_no_unconditional_pass),
    ("L1b gate alone does not pass on nothing",
     _leg1b_gate_alone_does_not_pass_on_nothing),
    ("L2 skip is conditional", _leg2_skip_is_conditional),
    ("L3 skip not folded into PASS", _leg3_skip_not_folded_into_pass),
    ("L3b target-less skip not folded into PASS",
     _leg3b_targetless_clause_skip_is_not_folded),
    ("L3c skip not inside the executed-PASS numerator",
     _leg3c_skip_not_inside_the_executed_pass_numerator),
    ("L4 yaml skip surfaces", _leg4_yaml_surfaces),
    ("L5 waiver channel is machine-readable", _leg5_waiver_channel),
    ("L6 skip was allowed, not merely disclosed",
     _leg6_skip_is_keyed_on_something_the_flow_never_promises),
)


# ──────────────────────────────────────────────────────────────────────
# The 63 cells
# ──────────────────────────────────────────────────────────────────────
def _params():
    out = []
    for cell in cells_for(DIM):
        mark = _mark_for(cell.step_id)
        out.append(pytest.param(cell, marks=[mark] if mark else []))
    return out


@pytest.mark.parametrize("cell", _params(), ids=lambda c: f"step{c.step_id}")
def test_d6_skip_discipline(cell):
    """Every skip / vacuous-pass surface of this step is conditioned on a
    runtime fact and reported at a tier that is not the plain PASS bucket."""
    assert cell.dim == DIM, f"{cell.label}: wrong dimension routed here"

    probe = probe_for(cell.step_id)
    assert probe.scenarios["EMPTY"].status is not None, (
        f"{cell.label}: flow_compliance_check produced no status for this step "
        f"on the EMPTY project — the measurement itself failed, so nothing "
        f"below is evidence. stderr: {probe.scenarios['EMPTY'].stderr!r}"
    )
    assert probe.scenarios["SEEDED"].status is not None, (
        f"{cell.label}: flow_compliance_check produced no status for this step "
        f"on the SEEDED project. stderr: {probe.scenarios['SEEDED'].stderr!r}"
    )

    # L5's applicability is a LIVE fact, not a list pinned here: the
    # ENV_UNAVAILABLE role map is imported from flow_compliance_check each
    # session. Guard both halves so the leg cannot be silently switched off —
    # an empty map would make L5 inapplicable to all 63 steps at once, and a
    # binding that appeared after the probe ran would leave this step's L5
    # measured against a stale applicability decision.
    assert _role_map(), (
        f"{cell.label}: flow_compliance_check declares NO ENV_UNAVAILABLE role "
        f"names at all — leg L5 would be inapplicable to every step, which is "
        f"indistinguishable from L5 having been deleted"
    )
    assert probe.roles == roles_for(cell.step_id), (
        f"{cell.label}: the probe ran with role bindings {probe.roles} but the "
        f"live map now says {roles_for(cell.step_id)}"
    )

    problems: List[str] = []
    for _name, leg in _LEGS:
        problems.extend(leg(probe))

    assert not problems, (
        f"{cell.label} — skip discipline, {len(problems)} finding(s):\n  - "
        + "\n  - ".join(problems)
        + f"\n  measured tiers: "
        + str({n: s.status for n, s in probe.scenarios.items()})
    )


# ──────────────────────────────────────────────────────────────────────
# Leg capability — the anti-"silent pass" census
#
# 2026-07-27, adversarial finding (HIGH): three cells (D1, 1, 12) were reported
# ENFORCED while NO leg was capable of firing on them — the only assertions that
# executed in those cell bodies were measurement-plumbing checks. A cell where
# every predicate is structurally inert is silent absence wearing a green tick,
# which is precisely the fourth state the campaign's three-state rule forbids.
#
# `leg_capability()` recomputes, live and per cell, which legs have a subject at
# all, and the test below asserts every one of the 63 cells has at least one.
# It is deliberately CONSERVATIVE: a leg counts as capable when a mutation of
# the repo could make it fire, not when it fires today.
# ──────────────────────────────────────────────────────────────────────
def leg_capability(step_id) -> Dict[str, bool]:
    """Which legs have a live subject for this step. Recomputed from the tree."""
    sid = step_id
    probe = probe_for(sid)
    clauses = F.gate_clauses(sid)
    blocking = [c for c in clauses if c.kind != F.K_ADVISORY]
    exec_blocking = [c for c in blocking if c.command]
    targets = {t for _k, _p, t in _gate_json_targets(sid) if t}
    cond = F.step_condition(sid)
    return {
        # L1 can only fire where the outputs-presence check does not pre-empt
        # a PASS on the empty tree.
        "L1": not F.declares_required_outputs(sid),
        # L1b has a subject wherever the step declares a gate at all.
        "L1b": F.has_gate(sid),
        # L2 needs at least one probed scenario to land on a skip tier.
        "L2": any(sc.status in SKIP_TIERS for sc in probe.scenarios.values()),
        # L3 needs at least one BLOCKING clause that writes a report.
        "L3": bool(targets and blocking),
        # L3b needs at least one BLOCKING exec clause that writes none.
        "L3b": bool(_targetless_blocking_clauses(sid)),
        # L3c needs a probed scenario that actually lands on VACUOUS_PASS —
        # the only tier whose fold into `pass_count` it can observe.
        "L3c": any(sc.status == "VACUOUS_PASS"
                   for sc in probe.scenarios.values()),
        # L6 needs a scenario that lands on a skip tier at all — the same
        # subject L2 needs, asked of a different pair of fixtures.
        "L6": any(sc.status in SKIP_TIERS for sc in probe.scenarios.values()),
        # L4 needs an optional clause or a step-level condition.
        "L4": any(c.kind == F.K_OPTIONAL for c in clauses) or bool(cond),
        # L5 needs an ENV_UNAVAILABLE role binding.
        "L5": bool(probe.roles),
        # (exec_blocking is unused directly; kept for the message below)
        "_exec_blocking": bool(exec_blocking),
    }


def test_d6_every_cell_has_at_least_one_capable_leg():
    """No cell may be green purely because every predicate is inert.

    The three cells the 2026-07-27 verifier named (D1, 1, 12) are covered by
    L1b, which was added for exactly this reason: steps 1 and 12 have
    ``files_exist``-only gates and no condition and no ENV role, and D1's
    blocking clauses all write no report. Emptying step 1's ``files_exist``
    list, or shimming D1's two gate programs to exit 0, now makes the gate pass
    an empty project undisclosed and reddens the cell.
    """
    inert = []
    census: Dict[str, List[str]] = {}
    for sid in F.step_ids():
        cap = leg_capability(sid)
        live = sorted(k for k, v in cap.items()
                      if v and not k.startswith("_"))
        census[F.normalize_id(sid)] = live
        if not live:
            inert.append((F.normalize_id(sid), cap))
    assert not inert, (
        f"{len(inert)} of the {len(F.step_ids())} dimension-{DIM} cells have "
        f"NO capable leg — their green measures nothing about skip discipline: "
        f"{[i[0] for i in inert]}. Per-cell capability: {inert[:3]}"
    )
    # Anti-starvation floor: if the capability computation itself broke and
    # reported everything capable, the assertion above would be vacuous. Pin
    # the measured shape of the two legs that carry the most cells.
    l1b = [s for s, live in census.items() if "L1b" in live]
    l3 = [s for s, live in census.items() if "L3" in live]
    assert len(l1b) == sum(1 for s in F.step_ids() if F.has_gate(s)), (
        f"L1b capability ({len(l1b)}) disagrees with the number of gated steps"
    )
    assert len(l3) >= 40, (
        f"only {len(l3)} steps have a BLOCKING clause that writes a report; "
        f"L3 — the leg most cells rest on — has nearly no subject left"
    )


def test_d6_targetless_blocking_clause_census_is_live_and_non_empty():
    """L3b must have a subject, and the subject must come from the live yaml.

    Measured 2026-07-27: 10 of the 117 BLOCKING exec clauses declare no
    ``--json`` / ``--out`` target, over 8 steps. If that count went to zero,
    L3b would return ``[]`` for all 63 cells and the FATAL hole it closes would
    silently reopen.
    """
    per_step = {F.normalize_id(sid): _targetless_blocking_clauses(sid)
                for sid in F.step_ids()}
    total = sum(len(v) for v in per_step.values())
    owners = sorted(k for k, v in per_step.items() if v)
    assert total >= 1, (
        "no BLOCKING gate clause in the live yaml lacks a --json/--out target; "
        "leg L3b now has no subject on any step and cannot fire"
    )
    assert owners, "L3b census resolved zero owning steps"
    # Every entry must resolve to a real program, or L3b silently runs nothing.
    for sid, clauses in per_step.items():
        for _kind, program, _tail in clauses:
            assert (F.PROGRAMS_DIR / f"{program}.py").is_file(), (
                f"step {sid}: target-less blocking clause names {program!r}, "
                f"which has no programs/{program}.py — L3b would skip it"
            )
    # And at least one of them must have actually been RUN by the probe, or the
    # channel is wired to nothing.
    ran = sum(len(sc.orphan_runs)
              for sid in owners
              for sc in probe_for(sid).scenarios.values())
    assert ran > 0, (
        f"L3b's census names {total} target-less blocking clause(s) over "
        f"{owners}, but the probe executed none of them"
    )


# ──────────────────────────────────────────────────────────────────────
# L3c falsifiability — BOTH directions, on a subject this module builds
# ──────────────────────────────────────────────────────────────────────
#: The shipped arithmetic, and the arithmetic it replaced. Both are matched
#: against the real source; the harness FAILS if either count is not exactly
#: one, so a rename cannot leave this test silently mutating nothing.
_PASS_COUNT_NOW = 'pass_count = counts["PASS"]\n'
_PASS_COUNT_REFOLDED = ('pass_count = counts["PASS"] + '
                        'counts["VACUOUS_PASS"]\n')
_PROGRAMS_DIR_SRC = "PROGRAMS_DIR = Path(__file__).parent\n"

#: A real gate program that vacuously passes on a project containing nothing —
#: rc 2, ``verdict: SKIP``, which is the tier-membership rule. Named as a
#: CANDIDATE LIST and verified live below, so a program that stops being
#: vacuous is reported rather than silently making this test inert.
_VACUOUS_GATE_CANDIDATES: Tuple[str, ...] = (
    "mixed_signal_merge_check",
    "foundry_handoff_package_check",
    "spice_correlation_check",
)


def _first_vacuous_gate_program() -> str:
    """The first candidate that really answers rc 2 on an empty project."""
    tried = []
    for name in _VACUOUS_GATE_CANDIDATES:
        prog = F.PROGRAMS_DIR / f"{name}.py"
        if not prog.is_file():
            tried.append(f"{name}: no such program")
            continue
        tmp = Path(tempfile.mkdtemp(prefix="matrix_d6_vacprobe_"))
        try:
            proc = subprocess.run([sys.executable, str(prog), "."], cwd=tmp,
                                  capture_output=True, text=True,
                                  timeout=_SUBPROCESS_TIMEOUT_S)
            if proc.returncode == 2:
                return name
            tried.append(f"{name}: rc={proc.returncode}")
        except (OSError, subprocess.SubprocessError) as exc:
            tried.append(f"{name}: {exc!r}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    raise AssertionError(
        "no candidate gate program vacuously passes an empty project any "
        f"more, so leg L3c cannot be given a subject to measure: {tried}. "
        "Unmeasured is not zero — pick a program that does, or say the tier "
        "is unreachable."
    )


def _two_step_probe_flow(path: Path, vacuous_program: str) -> None:
    """A flow of exactly two steps: one plain PASS, one VACUOUS_PASS.

    Built on the LIVE flow's top-level keys so it cannot drift from the
    schema the consumer parses, and deliberately NOT on any real step: the
    subject has to exist on every host, not only on one where some particular
    flow step happens to land on the tier.
    """
    doc = F.load_flow()
    top = {k: v for k, v in doc.items() if k != "steps"}
    top["steps"] = [
        {"id": "MD6PASS", "name": "matrix-d6 L3c probe: plain pass",
         "stage": "stage1", "gate": {"files_exist": ["md6_seed.txt"]}},
        {"id": "MD6VAC", "name": "matrix-d6 L3c probe: vacuous",
         "stage": "stage1",
         "gate": {"program_exit_zero": f"{vacuous_program} ."}},
    ]
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(top, fh, allow_unicode=True, sort_keys=False)


def _refolded_checker(dest_dir: Path) -> Path:
    """A copy of the SHIPPED checker with the retired arithmetic restored.

    Two substitutions, each asserted to apply exactly once:
      * ``pass_count`` goes back to ``counts["PASS"] + counts["VACUOUS_PASS"]``
        — the defect;
      * ``PROGRAMS_DIR`` is pinned to the real programs directory, because it
        is derived from ``__file__`` and the copy does not live there. Without
        it no gate program would resolve and the mutant would measure the
        harness rather than the arithmetic.
    """
    src = FCC_PY.read_text(encoding="utf-8")
    assert src.count(_PASS_COUNT_NOW) == 1, (
        f"the shipped numerator line {_PASS_COUNT_NOW!r} occurs "
        f"{src.count(_PASS_COUNT_NOW)} times in {FCC_PY.name}; this harness "
        f"would mutate the wrong thing (or nothing) and its green would mean "
        f"nothing"
    )
    assert src.count(_PROGRAMS_DIR_SRC) == 1, (
        f"cannot pin PROGRAMS_DIR in the mutant: {_PROGRAMS_DIR_SRC!r} occurs "
        f"{src.count(_PROGRAMS_DIR_SRC)} times"
    )
    src = src.replace(_PASS_COUNT_NOW, _PASS_COUNT_REFOLDED)
    src = src.replace(_PROGRAMS_DIR_SRC,
                      f"PROGRAMS_DIR = Path({str(F.PROGRAMS_DIR)!r})\n")
    dest = dest_dir / "flow_compliance_check_refolded.py"
    dest.write_text(src, encoding="utf-8")
    return dest


def _headline_and_counts(checker: Path, flow: Path, project: Path,
                         report: Path) -> Tuple[Optional[int], Dict[str, int],
                                                str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = (str(F.PROGRAMS_DIR) + os.pathsep
                         + env.get("PYTHONPATH", ""))
    proc = subprocess.run(
        [sys.executable, str(checker), str(project),
         "--flow-def", str(flow), "--json", str(report)],
        capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_S, env=env)
    m = _HEADLINE_RE.search(proc.stdout or "")
    doc = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    counts = {str(k): int(v) for k, v in (doc.get("counts") or {}).items()}
    return (int(m.group(1)) if m else None), counts, proc.stdout or ""


def test_d6_l3c_fires_when_the_numerator_folds_the_tier_back_in():
    """BOTH directions of leg L3c, measured on a subject built here.

    L3c charges 0 of the 63 cells now that ``flow_compliance_check`` computes
    ``pass_count = counts["PASS"]``. A leg that charges nothing is
    indistinguishable from a leg that cannot fire, so this test constructs the
    defect and shows the leg catching it:

      * DEFECT DIRECTION — a copy of the shipped checker with
        ``+ counts["VACUOUS_PASS"]`` restored publishes a headline X that
        exceeds the plain-PASS counter from the same run, and L3c's predicate
        (``numerator > counts["PASS"]``) is TRUE.
      * LEGITIMATE DIRECTION — the SHIPPED checker, same flow, same project,
        publishes X equal to the plain-PASS counter, the predicate is FALSE,
        and the vacuous step is still a VACUOUS_PASS (not a FAIL) with the
        run's Overall verdict unchanged between the two.

    The second half is what stops the fix being read as "VACUOUS_PASS was made
    to fail": both runs resolve the same step to the same tier, and both exit
    the same way.
    """
    program = _first_vacuous_gate_program()
    tmp = Path(tempfile.mkdtemp(prefix="matrix_d6_l3c_"))
    try:
        flow = tmp / "flow.yaml"
        _two_step_probe_flow(flow, program)
        project = tmp / "proj"
        project.mkdir()
        (project / "md6_seed.txt").write_text("stub\n", encoding="utf-8")

        x_now, counts_now, out_now = _headline_and_counts(
            FCC_PY, flow, project, tmp / "now.json")
        mutant = _refolded_checker(tmp)
        x_refold, counts_refold, out_refold = _headline_and_counts(
            mutant, flow, project, tmp / "refold.json")

        # The subject must exist, or neither direction measures anything.
        assert counts_now.get("VACUOUS_PASS") == 1, (
            f"the probe flow did not produce exactly one VACUOUS_PASS "
            f"(counts={counts_now}); gate program {program!r} no longer "
            f"vacuously passes and this test measured nothing.\n{out_now}"
        )
        assert counts_now.get("PASS") == 1, (
            f"the probe flow's plain-PASS step did not pass "
            f"(counts={counts_now}) — the comparison X vs counts['PASS'] "
            f"would be degenerate.\n{out_now}"
        )
        assert counts_refold == counts_now, (
            f"the mutant changed the per-tier counts as well as the "
            f"aggregation ({counts_refold} vs {counts_now}); it is no longer "
            f"an isolated test of the numerator"
        )

        # DEFECT DIRECTION — the leg's own predicate must be TRUE.
        assert x_refold is not None and x_now is not None, (
            f"no headline `X/Y executed PASS` line: now={x_now!r} "
            f"refold={x_refold!r}"
        )
        assert x_refold > counts_refold["PASS"], (
            f"with `+ counts['VACUOUS_PASS']` restored the published X is "
            f"{x_refold} and the plain-PASS counter is "
            f"{counts_refold['PASS']} — leg L3c's predicate does NOT fire on "
            f"the very defect it exists to catch, so its silence on the "
            f"shipped tree means nothing.\n{out_refold}"
        )
        assert x_refold == counts_refold["PASS"] + counts_refold["VACUOUS_PASS"]

        # LEGITIMATE DIRECTION — same subject, shipped checker, no charge.
        assert x_now == counts_now["PASS"], (
            f"the shipped checker published X={x_now} while only "
            f"{counts_now['PASS']} step(s) are on the plain PASS tier — the "
            f"skip is back inside the number a reviewer reads.\n{out_now}"
        )
        assert x_now == x_refold - 1, (
            f"the two runs differ by {x_refold - x_now} rather than by the "
            f"single VACUOUS_PASS step; something other than the aggregation "
            f"moved"
        )

        # …and the disclosure tier is still a DISCLOSURE, not a failure.
        for label, out in (("shipped", out_now), ("refolded", out_refold)):
            assert "[VACUOUS-PASS     ] Step MD6VAC" in out, (
                f"{label}: the vacuous step is no longer on the VACUOUS_PASS "
                f"tier:\n{out}"
            )
        assert "Overall: PASS" in out_now and "Overall: PASS" in out_refold, (
            f"leaving the numerator turned the vacuous step into a blocking "
            f"failure — it is a disclosure tier and must not gate.\n"
            f"shipped:\n{out_now}\nrefolded:\n{out_refold}"
        )
        assert counts_now["FAIL"] == 0, (
            f"the vacuous step joined the FAIL bucket: {counts_now}"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────
# Meta-guards on this module itself
# ──────────────────────────────────────────────────────────────────────
def test_d6_covers_every_step_exactly_once():
    """63 cells, one per flow step, no duplicates, no silent absence."""
    cells = cells_for(DIM)
    ids = [F.normalize_id(c.step_id) for c in cells]
    assert len(cells) == len(F.step_ids()), (
        f"dimension {DIM} has {len(cells)} cells but the flow yaml declares "
        f"{len(F.step_ids())} steps"
    )
    assert len(set(ids)) == len(ids), (
        f"duplicate step ids in the dimension-{DIM} cell list: "
        f"{[i for i in ids if ids.count(i) > 1]}"
    )
    assert set(ids) == {F.normalize_id(s) for s in F.step_ids()}


@pytest.mark.parametrize(
    "step_id", list(_waived_step_ids()) or [None],
    ids=lambda s: f"waived{s}")
def test_d6_waived_cells_are_clean_on_every_other_leg(step_id):
    """A waiver excuses ONE leg. It must not become a blanket exemption.

    ``test_d6_skip_discipline`` carries an ``xfail(strict=True)`` for the whole
    cell, so a waived step that ALSO starts failing a different leg still
    reports xfailed — green. Measured: with FS1 waived for L3c, reverting the
    FMEDA line-start disclosure token makes leg L3 fire again ("SKIP FOLDED
    INTO PASS") and nothing goes red. This test runs every leg EXCEPT the
    waived one, unwaived, so that regression is loud.
    """
    if step_id is None:
        pytest.skip("no dimension-6 cell carries a waiver")
    excused = _waived_leg(step_id)
    probe = probe_for(step_id)
    problems: List[str] = []
    ran: List[str] = []
    for name, leg in _LEGS:
        if name.split()[0] == excused:
            continue
        ran.append(name.split()[0])
        problems.extend(leg(probe))
    assert excused in {n.split()[0] for n, _ in _LEGS}, (
        f"step {step_id} is waived for leg {excused!r}, which is not a leg of "
        f"this dimension — the waiver excuses nothing and must be re-decided. "
        f"If the leg is {_WAIVED_LEG_UNDECLARED!r}, nobody declared WHICH gap "
        f"this waiver covers: add the cell to _WAIVED_LEG_OVERRIDE. There is "
        f"deliberately no default, because a default silently exempts a cell "
        f"from a leg nobody chose to exempt it from."
    )
    assert not problems, (
        f"step {step_id} is WAIVED only for leg {excused}, but it fails "
        f"{len(problems)} check(s) on the other legs ({', '.join(ran)}):\n"
        + "\n".join(f"  - {p}" for p in problems)
    )


def test_d6_waivers_are_evidence_backed_and_strict():
    """Every waiver this module relies on — central OR local — passes the
    registry's own validator and is consumed through a ``strict=True`` mark.

    ``strict=True`` is the anti-rot mechanism: when one of these gaps is fixed
    the cell XPASSes and this suite goes red, forcing the waiver's removal.
    """
    assert dim_waivers(), f"dimension {DIM} declares no waiver at all"
    for waiver in dim_waivers():
        problems = W.validate(waiver)
        assert not problems, f"waiver {waiver.label}: {problems}"
        assert waiver.dim == DIM
        mark = _mark_for(waiver.step_id)
        assert mark is not None, f"{waiver.label}: no xfail mark resolved"
        assert mark.kwargs.get("strict") is True, (
            f"{waiver.label}: xfail mark is not strict — a non-strict xfail "
            f"rots silently forever"
        )
    keys = [w.key for w in dim_waivers()]
    assert len(set(keys)) == len(keys), f"duplicate waivers: {keys}"
    # The marks and the waiver list must agree in BOTH directions: a cell
    # carrying an xfail mark that no waiver explains is an unexplained
    # exemption.
    marked = {F.normalize_id(sid) for sid in F.step_ids()
              if _mark_for(sid) is not None}
    explained = {F.normalize_id(w.step_id) for w in dim_waivers()}
    assert marked == explained, (
        f"dimension-{DIM} cells carrying an xfail mark: {sorted(marked)}; "
        f"cells with a resolvable waiver: {sorted(explained)}. Every "
        f"exemption must name its reason."
    )


def test_d6_probe_flow_yaml_is_not_redirected():
    """The measurement must read the repo's yaml, not a scratch copy.

    ``flowref`` honours ``$VIBE_IC_MATRIX_FLOW_YAML`` so a falsifiability
    harness can point it at a mutated file. A normal run with it set would
    grade the repo against a file nobody reviewed.
    """
    assert os.environ.get(F.FLOW_YAML_ENV) is None, (
        f"{F.FLOW_YAML_ENV} is set to "
        f"{os.environ.get(F.FLOW_YAML_ENV)!r} — this suite would measure that "
        f"file instead of {F.FLOW_YAML}"
    )
    assert F.FLOW_YAML.is_file(), f"flow yaml missing: {F.FLOW_YAML}"


def test_d6_consumer_and_reachability_programs_exist():
    """Both live instruments resolve. If either vanishes the legs above would
    silently measure nothing, which is the failure mode this campaign removes.
    """
    assert FCC_PY.is_file(), f"gate runner missing: {FCC_PY}"
    assert REACH_PY.is_file(), f"condition guard missing: {REACH_PY}"
    reach = _reachability()
    assert reach.get("gate") == "flow_condition_reachability_check", (
        f"reachability guard produced no usable report: keys={sorted(reach)}"
    )
    assert int(reach.get("total_conditions") or 0) > 0, (
        f"reachability guard reports {reach.get('total_conditions')!r} "
        f"conditions over {F.FLOW_YAML} — a zero-condition scan cannot fail, "
        f"so L4 would be measuring nothing"
    )


# ══════════════════════════════════════════════════════════════════════
# UNIFORM CELL-STATE INTERFACE (read by programs/tests/test_matrix_63x8_coverage.py)
#
# The coverage meta-test must be able to ask every dimension module the same
# question and get an answer the module itself computes. Anything it derived on
# its own would be a second opinion about cells it does not own — the adjacent
# measurement this campaign removes. Both functions are LIVE: they re-derive
# from the current tree on every call, so a cell that changes state changes its
# answer here without anyone editing a table.
# ══════════════════════════════════════════════════════════════════════
def matrix_na_precondition(step_id):
    """Why this cell is NA, re-derived LIVE, or ``None`` when it is answerable."""
    # Dimension 6 has no NA cell: every step is driven through the real
    # flow_compliance_check on two synthesized projects, so every step has a
    # resolved tier to interrogate. `test_d6_every_cell_has_at_least_one_
    # capable_leg` is what keeps that from degrading into a silent pass.
    del step_id
    return None


def matrix_cell_state(step_id) -> str:
    """``"ENFORCED"`` / ``"WAIVED"`` / ``"NA"`` for one cell of this dimension."""
    if matrix_na_precondition(step_id) is not None:
        return "NA"
    if _waiver_for(step_id) is not None:
        return "WAIVED"
    return "ENFORCED"


# ══════════════════════════════════════════════════════════════════════
# L6's own guards: the denominator, and the register that forgives three cells
# ══════════════════════════════════════════════════════════════════════
_FLOW_DECLARED_OUTPUT_FLOOR = 162


def test_d6_l6_flow_declared_output_denominator_is_disclosed():
    """L6's discriminator is the set of artefacts the flow PROMISES.

    If that set ever resolves to zero — `required_outputs` renamed,
    restructured, or the splitter changed — FLOW_COMPLETE becomes identical to
    SEEDED, every skip classifies as LEGITIMATE, and the leg goes green over
    nothing. That is the starvation shape this whole campaign was convened
    over, so the denominator is pinned as a FLOOR and stated out loud.
    """
    declared = flow_declared_outputs()
    assert len(declared) >= _FLOW_DECLARED_OUTPUT_FLOOR, (
        f"the flow-declared artefact set SHRANK to {len(declared)}, floor is "
        f"{_FLOW_DECLARED_OUTPUT_FLOOR}. L6 cannot tell a guaranteed artefact "
        f"from an unpromised one with an empty set, so it would classify "
        f"every skip as legitimate and report a confident zero."
    )


def test_d6_l6_separates_legitimate_skips_from_illegitimate_ones():
    """Both directions, on the real tree, in one measurement.

    The leg is only worth anything if it DISCRIMINATES. A classifier that
    called every skip legitimate would pass every cell; one that called every
    skip illegitimate would be a rename of L2. So both classes must be
    non-empty and the legitimate class must contain this module's own worked
    example — step 14, which its docstring names as THE legitimately-
    inapplicable step ("step 14 with no .ys script").
    """
    legit, illegit = [], []
    for sid in F.step_ids():
        probe = probe_for(sid)
        seeded = probe.scenarios.get("SEEDED")
        full = probe.scenarios.get("FLOW_COMPLETE")
        if not seeded or not full or seeded.status not in SKIP_TIERS:
            continue
        (legit if full.status in SKIP_TIERS else illegit).append(
            F.normalize_id(sid))
    assert legit, (
        "no skip classified LEGITIMATE — the leg has collapsed into 'every "
        "skip is a defect', which is L2 under another name")
    assert illegit, (
        "no skip classified ILLEGITIMATE — the leg cannot fire at all, and a "
        "detector that has never fired is indistinguishable from no detector")
    assert "14" in legit, (
        f"step 14 is this module's own named example of a legitimately "
        f"inapplicable step (no .ys script) and L6 classified it "
        f"{'ILLEGITIMATE' if '14' in illegit else 'not at all'}; "
        f"legitimate={sorted(legit)} illegitimate={sorted(illegit)}")


def test_d6_l6_deferred_register_only_shrinks():
    """`_DEFERRED_L6_SKIPS` is an admission, not an exemption.

    Every entry must still describe a live illegitimate skip. The moment a
    step is repaired — it stops skipping, or its skip becomes keyed on
    something the flow does not promise — the entry stops describing anything
    and this test reddens until it is deleted. A shrink-only register that can
    outlive its debt is a permanent amnesty with extra steps.
    """
    stale = []
    for sid in sorted(_DEFERRED_L6_SKIPS):
        assert F.has_step(sid), f"register names unknown step {sid!r}"
        probe = probe_for(sid)
        seeded = probe.scenarios.get("SEEDED")
        full = probe.scenarios.get("FLOW_COMPLETE")
        if seeded is None or seeded.status not in SKIP_TIERS:
            stale.append(f"{sid} no longer skips under SEEDED "
                         f"(status={seeded.status if seeded else None!r})")
        elif full is not None and full.status in SKIP_TIERS:
            stale.append(f"{sid}'s skip is now keyed on something the flow "
                         f"does not promise (FLOW_COMPLETE={full.status!r}) — "
                         f"it is legitimate, so delete the register entry")
    assert not stale, (
        "the deferred-skip register no longer describes live defects — it may "
        "only SHRINK, and shrinking means deleting the entry: "
        + "; ".join(stale))


def test_d6_l6_the_register_is_the_only_thing_holding_those_cells_green():
    """Paired control: remove the forgiveness and exactly those cells go red.

    Without this, a future edit could quietly stop the leg charging anything
    while the register still looked like it was tracking three known holes —
    a register describing a debt that is no longer measured.
    """
    charged = set()
    for sid in F.step_ids():
        probe = probe_for(sid)
        seeded = probe.scenarios.get("SEEDED")
        full = probe.scenarios.get("FLOW_COMPLETE")
        if not seeded or not full or seeded.status not in SKIP_TIERS:
            continue
        if full.status not in SKIP_TIERS:
            charged.add(F.normalize_id(sid))
    assert charged == set(_DEFERRED_L6_SKIPS), (
        f"the register and the live measurement disagree: measured "
        f"{sorted(charged)}, registered {sorted(_DEFERRED_L6_SKIPS)}")
