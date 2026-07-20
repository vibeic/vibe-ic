"""Unit tests for placement_legality_check.py (Step 17 substance gate).

The real backend failure this guards: a placed.def whose components are
still UNPLACED — the exact shape of a pre-placement floorplan.def that was
copied/renamed to placed.def, or a placement run that aborted leaving
cells without a location. LEF/DEF 5.8: a component is placed only if it
states PLACED / FIXED / COVER with a location; no status keyword = the
default UNPLACED.

Fixtures:
  * PASS  — every component has + PLACED ( x y ) status.
  * FAIL  — floorplan-style DEF: components have NO placement status
            (implicitly UNPLACED). This is the real failure mode.
  * FAIL  — an explicit ``+ UNPLACED`` mixed in with placed cells.
  * FAIL  — declared COMPONENTS count != parsed records (truncated DEF).
  * FAIL  — COMPONENTS 0 (empty placement).
  * FAIL  — missing / empty / garbage placed.def (honesty on absence).
  * FAIL  — density artefact reporting > 100% (overlap).
  * PASS  — density artefact in (0,100]% alongside fully-placed DEF.
  * SKIP  — project dir not found.
"""
import json
import subprocess
import sys
from pathlib import Path
from _hostpaths import require_repo  # noqa: E402

SCRIPT = Path(__file__).parent.parent / "placement_legality_check.py"
assert SCRIPT.exists()

_PNR = "phase3/stage3/pnr"


def _run(project: Path, json_out: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(SCRIPT), str(project)]
    if json_out is not None:
        argv += ["--json", str(json_out)]
    return subprocess.run(argv, capture_output=True, text=True)


def _write_placed_def(project: Path, *, n: int, status: str = "PLACED",
                      declared: int | None = None, extra_unplaced: int = 0,
                      density_comment: float | None = None,
                      no_components_section: bool = False) -> Path:
    """Write a minimal placed.def.

    status: the placement keyword for the n bulk components, or the
            literal "none" to emit floorplan-style records with NO status
            keyword (implicitly UNPLACED).
    extra_unplaced: additionally append this many explicit `+ UNPLACED`
            records.
    declared: override the COMPONENTS <n> declared count (default = total
            records emitted).
    """
    d = project / _PNR
    d.mkdir(parents=True, exist_ok=True)
    total = n + extra_unplaced
    lines = [
        "VERSION 5.8 ;",
        "DESIGN top ;",
        "UNITS DISTANCE MICRONS 1000 ;",
        "DIEAREA ( 0 0 ) ( 100000 100000 ) ;",
    ]
    if density_comment is not None:
        lines.append(f"# DENSITY {density_comment}")
    if not no_components_section:
        decl = declared if declared is not None else total
        lines.append(f"COMPONENTS {decl} ;")
        for i in range(n):
            if status == "none":
                lines.append(f"    - U_{i} AND2X1 ;")
            else:
                lines.append(
                    f"    - U_{i} AND2X1 + {status} ( {i*100} {i*200} ) N ;")
        for j in range(extra_unplaced):
            lines.append(f"    - X_{j} AND2X1 + UNPLACED ;")
        lines.append("END COMPONENTS")
    lines.append("END DESIGN")
    p = d / "placed.def"
    p.write_text("\n".join(lines) + "\n")
    return p


# ── PASS fixture: every component placed ───────────────────────────────

def test_all_placed_passes(tmp_path):
    _write_placed_def(tmp_path, n=50, status="PLACED")
    j = tmp_path / "out.json"
    r = _run(tmp_path, j)
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(j.read_text())
    assert doc["gate"] == "placement_legality_check"
    assert doc["verdict"] == "PASS"
    assert doc["placed"] == 50 and doc["unplaced"] == 0


def test_fixed_status_also_placed(tmp_path):
    # FIXED (e.g. macros / pads) is a legal placement status too.
    _write_placed_def(tmp_path, n=20, status="FIXED")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


# ── FAIL fixture: the real backend failure (floorplan copied) ──────────

def test_floorplan_style_no_status_fails(tmp_path):
    """Components with NO placement keyword = implicitly UNPLACED.
    This is exactly a renamed floorplan.def — the real failure."""
    _write_placed_def(tmp_path, n=40, status="none")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "UNPLACED_INSTANCES" in (r.stdout + r.stderr)


