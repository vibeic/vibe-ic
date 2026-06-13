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
    (d / "lvs.report").write_text(
        "Netgen LVS\nCircuits match uniquely.\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert _report(tmp_path)["verdict"] == "PASS"


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
# WAIVER — evidence + ticket suppresses a genuine failure
# ---------------------------------------------------------------------------

def test_waiver_suppresses_fail(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _bdir(tmp_path, "ldo")  # missing evidence → would FAIL
    (tmp_path / "phase3" / "analog" / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "analog_block_pv",
            "ticket": "ECO-123",
            "reason": "PV deferred to top-level signoff per agreement",
        }]
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _report(tmp_path)
    assert rpt["verdict"] == "WAIVED"


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
