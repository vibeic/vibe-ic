#!/usr/bin/env python3
"""#492 — the P0 umbrella's ONE argv shape, and rc 2's two meanings.

THE DEFECT. `flow_compliance_check`'s P0 umbrella called all 241 registered
structural gates with a single argv shape, `[sys.executable, <gate>.py,
<project>]`, and classified `rc == 2` as a skip. The repo documents rc 2 as
"the input-missing skip" — a verdict FROM the gate meaning "the artefact I audit
does not exist yet". But rc 2 is ALSO argparse's exit code for rejecting a
command line, which is a defect in the CALLER and no verdict at all.

MEASURED at v1.7.68, driving the umbrella's own argv against all 241 registered
gates (0 missing program files), twice — once against an EMPTY directory and
once against a real project carrying RTL and Phase-1 documents. Both runs
selected the SAME 39 gates, which is the proof that this is a property of the
call and not of any project's content:

    argparse rejected the argv                              35
      - missing required option                             26
      - `project` positional not accepted at all             7
      - missing required positional (`reference_dir`)        1
      - unsatisfied mutually-exclusive group                 1
    hand-rolled rejection naming an option not supplied       4
    ------------------------------------------------------------
    never validly invoked                                   39

The 4 that only the second rule catches are `mask_application_check`,
`payload_bit_position_check`, `periodic_signal_required_check` and
`fpga_async_input_synchronizer_check`. Each was confirmed BY READING ITS SOURCE
to take the value it needs only from a flag — `_resolve_top(qsf, top)` in the
last one never consults the project root even though `--project` is parsed — so
under the umbrella's argv they return rc 2 whatever the project contains.

`l9_completeness_check` is the sharpest case: a registered L9 declarative gate
that has never examined an L9 document in the flow, because the umbrella never
passed `--l9-file`.

WHY THE OBVIOUS FIX IS A TRAP. Repairing an argv alone converts a silent skip
into a universal FAIL. Re-derived here independently, driving `audit_l9` as a
PURE function over all 196 tracked L9 documents: it returns >= 1 ERROR on
196/196 (`registers` 196/196, `internal_wires` 190, `top_level_ports` 166,
`submodules` 160) while its declared escape hatch `no_registers` /
`registers_not_applicable` is set by 0 of 196. That is over-claiming, and it is
the shape v1.7.60 rejected. So both halves have to move together, and where they
cannot, the gate stays unconverted AND DISCLOSED.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _gate_invocation as GI  # noqa: E402


def _load_flow():
    spec = importlib.util.spec_from_file_location(
        "fcc_issue492", PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fcc_issue492"] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load_flow()


# ── the classifier: rc 2's two meanings ──────────────────────────────────────

def test_argparse_rejection_is_not_a_skip():
    """argparse's own rejection protocol is recognised as a CALLER defect."""
    stderr = ("usage: l9_completeness_check.py [-h] --l9-file L9_FILE\n"
              "l9_completeness_check.py: error: the following arguments are "
              "required: --l9-file\n")
    why = GI.classify_not_invocable("", stderr, supplied_flags=[])
    assert why is not None
    assert "--l9-file" in why


def test_input_missing_skip_stays_a_skip():
    """The documented rc-2 convention must NOT be reclassified. A gate that
    looked and found no input is a benign skip and stays one."""
    for stdout in ("[SKIP] l8_clock_domains_typed_check: single-clock topology",
                   "SKIP — no generated_docs/ in project",
                   "verdict: SKIP (no analog blocks)",
                   "error: no .v/.sv/.vh files under /tmp/x"):
        assert GI.classify_not_invocable(stdout, "", supplied_flags=[]) is None


def test_option_the_caller_did_supply_is_the_gates_verdict_not_a_caller_bug():
    """Rule B is scoped by what was actually passed. If the caller DID supply
    the option, a complaint mentioning it is the gate's verdict about the
    VALUE — misreading that as a caller defect would silence a real finding."""
    line = "error: no masks supplied (--masks or --mask)"
    assert GI.classify_not_invocable("", line, supplied_flags=[]) is not None
    assert GI.classify_not_invocable(
        "", line, supplied_flags=["--masks"]) is None


def test_sentinel_separates_the_two_populations():
    assert GI.is_not_invocable_entry(f"g ({GI.NOT_INVOCABLE_SENTINEL}: why)")
    assert not GI.is_not_invocable_entry("l8_clock_domains_typed_check")


# ── the argv builder: tests drive the REAL construction path ─────────────────

def test_default_shape_is_the_project_positional(tmp_path):
    """Pinned so the historical shape cannot drift silently. This drives
    `_structural_gate_argv` — the function the umbrella itself calls — not a
    re-typed literal, which would agree with the umbrella only by coincidence."""
    argv = F._structural_gate_argv("crc_completeness_check", tmp_path)
    assert argv[0] == sys.executable
    assert argv[1].endswith("crc_completeness_check.py")
    assert argv[2:] == [str(tmp_path)]


def test_strict_timing_still_reaches_only_the_provenance_gate(tmp_path):
    with_flag = F._structural_gate_argv(
        "provenance_output_hash_completeness_check", tmp_path,
        strict_timing=True)
    assert with_flag[-1] == "--strict-timing"
    other = F._structural_gate_argv("crc_completeness_check", tmp_path,
                                    strict_timing=True)
    assert "--strict-timing" not in other


