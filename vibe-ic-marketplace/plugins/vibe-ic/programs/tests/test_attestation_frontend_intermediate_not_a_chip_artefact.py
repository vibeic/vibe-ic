#!/usr/bin/env python3
"""A front-end pre-pass file is a synthesis INPUT, not a chip artefact.

THE DEFECT — `agent_report_sha256_attestation_check` collects canonical
artefacts with `phase2/stage2/synth/*.v` and `phase3/stage3/pnr/*.v`.
That glob asks "is there a .v file in the netlist directory"; the gate
reads the answer as "has this project produced a netlist". They are not
the same question, and the flow's OWN front-end fallback separates them:
when the SV front-end is unavailable the runner writes an sv2v pre-pass
file into the very directory the glob watches
(`design_one_shot_runner`: `synth_dir / f"{synth_top}_sv2v.v"`;
`phase3_one_shot_runner`: `out_dir / f"{top}_sv2v.v"`) and then feeds it
to yosys.

Consequence on a project whose synthesis never completed: the gate finds
1 "canonical artefact", skips its documented `no canonical artefacts ->
pre-output project` escape, and FAILs demanding attestation. The cheapest
way to clear that FAIL is to publish a SHA256 of a pre-synthesis
intermediate under a chip-artefact heading — a rule meant to make reports
verifiable rewarding a report that is falsely verifiable.

BIDIRECTIONAL NEGATIVE CONTROL. The first two tests FAIL against the
byte-identical pre-fix file and pass after. The REVERSE tests must pass
in BOTH directions: they are what proves the fix did not simply tighten
the glob until nothing matched, which would silently stop the gate
demanding attestation for every real netlist in the repo.

THE END-TO-END EXIT CODE IS rc 2, NOT rc 0 — SEE THE LAST TEST. This
file was authored against a gate that returned 0 for `VACUOUS_PASS`;
#834 fixed that half (VACUOUS now routes through
`_vacuous_exit.exit_code(passed=True, skipped=True)`). The two changes
merge with ZERO textual conflict and contradicted each other on exactly
one line. #834 is the side that is right and the reason is recorded on
`test_gate_exits_vacuous_when_only_the_intermediate_is_present` below.
Escaping the FAIL and being counted as an executed PASS are different
outcomes; this file needs the first, and only the first.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import _vacuous_exit as _vx


_PROGRAMS = Path(__file__).resolve().parent.parent
_GATE = _PROGRAMS / "agent_report_sha256_attestation_check.py"

#: Bound for every subprocess launch below, and it is NOT a round number
#: picked by feel. `ci_harness_timeout_ceiling_check` (BLOCKING) resolves the
#: pytest harness bound from `tools/gatekeeper-land.sh` — `--timeout=180`,
#: `--timeout-method=thread` — and permits any one blocking call at most
#: `180 // 3` = 60 s. Above that the inner bound can never fire: pytest reaches
#: 180 s first and takes the whole SESSION down, so `--maxfail` stops counting
#: and every other file in the subset loses its verdict, including files that
#: had already passed. Spelled once, as a named constant, so lowering it is one
#: edit rather than one per call site.
_GATE_TIMEOUT_S = 60


def _load():
    spec = importlib.util.spec_from_file_location(
        "_att_gate_frontend_intermediate", _GATE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


MOD = _load()

# A real gate-level netlist: cell instantiations, no `parameter`, no
# `always`. Content is illustrative only — the gate keys on the name.
_REAL_NETLIST = (
    "module top (clk, rst_n, q);\n"
    "  input clk;\n"
    "  input rst_n;\n"
    "  output q;\n"
    "  wire n1;\n"
    "  INVX1  u1 (.A(clk), .Y(n1));\n"
    "  DFFRX1 u2 (.D(n1), .CK(clk), .RN(rst_n), .Q(q));\n"
    "endmodule\n"
)

# The sv2v pre-pass output: still behavioural RTL. `parameter` and
# `always` are exactly what a gate-level netlist does not have.
_SV2V_INTERMEDIATE = (
    "module top (clk, rst_n, q);\n"
    "  parameter integer WIDTH = 8;\n"
    "  input wire clk;\n"
    "  input wire rst_n;\n"
    "  output reg q;\n"
    "  always @(posedge clk) q <= ~q;\n"
    "endmodule\n"
)

_REPORT_NO_TABLE = "# Final Summary\n\nNo attestation table here.\n"


def _mkproject(tmp_path: Path, files: dict, report: str) -> Path:
    proj = tmp_path / "proj"
    for rel, content in files.items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    rp = proj / "reports" / "final_summary.md"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(report)
    return proj


def _kinds(proj: Path):
    return [k for k, _ in MOD._collect_canonical_artefacts(proj)]


def _names(proj: Path):
    return sorted(p.name for _, p in MOD._collect_canonical_artefacts(proj))


# ── FORWARD: these FAIL against the pre-fix file ─────────────────────

def test_sv2v_prepass_in_synth_dir_is_not_a_canonical_artefact(tmp_path):
    """The measured case: synthesis never ran, only the pre-pass exists.

    PRE-FIX: `_collect_canonical_artefacts` returns 1 ("synth netlist"),
    so the gate skips its pre-output escape and FAILs.
    """
    proj = _mkproject(
        tmp_path,
        {"phase2/stage2/synth/top_sv2v.v": _SV2V_INTERMEDIATE},
        _REPORT_NO_TABLE,
    )
    assert _collect_is_empty(proj), (
        "a project whose only .v in the synth dir is the flow's own sv2v "
        "pre-pass has produced NO chip artefact; it must take the "
        "documented pre-output-project escape, not be told to attest an "
        "input to synthesis")


def _collect_is_empty(proj: Path) -> bool:
    return MOD._collect_canonical_artefacts(proj) == []


def test_sv2v_prepass_in_pnr_dir_is_not_a_canonical_artefact(tmp_path):
    """Same emitter convention, the other *.v glob.

    `phase3_one_shot_runner` writes `{top}_sv2v.v` too, so the PnR glob
    carries the same defect and must get the same treatment.
    """
    proj = _mkproject(
        tmp_path,
        {"phase3/stage3/pnr/top_sv2v.v": _SV2V_INTERMEDIATE},
        _REPORT_NO_TABLE,
    )
    assert _collect_is_empty(proj)


# ── REVERSE CONTROLS: must hold in BOTH directions ───────────────────
#
# Without these, a fix that deleted the two *.v globs outright would
# pass the two tests above while silently stopping the gate from ever
# demanding attestation for a real netlist again.

def test_reverse_real_synth_netlist_is_still_a_canonical_artefact(tmp_path):
    """THE load-bearing reverse case.

    An unattested real netlist must STILL be collected and must STILL
    FAIL. If this ever passes-by-absence the fix has swallowed the rule.
    """
    proj = _mkproject(
        tmp_path,
        {"phase2/stage2/synth/netlist_yosys.v": _REAL_NETLIST},
        _REPORT_NO_TABLE,
    )
    assert _kinds(proj) == ["synth netlist"]
    assert _names(proj) == ["netlist_yosys.v"]


def test_reverse_real_pnr_netlist_is_still_a_canonical_artefact(tmp_path):
    proj = _mkproject(
        tmp_path,
        {"phase3/stage3/pnr/netlist_routed.v": _REAL_NETLIST},
        _REPORT_NO_TABLE,
    )
    assert _kinds(proj) == ["PnR netlist"]


def test_reverse_real_netlist_beside_the_intermediate_still_collected(tmp_path):
    """The mixed case the real flow actually produces.

    After synthesis completes, BOTH files sit in the synth directory.
    The netlist must still be demanded; only the intermediate drops out.
    A fix that keyed on "directory contains an sv2v file" instead of on
    the file itself would wrongly exempt the whole directory here.
    """
    proj = _mkproject(
        tmp_path,
        {
            "phase2/stage2/synth/top_sv2v.v": _SV2V_INTERMEDIATE,
            "phase2/stage2/synth/netlist_yosys.v": _REAL_NETLIST,
        },
        _REPORT_NO_TABLE,
    )
    assert _names(proj) == ["netlist_yosys.v"]


def test_reverse_suffix_is_exact_not_a_substring_search(tmp_path):
    """Scope control: the rule matches the emitters' f-string, nothing more.

    A hand-authored netlist that merely CONTAINS "sv2v" in its name is
    not a name the flow generates, so it keeps requiring attestation.
    This pins the narrowness of the rule so a later widening to
    `"sv2v" in name` is a test failure rather than a silent loss of
    coverage.
    """
    proj = _mkproject(
        tmp_path,
        {
            "phase2/stage2/synth/sv2v_golden_netlist.v": _REAL_NETLIST,
            "phase2/stage2/synth/top_sv2v_reviewed.v": _REAL_NETLIST,
        },
        _REPORT_NO_TABLE,
    )
    assert _names(proj) == ["sv2v_golden_netlist.v", "top_sv2v_reviewed.v"]


def test_reverse_non_verilog_artefact_classes_are_untouched(tmp_path):
    """The fix must not perturb the seven non-*.v globs at all."""
    proj = _mkproject(
        tmp_path,
        {
            "phase2/stage1/fpga/output_files/top.sof": "sof",
            "phase3/stage4/gds/top.gds": "gds",
            "phase3/analog/hardmacro/blk/blk.lef": "lef",
        },
        _REPORT_NO_TABLE,
    )
    assert sorted(_kinds(proj)) == ["FPGA SOF", "analog LEF", "chip GDS"]


def test_reverse_gate_still_exits_1_for_an_unattested_real_netlist(tmp_path):
    """End-to-end reverse control on the EXIT CODE, not just collection.

    The gate's contract is rc 1 for an unattested canonical artefact.
    Asserting the exit code is what proves the gate can still FAIL for
    the reason it exists.
    """
    proj = _mkproject(
        tmp_path,
        {"phase2/stage2/synth/netlist_yosys.v": _REAL_NETLIST},
        _REPORT_NO_TABLE,
    )
    import subprocess
    r = subprocess.run(
        [sys.executable, str(_GATE), str(proj)],
        capture_output=True, text=True, timeout=_GATE_TIMEOUT_S)
    assert r.returncode == 1, (
        f"unattested real netlist must still FAIL; got rc={r.returncode}\n"
        f"{r.stdout}\n{r.stderr}")


def test_gate_exits_vacuous_when_only_the_intermediate_is_present(tmp_path):
    """Forward end-to-end: the measured case, on the exit code.

    PRE-FIX this is rc 1 (the false positive). POST-FIX the project has
    no chip artefact, so the documented pre-output escape applies — and
    that escape is rc 2, not rc 0.

    WHY rc 2 AND NOT rc 0 (this file x #834, decided 2026-08-05)
    -----------------------------------------------------------
    This assertion was authored as `r.returncode == 0`, against a gate
    whose `VACUOUS_PASS` branch returned 0. #834 changed that branch to
    `_vacuous_exit.exit_code(passed=True, skipped=True)` == 2. Both
    changes touch this gate, both merge with no textual conflict, and
    they disagree here and nowhere else.

    #834 wins, established by DRIVING the real umbrella
    (`flow_compliance_check._run_structural_rtl_gates`, which registers
    this gate in `_STRUCTURAL_RTL_GATES`) over this exact fixture — the
    shape of `benchmark-data/ic/ibex`, whose synth dir holds
    `chip_top_sv2v.v`, `sv2v.err`, `yosys.log` and NO netlist because
    synthesis failed:

        rc 0 -> {"verdict": "PASS", "exit_code": 0}
                umbrella executed-PASS count 143
        rc 2 -> {"verdict": "SKIP", "exit_code": 2,
                 "skip_kind": "input-missing"}
                umbrella executed-PASS count 142

    That driver reads the EXIT CODE and nothing else — it never opens
    the JSON report and never scans stdout. So under rc 0 a project that
    produced no chip artefact, and whose report carries zero sha256
    tokens, is credited in the executed-PASS numerator: indistinguishable
    to every automated consumer from a project whose every SOF / GDS /
    netlist is attested and whose hashes all match. That is this file's
    own defect — a rule meant to make reports verifiable rewarding an
    unverifiable one — resurfacing one layer up.

    What this file needs from the fix is that a synthesis INPUT stops
    being demanded as a chip artefact (rc 1 -> not rc 1). It does not
    need, and must not claim, that the project passed. The two forward
    tests above carry that half on their own: they FAIL against the
    byte-identical pre-fix gate whatever the vacuous rc is, because they
    assert on `_collect_canonical_artefacts` and not on an exit code.

    This assertion is now a bidirectional control over BOTH halves —
    revert the glob exclusion and it sees rc 1; revert #834's rc and it
    sees rc 0; only both together give rc 2.
    """
    proj = _mkproject(
        tmp_path,
        {"phase2/stage2/synth/top_sv2v.v": _SV2V_INTERMEDIATE},
        _REPORT_NO_TABLE,
    )
    import subprocess
    r = subprocess.run(
        [sys.executable, str(_GATE), str(proj)],
        capture_output=True, text=True, timeout=_GATE_TIMEOUT_S)
    assert r.returncode == _vx.RC_VACUOUS, (
        f"a pre-output project must not be told to attest a synthesis "
        f"input (rc 1), and must not be credited as an executed PASS "
        f"either (rc 0) — it examined nothing, which is "
        f"rc {_vx.RC_VACUOUS}; got rc={r.returncode}\n"
        f"{r.stdout}\n{r.stderr}")
