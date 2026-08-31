"""ORGANIC #1956 — `step_full_stack_tb_gen` CLOBBERED the functional TB the
skeleton itself asks for.

The step ended with an UNCONDITIONAL `tb_path.write_text(...)` on
`phase2/stage1/sim_full_stack/tb_<top>_full.v`. That file is a
connectivity-only skeleton (drives no functional stimulus; measured 9.09%
line / 0% toggle on u_hawaii_adc) and the functional body is explicitly the
author's residual — so every enhancement was silently reverted to the 9%
skeleton on the NEXT runner invocation. `coverage_closure` (80% goal) could
therefore never stay closed through the very rerun that measures it, and the
step-4 FAIL cascaded to the downstream chain.

Fix: regenerate ONLY when
  (a) no TB exists,
  (b) the TB on disk is a VERBATIM skeleton this generator stamped (its
      self-digest still matches — an in-place edit breaks it), or
  (c) the DUT INTERFACE CONTRACT changed — with a LOUD notice and the
      superseded file kept.
An author/AI TB that satisfies or EXTENDS the contract survives every rerun.

RED before the fix: (a) the enhanced TB comes back as the skeleton;
(c) the regeneration carries no notice and destroys the prior file.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402
import _path_layout as _pl  # noqa: E402


_WRAPPER = """\
module proj_wrapper (
    input  wire clk,
    input  wire rst_n,
    output wire [7:0] dout
);
    reg [7:0] q;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) q <= 8'h00; else q <= q + 1'b1;
    assign dout = q;
endmodule
"""

# The same wrapper after a REAL interface change: one added input pin.
_WRAPPER_V2 = """\
module proj_wrapper (
    input  wire clk,
    input  wire rst_n,
    input  wire enable,
    output wire [7:0] dout
);
    reg [7:0] q;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) q <= 8'h00; else if (enable) q <= q + 1'b1;
    assign dout = q;
