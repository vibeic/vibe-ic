#!/usr/bin/env python3
"""ORGANIC #697 [P1, chip-AGNOSTIC] — spec-first coverage attribution gate.

DOCTRINE: a hidden scoring TB is generated from the SAME spec the author sees,
so a verification FAILURE is almost always ONE OF OUR OWN GAPS — (1) a
SPEC-EXTRACTION gap (the requirement exists somewhere in the input chain but we
dropped it before some downstream station) or (2) a TESTBENCH-COVERAGE gap (we
extracted it but our self-TB never exercised it). "Spec" is the WHOLE input
chain: prompt (USER) -> fact graph (IC Expert Agent) -> L1-L23 (IC expert). FLOOR is
allowed ONLY when the failing thing is NOWHERE in the chain, with cited
evidence of the stations searched.

POSITIVE:
  * 驗收 END-STATE: the encoder enumerated-set instance -> the checklist flags
    the outside-the-set/default boundary + reset + 1-cycle latency as
    TESTBENCH-COVERAGE GAPs, rc non-zero in --strict.
  * a port / table-row / reset / worked-example requirement is extracted +
    coverage-attributed.
  * which-station routing: a requirement present in the PROMPT but absent from
    the L-docs -> extraction-gap routed to ic-expert (L-doc completion); held at
    fact-graph but dropped by L-docs -> ic-expert; held at L-docs but failing ->
    spec-to-rtl extraction; extracted-but-untested -> TB-coverage gap.

§4.05 NEGATIVE no-leak:
  * a genuinely chain-ABSENT requirement (a white-box internal name the chain
    never states) is NOT fabricated into the checklist / NOT charged as our gap
    (spec-absent, with the searched stations as evidence);
  * a fully-covered spec reports NO coverage gap (rc 0 even in --strict);
  * advisory WARN does NOT hard-block in non-strict (rc 0);
  * the program reads ONLY chain stations + RTL + TB — it has NO oracle / hidden
    TB input (asserted on the CLI surface).
"""
from __future__ import annotations

