"""v0.2.75 — #445: metal fill must substantiate, not just exist.

The audited rot: metal_fill.log showed "Placed 0 filler instances" with
pre/post design area byte-identical, yet the step PASSed because
metal_fill.done existed and the (data-less) density report raised no
ERROR; filled.def-not-larger was only a WARNING.

Pins:
  * gate: 0 fillers + no growth + no in-window per-layer density + rows
    not already full → FILL_NO_SUBSTANCE ERROR;
  * gate: claimed fillers with filled.def NOT larger → contradiction
    ERROR;
  * legitimate shapes still PASS: fillers placed + def grew; rows
    already ~full (0 fillers correct); in-window per-layer densities;
  * runner: done marker withheld on a no-op run (source pin).

chip-AGNOSTIC: structural artifact shapes only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import metal_fill_density_check as MF  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()


def _proj(tmp_path, filler_n=0, row_util=None, filled_sz=100,
          routed_sz=100, layers=None):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text("x" * routed_sz)
    (pnr / "filled.def").write_text("x" * filled_sz)
    (pnr / "metal_fill.done").write_text("metal_fill_done\n")
    rpt = tmp_path / "reports"
    rpt.mkdir(parents=True, exist_ok=True)
    payload = {"tool": "openroad-filler_placement",
               "filler_instances": filler_n,
               "row_utilization_pct": row_util}
    if layers is not None:
        payload["layers"] = layers
    (rpt / "density.json").write_text(json.dumps(payload))
    return tmp_path


def test_noop_fill_fails(tmp_path):
    # the audited shape: 0 fillers, identical sizes, no density data
    _proj(tmp_path, filler_n=0, row_util=None)
    findings, stats = MF.audit(tmp_path)
    assert any(f.category == "FILL_NO_SUBSTANCE" and f.severity == "ERROR"
               for f in findings)


def test_rows_already_full_zero_fillers_passes(tmp_path):
    _proj(tmp_path, filler_n=0, row_util=99.2)
    findings, stats = MF.audit(tmp_path)
    assert not any(f.severity == "ERROR" for f in findings)
    assert stats["rows_already_full"] is True


def test_fillers_placed_and_def_grew_passes(tmp_path):
    _proj(tmp_path, filler_n=1234, filled_sz=500, routed_sz=100)
    findings, stats = MF.audit(tmp_path)
    assert not any(f.severity == "ERROR" for f in findings)


def test_claimed_fillers_but_def_not_larger_contradiction(tmp_path):
    _proj(tmp_path, filler_n=1234, filled_sz=100, routed_sz=100)
    findings, stats = MF.audit(tmp_path)
    assert any(f.category == "FILL_CLAIM_CONTRADICTION" for f in findings)


def test_in_window_per_layer_density_passes(tmp_path):
    _proj(tmp_path, filler_n=0,
          layers=[{"name": "met1", "density_pct": 42.0},
                  {"name": "met2", "density_pct": 55.0}])
    findings, stats = MF.audit(tmp_path)
    assert not any(f.severity == "ERROR" for f in findings)
    assert stats["layers_ok"] == 2


def test_runner_withholds_done_marker_on_noop():
    i = _P3_SRC.index("fill_substantiated = placed_n > 0")
    window = _P3_SRC[i - 600:i + 1400]
    assert "metal_fill_noop.txt" in window
    assert "#445" in window
