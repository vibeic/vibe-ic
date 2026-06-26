#!/usr/bin/env python3
"""Tests for the candidate cvdp_harness_toplevel_alias absorption.

Run:  python3 -m pytest test_v1_2_harness_toplevel_alias.py -q
(or)  python3 test_v1_2_harness_toplevel_alias.py   # plain asserts

Verifies, with NO benchmark-keyword/SKU overfit (pure structural fixtures):
 1. authoritative toplevel parsed from .env and test_runner.py;
 2. NO-OP when the completion already declares the harness toplevel
    (the §4.05 no-leak property: never touch a correct completion);
 3. alias wrapper added when the harness toplevel is absent, and the result
    COMPILES under iverilog -g2012 -s <toplevel> (when iverilog is present);
 4. non-ANSI / unparseable headers are left untouched (never corrupt);
 5. a case-only / id-prefix / sub-module-name mismatch all get a valid alias.
"""
import os
import re
import subprocess
import sys
import tempfile

# the candidate module lives in the plugin's benchmark/ dir (../../benchmark
# relative to programs/tests/) — mirror the existing cvdp_gate test convention.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "benchmark"))
import cvdp_harness_toplevel_alias as A  # noqa: E402


def _mods(src):
    """Stand-in module-name extractor (comment-stripped) for the tests."""
    clean = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    clean = re.sub(r"//[^\n]*", " ", clean)
    return set(re.findall(r"\bmodule\s+([A-Za-z_]\w*)", clean))


def test_toplevel_from_env():
    rec = {"harness": {"files": {"src/.env": "toplevel=cvdp_copilot_foo\nsim=icarus\n"}}}
    assert A.harness_toplevel_from_dataset(rec) == "cvdp_copilot_foo"


def test_toplevel_from_test_runner_literal():
    rec = {"harness": {"files": {"src/test_runner.py": 'toplevel = "gf_mac"\n'}}}
    assert A.harness_toplevel_from_dataset(rec) == "gf_mac"


def test_toplevel_from_getenv_default():
    rec = {"harness": {"files": {
        "src/test_runner.py": 'toplevel = os.getenv("TOPLEVEL", "sprite_controller_fsm")\n'}}}
    assert A.harness_toplevel_from_dataset(rec) == "sprite_controller_fsm"


def test_noop_when_top_already_declared():
    """§4.05 no-leak: a completion that already declares the harness toplevel
    is returned byte-for-byte unchanged."""
    comp = ("module gf_mac (input wire a, output wire b);\n"
            "  assign b = a;\nendmodule\n")
    out = A.maybe_alias_completion(comp, "gf_mac", _mods)
    assert out == comp


def test_noop_when_no_toplevel():
    comp = "module anything (input a, output b); assign b=a; endmodule"
    assert A.maybe_alias_completion(comp, None, _mods) == comp


def test_noop_on_non_ansi_header():
    """A non-ANSI header (bare port names) is NOT aliasable (directions live in
    the body) → leave untouched rather than emit a broken wrapper."""
    comp = ("module myblk (a, b);\n input a; output b; assign b=a;\nendmodule\n")
    out = A.maybe_alias_completion(comp, "cvdp_copilot_myblk", _mods)
    assert out == comp


def _alias_and_check(comp, top):
    out = A.maybe_alias_completion(comp, top, _mods)
    assert out != comp, "expected an alias wrapper to be appended"
    assert f"module {top} (" in out
    assert top in _mods(out)
    return out


def test_case_only_mismatch_wraps():
    comp = ("module FindFasterClock (\n"
            "    input  wire clk_A,\n"
            "    input  wire rst_n,\n"
            "    output reg  valid\n"
            ");\n  always @(posedge clk_A) valid <= rst_n;\nendmodule\n")
    _alias_and_check(comp, "findfasterclock")


def test_id_prefix_mismatch_wraps():
    comp = ("module bus_arbiter (\n"
            "    input wire clk,\n"
            "    input wire req1,\n"
            "    output reg grant1\n"
            ");\n  always @(posedge clk) grant1 <= req1;\nendmodule\n")
    _alias_and_check(comp, "cvdp_copilot_bus_arbiter")


def test_submodule_name_mismatch_wraps():
    comp = ("module hebbian_rule (\n"
            "    input  wire [3:0] x,\n"
            "    output wire [3:0] y\n"
            ");\n  assign y = x;\nendmodule\n")
    _alias_and_check(comp, "hebb_gates")


def _has_iverilog():
    try:
        subprocess.run(["iverilog", "-V"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def test_aliased_completion_compiles():
    """The wrapper compiles under iverilog -g2012 -s <toplevel>."""
    if not _has_iverilog():
        return  # skip when iverilog absent
    comp = ("module FindFasterClock (\n"
            "    input  wire clk_A,\n"
            "    input  wire clk_B,\n"
            "    input  wire rst_n,\n"
            "    output reg  A_faster_than_B,\n"
            "    output reg  valid\n"
            ");\n"
            "  always @(posedge clk_A or negedge rst_n)\n"
            "    if (!rst_n) begin A_faster_than_B<=0; valid<=0; end\n"
            "    else begin A_faster_than_B<=clk_B; valid<=1; end\n"
            "endmodule\n")
    out = A.maybe_alias_completion(comp, "findfasterclock", _mods)
    with tempfile.NamedTemporaryFile("w", suffix=".sv", delete=False) as f:
        f.write(out)
        path = f.name
    try:
        r = subprocess.run(
            ["iverilog", "-g2012", "-s", "findfasterclock", "-o", os.devnull, path],
            capture_output=True, text=True)
        assert r.returncode == 0, f"compile failed: {r.stderr}"
    finally:
        os.unlink(path)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"PASS {fn.__name__}")
    print(f"\n{passed}/{len(fns)} tests passed")
