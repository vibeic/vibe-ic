"""Unit tests for the SHARED SystemVerilog-frontend selection logic
(`synth_frontend`) and its reuse across the Phase-2 + Phase-3 runners.

Closes ORGANIC-20260526-sv-synth-frontend: the Phase-3 synth step already
had `_decide_synth_frontend` (slang -> sv2v fallback); this pins that the
SAME rule now drives (a) the Phase-2 yosys-synth step and (b) the Phase-2
iverilog reference-TB step, via the shared `synth_frontend` module rather
than a divergent copy.

These tests mirror programs/tests/test_phase3_backend_fixes.py
::TestSynthFrontendSelection and are docker-free: they exercise the pure
decision logic with synthetic inputs and DO NOT spawn any container.

CRITICAL honesty-gate assertions: a plain-Verilog failure with NO SV
signature must NOT trigger the fallback (it is a real defect, not a
frontend gap); and a successful default attempt must never re-run.
"""
import importlib
import shutil
import subprocess
from pathlib import Path

import pytest

sf = importlib.import_module("synth_frontend")
p2 = importlib.import_module("design_one_shot_runner")
p3 = importlib.import_module("phase3_one_shot_runner")

import sys as _cg_sys
from pathlib import Path as _cg_path
_cg_sys.path.insert(0, str(_cg_path(__file__).resolve().parent))
import _container_guard as _cg  # noqa: E402
_cg_sys.path.insert(0, str(_cg_path(__file__).resolve().parents[1]))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin/name is stated

# THE NAME THE RUNTIME ITSELF DERIVES, not the bare shared literal.
#
# #2230 replaced this file's `docker inspect .State.Running` probe with
# `container_usable`, which turned "a container of that name runs other bytes"
# from a red into a skip. That fixed the PROBE and left the NAME: `vibeic-eda`
# is guessable and shared, nothing in this repo ever creates it, and whichever
# lane reached it first is what the question was being asked about.
#
# MEASURED 2026-09-10 on 8HD-8: the bare name is held by a four-day-old
# container of image 06537f7e8d3c while the pin is 89a8fd729520, so the guard
# correctly refused it — and the two TestPhase2IverilogTbFallbackEndToEnd ids
# SKIPPED even though the pinned runtime was genuinely present under its
# derived name. A skip is not a pass; the live path was simply unreachable.
#
# `default_container_name()` carries the pin digest, so it cannot be squatted,
# and it is the container `_iverilog_compile_with_sv_fallback` — which takes
# this very value as its `container` argument — will actually exec into.
_CONTAINER = _pin.default_container_name()


# A genuine modern-SystemVerilog repro that BOTH default frontends
# (`read_verilog -sv`, `iverilog -g2012`) reject — a package-scoped
# struct-typed parameter assigned via a named-field struct literal — but
# that `yosys -m slang` / `read_slang` and `sv2v` both handle. Verified
# against the iic-osic-tools container while authoring this fix:
#   read_verilog -sv → "syntax error, unexpected OP_CAST"
#   iverilog -g2012  → "syntax error"
#   read_slang       → synthesises (8 cells)
#   sv2v             → emits clean Verilog-2005
_PKG_SV = """\
package my_pkg;
  typedef struct packed { logic [7:0] a; logic [7:0] b; } pair_t;
  parameter pair_t DEFAULT_PAIR = '{a: 8'hAA, b: 8'h55};
endpackage
"""
_DUT_SV = """\
module sv_dut import my_pkg::*; (
  input  logic        clk,
  input  logic        rst_n,
  output logic [7:0]  q
);
  pair_t r;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) r <= DEFAULT_PAIR;
    else        r <= '{a: r.a + 8'd1, b: r.b};
  end
  assign q = r.a ^ r.b;
endmodule
"""


def _need_iic_eda():
    """Skip unless _CONTAINER PROVABLY runs the pinned image (#2230).

    Two earlier corrections walked toward this and stopped short. `docker
    inspect <name>` resolves IMAGES as well as containers, so the first guard
    declared the container available on any host that had merely pulled the
    image; `--type=container` fixed that, and `.State.Running` rejected a
    stopped one. What survived both is that RUNNING is still presence: on a
    multi-lane host `vibeic-eda` is a shared name, and whatever container
    reached it first answers True — including one running an image this repo
    does not pin, which then fails inside `docker exec` instead of skipping.
    That is the same sentence the two earlier comments wrote, one layer up.

    An environment-gated test must SKIP when its environment is absent, and a
    container running other bytes is exactly that: the pinned environment is
    not here.
    """
    if not shutil.which("docker"):
        skip_not_verified("docker not installed", RUN_REMEDY)
    if not _cg.container_usable(_CONTAINER):
        skip_not_verified(
            f"{_CONTAINER} is not the pinned runtime here — absent, stopped, "
            f"or a container of that name running other bytes", RUN_REMEDY)


