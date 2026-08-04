#!/usr/bin/env python3
"""sdc_gen — the emitted deck must reach every port the design DECLARES.

THE DEFECT (measured on the fleet). The sign-off SDC generator splits I/O
roles over the L9 pin list plus a narrowly-gated RTL residue. Both of those
surfaces can be NARROWER than the interface the design actually presents, and
when they are, the ports nobody classified get no constraint of any kind —
no `set_input_delay`, no `set_output_delay`, no `set_false_path`. The deck is
still written, is still syntactically valid, and `sdc_gen` still exits 0. The
one program that knows the split under-covered the boundary said nothing, so
"constrained the whole boundary" and "constrained part of it" were the same
observable all the way down to the exit code, and STA reported nothing about
the untimed paths because it was never asked to.

The measured trigger is a NON-ANSI top header (`module m(a,b); input a;
output b;`): it parses with no in-line direction, which is indistinguishable
from an undirected port list, so the residue pass is deliberately disarmed —
and every port L9 did not name is then classified by nobody.

THE RULE. Assert the emitted constraint surface covers every port the design
declares, and NAME every port left unconstrained rather than leaving the gap
silent.

WHAT IT NAMES vs WHAT IT FAILS ON. It names every uncovered port. It FAILS on
the subset the role split never examined — that is the captured defect, a
split walking a surface narrower than the design. A port the split DID
examine and route and that still ends up unconstrained was lost DOWNSTREAM of
the split (the single `clock_port` slot being overwritten by a later
clock-named port is the measured case); that is a different defect with a
different fix, so it is reported and not failed on. Both are in the gate JSON.

Existing behaviour deliberately preserved:
  * the #744 tier — a layer that declares NO ports at all keeps its exit 0 and
    its own diagnostic; the gate stands down there and only adds the name;
  * a project with no resolvable top keeps the pure-L9 fallback, and its PASS
    line now says the assertion did NOT run, so silence cannot be read as
    coverage.

chip-AGNOSTIC: synthetic generic module/port names only; no design, PDK,
foundry or vendor literal appears in the fixtures or in the rule.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


# ---------------------------------------------------------------------------
# Fixtures — ONE RTL top, several L-doc surfaces over it.
# ---------------------------------------------------------------------------
#: NON-ANSI header. Every port carries a direction, but on its own `input`/
#: `output` lines, so the port list itself parses undirected — the shape that
#: disarms the residue pass.
_TOP_NON_ANSI = """\
module dut (clk, rst_n, cmd_in, status_out, busy_out);
  input        clk;
  input        rst_n;
  input  [7:0] cmd_in;
  output [7:0] status_out;
  output       busy_out;
  reg [7:0] status_out;
  reg       busy_out;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin status_out <= 8'd0; busy_out <= 1'b0; end
    else        begin status_out <= cmd_in; busy_out <= |cmd_in; end
  end
endmodule
"""

#: ANSI header, directions in line — the residue pass is armed here.
_TOP_ANSI = """\
module dut (
  input  wire       clk,
  input  wire       rst_n,
  input  wire [7:0] cmd_in,
  output reg  [7:0] status_out,
  output reg        busy_out
);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin status_out <= 8'd0; busy_out <= 1'b0; end
    else        begin status_out <= cmd_in; busy_out <= |cmd_in; end
  end
