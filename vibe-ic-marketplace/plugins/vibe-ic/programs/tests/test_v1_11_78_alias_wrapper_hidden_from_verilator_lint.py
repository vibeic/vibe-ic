#!/usr/bin/env python3
"""An alias wrapper must be INVISIBLE to Verilator and VISIBLE to iverilog.

WHY (measured, 2026-08-24 cvdp-open run, 302 problems). `cvdp_gate` appends thin
pass-through alias wrappers so the official scorer's `iverilog -s <top>` binds
whatever name the hidden harness picked. `tb_toplevel_alias`'s own
docstring called them "dead code the scorer's `-s <top>` never elaborates, so
they are harmless". They are not.

A wrapper is instantiated by NOTHING, so `verilator --lint-only -Wall` reports
MULTITOP for it — and DECLFILENAME too when a wrapper is the file's first
module. Verilator exits non-zero on ANY warning under -Wall, so a problem whose
harness runs a scored `lint` service fails on the wrapper alone, whatever the
author wrote. In that run MULTITOP appeared in 22 of the 23 cid007 lint
failures and DECLFILENAME in 21; deleting only the wrappers from
`binary_to_gray_0013` turned the harness's own lint command to EXIT=0.

The fix is a `ifndef VERILATOR guard. It is sound because verilator is only ever
the LINTER in this track, never the simulator — every harness `.env` sets
`SIM = icarus` — while iverilog and yosys do not define VERILATOR and therefore
still see the wrapper.

These tests assert the PROPERTY (which tool sees the wrapper), not the emitted
string, so a future reformat of the wrapper cannot silently drop the guard.
"""
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "benchmark"))
import tb_toplevel_alias as A  # noqa: E402


def _mods(text):
    return re.findall(r"^\s*module\s+(\w+)", text or "", re.M)


_AUTHOR = ("module binary_to_gray (\n"
           "    input  wire [3:0] bin,\n"
           "    output wire [3:0] gray\n"
           ");\n"
           "  assign gray = bin ^ (bin >> 1);\n"
           "endmodule\n")

_ALIAS = "cvdp_copilot_binary_to_gray"


def _aliased():
    out = A.maybe_alias_completion(_AUTHOR, _ALIAS, _mods)
    assert _ALIAS in _mods(out), "fixture invalid: no alias was added"
    return out


def _strip_ifndef_verilator(text):
    """What a preprocessor with VERILATOR defined would keep."""
    return re.sub(r"(?ms)^`ifndef\s+VERILATOR\b.*?^`endif\s*$", "", text)


def test_alias_wrapper_is_guarded_from_verilator():
    """With VERILATOR defined, the wrapper is gone and the author module stays."""
    out = _aliased()
    seen_by_verilator = _mods(_strip_ifndef_verilator(out))
    assert _ALIAS not in seen_by_verilator, (
        "the alias wrapper survives into Verilator's view — it will be reported "
        "as MULTITOP and fail any `--lint-only -Wall` harness")
    assert "binary_to_gray" in seen_by_verilator, (
        "the guard swallowed the AUTHOR's module — the guard must cover only "
        "the appended wrapper")


def test_alias_wrapper_is_still_visible_without_the_define():
    """iverilog/yosys do not define VERILATOR, so the alias must remain."""
    out = _aliased()
    assert _ALIAS in _mods(out)
    assert "binary_to_gray" in _mods(out)


def test_every_guard_opened_is_closed():
    out = _aliased()
    assert out.count("`ifndef VERILATOR") == out.count("`endif"), (
        "unbalanced `ifndef/`endif would break every downstream tool")


def _have(tool, *ver):
    try:
        subprocess.run([tool, *ver], capture_output=True, check=True)
        return True
    except Exception:
        return False


def test_iverilog_still_binds_the_alias_top():
    if not _have("iverilog", "-V"):
        return
    out = _aliased()
    with tempfile.NamedTemporaryFile("w", suffix=".sv", delete=False) as f:
        f.write(out)
        path = f.name
    try:
        for top in ("binary_to_gray", _ALIAS):
            r = subprocess.run(
                ["iverilog", "-g2012", "-s", top, "-o", os.devnull, path],
                capture_output=True, text=True)
            assert r.returncode == 0, f"-s {top} failed: {r.stderr}"
    finally:
        os.unlink(path)


def test_verilator_lint_is_clean_with_the_guard():
    """The regression itself: -Wall must exit 0 on a wrapper-carrying file."""
    if not _have("verilator", "--version"):
        return
    out = _aliased()
    d = tempfile.mkdtemp()
    path = os.path.join(d, "binary_to_gray.sv")   # stem matches the author top
    with open(path, "w") as f:
        f.write(out)
    try:
        r = subprocess.run(["verilator", "--lint-only", "-Wall",
                            "-Wno-EOFNEWLINE", path],
                           capture_output=True, text=True)
        assert r.returncode == 0, (
            "verilator --lint-only -Wall rejected a wrapper-carrying file:\n"
            + r.stderr[-2000:])
    finally:
        os.unlink(path)
        os.rmdir(d)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
