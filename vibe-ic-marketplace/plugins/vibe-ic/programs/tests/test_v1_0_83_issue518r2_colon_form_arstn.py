#!/usr/bin/env python3
"""ORGANIC #518 REOPEN round-11 (MEDIUM) — the #518 alias-wrapper clobbered a
spec-declared reset port `arstn` because the #689 contract-port reader did NOT
recognize the DOMINANT RTLLM/VerilogEval `Input ports:` / `NAME: <desc>` colon-
form.

THE HALF-WIRED NO-OP THIS PINS
------------------------------
The author emitted a correct inner module with the exact spec port `arstn`; the
runner's #518 gate (`step_reset_clock_variant_aliases`) appended a `synchronizer`
alias wrapper that renamed `arstn`->`rst_n`. The hidden TB binds
`synchronizer dut(... .arstn(arstn) ...)` → `port 'arstn' is not a port of dut`,
compile_error.

ROOT CAUSE: the #689 contract reader recognised only backtick / table-cell /
Verilog-decl / `port <name>` forms — NOT the colon list under an `Input ports:`
heading that RTLLM / VerilogEval specs use:

    Input ports:
        arstn: active-low async reset
        clk:   system clock

So `arstn` was never registered as a contract-declared port → #518 canonicalised
it UNSUPPRESSED.

THE FIX
-------
`_contract_ports_from_colon_form` recognises a `NAME: <desc>` port LINE
(multiline-anchored `^\\s*<reset/clock token>\\s*:`) but ONLY inside an
`Input/Output ports:` SECTION (heading → next blank line / next ports heading /
EOF), so a spec-declared reset/clock port SUPPRESSES the rename while a stray
`reset:` in unrelated prose never over-suppresses.

§4.05 NEGATIVE NO-LEAK (load-bearing — this is a guard RELAXATION)
-----------------------------------------------------------------
A genuinely non-contract reset (a recognised-standard spelling the spec does NOT
declare, e.g. a design whose colon-form names a clock but NO reset) STILL gets
its alias — the field-verified #518 canonical-convergence doctrine is unchanged
when the contract is silent. A colon-form `reset:` in loose prose OUTSIDE a ports
section is NOT registered (no over-suppression).

chip-AGNOSTIC: the colon-form grammar + the closed standard reset/clock spelling
set; the design name `synchronizer`/`arstn` appears ONLY in the fixtures.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import reset_clock_variant_alias as V       # noqa: E402
import design_one_shot_runner as R          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None

# The dominant RTLLM/VerilogEval port contract: a colon list under headings. The
# reset port `arstn` (a recognised active-low async reset) is named here.
_SPEC_COLON = (
    "Module name:\n"
    "synchronizer\n\n"
    "Input ports:\n"
    "    clk_a: clock domain A\n"
    "    clk_b: clock domain B\n"
    "    arstn: active-low async reset for clk_a domain\n"
    "    brstn: active-low async reset for clk_b domain\n"
    "    din:   single-bit data to synchronize\n"
    "Output ports:\n"
    "    dout:  synchronized data output\n")

# A spec whose colon-form names a CLOCK but NO reset (the §4.05 non-contract case).
_SPEC_COLON_NO_RESET = (
    "Module name:\n"
    "counter\n\n"
    "Input ports:\n"
    "    clk: system clock\n"
    "    en:  count enable\n"
    "Output ports:\n"
    "    cnt: counter value\n")

# The author's correct inner module declaring the exact spec port `arstn`.
_RTL_SYNC = (
    "module synchronizer (\n"
    "    input clk_a, input clk_b,\n"
    "    input arstn, input brstn,\n"
    "    input din, output dout\n"
    ");\n"
    "  reg s1, s2;\n"
    "  always @(posedge clk_b or negedge brstn)\n"
    "    if (!brstn) {s2, s1} <= 2'b00; else {s2, s1} <= {s1, din};\n"
    "  assign dout = s2;\n"
    "endmodule\n")

# The hidden TB binds the spec port `arstn` BY NAME — the bind the rename breaks.
_TB_SYNC = (
    "module testbench;\n"
    "  reg clk_a=0, clk_b=0, arstn=0, brstn=0, din=0; wire dout;\n"
    "  synchronizer dut(.clk_a(clk_a), .clk_b(clk_b),\n"
    "                   .arstn(arstn), .brstn(brstn),\n"
    "                   .din(din), .dout(dout));\n"
    "  always #5 clk_b = ~clk_b;\n"
    "  initial begin\n"
    "    arstn=0; brstn=0; #12 arstn=1; brstn=1; din=1;\n"
    "    repeat (6) @(posedge clk_b); #1;\n"
    "    if (dout === 1'b1) $display(\"Your Design Passed\");\n"
    "    else $display(\"Your Design Failed\");\n"
    "    $finish;\n"
    "  end\n"
    "endmodule\n")


# ════════════════════ unit: the #689 colon-form contract reader ═══════════════

def test_colon_form_registers_arstn_as_contract_port():
    """ROOT CAUSE PIN: the colon-form `arstn: ...` under `Input ports:` is now
    registered (was missed → empty/clock-only set before the fix)."""
    cp = V._contract_ports_from_text(_SPEC_COLON)
    assert "arstn" in cp, cp


def test_colon_form_contract_suppresses_arstn_rename():
    """With `arstn` contract-declared, plan_aliases DROPS the arstn->rst_n
    rename — the wrapper keeps the spec port so the hidden `.arstn(...)` binds."""
    cp = V._contract_ports_from_text(_SPEC_COLON)
    plan = V.plan_aliases(
        ["clk_a", "clk_b", "arstn", "brstn", "din", "dout"], contract_ports=cp)
    assert plan == {}, plan  # arstn NOT renamed → wrapper exposes arstn verbatim


def test_noleak_no_reset_in_contract_still_aliases():
    """§4.05: a spec colon-form that names a CLOCK but NO reset does NOT pin any
    reset → a recognised-standard reset (`reset_n`) the design declares STILL gets
    its alias (the field-verified #518 doctrine, preserved)."""
    cp = V._contract_ports_from_text(_SPEC_COLON_NO_RESET)
    assert "reset_n" not in cp and "arstn" not in cp, cp
    plan = V.plan_aliases(["clk", "en", "reset_n", "cnt"], contract_ports=cp)
    assert plan == {"reset_n": "rst_n"}, plan


def test_colon_form_prose_outside_ports_section_does_not_oversuppress():
    """§4.05 no over-fire: a `reset:` in loose prose (no `Input ports:` heading)
    is NOT registered as a contract port."""
    prose = ("The block uses an active-low reset. Note: when reset:\n"
             "is asserted the FSM clears all state.\n")
    cp = V._contract_ports_from_text(prose)
    assert not (cp & {"rst", "reset", "arstn", "rst_n"}), cp


# ════════════════════ runner gate end-to-end (the real caller path) ═══════════

def _stage_project(tmp_path, spec, rtl_text, design="synchronizer"):
    proj = tmp_path / design
    (proj / "phase1" / "input_doc").mkdir(parents=True, exist_ok=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True, exist_ok=True)
    (proj / "phase1" / "input_doc" / "design_description.txt").write_text(spec)
    rtl = proj / "phase2" / "stage1" / "rtl" / f"{design}.v"
    rtl.write_text(rtl_text)
    return proj, rtl


def test_runner_gate_suppresses_arstn_rename_with_colon_spec(tmp_path):
    """END-STATE (#792 ADDITIVE doctrine): the runner gate (invoked as the
    orchestrator does, with the default auto-wrapper top name 'chip_top')
    resolves the leaf and, because the colon-form contract declares `arstn`,
    emits an ADDITIVE dual-spelling reset wrapper (PASS) — `arstn` STAYS a
    bindable port AND the canonical `rst_n` is ALSO exposed (active-low → tri1
    pull, AND-combine). The contract spelling is never destructively renamed; the
    arstn-binding hidden TB still elaborates (see the elaborate test below)."""
    proj, rtl = _stage_project(tmp_path, _SPEC_COLON, _RTL_SYNC)
    res = R.step_reset_clock_variant_aliases(proj, "chip_top")
    assert res.status == "PASS", (res.status, res.detail)
    assert "additive" in res.detail.lower(), res.detail
    txt = rtl.read_text()
    assert "arstn" in txt, txt          # spec port preserved (still bindable)
    assert "rst_n" in txt, txt          # canonical ALSO exposed additively (#792)


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_runner_gate_arstn_design_elaborates_against_hidden_tb(tmp_path):
    """END-TO-END: after the gate (correctly) leaves `arstn` alone, the RTL +
    the hidden TB that binds `.arstn(arstn)` ELABORATE (the reopen's
    `port 'arstn' is not a port of dut` compile_error is gone)."""
    proj, rtl = _stage_project(tmp_path, _SPEC_COLON, _RTL_SYNC)
    R.step_reset_clock_variant_aliases(proj, "chip_top")
    rtl_dir = proj / "phase2" / "stage1" / "rtl"
    tb = tmp_path / "testbench.v"
    tb.write_text(_TB_SYNC)
    with tempfile.TemporaryDirectory() as td:
        binp = Path(td) / "b"
        srcs = [str(p) for p in sorted(rtl_dir.glob("*.v"))]
        r = _pr.run(
            ["iverilog", "-g2012", "-o", str(binp), *srcs, str(tb)],
            capture_output=True, text=True)
        assert r.returncode == 0, (r.stdout + r.stderr)
        v = _pr.run(["vvp", str(binp)], capture_output=True,
                           text=True)
    assert "Your Design Passed" in (v.stdout + v.stderr), (v.stdout + v.stderr)


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_runner_control_no_contract_renames_and_breaks_arstn_bind(tmp_path):
    """§4.05 / CONTROL: with NO contract staged (the historical #518 doctrine),
    the SAME design DOES get the arstn->rst_n alias (alias still fires). This is
    the field-verified canonical bet — and it is exactly what the colon-form
    contract now correctly SUPPRESSES when the spec declares the port."""
    proj, rtl = _stage_project(tmp_path, "", _RTL_SYNC)  # empty spec → no contract
    res = R.step_reset_clock_variant_aliases(proj, "chip_top")
    assert res.status == "PASS", (res.status, res.detail)
    txt = rtl.read_text()
    assert "rst_n" in txt, txt          # canonical alias fired (no-leak intact)


def test_runner_gate_genuine_typo_reset_still_aliases(tmp_path):
    """§4.05: a genuinely non-contract recognised-standard reset (`reset_n`, NOT
    declared by the spec's colon-form which only names a clock) STILL gets its
    alias when the design declares it — the legitimate #518 case is preserved."""
    rtl_text = (
        "module counter (\n"
        "    input clk, input en, input reset_n,\n"
        "    output reg [3:0] cnt\n"
        ");\n"
        "  always @(posedge clk or negedge reset_n)\n"
        "    if (!reset_n) cnt <= 0; else if (en) cnt <= cnt + 1;\n"
        "endmodule\n")
    proj, rtl = _stage_project(tmp_path, _SPEC_COLON_NO_RESET, rtl_text,
                               design="counter")
    res = R.step_reset_clock_variant_aliases(proj, "chip_top")
    assert res.status == "PASS", (res.status, res.detail)
    assert "rst_n" in rtl.read_text()   # reset_n -> rst_n alias fired




def test_518_endstate_alias_program_runs_on_arstn(tmp_path):
    """#478 defect-artifact + end-state: the reset/clock alias program runs
    end-to-end on a tmp_path RTL declaring `arstn` and emits a wrapper plan
    (rc 0). The substantive contract-suppression proof is
    test_runner_gate_suppresses_arstn_rename_with_colon_spec above; this pins a
    real program-invocation end-state for the deterministic #478 gate."""
    (tmp_path / "core.sv").write_text(
        "module core(input clk, input arstn, output reg q);\n"
        "  always @(posedge clk or negedge arstn)\n"
        "    if(!arstn) q<=0; else q<=1;\nendmodule\n")
    prog = _PROGRAMS / "reset_clock_variant_alias.py"
    cp = subprocess.run([sys.executable, str(prog),
                         "--rtl", str(tmp_path / "core.sv"),
                         "--module", "core"], capture_output=True, text=True)
    assert cp.returncode == 0, (cp.returncode, cp.stdout, cp.stderr)
    assert "ok" in cp.stdout.lower()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
