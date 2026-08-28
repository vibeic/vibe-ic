"""v0.3.18 — #518: emit reset/clock NAME-VARIANT aliases at chip-top so a design
declaring one standard spelling (reset_n) elaborates against a hidden TB that
instantiates an equivalent standard spelling (.rst_n) — POLARITY PRESERVED.

Acceptance: a design declaring reset_n elaborates against `.rst_n` (same
active-low polarity); an active-HIGH reset must NEVER be aliased to an
active-low name.

chip-AGNOSTIC: only generic reset/clock spelling sets are baked in.
"""
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import reset_clock_variant_alias as V  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── polarity classification ─────────────────────────────────────────────

def test_classify_reset_polarity():
    for lo in ("rst_n", "rstn", "reset_n", "resetn", "nreset", "resetb",
               "arst_n"):
        assert V.classify_reset(lo) == "active_low", lo
    for hi in ("rst", "reset", "areset", "arst"):
        assert V.classify_reset(hi) == "active_high", hi
    for non in ("data", "enable", "id_bus", "foo_n_bar"):
        assert V.classify_reset(non) is None, non


def test_clock_recognition():
    assert V.is_clock("clk") and V.is_clock("clock") and V.is_clock("clk_i")
    assert not V.is_clock("clock_enable") and not V.is_clock("rst")


def test_equivalent_variants_same_polarity_only():
    eq = V.equivalent_variants("reset_n")
    assert "rst_n" in eq                      # same polarity
    assert "rst" not in eq and "reset" not in eq  # active-high excluded
    eq_hi = V.equivalent_variants("reset")
    assert "rst" in eq_hi
    assert "rst_n" not in eq_hi and "reset_n" not in eq_hi


def test_canonical_variant():
    assert V.canonical_variant("reset_n") == "rst_n"
    assert V.canonical_variant("resetb") == "rst_n"
    assert V.canonical_variant("reset") == "rst"
    assert V.canonical_variant("clock") == "clk"
    assert V.canonical_variant("data") is None


# ── deterministic rename policy ─────────────────────────────────────────

def test_plan_aliases_canonicalises_noncanonical():
    plan = V.plan_aliases(["clock", "reset_n", "data", "y"])
    assert plan == {"clock": "clk", "reset_n": "rst_n"}


def test_plan_aliases_skips_already_canonical_and_collisions():
    # clk + rst_n are already canonical → untouched.
    assert V.plan_aliases(["clk", "rst_n", "d"]) == {}
    # if canonical name already exists as another port, skip to avoid dup.
    assert V.plan_aliases(["clk", "reset_n", "rst_n"]) == {}


def test_two_same_polarity_variants_do_not_duplicate_target(tmp_path):
    # ADVERSARIAL-REVIEW REGRESSION (#518): a design declaring TWO non-canonical
    # same-polarity reset names (reset_n AND rstn, both → rst_n) must NOT map
    # both to rst_n — that would emit `input rst_n, input rst_n` (invalid).
    plan = V.plan_aliases(["clk", "reset_n", "rstn", "d"])
    # only ONE of them is canonicalised; the target appears at most once.
    targets = list(plan.values())
    assert targets.count("rst_n") <= 1, plan
    assert len(set(plan.values())) == len(plan.values())  # no duplicate target
    # and the emitted wrapper has unique port names.
    ports = [("input", "", "clk"), ("input", "", "reset_n"),
             ("input", "", "rstn"), ("input", "", "d")]
    wrapper = V.emit_variant_alias_wrapper("core", ports, plan)
    faces = [ln.split()[-1] for ln in wrapper.splitlines()
             if ln.strip().startswith("input ")]
    assert len(faces) == len(set(faces)), f"duplicate wrapper port: {faces}"


def test_emit_rejects_duplicate_face_map():
    # a hand-built rename_map collapsing two ports onto one name is refused.
    ports = [("input", "", "reset_n"), ("input", "", "rstn"),
             ("input", "", "clk")]
    with pytest.raises(ValueError):
        V.emit_variant_alias_wrapper("core", ports,
                                     {"reset_n": "rst_n", "rstn": "rst_n"})


# ── polarity guard — the critical safety property ───────────────────────

