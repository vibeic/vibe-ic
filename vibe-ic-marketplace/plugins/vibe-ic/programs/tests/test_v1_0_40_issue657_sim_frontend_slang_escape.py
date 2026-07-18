"""ORGANIC #657 — reference_tb SIM frontend chain lacks the slang/verilator
escape that the synth path has.

Frontend asymmetry: the synth fallback (_phase2_sv_synth_fallback) is
slang-PREFERRED → sv2v (accepts full SV-2017 incl. SVA sequences), but the
sim/reference_tb path (_iverilog_compile_with_sv_fallback) was iverilog →
sv2v ONLY with NO slang/verilator escape. When a REUSED-IP closure contains
an SVA consecutive-repetition `[*N]` that sv2v cannot lower, the sv2v
pre-pass fails, the runner honestly returns iverilog_g2012 + hard FAIL, and
Step-4 simulation is structurally unreachable — even though the IDENTICAL
RTL synthesises clean via yosys -m slang.

Fix: a shared chip-AGNOSTIC predicate sim_frontend_should_try_verilator
fires ONLY when (sv2v_rc != 0) AND (sv2v.err carries an SVA/sequence/property
parse signature, e.g. the consecutive-repetition `[*` lexer token
`Sym_brack_l_aster`) AND (the RTL text actually carries an SVA keyword) AND
(.sv inputs present). The runner then escapes to verilator
(_verilator_sim_escape) before declaring the honest FAIL. Honesty/NO-LEAK: a
genuine non-assertion defect that merely prints "Parse error" does NOT
trigger the escape, and verilator absence / verilator-also-rejects keeps the
honest iverilog FAIL.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import synth_frontend as SF  # noqa: E402
import design_one_shot_runner as R  # noqa: E402


# the field agent's exact sv2v stderr signature (round-3 reproduction):
SVA_SV2V_ERR = ("prim_alert_sender.sv:306:46: Parse error: unexpected "
                "token [* (Sym_brack_l_aster)")
SVA_RTL = ("module prim_alert_sender;\n"
           "  assert property (@(posedge clk) disable iff (!rst_n)\n"
           "    a |-> b [*3]);\n"
           "endmodule\n")


# ── decision predicate ──────────────────────────────────────────────────────

def test_escape_fires_on_sva_consecutive_repetition():
    should, reason = SF.sim_frontend_should_try_verilator(
        ["aes_pkg.sv", "prim_alert_sender.sv"], 1, SVA_SV2V_ERR, SVA_RTL)
    assert should is True
    assert "verilator" in reason.lower()


def test_escape_fires_on_goto_and_nonconsec_repetition():
    for tok_err, tok_rtl in (("unexpected token [=", "a [=2]"),
                             ("unexpected token [->", "a [->2]")):
        rtl = f"module m; assert property (a {tok_rtl});\nendmodule\n"
        should, _ = SF.sim_frontend_should_try_verilator(
            ["m.sv"], 1, f"m.sv:1: Parse error: {tok_err}", rtl)
        assert should is True, tok_err


# ── NO-LEAK negatives ───────────────────────────────────────────────────────

def test_no_escape_on_genuine_non_assertion_parse_error():
    # A real RTL defect printing "Parse error" but with NO SVA keyword must
    # NOT be escaped — it FAILs honestly.
    rtl = "module m; wire x = ;\nendmodule\n"
    should, reason = SF.sim_frontend_should_try_verilator(
        ["m.sv"], 1, "m.sv:1: Parse error: unexpected token", rtl)
    assert should is False
    assert "genuine defect" in reason.lower() or "no sva" in reason.lower()


def test_no_escape_when_sv2v_converted_cleanly():
    should, reason = SF.sim_frontend_should_try_verilator(
        ["m.sv"], 0, "", SVA_RTL)
    assert should is False
    assert "cleanly" in reason.lower()


def test_no_escape_without_sv_input():
    # plain .v only — sv2v/verilator escape would not help.
    should, _ = SF.sim_frontend_should_try_verilator(
        ["m.v"], 1, SVA_SV2V_ERR, SVA_RTL)
    assert should is False


def test_escape_fires_on_unrecognised_sv2v_phrasing():
    # v1.4.x CONTRACT CHANGE (deliberate — this test previously pinned the bug).
    # The escape used to require sv2v's error PHRASING to match an allow-list
    # containing `Sym_brack_l_aster`, an Alex-generated lexer token name. A
    # rename there silently skipped the whole verilator capability and produced
    # a FALSE FAIL. The decision now reads the OBSERVABLE (sv2v produced no
    # conversion) + the DESIGN PROPERTY (the RTL really does carry SVA), so ANY
    # phrasing — including a missing-include lexer error, which verilator may
    # well resolve since it is given its own -I — reaches the escape.
    # Honesty is unaffected: verilator must still build AND run the TB to its
    # completion marker, so a closure it also rejects still FAILs.
    for err in ("m.sv:1: Could not find file 'macros.svh'",
                "sv2v: m.sv:7:10: syntax error near Sym_bracket_l_asterisk",
                "sv2v: m.sv:2:19: unexpected '[*' in sequence_expr",
                ""):
        should, reason = SF.sim_frontend_should_try_verilator(
            ["m.sv"], 1, err, SVA_RTL)
        assert should is True, f"{err!r} → {reason}"


# ── runner integration: the escape ladder is wired into the SIM path ────────

def test_runner_sim_path_has_verilator_escape_helper():
    # The asymmetry the issue documents: the synth path had slang escapes but
    # the sim path had none. Pin that the sim-path helper now exists and the
    # compile fallback calls it.
    assert hasattr(R, "_verilator_sim_escape")
    src = inspect.getsource(R._iverilog_compile_with_sv_fallback)
    assert "_verilator_sim_escape" in src
    assert "sim_frontend_should_try_verilator" in src


def test_verilator_escape_returns_honest_fail_when_unavailable(tmp_path):
    # When verilator is not in the container (or docker absent), the escape
    # returns the honest iverilog_g2012 frontend, never a forged PASS.
    # _tool_in_container will return False on a non-existent container.
    rc, out, err, fe = R._verilator_sim_escape(
        rtl_files=[tmp_path / "m.sv"], tb_path=tmp_path / "tb.v",
        run_dir=tmp_path, container="vibeic-nonexistent-container-657",
        top_name="m", reason="test")
    assert fe == "iverilog_g2012"
    assert rc != 0
