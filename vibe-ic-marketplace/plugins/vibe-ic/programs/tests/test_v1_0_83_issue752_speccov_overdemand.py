"""ORGANIC #752 [P1] — spec_coverage_check --strict over-demanded TB coverage via
THREE structural-parse defects, hard-BLOCKing spec-faithful self-checking
testbenches. All fixes are contained in programs/spec_coverage_check.py.

  DEFECT 1 — reset coverage_tokens hard-coded ["reset","rst","por"] matched via
  \\b<tok>\\b never matched the dominant conventions (\\brst\\b fails inside
  rst_in/rst_n/srst; clr/sclr unmatched), so a TB driving the design's REAL
  reset port was scored UNCOVERED. FIX: derive reset coverage tokens from the
  authored RTL's actual reset port name(s) via a delimited reset-stem detector
  (matches rst_in/rst_n/srst/clr but NOT first/burst/worst).

  DEFECT 2 — an identifier-only Verilog bit-field CONCATENATION {E7..E0} was
  mis-read as an enumerated VALUE set (per-member coverage demand) and
  enum_boundary was structurally unsatisfiable for identifier-only sets. FIX:
  charge `{...}` as an enum value set only when it has >=1 hex/dec/bin literal OR
  sits in explicit set-context; auto-satisfy enum_boundary when there are no
  value-shaped members.

  DEFECT 3 — prose-fabricated phantom ports (latency/all/ports/coefficients)
  were never cross-checked against the authored RTL, so an un-coverable phantom
  port BLOCKed a correct design. FIX: drop spec-derived `port` checklist items
  absent from the authored RTL port set, but ONLY when the RTL parse yielded
  >=1 real port (so a parser miss never drops a genuine port).

§4.05 NO-LEAK (load-bearing): a TB that never drives the real reset port still
BLOCKs even with first/burst/worst decoys; a real RTL port the TB never drives
still BLOCKs; a genuine identifier enum IN set-context still GAPs when uncovered;
a value enum still demands its members + outside-set boundary.

chip-AGNOSTIC: generic reset-naming / set-builder grammar, no design literal.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import spec_coverage_check as SCC  # noqa: E402

_PROG = _PROGRAMS / "spec_coverage_check.py"


def _run(spec, rtl, tb):
    return SCC.run({"user_prompt": spec}, rtl, tb, None, True)


# ── DEFECT 1: reset tokens derived from real RTL reset port ─────────────────
def test_reset_stem_detector_matches_conventions_not_decoys():
    """The delimited reset-stem detector matches the dominant reset port naming
    conventions but NOT unrelated identifiers that merely contain the letters."""
    for good in ("rst", "rst_n", "rst_in", "srst", "sclr", "clr", "clear",
                 "reset", "reset_n", "por", "arst", "aresetn", "rstn"):
        assert SCC._is_reset_port_name(good), good
    for bad in ("first", "burst", "worst", "data", "clock", "clk", "cluster"):
        assert not SCC._is_reset_port_name(bad), bad


def test_reset_covered_when_tb_drives_real_reset_port():
    """A TB that faithfully drives the design's real reset port `rst_n` (and
    never the literal word reset/rst/por) is now scored COVERED."""
    spec = ("The module has a synchronous reset that clears all outputs.\n"
            "- input clk\n- input rst_n\n- output q\n")
    rtl = "module dut(input clk, input rst_n, output reg [7:0] q);\nendmodule\n"
    tb = ("module tb; reg clk, rst_n; wire [7:0] q;\n"
          "  initial begin rst_n=0; #10 rst_n=1; end\n"
          "endmodule\n")
    report = _run(spec, rtl, tb)
    reset = [it for it in report["items"] if it["kind"] == "reset"]
    assert reset and all(it["covered"] for it in reset), reset
    assert "rst_n" in reset[0]["coverage_tokens"]


def test_noleak_reset_decoys_do_not_satisfy():
    """§4.05: a TB that NEVER drives the real reset port `rst_n`, only decoy
    identifiers first/burst/worst, STILL gaps reset and BLOCKs under --strict."""
    spec = ("The module has a synchronous reset that clears all outputs.\n"
            "- input clk\n- input rst_n\n- output q\n")
    rtl = "module dut(input clk, input rst_n, output reg [7:0] q);\nendmodule\n"
    tb = ("module tb; reg clk; integer first, burst, worst;\n"
          "  initial begin first=0; burst=1; worst=2; end\n"
          "endmodule\n")
    report = _run(spec, rtl, tb)
    reset = [it for it in report["items"] if it["kind"] == "reset"]
    assert reset and all(it["covered"] is False for it in reset), reset
    assert report["blocked"] is True


# ── DEFECT 2: identifier concat vs value enum ────────────────────────────────
def test_identifier_concat_not_charged_as_enum():
    """An identifier-only Verilog bit-field CONCATENATION {E7..E0} (no value
    literal, no set-context) is NOT charged as an enumerated value set."""
    spec = ("The output is assembled as {E7, E6, E5, E4, E3, E2, E1, E0}\n"
            "from the decode table.\n- input clk\n- output [7:0] e\n")
    rtl = "module dut(input clk, output [7:0] e);\nendmodule\n"
    tb = "module tb; reg clk; wire [7:0] e; endmodule\n"
    report = _run(spec, rtl, tb)
    enum_kinds = [it["kind"] for it in report["items"]
                  if it["kind"] in ("enum_set", "enum_boundary")]
    assert enum_kinds == [], enum_kinds


def test_is_value_enum_helper_decisions():
    """Unit: value-shaped members accept; identifier-only accepts only in
    explicit set-context; bare identifier concat rejects."""
    assert SCC._is_value_enum("0,1,2", ["0", "1", "2"], "anything") is True
    assert SCC._is_value_enum(
        "IDLE,RUN,DONE", ["IDLE", "RUN", "DONE"],
        "state is one of {IDLE, RUN, DONE}") is True
    assert SCC._is_value_enum(
        "E7,E6,E5", ["E7", "E6", "E5"], "assembled as {E7,E6,E5}") is False


def test_noleak_value_enum_still_demands_members_and_boundary():
    """§4.05: a real VALUE enum {0,1,2,3} with an outside-set boundary still
    charges enum_set + enum_boundary and gaps when the TB under-covers."""
    spec = ("mode is one of {0, 1, 2, 3}; any other value gives error.\n"
            "- input [1:0] mode\n- output err\n")
    rtl = "module dut(input [1:0] mode, output err);\nendmodule\n"
    tb = "module tb; reg [1:0] mode; wire err; initial mode=0; endmodule\n"
    report = _run(spec, rtl, tb)
    kinds = {it["kind"] for it in report["items"]}
    assert "enum_set" in kinds and "enum_boundary" in kinds, kinds
    # TB only drives member 0 → outside-set boundary uncovered → block
    boundary = [it for it in report["items"] if it["kind"] == "enum_boundary"]
    assert boundary and boundary[0]["covered"] is False
    assert report["blocked"] is True


def test_noleak_identifier_enum_in_set_context_still_gaps():
    """§4.05: a genuine identifier enum IN explicit set-context still emits
    enum_set and GAPs when the TB does not cover its members."""
    spec = ("state is one of {IDLE, RUN, DONE}.\n"
            "- input clk\n- output [1:0] st\n")
    rtl = "module dut(input clk, output [1:0] st);\nendmodule\n"
    tb = "module tb; reg clk; wire [1:0] st; endmodule\n"
    report = _run(spec, rtl, tb)
    enum_set = [it for it in report["items"] if it["kind"] == "enum_set"]
    assert enum_set, "identifier enum in set-context must still charge"
    assert enum_set[0]["covered"] is False
    assert report["blocked"] is True


# ── DEFECT 3: phantom-port RTL cross-check ──────────────────────────────────
def test_phantom_port_dropped_when_rtl_has_real_ports():
    """A spec-derived phantom 'latency' port (absent from the authored RTL) is
    dropped, so the correct design is not blocked by an un-coverable phantom."""
    spec = ("Output latency is 1 clock cycle.\n"
            "- input clk\n- input d\n- output q\n")
    rtl = "module dut(input clk, input d, output q);\nendmodule\n"
    tb = ("module tb; reg clk, d; wire q;\n"
          "  initial begin clk=0; d=1; @(posedge clk); end\n"
          "endmodule\n")
    report = _run(spec, rtl, tb)
    port_tokens = [it["coverage_tokens"][0]
                   for it in report["items"] if it["kind"] == "port"]
    assert set(port_tokens) <= {"clk", "d", "q"}, port_tokens
    assert "latency" not in port_tokens


def test_noleak_real_uncovered_port_still_blocks():
    """§4.05: a REAL RTL port the TB never drives is KEPT (present in the RTL
    port set), so it still gaps and BLOCKs under --strict."""
    spec = ("- input clk\n- input rst_n\n- input data_in\n- output result\n")
    rtl = ("module dut(input clk, input rst_n, input data_in, "
           "output result);\nendmodule\n")
    tb = "module tb; reg clk; initial clk=0; endmodule\n"  # drives nothing else
    report = _run(spec, rtl, tb)
    uncovered = {it["coverage_tokens"][0]
                 for it in report["items"]
                 if it["kind"] == "port" and it["covered"] is False}
    assert {"data_in", "result"} <= uncovered, uncovered
    assert report["blocked"] is True


def test_noleak_parser_miss_does_not_drop_ports():
    """§4.05: when the RTL port parse yields NO usable port (empty set), the
    cross-check is SKIPPED so a genuine spec port is never silently dropped."""
    spec = "- input clk\n- input d\n- output q\n"
    rtl_unparseable = "// no module here, just a comment\n"
    tb = "module tb; reg clk; endmodule\n"
    report = _run(spec, rtl_unparseable, tb)
    port_tokens = {it["coverage_tokens"][0]
                   for it in report["items"] if it["kind"] == "port"}
    # all three spec ports preserved (no drop on a parser miss)
    assert {"clk", "d", "q"} <= port_tokens, port_tokens


# ── END-STATE via the real program CLI (the issue's 驗收 shape) ──────────────
def test_endstate_real_reset_tb_passes_strict(tmp_path):
    """END-STATE through the real CLI: a faithful TB driving rst_n no longer
    gaps reset (reset GAP under shipped -> OK under patch)."""
    sp = tmp_path / "spec.txt"
    rp = tmp_path / "rtl.sv"
    tp = tmp_path / "tb.sv"
    sp.write_text("The module has a synchronous reset clearing the counter.\n"
                  "- input clk\n- input rst_n\n- output [7:0] cnt\n")
    rp.write_text("module dut(input clk, input rst_n, "
                  "output reg [7:0] cnt);\nendmodule\n")
    tp.write_text("module tb; reg clk, rst_n; wire [7:0] cnt;\n"
                  "  initial begin rst_n=0; clk=0; #10 rst_n=1; "
                  "@(posedge clk); end\n"
                  "endmodule\n")
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--spec", str(sp), "--rtl", str(rp),
         "--tb", str(tp), "--strict"], capture_output=True, text=True)
    assert cp.returncode == 0, (cp.returncode, cp.stdout, cp.stderr)
    assert "reset behavior" in cp.stdout  # the item exists ...
    assert "(UNCOVERED)" not in cp.stdout.split("reset behavior", 1)[1][:80], \
        cp.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
