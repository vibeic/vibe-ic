"""ORGANIC #788 — rtl_hygiene_lint.py: rule_continuous_vs_procedural_driver
(added in #782) FALSE-FIRES `multidriven-continuous-procedural` when the
continuous `assign` driver and the procedural `always` write of a net live in
DIFFERENT, mutually-exclusive conditional-generate arms of the SAME `if/else`
generate chain.

ROOT CAUSE (chip-AGNOSTIC):
  The rule reasons over the FLAT set intersection `cont_lhs & proc_lhs` within a
  module, with no model of elaboration-time generate selection. When
      if (COND) begin : gen_a  always_ff ... q <= ...  end
      else      begin : gen_b  assign q = ...          end
  only ONE arm ever elaborates, so the net has exactly ONE real driver — this is
  legitimate, synthesizable RTL (the canonical parameterised flop-vs-comb
  selection idiom). iverilog -g2012 -t null accepts it (rc=0), but the lint
  emits a block-eligible ERROR (rc=1), contradicting the reference compiler.

FIX (structural, grammar-only):
  `_generate_if_arms` returns the named-`begin:label` arm spans of every
  `if/else[-if]` generate chain in a module region (begin/end balancer robust to
  nested case/function/task/fork). `_drivers_mutually_exclusive` suppresses ONLY
  when the continuous-driver offset and the procedural-driver offset fall into
  DIFFERENT arms of the SAME chain. Touches only that one rule + two helpers.

§4.05 NO-LEAK (load-bearing — this RELAXES a block-eligible gate):
  Every GENUINE same-scope continuous+procedural race of the same net MUST STILL
  hard-block (ERROR / rc=1):
    * no-generate same-scope race (realmd shape)            -> STILL fires
    * genuine race INSIDE one generate arm (same scope)     -> STILL fires
      (and iverilog -g2012 confirms THIS one is illegal)
    * two drivers in DIFFERENT arms only suppressed, never both arms
"""
import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_LINT = _PROGRAMS / "rtl_hygiene_lint.py"


def _run(tmp_path, src, name="d.sv", severity="ERROR"):
    p = tmp_path / name
    p.write_text(src)
    jp = tmp_path / (name + ".json")
    proc = subprocess.run(
        [sys.executable, str(_LINT), "--severity", severity,
         "--json", str(jp), str(p)],
        capture_output=True, text=True)
    findings = json.loads(jp.read_text()) if jp.exists() else []
    return proc, findings


def _cp(findings):
    return [f for f in findings
            if f["rule"] == "multidriven-continuous-procedural"]


# ---------------------------------------------------------------------------
# POSITIVE (the FP being fixed) — genex shape: the always_ff write and the
# continuous assign live in OPPOSITE, mutually-exclusive generate arms. Only one
# arm elaborates, so `q` has ONE real driver. iverilog -g2012 -t null -> rc=0.
# Unpatched 1.1.0: rc=1 (FALSE multidriven-continuous-procedural). Fixed: rc=0.
# ---------------------------------------------------------------------------
_GENEX = (
    "module genex #(parameter bit USE_FF=1)"
    "(input logic clk_i, rst_ni, d_i, output logic q_o);\n"
    "  logic q;\n"
    "  if (USE_FF) begin : gen_ff\n"
    "    always_ff @(posedge clk_i or negedge rst_ni) "
    "if(!rst_ni) q<=1'b0; else q<=d_i;\n"
    "  end else begin : gen_comb\n"
    "    assign q = d_i;\n"
    "  end\n"
    "  assign q_o = q;\n"
    "endmodule\n")


def test_mutually_exclusive_generate_arms_no_longer_false_fire(tmp_path):
    proc, findings = _run(tmp_path, _GENEX, "genex.sv")
    assert proc.returncode == 0, proc.stdout
    assert _cp(findings) == [], (
        "drivers in OPPOSITE generate arms must NOT be flagged "
        "continuous+procedural (only one arm elaborates): %r" % findings)


# ---------------------------------------------------------------------------
# §4.05 NEGATIVE #1 — realmd shape: NO generate at all; a continuous assign AND
# a procedural always both drive `q` in module scope. iverilog -g2012 rejects
# it. This is the genuine race the rule exists to catch — MUST STILL fire.
# ---------------------------------------------------------------------------
_REALMD = (
    "module realmd(input logic clk_i, rst_ni, d_i, output logic q_o);\n"
    "  logic q; assign q = d_i;\n"
    "  always_ff @(posedge clk_i or negedge rst_ni) "
    "if(!rst_ni) q<=1'b0; else q<=d_i;\n"
    "  assign q_o = q;\n"
    "endmodule\n")


