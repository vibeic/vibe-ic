"""ORGANIC #701 — RTL module-name enumerator regex blind to the SV-2012
`module X import pkg::*;` header-package-import declaration form.

ROOT CAUSE: `_MODULE_HEADER_RE` matched only `module <name> [#(...)] (...)` —
it did NOT tolerate a header-package-import clause between the module name and
the optional param block / port list. So `_v661_rtl_module_names` dropped every
`module <name> import pkg::*;` top/leaf from the resolver candidate set. On a
real reused-IP SoC the AES core hierarchy (each `module <name>\n import ...;`)
went MISSING, and the resolver's instantiation-graph-root fallback — seeded from
the SAME broken enumerator — could silently bind+synth+TB-verify a trivial
visible leaf instead of the real design core: a SILENT FALSE-PASS.

FIX: extend `_MODULE_HEADER_RE` to tolerate a REPEATED, optional package-import
clause (`(?:import\\s+[^;]+;\\s*)*`) before the optional `#(...)` param block /
`(...)` port list. The clause MUST be REPEATED (`*`, not `?`) — real designs
chain MULTIPLE `import` statements; a single optional clause would still drop
every module past the first import on a multi-import header.

DEFENSE-IN-DEPTH: `_v701_tiny_root_warn` WARNs (never silently PASSes) when the
bound DUT is a tiny/leaf module while larger un-instantiated modules exist on
disk that the narrow enumerator did not offer — so a future enumerator gap
surfaces loudly instead of recurring as a silent false-PASS.

POSITIVE: single-import / MULTI-import / multi-line import-header modules are
enumerated; the graph-root resolver no longer drops the real core.
§4.05 NO-LEAK: plain `module foo (...)` and `module foo #(...) (...)` still match
exactly as before (no regression); the repeated-import tolerance does NOT
over-match (it does not swallow a following module); the tiny-root WARN fires
only when a larger un-enumerated module genuinely exists.

chip-AGNOSTIC: pure SV header grammar + structural size/instantiation compare;
no chip/SKU/vendor literal.
"""
import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402


# ── the regex itself ─────────────────────────────────────────────────────────
def _names(text):
    return [m[0] for m in R._MODULE_HEADER_RE.findall(text)]


def test_plain_header_still_matches():
    # §4.05 — the legacy plain form is unchanged.
    assert _names("module foo (input a);") == ["foo"]


def test_param_header_still_matches():
    # §4.05 — the legacy `#(...)` param form is unchanged.
    assert _names("module foo #(parameter W=8) (input a);") == ["foo"]


def test_single_import_header_now_matches():
    # POSITIVE — the previously-dropped single-import form.
    assert _names("module foo import pkg::*; (input a);") == ["foo"]


def test_multi_import_header_now_matches():
    # POSITIVE — the CRITICAL case: chained imports. A single optional clause
    # (`?`) would drop this; the repeated clause (`*`) must catch it.
    txt = ("module aes_core import aes_pkg::*; import prim_pkg::*; "
           "(input a);")
    assert _names(txt) == ["aes_core"]


def test_multiline_import_header_now_matches():
    # POSITIVE — the real reused-IP shape: name + newline + import lines.
    txt = ("module aes_core\n"
           "  import aes_pkg::*;\n"
           "  import prim_pkg::*;\n"
           "  (input a);")
    assert _names(txt) == ["aes_core"]


def test_import_plus_param_header_matches():
    # POSITIVE — import clause(s) AHEAD of the `#(...)` param block.
    txt = "module foo import pkg::*; #(parameter W=8) (input a);"
    assert _names(txt) == ["foo"]


def test_no_overmatch_does_not_swallow_following_module():
    # §4.05 NO-LEAK — the `[^;]+;` import clause stops at its own `;`, so an
    # import-header module followed by a second module yields BOTH, not one
    # giant swallow.
    txt = ("module aes_core import aes_pkg::*; (input a); endmodule\n"
           "module prim_subreg (input b); endmodule")
    assert _names(txt) == ["aes_core", "prim_subreg"]


