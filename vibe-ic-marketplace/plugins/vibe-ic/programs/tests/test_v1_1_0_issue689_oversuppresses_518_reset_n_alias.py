"""ORGANIC #792 — the #689 contract-suppression false-blocked the #518
`reset_n`->`rst_n` alias rescue (HALF_WIRED_NOOP), in tension with the arstn /
multi_booth / up_down `.reset`-binding suppression cases.

THE TRAP (provable indistinguishability from the contract alone):

  | design            | spec colon-form | hidden TB binding | required |
  |-------------------|-----------------|-------------------|----------|
  | multi_booth_8bit  | reset           | .reset(reset)     | spec     |
  | up_down_counter   | reset           | .reset(reset)     | spec     |
  | synchronizer/arstn| arstn           | .arstn(arstn)     | spec     |
  | sequence_detector | reset_n         | .rst_n(rst_n)     | CANON    |

All four declare a NON-canonical standard reset whose canonical-per-polarity
target differs; the ONLY thing separating "suppress" from "rescue" is the hidden
TB binding, which is invisible at plan time. #689 suppressed the rename for ALL
of them — which CORRECTLY kept the three spec-binding cases but FALSE-BLOCKED
`sequence_detector` (hidden TB binds the canonical `.rst_n`) → elaboration FAIL
`port 'rst_n' is not a port of dut`.

THE FIX (#792 — additive dual-spelling reset wrapper): expose BOTH the contract
spelling AND the canonical, polarity-safely combined so the UNDRIVEN alias
defaults INACTIVE (active-low → `tri1` pull, AND-combine; active-high → `tri0`
pull, OR-combine). Whichever spelling the TB binds drives the reset; the other
never floats to `x`. REVISED per #115: the port faces are PLAIN inputs (a
port-level tri coerces to inout under stock iverilog 11 and rejects reg-driven
TBs); the inactive-default pull lives on INTERNAL `tri0`/`tri1` nets, with the
pull kept on the port only under `` `ifdef VERILATOR `` and yosys seeing the
plain port-direct combine. This
RESCUES `sequence_detector` AND keeps the three spec-binding cases green — every
in-edge proven by REAL iverilog elaboration of BOTH bindings.

chip-AGNOSTIC: standard reset spellings + port-decl grammar; no chip literal.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import reset_clock_variant_alias as V        # noqa: E402
import design_one_shot_runner as R           # noqa: E402
import _path_layout as PL                     # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_IV = shutil.which("iverilog")
_VVP = shutil.which("vvp")
_YOSYS = shutil.which("yosys")


def _stage(tmp_path, design, spec, rtl_text):
    proj = tmp_path / design
    (proj / "phase1" / "input_doc").mkdir(parents=True, exist_ok=True)
    rd = PL.rtl_dir(proj)
    rd.mkdir(parents=True, exist_ok=True)
    (proj / "phase1" / "input_doc" / "design_description.txt").write_text(spec)
    f = rd / f"{design}.v"
    f.write_text(rtl_text)
    return proj, f


# ── active-low reset core (sequence_detector / arstn) ────────────────────────
def _al_core(name, reset):
    return (f"module {name}(\n  input clk, input {reset}, input data_in,\n"
            f"  output reg detected\n);\n"
            f"  always @(posedge clk or negedge {reset})\n"
            f"    if(!{reset}) detected<=1'b0; else detected<=data_in;\n"
            f"endmodule\n")


def _al_spec(name, reset):
    return (f"Module name:\n    {name}\n\nInput ports:\n"
            f"    clk: Clock signal.\n    {reset}: active-low reset.\n"
            f"    data_in: input.\nOutput ports:\n    detected: out.\n")


# ── active-high reset core (multi_booth / up_down style) ─────────────────────
def _ah_core(name, reset):
    return (f"module {name}(\n  input clk, input {reset}, input d,\n"
            f"  output reg q\n);\n"
            f"  always @(posedge clk) if({reset}) q<=1'b0; else q<=d;\n"
            f"endmodule\n")


def _ah_spec(name, reset):
    return (f"Module name:\n    {name}\n\nInput ports:\n"
            f"    clk: Clock signal.\n    {reset}: active-high reset.\n"
            f"    d: input.\nOutput ports:\n    q: out.\n")


def _run_step(proj):
    return R.step_reset_clock_variant_aliases(proj, "chip_top")


def _apply_additive(proj, design, reset, canon):
    """Build the #792 additive dual-spelling wrapper the only way v1.17.48 left.

    RULED by v1.17.48 (76e5960ee, "require a requested interface before aliasing
    reset/clock names"): "Automatic flow never constructs additive aliases.
    Retain the emitter's explicit `additive_reset_map` API for intentional
    compatibility callers." MEASURED on e1814e28d, every case below returned
    ('SKIP', "…already declares the standard spelling(s) … (#689)") — the specs
    these designs ship DECLARE their reset, which is now authority to keep it.

    That ruling settles WHO may ask for a dual-spelling interface. It says
    nothing about what #792 measures here, which is how the wrapper BEHAVES once
    it exists: both spellings exposed, the undriven one defaulting INACTIVE
    rather than to `x`, and a TB binding EITHER spelling elaborating and
    functioning. So the wrapper is now built through the retained API —
    production code, not a hand-written copy — and every elaboration assertion
    below is measured exactly as before.
    """
    import re as _re
    import reset_clock_variant_alias as V
    f = PL.rtl_dir(proj) / f"{design}.v"
    txt = f.read_text()
    inner = f"{design}__rcvar_inner"
    wrapper = V.emit_variant_alias_wrapper(
        inner, V.parse_module_ports(txt, design), {}, wrapper_name=design,
        additive_reset_map={reset: canon})
    txt, n = _re.subn(rf"\bmodule(\s+){_re.escape(design)}\b",
                      rf"module\g<1>{inner}", txt, count=1)
    assert n == 1, f"could not rename `module {design}` to the inner"
    f.write_text(txt.rstrip("\n") + "\n\n" + wrapper)


def _elaborate(rtl_file, top, ports_bind):
    """Elaborate `top` against a TB that binds exactly `ports_bind` (dict of
    port→reg) plus clk; return iverilog returncode."""
    sigs = " ".join(f"reg {n}=0;" for n in ports_bind)
    conns = ", ".join(f".{p}({p})" for p in ports_bind)
    tb = rtl_file.parent.parent / f"tb_{top}_{'_'.join(ports_bind)}.v"
    tb.write_text(
        f"module tb; reg clk=0; {sigs} wire o;\n"
        f"  {top} dut(.clk(clk), {conns}, .o(o));\nendmodule\n")
    return tb


# ════════════════════════════════════════════════════════════════════════
# #792 RESCUE — the motivating defect: sequence_detector binds the CANONICAL
# ════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not (_IV and _VVP), reason="iverilog/vvp unavailable")
def test_792_rescue_sequence_detector_canonical_binding_now_elaborates(tmp_path):
    proj, f = _stage(tmp_path, "sequence_detector",
                     _al_spec("sequence_detector", "reset_n"),
                     _al_core("sequence_detector", "reset_n"))
    _apply_additive(proj, "sequence_detector", "reset_n", "rst_n")
    body = f.read_text()
    assert "reset_n" in body and "rst_n" in body          # BOTH spellings exposed
    assert "sequence_detector__rcvar_inner" in body
    # the canonical .rst_n-binding hidden TB now elaborates + functions.
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb; reg clk=0,rst_n=0,data_in=1; wire detected;\n"
        " sequence_detector dut(.clk(clk),.rst_n(rst_n),.data_in(data_in),"
        ".detected(detected));\n always #5 clk=~clk;\n"
        " initial begin #12 if(detected!==1'b0) $display(\"FAIL reset\");\n"
        "  rst_n=1; #10; @(posedge clk); #1;\n"
        "  if(detected===1'bx) $display(\"FAIL X\"); else $display(\"OK\");\n"
        "  $finish; end\nendmodule\n")
    rd = PL.rtl_dir(proj)
    srcs = [str(p) for p in sorted(rd.glob("*.v"))]
    r = _pr.run([_IV, "-g2012", "-o", str(tmp_path / "b"), *srcs,
                        str(tb)], capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr)   # was: port 'rst_n' not found
    v = _pr.run([_VVP, str(tmp_path / "b")], capture_output=True,
                       text=True)
    out = v.stdout + v.stderr
    assert "OK" in out and "FAIL" not in out, out      # undriven reset_n != X


# ════════════════════════════════════════════════════════════════════════
# NO-REGRESSION — the three spec-binding cases STILL elaborate (+ canon rescue)
# ════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not _IV, reason="iverilog unavailable")
@pytest.mark.parametrize("design,reset,canon,core,spec", [
    ("synchronizer", "arstn", "rst_n", _al_core, _al_spec),     # active-low
    ("multi_booth", "reset", "rst", _ah_core, _ah_spec),        # active-high
    ("up_down", "reset", "rst", _ah_core, _ah_spec),            # active-high
])
def test_792_noregression_spec_binding_and_canon_rescue(
        tmp_path, design, reset, canon, core, spec):
    proj, f = _stage(tmp_path, design, spec(design, reset), core(design, reset))
    _apply_additive(proj, design, reset, canon)
    body = f.read_text()
    assert reset in body and canon in body

    # the output port differs per core (detected vs q); bind clk+reset only and
    # let the rest default — both bindings must elaborate.
    out_port = "detected" if core is _al_core else "q"
    in_port = "data_in" if core is _al_core else "d"

    def _elab(rbind):
        tb = tmp_path / f"tb_{design}_{rbind}.v"
        tb.write_text(
            f"module tb; reg clk=0,{rbind}=0,{in_port}=0; wire {out_port};\n"
            f" {design} dut(.clk(clk),.{rbind}({rbind}),.{in_port}({in_port}),"
            f".{out_port}({out_port}));\nendmodule\n")
        rd = PL.rtl_dir(proj)
        srcs = [str(p) for p in sorted(rd.glob("*.v"))]
        return _pr.run([_IV, "-g2012", "-o", str(tmp_path / f"{rbind}.b"),
                               *srcs, str(tb)], capture_output=True, text=True)
    # spec binding: NO REGRESSION (this is the #689 case that must stay green).
    r_spec = _elab(reset)
    assert r_spec.returncode == 0, (r_spec.stdout + r_spec.stderr)
    # canonical binding: #792 RESCUE now also works.
    r_canon = _elab(canon)
    assert r_canon.returncode == 0, (r_canon.stdout + r_canon.stderr)


# ════════════════════════════════════════════════════════════════════════
# §4.05 — additive is SCOPED to contract-declared resets; the legit #518
# no-contract case still DESTRUCTIVELY renames (canonical-only), and a CLOCK
# is never additive.
# ════════════════════════════════════════════════════════════════════════
def test_792_noleak_no_contract_still_destructive_rename(tmp_path):
    # NO staged contract → the #518 doctrine: rename reset_n→rst_n, wrapper
    # exposes ONLY rst_n (no additive reset_n port). additive requires the
    # spelling to be in the design's own contract.
    proj, f = _stage(tmp_path, "seqd",
                     "no port section here, just prose about a reset.",
                     _al_core("seqd", "reset_n"))
    # blank the description so nothing registers as a contract port.
    (proj / "phase1" / "input_doc" / "design_description.txt").write_text(
        "A design with a reset. (no Input ports: section)\n")
    before = f.read_text()
    res = _run_step(proj)
    # RULED by v1.17.48 (76e5960ee): the #518 doctrine was a GUESS at a hidden
    # binding. With no contract there is no authority to rename at all, so the
    # authored ports are preserved and the step reports an advisory SKIP —
    # "SKIP is not semantic acceptance", it is the refusal to act unasked.
    # Pinned by its reason so it cannot be satisfied by the #689 refusal that
    # every OTHER case in this file now returns.
    assert res.status == "SKIP", (res.status, res.detail)
    assert "no authoritative interface requests" in res.detail, res.detail
    assert f.read_text() == before, "the authored RTL must be left unchanged"
    body = f.read_text()
    # The destructive rename this case pinned is exactly what the ruling
    # withdrew: an unrequested rename changes the delivered interface and can
    # break an otherwise passing design. So the canonical is NOT introduced and
    # no wrapper is emitted — the authored `reset_n` stays the design's port.
    assert "rst_n" not in body, body
    assert "seqd__rcvar_inner" not in body, body
    assert "input reset_n" in body or " reset_n" in body, body


def test_792_clock_is_never_additive(tmp_path):
    # A clock has no inactive level → never additive. With a contract declaring
    # only `clock`, the clock stays SUPPRESSED (no additive, no rename) and the
    # gate SKIPs (nothing to do) — additive must not fire on a clock.
    rtl = ("module dut_c(input clock, input d, output reg q);\n"
           "  always @(posedge clock) q<=d;\nendmodule\n")
    proj, f = _stage(tmp_path, "dut_c",
                     "Module name:\n    dut_c\n\nInput ports:\n"
                     "    clock: system clock.\n    d: input.\n"
                     "Output ports:\n    q: out.\n", rtl)
    res = _run_step(proj)
    # clock contract-suppressed, no reset → SKIP, and never an additive clock.
    assert res.status == "SKIP", (res.status, res.detail)
    assert "additive" not in res.detail.lower()
    assert "__rcvar_inner" not in f.read_text()


# ════════════════════════════════════════════════════════════════════════
# yosys tolerates the wrapper (tri nets live outside the `elsif YOSYS arm — #115)
# ════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not _YOSYS, reason="yosys unavailable")
def test_792_additive_wrapper_synth_reads_under_yosys(tmp_path):
    proj, f = _stage(tmp_path, "sequence_detector",
                     _al_spec("sequence_detector", "reset_n"),
                     _al_core("sequence_detector", "reset_n"))
    _run_step(proj)
    rd = PL.rtl_dir(proj)
    r = _pr.run(
        [_YOSYS, "-q", "-p",
         f"read_verilog {rd}/sequence_detector.v; "
         f"hierarchy -top sequence_detector; proc; opt; synth"],
        capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr)   # tri1 never reaches yosys


# ════════════════════════════════════════════════════════════════════════
# UNIT — the emitter + the port parser (net-type skip) directly
# ════════════════════════════════════════════════════════════════════════
def test_792_emitter_dual_port_polarity_safe_combine():
    ports = [("input", "", "clk"), ("input", "", "reset_n"),
             ("input", "", "data_in"), ("output", "", "detected")]
    w = V.emit_variant_alias_wrapper(
        "core__rcvar_inner", ports, {}, wrapper_name="core",
        additive_reset_map={"reset_n": "rst_n"})
    # REVISED shape (#115): the tri1 pull is verilator-only on the PORT faces
    # (iverilog 11 rejects reg-driven tri ports) and lives on INTERNAL nets for
    # event-driven simulators; the AND-combine exists in both arms.
    assert "`ifdef VERILATOR" in w and "tri1" in w        # active-low → tri1
    assert "wire reset_n__rcvar_net = reset_n & rst_n;" in w   # AND-combine
    assert "tri1 reset_n__rcvar_pull;" in w               # internal pull nets
    assert "tri1 rst_n__rcvar_pull;" in w
    assert ("wire reset_n__rcvar_net = reset_n__rcvar_pull & rst_n__rcvar_pull;"
            in w)
    # active-high → tri0 / OR-combine
    w2 = V.emit_variant_alias_wrapper(
        "core__rcvar_inner",
        [("input", "", "clk"), ("input", "", "reset"), ("output", "", "q")],
        {}, wrapper_name="core", additive_reset_map={"reset": "rst"})
    assert "tri0" in w2 and "wire reset__rcvar_net = reset | rst;" in w2
    assert ("wire reset__rcvar_net = reset__rcvar_pull | rst__rcvar_pull;"
            in w2)


def test_792_emitter_rejects_additive_on_nonreset():
    with pytest.raises(ValueError):
        V.emit_variant_alias_wrapper(
            "c", [("input", "", "clk"), ("output", "", "q")], {},
            additive_reset_map={"clk": "clock"})   # clock has no inactive level


def test_792_port_parser_skips_tri_nettypes():
    # the fix that unblocks full_stack_tb_gen: `input tri1 reset_n` parses the
    # NAME reset_n (not the net-type tri1) — regression for the parser change.
    rtl = ("module m(\n  input clk,\n  input tri1 reset_n,\n"
           "  input tri0 rst,\n  output q\n);\nendmodule\n")
    names = [p[2] for p in V.parse_module_ports(rtl, "m")]
    assert names == ["clk", "reset_n", "rst", "q"], names


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
