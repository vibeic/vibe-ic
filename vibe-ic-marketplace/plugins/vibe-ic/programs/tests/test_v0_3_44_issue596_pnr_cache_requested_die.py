"""ORGANIC #596 — the #593 PnR geometry cache wrote the EFFECTIVE
(auto-resized) die to the sidecar but the cache validity check compared
the REQUESTED --die-um arg. On any design that auto-resized (the entire
default/auto-die path), the recorded "806x806" never equalled the
compared "200x200", so the cache was ALWAYS judged invalid and route
re-ran from scratch every invocation — emitter↔checker drift
(#531/#572 family).

Fix: the sidecar's cache KEY is the REQUESTED die (`die_um`, never
mutated in step_pnr); the effective post-resize die is recorded for
disclosure only. A same-args auto-die re-run now HITS the cache; a
deliberate --die-um override still misses and re-runs (#593's
congestion-recovery case preserved).
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


# ── sidecar records requested key + effective disclosure ────────────────────

def test_sidecar_records_requested_and_effective(tmp_path):
    R._write_pnr_args_sidecar(tmp_path, "200x200", 0.30,
                              effective_die_um="806x806")
    g = R._pnr_cache_geometry(tmp_path)
    assert g["die_um"] == "200x200"            # cache KEY = requested
    assert g["effective_die_um"] == "806x806"  # disclosure only
    assert g["util"] == 0.30


def test_auto_die_same_args_rerun_hits_cache(tmp_path):
    """The issue's exact 現象: requested 200x200 auto-grew to 806x806;
    a re-run with the SAME requested args must HIT the cache (the same
    netlist reproduces the same auto-die, so reusing the DEF is correct)."""
    R._write_pnr_args_sidecar(tmp_path, "200x200", 0.30,
                              effective_die_um="806x806")
    ok, msg = R._pnr_cache_valid_for(tmp_path, "200x200", 0.30)
    assert ok is True, msg
    assert "unchanged" in msg
    # disclosure still surfaces the effective die
    assert "806x806" in msg


def test_explicit_die_override_misses_cache(tmp_path):
    """#593 congestion-recovery preserved: a deliberate bigger --die-um
    still MISSES (re-runs to apply the new geometry)."""
    R._write_pnr_args_sidecar(tmp_path, "200x200", 0.30,
                              effective_die_um="806x806")
    ok, msg = R._pnr_cache_valid_for(tmp_path, "1500x1500", 0.30)
    assert ok is False
    assert "re-running to apply" in msg


def test_util_change_misses_cache(tmp_path):
    R._write_pnr_args_sidecar(tmp_path, "200x200", 0.40,
                              effective_die_um="806x806")
    ok, _ = R._pnr_cache_valid_for(tmp_path, "200x200", 0.30)
    assert ok is False


def test_missing_sidecar_stale_unknown(tmp_path):
    ok, msg = R._pnr_cache_valid_for(tmp_path, "200x200", 0.30)
    assert ok is False
    assert "pre-#593" in msg or "unknown" in msg


def test_sidecar_without_effective_still_valid(tmp_path):
    """Back-compat: a sidecar written without effective_die_um (e.g. a
    non-resized run) still matches on requested."""
    R._write_pnr_args_sidecar(tmp_path, "1000x1000", 0.45)
    ok, _ = R._pnr_cache_valid_for(tmp_path, "1000x1000", 0.45)
    assert ok is True


# ── step_pnr writes the requested key, not the effective die ────────────────

def test_step_pnr_writes_requested_die_as_key():
    src = inspect.getsource(R.step_pnr)
    # the write passes the requested `die_um` arg as the key + effective
    # as disclosure — NOT the pre-fix `f"{die_w}x{die_h}"` as the key.
    assert "_write_pnr_args_sidecar(out_dir, die_um, util," in src
    assert 'effective_die_um=f"{die_w}x{die_h}"' in src