# ---------------------------------------------------------------------------
# Shared decision logic — yosys synth signature set (default).
# Mirrors TestSynthFrontendSelection in test_phase3_backend_fixes.py.
# ---------------------------------------------------------------------------
class TestSharedSynthFrontendSelection:
    def test_default_success_no_fallback(self):
        files = ["a.sv", "b.v"]
        need, reason = sf.decide_synth_frontend(
            files, default_rc=0, default_netlist_exists=True,
            default_log="")
        assert need is False
        assert "succeeded" in reason

    def test_sv_signature_triggers_fallback(self):
        files = ["a.v"]
        need, reason = sf.decide_synth_frontend(
            files, default_rc=1, default_netlist_exists=False,
            default_log="ERROR: syntax error in package import")
        assert need is True

    def test_sv_extension_triggers_fallback_on_failure(self):
        files = ["core.sv", "pkg.sv"]
        need, reason = sf.decide_synth_frontend(
            files, default_rc=1, default_netlist_exists=False,
            default_log="some unrelated error")
        assert need is True
        assert ".sv" in reason

    def test_no_sv_no_signature_no_fallback(self):
        # Honesty gate: a plain-Verilog failure with no SV signature is a
        # REAL defect — the fallback would not help and must not fire.
        files = ["plain.v"]
        need, reason = sf.decide_synth_frontend(
            files, default_rc=1, default_netlist_exists=False,
            default_log="ERROR: undefined module foo")
        assert need is False

    def test_tok_import_signature(self):
        files = ["a.v"]
        need, _ = sf.decide_synth_frontend(
            files, default_rc=1, default_netlist_exists=False,
            default_log="unexpected TOK_IMPORT")
        assert need is True

    def test_netlist_missing_with_sv_input_triggers(self):
        # rc==0 but no netlist produced + .sv input → still fall through.
        files = ["top.sv"]
        need, _ = sf.decide_synth_frontend(
            files, default_rc=0, default_netlist_exists=False,
            default_log="")
        assert need is True


# ---------------------------------------------------------------------------
# Shared decision logic — iverilog reference-TB signature set.
# ---------------------------------------------------------------------------
class TestIverilogSvFallbackDecision:
    def test_default_success_no_fallback(self):
        files = ["dut.sv"]
        need, reason = sf.decide_iverilog_sv_fallback(
            files, default_rc=0, default_artifact_exists=True,
            default_log="")
        assert need is False

    def test_iverilog_sorry_signature_triggers(self):
        # iverilog "sorry: <feature> not supported" is the canonical
        # unsupported-SV diagnostic.
        files = ["dut.v"]
        need, _ = sf.decide_iverilog_sv_fallback(
            files, default_rc=1, default_artifact_exists=False,
            default_log="dut.v:42: sorry: constant struct not supported")
        assert need is True

    def test_iverilog_package_signature_triggers(self):
        files = ["dut.v"]
        need, _ = sf.decide_iverilog_sv_fallback(
            files, default_rc=1, default_artifact_exists=False,
            default_log="error: Unknown package my_pkg")
        assert need is True

    def test_iverilog_sv_extension_triggers_on_failure(self):
        files = ["core.sv"]
        need, reason = sf.decide_iverilog_sv_fallback(
            files, default_rc=1, default_artifact_exists=False,
            default_log="unrelated elaboration message")
        assert need is True
        assert ".sv" in reason

    def test_iverilog_real_defect_no_fallback(self):
        # Honesty gate: a plain-Verilog (.v only) failure with no SV
        # signature is a real RTL defect and must NOT trigger sv2v.
        files = ["plain.v"]
        need, _ = sf.decide_iverilog_sv_fallback(
            files, default_rc=1, default_artifact_exists=False,
            default_log="error: port a is not a port of dut")
        assert need is False

    def test_iverilog_assignment_pattern_signature(self):
        # '{field: value, ...} named-field struct literal — the exact
        # construct the session reported iverilog rejecting.
        files = ["dut.v"]
        need, _ = sf.decide_iverilog_sv_fallback(
            files, default_rc=1, default_artifact_exists=False,
            default_log="error: invalid assignment pattern in context")
        assert need is True


