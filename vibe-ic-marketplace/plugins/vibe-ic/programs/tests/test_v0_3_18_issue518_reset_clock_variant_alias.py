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