def test_cross_polarity_alias_raises():
    ports = [("input", "", "clk"), ("input", "", "reset"),
             ("output", "", "y")]
    with pytest.raises(ValueError):
        # active-HIGH reset → active-low name must be refused.
        V.emit_variant_alias_wrapper("core", ports, {"reset": "rst_n"})
    with pytest.raises(ValueError):
        V.emit_variant_alias_wrapper("core", ports, {"reset": "resetn"})


def test_reset_to_clock_alias_raises():
    ports = [("input", "", "clk"), ("input", "", "reset_n")]
    with pytest.raises(ValueError):
        V.emit_variant_alias_wrapper("core", ports, {"reset_n": "clk"})


def test_plan_never_crosses_polarity():
    # an active-high reset only ever canonicalises to an active-high name.
    plan = V.plan_aliases(["clk", "reset", "y"])
    assert plan.get("reset") == "rst"
    assert V.classify_reset(plan["reset"]) == "active_high"


# ── emit + elaborate against the TB-facing variant ──────────────────────

def _core_rtl(reset_name: str) -> str:
    return (f"module mycore (\n"
            f"    input clk,\n"
            f"    input {reset_name},\n"
            f"    input [3:0] d,\n"
            f"    output reg [3:0] q\n"
            f");\n"
            f"    always @(posedge clk or negedge {reset_name})\n"
            f"        if (!{reset_name}) q <= 4'b0; else q <= d;\n"
            f"endmodule\n")


def test_emit_and_tb_variant_elaborates(tmp_path):
    core_rtl = tmp_path / "core.v"
    core_rtl.write_text(_core_rtl("reset_n"))
    ports = V.parse_module_ports(core_rtl.read_text(), "mycore")
    plan = V.plan_aliases([p[2] for p in ports])
    assert plan == {"reset_n": "rst_n"}
    wrapper = V.emit_variant_alias_wrapper("mycore", ports, plan,
                                           wrapper_name="mycore_top")
    # the wrapper exposes rst_n and wires it to the core's reset_n 1:1.
    assert "input rst_n" in wrapper
    assert ".reset_n(rst_n)" in wrapper
    wrap_f = tmp_path / "mycore_top.v"
    wrap_f.write_text(wrapper)

    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host — structural checks only")
    # a hidden TB instantiating .rst_n (+ .clk) must elaborate.
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb;\n"
        "  reg clk=0, rst_n=0; reg [3:0] d=0; wire [3:0] q;\n"
        "  mycore_top dut(.clk(clk), .rst_n(rst_n), .d(d), .q(q));\n"
        "endmodule\n")
    r = _pr.run(
        [iv, "-g2012", "-s", "tb", "-o", str(tmp_path / "tb.out"),
         str(core_rtl), str(wrap_f), str(tb)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_main_no_alias_when_canonical(tmp_path):
    core_rtl = tmp_path / "core.v"
    core_rtl.write_text(_core_rtl("rst_n"))  # already canonical
    rc = V.main(["--rtl", str(core_rtl), "--module", "mycore"])
    assert rc == 0
    assert not (tmp_path / "mycore_aliased.v").exists()


def test_parameterized_module_ports_parse(tmp_path):
    # REOPEN REGRESSION (#517 fix applied here too): a clocked chip-top is often
    # parameterized; the parser must skip the #(...) block and find the ports.
    rtl = ("module mycore #(parameter W = 8) (\n"
           "  input clk, input reset_n, input [W-1:0] d, output [W-1:0] q\n"
           ");\nendmodule\n")
    ports = V.parse_module_ports(rtl, "mycore")
    assert [p[2] for p in ports] == ["clk", "reset_n", "d", "q"]
    assert V.plan_aliases([p[2] for p in ports]) == {"reset_n": "rst_n"}


# ── REOPEN ROUND-2 REGRESSIONS (#518): wired into the runner (was DORMANT) ──

def _runner():
    import design_one_shot_runner as P
    import _path_layout as _pl
    return P, _pl


def _seq_core(reset_name: str) -> str:
    return (f"module sequence_detector(\n"
            f"    input wire clk,\n"
            f"    input wire {reset_name},\n"
            f"    input wire data_in,\n"
            f"    output reg detected\n"
            f");\n"
            f"    always @(posedge clk or negedge {reset_name})\n"
            f"        if (!{reset_name}) detected <= 1'b0; "
            f"else detected <= data_in;\n"
            f"endmodule\n")


def test_step_wired_binding_repro_elaborates(tmp_path):
    # the #518 reopen binding case: core declares active-low `reset_n`; a hidden
    # TB instantiates `.rst_n`. The runner step must auto-emit a wrapper that
    # TAKES the top name and exposes `rst_n`, so the TB elaborates.
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "sequence_detector.v").write_text(_seq_core("reset_n"))
    r = P.step_reset_clock_variant_aliases(tmp_path, "sequence_detector")
    assert r.status == "PASS", (r.status, r.detail)
    body = (rtl / "sequence_detector.v").read_text()
    # the wrapper keeps the TOP name and exposes the canonical rst_n.
    assert "module sequence_detector (" in body
    assert "input rst_n" in body
    assert "module sequence_detector__rcvar_inner(" in body
    assert ".reset_n(rst_n)" in body
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb; reg clk=0,rst_n=0,data_in=0; wire detected;"
        " sequence_detector dut(.clk(clk),.rst_n(rst_n),"
        ".data_in(data_in),.detected(detected)); endmodule\n")
    res = _pr.run(
        [iv, "-g2012", "-o", str(tmp_path / "sd"), str(tb),
         str(rtl / "sequence_detector.v")],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_step_idempotent(tmp_path):
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "sequence_detector.v").write_text(_seq_core("reset_n"))
    assert P.step_reset_clock_variant_aliases(
        tmp_path, "sequence_detector").status == "PASS"
    assert P.step_reset_clock_variant_aliases(
        tmp_path, "sequence_detector").status == "SKIP"


