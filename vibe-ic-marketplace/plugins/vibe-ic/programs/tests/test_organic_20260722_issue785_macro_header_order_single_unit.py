#!/usr/bin/env python3
"""Regression for ORGANIC-20260722 #785 — the ASIC synth compile set handed the
frontend a file referencing a `` `MACRO `` that no earlier file had defined,
although the defining header was RIGHT THERE in the same set.

Two independent causes, BOTH required for a fix (proved below):

(1) ORDER. Both synth source selectors (`design_one_shot_runner.
    _select_asic_rtl_sources` and `phase3_one_shot_runner.step_synth`) emitted
    plain RTL alphabetically. A macro header named `defines.v` therefore sorts
    AFTER a consumer named `caravel_user_project.v` — and the auto-emitted
    `<top>.v` wrapper is exactly such a consumer, because it copies the wrapped
    DUT's port block verbatim (macro width expressions included). #682 already
    hoists PACKAGES for the identical reason (a definition must precede its
    use); preprocessor definitions were never given the same treatment.

    `_rtl_include_hub.macro_headers_first` ALREADY existed as the single source
    of truth for this ordering — its docstring names this exact failure — but
    only `lec_run`'s gold read consumed it. The fix wires the two synth
    selectors to that same helper rather than adding a third copy.

(2) COMPILATION UNIT. SystemVerilog's DEFAULT is one compilation unit PER FILE,
    under which preprocessor state never crosses a file boundary at all. Without
    `--single-unit`, `read_slang` cannot see `defines.v`'s macros from any other
    file REGARDLESS of order. `lec_run` already reads its gold set with
    `--single-unit` for this documented reason; the synth path did not.

Observed on caravel_user_project x sky130A (phase3 synth, rc=1):

    error: unknown macro or compiler directive '`MPRJ_IO_PADS'
        input  [`MPRJ_IO_PADS-1:0] io_in,
    error: range of selection [37:30] from 'logic[-1:0]' is reversed
    Build failed: 11 errors, 0 warnings

The reversed-range cascade is the same defect: with the width macro unresolved
the port degrades to `logic[-1:0]`, so every legitimate part-select is then
reported as reversed.

MEASURED (yosys 0.67+ / read_slang, the real caravel source set) — this is why
neither half alone is the fix:

    A  alphabetical order, no --single-unit  → 8 "unknown macro" errors
    B  alphabetical order, --single-unit     → 4 "unknown macro" errors
    C  header-first,       --single-unit     → CLEAN (38 ports, 1274 port bits)

chip-AGNOSTIC: a "macro header" is identified STRUCTURALLY (defines >= 1 macro,
declares NO module), so hoisting it can only add preprocessor state that later
files may consume — never change elaboration. A source set with no such file is
byte-identical (test_noleak_*).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import design_one_shot_runner as P  # noqa: E402

_DEFINES = """\
// pure macro header — no module
`define MPRJ_IO_PADS_1 19
`define MPRJ_IO_PADS_2 19
`define MPRJ_IO_PADS (`MPRJ_IO_PADS_1 + `MPRJ_IO_PADS_2)
"""

_CONSUMER = """\
`default_nettype none
module caravel_user_project (
    input  [`MPRJ_IO_PADS-1:0] io_in,
    output [`MPRJ_IO_PADS-1:0] io_out
);
    assign io_out = io_in;
endmodule
`default_nettype wire
"""

_PLAIN = """\
module zzz_plain (input a, output b);
    assign b = a;
endmodule
"""


def _mk(tmp_path: Path, files: dict) -> Path:
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    for name, text in files.items():
        (rtl / name).write_text(text)
    return rtl


# ── the defect: ORDER ───────────────────────────────────────────────────
def test_macro_header_precedes_its_consumer(tmp_path):
    """`defines.v` sorts AFTER `caravel_user_project.v` alphabetically — the
    exact caravel shape. The header must still come first."""
    rtl = _mk(tmp_path, {"defines.v": _DEFINES,
                         "caravel_user_project.v": _CONSUMER})
    order = [p.name for p in P._select_asic_rtl_sources(rtl)]
    assert order.index("defines.v") < order.index("caravel_user_project.v")


def test_full_caravel_shape_order(tmp_path):
    """Every header ahead of every design file, headers' relative order kept."""
    rtl = _mk(tmp_path, {
        "defines.v": _DEFINES,
        "user_defines.v": "`define USER_X 1\n",
        "caravel_user_project.v": _CONSUMER,
        "user_proj_example.v": _PLAIN.replace("zzz_plain", "user_proj_example"),
        "user_project_wrapper.v": _PLAIN.replace("zzz_plain",
                                                 "user_project_wrapper"),
    })
    order = [p.name for p in P._select_asic_rtl_sources(rtl)]
    assert order[:2] == ["defines.v", "user_defines.v"], order
    assert set(order[2:]) == {"caravel_user_project.v",
                              "user_proj_example.v",
                              "user_project_wrapper.v"}


