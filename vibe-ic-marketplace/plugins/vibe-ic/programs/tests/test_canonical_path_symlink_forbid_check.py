"""tests/test_canonical_path_symlink_forbid_check.py — v1.6.51

Companion of test_chip_gds_canonical_real_file_check.py. Generalised
gate covers all 5 canonical-deliverable trees, every file extension.
"""
from __future__ import annotations

import os
from pathlib import Path

from programs.canonical_path_symlink_forbid_check import (
    audit, _FORBIDDEN_TREES,
)


def _real_file(p: Path, content: bytes = b"data") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


# ---------------------------------------------------------------------------
# Happy paths.
# ---------------------------------------------------------------------------

def test_vacuous_pass_no_canonical_trees(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    verdict, findings = audit(p)
    assert verdict == "VACUOUS_PASS"
    assert findings == []


def test_pass_real_files_in_every_canonical_tree(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _real_file(p / "phase3" / "stage4" / "gds" / "top.gds")
    _real_file(p / "phase3" / "mixed_signal" / "merged.gds")
    _real_file(p / "phase2" / "stage1" / "fpga" / "output_files" / "top.sof")
    _real_file(p / "phase2" / "stage2" / "synth" / "netlist.v")
    _real_file(p / "phase3" / "analog" / "hardmacro" / "blk_a" / "blk_a.lef")
    verdict, findings = audit(p)
    assert verdict == "PASS"
    assert findings == []


# ---------------------------------------------------------------------------
# Each forbidden tree triggers FAIL on a single symlink.
# ---------------------------------------------------------------------------

def test_symlink_in_phase3_stage4_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    src = p / "phase3" / "stage3" / "pnr" / "top.gds"
    _real_file(src, b"real bits")
    canonical = p / "phase3" / "stage4" / "gds" / "top.gds"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, canonical)
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert len(findings) == 1
    assert findings[0].rule == "SYMLINK_AT_CANONICAL_PATH"
    assert findings[0].tree == "phase3/stage4"
    assert findings[0].rel_path.endswith("top.gds")


def test_symlink_in_analog_hardmacro_fails(tmp_path: Path) -> None:
    """Backlog example: `analog/hardmacro/<block>/<block>.lef →
    ../../<block>/lef_skeleton.lef`."""
    p = tmp_path / "proj"
    src = p / "phase3" / "analog" / "blk_a" / "lef_skeleton.lef"
    _real_file(src)
    canonical = p / "phase3" / "analog" / "hardmacro" / "blk_a" / "blk_a.lef"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, canonical)
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert findings[0].tree == "phase3/analog/hardmacro"


def test_symlink_in_phase2_synth_netlist_fails(tmp_path: Path) -> None:
    """Backlog example: `phase2/stage2/synth/top_synth.v →
    ../stage1/rtl/top.v`."""
    p = tmp_path / "proj"
    src = p / "phase2" / "stage1" / "rtl" / "top.v"
    _real_file(src)
    canonical = p / "phase2" / "stage2" / "synth" / "top_synth.v"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, canonical)
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert findings[0].tree == "phase2/stage2/synth"


def test_symlink_in_phase2_fpga_sof_fails(tmp_path: Path) -> None:
    """Backlog example: `phase2/stage1/fpga/output_files/top.sof →
    ../../../old_runs/v3.sof`."""
    p = tmp_path / "proj"
    src = p / "old_runs" / "v3.sof"
    _real_file(src)
    canonical = p / "phase2" / "stage1" / "fpga" / "output_files" / "top.sof"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, canonical)
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert findings[0].tree == "phase2/stage1/fpga"


def test_symlink_in_phase3_mixed_signal_rpt_fails(tmp_path: Path) -> None:
    """`.rpt` sign-off file is a non-GDS extension the existing
    chip_gds gate could not catch."""
    p = tmp_path / "proj"
    src = p / "phase3" / "stage3" / "pnr" / "lvs_partial.rpt"
    _real_file(src)
    canonical = p / "phase3" / "mixed_signal" / "lvs_final.rpt"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, canonical)
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert findings[0].tree == "phase3/mixed_signal"
    assert findings[0].rel_path.endswith(".rpt")


# ---------------------------------------------------------------------------
# Broken symlink classification.
# ---------------------------------------------------------------------------