def test_step_parameterized_top_forwards_params(tmp_path):
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "core.v").write_text(
        "module core #(parameter W=8)(input clk, input reset_n,"
        " input [W-1:0] d, output reg [W-1:0] q);\n"
        " always @(posedge clk or negedge reset_n)"
        " if(!reset_n) q<=0; else q<=d;\nendmodule\n")
    r = P.step_reset_clock_variant_aliases(tmp_path, "core")
    assert r.status == "PASS"
    body = (rtl / "core.v").read_text()
    assert "module core #(" in body and "parameter W" in body
    assert "core__rcvar_inner #(.W(W))" in body
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb; reg clk=0,rst_n=0; reg [7:0] d=0; wire [7:0] q;"
        " core #(.W(8)) dut(.clk(clk),.rst_n(rst_n),.d(d),.q(q)); endmodule\n")
    res = _pr.run(
        [iv, "-g2012", "-o", str(tmp_path / "c"), str(tb),
         str(rtl / "core.v")], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_step_active_high_reset_never_leaks_to_active_low(tmp_path):
    # #511 no-leak: an active-HIGH `reset` must canonicalise to active-HIGH
    # `rst`, NEVER to an active-low `_n` name. The wrapper exposes `.rst`, so a
    # TB using `.rst_n` correctly FAILs to elaborate (no silent inversion).
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "c2.v").write_text(
        "module c2(input clk, input reset, input d, output reg q);\n"
        " always @(posedge clk) if(reset) q<=0; else q<=d;\nendmodule\n")
    r = P.step_reset_clock_variant_aliases(tmp_path, "c2")
    assert r.status == "PASS"
    body = (rtl / "c2.v").read_text()
    assert "input rst" in body and "input rst_n" not in body
    assert ".reset(rst)" in body


def test_step_top_only_does_not_touch_submodule(tmp_path):
    # only the TOP module may be renamed; an internal sub-module that declares
    # reset_n and is instantiated by name MUST be left intact (its caller wires
    # the original port name).
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "sub.v").write_text(
        "module sub(input clk, input reset_n, output q);"
        " assign q=reset_n; endmodule\n")
    (rtl / "top.v").write_text(
        "module top(input clk, input rst_n, output q);"
        " sub u(.clk(clk),.reset_n(rst_n),.q(q)); endmodule\n")
    # top is already canonical (rst_n) → SKIP; sub must be untouched.
    r = P.step_reset_clock_variant_aliases(tmp_path, "top")
    assert r.status == "SKIP"
    assert "module sub(" in (rtl / "sub.v").read_text()
    assert "reset_n" in (rtl / "sub.v").read_text()