# ---------------------------------------------------------------------------
# Phase-2 + Phase-3 both reuse the SHARED rule (no divergent copy).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Signature-set hygiene — chip-AGNOSTIC (no chip/vendor literal).
# ---------------------------------------------------------------------------
class TestSignatureSetsAreGeneral:
    def test_no_chip_or_vendor_literal_in_signatures(self):
        joined = " ".join(sf.SLANG_ERROR_SIGNATURES
                          + sf.IVERILOG_SV_ERROR_SIGNATURES).lower()
        for banned in ("cv32e40p", "ibex", "caravel", "sky130",
                       "riscv", "rv32", "spm", "sha256"):
            assert banned not in joined

    def test_signature_sets_nonempty(self):
        assert len(sf.SLANG_ERROR_SIGNATURES) >= 3
        assert len(sf.IVERILOG_SV_ERROR_SIGNATURES) >= 3


# ---------------------------------------------------------------------------
# END-TO-END (docker-gated): the fallback must actually synthesise /
# elaborate a real modern-SV design that the default frontends reject.
# Skips cleanly when the iic-osic-tools container is unavailable.
# ---------------------------------------------------------------------------
class TestPhase2SynthFallbackEndToEnd:
    def test_slang_or_sv2v_synthesises_rejected_sv(self, tmp_path):
        _need_iic_eda()
        rtl = tmp_path / "rtl"
        rtl.mkdir()
        (rtl / "my_pkg.sv").write_text(_PKG_SV)
        (rtl / "sv_dut.sv").write_text(_DUT_SV)
        synth_dir = tmp_path / "synth"
        synth_dir.mkdir()
        out_v = synth_dir / "netlist_yosys.v"
        log = synth_dir / "yosys.log"
        # Order packages first so import resolution binds.
        rtl_strs = [str(rtl / "my_pkg.sv"), str(rtl / "sv_dut.sv")]

        # Sanity: the SHARED decision must say "fall through" for a failed
        # default attempt on these .sv inputs.
        need, _ = sf.decide_synth_frontend(
            rtl_strs, default_rc=1, default_netlist_exists=False,
            default_log="syntax error, unexpected OP_CAST")
        assert need is True



class TestPhase2IverilogTbFallbackEndToEnd:
    def test_sv2v_prepass_lets_iverilog_compile(self, tmp_path):
        _need_iic_eda()
        if not shutil.which("iverilog"):
            pytest.skip("iverilog not on host")
        rtl = tmp_path / "rtl"
        rtl.mkdir()
        (rtl / "my_pkg.sv").write_text(_PKG_SV)
        (rtl / "sv_dut.sv").write_text(_DUT_SV)
        # A plain Verilog-2005 TB that instantiates the DUT and finishes.
        tb = tmp_path / "tb_sv_dut.v"
        tb.write_text("""\
`timescale 1ns/1ps
module tb_sv_dut;
  reg clk = 0, rst_n = 0;
  wire [7:0] q;
  sv_dut dut(.clk(clk), .rst_n(rst_n), .q(q));
  always #5 clk = ~clk;
  initial begin
    #12 rst_n = 1;
    #100 $display("TB_DONE q=%0d", q);
    $finish;
  end
endmodule
""")
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        vvp = run_dir / "x.vvp"
        rtl_files = [rtl / "my_pkg.sv", rtl / "sv_dut.sv"]
        cmd = ["iverilog", "-g2012", "-DSIMULATION",
               "-o", str(vvp), str(tb)] + [str(p) for p in rtl_files]

        # Default iverilog rejects this SV (proves the gap is real).
        d_rc, d_out, d_err = p2._run(cmd, cwd=run_dir, timeout=60)
        assert d_rc != 0 or not vvp.is_file()




# ── ORGANIC E2E (opentitan_aes GDS blocker) — phase-3 -DSYNTHESIS retry decision ──
# The phase-3 yosys/slang/sv2v synth frontends hardcode -DSIMULATION; a vendor
# primitive's `ifdef SIMULATION DV-only arm ($urandom / std::randomize / slang
# "Feature unimplemented") then FAILs synth even though the identical closure
# elaborates under -DSYNTHESIS. `synth_frontend_should_retry_under_synthesis`
# decides the retry; it must fire on a sim-only signature and STAY OFF (keep the
# honest FAIL) on a genuine design error — the §4.05 no-leak boundary.
import synth_frontend as _sfmod
# vibe-ic#1128 — these skips mean A VERIFICATION DID NOT HAPPEN, not that
# one passed. Declared through `not_verified_tier` so the run's roll-up
# cannot count them under `passed`; see that module's docstring.
from _tool_probes import skip_not_verified  # noqa: E402
PULL_REMEDY = 'docker pull ghcr.io/vibeic/vibeic-eda:latest'  # the repo stores no version to cat
RUN_REMEDY = 'bash tools/vibeic-eda/restart-eda.sh'

