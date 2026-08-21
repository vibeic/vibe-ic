"""Unit tests for dft_atpg_coverage_check.py — Step 11 DFT/ATPG real
stuck-at coverage gate (anti-fabrication).

The gate this checker replaces TRUSTED the self-produced boolean
`stuck_at_ge_target`. These tests pin that the new checker:

  * PASS  — measured stuck-at coverage >= target (substance good).
  * FAIL  — measured < target (the real sha256 0%-coverage DFT deficit).
  * FAIL  — fabricated boolean (`stuck_at_ge_target: true`) while the real
            measured number is below target → recomputed verdict wins.
  * FAIL  — no report at all (missing data, honest FAIL — NOT vacuous pass).
  * supports the .rpt fallback and both coverage.json schemas.

2026-07 DFT-depth raise: the checker now enforces a FOUNDRY floor (default
95 %) so a lenient written target cannot pass a sub-foundry number. The
tests below that assert PASS at a sub-95 % target are exercising the
RECOMPUTE mechanism (measured-field selection / .rpt fallback / ratio
normalisation) in ISOLATION, so they pin `--foundry-floor 0`
(`foundry_floor=0`) to hold the floor out of the way. The foundry-floor
behaviour itself is pinned in test_dft_foundry_depth.py.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG_DIR = Path(__file__).parent.parent
SCRIPT = PROG_DIR / "dft_atpg_coverage_check.py"
assert SCRIPT.exists()

sys.path.insert(0, str(PROG_DIR))
import dft_atpg_coverage_check as chk  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────

def _write_cov(project: Path, payload: dict) -> Path:
    """Write coverage.json at the canonical reports/phase2/dft/ path."""
    d = project / "reports" / "phase2" / "dft"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "coverage.json"
    p.write_text(json.dumps(payload, indent=2))
    return p


def _write_rpt(project: Path, text: str) -> Path:
    d = project / "phase2" / "stage2" / "dft"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "atpg_coverage.rpt"
    p.write_text(text)
    return p


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
    )


# ── PASS: substance good (fault_atpg_run schema) ────────────────────────

def test_pass_measured_above_target_fault_schema(tmp_path):
    """Real v047-style coverage.json: 81.72% >= 55% target → PASS."""
    _write_cov(tmp_path, {
        "tool": "fault",
        "coverage_pct": 81.7208707332611,
        "faults_covered": 8016,
        "faults_total": 9809,
        "target_pct": 55.0,
        "stuck_at_ge_target": True,
    })
    r = _run(str(tmp_path), "--foundry-floor", "0")
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "PASS"
    # checker rounds to 4 decimals for the report
    assert abs(rep["measured_coverage_pct"] - 81.7209) < 1e-3
    assert rep["target_pct"] == 55.0
    assert rep["recomputed_ge_target"] is True
    assert rep["self_assertion_mismatch"] is False
    # The checker derived the number from the measured field, not the bool.
    assert rep["measured_source"] == "coverage_pct"


def test_pass_runner_schema(tmp_path):
    """Runner/skill schema (stuck_at_coverage_percent / stuck_at_target)."""
    _write_cov(tmp_path, {
        "tool": "fault",
        "stuck_at_coverage_percent": 92.5,
        "stuck_at_target": 85.0,
        "stuck_at_ge_target": True,
    })
    assert chk.main([str(tmp_path), "--foundry-floor", "0"]) == 0


# ── FAIL: the real silicon deficit — measured < target ──────────────────

def test_fail_zero_coverage_design_deficit(tmp_path):
    """Exact sha256 v2 e2e case: 0% coverage, target 50% — no scan chain
    stitched. The producing step honestly wrote stuck_at_ge_target=false;
    the gate MUST FAIL (untestable silicon)."""
    _write_cov(tmp_path, {
        "tool": "fault",
        "scan_inserted": False,
        "stuck_at_coverage_percent": 0.0,
        "stuck_at_target": 50.0,
        "stuck_at_ge_target": False,
        "vectors_generated": 200,
        "deficit_class": "DESIGN_DEFICIT",
    })
    r = _run(str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "FAIL"
    assert rep["recomputed_ge_target"] is False
    assert any("below required floor" in x or "< " in x for x in rep["reasons"])


def test_fail_measured_just_below_target(tmp_path):
    _write_cov(tmp_path, {
        "coverage_pct": 54.9,
        "target_pct": 55.0,
        "stuck_at_ge_target": False,
    })
    assert chk.main([str(tmp_path)]) == 1


# ── FAIL: fabricated boolean — the #1 anti-fab case ─────────────────────

def test_fail_fabricated_boolean_overridden(tmp_path):
    """A fabricating step wrote stuck_at_ge_target=true while the real
    measured coverage (10%) is far below target (80%). The checker must
    IGNORE the boolean, recompute FAIL, and flag the mismatch."""
    _write_cov(tmp_path, {
        "coverage_pct": 10.0,
        "target_pct": 80.0,
        "stuck_at_ge_target": True,   # <-- fabricated self-assertion
    })
    r = _run(str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "FAIL"
    assert rep["self_asserted_ge_target"] is True
    assert rep["recomputed_ge_target"] is False
    assert rep["self_assertion_mismatch"] is True
    assert any("contradicts" in x for x in rep["reasons"])


# ── Missing data → honest FAIL (never vacuous pass) ─────────────────────

def test_fail_no_report_at_all(tmp_path):
    r = _run(str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "FAIL"
    assert rep["measured_coverage_pct"] is None
    assert any("no DFT/ATPG coverage evidence" in x for x in rep["reasons"])


def test_fail_present_but_no_number(tmp_path):
    """coverage.json present but carries only the boolean — no real number
    to verify → honest FAIL (insufficient substance, not a pass)."""
    _write_cov(tmp_path, {"stuck_at_ge_target": True})
    r = _run(str(tmp_path))
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "FAIL"
    assert any("no measured stuck-at coverage" in x for x in rep["reasons"])


def test_fail_invalid_json(tmp_path):
    d = tmp_path / "reports" / "phase2" / "dft"
    d.mkdir(parents=True)
    (d / "coverage.json").write_text("{ not json")
    r = _run(str(tmp_path))
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "FAIL"


# ── .rpt fallback parsing (both dialects) ───────────────────────────────

def test_rpt_fallback_fault_dialect_pass(tmp_path):
    """No coverage.json, only the fault_atpg_run .rpt → parse the
    'Stuck-at %' + 'Target (min)' lines."""
    _write_rpt(tmp_path,
               "Fault ATPG Coverage Report\n"
               "==========================\n"
               "Clock         : clk_i\n"
               "Stuck-at %    : 88.40\n"
               "Covered / Total: 880 / 996\n"
               "Target (min)  : 80.00\n"
               "Result        : PASS\n")
    r = _run(str(tmp_path), "--foundry-floor", "0")
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "PASS"
    assert rep["measured_source"] == "atpg_coverage.rpt"
    assert abs(rep["measured_coverage_pct"] - 88.40) < 1e-6
    assert abs(rep["target_pct"] - 80.0) < 1e-6


def test_rpt_fallback_runner_dialect_fail(tmp_path):
    """Runner .rpt dialect: 'Stuck-at coverage reached : 0.0% (target was ≥50%)'."""
    _write_rpt(tmp_path,
               "# Fault ATPG coverage report (Step 11)\n"
               "Test vectors generated     : 200\n"
               "Stuck-at coverage reached  : 0.0% (target was ≥50%)\n"
               "Result: stuck_at_coverage = 0.0%, target ≥ 50%, status FAIL\n")
    r = _run(str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "FAIL"
    assert rep["measured_coverage_pct"] == 0.0
    assert rep["target_pct"] == 50.0


def test_json_missing_target_falls_back_to_rpt(tmp_path):
    """coverage.json has the measured number but NO target; the .rpt
    supplies the target. Both substance pieces required → must combine."""
    _write_cov(tmp_path, {"coverage_pct": 70.0})  # no target field
    _write_rpt(tmp_path, "Stuck-at %    : 70.00\nTarget (min)  : 65.00\n")
    r = _run(str(tmp_path), "--foundry-floor", "0")
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "PASS"
    assert rep["target_source"] == "atpg_coverage.rpt"


# ── ratio normalisation ─────────────────────────────────────────────────

def test_ratio_normalised_to_percent(tmp_path):
    """A fractional ratio (0.91) must be read as 91%, not 0.91%."""
    res = chk.evaluate({"coverage_pct": 0.91, "target_pct": 80.0,
                        "stuck_at_ge_target": True}, None, foundry_floor=0)
    assert res["measured_coverage_pct"] == 91.0
    assert res["verdict"] == "PASS"


# ── --json output + arg handling ────────────────────────────────────────

def test_writes_json_output(tmp_path):
    _write_cov(tmp_path, {"coverage_pct": 90.0, "target_pct": 80.0,
                          "stuck_at_ge_target": True})
    out = tmp_path / "out.json"
    rc = chk.main([str(tmp_path), "--json", str(out), "--foundry-floor", "0"])
    assert rc == 0
    assert out.is_file()
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"


def test_not_a_directory(tmp_path):
    rc = chk.main([str(tmp_path / "nope")])
    assert rc == 2


def test_coverage_json_override(tmp_path):
    explicit = tmp_path / "elsewhere" / "cov.json"
    explicit.parent.mkdir(parents=True)
    explicit.write_text(json.dumps({"coverage_pct": 95.0, "target_pct": 80.0,
                                    "stuck_at_ge_target": True}))
    rc = chk.main([str(tmp_path), "--coverage-json", str(explicit)])
    assert rc == 0