def test_step_skip_when_no_rtl(tmp_path):
    P, _pl = _runner()
    r = P.step_reset_clock_variant_aliases(tmp_path, "whatever")
    assert r.status == "SKIP"


def test_step_thin_wrapper_parent_still_aliases_and_rewires(tmp_path):
    # ROUND-3 FIX (#518): the round-2 guard SKIPped whenever the top was
    # instantiated internally — but a THIN pass-through wrapper (the runner's
    # auto chip_top or an author synonym wrapper that instantiates ONLY the top)
    # is NOT a real design parent; the TB still targets the top name, so the
    # alias MUST still be emitted. The step now aliases AND rewires the wrapper's
    # instantiation to the inner so nothing breaks.
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "design.v").write_text(
        "module parent(input clk, input reset_n, output q);\n"
        "  top dut(.clk(clk), .reset_n(reset_n), .q(q));\n"
        "endmodule\n"
        "module top(input clk, input reset_n, output q);"
        " assign q=clk&reset_n; endmodule\n")
    r = P.step_reset_clock_variant_aliases(tmp_path, "top")
    assert r.status == "PASS", (r.status, r.detail)
    body = (rtl / "design.v").read_text()
    # top renamed to inner; canonical wrapper takes the top name; the thin
    # parent now instantiates the inner (preserving its .reset_n wiring).
    assert "module top (" in body and "input rst_n" in body
    assert "module top__rcvar_inner(" in body
    assert "top__rcvar_inner dut(" in body
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")
    res = _pr.run(
        [iv, "-g2012", "-o", str(tmp_path / "d"), str(rtl / "design.v")],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_step_round3_multimodule_top_aliases_and_tb_elaborates(tmp_path):
    # ROUND-3 binding repro (#518): the real clean-room work dir — a reset_n core
    # plus the runner's auto chip_top AND an author-emitted synonym wrapper, all
    # instantiating the core. The round-2 guard over-fired (top_refs > top_decls)
    # and SKIPped → sequence_detector stayed compile_error against a TB using
    # rst_n. The step must now EMIT and the TB must elaborate.
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "sequence_detector.v").write_text(_seq_core("reset_n"))
    (rtl / "chip_top.v").write_text(
        "module chip_top(input clk, input reset_n, input data_in,"
        " output detected);\n"
        "  sequence_detector u(.clk(clk), .reset_n(reset_n),"
        " .data_in(data_in), .detected(detected));\nendmodule\n")
    (rtl / "sequencer_detector.v").write_text(
        "module sequencer_detector(input clk, input reset_n, input data_in,"
        " output detected);\n"
        "  sequence_detector u(.clk(clk), .reset_n(reset_n),"
        " .data_in(data_in), .detected(detected));\nendmodule\n")
    r = P.step_reset_clock_variant_aliases(tmp_path, "sequence_detector")
    assert r.status == "PASS", (r.status, r.detail)
    # both thin wrappers were rewired to the inner.
    assert "sequence_detector__rcvar_inner u(" in \
        (rtl / "chip_top.v").read_text()
    assert "sequence_detector__rcvar_inner u(" in \
        (rtl / "sequencer_detector.v").read_text()
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb; reg clk=0,rst_n=0,data_in=0; wire detected;"
        " sequence_detector dut(.clk(clk),.rst_n(rst_n),"
        ".data_in(data_in),.detected(detected)); endmodule\n")
    # compile the WHOLE work dir + TB (the TB targets the canonical wrapper).
    vfiles = [str(p) for p in sorted(rtl.glob("*.v"))]
    res = _pr.run(
        [iv, "-g2012", "-o", str(tmp_path / "sd"), str(tb), *vfiles],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_step_round4_runner_chip_top_name_resolves_author_leaf(tmp_path):
    # ROUND-4 binding repro (#518): the orchestrator invokes the step with
    # args.top_name (default 'chip_top') and at this plan position chip_top.v
    # DOES NOT EXIST YET (it is emitted later inside step_yosys_synth). The
    # old code SKIPped with "top module 'chip_top' not in rtl/" and the
    # reset_n leaf was never aliased. The step must now resolve the single
    # author leaf and alias IT.
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "sequence_detector.v").write_text(_seq_core("reset_n"))
    r = P.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert r.status == "PASS", (r.status, r.detail)
    assert "resolved TB-facing leaf" in r.detail
    body = (rtl / "sequence_detector.v").read_text()
    assert "module sequence_detector (" in body and "input rst_n" in body
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb; reg clk=0,rst_n=0,data_in=0; wire detected;"
        " sequence_detector dut(.clk(clk),.rst_n(rst_n),"
        ".data_in(data_in),.detected(detected)); endmodule\n")
    res = _pr.run(
        [iv, "-g2012", "-o", str(tmp_path / "sd"), str(tb),
         str(rtl / "sequence_detector.v")],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_step_round4_real_workdir_shape_with_chip_top_present(tmp_path):
    # the REAL round-4 work-dir shape: author leaf (reset_n) + the #517
    # leaf-typo synonym wrapper + an auto-emitted chip_top.v WITH the leading
    # `default_nettype directive (empirically the loader handles it — the
    # field's directive hypothesis was disproven; the true cause was the wrong
    # top name + step ordering). step(top='chip_top') must alias the leaf and
    # rewire BOTH thin wrappers to the inner.
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "sequence_detector.v").write_text(_seq_core("reset_n"))
    (rtl / "sequencer_detector.v").write_text(
        "module sequencer_detector(input clk, input reset_n, input data_in,"
        " output detected);\n"
        "  sequence_detector u(.clk(clk), .reset_n(reset_n),"
        " .data_in(data_in), .detected(detected));\nendmodule\n")
    (rtl / "chip_top.v").write_text(
        "// auto-emitted chip_top wrapper\n"
        "`default_nettype none\n"
        "module chip_top(input wire clk, input wire reset_n,"
        " input wire data_in, output detected);\n"
        "  sequence_detector u_dut(.clk(clk), .reset_n(reset_n),"
        " .data_in(data_in), .detected(detected));\nendmodule\n"
        "`default_nettype wire\n")
    r = P.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert r.status == "PASS", (r.status, r.detail)
    assert "sequence_detector__rcvar_inner u_dut(" in \
        (rtl / "chip_top.v").read_text()
    assert "sequence_detector__rcvar_inner u(" in \
        (rtl / "sequencer_detector.v").read_text()
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb; reg clk=0,rst_n=0,data_in=0; wire detected;"
        " sequence_detector dut(.clk(clk),.rst_n(rst_n),"
        ".data_in(data_in),.detected(detected)); endmodule\n")
    vfiles = [str(p) for p in sorted(rtl.glob("*.v"))]
    res = _pr.run(
        [iv, "-g2012", "-o", str(tmp_path / "sd"), str(tb), *vfiles],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_step_round4_multimodule_project_skips_no_guess(tmp_path):
    # #511 NEGATIVE no-leak for the new resolution: a multi-module project
    # (several 0-children leaves under a real parent) has NO unambiguous
    # TB-facing author module — with top='chip_top' the step must SKIP and
    # leave every file untouched, never guess.
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "alu.v").write_text(
        "module alu(input clk, input reset_n, output q);"
        " assign q=clk&reset_n; endmodule\n")
    (rtl / "regs.v").write_text(
        "module regs(input clk, input reset_n, output q);"
        " assign q=clk|reset_n; endmodule\n")
    (rtl / "soc.v").write_text(
        "module soc(input clk, input reset_n, output q1, output q2);\n"
        "  alu u1(.clk(clk), .reset_n(reset_n), .q(q1));\n"
        "  regs u2(.clk(clk), .reset_n(reset_n), .q(q2));\nendmodule\n")
    before = {f.name: f.read_text() for f in rtl.glob("*.v")}
    r = P.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert r.status == "SKIP", (r.status, r.detail)
    assert "not single-leaf-shaped" in r.detail
    after = {f.name: f.read_text() for f in rtl.glob("*.v")}
    assert before == after


