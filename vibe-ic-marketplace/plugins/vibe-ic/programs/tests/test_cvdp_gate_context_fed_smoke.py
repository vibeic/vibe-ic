"""Tests for the context-fed yosys smoke in cvdp_gate.py (capture:
ORGANIC-20260713, CVDP canonical-entry campaign).

Defect chain this closes (7/14 first-round gate blocks): `_stub_for` derives a
context-module stub from the instantiation site, where port DIRECTIONS are
unknowable — it declared an instance OUTPUT connection as `input`; the undriven
nets const-propagated the module away; yosys 0.6x prints NO cells row for a
0-cell module; the cells regex found nothing → false "synthesized to nothing"
BLOCK on a correct completion.

Fixes under test:
  1. `_context_rtl_for_smoke` — feed the record's OWN input.context RTL into
     the smoke (the official harness's real compile environment; §4.05-safe
     INPUT), filtered at FILE level on the comment-stripped view.
  2. yosys_smoke composition — a context-provided module drops the colliding
     derived stub; the completion's OWN modules can never be excluded from the
     per-module synth loop (the collision emptied it → "no module declaration").
  3. INTERIM 0-cell wiring tolerance — stat header + wires row present but no
     cells row → tolerated with a note (pending the Bucket-T fork-yosys
     always-print-cells-row fix); anything else stays the hard BLOCK.
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2] / "benchmark" / "cvdp_gate.py")


def _load():
    spec = importlib.util.spec_from_file_location("cvdp_gate", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


COMPLETION = (
    "module inter_top(input clk, input [7:0] d, output [7:0] q);\n"
    "  wire [7:0] w;\n"
    "  helper_blk u0 (.in_data(d), .out_data(w));\n"
    "  assign q = ~w;\nendmodule\n")

CTX_HELPER = (
    "module helper_blk(input [7:0] in_data, output [7:0] out_data);\n"
    "  assign out_data = in_data ^ 8'hA5;\nendmodule\n")

# a context file that ALSO defines the completion's own module — the file the
# completion replaces (modify-task shape); must be skipped WHOLE.
CTX_REPLACED = (
    "module inter_top(input clk, input [7:0] d, output [7:0] q);\n"
    "  assign q = d;\nendmodule\n"
    "module extra_blk(input a, output b);\n  assign b = a;\nendmodule\n")

# a context file whose COMMENT mentions a module name — must not create a
# phantom slice (filtering happens on the comment-stripped view).
CTX_COMMENT_TRAP = (
    "// this file wires module inter_top into the fabric\n"
    "module wiring_blk(input x, output y);\n  assign y = x;\nendmodule\n")


# ---- _context_rtl_for_smoke ------------------------------------------------
def test_ctx_module_included_when_not_owned():
    m = _load()
    out = m._context_rtl_for_smoke([CTX_HELPER], COMPLETION)
    assert "helper_blk" in out and "8'hA5" in out


def test_ctx_file_defining_owned_module_skipped_whole():
    """The manchester shape: a ctx file defines the completion's own module
    (plus others) — including it would duplicate the definition. The WHOLE
    file is skipped, including its other modules."""
    m = _load()
    out = m._context_rtl_for_smoke([CTX_REPLACED], COMPLETION)
    assert "extra_blk" not in out          # whole-file skip
    assert out.count("module inter_top") == 0


def test_ctx_comment_module_name_is_not_a_phantom():
    """A comment saying 'module inter_top' must not make the filter treat the
    file as defining the owned module — detection runs comment-stripped."""
    m = _load()
    out = m._context_rtl_for_smoke([CTX_COMMENT_TRAP], COMPLETION)
    assert "wiring_blk" in out


def test_ctx_empty_or_none_is_noop():
    m = _load()
    assert m._context_rtl_for_smoke(None, COMPLETION) == ""
    assert m._context_rtl_for_smoke([], COMPLETION) == ""


# ---- yosys_smoke composition (fake yosys via _run monkeypatch) -------------
def _fake_run_factory(blob_by_top):
    def fake_run(cmd, timeout=120):
        # cmd = ["yosys", "-p", "read_verilog -sv <f>; synth -top <top>; stat"]
        p = cmd[-1]
        top = p.split("synth -top ")[1].split(";")[0].strip()
        return 0, blob_by_top.get(top, ""), ""
    return fake_run


def test_own_module_never_excluded_by_ctx_collision(tmp_path, monkeypatch):
    """Regression of the 'no module declaration found' block: a ctx name
    colliding with the completion's own module must not empty the synth loop."""
    m = _load()
    ok_blob = "=== inter_top ===\n   12 wires\n   34 cells\n"
    monkeypatch.setattr(m, "_run", _fake_run_factory({"inter_top": ok_blob}))
    # context text that (wrongly, via any upstream slip) still contains the
    # own module name — composition must keep inter_top in the loop
    ctx = CTX_HELPER + "\nmodule inter_top(); endmodule\n"
    ok, why = m.yosys_smoke(COMPLETION, tmp_path, "", context_rtl=ctx)
    assert ok, why
    assert "inter_top: 34 cells" in why


