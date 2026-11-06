#!/usr/bin/env python3
"""DFT_FCC / 11-d3 — step 11 must not manufacture the absence of a real ATPG
measurement.

MEASURED on the reference run (spm × ihp-sg13g2, host 192.168.1.120, project
~/campaign_pr427/spm/converge_ihp-sg13g2), re-running today's own
`fault_atpg_run.py` over that project's own artefacts:

    fault_atpg_run: stuck-at coverage=90.40%  target=95.00%
                    stuck_at_ge_target=False
    phase2/stage2/dft/coverage.yml : ratio: 9.03999984264374e-1
                                     faultPoints: 1000 entries
    phase2/stage2/dft/atpg_coverage.rpt : Covered / Total: 904 / 1000
                                          Result: FAIL

while the flow's own step-11 verdict on that same project is
SKIPPED-CONDITION, on the strength of a sentinel that reads

    "OSS Fault ATPG could not measure sign-off stuck-at coverage on this
     netlist"

and whose supporting artefacts (atpg_coverage.rpt, coverage.json,
coverage.yml) had been DELETED by the runner, with scan_netlist.v renamed
away. Three separate mechanisms produced that outcome; each has a test here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import fault_atpg_run as fatpg          # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures modelled on the REAL Fault 0.9 outputs captured from the run above.
# ---------------------------------------------------------------------------
def _coverage_yaml(n_points: int = 1000, ratio: str = "9.03999984264374e-1") -> str:
    lines = [f"ratio: {ratio}", "faultPoints:"]
    lines += [f"- _{300 + i}_.A" for i in range(n_points)]
    lines += ["sa0Covered:"] + [f"- _{300 + i}_.A" for i in range(3)]
    lines += ["sa1Covered:"] + [f"- _{300 + i}_.Y" for i in range(3)]
    return "\n".join(lines) + "\n"


# The tail Fault actually printed on the reference run. Note what is NOT in
# it: the "Found N fault sites" line the old parser needed.
_REAL_LOG_TAIL = (
    "tors in Fault JSON format to /work/phase2/stage2/dft/tv.json\n"
    "Finding essential test vectors\n"
    "Found 0 essential test vectors.\n"
    "Performing compaction\n"
    "Initial TV Count: 1000. Compacted TV Count: 14. \n"
    "Successfully compacted test vectors by a ratio of 98.60%.\n"
    "Writing YAML file of final coverage metadata to "
    "/work/phase2/stage2/dft/coverage.yml\n"
)


# ---------------------------------------------------------------------------
# 1. The parse: a clean run whose metadata holds a real ratio is a MEASUREMENT
# ---------------------------------------------------------------------------
def test_measurement_survives_a_missing_stdout_fault_site_line():
    """The discriminator.

    `faults_total` used to come ONLY from a scrape of `Found N fault sites`
    in the container stdout, while the caller decided "did the engine
    measure?" from `faults_total > 0`.  With that line absent — as it is in
    the reference run's captured log tail — a run holding a real 90.4% ratio
    reported faults_total=0, i.e. "engine could not measure".
    """
    got = fatpg.parse_atpg_coverage(_coverage_yaml(), _REAL_LOG_TAIL, 0)
    assert got["coverage_pct"] == pytest.approx(90.3999984264374)
    assert got["faults_total"] == 1000
    assert got["faults_covered"] == 904
    assert got["coverage_measured"] is True
    # The number must be attributable, not anonymous.
    assert got["faults_total_source"] == "fault_coverage_metadata_yaml:faultPoints"
    assert got["coverage_source"] == "fault_coverage_metadata_yaml:ratio"


def test_faultpoints_count_is_the_engines_own_universe_not_an_estimate():
    """Anti-inflation guard.  The denominator is a COUNT of the engine's own
    `faultPoints:` block — not the union of detected nodes, which would read
    as ~100% coverage.  Sibling blocks (`sa0Covered:` …) must not be summed
    into it."""
    text = _coverage_yaml(n_points=37)
    assert fatpg._count_yaml_block_items(text, "faultPoints") == 37
    assert fatpg._count_yaml_block_items(text, "sa0Covered") == 3
    assert fatpg._count_yaml_block_items(text, "absent_key") == 0
    assert fatpg.parse_atpg_coverage(text, _REAL_LOG_TAIL, 0)["faults_total"] == 37


def test_stdout_scrape_still_wins_when_present():
    """DIRECTION-1 GUARD — the historical stdout source keeps priority and
    keeps producing the same numbers.  Both channels agree on the reference
    run (1000 == 1000); this pins that the fallback never displaces a
    directly reported value."""
    log = _REAL_LOG_TAIL + "Found 1000 fault sites\n"
    got = fatpg.parse_atpg_coverage(_coverage_yaml(), log, 0)
    assert got["faults_total"] == 1000
    assert got["faults_total_source"] == "atpg_stdout:Found N fault sites"
    assert got["coverage_measured"] is True


@pytest.mark.parametrize("cov_text,log,rc,why", [
    ("", "Unknown module type: sky130_fd_sc_hd__udp_mux_4to2", 1,
     "engine could not elaborate the netlist"),
    ("", "Found 1000 fault sites\n", 1,
     "non-zero exit — a fault-site count without a completed run"),
    ("ratio: 0.0\nfaultPoints:\n- a\n", "", 0,
     "clean exit but zero coverage from a non-run"),
    ("faultPoints:\n- a\n- b\n", "", 0,
     "fault universe but no ratio anywhere"),
])
def test_a_non_run_is_never_a_measurement(cov_text, log, rc, why):
    """DIRECTION-1 GUARD — the honest disclosed capability gap must survive.

    A genuine engine failure (missing cell model, unmapped netlist,
    DFF-detect limit) must keep reporting coverage_measured=False so step 11
    keeps writing its disclosed sentinel instead of a fabricated 0%.
    """
    got = fatpg.parse_atpg_coverage(cov_text, log, rc)
    assert got["coverage_measured"] is False, why


# ---------------------------------------------------------------------------
# 2. The caller's predicate
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 3. The evidence: retained, never deleted
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 4. The PDK sniff: read the netlist ATPG will actually use
# ---------------------------------------------------------------------------
_GENERIC = (
    "module spm(clk, rst, x, y, p);\n"
    "  input clk, rst; input [31:0] x; input y; output p;\n"
    "  $_NAND_ _0_ (.A(x[0]), .B(y), .Y(p));\n"
    "  $_NOR_ _1_ (.A(x[1]), .B(y), .Y(p));\n"
    "  $_DFF_P_ _2_ (.C(clk), .D(y), .Q(p));\n"
    "endmodule\n"
)
_MAPPED_SG13 = (
    "module spm(clk, rst, x, y, p);\n"
    "  input clk, rst; input [31:0] x; input y; output p;\n"
    "  sg13g2_nand2_1 _0_ (.A(x[0]), .B(y), .Y(p));\n"
    "  sg13g2_dfrbpq_1 _1_ (.CLK(clk), .D(y), .Q(p));\n"
    "endmodule\n"
)
