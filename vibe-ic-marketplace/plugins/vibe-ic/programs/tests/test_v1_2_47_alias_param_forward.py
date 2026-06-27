#!/usr/bin/env python3
"""Tests for v1.2.47 alias-parameter-port forwarding.

Run:  python3 -m pytest test_v1_2_47_alias_param_forward.py -q
(or)  python3 test_v1_2_47_alias_param_forward.py

Why — cvdp_harness_toplevel_alias (v1.2.40) emitted `module <top>(...)`
WITHOUT parameter port list. A parameter author's port widths reference
parameter names (e.g. `[InWidth_g-1:0]`), so iverilog ELABs the wrapper with
the parameter names unbound (`Unable to bind parameter 'InWidth_g'`), which
either SILENTLY DEGRADES port widths to 1-bit (on iverilog 13) or surfaces
as ELAB errors (on iverilog 12) — both kill the harness compile and every
cocotb test loops out.

The benchmark-fail facts that motivated this fix:
  * `decode_firstbit_0001` — module `decode_firstbit` declared
    `parameter int InWidth_g = 32`, port `input [InWidth_g-1:0] In_Data`.
    Alias wrapper previously was `module cvdp_copilot_decode_firstbit (
    input [InWidth_g-1:0] In_Data )` — unbound param → FAIL.
  * `perf_counters_0001` — module `perf_counters` declared
    `parameter CNT_W = 8`, port `output wire [CNT_W-1:0] p_count_o`. Same
    bug, same FAIL.

Tests:
  1. parameter port list is forwarded into the wrapper module header.
  2. non-parameter module wrapper remains correct (no spurious `#()`).
  3. a no-op case (already-correct completion) does not regress.
  4. param-forwarding case COMPILES under iverilog -g2012 (when present).
  5. non-#_no-leak_: the 7 NON-PARAM alias-wrapped pids (e.g. findfasterclock)
     get the SAME wrapper shape they did before the patch (just port decls;
     no `#()` inserted when there are no parameters).
  6. the regex groupnamed parameter capture is intact (no false negative).
"""
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "benchmark"))
import cvdp_harness_toplevel_alias as A  # noqa: E402


def _mods(src):
    clean = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    clean = re.sub(r"//[^\n]*", " ", clean)
    return set(re.findall(r"\bmodule\s+([A-Za-z_]\w*)", clean))


# a parameter module with [InWidth_g-1:0] port widths
PARAM_MODULE = (
    "module decode_firstbit #(\n"
    "    parameter int InWidth_g = 32,\n"
    "    parameter int InReg_g   = 1,\n"
    "    parameter int OutReg_g  = 1,\n"
    "    parameter int PlRegs_g  = 1\n"
    ") (\n"
    "    input  logic                          Clk,\n"
    "    input  logic                          Rst,\n"
    "    input  logic [InWidth_g-1:0]          In_Data,\n"
    "    input  logic                          In_Valid,\n"
    "    output logic [$clog2(InWidth_g)-1:0]  Out_FirstBit,\n"
    "    output logic                          Out_Found,\n"
    "    output logic                          Out_Valid\n"
    ");\n"
    "    // body omitted for brevity\n"
    "endmodule\n"
)

# a NON-parameter module (the canonical already-passing alias case)
NONPARAM_MODULE = (
    "module FindFasterClock (\n"
    "    input  wire clk_A,\n"
    "    input  wire rst_n,\n"
    "    output reg  valid\n"
    ");\n"
    "  always @(posedge clk_A) valid <= rst_n;\n"
    "endmodule\n"
)


def test_param_port_block_returns_in_author_top_and_ports():
    """author_top_and_ports now returns a 4-tuple carrying the parameter
    block when the author header has `#(...)`."""
    res = A.author_top_and_ports(PARAM_MODULE)
    assert res is not None, "parameter module must be parseable"
    assert len(res) == 4, "v1.2.47 returns (name, ports, ansi, param_block)"
    name, ports, ansi, param_block = res
    assert name == "decode_firstbit"
    assert ports == ["Clk", "Rst", "In_Data", "In_Valid",
                     "Out_FirstBit", "Out_Found", "Out_Valid"]
    assert "#(" in param_block, "param_block must contain #( ..."
    assert "InWidth_g" in param_block
    assert "PlRegs_g" in param_block


def test_nonparam_returns_empty_param_block():
    """author_top_and_ports returns a 4-tuple with empty param_block when
    the author header has no `#(...)`."""
    res = A.author_top_and_ports(NONPARAM_MODULE)
    assert res is not None
    assert len(res) == 4
    name, ports, ansi, param_block = res
    assert name == "FindFasterClock"
    assert param_block == "", "non-param module ⇒ empty param_block"


