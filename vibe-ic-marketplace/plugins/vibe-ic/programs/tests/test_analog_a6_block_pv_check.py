"""tests/test_analog_a6_block_pv_check.py — A6 per-block DRC+LVS gate.

Hardened from the v1.6.13 PASS-on-presence stub into REAL per-block
physical verification:
  * PASS  — every block has DRC violations == 0 AND LVS == match.
  * FAIL  — a block has DRC violations > 0 OR LVS mismatch (real
            silicon failure).
  * FAIL  — a block whose dir EXISTS but is missing DRC/LVS evidence
            (honesty: never a vacuous PASS on absence).
  * SKIP (rc=2) — genuinely no analog blocks (empty/absent block list).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "analog_a6_block_pv_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(json.dumps({"blocks": blocks}))


def _bdir(project: Path, block: str) -> Path:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def _report(project: Path) -> dict:
    return json.loads((project / "report.json").read_text())


# ---------------------------------------------------------------------------
# PASS — DRC 0 + LVS match for every block
# ---------------------------------------------------------------------------

def test_pass_flags_with_explicit_verdicts(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    d = _bdir(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("DRC clean\nviolations: 0\n")
    (d / "lvs_match.flag").write_text("LVS: match\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = _report(tmp_path)
    assert rpt["verdict"] == "PASS"
    assert rpt["blocks_pass"] == 1


def test_pass_real_reports(tmp_path: Path) -> None:
    _block_list(tmp_path, ["bandgap"])
    d = _bdir(tmp_path, "bandgap")
    (d / "drc.report").write_text(
        "Magic DRC run\n[INFO] geometry checked\nTotal DRC errors: 0\n")
    # A REAL netgen report always ends with a terminal `Final result:` line
    # (confirmed against every netgen report artifact on disk). A bare
    # `Circuits match uniquely.` with no terminal line is a truncated
    # hierarchical run — per-subcell match lines print long before the
    # top-level compare — and is refused by the shared classifier (#477).
    # See test_lvs_report_without_terminal_line_is_not_a_pass below.
    (d / "lvs.report").write_text(
        "Netgen LVS\nCircuits match uniquely.\n"
        "Final result: Circuits match uniquely.\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert _report(tmp_path)["verdict"] == "PASS"


def test_lvs_report_without_terminal_line_is_not_a_pass(tmp_path: Path) -> None:
    """A netgen report carrying a `match uniquely` line but NO terminal
    `Final result:` line is a truncated run, not a clean LVS. The A6 gate used
    its own tool-generic phrase list here and would PASS it; it now yields the
    netgen verdict to the shared classifier, which refuses it. Honesty: FAIL on
    inconclusive evidence, never a vacuous PASS."""
    _block_list(tmp_path, ["bandgap"])
    d = _bdir(tmp_path, "bandgap")
    (d / "drc.report").write_text("Total DRC errors: 0\n")
    (d / "lvs.report").write_text("Netgen LVS\nCircuits match uniquely.\n")
    r = _run(tmp_path)
    assert r.returncode != 0
    assert _report(tmp_path)["verdict"] != "PASS"


def test_lvs_report_reworded_mismatch_is_not_a_pass(tmp_path: Path) -> None:
    """The wording-gate defect, at the A6 layer: a netgen failure worded
    outside the enumerated phrase list, next to a `match uniquely` line, must
    never be read as a clean block."""
    _block_list(tmp_path, ["bandgap"])
    d = _bdir(tmp_path, "bandgap")
    (d / "drc.report").write_text("Total DRC errors: 0\n")
    (d / "lvs.report").write_text(
        "Circuits match uniquely.\n"
        "Result: Netlists are NOT equivalent.\n"
        "Final result: Netlist comparison FAILED (2 discrepancies).\n")
    r = _run(tmp_path)
    assert r.returncode != 0
    assert _report(tmp_path)["verdict"] != "PASS"


def test_pass_multi_block(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo", "por"])
    for b in ("ldo", "por"):
        d = _bdir(tmp_path, b)
        (d / "drc_clean.flag").write_text("violations: 0\n")
        (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert _report(tmp_path)["blocks_pass"] == 2


# ---------------------------------------------------------------------------
# FAIL — real silicon failure: DRC violations / LVS mismatch
# ---------------------------------------------------------------------------

def test_fail_drc_violations(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    d = _bdir(tmp_path, "ldo")
    (d / "drc.report").write_text("Total DRC errors: 7\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _report(tmp_path)
    assert rpt["verdict"] == "FAIL"
    assert any(f["rule"] == "A6_PV_DRC_VIOLATIONS" for f in rpt["findings"])


def test_fail_lvs_mismatch(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    d = _bdir(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs.report").write_text("Netgen LVS\nCircuits do not match.\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _report(tmp_path)
    assert rpt["verdict"] == "FAIL"
    assert any(f["rule"] == "A6_PV_LVS_MISMATCH" for f in rpt["findings"])


def test_fail_one_bad_block_among_good(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo", "por"])
    good = _bdir(tmp_path, "ldo")
    (good / "drc_clean.flag").write_text("violations: 0\n")
    (good / "lvs_match.flag").write_text("lvs: match\n")
    bad = _bdir(tmp_path, "por")
    (bad / "drc.report").write_text("Total DRC errors: 3\n")
    (bad / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert _report(tmp_path)["blocks_fail"] == 1


# ---------------------------------------------------------------------------
# HONESTY — missing/empty/garbage evidence for an EXISTING block => FAIL
# ---------------------------------------------------------------------------

def test_honesty_missing_both(tmp_path: Path) -> None:
    """Block dir exists but no DRC nor LVS evidence at all => FAIL,
    never a vacuous PASS."""
    _block_list(tmp_path, ["ldo"])
    _bdir(tmp_path, "ldo")  # empty block dir
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _report(tmp_path)
    assert rpt["verdict"] == "FAIL"
    rules = {f["rule"] for f in rpt["findings"]}
    assert "A6_PV_DRC_NO_EVIDENCE" in rules
    assert "A6_PV_LVS_NO_EVIDENCE" in rules


def test_honesty_bare_flag_rejected(tmp_path: Path) -> None:
    """A bare drc_clean.flag / lvs_match.flag WITHOUT an explicit
    count / verdict line is NOT acceptable evidence => FAIL."""
    _block_list(tmp_path, ["ldo"])
    d = _bdir(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("")          # empty flag
    (d / "lvs_match.flag").write_text("touched\n")  # no verdict line
    r = _run(tmp_path)
    assert r.returncode == 1
    rules = {f["rule"] for f in _report(tmp_path)["findings"]}
    assert "A6_PV_DRC_NO_EVIDENCE" in rules
    assert "A6_PV_LVS_NO_EVIDENCE" in rules


def test_honesty_missing_lvs_only(tmp_path: Path) -> None:
    """DRC clean but no LVS evidence => still FAIL (both required)."""
    _block_list(tmp_path, ["ldo"])
    d = _bdir(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("violations: 0\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rules = {f["rule"] for f in _report(tmp_path)["findings"]}
    assert "A6_PV_LVS_NO_EVIDENCE" in rules


def test_honesty_block_dir_missing(tmp_path: Path) -> None:
    """Block declared but its dir was never created (A5 didn't run)
    => FAIL, not SKIP."""
    _block_list(tmp_path, ["ldo"])  # no block dir on disk
    r = _run(tmp_path)
    assert r.returncode == 1
    rules = {f["rule"] for f in _report(tmp_path)["findings"]}
    assert "A6_PV_BLOCK_DIR_MISSING" in rules


# ---------------------------------------------------------------------------
# SKIP — genuinely no analog blocks (real non-applicability)
# ---------------------------------------------------------------------------

def test_skip_no_block_list(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 2
    assert _report(tmp_path)["verdict"] == "SKIP"


def test_skip_empty_block_list(tmp_path: Path) -> None:
    _block_list(tmp_path, [])  # explicit empty
    r = _run(tmp_path)
    assert r.returncode == 2
    assert _report(tmp_path)["verdict"] == "SKIP"


# ---------------------------------------------------------------------------
# WAIVER — evidence + ticket suppresses a MEASURED defect, and only that.
#
# A waiver is an accepted-RISK statement about something somebody measured.
# It must still work for that (`test_waiver_suppresses_measured_defect`), and
# it must NOT work where nothing was measured
# (`test_waiver_cannot_cover_absent_measurement`) — otherwise a single
# `waived_steps` entry turns "the tool never ran" into rc 0, which is the
# unmeasured-as-zero failure this gate exists to refuse. This matters more
# since A5 stopped reading A6's DRC/LVS outputs (the A5<->A6 cycle fix): A6 is
# now the only per-block PV gate, so its non-silenceable core carries the
# whole class, and the old A5 — which had no waiver path at all — rejected
# exactly this tree with rc=1.
# ---------------------------------------------------------------------------

def _waive_block_pv(tmp_path: Path) -> None:
    (tmp_path / "phase3" / "analog" / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "analog_block_pv",
            "ticket": "ECO-123",
            "reason": "PV deferred to top-level signoff per agreement",
        }]
    }))


def test_waiver_suppresses_measured_defect(tmp_path: Path) -> None:
    """NO FALSE ALARM. DRC measured 3 violations and LVS measured a
    mismatch — a real, ticketed accepted risk. The waiver still applies."""
    _block_list(tmp_path, ["ldo"])
    d = _bdir(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("violations: 3\n")
    (d / "lvs_match.flag").write_text("lvs: mismatch\n")
    _waive_block_pv(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _report(tmp_path)
    assert rpt["verdict"] == "WAIVED"
    assert {f["rule"] for f in rpt["suppressed_findings"]} == {
        "A6_PV_DRC_VIOLATIONS", "A6_PV_LVS_MISMATCH"}


def test_waiver_cannot_cover_absent_measurement(tmp_path: Path) -> None:
    """FALSIFIABILITY. The same waiver over a block with NO drc/lvs artefact
    at all. There is no measurement, so there is no risk to accept: the
    findings stay live and the step FAILs, naming what the waiver could not
    cover."""
    _block_list(tmp_path, ["ldo"])
    _bdir(tmp_path, "ldo")  # directory only — the tool never ran
    _waive_block_pv(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _report(tmp_path)
    assert rpt["verdict"] == "FAIL"
    assert {f["rule"] for f in rpt["findings"]} == {
        "A6_PV_DRC_NO_EVIDENCE", "A6_PV_LVS_NO_EVIDENCE"}
    assert {c["rule"] for c in rpt["waiver_cannot_cover"]} == {
        "A6_PV_DRC_NO_EVIDENCE", "A6_PV_LVS_NO_EVIDENCE"}
    assert rpt["waiver"]["ticket"] == "ECO-123"


def test_waiver_cannot_cover_missing_block_dir(tmp_path: Path) -> None:
    """FALSIFIABILITY, strongest form: A5 never produced a layout for the
    block, so PV cannot have run on anything. Not waivable."""
    _block_list(tmp_path, ["ldo"])  # no block dir on disk
    (tmp_path / "phase3" / "analog").mkdir(parents=True, exist_ok=True)
    _waive_block_pv(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _report(tmp_path)
    assert rpt["verdict"] == "FAIL"
    assert {f["rule"] for f in rpt["findings"]} == {"A6_PV_BLOCK_DIR_MISSING"}


def test_waiver_mixed_keeps_unmeasured_live_and_suppresses_measured(
        tmp_path: Path) -> None:
    """Both classes at once on two blocks: the measured DRC violation is
    suppressed and disclosed, the absent LVS measurement stays live."""
    _block_list(tmp_path, ["ldo", "bg"])
    d1 = _bdir(tmp_path, "ldo")
    (d1 / "drc_clean.flag").write_text("violations: 2\n")
    (d1 / "lvs_match.flag").write_text("lvs: match\n")
    d2 = _bdir(tmp_path, "bg")
    (d2 / "drc_clean.flag").write_text("violations: 0\n")
    # bg has no LVS evidence at all
    _waive_block_pv(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _report(tmp_path)
    assert rpt["verdict"] == "FAIL"
    assert {f["rule"] for f in rpt["findings"]} == {"A6_PV_LVS_NO_EVIDENCE"}
    assert {f["rule"] for f in rpt["suppressed_findings"]} == {
        "A6_PV_DRC_VIOLATIONS"}


# ---------------------------------------------------------------------------
# per-block (--block) mode used by analog_one_shot_runner
# ---------------------------------------------------------------------------

def test_per_block_missing_evidence_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo", "por"])
    _bdir(tmp_path, "ldo")
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 1
    assert _report(tmp_path)["verdict"] == "FAIL"


def test_per_block_pass(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo", "por"])
    d = _bdir(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 0
    assert _report(tmp_path)["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# TWO WITNESSES THAT CONTRADICT EACH OTHER
#
# Added 2026-07-28 at the convergence merge. When A5's PV reads were withdrawn
# to break the A5/A6 dependency cycle, a defect class went with them: A5 read
# the FLAGS while A6 prefers the REPORT, so a block whose flag contradicts its
# report was rejected rc=1 by old A5 and accepted rc=0 by BOTH gates.
# Measured on that exact input before this rule existed:
#   test/matrix-63x8-coverage            -> A5 rc=1 (A5_DRC_NOT_CLEAN + A5_LVS_NOT_MATCH)
#   after the cycle fix, before the rule -> A5 rc=0 AND A6 rc=0, findings []
# ---------------------------------------------------------------------------


def _two_witness_block(project: Path, *, drc_report: str, drc_flag: str,
                       lvs_report: str, lvs_flag: str) -> None:
    _block_list(project, ["ldo"])
    d = _bdir(project, "ldo")
    (d / "drc.report").write_text(drc_report)
    (d / "drc_clean.flag").write_text(drc_flag)
    (d / "lvs.report").write_text(lvs_report)
    (d / "lvs_match.flag").write_text(lvs_flag)


def test_contradicting_pv_witnesses_are_a_blocking_finding(tmp_path: Path) -> None:
    """THE DEFECT. A stale flag beside a fresh report — the shape a resumed
    project produces naturally. Neither number can be a sign-off verdict when
    the two disagree, so the gate must not silently believe the clean one."""
    _two_witness_block(tmp_path,
                       drc_report="total violations: 0\n",
                       drc_flag="violations: 5\n",
                       lvs_report="netlists match\n",
                       lvs_flag="lvs: mismatch\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = _report(tmp_path)
    assert rpt["verdict"] == "FAIL"
    assert {f["rule"] for f in rpt["findings"]} == {
        "A6_PV_DRC_WITNESS_DISAGREEMENT", "A6_PV_LVS_WITNESS_DISAGREEMENT"}


def test_contradicting_pv_witnesses_are_not_waivable(tmp_path: Path) -> None:
    """A waiver accepts a MEASURED risk. Here the measurement itself is in
    dispute, so there is nothing for a waiver to be about."""
    _two_witness_block(tmp_path,
                       drc_report="total violations: 0\n",
                       drc_flag="violations: 5\n",
                       lvs_report="netlists match\n",
                       lvs_flag="lvs: mismatch\n")
    _waive_block_pv(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = _report(tmp_path)
    assert rpt["verdict"] == "FAIL"
    assert {c["rule"] for c in rpt["waiver_cannot_cover"]} == {
        "A6_PV_DRC_WITNESS_DISAGREEMENT", "A6_PV_LVS_WITNESS_DISAGREEMENT"}


def test_agreeing_pv_witnesses_still_pass(tmp_path: Path) -> None:
    """NO FALSE ALARM. Both witnesses present and agreeing is the ordinary
    shape of a real run and must stay rc 0."""
    _two_witness_block(tmp_path,
                       drc_report="total violations: 0\n",
                       drc_flag="violations: 0\n",
                       lvs_report="netlists match\n",
                       lvs_flag="lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert _report(tmp_path)["verdict"] == "PASS"


def test_a_single_pv_witness_is_never_a_disagreement(tmp_path: Path) -> None:
    """NO FALSE ALARM. The rule needs TWO parseable verdicts; a block with the
    reports only, or with a bare flag carrying no verdict line, reaches none of
    its branches."""
    _block_list(tmp_path, ["ldo"])
    d = _bdir(tmp_path, "ldo")
    (d / "drc.report").write_text("total violations: 0\n")
    (d / "lvs.report").write_text("netlists match\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    (d / "drc_clean.flag").write_text("generated by the runner\n")   # no count
    (d / "lvs_match.flag").write_text("see lvs.report\n")            # no verdict
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert _report(tmp_path)["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# The KLayout marker database — the one DRC format the open-PDK path emits
#
# `*.lyrdb` has always been in the report glob and has always been inert: a
# marker database carries no "N violations" phrase, so the free-text reader
# extracted no count from one in EITHER direction, and a sign-off-CLEAN block
# reached the same "no parseable DRC evidence" FAIL as a violating one.
# Measured on the campaign's two analog blocks at the moment they first went
# DRC-0: both were reported as having no DRC evidence at all.
# ---------------------------------------------------------------------------

def _lyrdb(cats: list, items: list) -> str:
    c = "".join("<category><name>%s</name></category>" % n for n in cats)
    it = "".join(
        "<item><category>'%s'</category><values><value>%s</value>"
        "</values></item>" % (n, v) for n, v in items)
    return ("<?xml version='1.0'?><report-database><categories>%s</categories>"
            "<items>%s</items></report-database>" % (c, it))


def test_clean_marker_database_certifies_zero(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    d = _bdir(tmp_path, "ldo")
    (d / "ldo.lyrdb").write_text(_lyrdb(["M1.b", "CntB.h1"], []))
    (d / "lvs.report").write_text("netlists match\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert _report(tmp_path)["verdict"] == "PASS"


def test_violating_marker_database_is_counted(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    d = _bdir(tmp_path, "ldo")
    (d / "ldo.lyrdb").write_text(
        _lyrdb(["CntB.h1"], [("CntB.h1", "edge-pair: a"),
                             ("CntB.h1", "edge-pair: b")]))
    (d / "lvs.report").write_text("netlists match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rules = [f["rule"] for f in _report(tmp_path)["findings"]]
    assert "A6_PV_DRC_VIOLATIONS" in rules


def test_marker_database_that_graded_no_rule_is_not_a_pass(
        tmp_path: Path) -> None:
    """A database with zero CATEGORIES ran no rule; its emptiness is silence.
    This is the zero-rules law, and without it the repair above would turn a
    deck that aborted before grading anything into a certified-clean block."""
    _block_list(tmp_path, ["ldo"])
    d = _bdir(tmp_path, "ldo")
    (d / "ldo.lyrdb").write_text(_lyrdb([], []))
    (d / "lvs.report").write_text("netlists match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rules = [f["rule"] for f in _report(tmp_path)["findings"]]
    assert "A6_PV_DRC_NO_EVIDENCE" in rules


def test_a_lyrdb_that_is_not_xml_is_no_evidence(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    d = _bdir(tmp_path, "ldo")
    (d / "ldo.lyrdb").write_text("truncated by a killed run <report-datab")
    (d / "lvs.report").write_text("netlists match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rules = [f["rule"] for f in _report(tmp_path)["findings"]]
    assert "A6_PV_DRC_NO_EVIDENCE" in rules
