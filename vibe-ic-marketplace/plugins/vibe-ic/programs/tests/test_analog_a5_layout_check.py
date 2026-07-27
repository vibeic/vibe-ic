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
# Reproduced on main @ v1.7.36: a block with a real 255-byte layout.mag and
# `: > drc_clean.flag` / `: > lvs_match.flag` (both 0 bytes, verified with
# `find -printf '%s'`) returned `PASS — 1/1 block(s) clean`, rc=0, with and
# without `--block`. The module docstring already claimed "any NON-EMPTY
# file"; the code only did `is_file()`. One step later,
# analog_a6_block_pv_check rejects exactly these flags
# ("Bare flag with no count line -> NOT acceptable evidence").
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
    LVS verdict) are the shape A6 already refuses; A5 now refuses them too."""
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
    """Because the content check REUSES A6's parser rather than inventing a
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


def test_d5_parser_import_failure_degrades_but_never_fails_open(
        tmp_path: Path) -> None:
    """Degraded-mode contract (a NEW behaviour, so it fails on the base tree
    like the other d5 discriminators). The content check borrows A6's parsers
    via a cross-program import. If that import ever fails the gate must
    DEGRADE to the docstring's stated minimum (a non-empty flag) — never fail
    open on a 0-byte flag, and never fail EVERY block on an ImportError."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_a5_under_test", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_a5_under_test"] = mod
    sys.path.insert(0, str(PROG.parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(PROG.parent))
    mod._PARSE_DRC_COUNT = None
    mod._PARSE_LVS_MATCH = None

    d = tmp_path / "blk"
    d.mkdir()
    empty = d / "drc_clean.flag"
    empty.write_bytes(b"")
    # Degraded mode still catches the 0-byte flag (never fails open) …
    assert mod._drc_flag_defect(empty)[0] == "A5_DRC_FLAG_EMPTY"
    # … but does not condemn a verdict-free flag it can no longer parse.
    verdictless = d / "lvs_match.flag"
    verdictless.write_text("clean\n")
    assert mod._lvs_flag_defect(verdictless) is None