import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
PROG = PROGRAMS / "spec_coverage_check.py"
sys.path.insert(0, str(PROGRAMS))
import spec_coverage_check as M  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── helpers ─────────────────────────────────────────────────────────────────
def _w(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def _run(args, strict=False, failure=None):
    cmd = [sys.executable, str(PROG)] + args
    if strict:
        cmd.append("--strict")
    if failure is not None:
        cmd += ["--failure", failure]
    return _pr.run(cmd, capture_output=True, text=True)


# ── 驗收 fixtures (verbatim from the issue) ──────────────────────────────────
ACCEPT_SPEC = ("Module dec. Valid opcodes {0x1,0x2,0x3}; any other -> out=0 "
               "default. Output registered 1-cycle latency. Reset active-high "
               "sync: out=0.\n")
ACCEPT_TB = ("// tb tests only opcodes 0x1,0x2,0x3; no outside-set, no reset, "
             "no latency check\n")


# ── POSITIVE: 驗收 END-STATE ─────────────────────────────────────────────────
def test_acceptance_end_state_strict_blocks(tmp_path):
    """The exact 驗收: lists the checklist, flags the outside-the-set boundary +
    reset + 1-cycle latency as UNCOVERED, rc non-zero in --strict."""
    sp = _w(tmp_path, "spec.md", ACCEPT_SPEC)
    tb = _w(tmp_path, "tb.sv", ACCEPT_TB)
    r = _run(["--spec", sp, "--tb", tb], strict=True)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    out = r.stdout.lower()
    # outside-the-set opcode -> default out=0 (UNCOVERED)
    assert "outside-the-set" in out and "uncovered" in out
    # reset (UNCOVERED)
    assert "reset" in out
    # 1-cycle / registered latency (UNCOVERED)
    assert "latency" in out
    assert "testbench-coverage gap" in out


def test_acceptance_spec_alias_equiv_prompt(tmp_path):
    """--spec is the back-compat alias for the USER prompt station."""
    sp = _w(tmp_path, "spec.md", ACCEPT_SPEC)
    a = _run(["--spec", sp])
    b = _run(["--prompt", sp])
    assert a.stdout == b.stdout


def test_enum_boundary_always_emitted(tmp_path):
    """The most-missed #697 pattern: an enumerated set ALWAYS emits the
    outside-the-set/default boundary checklist item."""
    items = M.extract_chain({"user_prompt": ACCEPT_SPEC})
    kinds = {it.kind for it in items}
    assert "enum_set" in kinds
    assert "enum_boundary" in kinds
    boundary = next(it for it in items if it.kind == "enum_boundary")
    assert "outside-the-set" in boundary.requirement


# ── POSITIVE: per-requirement extraction + coverage attribution ──────────────
def test_port_table_reset_example_extracted(tmp_path):
    spec = ("Module adder.\n- input a (8 bits)\n- output sum (8 bits)\n"
            "Example: 0x05 -> 0x0A.\nReset active-low.\n"
            "| opcode | output |\n|--------|--------|\n| 0x10 | add |\n")
    items = M.extract_chain({"user_prompt": spec})
    kinds = [it.kind for it in items]
    assert "port" in kinds
    assert "table_row" in kinds
    assert "reset" in kinds
    assert "worked_example" in kinds


def test_fully_covered_no_gap_rc0(tmp_path):
    """A TB that stimulates every member + an OUTSIDE-set value + reset + a
    clock edge => zero coverage gaps, rc 0 even in --strict (NO leak: full
    coverage is correctly recognised, not falsely flagged)."""
    sp = _w(tmp_path, "spec.md", ACCEPT_SPEC)
    tb = _w(tmp_path, "tb_full.sv",
            "module tb; reg reset; reg [7:0] op;\n"
            "initial begin reset=1; #10 reset=0;\n"
            "op=8'h1; #10; op=8'h2; #10; op=8'h3; #10; op=8'hFF; #10; end\n"
            "always @(posedge clk) ; endmodule\n")
    for strict in (False, True):
        r = _run(["--spec", sp, "--tb", tb], strict=strict)
        assert r.returncode == 0, (strict, r.stdout, r.stderr)
        assert "spec-coverage ok" in r.stdout


def test_outside_set_requires_non_member_value(tmp_path):
    """A TB that stimulates ONLY the listed members does NOT cover the
    boundary — outside-the-set requires a non-member value."""
    sp = _w(tmp_path, "spec.md", ACCEPT_SPEC)
    tb = _w(tmp_path, "tb_members_only.sv",
            "module tb; reg [7:0] op;\n"
            "initial begin op=8'h1; op=8'h2; op=8'h3; end endmodule\n")
    r = _run(["--spec", sp, "--tb", tb], strict=True)
    assert r.returncode == 1
    # enum_set covered (members touched) but boundary UNCOVERED
    assert "outside-the-set" in r.stdout.lower()


# ── POSITIVE: which-station routing (the scope refinement) ───────────────────
def test_route_extraction_gap_prompt_only_to_ic_expert_agent(tmp_path):
    """A behavior present ONLY in the USER prompt (not in our checklist, dropped
    before the fact graph) -> extraction-gap routed to the IC Expert Agent (the
    plain-language elicitation register that owns the user-facing front door)."""
    p = _w(tmp_path, "p.md",
           "A FIFO. It asserts almostfull when occupancy exceeds the watermark.\n")
    l = _w(tmp_path, "l.md", "L1: a FIFO with ports clk, data.\n")
    r = _run(["--prompt", p, "--ldocs", l],
             failure="almostfull never asserts at watermark")
    assert r.returncode == 0  # advisory (no --strict)
    assert "extraction-gap" in r.stdout
    assert "route_to: ic-expert-agent" in r.stdout
    assert "user_prompt" in r.stdout


def test_route_extraction_gap_fact_graph_to_ic_expert(tmp_path):
    """Held at the fact graph but dropped by the L-docs -> route ic-expert."""
    p = _w(tmp_path, "p.md", "A FIFO with ports clk, data.\n")
    fg = _w(tmp_path, "fg.json", '{"behavior":"almostfull asserts at watermark"}\n')
    l = _w(tmp_path, "l.md", "L1: a FIFO with ports clk, data.\n")
    r = _run(["--prompt", p, "--fact-graph", fg, "--ldocs", l],
             failure="almostfull watermark behavior wrong")
    assert "extraction-gap" in r.stdout
    assert "route_to: ic-expert-agent" in r.stdout


def test_route_extraction_gap_ldocs_to_spec_to_rtl(tmp_path):
    """Held at the most-downstream L-docs station but failing -> the spec-to-rtl
    extraction didn't read it out -> route spec-to-rtl."""
    p = _w(tmp_path, "p.md", "A FIFO with ports clk, data.\n")
    l = _w(tmp_path, "l.md",
           "L5: occupancy watermark causes almostfull assertion. ports clk.\n")
    r = _run(["--prompt", p, "--ldocs", l],
             failure="almostfull never asserts at watermark")
    assert "extraction-gap" in r.stdout
    assert "route_to: spec-to-rtl" in r.stdout
    assert "l_docs" in r.stdout


def test_coverage_gap_when_extracted_but_untested(tmp_path):
    """A requirement we DID extract (in the checklist) but the TB left UNCOVERED
    -> coverage-gap (enhance our TB), NOT an extraction gap."""
    sp = _w(tmp_path, "spec.md", ACCEPT_SPEC)
    tb = _w(tmp_path, "tb.sv", ACCEPT_TB)
    r = _run(["--spec", sp, "--tb", tb],
             failure="fails on the outside-the-set opcode 0xFF default path")
    assert "coverage-gap" in r.stdout


def test_cross_station_merge_records_last_station(tmp_path):
    """An identical requirement found at several stations MERGES; the most-
    downstream station is recorded as last_station."""
    items = M.extract_chain({
        "user_prompt": "Valid opcodes {0x1,0x2,0x3}.\n",
        "l_docs": "L3 opcode table: valid opcodes {0x1,0x2,0x3}.\n",
    })
    enum = next(it for it in items if it.kind == "enum_set")
    assert set(enum.stations) == {"user_prompt", "l_docs"}
    assert enum.last_station == "l_docs"


# ── §4.05 NEGATIVE no-leak ───────────────────────────────────────────────────
def test_noleak_spec_absent_not_fabricated_as_our_gap(tmp_path):
    """A white-box internal name the chain never states is attributed
    spec-absent (FLOOR-with-evidence), NOT fabricated into the checklist and
    NOT charged as our extraction/coverage gap."""
    p = _w(tmp_path, "p.md", "A counter. ports clk, q. Reset active-high.\n")
    l = _w(tmp_path, "l.md", "L1: a counter with ports clk, q.\n")
    r = _run(["--prompt", p, "--ldocs", l],
             failure="mismatch on internal signal "
                     "pipeline_stage_3_carry_lookahead never named in chain")
    assert r.returncode == 0
    assert "spec-absent" in r.stdout
    assert "stations_searched" in r.stdout
    # NOT fabricated into the checklist
    items = M.extract_chain({"user_prompt": p and open(p).read(),
                             "l_docs": open(l).read()})
    assert all("pipeline_stage_3_carry" not in it.requirement for it in items)
    # not routed to pm/ic-expert/spec-to-rtl (it is genuinely a floor)
    assert "route_to" not in r.stdout


def test_noleak_advisory_does_not_block_non_strict(tmp_path):
    """Coverage gaps present, but non-strict -> advisory WARN, rc 0 (no hard
    block). The strict-only block is the load-bearing gate."""
    sp = _w(tmp_path, "spec.md", ACCEPT_SPEC)
    tb = _w(tmp_path, "tb.sv", ACCEPT_TB)
    r = _run(["--spec", sp, "--tb", tb])  # no --strict
    assert r.returncode == 0
    assert "advisory" in r.stdout.lower()
    assert "testbench-coverage gap" in r.stdout.lower()


def test_noleak_no_tb_is_advisory_not_block(tmp_path):
    """No TB supplied -> everything UNCOVERED but still advisory in non-strict."""
    sp = _w(tmp_path, "spec.md", ACCEPT_SPEC)
    r = _run(["--spec", sp])
    assert r.returncode == 0


def test_noleak_blind_no_oracle_flag_on_cli(tmp_path):
    """The program reads ONLY the input chain + RTL + TB — it has NO oracle /
    hidden-TB flag on its CLI surface (it can never read the scoring TB)."""
    r = _run(["--help"])
    help_text = r.stdout + r.stderr
    for forbidden in ("--oracle", "--hidden", "--golden", "--scorer", "--ref-tb"):
        assert forbidden not in help_text
    # the only accepted inputs are the chain stations + rtl + tb + failure
    for ok in ("--prompt", "--fact-graph", "--ldocs", "--rtl", "--tb",
               "--failure", "--strict"):
        assert ok in help_text


def test_noleak_pure_prose_no_structural_feature_no_fabrication(tmp_path):
    """Pure prose with NO structural feature (no set/table/example/port/reset/
    latency keyword) emits NO checklist items — the program never invents a
    requirement out of free prose."""
    p = _w(tmp_path, "p.md",
           "This is a wonderful, well-engineered, elegant module that does "
           "delightful things in a tasteful manner.\n")
    items = M.extract_chain({"user_prompt": open(p).read()})
    assert items == []


# ── chip-AGNOSTIC sanity (no chip/vendor/SKU literal) ───────────────────────
def test_source_is_chip_agnostic():
    src = PROG.read_text()
    # the program must not hardcode any chip/vendor/SKU token; the guard program
    # enforces this corpus-wide — here we sanity-check the obvious ones.
    for tok in ("sky130", "gf180", "caravel", "opentitan", "ibex"):
        assert tok.lower() not in src.lower()
