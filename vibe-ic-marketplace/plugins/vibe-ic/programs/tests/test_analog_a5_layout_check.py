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
    (d / "drc_clean.flag").write_text("DRC clean: 0 errors\n")
    (d / "lvs_match.flag").write_text("LVS match: 0 mismatches\n")


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

    d5 FIX: this test used to write `drc_clean.flag`='clean' /
    `lvs_match.flag`='match', i.e. flags carrying NO parseable verdict, and
    assert PASS — so it encoded the very hole d5 reports (A5 accepting a
    contentless sign-off flag) as the expected behaviour of the happy path.
    The assertion it actually claims to make is about the LAYOUT
    representation (GDS instead of .mag), so the flags are corrected to real
    sign-off evidence; the `returncode == 0` assertion is unchanged."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ldo.gds").write_bytes(_GDS_WITH_GEOMETRY)
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr


def test_empty_geometry_gds_fails(tmp_path: Path) -> None:
    """ORGANIC #144 no-leak — a size-passing but geometry-EMPTY GDS (the
    `readspice`+`gds write` empty stream) FAILs the tightened gate."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ldo.gds").write_bytes(_GDS_EMPTY_GEOMETRY)
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
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
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
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
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout


def test_real_mag_with_instances_passes(tmp_path: Path) -> None:
    """A .mag whose geometry is cell instances (`use` lines) — no paint
    rects — still passes (instance-based placement is real geometry).

    d5 FIX: same correction as `test_happy_path_gds_alternative` — the
    verdict-less 'clean'/'match' flags this test used to write made it an
    accidental guarantee that a contentless sign-off flag PASSes A5. The
    claim under test is the .mag geometry parse, so the flags now carry real
    evidence; the `returncode == 0` assertion is unchanged."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    body = "magic\ntech sky130A\ntimestamp 0\n"
    for i in range(8):
        body += (f"use sky130_fd_pr__nfet_01v8 m{i}\n"
                 f"transform 1 0 0 0 1 {i*10}\nbox 0 0 100 100\n")
    (d / "layout.mag").write_text(body)
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "analog-layout"


def test_drc_flag_missing_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _layout_full(tmp_path, "ldo")
    (tmp_path / "phase3" / "analog" / "ldo" / "drc_clean.flag").unlink()
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A5_DRC_FLAG_MISSING" in f["rule"]
               for f in rpt["findings"])


def test_lvs_flag_missing_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _layout_full(tmp_path, "ldo")
    (tmp_path / "phase3" / "analog" / "ldo" / "lvs_match.flag").unlink()
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A5_LVS_FLAG_MISSING" in f["rule"]
               for f in rpt["findings"])


def test_layout_too_small_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text("magic\n")  # < 200B
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
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
    """A per-block dir with a REAL-geometry layout and REAL sign-off flags."""
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text(
        "magic\ntech sky130A\ntimestamp 0\n" + "rect 0 0 100 100\n" * 20)
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
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
# A5/d5 — the DRC / LVS sign-off flags must carry a real verdict
#
# Reproduced on main @ v1.7.36 with the fixture THIS FILE builds — a block
# whose `_layout_only` layout.mag is 371 bytes (31-byte magic header + 20
# `rect 0 0 100 100` lines) and whose `drc_clean.flag` / `lvs_match.flag` are
# 0 bytes: `PASS — 1/1 block(s) clean`, rc=0, with and without `--block`.
# (PR #464's prose cited a "255-byte layout.mag"; that was the author's own
# ad-hoc fixture, not this one, and it does not reproduce byte-for-byte. Only
# the >200-byte threshold is load-bearing, and both shapes clear it.)
# The module docstring already claimed "any NON-EMPTY file"; the code only
# did `is_file()`. One step later, analog_a6_block_pv_check rejects exactly
# these flags — "Bare flag with no count line -> NOT acceptable evidence" —
# BUT only when no DRC/LVS report sits beside them; see the FOLLOW-UP block
# at the end of this file for the parity the original claim overstated.
# ===========================================================================