endmodule
"""

# What an author/AI writes on top of the skeleton: real clocking, real
# checking, extra tasks — and the SAME DUT binding. This is the artefact the
# whole issue is about; it must survive a rerun byte-for-byte.
_ENHANCED_TB = """\
// Functional full-stack TB — authored on top of the generated skeleton.
`timescale 1ns / 1ps
module tb_proj_wrapper_full;
  reg clk = 0;
  reg rst_n = 0;
  wire [7:0] dout;
  integer errors = 0;
  integer i;

  always #10 clk = ~clk;   // the skeleton drives no clock; this one does

  proj_wrapper u_dut (
    .clk(clk),
    .rst_n(rst_n),
    .dout(dout)
  );

  task check_eq;
    input [7:0] got;
    input [7:0] exp;
    begin
      if (got !== exp) errors = errors + 1;
    end
  endtask

  initial begin
    rst_n = 0; repeat (4) @(posedge clk);
    rst_n = 1;
    for (i = 0; i < 64; i = i + 1) begin
      @(posedge clk);
      check_eq(dout, i[7:0] + 8'h01);
    end
    $display("FULL_STACK_TB_DONE errors=%0d", errors);
    $finish;
  end
endmodule
"""


def _scaffold(tmp_path, rtl=_WRAPPER, ports=None):
    proj = tmp_path / "proj"
    rtl_dir = _pl.rtl_dir(proj)
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "proj_wrapper.v").write_text(rtl)
    gd = _pl.generated_docs_dir(proj)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "proj_wrapper",
        "top_ports": ports if ports is not None else [
            {"name": "clk", "direction": "input"},
            {"name": "rst_n", "direction": "input"},
            {"name": "dout", "direction": "output", "width": 8},
        ],
    }))
    return proj


def _tb(proj):
    return _pl.sim_full_stack_dir(proj) / "tb_proj_wrapper_full.v"


# ── (a) an enhanced TB present → the rerun PRESERVES it ────────────────────

def test_enhanced_tb_survives_rerun(tmp_path):
    proj = _scaffold(tmp_path)
    res1 = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert res1.status in ("PASS", "SKIP"), res1.detail
    tb = _tb(proj)
    assert tb.is_file()

    # The author closes coverage by replacing the skeleton with a real TB.
    tb.write_text(_ENHANCED_TB)

    res2 = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert res2.status in ("PASS", "SKIP"), res2.detail
    # THE defect: this used to come back as the 9%-coverage skeleton.
    assert tb.read_text() == _ENHANCED_TB, \
        "the enhanced full-stack TB was CLOBBERED by the rerun (#1956)"
    assert (res2.extras or {}).get("v1956_tb_action") == "preserved"
    assert "PRESERVED" in res2.detail
    # …and it keeps surviving, run after run.
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert tb.read_text() == _ENHANCED_TB


def test_preserved_tb_is_not_reported_as_emitted_by_this_step(tmp_path):
    """A preserved TB was NOT authored by this step; the detail must not
    claim it was (an honest record is the point of the whole guard)."""
    proj = _scaffold(tmp_path)
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    _tb(proj).write_text(_ENHANCED_TB)
    res = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert "PRESERVED (not re-emitted)" in res.detail
    assert "_full.v emitted" not in res.detail


def test_enhanced_tb_that_extends_the_contract_survives(tmp_path):
    """EXTENDING the skeleton (extra instances / extra binds of its own) is
    not a contract violation — a scoreboard or BFM instance must not make the
    generator think the DUT interface changed."""
    proj = _scaffold(tmp_path)
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    extended = _ENHANCED_TB.replace(
        "  task check_eq;",
        "  wire mon_busy;\n"
        "  some_scoreboard u_sb (.clk(clk), .dout(dout), .busy(mon_busy));\n"
        "  task check_eq;")
    _tb(proj).write_text(extended)
    res = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert _tb(proj).read_text() == extended
    assert (res.extras or {}).get("v1956_tb_action") == "preserved"


# ── (b) no TB → the rerun GENERATES the skeleton ───────────────────────────

def test_absent_tb_is_generated(tmp_path):
    proj = _scaffold(tmp_path)
    tb = _tb(proj)
    assert not tb.exists()
    res = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert res.status in ("PASS", "SKIP"), res.detail
    txt = tb.read_text()
    assert "module tb_proj_wrapper_full;" in txt
    assert "proj_wrapper u_dut (" in txt
    assert (res.extras or {}).get("v1956_tb_action") == "generated"

    # A DELETED TB is regenerated too — preservation must not become a way to
    # lose the TB entirely.
    tb.unlink()
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert tb.is_file() and "proj_wrapper u_dut (" in tb.read_text()


def test_untouched_skeleton_is_still_refreshed(tmp_path):
    """NO-REGRESSION: an unedited skeleton stays regenerable — preservation
    must not pin a stale skeleton that the generator itself owns."""
    proj = _scaffold(tmp_path)
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert R._v1956_is_verbatim_skeleton(_tb(proj).read_text())
    res = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert (res.extras or {}).get("v1956_tb_action") in (
        "unchanged", "regenerated")


# ── (c) interface contract changed → REGENERATED, with a notice ────────────

def test_interface_change_regenerates_with_notice(tmp_path):
    proj = _scaffold(tmp_path)
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    tb = _tb(proj)
    tb.write_text(_ENHANCED_TB)

    # The DUT grows a pin the enhanced TB cannot bind.
    (_pl.rtl_dir(proj) / "proj_wrapper.v").write_text(_WRAPPER_V2)
    gd = _pl.generated_docs_dir(proj) / "L9_INTEGRATION_SPEC.json"
    l9 = json.loads(gd.read_text())
    l9["top_ports"].insert(2, {"name": "enable", "direction": "input"})
    gd.write_text(json.dumps(l9))

    res = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    txt = tb.read_text()
    assert ".enable(enable)" in txt, "the new pin was not picked up"
    assert (res.extras or {}).get("v1956_tb_action") \
        == "regenerated_contract_changed"
    # The notice is the point: a silent overwrite is what #1956 was.
    assert "NOTICE" in res.detail and "contract CHANGED" in res.detail
    assert "enable" in res.detail
    # …and the author's work is kept, not destroyed.
    backup = Path((res.extras or {})["v1956_superseded_tb"])
    assert backup.is_file() and backup.read_text() == _ENHANCED_TB
    # The backup must not masquerade as a full-stack TB to any consumer.
    assert not list(_pl.sim_full_stack_dir(proj).glob("tb_*_full.v")) \
        == [backup]
    assert backup.parent != _pl.sim_full_stack_dir(proj)


def test_foreign_tb_not_instantiating_the_dut_is_regenerated(tmp_path):
    """A file at that path that does not instantiate the DUT at all cannot be
    the full-stack TB — regenerate (and keep the file)."""
    proj = _scaffold(tmp_path)
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    _tb(proj).write_text("module tb_proj_wrapper_full;\nendmodule\n")
    res = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert (res.extras or {}).get("v1956_tb_action") \
        == "regenerated_contract_changed"
    assert "proj_wrapper u_dut (" in _tb(proj).read_text()
    assert Path((res.extras or {})["v1956_superseded_tb"]).is_file()


def test_force_regen_escape_hatch(tmp_path, monkeypatch):
    proj = _scaffold(tmp_path)
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    _tb(proj).write_text(_ENHANCED_TB)
    monkeypatch.setenv("VIBE_IC_TB_FORCE_REGEN", "1")
    res = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert (res.extras or {}).get("v1956_tb_action") == "regenerated_forced"
    assert "proj_wrapper u_dut (" in _tb(proj).read_text()
    assert "NOTICE" in res.detail


# ── unit: the stamp and the contract parse ────────────────────────────────

def test_stamp_detects_any_in_place_edit():
    lines = ["// header", "`timescale 1ns / 1ps", "module m; endmodule", ""]
    txt = R._v1956_stamped_skeleton(lines)
    assert R._v1956_is_verbatim_skeleton(txt)
    # An in-place enhancement that KEEPS the auto-generated header is still
    # detected — the header comment alone was never proof of authorship.
    assert not R._v1956_is_verbatim_skeleton(
        txt.replace("module m; endmodule",
                    "module m; initial $display(\"x\"); endmodule"))
    # An unstamped file is never "verbatim" (we cannot prove it unedited).
    assert not R._v1956_is_verbatim_skeleton("// header\nmodule m; endmodule")