endmodule
"""

#: A top whose only ports are a clock and a reset — no data path at all. This
#: is the #744 tier: the split produces no I/O role because there is none to
#: produce, which the generator already diagnoses and deliberately exits 0 on.
_TOP_NO_DATA = """\
module dut (
  input wire aclk,
  input wire arst_n
);
endmodule
"""

_PINS_PARTIAL = [{"name": "clk", "dir": "in"},
                 {"name": "rst_n", "dir": "in"},
                 {"name": "cmd_in", "dir": "in"}]
_PINS_FULL = _PINS_PARTIAL + [{"name": "status_out", "dir": "out"},
                              {"name": "busy_out", "dir": "out"}]


def _mk(root: Path, l9_pins, rtl_text, top="dut", clock_mhz=100.0):
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(
        json.dumps({"clock_mhz": clock_mhz}), encoding="utf-8")
    doc = {"top_module": top}
    if l9_pins is not None:
        doc["top_ports"] = l9_pins
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(doc), encoding="utf-8")
    if rtl_text is not None:
        rtl = root / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / f"{top}.v").write_text(rtl_text, encoding="utf-8")
    return root


def _run(root: Path, top="dut"):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "sdc_gen.py"), str(root),
         "--top-name", top, "--force"],
        capture_output=True, text=True, cwd=str(PROGRAMS))


def _gate(root: Path):
    hits = sorted((root / "reports").rglob("sdc_gen.json"))
    assert hits, "sdc_gen wrote no gate evidence"
    return json.loads(hits[0].read_text(encoding="utf-8"))


def _sdc(root: Path, top="dut"):
    return (root / "phase2" / "stage1" / "fpga" / f"{top}.sdc").read_text(
        encoding="utf-8")


# ---------------------------------------------------------------------------
# THE DEFECT — this must FAIL against the byte-identical pre-fix generator.
# ---------------------------------------------------------------------------
def test_partial_role_split_over_a_narrower_surface_is_a_failure(tmp_path):
    """L9 names 3 of the 5 ports the RTL top declares, and the header shape
    disarms the residue pass. Pre-fix: exit 0, a deck constraining 3 ports,
    and not one word about the two outputs whose every path is untimed."""
    p = _mk(tmp_path / "partial", _PINS_PARTIAL, _TOP_NON_ANSI)
    r = _run(p)
    both = r.stdout + r.stderr

    assert r.returncode == 1, (
        "a deck that constrains PART of the declared boundary must not exit 0"
        f"\n{both}")
    # The gap is NAMED — the whole point of the rule.
    for port in ("status_out", "busy_out"):
        assert port in both, (
            f"unconstrained port {port!r} was not named in the diagnostic"
            f"\n{both}")
    # ...and it is named because it is genuinely absent from the deck, not
    # because the program guessed.
    text = _sdc(p)
    for port in ("status_out", "busy_out"):
        assert port not in text, "fixture no longer reproduces the defect"


def test_the_gap_is_recorded_as_cross_checkable_evidence(tmp_path):
    """The verdict must be re-derivable from the gate's own output — the
    declared surface, the covered subset, the uncovered names, and which of
    them the role split never examined."""
    p = _mk(tmp_path / "evidence", _PINS_PARTIAL, _TOP_NON_ANSI)
    _run(p)
    g = _gate(p)
    assert set(g["top_ports"]) == {
        "clk", "rst_n", "cmd_in", "status_out", "busy_out"}
    assert set(g["uncovered_ports"]) == {"status_out", "busy_out"}
    assert set(g["uncovered_ports_never_examined"]) == {
        "status_out", "busy_out"}
    assert g["boundary_coverage"] == "3/5"
    assert g["coverage_asserted"] is True
    # covered + uncovered must partition the declared surface, so the
    # denominator cannot be quietly shrunk.
    assert (set(g["constrained_ports"]) | set(g["uncovered_ports"])
            == set(g["top_ports"]))
    assert not (set(g["constrained_ports"]) & set(g["uncovered_ports"]))


# ---------------------------------------------------------------------------
# THE REVERSE CASES — these must STILL PASS. A rule that fires on every
# design is not a rule. Each of these holds the property legitimately, by a
# different mechanism.
# ---------------------------------------------------------------------------
def test_same_rtl_fully_covered_by_l9_still_passes(tmp_path):
    """The tightest control available: byte-identical RTL to the failing case,
    same top, same clock. ONLY the L9 coverage differs. If this also failed,
    the rule would be firing on the design rather than on the gap."""
    p = _mk(tmp_path / "full", _PINS_FULL, _TOP_NON_ANSI)
    r = _run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    g = _gate(p)
    assert g["uncovered_ports"] == []
    assert g["boundary_coverage"] == "5/5"


def test_ansi_header_recovered_by_the_residue_pass_still_passes(tmp_path):
    """Same under-covering L9 as the failing case, but an ANSI header — the
    residue pass recovers the two outputs from the RTL's own directions, so
    the boundary IS fully covered and the gate must stay quiet. This is the
    pre-existing recovery; the new assertion must not double-count it as a
    gap."""
    p = _mk(tmp_path / "ansi", _PINS_PARTIAL, _TOP_ANSI)
    r = _run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    g = _gate(p)
    assert g["uncovered_ports"] == [], (
        "the residue pass covered these ports; the assertion must see that")
    assert set(g["residue_pins_constrained"]) == {"status_out", "busy_out"}


def test_a_port_covered_only_by_false_path_counts_as_covered(tmp_path):
    """Coverage means REACH, not a particular role. `rst_n` is constrained by
    `set_false_path` and by nothing else; an assertion that only counted
    set_input_delay / set_output_delay would report it as a gap on every
    design that has a reset."""
    p = _mk(tmp_path / "falsepath", _PINS_FULL, _TOP_ANSI)
    r = _run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    text = _sdc(p)
    # rst_n appears ONLY on set_false_path lines — no I/O delay names it.
    rst_lines = [ln for ln in text.splitlines() if "rst_n" in ln]
    assert rst_lines, "fixture no longer constrains the reset at all"
    assert all(ln.lstrip().startswith("set_false_path") for ln in rst_lines), (
        "fixture changed: rst_n is no longer false_path-only\n"
        + "\n".join(rst_lines))
    g = _gate(p)
    assert "rst_n" in g["constrained_ports"]
    assert "rst_n" not in g["uncovered_ports"]


def test_no_io_role_at_all_keeps_its_own_tier_and_exit_zero(tmp_path):
    """#744's deliberate decision stands: a layer that declares no ports is
    the design's problem, not this generator's, and that tier already has its
    own diagnostic. The new gate stands down there — but it stops being
    SILENT about which port is unconstrained, which is what the rule is for."""
    p = _mk(tmp_path / "nodata", None, _TOP_NO_DATA)
    r = _run(p)
    both = r.stdout + r.stderr
    assert r.returncode == 0, (
        "the no-I/O tier must keep its exit 0 (#744)\n" + both)
    assert "constrains NO input or output path" in both, (
        "#744's diagnostic was lost\n" + both)
    g = _gate(p)
    assert g["coverage_asserted"] is False
    assert g["uncovered_ports"] == ["arst_n"]
    assert "arst_n" in both, (
        "the unconstrained port was still not named\n" + both)


def test_examined_but_lost_downstream_is_reported_not_failed(tmp_path):
    """A port the split examined and routed into the clock branch, then lost
    to the single clock-port slot, is NOT this rule's defect — the split's
    surface was wide enough. It must be named and must not fail the gate,
    so this rule cannot take credit for a hole it does not repair."""
    rtl = """\