def test_wrapper_emits_param_port_list():
    """alias_wrapper emits the #(...) parameter port list on the wrapper
    module, so iverilog can bind parameter names referenced by port widths."""
    res = A.author_top_and_ports(PARAM_MODULE)
    name, ports, ansi, param_block = res
    out = A.alias_wrapper("cvdp_copilot_decode_firstbit", name, ports,
                          ansi, param_block)
    # the wrapper module header carries the parameter block
    wrapper_section = out.split("// --- harness-toplevel alias", 1)[1]
    # exact wrapper module line(s)
    m = re.search(
        r"module\s+cvdp_copilot_decode_firstbit\b[^;]*?\)\s*\([^;]*?\)\s*;",
        wrapper_section, re.S)
    assert m is not None, f"could not locate wrapper module header: {wrapper_section[:300]!r}"
    hdr = m.group(0)
    assert "parameter" in hdr, f"wrapper header missing parameter block: {hdr}"
    assert "InWidth_g" in hdr
    assert "Out_Valid" in hdr


def test_wrapper_emits_no_spurious_param_block_when_none():
    """Non-parameter module wrapper must NOT emit `#(...)` (would be a stray
    parameter port list). The format remains `module <top> (<ports>);` —
    same shape as v1.2.40 emitted, modulo a single-space normalization
    between `<top>` and `(`."""
    res = A.author_top_and_ports(NONPARAM_MODULE)
    name, ports, ansi, param_block = res
    out = A.alias_wrapper("cvdp_copilot_findfasterclock", name, ports,
                          ansi, param_block)
    wrapper_section = out.split("// --- harness-toplevel alias", 1)[1]
    m = re.search(r"module\s+cvdp_copilot_findfasterclock[^\n]*\n.*?\)\s*;",
                  wrapper_section, re.S)
    assert m is not None
    hdr = m.group(0)
    # uniform single space between `<top>` and `(`; no spurious `#`
    assert hdr.lstrip().startswith("module cvdp_copilot_findfasterclock ("), \
        f"non-param wrapper must start with `module <top> (`, got: {hdr[:120]!r}"
    assert "#" not in hdr, "stray `#` must not appear on non-param wrapper"


def test_wrapper_emits_param_port_list_with_uniform_spacing():
    """The patched wrapper header for parameter modules is
    `module <top> #(<params>) (` — identical single-space delimiters."""
    res = A.author_top_and_ports(PARAM_MODULE)
    name, ports, ansi, param_block = res
    out = A.alias_wrapper("cvdp_copilot_decode_firstbit", name, ports,
                          ansi, param_block)
    wrapper_section = out.split("// --- harness-toplevel alias", 1)[1]
    m = re.search(
        r"module\s+cvdp_copilot_decode_firstbit[^\n]*\n.*?\)\s*\([^;]*?\)\s*;",
        wrapper_section, re.S)
    assert m is not None, f"could not locate wrapper module header: {wrapper_section[:300]!r}"
    hdr = m.group(0)
    assert " parameter" in hdr, f"wrapper header missing parameter block: {hdr}"
    assert " InWidth_g" in hdr
    assert " Out_Valid" in hdr


def test_no_leak_noop_when_toplevel_already_declared():
    """§4.05 — a completion that already declares the harness toplevel is
    returned byte-for-byte unchanged even when the module carries
    parameters. Never accidentally regenerate an already-correct RTL."""
    out = A.maybe_alias_completion(PARAM_MODULE, "decode_firstbit", _mods)
    assert out == PARAM_MODULE


def _has_iverilog():
    try:
        subprocess.run(["iverilog", "-V"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def test_param_aliased_completion_compiles():
    """The wrapped completion (with parameter port block) compiles under
    `iverilog -g2012 -s cvdp_copilot_decode_firstbit -t null`.

    The unpatched alias_wrapper emitted `module cvdp_copilot_decode_firstbit(
        input logic [InWidth_g-1:0] In_Data, ...)` referencing the
    unbound `InWidth_g` parameter — iverilog ELABs with `Unable to bind
    parameter 'InWidth_g'` and dies. The patched wrapper re-declares
    `#(parameter int InWidth_g = 32, ...)` so the port width binds.
    """
    if not _has_iverilog():
        return
    out = A.maybe_alias_completion(PARAM_MODULE,
                                   "cvdp_copilot_decode_firstbit", _mods)
    with tempfile.NamedTemporaryFile("w", suffix=".sv", delete=False) as f:
        f.write(out)
        path = f.name
    try:
        r = subprocess.run(
            ["iverilog", "-g2012", "-s", "cvdp_copilot_decode_firstbit",
             "-t", "null", path],
            capture_output=True, text=True)
        assert r.returncode == 0, \
            f"alias wrapper compile FAILED: stderr={r.stderr!r} stdout={r.stdout!r}"
    finally:
        os.unlink(path)


def test_nonparam_aliased_completion_still_compiles():
    """Regression guard: the v1.2.40 NON-parameter alias case (findfasterclock)
    must continue to compile. If the patch broke the non-param path, all 7
    non-param alias-wrapped pids (Attenuator_0001 + 6 wirings) would fail
    on every fresh run."""
    if not _has_iverilog():
        return
    out = A.maybe_alias_completion(NONPARAM_MODULE, "findfasterclock", _mods)
    with tempfile.NamedTemporaryFile("w", suffix=".sv", delete=False) as f:
        f.write(out)
        path = f.name
    try:
        r = subprocess.run(
            ["iverilog", "-g2012", "-s", "findfasterclock",
             "-t", "null", path],
            capture_output=True, text=True)
        assert r.returncode == 0, \
            f"non-param alias wrapper regressed: stderr={r.stderr!r}"
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
