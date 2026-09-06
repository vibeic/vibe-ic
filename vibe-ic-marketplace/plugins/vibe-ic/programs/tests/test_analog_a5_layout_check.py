"""tests/test_analog_a5_layout_check.py — v1.6.35"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "analog_a5_layout_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _layout_full(project: Path, block: str) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text(
        "magic\ntech sky130A\n" + "rect 0 0 100 100\n" * 20)


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path_mag(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _layout_full(tmp_path, "ldo")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


# A minimal real GDS stream: one BOUNDARY (0x08) geometry record followed by
# zero padding so it clears the 200-byte size bar AND carries real geometry.
_GDS_WITH_GEOMETRY = b"\x00\x04\x08\x00" + b"\x00" * 508
# An empty-geometry GDS: a HEADER record + padding, NO geometry record — the
# exact shape an `eda_analog_layout` `readspice`+`gds write` (no placement)
# streams. ORGANIC #144: this must now FAIL, not pass on size alone.
_GDS_EMPTY_GEOMETRY = b"\x00\x06\x00\x02" + b"\x00" * 508


def test_happy_path_gds_alternative(tmp_path: Path) -> None:
    """Either layout.mag OR <block>.gds satisfies A5 — when the GDS carries
    real placed geometry (ORGANIC #144: at least one geometry record).

    The claim under test is the LAYOUT representation (GDS instead of .mag).
    The DRC/LVS sign-off flags this fixture used to write are gone: they are
    A6's artefacts and A6's verdict (see "A5 -> A6 PV OWNERSHIP" below), so
    writing them here would re-assert a contract A5 no longer has. The
    `returncode == 0` assertion is unchanged."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ldo.gds").write_bytes(_GDS_WITH_GEOMETRY)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr


def test_empty_geometry_gds_fails(tmp_path: Path) -> None:
    """ORGANIC #144 no-leak — a size-passing but geometry-EMPTY GDS (the
    `readspice`+`gds write` empty stream) FAILs the tightened gate."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ldo.gds").write_bytes(_GDS_EMPTY_GEOMETRY)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = json.loads((tmp_path / "report.json").read_text())
    rules = {f["rule"] for f in rpt.get("findings", [])}
    assert "A5_LAYOUT_EMPTY_GEOMETRY" in rules, rpt


def test_padded_mag_stub_fails(tmp_path: Path) -> None:
    """ORGANIC #144 no-leak — the runner's own deterministic A5 stub
    (`layout.mag` = magic header + `"x"*400` padding, no placed geometry)
    now FAILs on the geometry assertion instead of passing on size."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text(
        "magic\ntech sky130A\n# deterministic-stub padding "
        + "x" * 400 + "\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = json.loads((tmp_path / "report.json").read_text())
    rules = {f["rule"] for f in rpt.get("findings", [])}
    assert "A5_LAYOUT_EMPTY_GEOMETRY" in rules, rpt


def test_empty_geometry_mag_no_marker_fails(tmp_path: Path) -> None:
    """A geometry-empty .mag with NO stub marker (e.g. just a header + a
    long comment) still FAILs — the geometry parse, not just the marker,
    is load-bearing."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text(
        "magic\ntech sky130A\ntimestamp 0\n"
        + "# placeholder header only, no paint\n" * 20)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout


def test_real_mag_with_instances_passes(tmp_path: Path) -> None:
    """A .mag whose geometry is cell instances (`use` lines) — no paint
    rects — still passes (instance-based placement is real geometry).

    Same scope correction as `test_happy_path_gds_alternative`: the claim
    under test is the .mag geometry parse, and the PV flags are A6's."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    body = "magic\ntech sky130A\ntimestamp 0\n"
    for i in range(8):
        body += (f"use sky130_fd_pr__nfet_01v8 m{i}\n"
                 f"transform 1 0 0 0 1 {i*10}\nbox 0 0 100 100\n")
    (d / "layout.mag").write_text(body)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "analog-layout"


