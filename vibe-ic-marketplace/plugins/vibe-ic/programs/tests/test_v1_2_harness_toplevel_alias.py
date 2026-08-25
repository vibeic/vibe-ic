#!/usr/bin/env python3
"""Tests for tb_toplevel_alias — the prompt-driven alias wrapper.

Run:  python3 -m pytest test_v1_2_harness_toplevel_alias.py -q
(or)  python3 test_v1_2_harness_toplevel_alias.py   # plain asserts

COMPLIANCE NOTE (CVDP official — arXiv:2506.14074 §2 + README_NON_AGENTIC):
the alias TARGET (the top the wrapper exposes) comes from the PROMPT skeleton
(`cvdp_gate.skeleton_module_name_from_prompt`), NEVER from the hidden harness
`.env`. The former harness-`.env` readers `harness_toplevel_from_dataset` /
`load_harness_toplevels` have been DELETED — the module now carries ZERO harness
`.env` / cocotb readers (asserted here + by the dedicated
`test_cvdp_gate_alias_compliance.py` structural guard). The wrapper-correctness
tests feed a literal top name — that literal stands in for the prompt-derived
name the compliant gate supplies.

Verifies, with NO benchmark-keyword/SKU overfit (pure structural fixtures):
 1. the harness-`.env`/test_runner.py readers are GONE (deleted) AND the gate
    flow never calls them;
 2. NO-OP when the completion already declares the (prompt) toplevel
    (the §4.05 no-leak property: never touch a correct completion);
 3. alias wrapper added when the toplevel is absent, and the result
    COMPILES under iverilog -g2012 -s <toplevel> (when iverilog is present);
 4. non-ANSI / unparseable headers are left untouched (never corrupt);
 5. a case-only / id-prefix / sub-module-name mismatch all get a valid alias.
"""
import ast
import os
import re
import subprocess
import sys
import tempfile

# the module lives in the plugin's benchmark/ dir (../../benchmark relative to
# programs/tests/) — mirror the existing cvdp_gate test convention.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "benchmark"))
import tb_toplevel_alias as A  # noqa: E402
import cvdp_gate as G  # noqa: E402


def _mods(src):
    """Stand-in module-name extractor (comment-stripped) for the tests."""
    clean = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    clean = re.sub(r"//[^\n]*", " ", clean)
    return set(re.findall(r"\bmodule\s+([A-Za-z_]\w*)", clean))


# ── 0. the harness-`.env`/test_runner.py readers are DELETED (zero harness
#       readers) AND the gate emit flow never calls them (compliance) ───────────
def test_offlimits_harness_readers_are_deleted():
    """The former OFF-LIMITS harness-`.env` readers have been DELETED — the
    alias module exposes ZERO harness `.env` / cocotb readers, so there is
    nothing left to mis-wire into the scored-completion path."""
    assert not hasattr(A, "harness_toplevel_from_dataset")
    assert not hasattr(A, "load_harness_toplevels")


def test_offlimits_readers_not_wired_into_gate():
    """COMPLIANCE: the gate flow calls NEITHER OFF-LIMITS hidden-.env reader —
    the alias top must come from the PROMPT skeleton. (AST-based so comment/
    docstring mentions of the names are ignored; only a real Call trips it.)"""
    with open(G.__file__, "r", encoding="utf-8") as f:
        src = f.read()
    calls = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                calls.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                calls.add(fn.attr)
    assert "harness_toplevel_from_dataset" not in calls
    assert "load_harness_toplevels" not in calls
    # positive: the compliant PROMPT-derived source IS wired
    assert "skeleton_module_name_from_prompt" in calls


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