def test_contract_check_ignores_comments_and_ifdef_regions():
    required = {"clk", "rst_n", "dout"}
    ok, why = R._v1956_contract_check(_ENHANCED_TB, "proj_wrapper", required)
    assert ok, why
    # A commented-out binding is NOT a binding.
    commented = _ENHANCED_TB.replace("    .dout(dout)", "  //  .dout(dout)")
    ok2, why2 = R._v1956_contract_check(commented, "proj_wrapper", required)
    assert not ok2 and "dout" in why2
    # A power pin bound under `ifdef USE_POWER_PINS is CONDITIONAL — it is not
    # a pin "the DUT no longer exposes" (#645 emits exactly this shape).
    powered = _ENHANCED_TB.replace(
        "    .dout(dout)\n",
        "    .dout(dout)\n`ifdef USE_POWER_PINS\n"
        "    , .vccd1(vccd1)\n`endif\n")
    ok3, why3 = R._v1956_contract_check(powered, "proj_wrapper", required)
    assert ok3, why3
    # A stale UNCONDITIONAL bind of a pin the DUT dropped IS a change.
    stale = _ENHANCED_TB.replace("    .dout(dout)",
                                 "    .dout(dout),\n    .gone_pin(1'b0)")
    ok4, why4 = R._v1956_contract_check(stale, "proj_wrapper", required)
    assert not ok4 and "gone_pin" in why4


