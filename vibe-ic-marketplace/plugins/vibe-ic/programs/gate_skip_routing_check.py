#!/usr/bin/env python3
"""gate_skip_routing_check.py — every gate, and whether its skip REACHES the
machine that reads the verdict (#528).

THE CLASS, AND WHY TWO FIXES DID NOT CLOSE IT
=============================================
``flow_compliance_check`` decides verdict-tier membership from a gate's exit
code: rc 0 PASS / rc 1 FAIL / rc 2 VACUOUS. A gate that examined nothing and
exits 0 is credited in the plain PASS tier — indistinguishable, to every
automated consumer, from a gate that examined the design and found it correct.

#515 (v1.7.79) fixed four such gates; #521 (v1.7.84) fixed nineteen more. Both
were driven by BEHAVIOURAL sweeps, and #528 measured what those sweeps could
see:

    gates with argparse                              389
      positional project_dir first                   313
      flag-only, project-ish flag                     31
      neither shape                                   45
    the sweep actually covered                       181   (47%)

A behavioural sweep needs TWO things per gate before it can say anything at
all: the gate's CLI interface, and an input that drives it down its skip
branch. Both are per-gate work, and when either is missing the gate does not
report "unknown" — it silently leaves the denominator. A gate taking
``--rtl-dir`` was handed a positional project directory, argparse rejected it
with rc 2, and rc 2 to a probe looking for rc 0 read as "did not reproduce".
That is how ``pre_awake_silence_check`` (106 of 107 RTL directories) and
``warn_acceptance_policy_check`` were wrongly cleared until #521 drove them
through their real interfaces.

THE SAME SHAPE IS IN A LANDED CHECK, NOT ONLY IN THE SWEEPS. #528 attributes
the blindness to ad-hoc scripts. It is also in
``gate_discloses_denominator_check --population project``, which drives every
``programs/*_check.py`` with ``subprocess.run([sys.executable, prog, "."])`` —
a positional project directory. Every flag-only gate in that population is
argparse-rejected before its own code runs. That check is not wrong; its
question (can a HUMAN READER see that the gate examined nothing?) is honestly
answered from output text. It is the DENOMINATOR that the invocation shape
truncates, and this module exists because the denominator is the deliverable.

That the shape truncates is not inferred here — ``_gate_invocation`` already
measured it for the SAME argv, ``[sys.executable, <gate>.py, <project>]``:
"of the 241 registered structural gates (0 missing files), 39 never got past
argument parsing — 35 rejected by argparse itself, 4 rejected by a hand-rolled
check for an option the umbrella does not supply". A gate rejected before its
own first statement runs cannot disclose anything, and its silence is
indistinguishable from a clean result.

MEASURED HERE, and it is a SECOND hole in #528's own denominator rather than
the one it named: "gates with argparse: 389" excludes every gate that parses
``sys.argv`` directly. **29 of the 52 gates** in this check's residual contain
no ``argparse`` at all. The axis a population is defined on decides what it can
contain, one level above the axis a probe is driven on.

WHY THIS IS A STATIC ANALYSIS, STATED SO NOBODY RE-DERIVES A 47% SWEEP
======================================================================
A static enumeration's denominator is the FILE LIST. It needs no interface and
no crafted input, so the axis that split the population — ARGUMENT SHAPE —
stops being a filter and becomes a reported column. Every gate is enumerated
whether or not any input in reach makes it skip.

    THE 45 "NEITHER SHAPE" GATES ARE NOT EXCLUDED. They are not a category
    here at all. "Neither shape" is a property of how you INVOKE a gate, and
    this check never invokes one. They are parsed, classified and reported
    exactly like every other in-scope module, and ``--table`` prints their
    shape beside everyone else's so the column stays visible rather than
    becoming a silent filter a second time.

MEASURED, because "it cannot have that blind spot" is a claim and claims get
measured here. Every in-scope module was driven with the sweeps' own argv,
``[sys.executable, <gate>.py, "."]``, over a scratch project:

    in-scope modules                                        548
      the probe could drive                                 411   (75.0%)
      argparse / required-argument REJECTION                137   (25.0%)

Those 137 are the population that answers rc 2 to a probe looking for rc 0 and
is read as "did not reproduce". Against the SAME 137, this enumeration
produces a substantive row for 134 and names the other 3 as exclusions with a
written reason — **0 silently absent, 0 unanalysable**. Inside that blind spot
it finds 7 gates that have skip paths at all and 1,
``emit_attestation_check``, whose skip path is unrouted: an instance no
positional-argv sweep can see, at any sample size.

    "THE GATE HAS NO SKIP PATH" AND "MY PROBE COULD NOT DRIVE THIS GATE" ARE
    DIFFERENT ANSWERS, AND ONLY ONE OF THEM IS ABOUT THE GATE. Nothing here
    probes, so the second answer cannot be produced, and the enumeration never
    has to tell them apart after the fact.

The two blind spots a static analysis has instead are stated up front, because
an audit that does not publish its own blind spots is the defect this file is
about:

  (1) It recognises the skip VOCABULARY in ``_SKIP_DECLARATION_TOKENS`` and no
      other. A gate that declares a skip in a form not listed there is invisible
      to it. The list is printed by ``--table`` and by ``--json`` on every run.
  (2) It reasons about the ENTRY function's own statements. A skip declared and
      terminated entirely inside a helper the entry calls is seen only through
      rule B below (the structured-result rule), not rule A.

WHAT IT IS NOT: a text scan, and not a stdout grep
==================================================
It does not grep source for ``sys.exit(2)``. That is the mistake PR #460
shipped and ``test_matrix_d6_skip_discipline`` records: a text scan sees a
comment as a call site and misses a dispatched one. Every predicate here runs
over the PARSED ``ast``, resolving each terminator's rc EXPRESSION.

It never runs a gate, so it never reads a gate's stdout. Deciding a gate's skip
state by grepping its runtime output is precisely the anti-pattern
``_vacuous_exit`` was built to remove, and doing it in the checker would be the
same defect a third time. What this module DOES read out of the source is the
STRING LITERAL the author wrote into a ``print`` call — a declaration in the
program text, not a stream. And the remedy it demands is never "keep the prose":
it is to route the gate's own ``(passed, skipped)`` pair through
``_vacuous_exit``.

WHAT "ROUTES" MEANS — TAKEN FROM THE CONSUMER, NOT INVENTED HERE
=================================================================
``flow_compliance_check._check_program_exit_zero`` is the one function that
decides the tier. It reads exactly two channels, and this module accepts
exactly those two:

  (A) rc == 2                     -> ``__VACUOUS_HINT__``, the VACUOUS tier.
  (B) rc == 0 AND a line-start ``VACUOUS_PASS`` token in the combined
      stdout/stderr snippet -> ``_stdout_signals_vacuous`` -> the same tier.

A JSON report whose ``verdict`` field says ``VACUOUS_PASS`` is NOT a third
channel: ``_check_program_exit_zero`` never opens the report. Measured by
execution, not by reading — see
``test_gate_skip_routing_check.test_consumer_reads_only_two_channels``.

Channel (B) is real but FRAGILE, and the check says so on every run: the
snippet is ``stdout[-300:] + stderr[-300:]``, so a sentinel printed before ~300
further characters is truncated away and the gate reads as a bare PASS.
``_vacuous_exit`` gives both channels at once — ``exit_code`` returns rc 2 and
``announce_vacuous`` writes the sentinel to stderr — which is why routing
through it, rather than printing a token, is what this check names as the fix.

THE SHARPEST INSTANCE THIS FOUND, AND WHY A SWEEP COULD NOT
============================================================
``_stdout_signals_vacuous`` matches ``line.lstrip().startswith("VACUOUS_PASS")``.
Three gates announced the tier as ``[VACUOUS_PASS] <gate>: ...`` — bracketed.
``"[VACUOUS_PASS] ...".startswith("VACUOUS_PASS")`` is False. Each author wrote
the disclosure, each gate exits 0, and the consumer reads all three as a plain
PASS. No verdict sweep can see this: the gate's output LOOKS like a disclosure,
its rc looks deliberate, and only comparing the emitted token against the
consumer's own matcher separates them.

SCOPE — THREE TIERS, EACH WITH ITS REASON WRITTEN DOWN
=======================================================
An exclusion with a written reason is a result. An exclusion by omission is how
a 47% sweep gets called systematic. Every module in ``programs/`` lands in
exactly one tier and every tier is reported with its count:

  TIER 1  VERDICT-CONSUMED — named in ``flow_compliance_check``'s
          ``_STRUCTURAL_RTL_GATES`` or by a flow-yaml exec clause. Its rc IS a
          verdict about a design today. IN SCOPE.

  TIER 2  GATE-SHAPED, NOT YET WIRED — ``*_check`` / ``*_gate`` / ``*_audit`` /
          ``*_lint`` / ``*_guard`` with no consumer yet. IN SCOPE, deliberately:
          these become tier 1 the moment somebody adds one line to a registry,
          and registering a gate must not silently require re-auditing its exit
          codes. ``marketplace_version_sync_check`` is tier 2 and is read by
          ``gatekeeper_review``, CI and the pre-commit hook — "not in the flow
          yaml" never meant "nobody reads the rc".

  TIER 3  NOT A GATE — generators, one-shot runners, emitters, dashboards. OUT
          OF SCOPE, and the reason is not "hard to analyse": their exit code is
          not a verdict ABOUT A DESIGN, so exiting 0 with nothing to generate
          makes no PASS claim for anything to be credited to. They are still
          enumerated, still classified, and still listed by ``--table`` with
          their tier, so the exclusion is visible rather than absent.

chip-AGNOSTIC: it reasons about Python syntax, exit codes and this repo's own
verdict convention. No vendor, device, PDK or IC name appears in any predicate.

Exit codes:
    0  PASS — every in-scope gate's skip paths reach a consumer channel
    1  FAIL — at least one in-scope gate has a skip path that cannot
    2  cannot run — the programs directory does not exist
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent

# The consumer matches `line.lstrip().startswith("VACUOUS_PASS")`. Derived from
# the shared site rather than re-typed, so the token cannot drift apart from the
# one `_vacuous_exit.announce_vacuous` emits. The trailing ":" is stripped
# because the consumer does not require it — but the LEADING characters matter
# absolutely, which is the whole `[VACUOUS_PASS]` finding.
try:  # pragma: no cover - exercised by the import-shape test
    import _vacuous_exit as _vx
    _CONSUMER_SENTINEL = _vx.VACUOUS_STDOUT_SENTINEL.rstrip(":")
except Exception:  # pragma: no cover - defensive only
    _CONSUMER_SENTINEL = "VACUOUS_PASS"

#: The vocabulary a gate uses to declare "I examined nothing". Recognised as a
#: LINE-START token in a string literal the source passes to `print`. Published
#: on every run (`--json`, `--table`) because a recogniser's word list is its
#: blind spot, and an unpublished blind spot is indistinguishable from none.
_SKIP_DECLARATION_TOKENS: Tuple[str, ...] = (
    "[SKIP]", "[SKIPPED]", "SKIP:", "SKIPPED:", "[SKIP ", "SKIP —", "SKIP -",
    "[N/A]", "N/A:", "[NA]", "[NOT_APPLICABLE]", "NOT_APPLICABLE:",
    "[NOT_CHECKED]", "NOT_CHECKED:", "[NOT-CHECKED]",
    "[VACUOUS]", "[VACUOUS_PASS]", "VACUOUS_PASS:", "VACUOUS:",
    "[PASS_SKIP]", "PASS_SKIP",
)

#: Suffixes that make a module gate-SHAPED even with no consumer wired yet.
_GATE_SHAPED_SUFFIXES: Tuple[str, ...] = (
    "_check", "_gate", "_audit", "_lint", "_guard",
)

TIER_CONSUMED, TIER_GATE_SHAPED, TIER_NOT_A_GATE = 1, 2, 3
_TIER_REASON = {
    TIER_CONSUMED: "rc is read as a verdict by a registered consumer today",
    TIER_GATE_SHAPED: ("gate-shaped; becomes tier 1 the moment a registry line "
                       "is added, so its exit codes are audited now"),
    TIER_NOT_A_GATE: ("generator / runner / emitter — its rc is not a verdict "
                      "about a design, so rc 0 with nothing to do makes no "
                      "PASS claim"),
}


# ---------------------------------------------------------------------------
# THE EXCLUSION REGISTRY — every entry carries the reason, in the code.
#
# "I examined it and dismissed it" is a result and belongs here where the next
# person reads it. "I did not look" leaves no trace and is how this class
# survived two fixes. Nothing is excluded by being hard to parse: an entry that
# cannot be analysed is REPORTED as unanalysable, never quietly cleared.
# ---------------------------------------------------------------------------
_EXCLUDED: Dict[str, str] = {
    "artefact_defect_close_check": (
        "DOCUMENTED CONTRACT, not an oversight (#528, examined and dismissed). "
        "Its header states: 0 = PASS, ADVISORY-only, or SKIPPED (no issue API "
        "reachable) / 2 = cannot run (range or repository unusable). It "
        "deliberately separates 'cannot run' from 'skipped because the issue "
        "API is unreachable', and it is an advisory issue-hygiene gate over a "
        "GitHub corpus, not a gate over a design — so nothing about a design is "
        "credited when it exits 0. Whether an unreachable API should read as 0 "
        "is arguable; it is a decision someone made and wrote down, and this "
        "check does not overturn it by machine."
    ),
    "l9_completeness_check": (
        "NOT AN INSTANCE (#521, recorded so a later sweep does not re-open it "
        "as an oversight). Its `skipped` is a PER-SECTION field inside "
        "`section_summary['registers']`, waiving one requirement that a "
        "declared `no_registers: true` makes N/A. There is no top-level "
        "`summary.skipped` for a router to read, so the structured-result rule "
        "would accuse it of losing a skip signal that does not exist."
    ),
    "gate_skip_routing_check": (
        "This module. It has no skip path — its own vacuous case (no programs "
        "directory) is rc 2 — and analysing itself would make its token list "
        "appear as a skip declaration on every run."
    ),
}


# ---------------------------------------------------------------------------
# THE RESIDUAL, PUBLISHED AND RATCHETED — the point of having a denominator.
#
# MEASURED 2026-07-28 at v1.7.84 + the four fixes that land with this file:
# 52 gates carry 97 skip paths that exit 0 where no consumer channel fires.
# (v1.7.84+ update: +1 gate / +1 path for buffer_occupancy_flag_latency_check
#  → 53 gates / 98 skip paths; the empty/full stale-pointer latency screen has
#  the same "no occupancy flag present → SKIP" unrouted branch.)
# (2026-08-13 update: +1 gate / +1 path for vendored_attribution_retained_check
#  → 52 gates / 97 paths becomes 53 / 98. It is not a NEW defect: the branch was
#  always there, and wiring the checker into the corpus run (#1253, closing a
#  #1241 row) is what made it a GATE and so brought it into this population.
#  Closing one #1241 row opened this one — the entry below says why it is listed
#  rather than drained.)
# #515 fixed 4 and #521 fixed 19; this is 97 more, and the reason neither
# earlier round saw them is exactly what #528 says — a sweep whose
# preconditions decide what it can find reports a clean zero when nothing
# matches its preconditions.
#
# THIS LIST IS NOT AN EXCUSE LIST. It is the count of what is still wrong,
# printed on every run, pass or fail, and the comparison is EXACT in BOTH
# directions:
#
#   * a gate with an unrouted skip path that is NOT here FAILs the check — a
#     NEW gate, or a new branch in an old one, cannot join the class unnoticed,
#     which is the whole reason this is a check and not a script;
#   * a gate here whose count GREW FAILs — the entry cannot absorb a new
#     instance behind an old one;
#   * a gate here whose count SHRANK or reached zero ALSO FAILs, with "update
#     the inventory" — so the list can only ever be made shorter by an edit
#     somebody writes.
#
# It is keyed by COUNT, not by line number, deliberately: line numbers churn on
# every unrelated edit above them and a line-keyed ratchet would be red
# constantly and then disabled. `gate_discloses_denominator_check`'s
# `_EMPTY_PROJECT_SILENT_PASS` keys on the gate NAME alone, which cannot see a
# SECOND unrouted branch appearing in a gate already listed; the count can.
#
# CORROBORATED BY EXECUTION, not only by parsing. Twelve of these were driven
# against a project containing nothing and passed through the real
# `flow_compliance_check._check_program_exit_zero`: 12 of 12 came back
# `passed=True` with NO `__VACUOUS_HINT__` — a plain PASS credited over a
# design nothing examined. See `test_gate_skip_routing_check`.
#
# Draining it is per-gate work with a per-gate reproduction, not a bulk edit:
# each of these needs its skip branch driven, its consumers checked for an
# `rc != 0 -> RED` reader, and its own tests updated. `--strict` reports the
# residual as a FAIL for whoever does that.
_UNROUTED_INVENTORY: Dict[str, int] = {
    # analog_content_detected_must_emit_l5_check: DRAINED (#833). Its one
    # unrouted branch ("no analog keywords found" -> rc 0) now routes through
    # `_vacuous_exit`. The entry is DELETED rather than zeroed, because the
    # ratchet's "fixed" direction demands exactly that: a list that keeps
    # claiming what is already fixed is a baseline outliving its truth.
    "bram_init_file_actually_loaded_check": 1,
    # buffer_occupancy_flag_latency_check (empty/full stale-pointer latency
    # gate) SKIPs (exit 0) on any design with no occupancy flag — an unrouted
    # skip path, same shape as nba_shift_register_same_cycle_read_check below.
    "buffer_occupancy_flag_latency_check": 1,
    "byte_assembler_explicit_9bit_reject_check": 5,
    "cmd_buf_index_semantic_consistency_check": 7,
    "connect_vs_send_test_parity_check": 1,
    "crc_compute_done_before_tx_start_check": 1,
    "crc_polyform_outputreversal_pairing_check": 1,
    "crc_q_settle_cycle_after_last_feed_check": 1,
    "crc_validation_present": 4,
    "dispatch_handler_completeness": 4,
    "emit_attestation_check": 1,
    "fpga_port_qsf_consistency_check": 1,
    "fpga_search_path_includes_required_dirs_check": 1,
    "frame_end_gap_in_l8_check": 1,
    "fsm_state_coverage_check": 1,
    "function_void_with_output_check": 1,
    "half_duplex_response_window_check": 1,
    "l3_opcode_pre_wake_allowed_typed_check": 5,
    "l6_reject_rules_from_rx_event_check": 6,
    "l7_debug_access_grounding_check": 1,
    "l8_clock_period_actionability_check": 1,
    "l8_frame_end_gap_derivation_check": 1,
    "l9_floorplan_contract_check": 1,
    "l9_rtl_pin_consistency_check": 3,
    "metadata_content_substance_check": 1,
    "nba_shift_register_same_cycle_read_check": 1,
    "opcode_dispatch_completeness_check": 1,
    "otp_image_nonzero_check": 1,
    "otp_module_uses_supported_pattern_check": 1,
    "pdk_analog_completeness_check": 1,
    "phase1_doc_content_implementation_completeness_check": 1,
    "phase1_doc_input_completeness_check": 3,
    "phase1_input_vs_generated_completeness_check": 2,
    "protocol_reference_tb_pass_check": 1,
    "response_latency_observability_check": 1,
    "result_md_audit_provenance_check": 1,
    "rig_firmware_capability_check": 2,
    "rx_byte_assembler_ibt_flush_recovery_check": 2,
    "rx_deglitch_filter_required_check": 1,
    "rx_ibt_frame_end_semantics_check": 2,
    "rx_last_bit_frame_end_commit_check": 1,
    "scope_reply_preamble_check": 6,
    "self_rx_mask_required_check": 1,
    "send_test_active_drive_check": 1,
    "slave_tx_no_device_break_check": 1,
    "tb_timing_extremes_check": 1,
    "tx_phy_bit_cell_total_consumed_check": 2,
    # vendored_attribution_retained_check (#1241 / #1253): the gate is wired
    # into the corpus run at `tools/ci/repo_hygiene_gates.sh`, and wiring it is
    # what makes it a gate and so subjects it to this ratchet. Its one unrouted
    # branch is `not res["licensed"]` -> `[VACUOUS_PASS] ... this gate checked
    # nothing` -> rc 0.
    #
    # LISTED RATHER THAN ROUTED, and the reason is a genuine conflict rather
    # than reluctance. Routing means rc 2, and rc 2 has no home here:
    #   * plain `run` makes rc 2 a FAIL, which would make the gate object to a
    #     lawful total withdrawal of the vendored code — the one thing
    #     `test_removing_the_code_too_is_lawful_and_stays_green` records the
    #     owner ruling it must not do;
    #   * `run_tolerating_uncheckable` makes rc 2 non-fatal, but
    #     `test_the_hygiene_script_declares_it_as_a_blocking_gate` requires the
    #     blocking form.
    # Splitting the two does not rescue it: lawful withdrawal and a
    # misconfigured scope are the SAME observation to this gate (both
    # `tracked=0, licensed=0`), so nothing it can see tells them apart.
    #
    # The cheap escape was measured and rejected. Emitting the `VACUOUS_PASS:`
    # sentinel while keeping `return 0` turns THIS check green, because
    # sentinel-only counts as routed — and changes nothing real, because
    # `tools/ci/_gate_dispatch.sh` reads rc and never the sentinel. A routing
    # that routes nowhere is worse than a declared debt.
    "vendored_attribution_retained_check": 1,
    "wake_gen_bus_active_reset_check": 2,
    "wake_gen_silence_gate": 4,
    "wake_pulse_emit_gated_by_first_rx_command_check": 2,
    "wake_pulse_implementation_check": 1,
    "wake_pulse_width_matches_measurement_check": 2,
}


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    gate: str
    rule: str
    lineno: int
    severity: str
    message: str


@dataclass
class GateRow:
    """One row of the enumeration table — the deliverable, per gate."""
    gate: str
    tier: int
    tier_reason: str
    arg_shape: str
    entry: Optional[str]
    skip_paths: int
    routed_paths: int
    unrouted_paths: int
    sentinel_only_paths: int
    unanalysable: Optional[str] = None
    excluded_reason: Optional[str] = None


@dataclass
class Result:
    program: str = "gate_skip_routing_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    rows: List[GateRow] = field(default_factory=list)
    ratchet: Dict = field(default_factory=dict)
    summary: Dict = field(default_factory=dict)


def ratchet(measured: Dict[str, int],
            inventory: Dict[str, int]) -> Dict[str, List[str]]:
    """Exact comparison, both directions. See `_UNROUTED_INVENTORY`."""
    new, grown, shrunk, fixed = [], [], [], []
    for gate, n in sorted(measured.items()):
        if gate not in inventory:
            new.append(f"{gate}: {n} unrouted skip path(s), not in the "
                       f"inventory — a gate cannot join this class unnoticed")
        elif n > inventory[gate]:
            grown.append(f"{gate}: {inventory[gate]} -> {n} unrouted skip "
                         f"path(s); a NEW branch landed behind an old entry")
        elif n < inventory[gate]:
            shrunk.append(f"{gate}: {inventory[gate]} -> {n}; update the "
                          f"inventory so the list stops claiming what is fixed")
    for gate, n in sorted(inventory.items()):
        if gate not in measured:
            fixed.append(f"{gate}: {n} -> 0; delete the inventory entry")
    return {"new": new, "grown": grown, "shrunk": shrunk, "fixed": fixed}


# ---------------------------------------------------------------------------
# Consumer discovery — who reads an exit code as a verdict?
# ---------------------------------------------------------------------------
def structural_gate_registry(programs_dir: Path) -> List[str]:
    """`flow_compliance_check._STRUCTURAL_RTL_GATES`, read from its AST.

    Parsed, not imported: importing `flow_compliance_check` executes a 7000-line
    module for one tuple. Parsed, not regexed: the tuple is a literal and `ast`
    reads it as one.
    """
    src = programs_dir / "flow_compliance_check.py"
    if not src.exists():
        return []
    try:
        tree = ast.parse(src.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "_STRUCTURAL_RTL_GATES":
            value = node.value
            if isinstance(value, (ast.Tuple, ast.List)):
                return [e.value for e in value.elts
                        if isinstance(e, ast.Constant)
                        and isinstance(e.value, str)]
    return []


_YAML_CMD_RE = re.compile(r'(?:program_exit_zero:|command:)\s*"([^"]+)"')


def flow_yaml_programs(plugin_root: Path, known: Sequence[str]) -> List[str]:
    """Program stems named by an exec clause in any flow yaml."""
    flow_dir = plugin_root / "flow"
    if not flow_dir.is_dir():
        return []
    known_set = set(known)
    found = set()
    for yml in sorted(flow_dir.glob("*.y*ml")):
        text = yml.read_text(encoding="utf-8", errors="ignore")
        for m in _YAML_CMD_RE.finditer(text):
            tok = m.group(1).split()
            if not tok:
                continue
            stem = tok[0].split("/")[-1]
            if stem.endswith(".py"):
                stem = stem[:-3]
            if stem in known_set:
                found.add(stem)
    return sorted(found)


# ---------------------------------------------------------------------------
# Argument shape — REPORTED, never used to select.
#
# This is the column whose use as a FILTER produced the 47%. It is computed
# here so the table can show it, and it is deliberately load-bearing for
# nothing: no finding, no tier and no exclusion consults it. Its own precision
# is therefore not critical, which is stated rather than hidden — parsers built
# in a helper or extended in a loop are approximated by walking every
# `add_argument` call in the module in source order.
# ---------------------------------------------------------------------------
_PROJECTISH = ("project", "dir", "root", "run", "path", "design", "file")


def argument_shape(tree: ast.AST, src: str) -> str:
    if "argparse" not in src:
        return "no-argparse"
    names: List[str] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            names.append((node.lineno, node.args[0].value))
    names = [n for _, n in sorted(names)]
    if not names:
        return "argparse-no-arguments"
    if not names[0].startswith("-"):
        return "positional-first"
    flags = [n for n in names if n.startswith("--")]
    if any(any(k in f.lower() for k in _PROJECTISH) for f in flags):
        return "flag-only-projectish"
    return "flag-only-other"


# ---------------------------------------------------------------------------
# Entry-point discovery
# ---------------------------------------------------------------------------
def _called_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
    return None


def entry_function(tree: ast.Module) -> Optional[ast.FunctionDef]:
    """The function the ``if __name__ == "__main__"`` block calls.

    THE GUARD IS THE WHOLE DEFINITION, and a fallback to a bare module-level
    ``main`` was REMOVED rather than kept as a safety net. Two reasons, in
    order:

      * SEMANTICS. A module that defines ``main()`` and has no ``__main__``
        guard cannot be run as a CLI at all — invoking it executes nothing — so
        its exit code is never read as a verdict by anybody. Findings about it
        would be findings about code that cannot run as a gate.
      * MEASUREMENT. It was dead. Of 1032 modules in ``programs/``, **0** had
        an entry that only the fallback could find, so mutating that branch to
        ``return None`` changed no test's outcome — it survived the whole
        mutation set. A branch whose deletion changes nothing is not covered by
        anything, and keeping it would have left one unmeasured claim inside a
        file whose entire subject is unmeasured claims.

    A module with no guard is therefore reported as UNANALYSABLE ("no
    module-level entry function") — never silently cleared, which is the
    fail-safe direction and is pinned by
    ``test_a_module_with_no_main_guard_is_unanalysable_not_analysed``.
    """
    funcs = {n.name: n for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = ast.dump(node.test)
        if "__name__" not in test or "__main__" not in test:
            continue
        for sub in ast.walk(node):
            name = _called_name(sub)
            if name and name in funcs:
                return funcs[name]
    return None


# ---------------------------------------------------------------------------
# Rule A — a skip DECLARED on a branch that then terminates with rc 0
# ---------------------------------------------------------------------------
def _literals(node: ast.AST) -> List[str]:
    """Every string constant this expression would render, in source order."""
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


#: Returned when the line's verdict word is COMPUTED, so this scanner cannot
#: read it out of the source at all. Distinct from None ("no literal here"),
#: because the two must not be tallied the same way — see `_leading_literal`.
_INTERPOLATED = object()


def _verdict_is_interpolated(arg: ast.AST) -> bool:
    """Does this argument begin with an interpolation, or with punctuation
    followed by one?

    `print(f"[{label}] some_check ...")` renders its verdict word from `label`.
    The leading STRING constant is `"["`, which carries no token, so a scanner
    reading literals sees nothing and — before this — recorded neither a skip
    nor an uncertainty. Measured (vibe-ic#707) across the analog-hil family:
    `skip_paths=0 unresolved=0` for four gates that plainly have skip paths.

    That is the shape #693 is about, one level down: the ratchet's `98 == 98`
    balance was computed over a population that STRUCTURALLY excluded them, so
    it reported balance for lines it could not see.
    """
    if not isinstance(arg, ast.JoinedStr):
        return False
    for v in arg.values:
        if isinstance(v, ast.FormattedValue):
            return True
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            # punctuation/whitespace before the first interpolation is a prefix,
            # not a verdict; anything else is a real leading literal.
            if v.value.strip(" \t[(<-—|") == "":
                continue
            return False
    return False


def _leading_literal(call: ast.Call):
    """The first string constant of a `print` call's FIRST positional arg.

    The first argument is what lands at the start of the line, and line-START
    is exactly what the consumer's matcher requires. Taking any literal in the
    call would let a `VACUOUS_PASS` appearing mid-sentence read as a routed
    disclosure it is not.

    Returns `_INTERPOLATED` when the verdict word is computed rather than
    written — an answer this scanner cannot give, which must be COUNTED as
    such rather than pass for "there is no skip here".
    """
    if not call.args:
        return None
    if _verdict_is_interpolated(call.args[0]):
        return _INTERPOLATED
    lits = _literals(call.args[0])
    return lits[0] if lits else None


def _is_print(node: ast.stmt) -> Optional[ast.Call]:
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        name = _called_name(node.value)
        if name in ("print",):
            return node.value
    return None


def _skip_token(text: str) -> Optional[str]:
    head = text.lstrip()
    upper = head.upper()
    for tok in _SKIP_DECLARATION_TOKENS:
        if upper.startswith(tok):
            return tok
    return None


def _reaches_consumer_by_sentinel(text: str) -> bool:
    """True iff this literal, printed at line start, is what the consumer reads.

    `_stdout_signals_vacuous` matches `line.lstrip().startswith("VACUOUS_PASS")`.
    A bracketed `[VACUOUS_PASS]` does not, which is the whole point.
    """
    return text.lstrip().upper().startswith(_CONSUMER_SENTINEL)


_ROUTED_CALLEES = frozenset({"exit_code", "announce_vacuous"})
_RC_NAMES = {"RC_PASS": 0, "RC_FAIL": 1, "RC_VACUOUS": 2}


def _static_rc(expr: Optional[ast.AST]) -> Tuple[Optional[int], bool]:
    """(rc, routed_by_shared_router) for a terminator's value expression.

    rc is None when the expression cannot be resolved statically — reported as
    unresolved, never assumed to be 0.
    """
    if expr is None:
        return 0, False          # bare `return` in an entry -> None -> rc 0
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int) \
            and not isinstance(expr.value, bool):
        return expr.value, False
    if isinstance(expr, ast.Name) and expr.id in _RC_NAMES:
        return _RC_NAMES[expr.id], True
    if isinstance(expr, ast.Attribute) and expr.attr in _RC_NAMES:
        return _RC_NAMES[expr.attr], True
    name = _called_name(expr)
    if name in _ROUTED_CALLEES:
        # `_vx.exit_code(passed, skipped)` decides rc FROM the gate's own
        # conclusion; that IS the routing this check asks for.
        return None, True
    return None, False


def _terminator(node: ast.stmt) -> Optional[Tuple[int, Optional[ast.AST]]]:
    """(lineno, value-expression) if this statement ends the entry function."""
    if isinstance(node, ast.Return):
        return node.lineno, node.value
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        if _called_name(node.value) == "exit":
            args = node.value.args
            return node.lineno, (args[0] if args else None)
    if isinstance(node, ast.Raise) and node.exc is not None:
        if _called_name(node.exc) == "SystemExit":
            args = getattr(node.exc, "args", [])
            return node.lineno, (args[0] if args else None)
    return None


@dataclass
class SkipPath:
    lineno: int
    token: str
    rc: Optional[int]
    routed_by: str          # "rc2" | "shared-router" | "sentinel" | ""
    sentinel_only: bool


def scan_skip_paths(fn: ast.FunctionDef) -> Tuple[List[SkipPath], List[int]]:
    """Rule A over the entry function.

    Walks each statement LIST as its own scope. A skip declaration is remembered
    only until the block's next terminator, and never leaks into a nested block:
    a nested block starts with no pending declaration, so a skip announced in
    one branch can never be charged to a terminator in another.
    """
    paths: List[SkipPath] = []
    unresolved: List[int] = []
    #: `print` calls whose VERDICT WORD is computed (vibe-ic#707). Paired at
    #: FUNCTION scope, not block scope, and that is what makes the count mean
    #: something. The real shape is
    #:
    #:     label = "NOT CHECKED" if verdict == "SKIP" else verdict
    #:     print(f"[{label}] some_check ...")
    #:     for b in report["blocks"]: ...
    #:     if verdict == "SKIP":
    #:         return 2
    #:
    #: — announce, then unrelated statements, then a skip-tier return nested in
    #: an `if`. Block-local pairing never sees it (measured: 0 unresolved for
    #: all four analog-hil gates), and counting every interpolated print instead
    #: took the unanalysable tally from 9 to 311, which is noise rather than
    #: disclosure. A function that announces a COMPUTED verdict AND returns a
    #: skip tier has a skip path this scanner cannot read — that pair, once per
    #: function, is the honest unit.
    interpolated_announce: List[int] = []
    skip_tier_return = False

    def walk(block: List[ast.stmt]) -> None:
        pending: Optional[Tuple[int, str, str]] = None   # lineno, token, text
        for stmt in block:
            call = _is_print(stmt)
            if call is not None:
                text = _leading_literal(call)
                if text is _INTERPOLATED:
                    interpolated_announce.append(stmt.lineno)
                elif text is not None:
                    tok = _skip_token(text)
                    if tok:
                        pending = (stmt.lineno, tok, text)
            elif _called_name(getattr(stmt, "value", None)) == "announce_vacuous":
                pending = (stmt.lineno, "announce_vacuous", _CONSUMER_SENTINEL)

            term = _terminator(stmt)
            if term is not None:
                lineno, value = term
                rc, routed = _static_rc(value)
                if rc == 2:
                    nonlocal skip_tier_return
                    skip_tier_return = True
                if pending is not None:
                    p_line, p_tok, p_text = pending
                    if routed:
                        why = "shared-router"
                    elif rc == 2:
                        why = "rc2"
                    elif rc == 0 and _reaches_consumer_by_sentinel(p_text):
                        why = "sentinel"
                    elif rc is None:
                        unresolved.append(lineno)
                        pending = None
                        continue
                    elif rc == 1:
                        # A FINDING beats a skip; rc 1 is never a lost skip.
                        why = "rc1-finding"
                    else:
                        why = ""
                    paths.append(SkipPath(
                        lineno=p_line, token=p_tok, rc=rc, routed_by=why,
                        sentinel_only=(why == "sentinel")))
                pending = None

            for fld in ("body", "orelse", "finalbody"):
                sub = getattr(stmt, fld, None)
                if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                    walk(sub)
            for handler in getattr(stmt, "handlers", []):
                walk(handler.body)

    walk(fn.body)
    # vibe-ic#707 — a function that announces a COMPUTED verdict and returns a
    # skip tier has a skip path whose word this scanner never read. Recorded
    # ONCE, and only when both halves are present, so the tally stays a
    # disclosure rather than a count of every f-string in the tree.
    if interpolated_announce and skip_tier_return:
        unresolved.append(interpolated_announce[0])
    return paths, unresolved


# ---------------------------------------------------------------------------
# Rule B — a structured skip the entry never reads back (the #515/#521 shape)
# ---------------------------------------------------------------------------
#: Value shapes a `skipped` field can hold that are NOT a skip FLAG.
#:
#: MEASURED: `reset_dependency_check` writes
#: ``'skipped': [{'file': fp, 'reason': rsn} for fp, rsn in skipped[:50]]`` —
#: an ORGANIC #615 transparency list of the synth-output and multi-MB files its
#: scan excluded. Driven for real it answers rc 0 with ``summary['skipped'] ==
#: []``, i.e. it examined the design and skipped nothing. Rule B accused it of
#: losing a skip signal it never had, which is the false-positive shape that
#: gets a checker deleted rather than landed (#439). A container is a
#: POPULATION, not a verdict; only a scalar can be the gate's own yes/no.
_NON_FLAG_VALUE_NODES = (ast.List, ast.ListComp, ast.Dict, ast.DictComp,
                         ast.Set, ast.SetComp, ast.Tuple, ast.GeneratorExp,
                         ast.JoinedStr)


def _is_flag_shaped(value: ast.AST) -> bool:
    if isinstance(value, _NON_FLAG_VALUE_NODES):
        return False
    if isinstance(value, ast.Constant):
        return value.value is True
    return True


def _writes_truthy_skipped(tree: ast.Module) -> Optional[int]:
    """Line where the module writes a truthy skip FLAG named `skipped`.

    An explicit `skipped = False` / `"skipped": False` is the gate saying it did
    NOT skip and is not a write for this purpose. A non-constant scalar IS
    counted, because `summary["skipped"] = not blocks` can be either.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                sub_hit = (isinstance(tgt, ast.Subscript)
                           and isinstance(tgt.slice, ast.Constant)
                           and tgt.slice.value == "skipped")
                attr_hit = isinstance(tgt, ast.Attribute) and tgt.attr == "skipped"
                if (sub_hit or attr_hit) and _is_flag_shaped(node.value):
                    return node.lineno
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "skipped" \
                        and _is_flag_shaped(v):
                    return node.lineno
    return None


def _entry_reads_skip(fn: ast.FunctionDef) -> bool:
    """Does the entry consult a skip signal at all?

    Deliberately generous — any mention of the name, or any call into the
    shared router, clears the gate. Rule B can only ever ACCUSE a gate that
    never mentions its own skip flag in the one function that chooses the exit
    code, which is exactly the #515/#521 shape and nothing wider.

    THE SHAPE THIS CANNOT SEE, and the measurement that says leaving it is
    correct: an entry that WRITES ``summary["skipped"] = ...`` itself and then
    returns 0/1 without reading it back would be cleared, because the write
    mentions the name. Counted over every module in ``programs/`` with an entry
    function: **0** have that shape. Tightening the rule to separate writes
    from reads would therefore buy no coverage on this tree and would add a
    second way to be wrong, so it is not done — recorded here rather than left
    as an unexamined "could be stricter".
    """
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id in (
                "skipped", "summary_is_skipped", "exit_code"):
            return True
        if isinstance(node, ast.Attribute) and node.attr in (
                "skipped", "summary_is_skipped", "exit_code"):
            return True
        if isinstance(node, ast.Constant) and node.value == "skipped":
            return True
    return False


def _entry_can_return_two(fn: ast.FunctionDef) -> bool:
    for node in ast.walk(fn):
        term = _terminator(node) if isinstance(node, ast.stmt) else None
        if term is None:
            continue
        rc, routed = _static_rc(term[1])
        if routed or rc == 2:
            return True
    return False


# ---------------------------------------------------------------------------
# The audit
# ---------------------------------------------------------------------------
def analyse_module(path: Path, tier: int) -> Tuple[GateRow, List[Finding]]:
    stem = path.stem
    reason = _TIER_REASON[tier]
    src = path.read_text(encoding="utf-8", errors="ignore")
    row = GateRow(gate=stem, tier=tier, tier_reason=reason, arg_shape="?",
                  entry=None, skip_paths=0, routed_paths=0, unrouted_paths=0,
                  sentinel_only_paths=0)
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        row.unanalysable = f"unparseable: {exc}"
        return row, []
    row.arg_shape = argument_shape(tree, src)

    fn = entry_function(tree)
    if fn is None:
        row.unanalysable = "no module-level entry function"
        row.entry = None
    else:
        row.entry = fn.name

    if stem in _EXCLUDED:
        row.excluded_reason = _EXCLUDED[stem]
        return row, []

    findings: List[Finding] = []
    if fn is None:
        return row, findings

    paths, unresolved = scan_skip_paths(fn)
    row.skip_paths = len(paths)
    for p in paths:
        if p.routed_by:
            row.routed_paths += 1
            if p.sentinel_only:
                row.sentinel_only_paths += 1
        else:
            row.unrouted_paths += 1

    if tier == TIER_NOT_A_GATE:
        return row, findings

    for p in paths:
        if p.routed_by:
            continue
        if _reaches_consumer_by_sentinel(p.token.lstrip("[")) and p.rc == 0:
            msg = (f"declares the vacuous tier as {p.token!r} and exits 0. The "
                   f"consumer matches a LINE-START {_CONSUMER_SENTINEL!r}, so a "
                   f"bracketed token is not read and the step is credited a "
                   f"plain PASS. Route the gate's own (passed, skipped) pair "
                   f"through _vacuous_exit.exit_code().")
            rule = "bracketed-sentinel-unreadable"
        else:
            msg = (f"declares a skip as {p.token!r} and exits {p.rc}. Neither "
                   f"consumer channel fires (rc != 2, no line-start "
                   f"{_CONSUMER_SENTINEL!r}), so the step is credited a plain "
                   f"PASS over a design nothing examined. Route the gate's own "
                   f"(passed, skipped) pair through _vacuous_exit.exit_code().")
            rule = "unrouted-skip-exit"
        findings.append(Finding(gate=stem, rule=rule, lineno=p.lineno,
                                severity="ERROR", message=msg))

    skipped_line = _writes_truthy_skipped(tree)
    if (skipped_line is not None and not _entry_reads_skip(fn)
            and not _entry_can_return_two(fn)):
        findings.append(Finding(
            gate=stem, rule="structured-skip-not-read-back",
            lineno=skipped_line, severity="ERROR",
            message=("writes a truthy `skipped` into its own structured result "
                     "and its entry function never reads it back, so the "
                     "conclusion the gate already reached cannot reach the exit "
                     "code. This is the #515 / #521 shape: read it with "
                     "_vacuous_exit.summary_is_skipped() and route it with "
                     "_vacuous_exit.exit_code().")))
    if unresolved:
        row.unanalysable = (f"{len(unresolved)} skip terminator(s) with an "
                            f"exit expression this check cannot resolve "
                            f"statically (lines {unresolved[:5]})")
    return row, findings


def classify_tier(stem: str, consumed: set) -> int:
    if stem in consumed:
        return TIER_CONSUMED
    if any(stem.endswith(s) for s in _GATE_SHAPED_SUFFIXES):
        return TIER_GATE_SHAPED
    return TIER_NOT_A_GATE


def audit(plugin_root: Path, strict: bool = False,
          inventory: Optional[Dict[str, int]] = None) -> Result:
    programs = plugin_root / "programs"
    res = Result()
    modules = sorted(p for p in programs.glob("*.py")
                     if not p.name.startswith("__"))
    stems = [p.stem for p in modules]
    consumed = set(structural_gate_registry(programs)) | set(
        flow_yaml_programs(plugin_root, stems))

    for path in modules:
        tier = classify_tier(path.stem, consumed)
        row, findings = analyse_module(path, tier)
        res.rows.append(row)
        res.findings.extend(findings)

    in_scope = [r for r in res.rows if r.tier != TIER_NOT_A_GATE]
    measured: Dict[str, int] = {}
    for f in res.findings:
        measured[f.gate] = measured.get(f.gate, 0) + 1
    inv = _UNROUTED_INVENTORY if inventory is None else inventory
    res.ratchet = ratchet(measured, inv)
    res.ratchet["inventory_size"] = len(inv)
    res.ratchet["inventory_paths"] = sum(inv.values())
    res.ratchet["measured_gates"] = len(measured)
    res.ratchet["measured_paths"] = sum(measured.values())
    drift = any(res.ratchet[k] for k in ("new", "grown", "shrunk", "fixed"))
    res.passed = (not res.findings) if strict else (not drift)
    res.summary = {
        "modules_enumerated": len(res.rows),
        "tier1_verdict_consumed": sum(1 for r in res.rows
                                      if r.tier == TIER_CONSUMED),
        "tier2_gate_shaped": sum(1 for r in res.rows
                                 if r.tier == TIER_GATE_SHAPED),
        "tier3_not_a_gate": sum(1 for r in res.rows
                                if r.tier == TIER_NOT_A_GATE),
        "in_scope": len(in_scope),
        "in_scope_with_skip_paths": sum(1 for r in in_scope if r.skip_paths),
        "skip_paths_total": sum(r.skip_paths for r in in_scope),
        "skip_paths_routed": sum(r.routed_paths for r in in_scope),
        "skip_paths_unrouted": sum(r.unrouted_paths for r in in_scope),
        "skip_paths_sentinel_only": sum(r.sentinel_only_paths for r in in_scope),
        # Reported separately because the total is dominated by tier-3 modules
        # that are out of scope anyway; the IN-SCOPE figure is the one that is
        # actually a blind spot, and quoting the big number would overstate it.
        "unanalysable_in_scope": sum(1 for r in in_scope if r.unanalysable),
        "unanalysable_all_tiers": sum(1 for r in res.rows if r.unanalysable),
        "excluded": sum(1 for r in res.rows if r.excluded_reason),
        "arg_shapes": _shape_census(in_scope),
        "skip_vocabulary": list(_SKIP_DECLARATION_TOKENS),
        "consumer_sentinel": _CONSUMER_SENTINEL,
        "sentinel_channel_is_fragile": (
            "channel B survives only in the last 300 characters of "
            "stdout+stderr that _check_program_exit_zero keeps; rc 2 has no "
            "such window, which is why _vacuous_exit gives both"),
    }
    return res


def _shape_census(rows: Sequence[GateRow]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        out[r.arg_shape] = out.get(r.arg_shape, 0) + 1
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_table(res: Result, tiers: Sequence[int]) -> None:
    print(f"{'gate':58s} {'tier':>4s} {'arg-shape':22s} "
          f"{'skip':>4s} {'rout':>4s} {'unro':>4s}  note")
    print("-" * 122)
    for r in res.rows:
        if r.tier not in tiers:
            continue
        note = ""
        if r.excluded_reason:
            note = "EXCLUDED: " + r.excluded_reason.split(".")[0]
        elif r.unanalysable:
            note = "UNANALYSABLE: " + r.unanalysable
        elif r.sentinel_only_paths:
            note = (f"{r.sentinel_only_paths} path(s) rely on the stdout "
                    f"sentinel alone")
        print(f"{r.gate:58s} {r.tier:4d} {r.arg_shape:22s} "
              f"{r.skip_paths:4d} {r.routed_paths:4d} {r.unrouted_paths:4d}  "
              f"{note[:60]}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plugin_root", nargs="?", type=Path, default=_PLUGIN,
                    help="plugin root containing programs/ (default: this "
                         "program's own plugin)")
    ap.add_argument("--json", default=None,
                    help="write the FULL enumeration as JSON ('-' for stdout)")
    ap.add_argument("--table", action="store_true",
                    help="print the full per-gate enumeration table")
    ap.add_argument("--tier", type=int, action="append", default=None,
                    help="restrict --table to these tiers (repeatable)")
    ap.add_argument("--strict", action="store_true",
                    help="FAIL on the whole residual, not just on drift from "
                         "the published inventory — for draining the class")
    args = ap.parse_args(argv)

    root = args.plugin_root
    if not (root / "programs").is_dir():
        print(f"ERROR: no programs/ directory under {root}", file=sys.stderr)
        return 2

    res = audit(root, strict=args.strict)
    payload = {
        "program": res.program,
        "passed": res.passed,
        "mode": "strict" if args.strict else "ratchet",
        "summary": res.summary,
        "ratchet": res.ratchet,
        "findings": [asdict(f) for f in res.findings],
        "enumeration": [asdict(r) for r in res.rows],
    }
    if args.json:
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.json == "-":
            print(text)
        else:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")

    if args.table:
        _print_table(res, args.tier or [TIER_CONSUMED, TIER_GATE_SHAPED,
                                        TIER_NOT_A_GATE])

    if args.json != "-":
        s = res.summary
        print(f"[{'PASS' if res.passed else 'FAIL'}] gate_skip_routing_check: "
              f"{s['modules_enumerated']} module(s) enumerated — "
              f"{s['tier1_verdict_consumed']} verdict-consumed + "
              f"{s['tier2_gate_shaped']} gate-shaped = {s['in_scope']} in "
              f"scope, {s['tier3_not_a_gate']} not-a-gate (out of scope, "
              f"reason recorded)")
        print(f"       {s['skip_paths_total']} skip path(s) in scope: "
              f"{s['skip_paths_routed']} reach a consumer channel "
              f"({s['skip_paths_sentinel_only']} via the fragile stdout "
              f"sentinel only), {s['skip_paths_unrouted']} do not; "
              f"{s['unanalysable_in_scope']} in-scope module(s) unanalysable, "
              f"{s['excluded']} excluded with a written reason")
        print(f"       argument shapes in scope: {s['arg_shapes']} "
              f"— REPORTED, never used to select")
        r = res.ratchet
        print(f"       residual: {r['measured_paths']} unrouted skip path(s) "
              f"in {r['measured_gates']} gate(s); published inventory holds "
              f"{r['inventory_paths']} in {r['inventory_size']}"
              f"{' (STRICT: the whole residual FAILs)' if args.strict else ''}")
        for key, label in (("new", "NOT IN THE INVENTORY"),
                           ("grown", "GREW"),
                           ("shrunk", "SHRANK"),
                           ("fixed", "FIXED")):
            for line in r.get(key, []):
                print(f"  [RATCHET-{label}] {line}")
        if args.strict:
            for f in res.findings:
                print(f"  [{f.severity}] {f.gate}:{f.lineno} ({f.rule}) "
                      f"{f.message}")
    return 0 if res.passed else 1


if __name__ == "__main__":
    sys.exit(main())