def test_step_round4_rerun_after_alias_skips_globally(tmp_path):
    # idempotency across DIFFERENT top names: after a leaf alias emitted via
    # top='chip_top', a re-run (any top name) must SKIP on the global
    # __rcvar_inner marker — never wrap the inner a second time.
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "sequence_detector.v").write_text(_seq_core("reset_n"))
    assert P.step_reset_clock_variant_aliases(
        tmp_path, "chip_top").status == "PASS"
    r2 = P.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert r2.status == "SKIP"
    assert "already present" in r2.detail
    r3 = P.step_reset_clock_variant_aliases(tmp_path, "sequence_detector")
    assert r3.status == "SKIP"
    assert "already present" in r3.detail


def test_step_round4_authored_chip_top_still_aliases_directly(tmp_path):
    # ADVERSARIAL-REVIEW REGRESSION (round-4): an AUTHORED top literally named
    # chip_top (spec-to-rtl writes chip_top directly; possibly multi-module)
    # must keep the round-3 capability — alias chip_top itself when single-leaf
    # resolution has no answer.
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "core_a.v").write_text(
        "module core_a(input clk, output q); assign q=clk; endmodule\n")
    (rtl / "core_b.v").write_text(
        "module core_b(input clk, output q); assign q=~clk; endmodule\n")
    (rtl / "chip_top.v").write_text(
        "module chip_top(input clk, input reset_n, output q1, output q2);\n"
        "  core_a u1(.clk(clk), .q(q1));\n"
        "  core_b u2(.clk(clk), .q(q2));\nendmodule\n")
    r = P.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert r.status == "PASS", (r.status, r.detail)
    body = (rtl / "chip_top.v").read_text()
    assert "module chip_top (" in body and "input rst_n" in body
    assert "module chip_top__rcvar_inner(" in body
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")
    tb = tmp_path / "tb.v"
    tb.write_text("module tb; reg clk=0,rst_n=0; wire q1,q2;"
                  " chip_top dut(.clk(clk),.rst_n(rst_n),.q1(q1),.q2(q2));"
                  " endmodule\n")
    res = _pr.run(
        [iv, "-g2012", "-o", str(tmp_path / "d"), str(tb),
         *[str(p) for p in sorted(rtl.glob("*.v"))]],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_step_round4_l9_native_spelling_guards_skip(tmp_path):
    # ADVERSARIAL-REVIEW HIGH (round-4): when L9 explicitly declares the
    # NATIVE port spelling for the module being aliased, the runner's own
    # L9-driven TBs bind that spelling — the alias must SKIP, leaving the
    # design untouched (renaming would hard-FAIL reference_tb on a healthy
    # design).
    import json as _json
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "sequence_detector.v").write_text(_seq_core("reset_n"))
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(_json.dumps({
        "top_module": "sequence_detector",
        "top_ports": [{"name": "clk"}, {"name": "reset_n"},
                      {"name": "data_in"}, {"name": "detected"}]}))
    before = (rtl / "sequence_detector.v").read_text()
    r = P.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert r.status == "SKIP", (r.status, r.detail)
    assert "L9 declares native port spelling" in r.detail
    assert (rtl / "sequence_detector.v").read_text() == before