def test_ctx_module_drops_colliding_stub(tmp_path, monkeypatch):
    """When context provides helper_blk, a derived stub for helper_blk must be
    dropped (duplicate definition would abort yosys)."""
    m = _load()
    ok_blob = "=== inter_top ===\n   12 wires\n   34 cells\n"
    monkeypatch.setattr(m, "_run", _fake_run_factory({"inter_top": ok_blob}))
    stub = ("\n\n// gate-synthesized context stubs\n"
            "module helper_blk(input in_data, input out_data);\nendmodule\n")
    ok, why = m.yosys_smoke(COMPLETION, tmp_path, stub, context_rtl=CTX_HELPER)
    assert ok, why
    smoke = (tmp_path / "smoke.sv").read_text()
    assert smoke.count("module helper_blk") == 1        # ctx wins, stub dropped
    assert "8'hA5" in smoke                             # the REAL body, not the stub


# ---- 0-cell wiring tolerance (interim, pending fork-yosys fix) -------------
def test_zero_cell_wiring_module_tolerated_with_note(tmp_path, monkeypatch):
    m = _load()
    wiring_blob = "=== inter_top ===\n   12 wires\n    5 ports\n"   # no cells row
    monkeypatch.setattr(m, "_run", _fake_run_factory({"inter_top": wiring_blob}))
    ok, why = m.yosys_smoke(COMPLETION, tmp_path, "", context_rtl=CTX_HELPER)
    assert ok, why
    assert "INCONCLUSIVE wiring-shape" in why and "0 cells" in why


def test_no_stat_header_still_blocks(tmp_path, monkeypatch):
    """§4.05 no-leak: the tolerance must NOT widen to 'any missing cells row' —
    a blob without the module's stat header stays the hard BLOCK."""
    m = _load()
    monkeypatch.setattr(m, "_run", _fake_run_factory({"inter_top": "nothing useful\n"}))
    ok, why = m.yosys_smoke(COMPLETION, tmp_path, "", context_rtl=CTX_HELPER)
    assert not ok
    assert "synthesized to nothing" in why


# ---- e2e with a real yosys (skips when unavailable) ------------------------
def test_e2e_context_fed_smoke_real_yosys(tmp_path):
    m = _load()
    if not shutil.which("yosys"):
        pytest.skip("yosys not on PATH")
    ok, why = m.yosys_smoke(COMPLETION, tmp_path, "", context_rtl=CTX_HELPER)
    assert ok, why