# v1.4.x — decided by the OBSERVABLE (no netlist) + the DESIGN PROPERTY
# (the closure branches on the define set), not by the tool's phrasing.
_SIMONLY_RTL_P3 = (
    "module prim(input clk, input d, output q);\n"
    "`ifdef SIMULATION\n"
    "  initial q = $urandom;\n"
    "`else\n"
    "  logic qq; always_ff @(posedge clk) qq <= d; assign q = qq;\n"
    "`endif\n"
    "endmodule\n")


def test_synth_dsynthesis_retry_fires_on_urandom():
    ok, reason = _sfmod.synth_frontend_should_retry_under_synthesis(
        "slang: error: $urandom not allowed in a constant context",
        rtl_text_blob=_SIMONLY_RTL_P3)
    assert ok is True
    assert "-DSYNTHESIS" in reason


def test_synth_dsynthesis_retry_fires_on_std_randomize():
    ok, _ = _sfmod.synth_frontend_should_retry_under_synthesis(
        "std::randomize used in a synthesis context",
        rtl_text_blob=_SIMONLY_RTL_P3)
    assert ok is True


def test_synth_dsynthesis_retry_fires_on_slang_feature_unimplemented():
    ok, _ = _sfmod.synth_frontend_should_retry_under_synthesis(
        "error: Feature unimplemented: $value$plusargs",
        rtl_text_blob=_SIMONLY_RTL_P3)
    assert ok is True


def test_synth_dsynthesis_retry_stays_off_on_genuine_design_error():
    # NEGATIVE no-leak: a real elaboration/syntax error carries NO sim-only
    # signature → do NOT retry, keep the honest FAIL (a -DSYNTHESIS retry would
    # mask a genuine bug).
    ok, reason = _sfmod.synth_frontend_should_retry_under_synthesis(
        "ERROR: syntax error, unexpected TOK_ID at chip_top.sv:42",
        rtl_text_blob="module chip_top(input a); wire b = ; endmodule\n")
    assert ok is False
    assert "honest FAIL" in reason


def test_synth_dsynthesis_signatures_superset_of_verilator():
    # single-source-of-truth: the phase-3 set includes every verilator #668
    # signature (so the shared retry doctrine is not duplicated/divergent).
    for s in _sfmod.VERILATOR_SIMONLY_CONSTRUCT_SIGNATURES:
        assert s in _sfmod.SYNTH_FRONTEND_SIMONLY_CONSTRUCT_SIGNATURES


# ---------------------------------------------------------------------------
# CONTROLS for the two repairs above, hermetic so they run where the live path
# cannot. The falsifier runs pytest INSIDE the pinned image, which carries no
# docker client, so every container-gated test there skips; a claim that only
# the live path can falsify is a claim nothing in CI ever checks.
# ---------------------------------------------------------------------------
def test_the_container_name_is_derived_from_the_pin_not_a_bare_literal():
    """`_CONTAINER` must be COMPUTED, never a string constant.

    The bare literal `vibeic-eda` is guessable and shared; nothing in this repo
    ever creates it, so it can only ever be somebody else's container. Asking
    about it asks which lane won a race for a name. This control sits behind
    that mechanism rather than restating it: it reads this module's own AST and
    refuses a constant, so re-planting the literal fails HERE and not only on a
    host that happens to hold the pinned runtime.
    """
    import ast
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    found = [n for n in tree.body
             if isinstance(n, ast.Assign)
             and any(getattr(t, "id", None) == "_CONTAINER" for t in n.targets)]
    assert len(found) == 1, f"expected one _CONTAINER assignment, got {len(found)}"
    value = found[0].value
    assert not isinstance(value, ast.Constant), (
        "_CONTAINER is a bare string constant. The container this file execs "
        "into must be the pin-derived name `_eda_pin.default_container_name()`, "
        "which carries the digest and cannot be squatted.")
    assert isinstance(value, ast.Call), f"_CONTAINER is not derived: {ast.dump(value)}"