# ── the enumerator + resolver against a real reused-IP-shaped rtl/ ───────────
def _write_rtl(tmp_path):
    """A mini AES-core-shaped hierarchy: every internal module uses the
    header-import form; the single top (aes) instantiates aes_core, which
    instantiates the leaves. NONE is `module X (...)` plain except the TB-
    visible trivial leaf, which is what the broken enumerator would have left
    as the only enumerable graph-root."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "aes_pkg.sv").write_text("package aes_pkg; endpackage\n")
    (rtl / "aes.sv").write_text(
        "module aes\n  import aes_pkg::*;\n (input clk, input reset_n);\n"
        "  aes_core u_core (.clk(clk), .reset_n(reset_n));\n"
        "endmodule\n")
    (rtl / "aes_core.sv").write_text(
        "module aes_core\n  import aes_pkg::*;\n  import prim_pkg::*;\n"
        " (input clk, input reset_n);\n"
        "  aes_cipher_core u_cipher (.clk(clk));\n"
        "  prim_subreg u_reg (.clk(clk));\n"
        "endmodule\n")
    (rtl / "aes_cipher_core.sv").write_text(
        "module aes_cipher_core import aes_pkg::*; (input clk);\n"
        "endmodule\n")
    (rtl / "prim_subreg.sv").write_text(
        "module prim_subreg import prim_pkg::*; (input clk);\n"
        "endmodule\n")
    return rtl


def test_enumerator_includes_all_import_header_modules(tmp_path):
    _write_rtl(tmp_path)
    names = R._v661_rtl_module_names(tmp_path)
    # POSITIVE — the entire import-header hierarchy is now enumerated (it was
    # ENTIRELY MISSING before the fix).
    for expected in ("aes", "aes_core", "aes_cipher_core", "prim_subreg"):
        assert expected in names, f"{expected} dropped by enumerator: {names}"


def test_resolver_binds_real_top_not_dropped_leaf(tmp_path):
    _write_rtl(tmp_path)
    # The resolver's graph-root fallback (clause c) must now find `aes` (the
    # one module nobody instantiates) — NOT fall through / pick a leaf, which
    # is exactly the silent-false-PASS the bug enabled.
    resolved = R._v661_resolve_dut_module(tmp_path, top_name="not_a_module",
                                          l9_top_module=None)
    assert resolved == "aes", resolved


# ── defense-in-depth tiny-root WARN ──────────────────────────────────────────
def test_tiny_root_warn_fires_on_leaf_with_larger_unenumerated(tmp_path):
    """Simulate a residual enumerator gap: a large module exists on disk that
    nobody instantiates, but the resolver bound a trivial leaf. The backstop
    must WARN (loud, not silent)."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    # A tiny leaf (the wrongly-bound DUT).
    (rtl / "tiny.sv").write_text(
        "module tiny (input a);\nendmodule\n")
    # A large, un-instantiated module the enumerator should have offered.
    big_body = "\n".join(f"  wire w{i};" for i in range(60))
    (rtl / "big.sv").write_text(
        "module big import pkg::*; (input clk);\n" + big_body + "\nendmodule\n")
    warn = R._v701_tiny_root_warn(tmp_path, "tiny")
    assert warn, "tiny-root WARN should fire"
    assert "WARN #701" in warn
    assert "big" in warn


def test_tiny_root_warn_silent_when_bound_dut_is_the_big_module(tmp_path):
    # §4.05 NO-LEAK — when the resolver correctly bound the large top, the
    # backstop stays SILENT (no spurious WARN on a healthy design).
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "tiny.sv").write_text("module tiny (input a);\nendmodule\n")
    big_body = "\n".join(f"  wire w{i};" for i in range(60))
    (rtl / "big.sv").write_text(
        "module big (input clk);\n" + big_body
        + "\n  tiny u_t (.a(clk));\nendmodule\n")
    warn = R._v701_tiny_root_warn(tmp_path, "big")
    assert warn == "", f"unexpected WARN on healthy big-top design: {warn}"


def test_tiny_root_warn_silent_single_module(tmp_path):
    # §4.05 NO-LEAK — a single-module design has nothing larger to compare to.
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "only.sv").write_text("module only (input a);\nendmodule\n")
    assert R._v701_tiny_root_warn(tmp_path, "only") == ""


def test_repeated_import_clause_is_starred_not_optional():
    # Pin the REGEX SOURCE: the import clause must be `*`-repeated, not a single
    # `?`. A `?`-only clause is the silent-shrink trap #701 warns against.
    src = R._MODULE_HEADER_RE.pattern
    assert "import" in src
    # The import group is followed by `*` (repeated), never a lone `?`.
    assert re.search(r"import.*?;.*?\)\*", src) or "import\\s+[^;]+;\\s*)*" in src
