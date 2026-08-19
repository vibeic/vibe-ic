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
    # #364 — the two files must not be BYTE-IDENTICAL unless a test is
    # deliberately exercising the no-op case. This fixture defaulted to
    # `"x" * 100` for BOTH, so every test that used the defaults was also,
    # incidentally, asserting that an identical filled.def is acceptable —
    # which is the false-PASS #364 measured on real silicon (identical DEFs,
    # zero FILLWIRES, step-34 PASS, 6 whole-die density violations shipped).
    # Distinct fill bytes keep each test's ACTUAL property (in-window
    # density / rows-already-full as substance) as the deciding branch,
    # while byte-identity gets its own explicit tests in
    # test_metal_fill_density_check.py.
    (pnr / "routed.def").write_text("x" * routed_sz)
    (pnr / "filled.def").write_text(
        "x" * filled_sz if filled_sz != routed_sz else "y" * filled_sz)
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


def test_byte_identical_but_rows_already_full_passes(tmp_path):
    """#364 regression: when std-cell fill was placed DURING PnR the routed.def
    baseline already carries every fill cell (row_utilization_pct>=95), so the
    standalone step correctly emits a BYTE-IDENTICAL filled.def. That is fill
    DONE, not fill MISSING — it must NOT raise FILL_NOOP, and it must disclose
    FILL_DONE_AT_PNR so the byte-identity is explained, not silent."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    same = "IDENTICAL-ROUTED-AND-FILLED-DEF\n" * 20
    (pnr / "routed.def").write_text(same)
    (pnr / "filled.def").write_text(same)          # byte-identical on purpose
    (pnr / "metal_fill.done").write_text("metal_fill_done\n")
    rpt = tmp_path / "reports"
    rpt.mkdir(parents=True, exist_ok=True)
    (rpt / "density.json").write_text(json.dumps(
        {"tool": "openroad-filler_placement",
         "filler_instances": 0, "row_utilization_pct": 100.0}))
    findings, stats = MF.audit(tmp_path)
    assert stats["filled_byte_identical"] is True
    assert stats["rows_already_full"] is True
    assert not any(f.category == "FILL_NOOP" for f in findings)
    assert not any(f.severity == "ERROR" for f in findings), \
        [(f.category, f.severity) for f in findings]
    assert any(f.category == "FILL_DONE_AT_PNR" for f in findings)


def test_byte_identical_rows_not_full_still_fails(tmp_path):
    """Guard: byte-identical with rows NOT full is still a genuine no-op FAIL."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    same = "IDENTICAL\n" * 20
    (pnr / "routed.def").write_text(same)
    (pnr / "filled.def").write_text(same)
    (pnr / "metal_fill.done").write_text("metal_fill_done\n")
    rpt = tmp_path / "reports"
    rpt.mkdir(parents=True, exist_ok=True)
    (rpt / "density.json").write_text(json.dumps(
        {"tool": "openroad-filler_placement",
         "filler_instances": 0, "row_utilization_pct": 40.0}))
    findings, stats = MF.audit(tmp_path)
    assert any(f.category == "FILL_NOOP" and f.severity == "ERROR"
               for f in findings)
