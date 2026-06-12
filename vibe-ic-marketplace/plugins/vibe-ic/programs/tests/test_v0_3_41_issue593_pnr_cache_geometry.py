"""ORGANIC #593 — pnr/gds cache-skip keyed on artifact existence ALONE,
so a re-run with a DIFFERENT --die-um/--util (the canonical
congestion-recovery for #585's ROUTE_NOT_CONVERGED) silently reused the
old die's DEF/GDS and re-reported byte-identical downstream DRC/LVS
failures (live: unconverged at auto-die 1233x1233 → re-dispatch
--die-um 1500x1500 --util 0.3 → "skipped re-run" → identical 640 DRC).

Fix: step_pnr persists the effective geometry in pnr_args.json;
_pnr_cache_valid_for() makes the cache valid ONLY when requested
die/util match the sidecar (absent sidecar = stale-unknown → re-run);
the orchestrator's cache-skip and the disclosure line consult it.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


# ── sidecar round-trip + validity semantics ─────────────────────────────────

def test_sidecar_roundtrip(tmp_path):
    R._write_pnr_args_sidecar(tmp_path, "1500x1500", 0.30)
    g = R._pnr_cache_geometry(tmp_path)
    assert g == {"die_um": "1500x1500", "util": 0.30}


def test_cache_valid_when_geometry_matches(tmp_path):
    R._write_pnr_args_sidecar(tmp_path, "1233x1233", 0.40)
    ok, msg = R._pnr_cache_valid_for(tmp_path, "1233x1233", 0.40)
    assert ok is True
    assert "unchanged" in msg


def test_cache_invalid_on_die_change(tmp_path):
    """The issue's exact 現象: cached at 1233x1233, requested 1500x1500
    → cache invalid, disclosure names both geometries."""
    R._write_pnr_args_sidecar(tmp_path, "1233x1233", 0.40)
    ok, msg = R._pnr_cache_valid_for(tmp_path, "1500x1500", 0.30)
    assert ok is False
    assert "1233x1233" in msg and "1500x1500" in msg
    assert "re-running to apply" in msg


def test_cache_invalid_on_util_change(tmp_path):
    R._write_pnr_args_sidecar(tmp_path, "1500x1500", 0.40)
    ok, msg = R._pnr_cache_valid_for(tmp_path, "1500x1500", 0.30)
    assert ok is False


def test_missing_sidecar_is_stale_unknown(tmp_path):
    """A pre-#593 artifact (no sidecar) must NOT be silently reused —
    treated as stale-unknown so a deliberate geometry change applies."""
    ok, msg = R._pnr_cache_valid_for(tmp_path, "1500x1500", 0.30)
    assert ok is False
    assert "pre-#593" in msg or "unknown" in msg


def test_util_float_tolerance(tmp_path):
    R._write_pnr_args_sidecar(tmp_path, "200x200", 0.3)
    ok, _ = R._pnr_cache_valid_for(tmp_path, "200x200", 0.30000000001)
    assert ok is True


# ── wiring: orchestrator consults the geometry cache, step_pnr writes it ────

def test_step_pnr_writes_geometry_sidecar():
    src = inspect.getsource(R.step_pnr)
    assert "_write_pnr_args_sidecar" in src
    # written with the EFFECTIVE die (post auto-resize), not the request
    assert 'f"{die_w}x{die_h}"' in src


def test_orchestrator_cache_skip_is_geometry_aware():
    src = inspect.getsource(R.main)
    assert "_pnr_cache_valid_for" in src
    # DEF existence alone no longer authorizes the skip
    assert "def_existing.is_file() and _cache_ok" in src
    # the GDS skip is invalidated when PnR re-ran
    assert "_pnr_reran" in src
