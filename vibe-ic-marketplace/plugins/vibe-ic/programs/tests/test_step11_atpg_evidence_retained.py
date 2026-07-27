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

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import fault_atpg_run as fatpg          # noqa: E402
import design_one_shot_runner as dosr   # noqa: E402


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
def test_measured_predicate_prefers_the_producers_declaration():
    assert dosr._dft_atpg_measured(
        {"coverage_measured": True, "faults_total": 0, "coverage_pct": 90.4}) is True
    assert dosr._dft_atpg_measured(
        {"coverage_measured": False, "faults_total": 1000}) is False


def test_measured_predicate_keeps_the_legacy_fallback():
    """DIRECTION-1 GUARD — a coverage.json written by an older plugin version
    has no `coverage_measured` key; the historical `faults_total > 0` rule
    must still apply to it."""
    assert dosr._dft_atpg_measured({"faults_total": 1000}) is True
    assert dosr._dft_atpg_measured({"faults_total": 0}) is False
    assert dosr._dft_atpg_measured({}) is False
    assert dosr._dft_atpg_measured({"faults_total": None}) is False
    assert dosr._dft_atpg_measured("not-a-dict") is False


# ---------------------------------------------------------------------------
# 3. The evidence: retained, never deleted
# ---------------------------------------------------------------------------
def _unmeasured_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    dft = tmp_path / "phase2/stage2/dft"
    dft.mkdir(parents=True)
    cov_json = tmp_path / "reports/phase2/dft/coverage.json"
    cov_json.parent.mkdir(parents=True)
    (dft / "atpg_coverage.rpt").write_text("Covered / Total: 904 / 1000\n")
    (dft / "coverage.yml").write_text(_coverage_yaml())
    (dft / "scan_netlist_prelim.v").write_text("module scan; endmodule\n")
    cov_json.write_text(json.dumps({"coverage_pct": 90.4, "faults_total": 1000}))
    return tmp_path, dft, cov_json


def test_unmeasured_artefacts_are_retained_not_destroyed(tmp_path):
    """The core of 11-d3: the runner used to `unlink()` atpg_coverage.rpt,
    coverage.json and coverage.yml so that "ALL step-11 sub-gates see cleanly
    absent inputs".  Erasing what the engine produced makes a disclosed skip
    indistinguishable from a suppressed result."""
    project, dft, cov_json = _unmeasured_project(tmp_path)
    retained = dosr._dft_retain_unmeasured(project, dft, cov_json)

    assert (dft / "atpg_coverage.unmeasured.rpt").is_file()
    assert (dft / "coverage.unmeasured.yml").is_file()
    assert (cov_json.parent / "coverage.unmeasured.json").is_file()
    # …with their content intact, not truncated placeholders.
    assert "904 / 1000" in (dft / "atpg_coverage.unmeasured.rpt").read_text()
    assert json.loads(
        (cov_json.parent / "coverage.unmeasured.json").read_text()
    )["faults_total"] == 1000

    # every retained path is NAMED, so the sentinel can point at it
    assert "phase2/stage2/dft/atpg_coverage.unmeasured.rpt" in retained
    assert "phase2/stage2/dft/coverage.unmeasured.yml" in retained
    assert "reports/phase2/dft/coverage.unmeasured.json" in retained
    assert "phase2/stage2/dft/scan_netlist_prelim.v" in retained


def test_canonical_measurement_paths_are_still_absent_after_retention(tmp_path):
    """DIRECTION-1 GUARD — retention must NOT resurrect the canonical names.

    The #608 honest SKIPPED-CONDITION depends on the canonical measurement
    artefacts being absent when there IS no measurement.  Retaining a copy
    under a disclosed name is the whole point; leaving the canonical name in
    place would let a non-measurement be read as a measurement.
    """
    project, dft, cov_json = _unmeasured_project(tmp_path)
    dosr._dft_retain_unmeasured(project, dft, cov_json)
    assert not (dft / "atpg_coverage.rpt").exists()
    assert not (dft / "coverage.yml").exists()
    assert not cov_json.exists()


def test_retention_on_an_empty_dft_dir_is_a_no_op(tmp_path):
    dft = tmp_path / "phase2/stage2/dft"
    dft.mkdir(parents=True)
    cov_json = tmp_path / "reports/phase2/dft/coverage.json"
    assert dosr._dft_retain_unmeasured(tmp_path, dft, cov_json) == []


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


def _synth_project(tmp_path: Path, netlist: str, sibling: str | None) -> Path:
    synth = tmp_path / "phase2/stage2/synth"
    synth.mkdir(parents=True)
    (synth / "netlist.v").write_text(netlist)
    if sibling is not None:
        (synth / "spm_synth.v").write_text(sibling)
    return tmp_path


def test_pdk_sniffed_from_the_netlist_atpg_actually_uses(tmp_path):
    """The provenance defect: the runner sniffed the PDK from netlist.v — the
    technology-GENERIC yosys netlist it writes itself — while fault_atpg_run
    silently switched to the tech-mapped sibling.  Result on the reference
    run: `pdk=generic` recorded for an ihp-sg13g2 design, `--pdk unmapped`
    passed, and fault_atpg_run's rc=2 "unsupported pdk" early return read
    downstream as an engine capability gap.
    """
    project = _synth_project(tmp_path, _GENERIC, _MAPPED_SG13)
    used, pdk = dosr._dft_atpg_sniff_pdk(project, "phase2/stage2/synth/netlist.v")
    assert pdk == "ihp-sg13g2"
    assert used.name == "spm_synth.v"


def test_pdk_sniff_unchanged_when_the_named_netlist_is_already_mapped(tmp_path):
    """DIRECTION-1 GUARD — when netlist.v is itself tech-mapped, nothing
    switches and the answer is unchanged."""
    project = _synth_project(tmp_path, _MAPPED_SG13, None)
    used, pdk = dosr._dft_atpg_sniff_pdk(project, "phase2/stage2/synth/netlist.v")
    assert pdk == "ihp-sg13g2"
    assert used.name == "netlist.v"


def test_pdk_sniff_stays_generic_when_there_is_no_mapped_netlist(tmp_path):
    """DIRECTION-1 GUARD — a genuinely unmapped project must still report
    "" so the disclosed capability gap survives.  This must not become a
    guess."""
    project = _synth_project(tmp_path, _GENERIC, None)
    used, pdk = dosr._dft_atpg_sniff_pdk(project, "phase2/stage2/synth/netlist.v")
    assert pdk == ""
    assert used.name == "netlist.v"


@pytest.mark.parametrize("cells,expect", [
    ("sky130_fd_sc_hd__nand2_1 _0_ (.A(a));", "sky130"),
    ("gf180mcu_fd_sc_mcu7t5v0__nand2_1 _0_ (.A(a));", "gf180"),
])
def test_pdk_sniff_preserves_the_other_library_branches(tmp_path, cells, expect):
    """DIRECTION-1 GUARD — sky130 / gf180 detection is unchanged."""
    project = _synth_project(
        tmp_path, f"module m(a);\n input a;\n {cells}\nendmodule\n", None)
    _used, pdk = dosr._dft_atpg_sniff_pdk(project, "phase2/stage2/synth/netlist.v")
    assert pdk == expect