def test_broken_symlink_classified_separately(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    canonical = p / "phase3" / "stage4" / "gds" / "ghost.gds"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    # Symlink whose target never existed.
    os.symlink(p / "nonexistent" / "ghost.gds", canonical)
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert len(findings) == 1
    assert findings[0].rule == "BROKEN_SYMLINK"


# ---------------------------------------------------------------------------
# Allowlist exempts foundry-shipped symlinks.
# ---------------------------------------------------------------------------

def test_allowlist_exempts_named_path(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    src = p / "vendor_pdk" / "ref.lib"
    _real_file(src)
    canonical = (p / "phase3" / "analog" / "hardmacro" / "vendor_blk"
                 / "vendor_blk.lib")
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, canonical)
    # Without allowlist → FAIL
    verdict, _ = audit(p)
    assert verdict == "FAIL"
    # With allowlist → PASS
    (p / ".canonical_symlink_allowlist").write_text(
        "# vendor reference cell library (foundry-shipped)\n"
        "phase3/analog/hardmacro/vendor_blk/vendor_blk.lib\n")
    verdict2, findings2 = audit(p)
    assert verdict2 == "PASS"
    assert findings2 == []


def test_allowlist_supports_glob_patterns(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    for blk in ("v1", "v2", "v3"):
        src = p / "vendor_pdk" / f"{blk}.lib"
        _real_file(src)
        can = (p / "phase3" / "analog" / "hardmacro" / f"vendor_{blk}"
               / f"vendor_{blk}.lib")
        can.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(src, can)
    # Glob pattern matches all three vendor symlinks.
    (p / ".canonical_symlink_allowlist").write_text(
        "phase3/analog/hardmacro/vendor_*/*.lib\n")
    verdict, findings = audit(p)
    assert verdict == "PASS"
    assert findings == []


def test_allowlist_comments_and_blanks_ignored(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    src = p / "x.lib"
    _real_file(src)
    can = p / "phase3" / "analog" / "hardmacro" / "blk" / "blk.lib"
    can.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, can)
    (p / ".canonical_symlink_allowlist").write_text(
        "# this is a comment\n"
        "\n"
        "  # indented comment also ignored\n"
        "phase3/analog/hardmacro/blk/blk.lib\n"
        "\n")
    verdict, _ = audit(p)
    assert verdict == "PASS"


# ---------------------------------------------------------------------------
# Mixed scenarios.
# ---------------------------------------------------------------------------

def test_partial_failure_reports_all_offenders(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    # 1 real file + 2 symlinks across different trees.
    _real_file(p / "phase3" / "stage4" / "gds" / "real.gds")
    src1 = p / "external" / "a.sof"
    src2 = p / "external" / "b.lef"
    _real_file(src1)
    _real_file(src2)
    can1 = p / "phase2" / "stage1" / "fpga" / "output_files" / "a.sof"
    can2 = p / "phase3" / "analog" / "hardmacro" / "b" / "b.lef"
    can1.parent.mkdir(parents=True, exist_ok=True)
    can2.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src1, can1)
    os.symlink(src2, can2)
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert len(findings) == 2
    trees = {f.tree for f in findings}
    assert trees == {"phase2/stage1/fpga", "phase3/analog/hardmacro"}


def test_forbidden_trees_match_anti_fabrication_doctrine() -> None:
    """v1.6.30 anti-fabrication rule #1 enumerates 4 trees;
    backlog adds phase2/stage2/synth/. Gate must cover all 5."""
    expected = {
        "phase3/stage4",
        "phase3/mixed_signal",
        "phase2/stage1/fpga",
        "phase2/stage2/synth",
        "phase3/analog/hardmacro",
    }
    assert set(_FORBIDDEN_TREES) == expected

# --- the exit code is what the flow reads, and no test drove main()

def test_main_exits_non_zero_on_a_finding(tmp_path, monkeypatch):
    """`gate_cli_mutation_probe` reported this gate SILENT: neutering `main()`
    reddened nothing in its own test file.

    Every test above drives `audit()` and asserts the VERDICT it returns. The
    flow reads the EXIT CODE, and nothing exercised the mapping between them —
    the gate could have started answering 0 to every finding with the suite
    still green.
    """
    import canonical_path_symlink_forbid_check as M
    # Empty findings with a FAIL verdict: the verdict is what main()
    # maps to the exit code, and constructing this module's own finding
    # dataclass by guessing its fields tests my guess, not the gate.
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("FAIL", []))
    assert M.main([str(tmp_path)]) == 1


def test_main_exits_zero_when_clean(tmp_path, monkeypatch):
    """The other direction, or the test above is met by a gate that always
    fails."""
    import canonical_path_symlink_forbid_check as M
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("PASS", []))
    assert M.main([str(tmp_path)]) == 0


def test_main_refuses_on_a_missing_project(tmp_path):
    """rc 2 — the question could not be asked, which is not a pass."""
    import canonical_path_symlink_forbid_check as M
    assert M.main([str(tmp_path / "does_not_exist")]) == 2