def test_pv_flags_absent_do_not_fail_a5(tmp_path: Path) -> None:
    """DIRECTION-2 GUARD for the A5/A6 cycle break. Straight after A5 runs,
    `drc_clean.flag` / `lvs_match.flag` DO NOT EXIST — they are written by the
    A6 step. A5 must PASS on a real layout alone; requiring them made A5 red
    on every correct single-pass run for a condition A5 cannot satisfy."""
    _block_list(tmp_path, ["ldo"])
    _layout_full(tmp_path, "ldo")
    d = tmp_path / "phase3" / "analog" / "ldo"
    assert not (d / "drc_clean.flag").exists()
    assert not (d / "lvs_match.flag").exists()
    r = _run(tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS", rpt


def test_layout_too_small_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text("magic\n")  # < 200B
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A5_LAYOUT_TOO_SMALL" in f["rule"]
               for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"


# ===========================================================================
# A5/d2 — PARTIAL BLOCK COVERAGE must not be certified as PASS
#
# Reproduced on main @ v1.7.36: a 2-block project where only `blk_ok` has a
# layout returned `PASS: analog_a5_layout_check — 1/2 block(s) clean`, rc=0,
# verdict PASS, blocks_missing=1. The step's declaration
# (`phase3/analog/*/layout.mag OR phase3/analog/*/*.gds`) is a glob that ONE
# matching block satisfies, so the flow gate cannot see the uncovered block
# either — only this per-block gate can.
# ===========================================================================


def _layout_and_flags(project: Path, block: str) -> Path:
    """A per-block dir with a REAL-geometry layout (A5's whole contract)."""
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text(
        "magic\ntech sky130A\ntimestamp 0\n" + "rect 0 0 100 100\n" * 20)
    return d


def test_d2_partial_block_coverage_is_incomplete_not_pass(
        tmp_path: Path) -> None:
    """THE d2 DISCRIMINATOR. Two declared blocks, only one laid out. The
    gate must refuse to certify A5 (rc=1, verdict INCOMPLETE) and must NAME
    the uncovered block. Before the fix this returned rc=0 / verdict PASS."""
    _block_list(tmp_path, ["blk_ok", "blk_missing"])
    _layout_and_flags(tmp_path, "blk_ok")
    (tmp_path / "phase3" / "analog" / "blk_missing").mkdir(parents=True)
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "INCOMPLETE", rpt
    assert rpt["blocks_pass"] == 1 and rpt["blocks_missing"] == 1, rpt
    assert {f["block"] for f in rpt["findings"]} == {"blk_missing"}, rpt
    assert {f["rule"] for f in rpt["findings"]} == {"A5_LAYOUT_MISSING"}, rpt
    # The uncovered block must be named to a human, not just counted.
    assert "blk_missing" in r.stderr, r.stderr


def test_d2_partial_coverage_when_uncovered_block_has_no_dir_at_all(
        tmp_path: Path) -> None:
    """Same defect, harsher shape: the uncovered block has no directory —
    the A-track never touched it. Still INCOMPLETE, never PASS."""
    _block_list(tmp_path, ["blk_ok", "never_started"])
    _layout_and_flags(tmp_path, "blk_ok")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "INCOMPLETE", rpt
    assert {f["block"] for f in rpt["findings"]} == {"never_started"}, rpt


def test_d2_partial_coverage_names_every_uncovered_block(
        tmp_path: Path) -> None:
    """3 declared, 1 laid out — the report names BOTH uncovered blocks so an
    operator can act on it (a bare count would not be actionable)."""
    _block_list(tmp_path, ["blk_ok", "gap_a", "gap_b"])
    _layout_and_flags(tmp_path, "blk_ok")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "INCOMPLETE", rpt
    assert {f["block"] for f in rpt["findings"]} == {"gap_a", "gap_b"}, rpt
    assert rpt["blocks_checked"] == 3 and rpt["blocks_pass"] == 1, rpt


# ---- d2 direction-1 guards: behaviour that must NOT change ----------------


def test_d2_guard_all_blocks_missing_still_vacuous_pass(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD. When NO declared block has a layout, A5 has simply
    not run yet: the gate EXPLAINS the absence (VACUOUS_PASS naming the
    upstream skill) and defers. That deliberate deferral must survive — the
    d2 fix targets PARTIAL coverage only."""
    _block_list(tmp_path, ["blk_a", "blk_b"])
    (tmp_path / "phase3" / "analog" / "blk_a").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "blk_b").mkdir(parents=True)
    r = _run(tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS", rpt
    assert "analog-layout" in rpt["reason"], rpt


def test_d2_guard_full_coverage_still_passes(tmp_path: Path) -> None:
    """DIRECTION-1 GUARD. Every declared block laid out and signed off →
    still a plain PASS. The fix must not turn a complete A5 red."""
    _block_list(tmp_path, ["blk_a", "blk_b"])
    _layout_and_flags(tmp_path, "blk_a")
    _layout_and_flags(tmp_path, "blk_b")
    r = _run(tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS", rpt
    assert rpt["blocks_pass"] == 2 and rpt["blocks_missing"] == 0, rpt


def test_d2_guard_block_mode_missing_stays_waived_exit_2(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD. The runner drives A5 per block with `--block`, and
    relies on rc=2 → WAIVED for a block whose layout is not emitted yet. The
    new project-level exit-1 path must stay confined to no-`--block` mode."""
    _block_list(tmp_path, ["blk_ok", "blk_missing"])
    _layout_and_flags(tmp_path, "blk_ok")
    (tmp_path / "phase3" / "analog" / "blk_missing").mkdir(parents=True)
    r = _run(tmp_path, "--block", "blk_missing")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "WAIVED", rpt
    assert rpt["suggested_skill"] == "analog-layout", rpt


# ===========================================================================
# A5 -> A6 PV OWNERSHIP — the dependency cycle, and the proof nothing was lost
#
# A5's gate used to require `<block>/drc_clean.flag` and `<block>/lvs_match.flag`
# to carry clean verdicts. Both are step A6's DECLARED required_outputs and A6
# declares `blocks_on: [A5]`, so the declared ordering ran A6 -> A5 while the
# real read ran A5 -> A6 — a cycle no `blocks_on` value can express.
#
# It was broken on the A5 side. The direction was DECIDED, not guessed:
#   * A6 cannot run without A5's layout (`A6_PV_BLOCK_DIR_MISSING` says so in
#     as many words); A5 -> A6 is the DATA dependency.
#   * `analog_one_shot_runner._emit_deterministic_stub` writes `layout.mag`
#     under `step_name == "A5_layout"` and BOTH flags under `"A6_block_pv"`,
#     and the runner runs A5 before A6 — so A5 was FAILing every correct
#     single-pass run for a condition A5 itself cannot satisfy.
#
# The tests below are the "nothing was lost" half. Each one feeds the A6 gate
# the SAME per-block input the deleted A5 test fed the A5 gate, and asserts
# rc=1. If a future change relaxes A6, these go red — the defect classes are
# still under test, they just belong to the step that owns the evidence.
#
# ONE deleted test has NO counterpart here, deliberately:
# `test_d5_parser_import_failure_degrades_but_never_fails_open` exercised A5's
# `_load_pv_parsers()` degraded mode — the fallback for when A5's cross-program
# import of A6's parsers failed. A5 no longer imports A6, so there is no import
# to fail and no degraded mode to guard; A6 calls its own parsers directly.
# That is a deleted CODE PATH, not a deleted defect class.
#
# WHAT DID CHANGE, STATED EXACTLY. The old A5 gate contained no waiver code
# path at all (`grep -c waiver` on the pre-move file: 0), so it was a second,
# independently NON-SILENCEABLE gate on per-block DRC/LVS. A6 has the
# flow-wide waiver path, so a project-side `waived_steps: [{id:
# analog_block_pv}]` entry now reaches this class where it previously could
# not. That is not symmetric across the defect classes and the difference is
# load-bearing:
#   * MEASURED defects (A6_PV_DRC_VIOLATIONS / A6_PV_LVS_MISMATCH) ARE
#     waivable — a ticketed accepted risk over a real measurement, policed by
#     waivers_schema_check / waiver_legitimacy_check / foundry_signoff_plan_
#     check, which is what the flow's waiver mechanism is for.
#   * ABSENT measurements (A6_PV_BLOCK_DIR_MISSING / A6_PV_DRC_NO_EVIDENCE /
#     A6_PV_LVS_NO_EVIDENCE) are NOT waivable
#     (`analog_a6_block_pv_check._NON_WAIVABLE_RULES`): there is no risk to
#     accept where nothing was measured. Asserted below, both directions.
# CORRECTED 2026-07-28. The claim that stood here — "every input the old A5
# rejected is still rejected rc=1 by A6" — was FALSE as written, and the
# fixtures below could not see it because every one of them is FLAG-ONLY
# (`_a6_rejects` never writes a report). Old A5 read the FLAGS; A6 prefers the
# REPORT. Two inputs separate them:
#
#   * FLAG CONTRADICTS REPORT — `drc_clean.flag: "violations: 5"` beside
#     `drc.report: "total violations: 0"`, and `lvs_match.flag: "lvs: mismatch"`
#     beside `lvs.report: "netlists match"`. Measured: baseline A5 rc=1; after
#     the cycle fix and before the repair, A5 rc=0 AND A6 rc=0 with no findings.
#     A defect class the baseline rejected had become green in both gates.
#     CLOSED — `analog_a6_block_pv_check._witness_disagreements` FAILs on it and
#     the rule is in `_NON_WAIVABLE_RULES`; the falsifiers and the no-false-alarm
#     controls live in test_analog_a6_block_pv_check.py under "TWO WITNESSES
#     THAT CONTRADICT EACH OTHER", and A6's rc is unchanged on all 23 tracked
#     analog run roots.
#   * CLEAN REPORT, NO FLAG — rejected by old A5 (A5_DRC_FLAG_MISSING /
#     A5_LVS_FLAG_MISSING), accepted by A6, and deliberately NOT called a lost
#     defect class: the tool's own report is richer evidence than a flag file.
#
# So the honest claim, in full: every input the old A5 rejected is still
# rejected rc=1 by A6 EXCEPT a block whose clean tool report carries no flag
# beside it; for the evidence-ABSENCE classes and for a witness contradiction
# that holds even under a project-side step waiver; and only the two
# measured-defect classes gained a ticketed escape they did not have while A5
# duplicated them.
# ===========================================================================

A6_PROG = (Path(__file__).resolve().parent.parent
           / "analog_a6_block_pv_check.py")


def _layout_only(project: Path, block: str) -> Path:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text(
        "magic\ntech sky130A\ntimestamp 0\n" + "rect 0 0 100 100\n" * 20)
    return d


def _run_a6(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(A6_PROG), str(project),
         "--json", str(project / "a6.json"), *args],
        capture_output=True, text=True,
    )


def _a6_report(project: Path) -> dict:
    return json.loads((project / "a6.json").read_text())


def _a6_rejects(tmp_path: Path, drc, lvs, *args: str) -> dict:
    """Write the given flag bodies (bytes/str, or None to omit the file) and
    assert the A6 gate rejects the block with rc=1. Returns its report."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    for name, body in (("drc_clean.flag", drc), ("lvs_match.flag", lvs)):
        if body is None:
            continue
        if isinstance(body, bytes):
            (d / name).write_bytes(body)
        else:
            (d / name).write_text(body)
    r = _run_a6(tmp_path, *args)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    return _a6_report(tmp_path)


def test_ownership_zero_byte_drc_flag_rejected_by_a6(tmp_path: Path) -> None:
    """Was `test_d5_zero_byte_drc_flag_fails` on A5."""
    rpt = _a6_rejects(tmp_path, b"", "lvs: match\n")
    assert "A6_PV_DRC_NO_EVIDENCE" in {f["rule"] for f in rpt["findings"]}, rpt
    # The ABSENT / EMPTY / VERDICT-LESS distinction A5's rule ids carried is
    # preserved in the detail, so the finding still tells an operator whether
    # to run the tool or to fix its output.
    assert "empty/whitespace" in " ".join(
        f["detail"] for f in rpt["findings"]), rpt


def test_ownership_zero_byte_lvs_flag_rejected_by_a6(tmp_path: Path) -> None:
    """Was `test_d5_zero_byte_lvs_flag_fails` on A5."""
    rpt = _a6_rejects(tmp_path, "violations: 0\n", b"")
    assert "A6_PV_LVS_NO_EVIDENCE" in {f["rule"] for f in rpt["findings"]}, rpt


def test_ownership_whitespace_only_flags_rejected_by_a6(
        tmp_path: Path) -> None:
    """Was `test_d5_whitespace_only_flags_fail` on A5."""
    rpt = _a6_rejects(tmp_path, "   \n\n\t\n", "\n")
    assert {"A6_PV_DRC_NO_EVIDENCE", "A6_PV_LVS_NO_EVIDENCE"} <= {
        f["rule"] for f in rpt["findings"]}, rpt


def test_ownership_verdictless_flags_rejected_by_a6(tmp_path: Path) -> None:
    """Was `test_d5_verdictless_flags_fail` on A5 — non-empty but carrying no
    count / no LVS verdict."""
    rpt = _a6_rejects(tmp_path, "clean\n", "ok\n")
    assert {"A6_PV_DRC_NO_EVIDENCE", "A6_PV_LVS_NO_EVIDENCE"} <= {
        f["rule"] for f in rpt["findings"]}, rpt
    assert "carries no verdict line" in " ".join(
        f["detail"] for f in rpt["findings"]), rpt


def test_ownership_drc_flag_declaring_violations_rejected_by_a6(
        tmp_path: Path) -> None:
    """Was `test_d5_drc_flag_declaring_violations_fails` on A5."""
    rpt = _a6_rejects(tmp_path, "violations: 7\n", "lvs: match\n")
    assert "A6_PV_DRC_VIOLATIONS" in {f["rule"] for f in rpt["findings"]}, rpt


def test_ownership_lvs_flag_declaring_mismatch_rejected_by_a6(
        tmp_path: Path) -> None:
    """Was `test_d5_lvs_flag_declaring_mismatch_fails` on A5."""
    rpt = _a6_rejects(tmp_path, "violations: 0\n", "lvs: mismatch\n")
    assert "A6_PV_LVS_MISMATCH" in {f["rule"] for f in rpt["findings"]}, rpt


def test_ownership_netgen_shaped_flag_without_terminal_verdict_rejected(
        tmp_path: Path) -> None:
    """Was `test_d5_netgen_shaped_flag_without_terminal_verdict_fails` on A5.
    A5 only ever had this behaviour because it BORROWED A6's parser; the
    fail-safe lives in `analog_a6_block_pv_check._parse_lvs_match` and is
    unaffected by the ownership move."""
    rpt = _a6_rejects(tmp_path, "violations: 0\n",
                      "Subcircuit summary:\nCircuits match uniquely.\n")
    assert "A6_PV_LVS_NO_EVIDENCE" in {f["rule"] for f in rpt["findings"]}, rpt


def test_ownership_absent_drc_flag_rejected_by_a6(tmp_path: Path) -> None:
    """Was `test_d5_guard_missing_flag_file_still_reports_missing_rule` and
    `test_drc_flag_missing_fails` on A5 — the ABSENT case, whose distinct
    diagnosis must survive the move."""
    rpt = _a6_rejects(tmp_path, None, "lvs: match\n")
    assert "A6_PV_DRC_NO_EVIDENCE" in {f["rule"] for f in rpt["findings"]}, rpt
    assert "the tool has not run" in " ".join(
        f["detail"] for f in rpt["findings"]), rpt


def test_ownership_absent_lvs_flag_rejected_by_a6(tmp_path: Path) -> None:
    """Was `test_lvs_flag_missing_fails` on A5."""
    rpt = _a6_rejects(tmp_path, "violations: 0\n", None)
    assert "A6_PV_LVS_NO_EVIDENCE" in {f["rule"] for f in rpt["findings"]}, rpt


def test_ownership_block_mode_empty_flags_are_fail_not_waived(
        tmp_path: Path) -> None:
    """Was `test_d5_block_mode_empty_flags_are_fail_not_waived` on A5. Under
    `--block` the contentless-flag case must stay a substance FAIL (rc=1), not
    a deferral (rc=2) that the runner would record as WAIVED."""
    rpt = _a6_rejects(tmp_path, b"", b"", "--block", "ldo")
    assert rpt["verdict"] == "FAIL", rpt


# ---- the ONE asymmetry the ownership move introduced, both directions ------


def _waived_project(tmp_path: Path, drc, lvs) -> subprocess.CompletedProcess:
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    for name, body in (("drc_clean.flag", drc), ("lvs_match.flag", lvs)):
        if body is not None:
            (d / name).write_text(body)
    (tmp_path / "phase3" / "analog" / "waivers.json").write_text(json.dumps({
        "waived_steps": [{"id": "analog_block_pv", "ticket": "T-1",
                          "reason": "vendor hardmacro"}]}))
    return _run_a6(tmp_path)


def test_ownership_waiver_cannot_silence_absent_pv_evidence(
        tmp_path: Path) -> None:
    """FALSIFIABILITY of the residual. The old A5 had no waiver path, so a
    `waived_steps` entry could not reach per-block PV at all. With A5 out of
    the business, the case that MUST NOT become silenceable is the one where
    nothing was measured — otherwise a single JSON entry turns "DRC and LVS
    never ran" into rc 0. Measured: rc=1, both no-evidence rules live."""
    r = _waived_project(tmp_path, None, None)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rpt = _a6_report(tmp_path)
    assert rpt["verdict"] == "FAIL", rpt
    assert {f["rule"] for f in rpt["findings"]} == {
        "A6_PV_DRC_NO_EVIDENCE", "A6_PV_LVS_NO_EVIDENCE"}, rpt
    assert rpt["waiver_cannot_cover"], rpt


def test_ownership_waiver_still_covers_a_measured_pv_defect(
        tmp_path: Path) -> None:
    """NO FALSE ALARM, and the honest statement of what DID change: a
    ticketed waiver over a MEASURED defect still applies (rc=0, WAIVED, the
    suppressed findings disclosed). This is the flow-wide waiver mechanism
    that the duplicated A5 rules used to sit outside of."""
    r = _waived_project(tmp_path, "violations: 3\n", "lvs: mismatch\n")
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    rpt = _a6_report(tmp_path)
    assert rpt["verdict"] == "WAIVED", rpt
    assert {f["rule"] for f in rpt["suppressed_findings"]} == {
        "A6_PV_DRC_VIOLATIONS", "A6_PV_LVS_MISMATCH"}, rpt


# ---- ownership direction-1 guards: A6 must not turn a clean block red ------


def test_ownership_guard_runner_deterministic_stub_flags_still_pass(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD. `analog_one_shot_runner._emit_deterministic_stub`
    writes these exact flag bodies for A6_block_pv. A6 must accept them, or
    every stub dry-run turns red for the wrong reason."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text(
        "# deterministic_stub extraction_strategy=deterministic_stub "
        "low_confidence=true\n"
        "# ldo — DRC clean (deterministic stub)\n"
        "deterministic_stub\n"
        "violations: 0\n")
    (d / "lvs_match.flag").write_text(
        "# deterministic_stub extraction_strategy=deterministic_stub "
        "low_confidence=true\n"
        "# ldo — LVS match (deterministic stub)\n"
        "deterministic_stub\n"
        "lvs: match\n")
    r = _run_a6(tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert _a6_report(tmp_path)["verdict"] == "PASS"


def test_ownership_guard_tool_generic_report_phrasings_still_pass(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD. The accepted phrasings stay TOOL-generic (Magic /
    KLayout / Calibre / Netgen wording), never a vendor or chip literal."""
    for i, (drc, lvs) in enumerate([
            ("DRC clean: 0 errors\n", "LVS match: 0 mismatches\n"),
            ("no drc violations\n", "Final result: Circuits match "
                                    "uniquely.\n"),
            ("total errors = 0\n", "netlists match\n"),
            ("count=0\n", "match: true\n")]):
        proj = tmp_path / f"p{i}"
        proj.mkdir()
        _block_list(proj, ["ldo"])
        d = _layout_only(proj, "ldo")
        (d / "drc_clean.flag").write_text(drc)
        (d / "lvs_match.flag").write_text(lvs)
        r = _run_a6(proj)
        assert r.returncode == 0, (drc, lvs, r.returncode, r.stderr)


# ---- the precondition the ownership move depended on ----------------------


def test_ownership_a6_reads_the_block_list_root_its_own_condition_names(
        tmp_path: Path) -> None:
    """THE PRECONDITION. A6's flow `condition` names
    `phase1/analog/analog_block_list.json`, but its block-list reader probed
    only `phase3/analog/` and the legacy `analog/`. On a project carrying the
    list ONLY at the flow-declared root, A6 returned `SKIP (no analog blocks)`
    with rc=2 — which `flow_compliance_check` credits as VACUOUS_PASS — while
    A5's flag rules were still catching the gap. Moving the PV verdict to A6
    without this fix would have opened a hole, so it is asserted here rather
    than assumed."""
    (tmp_path / "phase1" / "analog").mkdir(parents=True)
    (tmp_path / "phase1" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": ["ldo"]}))
    _layout_only(tmp_path, "ldo")   # layout done, PV evidence absent
    r = _run_a6(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rules = {f["rule"] for f in _a6_report(tmp_path)["findings"]}
    assert {"A6_PV_DRC_NO_EVIDENCE", "A6_PV_LVS_NO_EVIDENCE"} <= rules


def test_ownership_a6_still_skips_a_project_with_no_block_list(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD for the root fix: a project declaring analog blocks
    NOWHERE is still a genuine non-applicability (rc=2), not a new red."""
    r = _run_a6(tmp_path)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert _a6_report(tmp_path)["verdict"] == "SKIP"


# ── A DRAWN SHORT IS BLOCKING ───────────────────────────────────────────
#
# MEASURED on u_hawaii_adc (ihp-sg13g2, image 0.3.46): 13 pairs of routed
# nets were one conductor in the drawn layout — 1 on `ldo`, 12 on
# `delta_sigma` — while this gate reported PASS and A6's per-block LVS
# reported `mismatch` with nothing between the two able to say why. Every
# other number in `layout_provenance.json` is a clearance A6's deck
# adjudicates; this one is not a distance at all.
_WITNESS = ("nets vg and vout are ONE conductor in this layout: "
            "vg:metal5[46250, 13744, 46298, 13776] -> "
            "<device cc>:metal5[45714, 13200, 46834, 14320] -> "
            "vout:metal5[46505, 13744, 46553, 13776]")


def _provenance(project: Path, block: str, deviations: list) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout_provenance.json").write_text(json.dumps(
        {"producer": "analog_a5_layout_emit", "result": "OK",
         "deviations": deviations}, indent=2))


def test_drawn_short_in_the_producers_record_fails_the_gate(
        tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _layout_full(tmp_path, "ldo")
    _provenance(tmp_path, "ldo", [
        {"quantity": "bulk_tap_clearance_lambda", "required": 21,
         "achieved": 9, "detail": "a clearance A6's deck adjudicates"},
        {"quantity": "routed_nets_per_conductor", "required": 1,
         "achieved": 2, "detail": _WITNESS},
    ])
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "FAIL"
    rules = [f["rule"] for f in rpt["findings"]]
    assert "A5_LAYOUT_DRAWN_SHORT" in rules, rpt["findings"]
    hit = [f for f in rpt["findings"]
           if f["rule"] == "A5_LAYOUT_DRAWN_SHORT"][0]
    assert "<device cc>" in hit["detail"], (
        "the finding must carry the WITNESS PATH; a reader told only that "
        "two nets are one has been told the symptom")


def test_the_clearance_deviations_beside_it_do_not_fail_the_gate(
        tmp_path: Path) -> None:
    """THE CONTROL, and it is the one that matters: the SAME record with the
    short removed and every other deviation left in place is a PASS. This
    gate did not start judging clearances — A6 still owns those."""
    _block_list(tmp_path, ["ldo"])
    _layout_full(tmp_path, "ldo")
    _provenance(tmp_path, "ldo", [
        {"quantity": "bulk_tap_clearance_lambda", "required": 21,
         "achieved": 9, "detail": "a clearance A6's deck adjudicates"},
        {"quantity": "metal2_space_to_device_lambda", "required": 21,
         "achieved": 2, "detail": "another one"},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_no_record_at_all_is_not_read_as_a_clean_one(tmp_path: Path) -> None:
    """"Could not read it" is not "read it and it was clean". A block with
    no producer record is not asked — and is not failed for it either; the
    producer's own non-zero exit is the enforcement."""
    _block_list(tmp_path, ["ldo"])
    _layout_full(tmp_path, "ldo")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    rules = [f["rule"] for f in
             json.loads((tmp_path / "report.json").read_text())
             .get("findings", [])]
    assert "A5_LAYOUT_DRAWN_SHORT" not in rules