# ── the umbrella: a never-invoked gate is no longer a benign skip ────────────

def _project_with_rtl(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top(input clk, input rst_n, output reg q);\n"
        "  always @(posedge clk) if (!rst_n) q <= 1'b0; else q <= ~q;\n"
        "endmodule\n")
    return tmp_path


def test_umbrella_closes_the_never_invoked_population(tmp_path):
    """#1968 turns every historical parser silence into a verdict or N/A."""
    proj = _project_with_rtl(tmp_path)
    records = []
    _passed, _fails, skips, _waivers = F._run_structural_rtl_gates(
        proj, records_out=records)
    not_invoked = [s for s in skips if GI.is_not_invocable_entry(s)]
    assert not_invoked == []
    assert not [r for r in records if r["verdict"] == "NOT_INVOCABLE"]
    l9 = next(r for r in records if r["name"] == "l9_completeness_check")
    assert l9["verdict"] == "SKIP"
    assert l9["evidence"]["skip_kind"] == "declaration-not-present"


def test_derived_na_gates_do_not_become_failures(tmp_path):
    """A missing design declaration is named N/A, never blamed as a FAIL."""
    proj = _project_with_rtl(tmp_path)
    records = []
    _passed, fails, _skips, _waivers = F._run_structural_rtl_gates(
        proj, records_out=records)
    derived_na = {r["name"] for r in records
                  if r["evidence"].get("skip_kind") ==
                  "declaration-not-present"}
    assert derived_na
    for f in fails:
        for gate in derived_na:
            assert gate not in f, f"derived-N/A gate {gate} leaked into fails"


# ── the measurement that licenses each conversion, and each refusal ──────────

def test_the_l9_trap_is_still_a_trap():
    """Re-derived, not taken on trust: `audit_l9` over every tracked L9 doc.
    While this holds, converting `l9_completeness_check`'s argv would redden
    the entire corpus, so it stays disclosed instead."""
    repo = PROGRAMS.parents[3]
    bench = repo / "benchmark-data"
    if not bench.is_dir():
        pytest.skip("benchmark-data corpus not present in this checkout")
    tracked = subprocess.run(["git", "ls-files", "benchmark-data"], cwd=repo,
                             capture_output=True, text=True).stdout.splitlines()
    l9_docs = [repo / f for f in tracked
               if Path(f).name.startswith("L9_") and f.endswith(".json")]
    if not l9_docs:
        pytest.skip("no tracked L9 documents")
    spec = importlib.util.spec_from_file_location(
        "l9c_issue492", PROGRAMS / "l9_completeness_check.py")
    l9c = importlib.util.module_from_spec(spec)
    sys.modules["l9c_issue492"] = l9c
    spec.loader.exec_module(l9c)

    errored = 0
    escape_hatch = 0
    for p in l9_docs:
        findings, _summary = l9c.audit_l9(p)          # PURE function, read-only
        if any(getattr(f, "severity", "") == "ERROR" for f in findings):
            errored += 1
        try:
            data = json.loads(p.read_text())
        except Exception:
            data = {}
        if isinstance(data, dict) and (data.get("no_registers")
                                       or data.get("registers_not_applicable")):
            escape_hatch += 1
    assert errored == len(l9_docs), (
        f"l9 trap changed: {errored}/{len(l9_docs)} error — if this is now "
        f"below the denominator, re-open the conversion decision")
    assert escape_hatch == 0, (
        f"{escape_hatch}/{len(l9_docs)} now set the escape hatch")
    assert "l9_completeness_check" not in F._STRUCTURAL_GATE_ARGV_ADAPTERS


# Group B — arguments the umbrella CANNOT supply, because they are per-design
# VALUES rather than paths derivable from a project root. Passing a guess would
# manufacture a verdict, so these are not conversion candidates at all. They are
# recorded here because a registered gate that can never be invoked is a
# standing claim the umbrella cannot honour; the options are to remove them from
# `_STRUCTURAL_RTL_GATES` with the reason recorded, or to give the project a way
# to DECLARE the parameters. Both are follow-up work; what this round owes them
# is that their silence is now visible instead of benign.
_UNSUPPLIABLE_BY_UMBRELLA = {
    "crc_bitorder_check": "--crc-signal is a per-design signal name",
    "crc_seed_consistency_check": "--vectors-json is a per-design oracle file",
    "protocol_gap_check": "--end-signal/--bus-idle/--min-cycles are per-design",
    "tristate_bus_check": "--bus-name/--drivers are per-design signal names",
    "mask_application_check": "--masks is a per-design mask manifest",
    "payload_bit_position_check": "--bitmap is a per-design bit map",
    "periodic_signal_required_check": "--periodic is a per-design manifest",
}


def test_group_b_gates_are_registered_but_can_never_be_invoked():
    """Documents the standing contradiction rather than papering over it: these
    are registered as structural gates, and no project-root-derived argv can
    ever satisfy them."""
    for gate in _UNSUPPLIABLE_BY_UMBRELLA:
        assert gate in F._STRUCTURAL_RTL_GATES, (
            f"{gate} left the registry — update this record")
        assert gate not in F._STRUCTURAL_GATE_ARGV_ADAPTERS, (
            f"{gate} needs a per-design VALUE; the umbrella must not guess it")