def test_step_round4_l9_empty_ports_does_not_block(tmp_path):
    # the REAL round-4 work dir has L9 with top_ports: [] — no spelling
    # evidence → the canonical alias fires (the field-verified doctrine).
    import json as _json
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "sequence_detector.v").write_text(_seq_core("reset_n"))
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(_json.dumps({
        "top_module": "sequence_detector", "top_ports": []}))
    r = P.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert r.status == "PASS", (r.status, r.detail)
    assert "input rst_n" in (rtl / "sequence_detector.v").read_text()


def test_step_comment_module_header_does_not_eat_rename(tmp_path):
    # ADVERSARIAL-REVIEW MED (round-4): a doc-header comment `// module core …`
    # above the real declaration must NOT consume the count=1 rename (that
    # produced a duplicate `module core` + broken RTL while reporting PASS).
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "core.v").write_text(
        "// module core : toggling datapath, auto-generated header\n"
        "module core(input clk, input reset_n, output reg q);\n"
        "  always @(posedge clk or negedge reset_n)"
        " if(!reset_n) q<=0; else q<=~q;\nendmodule\n")
    r = P.step_reset_clock_variant_aliases(tmp_path, "core")
    assert r.status == "PASS", (r.status, r.detail)
    body = (rtl / "core.v").read_text()
    # real decl renamed; comment untouched; exactly one wrapper named core.
    assert "module core__rcvar_inner(" in body
    assert "// module core :" in body
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")
    tb = tmp_path / "tb.v"
    tb.write_text("module tb; reg clk=0,rst_n=0; wire q;"
                  " core dut(.clk(clk),.rst_n(rst_n),.q(q)); endmodule\n")
    res = _pr.run(
        [iv, "-g2012", "-o", str(tmp_path / "d"), str(tb),
         str(rtl / "core.v")], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_step_display_string_is_not_an_instantiation(tmp_path):
    # ADVERSARIAL-REVIEW MED (round-4): `$display("core init (ok)")` inside a
    # SIBLING module must not be mistaken for an instantiation of `core` —
    # that flipped a genuine 2-leaf project into "single-leaf" and corrupted
    # the string during rewiring. The correct behavior: 2 leaves → SKIP, all
    # files byte-identical.
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "core.v").write_text(
        "module core(input clk, input reset_n, output q);"
        " assign q=clk&reset_n; endmodule\n")
    (rtl / "helper.v").write_text(
        "module helper(input clk, output q);\n"
        "  initial $display(\"core init (ok)\");\n"
        "  assign q=clk;\nendmodule\n")
    before = {f.name: f.read_text() for f in rtl.glob("*.v")}
    r = P.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert r.status == "SKIP", (r.status, r.detail)
    after = {f.name: f.read_text() for f in rtl.glob("*.v")}
    assert before == after