def test_genuine_no_generate_race_still_blocks(tmp_path):
    proc, findings = _run(tmp_path, _REALMD, "realmd.sv")
    assert proc.returncode == 1, proc.stdout
    cp = _cp(findings)
    assert any(f["symbol"] == "q" and f["severity"] == "ERROR" for f in cp), cp


# ---------------------------------------------------------------------------
# §4.05 NEGATIVE #2 (the strong one) — a GENUINE continuous+procedural race that
# lives INSIDE ONE generate arm (same scope): both drivers of `q` are in
# gen_on. The other arm (gen_off) drives `q` differently but that does NOT make
# the in-arm pair mutually exclusive. iverilog -g2012 -t null FAILS on this
# (rc!=0, "Unable to assign to unresolved wires"), so the lint MUST STILL fire.
# This proves the suppression is confined to DIFFERENT-arm pairs only.
# ---------------------------------------------------------------------------
_SAME_ARM = (
    "module samearm #(parameter bit EN=1)"
    "(input logic clk_i, rst_ni, d_i, output logic q_o);\n"
    "  logic q;\n"
    "  if (EN) begin : gen_on\n"
    "    assign q = d_i;\n"
    "    always_ff @(posedge clk_i or negedge rst_ni) "
    "if(!rst_ni) q<=1'b0; else q<=d_i;\n"
    "  end else begin : gen_off\n"
    "    assign q = 1'b0;\n"
    "  end\n"
    "  assign q_o = q;\n"
    "endmodule\n")


def test_genuine_same_arm_race_still_blocks(tmp_path):
    proc, findings = _run(tmp_path, _SAME_ARM, "samearm.sv")
    assert proc.returncode == 1, proc.stdout
    cp = _cp(findings)
    assert any(f["symbol"] == "q" and f["severity"] == "ERROR" for f in cp), cp


# ---------------------------------------------------------------------------
# Helper-level structural unit checks — import the module directly so the
# offset/arm-span model is pinned independent of the CLI plumbing.
# ---------------------------------------------------------------------------
def _import_lint():
    import importlib
    if str(_PROGRAMS) not in sys.path:
        sys.path.insert(0, str(_PROGRAMS))
    # import by canonical module name so @dataclass forward-ref resolution
    # finds the module in sys.modules (a custom-named module breaks that).
    return importlib.import_module("rtl_hygiene_lint")


def test_generate_if_arms_returns_two_mutually_exclusive_arms():
    mod = _import_lint()
    src = _GENEX
    # single module region spanning the whole source
    regions = mod._module_regions(src)
    assert len(regions) == 1
    _name, mlo, mhi = regions[0]
    groups = mod._generate_if_arms(src, mlo, mhi)
    assert len(groups) == 1, groups
    arms = groups[0]
    assert len(arms) == 2, arms
    # the always_ff (gen_ff) driver and the assign (gen_comb) driver land in
    # different arms.
    ff_off = src.index("always_ff")
    assign_off = src.index("assign q = d_i;")
    assert mod._drivers_mutually_exclusive(groups, ff_off, assign_off) is True
    # two offsets in the SAME arm (both inside gen_ff) -> NOT mutually exclusive.
    rst_off = src.index("rst_ni) q<=1'b0")
    assert mod._drivers_mutually_exclusive(groups, ff_off, rst_off) is False


def test_drivers_outside_any_group_not_suppressed():
    mod = _import_lint()
    # realmd has no generate chain at all -> no groups -> never suppress.
    regions = mod._module_regions(_REALMD)
    _name, mlo, mhi = regions[0]
    groups = mod._generate_if_arms(_REALMD, mlo, mhi)
    assert groups == [], groups
    assert mod._drivers_mutually_exclusive(groups, 5, 50) is False


def test_match_begin_end_skips_nested_case_block():
    mod = _import_lint()
    # a nested case…endcase inside the begin must not desync the balance.
    src = "begin : a case (x) 0: y=1; default: y=0; endcase z=2; end TAIL"
    end = mod._match_begin_end(src, src.index("begin"))
    # the matching `end` is right before TAIL
    assert src[end:].strip().startswith("TAIL"), src[end:]