def test_header_detection_is_structural_not_name_based(tmp_path):
    """A header named so it ALREADY sorts first must not be the only case that
    works, and a file merely NAMED `defines` that declares a module is NOT a
    header (moving it could change elaboration)."""
    rtl = _mk(tmp_path, {
        "aaa_defines.v": "`define X 1\nmodule aaa_defines(input a); endmodule\n",
        "zzz_real_header.v": _DEFINES,
        "bbb_design.v": _CONSUMER,
    })
    order = [p.name for p in P._select_asic_rtl_sources(rtl)]
    assert order[0] == "zzz_real_header.v", order
    # the module-declaring file stays in the ordinary group
    assert order.index("aaa_defines.v") > 0


# ── the defect: COMPILATION UNIT ────────────────────────────────────────
def test_every_read_slang_call_site_uses_single_unit():
    """Ordering alone cannot help under SV's default file-per-compilation-unit
    semantics. EVERY read_slang invocation that reads a multi-file design must
    pass --single-unit, or macros never cross a file boundary. phase3 was the
    site that kept the caravel run failing after phase2 was already fixed —
    which is precisely why this asserts over all of them, not just one."""
    import re as _re
    for mod in ("design_one_shot_runner.py", "phase3_one_shot_runner.py",
                "lec_run.py"):
        src = (PROG_DIR / mod).read_text()
        sites = _re.findall(r"read_slang(?: --single-unit)? \{", src)
        assert sites, f"{mod}: no read_slang call site found — test is stale"
        bare = [s for s in sites if "--single-unit" not in s]
        assert not bare, f"{mod}: {len(bare)} read_slang site(s) without --single-unit"


def test_phase3_comment_claim_now_matches_behaviour():
    """phase3's own comment claimed "All RTL read together in one slang
    compilation unit" while the flag that makes it true was never passed. Pin
    the claim to the code."""
    src = (PROG_DIR / "phase3_one_shot_runner.py").read_text()
    assert "one slang compilation unit" in src
    assert "read_slang --single-unit {slang_files}" in src


def test_phase3_orders_macro_headers_first():
    """phase3 builds its OWN source list; it must use the shared helper too."""
    src = (PROG_DIR / "phase3_one_shot_runner.py").read_text()
    assert "_macro_headers_first(pkg_files + other)" in src


def test_selectors_share_one_ordering_implementation():
    """No third copy: both synth selectors delegate to _rtl_include_hub."""
    d = (PROG_DIR / "design_one_shot_runner.py").read_text()
    assert "_hub.macro_headers_first(" in d
    p3 = (PROG_DIR / "phase3_one_shot_runner.py").read_text()
    assert "from _rtl_include_hub import macro_headers_first" in p3


# ── no-leak ─────────────────────────────────────────────────────────────
def test_noleak_no_macro_header_is_identity(tmp_path):
    """A source set with no pure-header file must be ordered exactly as before
    (alphabetical within the .sv-then-.v grouping)."""
    rtl = _mk(tmp_path, {
        "b_mod.v": _PLAIN.replace("zzz_plain", "b_mod"),
        "a_mod.v": _PLAIN.replace("zzz_plain", "a_mod"),
    })
    assert [p.name for p in P._select_asic_rtl_sources(rtl)] == [
        "a_mod.v", "b_mod.v"]


def test_noleak_packages_still_precede_rtl(tmp_path):
    """#682's package hoist must survive #785's header hoist."""
    rtl = _mk(tmp_path, {
        "defines.v": _DEFINES,
        "a_pkg.sv": "package a_pkg; parameter W = 4; endpackage\n",
        "z_design.sv": "module z_design(input a); endmodule\n",
    })
    order = [p.name for p in P._select_asic_rtl_sources(rtl)]
    assert order[0] == "defines.v"
    assert order.index("a_pkg.sv") < order.index("z_design.sv")


def test_noleak_testbenches_still_excluded(tmp_path):
    rtl = _mk(tmp_path, {"defines.v": _DEFINES,
                         "tb_top.v": _PLAIN.replace("zzz_plain", "tb_top"),
                         "d.v": _PLAIN.replace("zzz_plain", "d")})
    names = [p.name for p in P._select_asic_rtl_sources(rtl)]
    assert "tb_top.v" not in names


# ── helper contract ─────────────────────────────────────────────────────
def test_helper_is_identity_on_unreadable_file(tmp_path):
    import _rtl_include_hub as _hub
    missing = tmp_path / "gone.v"
    assert _hub.macro_headers_first([missing]) == [missing]


def test_helper_ignores_define_inside_a_comment(tmp_path):
    rtl = _mk(tmp_path, {
        "commented.v": "// `define NOT_REAL 1\nmodule commented(input a);"
                       " endmodule\n",
        "real_hdr.v": _DEFINES,
    })
    import _rtl_include_hub as _hub
    files = sorted(rtl.glob("*.v"))
    out = [p.name for p in _hub.macro_headers_first(files)]
    assert out[0] == "real_hdr.v", out