module dut (
  input  wire       clk_a,
  input  wire       clk_b,
  input  wire       rst_n,
  input  wire [7:0] d_in,
  output reg  [7:0] d_out
);
  always @(posedge clk_a or negedge rst_n)
    if (!rst_n) d_out <= 8'd0; else d_out <= d_in;
endmodule
"""
    pins = [{"name": n, "dir": d} for n, d in
            (("clk_a", "in"), ("clk_b", "in"), ("rst_n", "in"),
             ("d_in", "in"), ("d_out", "out"))]
    p = _mk(tmp_path / "twoclk", pins, rtl)
    r = _run(p)
    both = r.stdout + r.stderr
    assert r.returncode == 0, (
        "a port lost downstream of the split is a different defect\n" + both)
    g = _gate(p)
    assert g["uncovered_ports"] == ["clk_a"], g
    assert g["uncovered_ports_never_examined"] == [], (
        "the split DID examine this port; it was lost after classification")
    assert "clk_a" in both, "the gap was left silent\n" + both


def test_unassertable_coverage_says_so_instead_of_reading_as_clean(tmp_path):
    """With no rtl/ there is no declared port list to compare the deck
    against, so the assertion cannot run. The PASS line must SAY that, or a
    silent cap reads as full coverage."""
    p = _mk(tmp_path / "nortl", _PINS_FULL, None)
    r = _run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "boundary coverage NOT ASSERTED" in r.stdout + r.stderr, (
        "an unrun assertion was reported as if it had passed\n"
        + r.stdout + r.stderr)


# ---------------------------------------------------------------------------
# The rule must not have been written as a name test.
# ---------------------------------------------------------------------------
def test_rule_is_set_arithmetic_not_a_name_heuristic():
    """Guards the chip-AGNOSTIC requirement structurally: the coverage
    computation is a set difference between the parsed top header and the
    deck's own get_ports references. If a future edit reintroduces a port-name
    substring test to decide coverage, this notices."""
    src = (PROGRAMS / "sdc_gen.py").read_text(encoding="utf-8")
    i = src.index("uncovered = sorted(")
    window = src[i:i + 400]
    assert "_ref_set" in window and "top_ports" in window
    for smell in ("_is_clock(", "_is_reset(", ".startswith(", ".lower()"):
        assert smell not in window, (
            f"coverage decided by {smell!r} rather than by set membership")