def _layout_only(project: Path, block: str) -> Path:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text(
        "magic\ntech sky130A\ntimestamp 0\n" + "rect 0 0 100 100\n" * 20)
    return d


def test_d5_zero_byte_drc_flag_fails(tmp_path: Path) -> None:
    """THE d5 DISCRIMINATOR (DRC). A `touch`-created 0-byte drc_clean.flag
    is not DRC sign-off. Before the fix this was rc=0 / PASS."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc_clean.flag").write_bytes(b"")
    (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "FAIL", rpt
    assert {f["rule"] for f in rpt["findings"]} == {"A5_DRC_FLAG_EMPTY"}, rpt


def test_d5_zero_byte_lvs_flag_fails(tmp_path: Path) -> None:
    """THE d5 DISCRIMINATOR (LVS). Same for lvs_match.flag."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_bytes(b"")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert {f["rule"] for f in rpt["findings"]} == {"A5_LVS_FLAG_EMPTY"}, rpt


def test_d5_whitespace_only_flags_fail(tmp_path: Path) -> None:
    """A flag holding only whitespace is the same non-evidence as a 0-byte
    flag — a byte-count test alone would let this through."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("   \n\n\t\n")
    (d / "lvs_match.flag").write_text("\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert {f["rule"] for f in rpt["findings"]} == {
        "A5_DRC_FLAG_EMPTY", "A5_LVS_FLAG_EMPTY"}, rpt


def test_d5_verdictless_flags_fail(tmp_path: Path) -> None:
    """Non-empty but verdict-free flags ('clean' / 'match' with no count or
    LVS verdict), WITH NO DRC/LVS REPORT beside them, are the shape A6 already
    refuses; A5 refuses them too. (The report-present case is the opposite
    way round — see test_followup_bare_flags_beside_real_reports_*.)"""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("ok\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert {f["rule"] for f in rpt["findings"]} == {
        "A5_DRC_FLAG_NO_EVIDENCE", "A5_LVS_FLAG_NO_EVIDENCE"}, rpt


def test_d5_drc_flag_declaring_violations_fails(tmp_path: Path) -> None:
    """A `drc_clean.flag` whose own content says the block is NOT clean must
    never be read as sign-off."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("violations: 7\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert {f["rule"] for f in rpt["findings"]} == {"A5_DRC_NOT_CLEAN"}, rpt


def test_d5_lvs_flag_declaring_mismatch_fails(tmp_path: Path) -> None:
    """Likewise for an `lvs_match.flag` that reports a mismatch."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: mismatch\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert {f["rule"] for f in rpt["findings"]} == {"A5_LVS_NOT_MATCH"}, rpt


def test_d5_netgen_shaped_flag_without_terminal_verdict_fails(
        tmp_path: Path) -> None:
    """Because the evidence check REUSES A6's resolver rather than inventing a
    second dialect, A5 also inherits the shared netgen fail-safe: a
    netgen-shaped transcript with no terminal `Final result:` line is an
    unfinished compare and must not be read as a match."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text(
        "Subcircuit summary:\nCircuits match uniquely.\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert {f["rule"] for f in rpt["findings"]} == {
        "A5_LVS_FLAG_NO_EVIDENCE"}, rpt