def test_step_multi_instance_parent_is_genuine_not_thin(tmp_path):
    # ADVERSARIAL-REVIEW LOW (round-4): a parent that instantiates the leaf
    # TWICE and has its own logic (XOR) is a REAL design parent, not a thin
    # wrapper — the #511 genuine-parent guard must fire (explicit-top path)
    # and the chip_top path must not see a single-leaf shape.
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "core.v").write_text(
        "module core(input clk, input reset_n, output q);"
        " assign q=clk&reset_n; endmodule\n")
    (rtl / "dual.v").write_text(
        "module dual(input clk, input reset_n, output q);\n"
        "  wire q0, q1;\n"
        "  core u0(.clk(clk), .reset_n(reset_n), .q(q0));\n"
        "  core u1(.clk(clk), .reset_n(reset_n), .q(q1));\n"
        "  assign q = q0 ^ q1;\nendmodule\n")
    r = P.step_reset_clock_variant_aliases(tmp_path, "core")
    assert r.status == "SKIP", (r.status, r.detail)
    assert "real internal submodule" in r.detail
    r2 = P.step_reset_clock_variant_aliases(tmp_path, "chip_top")
    assert r2.status == "SKIP", (r2.status, r2.detail)


def test_step_skips_when_top_is_genuine_leaf_submodule(tmp_path):
    # #511 NEGATIVE no-leak (the field's explicit ask): a GENUINE internal leaf
    # submodule — instantiated by a real design parent that also instantiates
    # OTHER submodules (not a thin pass-through) — must still be left intact
    # (its parent wires the original port names). The step must SKIP.
    P, _pl = _runner()
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True)
    (rtl / "leaf.v").write_text(
        "module leaf(input clk, input reset_n, output q);"
        " assign q=clk&reset_n; endmodule\n")
    (rtl / "other.v").write_text(
        "module other(input clk, output q); assign q=clk; endmodule\n")
    # datapath is a REAL parent: it instantiates leaf AND other (>1 child).
    (rtl / "datapath.v").write_text(
        "module datapath(input clk, input reset_n, output q1, output q2);\n"
        "  leaf u1(.clk(clk), .reset_n(reset_n), .q(q1));\n"
        "  other u2(.clk(clk), .q(q2));\nendmodule\n")
    r = P.step_reset_clock_variant_aliases(tmp_path, "leaf")
    assert r.status == "SKIP", (r.status, r.detail)
    assert "module leaf(" in (rtl / "leaf.v").read_text()
    assert "__rcvar_inner" not in (rtl / "leaf.v").read_text()
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")
    res = _pr.run(
        [iv, "-g2012", "-o", str(tmp_path / "d"),
         *[str(p) for p in sorted(rtl.glob("*.v"))]],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
