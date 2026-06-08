"""v0.3.18 — #518: emit reset/clock NAME-VARIANT aliases at chip-top so a design
declaring one standard spelling (reset_n) elaborates against a hidden TB that
instantiates an equivalent standard spelling (.rst_n) — POLARITY PRESERVED.

Acceptance: a design declaring reset_n elaborates against `.rst_n` (same
active-low polarity); an active-HIGH reset must NEVER be aliased to an
active-low name.

chip-AGNOSTIC: only generic reset/clock spelling sets are baked in.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import reset_clock_variant_alias as V  # noqa: E402


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
    r = subprocess.run(
        [iv, "-g2012", "-s", "tb", "-o", str(tmp_path / "tb.out"),
         str(core_rtl), str(wrap_f), str(tb)],
        capture_output=True, text=True, timeout=60)
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
    import phase2_one_shot_runner as P
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
    res = subprocess.run(
        [iv, "-g2012", "-o", str(tmp_path / "sd"), str(tb),
         str(rtl / "sequence_detector.v")],
        capture_output=True, text=True, timeout=60)
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
    res = subprocess.run(
        [iv, "-g2012", "-o", str(tmp_path / "c"), str(tb),
         str(rtl / "core.v")], capture_output=True, text=True, timeout=60)
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


def test_step_skips_when_top_instantiated_internally(tmp_path):
    # ROUND-2 ADVERSARIAL-REVIEW REGRESSION (#518): if the designated top is
    # instantiated by ANOTHER module (so it is not really an external-TB top),
    # renaming it + giving its name to a canonical-port wrapper would silently
    # break the internal caller (which still wires the ORIGINAL port names). The
    # step MUST detect the internal reference and SKIP (leave the RTL intact),
    # never emit broken code.
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
    assert r.status == "SKIP", (r.status, r.detail)
    body = (rtl / "design.v").read_text()
    # RTL left untouched — no rename, no wrapper.
    assert "module top(" in body
    assert "__rcvar_inner" not in body
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host")
    # the un-transformed design still elaborates (parent + top consistent).
    res = subprocess.run(
        [iv, "-g2012", "-o", str(tmp_path / "d"), str(rtl / "design.v")],
        capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
