"""Unit tests for def_stage_progression_check.py.

Catches the 5-identical-DEF fabrication pattern seen in the BENCH-A
2026-04-22 pilot (subagent copied `ic_a_top.def` to all 5 stage names
and declared PnR complete).

Tests:
  1. 5 byte-identical DEFs                 — FAIL (identical-def-fraud)
  2. Missing some stages                   — FAIL (missing-stage)
  3. Monotone-growing but hash-distinct    — PASS
  4. routed.def SMALLER than floorplan.def — FAIL (size-non-monotone)
  5. routed.def has no `+ ROUTED`          — FAIL (no-routing-geometry)
  6. Real progression with all markers     — PASS
"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "def_stage_progression_check.py"
assert SCRIPT.exists()


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(project)],
        capture_output=True, text=True,
    )


def _make_def(path: Path, *, n_components: int, routed: bool, filler: str = ""):
    """Write a minimal DEF with the requested shape."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "VERSION 5.8 ;",
        f"DESIGN top ;",
        f"DIEAREA ( 0 0 ) ( 10000 10000 ) ;",
        f"COMPONENTS {n_components} ;",
    ]
    for i in range(n_components):
        lines.append(f"  - U_{i} AND2X1 + PLACED ( {i*100} {i*100} ) N ;")
    lines.append("END COMPONENTS")
    if routed:
        lines.append("NETS 2 ;")
        lines.append("  - n1 ( U_0 Y ) ( U_1 A )")
        lines.append("    + ROUTED met1 ( 100 100 ) ( 200 100 )")
        lines.append("    ;")
        lines.append("  - n2 ( U_1 Y ) ( U_2 A )")
        lines.append("    + ROUTED met2 ( 300 100 ) ( 400 100 )")
        lines.append("    ;")
        lines.append("END NETS")
    lines.append(filler)
    lines.append("END DESIGN")
    path.write_text("\n".join(lines) + "\n")


def test_5_identical_defs_fraud(tmp_path):
    for stage in ["floorplan", "placed", "post_cts", "post_hold", "routed"]:
        _make_def(tmp_path / "phase3" / "stage3" / "pnr" / f"{stage}.def", n_components=100, routed=True)
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "identical-def-fraud" in r.stdout + r.stderr


def test_missing_stages(tmp_path):
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "floorplan.def", n_components=10, routed=False)
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "routed.def", n_components=200, routed=True)
    r = _run(tmp_path)
    assert r.returncode == 1
    out = r.stdout + r.stderr
    assert "missing-stage" in out


def test_routed_smaller_than_floorplan(tmp_path):
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "floorplan.def", n_components=200, routed=True,
              filler="X"*5000)
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "placed.def", n_components=200, routed=True,
              filler="X"*5100)
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "post_cts.def", n_components=200, routed=True,
              filler="X"*5200)
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "post_hold.def", n_components=200, routed=True,
              filler="X"*5300)
    # Shrink routed — suspicious
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "routed.def", n_components=50, routed=True,
              filler="X"*100)
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "size-non-monotone" in (r.stdout + r.stderr) \
        or "instance-count-regression" in (r.stdout + r.stderr)


def test_routed_has_no_routing(tmp_path):
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "floorplan.def", n_components=10, routed=False)
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "placed.def", n_components=100, routed=False,
              filler="p"*100)
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "post_cts.def", n_components=110, routed=False,
              filler="c"*200)
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "post_hold.def", n_components=115, routed=False,
              filler="h"*300)
    # routed but no `+ ROUTED` → catch
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "routed.def", n_components=115, routed=False,
              filler="r"*400)
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "no-routing-geometry" in (r.stdout + r.stderr)


def test_real_progression_passes(tmp_path):
    """Monotone growth + distinct hashes + routed geometry → PASS."""
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "floorplan.def", n_components=100, routed=False,
              filler="f"*100)
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "placed.def", n_components=300, routed=False,
              filler="p"*200)
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "post_cts.def", n_components=350, routed=False,
              filler="c"*300)  # +50 CTS buffers
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "post_hold.def", n_components=380, routed=False,
              filler="h"*400)  # +30 hold buffers
    _make_def(tmp_path / "phase3" / "stage3" / "pnr" / "routed.def", n_components=380, routed=True,
              filler="r"*1000)  # + routing geometry
    r = _run(tmp_path)
    assert r.returncode == 0, f"stdout={r.stdout[:500]}\nstderr={r.stderr[:500]}"
