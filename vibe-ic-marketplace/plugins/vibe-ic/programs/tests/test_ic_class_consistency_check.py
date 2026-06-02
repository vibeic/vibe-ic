"""tests/test_ic_class_consistency_check.py — Wave 42 (v0.119.70 / SF6).

Cross-check facts.yaml vs detect_ic_class() output.  Five scenarios:
  1. PASS — bare-skeleton (silent SKIP)
  2. PASS — facts.yaml ic_class matches inferred
  3. FAIL — facts.yaml ic_class mismatches inferred
  4. FAIL — facts.yaml escape boolean contradicts inferred profile
  5. FAIL — Path A marker but vendor docs present
  6. PASS — facts.yaml absent but L docs present (no claim → no
     inconsistency)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent


def _write_json(p: Path, body: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body, indent=2))


def _write_text(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable,
         str(PROGRAMS / "ic_class_consistency_check.py"),
         str(project)],
        capture_output=True, text=True,
    )


def _evidence(name: str) -> dict:
    return {
        "extraction_evidence": {
            "vendor.pdf": [{"literal": f"sentinel-{name}", "label": name}],
        }
    }


def _build_pure_analog(project: Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    _write_json(project / "phase1/generated_docs/L1_DATASHEET.json", {
        **_evidence("L1"), "interface": "pure analog",
    })
    _write_json(project / "phase1/generated_docs/L2_FRS.json", {
        **_evidence("L2"), "interface": "pure analog",
    })
    _write_json(project / "phase1/generated_docs/L5_ADI_SPEC.json", {
        **_evidence("L5"),
        "analog_blocks": [{"name": "BANDGAP_REF"}],
    })


def test_bare_skeleton_skips(tmp_path: Path) -> None:
    project = tmp_path / "bare"
    project.mkdir(parents=True, exist_ok=True)
    proc = _run(project)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SKIP" in proc.stdout, proc.stdout


def test_facts_ic_class_matches_inferred_passes(tmp_path: Path) -> None:
    project = tmp_path / "match"
    _build_pure_analog(project)
    _write_text(project / "facts.yaml", "ic_class: pure_analog\n")
    proc = _run(project)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout, proc.stdout
    assert "pure_analog" in proc.stdout


def test_facts_ic_class_mismatch_fails(tmp_path: Path) -> None:
    project = tmp_path / "mismatch"
    _build_pure_analog(project)
    _write_text(
        project / "facts.yaml",
        "ic_class: aid_class_half_duplex\n",
    )
    proc = _run(project)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "FAIL" in proc.stdout
    assert "ic_class" in proc.stdout


def test_escape_boolean_contradiction_fails(tmp_path: Path) -> None:
    """facts.yaml asserts no_analog=true but L5 has analog blocks."""
    project = tmp_path / "escape_lie"
    _build_pure_analog(project)
    _write_text(project / "facts.yaml", "no_analog: true\n")
    proc = _run(project)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "no_analog" in proc.stdout
    assert "analog" in proc.stdout.lower()


def test_path_a_marker_with_vendor_docs_fails(tmp_path: Path) -> None:
    project = tmp_path / "path_a_lie"
    project.mkdir(parents=True, exist_ok=True)
    (project / "input/docs").mkdir(parents=True)
    (project / "input/docs/vendor.pdf").write_text("x")
    _write_text(project / "facts.yaml",
                "phase1_skipped_path_a: true\n")
    proc = _run(project)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "phase1_skipped_path_a" in proc.stdout


def test_no_facts_yaml_with_l_docs_passes(tmp_path: Path) -> None:
    """No claim made → no inconsistency."""
    project = tmp_path / "no_claim"
    _build_pure_analog(project)
    proc = _run(project)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout
