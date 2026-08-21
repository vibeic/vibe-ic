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


# ---------------------------------------------------------------------------
# #364 FILL_DONE_AT_PNR exemption. When the std-cell filler ran DURING PnR the
# routed.def baseline already carries the fill cells, so the LATER standalone
# step correctly places 0 and writes a BYTE-IDENTICAL filled.def. That is fill
# DONE, not fill MISSING.
#
# §4.05 — the exemption is a RELAXATION, so these fixtures pin BOTH directions.
# The decisive one is `..._rows_full_but_zero_fill_cells_still_fails`: keying the
# exemption on row-utilization ALONE leaks, because the runner computes
# row_utilization_pct over every CORE*-class instance (logic AND fill), so a
# densely-placed design that was NEVER filled also reads >= 95. The exemption
# therefore also requires fill cells MEASURED PRESENT in the baseline.
# ---------------------------------------------------------------------------
_DEF_HEAD = ("VERSION 5.8 ;\nDESIGN t ;\nUNITS DISTANCE MICRONS 1000 ;\n")


def _def_with(components: str, n: int) -> str:
    return (_DEF_HEAD + f"COMPONENTS {n} ;\n" + components
            + "END COMPONENTS\nEND DESIGN\n")


# Deliberately NO pdk/vendor prefix in these fixtures: the matcher keys on the
# generic physical-cell naming convention, so a neutral prefix must match.
_DEF_ALREADY_FILLED = _def_with(
    "- u_logic0 GENERIC_NAND2  + PLACED ( 1000 1000 ) N ;\n"
    "- u_logic1 GENERIC_DFF    + PLACED ( 2000 1000 ) N ;\n"
    "- FILLER_0 GENERIC_fill_1 + PLACED ( 3000 1000 ) N ;\n"
    "- FILLER_1 GENERIC_fill_4 + PLACED ( 4000 1000 ) N ;\n", 4)

_DEF_DENSE_NO_FILL = _def_with(
    "- u_logic0 GENERIC_NAND2  + PLACED ( 1000 1000 ) N ;\n"
    "- u_logic1 GENERIC_DFF    + PLACED ( 2000 1000 ) N ;\n"
    "- u_logic2 GENERIC_INV    + PLACED ( 3000 1000 ) N ;\n"
    "- u_logic3 GENERIC_AOI22  + PLACED ( 4000 1000 ) N ;\n", 4)


def _byte_identical_project(tmp_path, def_text, row_util):
    """routed.def == filled.def (byte-identical on purpose) + a density.json."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text(def_text)
    (pnr / "filled.def").write_text(def_text)
    (pnr / "metal_fill.done").write_text("metal_fill_done\n")
    rpt = tmp_path / "reports"
    rpt.mkdir(parents=True, exist_ok=True)
    (rpt / "density.json").write_text(json.dumps(
        {"tool": "openroad-filler_placement",
         "filler_instances": 0, "row_utilization_pct": row_util}))
    return tmp_path


def test_byte_identical_rows_full_and_fill_present_passes(tmp_path):
    """The real shape this exemption exists for: rows full AND the baseline
    measurably carries fill cells → no FILL_NOOP, and FILL_DONE_AT_PNR is
    DISCLOSED with the measured count so the byte-identity is explained."""
    p = _byte_identical_project(tmp_path, _DEF_ALREADY_FILLED, 100.0)
    findings, stats = MF.audit(p)
    assert stats["filled_byte_identical"] is True
    assert stats["rows_already_full"] is True
    assert stats["baseline_fill_instances"] == 2
    assert stats["fill_done_at_pnr"] is True
    assert not any(f.category == "FILL_NOOP" for f in findings)
    assert not any(f.severity == "ERROR" for f in findings), \
        [(f.category, f.severity) for f in findings]
    disc = [f for f in findings if f.category == "FILL_DONE_AT_PNR"]
    assert disc, [(f.category, f.severity) for f in findings]
    # the claim must carry the number it was measured from, not assert it
    assert "2" in disc[0].message


def test_byte_identical_rows_full_but_zero_fill_cells_still_fails(tmp_path):
    """§4.05 NEGATIVE CONTROL — the leak this exemption must not open.

    A densely-placed design reads row_utilization_pct >= 95 from LOGIC alone
    (the runner sums every CORE*-class master), and here the baseline carries
    ZERO fill cells: fill never ran. Byte-identity is then exactly the defect
    #364 exists to catch, so FILL_NOOP MUST still fire and the gate must NOT
    claim fill is present."""
    p = _byte_identical_project(tmp_path, _DEF_DENSE_NO_FILL, 98.0)
    findings, stats = MF.audit(p)
    assert stats["rows_already_full"] is True     # the proxy is satisfied ...
    assert stats["baseline_fill_instances"] == 0  # ... but there is no fill
    assert stats["fill_done_at_pnr"] is False
    assert any(f.category == "FILL_NOOP" and f.severity == "ERROR"
               for f in findings), [(f.category, f.severity) for f in findings]
    assert not any(f.category == "FILL_DONE_AT_PNR" for f in findings)


def test_byte_identical_rows_not_full_still_fails(tmp_path):
    """Guard: byte-identical with rows NOT full is still a genuine no-op FAIL."""
    p = _byte_identical_project(tmp_path, _DEF_DENSE_NO_FILL, 40.0)
    findings, _ = MF.audit(p)
    assert any(f.category == "FILL_NOOP" and f.severity == "ERROR"
               for f in findings)


def test_byte_identical_unmeasurable_baseline_is_not_exempt(tmp_path):
    """Fail-closed: a routed.def with no COMPONENTS section cannot substantiate
    'already filled'. NOT MEASURED must not be treated as measured-zero OR as
    measured-present — the exemption is withheld and FILL_NOOP fires."""
    p = _byte_identical_project(tmp_path, "GARBAGE-NOT-A-DEF\n" * 20, 100.0)
    findings, stats = MF.audit(p)
    assert stats["baseline_fill_instances"] is None
    assert stats["fill_done_at_pnr"] is False
    assert any(f.category == "FILL_NOOP" and f.severity == "ERROR"
               for f in findings)


def test_fill_master_matcher_is_naming_convention_not_pdk_literal():
    """The matcher must recognise the row-fill NAMING CONVENTION across PDK
    prefixes without any PDK/vendor/SKU literal in the program, and must not
    claim ordinary logic masters."""
    for master in ("aaa_fill_1", "bbb_fd_sc_hd__fill_2", "ccc__fill_8",
                   "FILLER_4", "DECAP8", "fillcap_3", "dcap_2"):
        assert MF._FILL_MASTER_RE.search(master), master
    for master in ("NAND2_X1", "DFFRPQ_X2", "sky_INV_X4", "AOI22_X1",
                   "BUFFER_X8", "TAPCELL_X1"):
        assert not MF._FILL_MASTER_RE.search(master), master
