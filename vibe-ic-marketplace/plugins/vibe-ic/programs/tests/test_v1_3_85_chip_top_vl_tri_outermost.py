"""#115 follow-up (v1.3.85) — Verilator dead-reset through the auto-emitted
chip_top double-tri chain.

DEFECT (reproduced end-to-end, pre-existing parity with the old port-face
emission): the reset-alias additive wrapper carries `ifdef VERILATOR tri0/tri1
qualifiers on its port faces; `_autoemit_chip_top_if_needed` copied that port
block VERBATIM into chip_top, so BOTH hierarchy levels carried the pull —
and Verilator (5.020 / 5.048) never transfers a driven value through a
tri-port -> tri-port two-level chain: the design could never be reset
(RESET_DEAD for both spellings; iverilog was unaffected).

FIX (variant B — the only shape green in all quadrants; variant A, stripping
the copied tri from chip_top, freezes the design permanently IN reset under
Verilator because a plain unbound input ties to 0): chip_top KEEPS the copied
qualifiers (the outermost face owns the pull) and the INNER wrapper's
port-face tri qualifiers are neutralized to plain inputs — its body
(`ifdef VERILATOR combine arm + `else-arm internal pull nets) is untouched.
Verified 6/6 RESET_OK: iverilog 11.0 / 12.0 / Verilator 5.048 x
{spec spelling, canonical alias}.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from not_verified_tier import not_verified_reason  # noqa: E402

import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parents[1]


def _load_runner():
    import sys
    if str(PROG) not in sys.path:
        sys.path.insert(0, str(PROG))
    import design_one_shot_runner as mod
    return mod


# The runner-emitted additive wrapper shape (post-#115): VERILATOR-only port
# tri + internal pull nets in the else arm.
_WRAPPER = """\
module counter (
    input clk,
    input
`ifdef VERILATOR
    tri1
`endif
    resetn,
    input
`ifdef VERILATOR
    tri1
`endif
    rst_n,
    output [7:0] cnt
);
`ifdef VERILATOR
    wire resetn__rcvar_net = resetn & rst_n;
`elsif YOSYS
    wire resetn__rcvar_net = resetn & rst_n;
`else
    tri1 resetn__rcvar_pull;
    tri1 rst_n__rcvar_pull;
    assign resetn__rcvar_pull = resetn;
    assign rst_n__rcvar_pull = rst_n;
    wire resetn__rcvar_net = resetn__rcvar_pull & rst_n__rcvar_pull;
`endif
    counter__rcvar_inner u_counter__rcvar_inner (
        .clk(clk),
        .resetn(resetn__rcvar_net),
        .cnt(cnt)
    );
endmodule
"""

_CORE = """\
module counter__rcvar_inner (
    input clk,
    input resetn,
    output reg [7:0] cnt
);
    always @(posedge clk) begin
        if (!resetn) cnt <= 8'd0;
        else cnt <= cnt + 8'd1;
    end