def test_explicit_unplaced_mixed_fails(tmp_path):
    _write_placed_def(tmp_path, n=30, status="PLACED", extra_unplaced=3)
    j = tmp_path / "out.json"
    r = _run(tmp_path, j)
    assert r.returncode == 1, r.stdout + r.stderr
    doc = json.loads(j.read_text())
    assert doc["verdict"] == "FAIL"
    assert doc["unplaced"] == 3


# ── FAIL fixture: structural defects ───────────────────────────────────

def test_count_mismatch_fails(tmp_path):
    # Declare 100 but only emit 30 records → truncated/malformed.
    _write_placed_def(tmp_path, n=30, status="PLACED", declared=100)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "COMPONENT_COUNT_MISMATCH" in (r.stdout + r.stderr)


def test_zero_components_fails(tmp_path):
    _write_placed_def(tmp_path, n=0, status="PLACED", declared=0)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "EMPTY_COMPONENTS" in (r.stdout + r.stderr)


def test_no_components_section_fails(tmp_path):
    _write_placed_def(tmp_path, n=0, no_components_section=True)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NO_COMPONENTS_SECTION" in (r.stdout + r.stderr)


# ── FAIL fixture: missing / empty / garbage (honesty on absence) ───────

def test_missing_placed_def_fails(tmp_path):
    (tmp_path / _PNR).mkdir(parents=True)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PLACED_DEF_MISSING" in (r.stdout + r.stderr)


def test_empty_placed_def_fails(tmp_path):
    d = tmp_path / _PNR
    d.mkdir(parents=True)
    (d / "placed.def").write_text("")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PLACED_DEF_EMPTY" in (r.stdout + r.stderr)


def test_garbage_placed_def_fails(tmp_path):
    d = tmp_path / _PNR
    d.mkdir(parents=True)
    (d / "placed.def").write_text("this is not a DEF file at all\n\x00\xff binary\n")
    r = _run(tmp_path)
    # No COMPONENTS section → honest FAIL, never a vacuous pass.
    assert r.returncode == 1, r.stdout + r.stderr
    assert ("NO_COMPONENTS_SECTION" in (r.stdout + r.stderr)
            or "PLACED_DEF_UNPARSEABLE" in (r.stdout + r.stderr))


# ── Density: derivable, sanity-bounded (never fabricated) ──────────────

def test_density_over_100_fails(tmp_path):
    _write_placed_def(tmp_path, n=20, status="PLACED", density_comment=101.5)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "DENSITY_OVER_100" in (r.stdout + r.stderr)


def test_density_fraction_ok_passes(tmp_path):
    # 0.63 → 63% utilization, within (0,100].
    _write_placed_def(tmp_path, n=20, status="PLACED", density_comment=0.63)
    j = tmp_path / "out.json"
    r = _run(tmp_path, j)
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(j.read_text())
    assert doc["density_pct"] == 63.0


def test_density_not_derivable_does_not_fabricate(tmp_path):
    _write_placed_def(tmp_path, n=20, status="PLACED")
    j = tmp_path / "out.json"
    r = _run(tmp_path, j)
    assert r.returncode == 0, r.stdout + r.stderr
    doc = json.loads(j.read_text())
    assert doc["density_pct"] is None
    assert any(f["rule"] == "DENSITY_NOT_DERIVABLE" for f in doc["findings"])


def test_density_json_report_over_100_fails(tmp_path):
    _write_placed_def(tmp_path, n=20, status="PLACED")
    rep = tmp_path / "reports" / "phase3"
    rep.mkdir(parents=True)
    (rep / "density.json").write_text(json.dumps({"placement_density_pct": 142.0}))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "DENSITY_OVER_100" in (r.stdout + r.stderr)


# ── SKIP: not a project dir ────────────────────────────────────────────

def test_skip_when_not_a_dir(tmp_path):
    missing = tmp_path / "does_not_exist"
    r = _run(missing)
    assert r.returncode == 2, r.stdout + r.stderr


# ── Real artefact regression (if present in the tree) ──────────────────

def test_real_placed_def_if_present():
    real = require_repo("benchmark-data/ic/subservient_v0125_fresh")
    if not (real / _PNR / "placed.def").is_file():
        return  # tree not present in this checkout — skip silently
    r = _run(real)
    assert r.returncode == 0, r.stdout + r.stderr