def test_contract_check_preserves_when_connections_are_positional():
    """Unparseable (positional) connections are not proof of breakage — the
    asymmetry is total, so preserve rather than clobber."""
    positional = _ENHANCED_TB.replace(
        "  proj_wrapper u_dut (\n    .clk(clk),\n    .rst_n(rst_n),\n"
        "    .dout(dout)\n  );",
        "  proj_wrapper u_dut (clk, rst_n, dout);")
    ok, _ = R._v1956_contract_check(positional, "proj_wrapper",
                                    {"clk", "rst_n", "dout"})
    assert ok


# ── the preserved TB is what the downstream gate now reads — say so ────────

def test_preserved_tb_carries_the_bit_level_advisory(tmp_path):
    """A preserved TB is the artefact `bit_level_full_stack_tb_check` reads.
    When the enhancement dropped that gate's bit-level evidence, this step
    must say so LOUDLY — the author should learn it here, not as an opaque
    FAIL several steps downstream. The predicate is the GATE'S OWN (imported,
    never re-implemented)."""
    proj = _scaffold(tmp_path)
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    _tb(proj).write_text(_ENHANCED_TB)   # no pad alias, no bit-time delays
    res = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert (res.extras or {}).get("v1956_tb_action") == "preserved"
    assert (res.extras or {}).get("v1956_bit_level_advisory")
    assert "ADVISORY" in res.detail
    # …and it is an ADVISORY, not a verdict: the gate stays the gate, and the
    # TB is still preserved.
    assert _tb(proj).read_text() == _ENHANCED_TB


def test_preserved_tb_without_the_completion_marker_is_flagged(tmp_path):
    """The step that simulates this TB scores it by the FULL_STACK_TB_DONE
    $display and otherwise reports "possible RTL defect". An enhancement that
    drops the marker must be told so HERE, not blamed on the RTL later."""
    proj = _scaffold(tmp_path)
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    _tb(proj).write_text(_ENHANCED_TB)   # prints FULL_STACK_TB_DONE
    res = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert not any("FULL_STACK_TB_DONE" in a for a
                   in (res.extras or {}).get("v1956_bit_level_advisory", []))
    _tb(proj).write_text(_ENHANCED_TB.replace("FULL_STACK_TB_DONE", "DONE"))
    res2 = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert any("FULL_STACK_TB_DONE" in a for a
               in (res2.extras or {}).get("v1956_bit_level_advisory", []))


def test_no_advisory_when_the_enhanced_tb_keeps_the_bit_level_evidence(
        tmp_path):
    proj = _scaffold(tmp_path)
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    good = _ENHANCED_TB.replace(
        "  integer errors = 0;",
        "  integer errors = 0;\n"
        "  wire id_pin = dout[0];   // single-wire pad alias\n"
        "  localparam integer T_BIT = 1000;\n"
        "  initial begin #T_BIT; end")
    _tb(proj).write_text(good)
    res = R.step_full_stack_tb_gen(proj, "proj_wrapper")
    assert (res.extras or {}).get("v1956_tb_action") == "preserved"
    assert not (res.extras or {}).get("v1956_bit_level_advisory")
    assert "ADVISORY" not in res.detail


def test_skeleton_tells_the_author_the_file_is_theirs_to_extend(tmp_path):
    """The one place an author reliably reads is the file being edited. The
    preservation contract is stated THERE, or it is not stated at all."""
    proj = _scaffold(tmp_path)
    R.step_full_stack_tb_gen(proj, "proj_wrapper")
    head = _tb(proj).read_text().split("`timescale")[0]
    assert "#1956" in head
    assert "FULL_STACK_TB_DONE" in head
    assert "SURVIVES" in head
    assert "CONNECTIVITY-ONLY" in head
    # …and the stamp that makes "unedited" a measurement, not a guess.
    assert R._V1956_STAMP in head