def test_d5_block_mode_empty_flags_are_fail_not_waived(
        tmp_path: Path) -> None:
    """The MISSING-vs-FAIL split must hold: a block WITH a layout but with
    contentless flags is a substance FAIL (rc=1), not a deferral (rc=2).
    Returning 2 here would let the runner mark the step WAIVED."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc_clean.flag").write_bytes(b"")
    (d / "lvs_match.flag").write_bytes(b"")
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "FAIL", rpt


# ---- d5 direction-1 guards: behaviour that must NOT change ----------------


def test_d5_guard_runner_deterministic_stub_flags_still_pass(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD. `analog_one_shot_runner._emit_deterministic_stub`
    writes these exact flag bodies for A6_block_pv (it was already hardened
    to A6's standard). A5 must accept them, or every stub dry-run turns red
    for the wrong reason. Byte-for-byte copy of the runner's output shape,
    including the `_wt` provenance header line."""
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
    r = _run(tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS", rpt


def test_d5_guard_tool_generic_report_phrasings_still_pass(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD. The accepted phrasings stay TOOL-generic (Magic /
    KLayout / Calibre / Netgen wording), never a vendor or chip literal —
    the check must not become a hard-coded string match on one flow."""
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
        r = _run(proj)
        assert r.returncode == 0, (drc, lvs, r.returncode, r.stderr)


def test_d5_guard_missing_flag_file_still_reports_missing_rule(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD. An ABSENT flag must keep its own distinct rule
    (A5_*_FLAG_MISSING) — the new content rules must not swallow it, or the
    finding stops telling an operator whether to run the tool or to fix its
    output."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert {f["rule"] for f in rpt["findings"]} == {"A5_DRC_FLAG_MISSING"}, rpt


def _isolated_a5_without_a6(tmp_path: Path) -> Path:
    """Copy the gate (and the shared helper it imports) into a directory that
    does NOT contain `analog_a6_block_pv_check.py`, so the cross-program
    import genuinely fails. Exercising degraded mode this way keeps the test
    on the OBSERVABLE contract (exit code + rule set through the CLI); the
    previous version monkeypatched private module globals and called private
    helpers by name, so it passed the mutant only via AttributeError and would
    have reddened against any correct fix that renamed or inlined them."""
    import shutil

    iso = tmp_path / "_iso_programs"
    iso.mkdir()
    for name in ("analog_a5_layout_check.py", "_analog_a_check_common.py"):
        shutil.copy2(PROG.parent / name, iso / name)
    assert not (iso / "analog_a6_block_pv_check.py").exists()
    return iso / "analog_a5_layout_check.py"


def _run_prog(prog: Path, project: Path,
              *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(prog), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True, cwd=str(project),
    )


def test_d5_parser_import_failure_degrades_but_never_fails_open(
        tmp_path: Path) -> None:
    """Degraded-mode contract, asserted through the CLI. The evidence check
    borrows A6's readers via a cross-program import. If that import ever fails
    the gate must DEGRADE to the docstring's stated minimum (a non-empty flag)
    — never fail open on a 0-byte flag, and never turn EVERY block red on an
    ImportError."""
    prog = _isolated_a5_without_a6(tmp_path)

    # (a) never fails OPEN: a 0-byte flag is still a FAIL without A6.
    p_open = tmp_path / "p_open"
    p_open.mkdir()
    _block_list(p_open, ["ldo"])
    d = _layout_only(p_open, "ldo")
    (d / "drc_clean.flag").write_bytes(b"")
    (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run_prog(prog, p_open)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((p_open / "report.json").read_text())
    assert {f["rule"] for f in rpt["findings"]} == {"A5_DRC_FLAG_EMPTY"}, rpt

    # (b) never fails CLOSED on every block: a verdict-free flag it can no
    #     longer parse is not condemned, so an ImportError cannot blanket-red
    #     the run.
    p_closed = tmp_path / "p_closed"
    p_closed.mkdir()
    _block_list(p_closed, ["ldo"])
    d = _layout_only(p_closed, "ldo")
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("ok\n")
    r = _run_prog(prog, p_closed)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)

    # … and the SAME fixture is a FAIL when A6 IS importable, which is what
    # proves (b) is degraded mode and not a hole in the normal path.
    r = _run(p_closed)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)


# ===========================================================================
# A5/d5 FOLLOW-UP — the PARITY the d5 fix CLAIMED but did not have
#
# PR #464's module comment and detail strings justify the flag-content check
# as "exactly the standard `analog_a6_block_pv_check` already enforces one
# step later" / "as A6 requires". Measured on main @ v1.7.58, that was false:
# A6's `_drc_violations` / `_lvs_match` read the block's TOOL REPORTS first
# (drc.report / *.lyrdb / comp.json / lvs.report …) and fall back to the flag
# only last, whereas A5 read the FLAG ALONE. On one directory carrying a
# real-geometry layout.mag, `drc.report` = "total errors = 0",
# `lvs.report` = "Final result: Circuits match uniquely." and bare marker
# flags "clean"/"match":
#     analog_a6_block_pv_check -> rc=0 PASS (1/1 DRC-0 + LVS-match)
#     analog_a5_layout_check   -> rc=1 FAIL (A5_DRC_FLAG_NO_EVIDENCE,
#                                            A5_LVS_FLAG_NO_EVIDENCE)
# and on the PR's merge-base (7153eb9e9) A5 PASSed that same directory. Since
# A5's flow leg is a `program_exit_zero` inside `all_of`, that is a BLOCKING
# false-fail live on main: driving the real `flow_compliance_check.py` on
# that project moved step A5 from `status: PASS` (merge-base) to
# `status: FAIL` (main) with the A5_*_NO_EVIDENCE text as its reason.
# ===========================================================================


def _reports(d: Path, *, drc: str = "Magic DRC summary\ntotal errors = 0\n",
             lvs: str = ("Subcircuit summary:\n"
                         "Final result: Circuits match uniquely.\n")) -> None:
    """The tool reports A6 prefers over the flag."""
    (d / "drc.report").write_text(drc)
    (d / "lvs.report").write_text(lvs)


def _run_a6(project: Path) -> subprocess.CompletedProcess:
    a6 = PROG.parent / "analog_a6_block_pv_check.py"
    return subprocess.run(
        [sys.executable, str(a6), str(project),
         "--json", str(project / "a6.json")],
        capture_output=True, text=True,
    )


def test_followup_bare_flags_beside_real_reports_are_not_a_fail(
        tmp_path: Path) -> None:
    """THE FOLLOW-UP DISCRIMINATOR. Real DRC/LVS reports + bare marker flags:
    the evidence for sign-off is present and says clean/match, so A5 must
    PASS. On main this was rc=1 with A5_DRC_FLAG_NO_EVIDENCE +
    A5_LVS_FLAG_NO_EVIDENCE."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    _reports(d)
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("match\n")
    r = _run(tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS", rpt


def test_followup_a5_and_a6_agree_on_the_same_block_dir(
        tmp_path: Path) -> None:
    """The PROPERTY the committed comment asserts: A5 and A6 must not reach
    opposite verdicts on one directory. Checked over four evidence shapes,
    including the two where the evidence lives ONLY in the reports."""
    shapes = [
        ("reports_and_bare_flags", True, "clean\n", "match\n"),
        ("reports_and_no_flags", True, None, None),
        ("flags_only_real_verdicts", False, "violations: 0\n", "lvs: match\n"),
        ("flags_only_bare", False, "clean\n", "match\n"),
    ]
    for name, with_reports, drc_flag, lvs_flag in shapes:
        proj = tmp_path / name
        proj.mkdir()
        _block_list(proj, ["ldo"])
        d = _layout_only(proj, "ldo")
        if with_reports:
            _reports(d)
        if drc_flag is not None:
            (d / "drc_clean.flag").write_text(drc_flag)
        if lvs_flag is not None:
            (d / "lvs_match.flag").write_text(lvs_flag)
        a5 = _run(proj)
        a6 = _run_a6(proj)
        assert (a5.returncode == 0) == (a6.returncode == 0), (
            name, a5.returncode, a5.stdout, a6.returncode, a6.stdout)


def test_followup_no_flag_at_all_but_real_reports_passes(
        tmp_path: Path) -> None:
    """`analog_a6_native_pv.py` — the only real in-repo PRODUCER of per-block
    PV evidence — writes `drc.report` / `comp.json` and writes NO
    `drc_clean.flag` / `lvs_match.flag` at all. A5 must read what that
    producer emits instead of demanding a file nothing writes."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    _reports(d)
    r = _run(tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


def test_followup_comp_json_is_accepted_lvs_evidence(tmp_path: Path) -> None:
    """A6's LVS precedence starts at netgen's structured `comp.json`; A5
    inherits it rather than re-deciding what an LVS verdict looks like."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc.report").write_text("total errors = 0\n")
    (d / "comp.json").write_text(json.dumps({"result": "match"}))
    r = _run(tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


# ---- follow-up direction-1 guards: the fix must not become a loophole -----


def test_followup_guard_report_violations_beat_a_flag_claiming_zero(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD / anti-weakening. Precedence means the REPORT wins,
    not 'whichever artefact says clean wins'. A drc.report declaring 3 errors
    next to a `drc_clean.flag` saying `violations: 0` is a FAIL. On main
    (flag-only) this PASSed."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    _reports(d, drc="total errors = 3\n")
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert {f["rule"] for f in rpt["findings"]} == {"A5_DRC_NOT_CLEAN"}, rpt


def test_followup_guard_report_mismatch_beats_a_flag_claiming_match(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD / anti-weakening. Same for LVS: an lvs.report saying
    the circuits do not match outranks an `lvs_match.flag` saying `match`."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    _reports(d, lvs="Final result: Circuits do not match.\n")
    (d / "drc_clean.flag").write_text("violations: 0\n")
    (d / "lvs_match.flag").write_text("lvs: match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert {f["rule"] for f in rpt["findings"]} == {"A5_LVS_NOT_MATCH"}, rpt


def test_followup_guard_empty_reports_do_not_rescue_a_bare_flag(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD. The d5 hole must stay shut: report files that exist
    but carry no verdict (0-byte / whitespace) are not evidence, so a bare
    flag beside them is still A5_*_FLAG_NO_EVIDENCE."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc.report").write_bytes(b"")
    (d / "lvs.report").write_text("   \n")
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert {f["rule"] for f in rpt["findings"]} == {
        "A5_DRC_FLAG_NO_EVIDENCE", "A5_LVS_FLAG_NO_EVIDENCE"}, rpt


def test_followup_guard_reports_do_not_excuse_a_missing_layout(
        tmp_path: Path) -> None:
    """DIRECTION-1 GUARD. Reading the PV reports must not leak into the d2
    coverage rule: a declared block with perfect DRC/LVS evidence but NO
    layout is still an uncovered block, so a 2-block project with one such
    block stays INCOMPLETE."""
    _block_list(tmp_path, ["blk_ok", "blk_missing"])
    _layout_and_flags(tmp_path, "blk_ok")
    d = tmp_path / "phase3" / "analog" / "blk_missing"
    d.mkdir(parents=True)
    _reports(d)
    r = _run(tmp_path)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "INCOMPLETE", rpt
    assert {f["rule"] for f in rpt["findings"]} == {"A5_LAYOUT_MISSING"}, rpt


def test_followup_guard_detail_text_no_longer_misattributes_to_a6(
        tmp_path: Path) -> None:
    """The emitted detail said "need an explicit violation count … AS A6
    REQUIRES", which A6 does not require when a report is present — an
    operator following that message would rewrite a flag A6 was already
    happy to ignore. The message must state A5's ACTUAL requirement: either
    a report or a verdict in the flag."""
    _block_list(tmp_path, ["ldo"])
    d = _layout_only(tmp_path, "ldo")
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("ok\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    details = " ".join(f["detail"] for f in rpt["findings"])
    assert "as A6 requires" not in details, details
    assert "drc.report" in details and "lvs.report" in details, details