endmodule
"""


def test_neutralize_strips_port_tri_keeps_body_pulls():
    d = _load_runner()
    text = _CORE + "\n" + _WRAPPER
    out = d._chip_top_neutralize_inner_vl_port_tri(text, "counter")
    assert out is not None
    header = out.split("module counter (", 1)[1].split(");", 1)[0]
    assert "tri1" not in header, "port-face tri must be neutralized"
    assert "`ifdef VERILATOR" not in header
    # body arms untouched
    assert "tri1 resetn__rcvar_pull;" in out
    assert "wire resetn__rcvar_net = resetn & rst_n;" in out
    # inner core module untouched
    assert out.startswith(_CORE.split("\n")[0])


@pytest.mark.parametrize("banner", [
    "// module counter — 8-bit up counter\n",
    "//module counter\n",
    "/* module counter */\n",
    "// module counter ( clk, resetn, cnt )\n",
])
def test_neutralize_survives_banner_comments(banner):
    """Step-2.7 reproduced MEDIUM: a plain banner comment naming the module
    BEFORE its declaration anchored the raw-text span locator on the comment,
    silently no-op'ing the neutralize — the Verilator dead-reset returned
    with no error. The span is now located on a comment-masked copy."""
    d = _load_runner()
    text = banner + _CORE + "\n" + _WRAPPER
    out = d._chip_top_neutralize_inner_vl_port_tri(text, "counter")
    assert out is not None, f"banner comment defeated the neutralize: {banner!r}"
    header = out.split("module counter (", 1)[1].split(");", 1)[0]
    assert "tri1" not in header
    assert "tri1 resetn__rcvar_pull;" in out   # body pull survives
    assert out.startswith(banner)              # comment itself untouched


def test_neutralize_noop_without_vl_tri_or_module():
    d = _load_runner()
    assert d._chip_top_neutralize_inner_vl_port_tri(_CORE, "counter__rcvar_inner") is None
    assert d._chip_top_neutralize_inner_vl_port_tri(_WRAPPER, "no_such_module") is None


def _stage(tmp_path):
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "input" / "docs" / "design_description.md").write_text(
        # THE DOC SHAPE IS LOAD-BEARING, and this is why it changed (#186/#689).
        # These two tests are about the ADDITIVE DUAL-SPELLING wrapper — the
        # second one says so: "the driven value must transfer ... for BOTH
        # spellings". The VERILATOR `tri1` pull exists to hold the spelling the
        # hidden TB did NOT bind. So the fixture must reach the additive path.
        # This doc used to carry BOTH a labelled "Input ports:" and a labelled
        # "Output ports:" section. Since #186 that pair is recognised as an
        # AUTHORITATIVE COMPLETE port enumeration, and the additive synonym is
        # then correctly suppressed — adding `rst_n` beside a documented N-port
        # contract would be a phantom port that spec_conformance_check FAILs.
        # Correct, and it leaves NO additive port and therefore no tri pull.
        # MEASURED, one RTL, four doc/code cells:
        #                labelled in+out            input-only
        #   before #186  additive kept,  tri1=2     additive kept, tri1=2
        #   with   #186  SUPPRESSED,     tri1=0     additive kept, tri1=2
        # Dropping the "Output ports:" section makes the enumeration INCOMPLETE,
        # which is exactly the state the additive path is for, and it no longer
        # depends on the detector failing to recognise a complete one.
        "# counter — 8-bit up counter\n\n"
        "Input ports:\n    clk: clock input\n"
        "    resetn: active-low synchronous reset\n"
        "\nThe module drives an 8-bit count output.\n\n"
        "On every rising edge of clk, if resetn is low the count clears to 0,\n"
        "otherwise it increments by 1.\n")
    (proj / "phase2" / "stage1" / "rtl" / "counter.v").write_text(
        "module counter (\n    input clk,\n    input resetn,\n"
        "    output reg [7:0] cnt\n);\n"
        "    always @(posedge clk) begin\n"
        "        if (!resetn) cnt <= 8'd0;\n"
        "        else cnt <= cnt + 8'd1;\n    end\nendmodule\n")
    # a second instantiation-graph root so #683 adoption declines and the
    # chip_top auto-emit path fires
    (proj / "phase2" / "stage1" / "rtl" / "top_wrap.v").write_text(
        "module counter_sync (\n    input clk,\n    input resetn,\n"
        "    output [7:0] cnt\n);\n"
        "    counter u_c (.clk(clk), .resetn(resetn), .cnt(cnt));\nendmodule\n")
    return proj


def _apply_additive_alias(proj, core="counter", src="resetn", dst="rst_n"):
    """Build the #792 additive dual-spelling wrapper the way v1.17.48 leaves as
    the ONLY way to build it.

    RULED by v1.17.48 (76e5960ee, "require a requested interface before aliasing
    reset/clock names"): "Automatic flow never constructs additive aliases.
    Retain the emitter's explicit `additive_reset_map` API for intentional
    compatibility callers." So `step_reset_clock_variant_aliases` can no longer
    produce this wrapper from any staged document — measured on e1814e28d, the
    fixture below returns SKIP (#689) whatever L3/L9 authority is added, because
    the design's own contract already declares `resetn`.

    That ruling is about WHO may ask for a dual-spelling interface. It says
    nothing about #115, which is what these two tests measure: given that such a
    wrapper exists, the VERILATOR `tri` pull must end up on the OUTERMOST
    chip_top face and the inner faces must be plain, or the driven reset never
    transfers through the two-level chain. So the wrapper is now built through
    the retained API — production code, not a hand-written copy — and everything
    the two tests actually assert is measured unchanged from there on.
    """
    import reset_clock_variant_alias as V
    f = proj / "phase2" / "stage1" / "rtl" / f"{core}.v"
    txt = f.read_text()
    inner = f"{core}__rcvar_inner"
    wrapper = V.emit_variant_alias_wrapper(
        inner, V.parse_module_ports(txt, core), {}, wrapper_name=core,
        additive_reset_map={src: dst})
    txt, n = re.subn(rf"\bmodule(\s+){re.escape(core)}\b",
                     rf"module\g<1>{inner}", txt, count=1)
    assert n == 1, f"could not rename `module {core}` to the inner"
    f.write_text(txt.rstrip("\n") + "\n\n" + wrapper)
    # The runner does not stop at the target file: it rewires every staged
    # instantiation of the target to the inner, so the wrapper that TOOK the
    # target's name is left uninstantiated. That is load-bearing here and not a
    # detail — it is what makes `counter` a second instantiation-graph root, so
    # #683 adoption declines and the chip_top auto-emit path under test fires.
    # MEASURED at v1.17.47 (35bc1d1ab), where these two tests were last green:
    # rewiring only `counter.v` leaves `counter_sync` instantiating the wrapper,
    # no chip_top is emitted, and synth returns FAIL with cells=2 instead of 55.
    # Uses the runner's own code-masked, label-guarded substitution rather than
    # a second copy of it.
    d = _load_runner()
    pat = d._rcvar_inst_pat(core)
    for other in sorted((proj / "phase2" / "stage1" / "rtl").glob("*.v")):
        if other == f:
            continue
        txt2, n2 = d._rcvar_sub_code_only(other.read_text(), pat,
                                          rf"{inner}\g<1>", label_guard=True)
        if n2:
            other.write_text(txt2)
    return f


@pytest.mark.skipif(
    not shutil.which("docker"),
    reason=not_verified_reason(
        "docker engine not bound in this run",
        remedy="run through tools/ci/run_suite_in_eda_image.sh, which "
               "binds the host docker CLI and socket into the container"))
def test_autoemit_moves_pull_to_outermost_face_end_to_end(tmp_path):
    """Runner-level end state: after alias + synth (chip_top auto-emit), the
    OUTERMOST chip_top faces carry the VERILATOR tri pull and the inner
    wrapper's port list is plain; the reset actually works under host
    iverilog through the two-level chain."""
    d = _load_runner()
    import os
    container = os.environ.get("VIBEIC_IVERILOG13_CONTAINER", "vibeic-eda")
    probe = subprocess.run(["docker", "exec", container, "sh", "-c", "true"],
                           capture_output=True)
    if probe.returncode != 0:
        pytest.skip(f"container {container!r} not running")
    proj = _stage(tmp_path)
    _apply_additive_alias(proj)
    r2 = d.step_yosys_synth(proj, "chip_top")
    assert r2.status == "PASS", r2.detail
    ct = (proj / "phase2" / "stage1" / "rtl" / "chip_top.v").read_text()
    inner = (proj / "phase2" / "stage1" / "rtl" / "counter.v").read_text()
    assert ct.count("tri1") == 2, "chip_top must keep the copied pulls"
    wrapper_hdr = inner.split("module counter (", 1)[1].split(");", 1)[0]
    assert not re.search(r"\btri1\b", wrapper_hdr), (
        "inner wrapper port faces must be plain after auto-emit")
    assert "tri1 resetn__rcvar_pull;" in inner, "body pull nets must survive"
    # behavior through the two-level chain on the host simulator, BOTH faces
    if shutil.which("iverilog"):
        for sp in ("resetn", "rst_n"):
            tb = tmp_path / f"tb_{sp}.v"
            tb.write_text(
                "module tb;\n  reg clk=0, r; wire [7:0] cnt; reg ok=1;\n"
                f"  chip_top u (.{sp}(r), .clk(clk), .cnt(cnt));\n"
                "  always #1 clk = ~clk;\n"
                "  initial begin\n"
                "    r = 0; #6; if (cnt !== 8'd0) ok = 0;\n"
                "    r = 1; #6; if (cnt === 8'd0 || cnt === 8'hxx) ok = 0;\n"
                "    r = 0; #6; if (cnt !== 8'd0) ok = 0;\n"
                "    if (ok) $display(\"RESET_OK\");"
                " else $display(\"RESET_DEAD\");\n"
                "    $finish;\n  end\nendmodule\n")
            binp = tmp_path / f"b_{sp}"
            c = subprocess.run(
                ["iverilog", "-g2012", "-s", "tb", "-o", str(binp), str(tb),
                 str(proj / "phase2" / "stage1" / "rtl" / "chip_top.v"),
                 str(proj / "phase2" / "stage1" / "rtl" / "counter.v")],
                capture_output=True, text=True)
            assert c.returncode == 0, c.stderr
            r = _pr.run(["vvp", str(binp)], capture_output=True,
                               text=True)
            assert "RESET_OK" in r.stdout, (sp, r.stdout)


@pytest.mark.skipif(
    not shutil.which("docker"),
    reason=not_verified_reason(
        "docker engine not bound in this run",
        remedy="run through tools/ci/run_suite_in_eda_image.sh, which "
               "binds the host docker CLI and socket into the container"))
def test_two_level_chain_resets_under_verilator(tmp_path):
    """The DISCRIMINATING pin (pre-fix: RESET_DEAD): under Verilator the
    driven value must transfer through chip_top into the wrapper and reset
    the design — for BOTH spellings."""
    d = _load_runner()
    import os
    container = os.environ.get("VIBEIC_IVERILOG13_CONTAINER", "vibeic-eda")
    probe = subprocess.run(
        ["docker", "exec", container, "sh", "-c",
         "PATH=/foss/tools/bin:$PATH verilator --version"],
        capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip(f"container {container!r} with verilator not running")
    proj = _stage(tmp_path)
    _apply_additive_alias(proj)
    assert d.step_yosys_synth(proj, "chip_top").status == "PASS"
    tag = f"/tmp/vibeic_t115ct_{os.getpid()}"
    try:
        subprocess.run(["docker", "exec", container, "sh", "-c",
                        f"rm -rf {tag} && mkdir -p {tag}"], check=True,
                       capture_output=True)
        for name, src in (
                ("chip_top.v", proj / "phase2/stage1/rtl/chip_top.v"),
                ("counter.v", proj / "phase2/stage1/rtl/counter.v")):
            subprocess.run(["docker", "cp", str(src), f"{container}:{tag}/{name}"],
                           check=True, capture_output=True)
        for sp in ("resetn", "rst_n"):
            tb = tmp_path / f"vtb_{sp}.v"
            tb.write_text(
                "module tb;\n  reg clk=0, r; wire [7:0] cnt; reg ok=1;\n"
                f"  chip_top u (.{sp}(r), .clk(clk), .cnt(cnt));\n"
                "  always #1 clk = ~clk;\n"
                "  initial begin\n"
                "    r = 0; #6; if (cnt !== 8'd0) ok = 0;\n"
                "    r = 1; #6; if (cnt === 8'd0) ok = 0;\n"
                "    r = 0; #6; if (cnt !== 8'd0) ok = 0;\n"
                "    if (ok) $display(\"RESET_OK\");"
                " else $display(\"RESET_DEAD\");\n"
                "    $finish;\n  end\nendmodule\n")
            subprocess.run(["docker", "cp", str(tb), f"{container}:{tag}/tb_{sp}.v"],
                           check=True, capture_output=True)
            r = _pr.run(
                ["docker", "exec", container, "bash", "-c",
                 f"export PATH=/foss/tools/bin:$PATH; cd {tag} && "
                 f"rm -rf vobj_{sp} && verilator --binary --timing -Wno-fatal "
                 f"-Wno-WIDTH -Mdir vobj_{sp} --top-module tb tb_{sp}.v "
                 f"chip_top.v counter.v >vl.log 2>&1 && "
                 f"timeout 60 vobj_{sp}/Vtb 2>&1"],
                capture_output=True, text=True)
            assert "RESET_OK" in r.stdout, (sp, r.stdout[-300:], r.stderr[-200:])
    finally:
        subprocess.run(["docker", "exec", container, "sh", "-c",
                        f"rm -rf {tag}"], capture_output=True)