# ---- §4.05 no-leak regressions from the adversarial PR-round verification ----
def test_leak1_undriven_output_shell_still_blocks(tmp_path, monkeypatch):
    """LEAK #1 fixture: `module m2(input a, output b); wire dummy; endmodule`
    (undriven output, zero logic) produces the SAME header+wires/no-cells stat
    shape as a legit feed-through — the narrowed tolerance must NOT wave it
    through (no assign / no instantiation in the body)."""
    m = _load()
    shell = "module m2(input a, output b);\n  wire dummy;\nendmodule\n"
    wiring_blob = "=== m2 ===\n   3 wires\n    2 ports\n"   # no cells row
    monkeypatch.setattr(m, "_run", _fake_run_factory({"m2": wiring_blob}))
    ok, why = m.yosys_smoke(shell, tmp_path, "", context_rtl="")
    assert not ok
    assert "synthesized to nothing" in why


def test_leak1_true_feedthrough_still_tolerated(tmp_path, monkeypatch):
    """The legit half of the boundary: a real feed-through (has assign) with
    the same no-cells stat shape stays tolerated, with the TRUTHFUL note."""
    m = _load()
    ft = ("module ftw(input [3:0] a, output [3:0] y);\n"
          "  assign y = {a[0],a[1],a[2],a[3]};\nendmodule\n")
    wiring_blob = "=== ftw ===\n   3 wires\n    2 ports\n"
    monkeypatch.setattr(m, "_run", _fake_run_factory({"ftw": wiring_blob}))
    ok, why = m.yosys_smoke(ft, tmp_path, "", context_rtl="")
    assert ok, why
    assert "INCONCLUSIVE wiring-shape" in why
    assert "provably" not in why


def test_leak2_unparseable_ctx_file_dropped(monkeypatch):
    """LEAK #2 fixture: a ctx file the host yosys frontend rejects (SV class)
    must be DROPPED by the per-file pre-parse — never appended to smoke.sv
    where it would kill read_verilog and degrade the whole smoke to a
    frontend-gap tolerate."""
    m = _load()
    bad_ctx = ("class cfg_c;\n  int unsigned depth;\nendclass\n"
               "module ctx_ok(input a, output b);\n  assign b = a;\n"
               "endmodule\n")
    good_ctx = "module helper2(input a, output b);\n  assign b = ~a;\nendmodule\n"
    calls = []

    def fake_run(cmd, timeout=120):
        calls.append(cmd)
        # solo pre-parse probe: reject the file containing the class.
        # The real call QUOTES the path inside the `-p` script (an unquoted
        # path let a TMPDIR containing a space silently degrade the smoke),
        # so strip the quotes the same way a shell-ish reader would.
        f = cmd[-1].split("read_verilog -sv ", 1)[-1].strip().strip('"')
        try:
            txt = open(f).read()
        except OSError:
            txt = ""
        return (1, "", "syntax error") if "class " in txt else (0, "", "")
    monkeypatch.setattr(m, "_run", fake_run)
    comp = "module topz(input a, output b);\n  helper2 u(.a(a), .b(b));\nendmodule\n"
    out = m._context_rtl_for_smoke([bad_ctx, good_ctx], comp)
    assert "helper2" in out            # parseable ctx kept
    assert "cfg_c" not in out          # unparseable ctx dropped whole
    assert "ctx_ok" not in out


def test_minor_ctx_comment_module_name_no_phantom_stub_drop(tmp_path, monkeypatch):
    """ctx_names must come from the comment-stripped view: a ctx COMMENT
    saying 'module helper_blk' must not drop helper_blk's derived stub."""
    m = _load()
    ok_blob = "=== inter_top ===\n   12 wires\n   34 cells\n"
    monkeypatch.setattr(m, "_run", _fake_run_factory({"inter_top": ok_blob}))
    ctx_comment_only = "// wiring notes: module helper_blk is instantiated here\n"
    stub = ("\n\n// gate-synthesized context stubs\n"
            "module helper_blk(input in_data, input out_data);\nendmodule\n")
    ok, why = m.yosys_smoke(COMPLETION, tmp_path, stub,
                            context_rtl=ctx_comment_only)
    assert ok, why
    smoke = (tmp_path / "smoke.sv").read_text()
    assert smoke.count("module helper_blk(") == 1  # stub KEPT (no phantom drop)
