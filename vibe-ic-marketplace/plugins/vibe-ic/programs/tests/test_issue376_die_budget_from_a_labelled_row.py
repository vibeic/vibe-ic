#!/usr/bin/env python3
"""A die budget stated as a labelled table row was invisible to the extractor.

vibe-ic#376 instance 3. MEASURED: 194 of 194 tracked `L19_CONSTRAINTS_PDK.json`
carry `die_area_budget_um: null`. Not because the designs are silent — several
input documents state a die size plainly:

    | Die size | **2400 x 2400 um (5.76 mm2)** (1.4M cells + 20 macros; L1) |
    | Core die (no seal ring) | 1300 x 1300 um |

Every recogniser in `floorplan_contract` needed a `DIE_AREA` / `DIE_WIDTH`
keyword, and none of those rows has one. So the extractor answered "no mandated
floorplan", the L19 emitter returned early on
`if not contract.get("constraints_present")`, and the consumer
(`l9_floorplan_contract_check`) hit `if not isinstance(val, str): return None`
— rc 0, vacuous, on every design.

The consequence is not bookkeeping. `phase3_one_shot_runner` documents its die
precedence as `... > L19-mandated die_area_budget_um > 'auto'`, so that middle
rung has never been reached: a design that states its die size got `--die-um
auto` picking its own floorplan instead.

TWO DISCRIMINATORS, both measured over the published input documents:

    labelled form (label names a die AND the value carries a length unit)
        16 occurrences across 2 ICs
    unlabelled (any `W x H <unit>`)
        24 occurrences

The 8 extra are what this must never read as a die. Both halves are pinned
below — a pixel resolution and an array shape must not become a floorplan.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import floorplan_contract as F  # noqa: E402

_CORPUS = _PROGRAMS.parents[3] / "benchmark-data" / "ic"


def _doc(tmp_path: Path, body: str) -> Path:
    d = tmp_path / "cell"
    (d / "input" / "docs").mkdir(parents=True)
    (d / "input" / "docs" / "L9_CONSTRAINTS.md").write_text(body)
    (d / "phase1").mkdir(parents=True, exist_ok=True)
    return d


def test_a_labelled_die_row_is_extracted(tmp_path):
    """THE LOAD-BEARING CASE — the form real documents use."""
    d = _doc(tmp_path, "| Die size | **2400 x 2400 um (5.76 mm2)** |\n")
    r = F.extract_floorplan_contract(d)
    assert r["constraints_present"] is True, r
    assert r["die_area_budget_um"] == "2400x2400", r


def test_the_source_is_recorded(tmp_path):
    """A value with no provenance cannot be audited — and a WRONG extraction
    has to be traceable to the line it came from."""
    d = _doc(tmp_path, "| Core die (no seal ring) | 1300 x 1300 um |\n")
    r = F.extract_floorplan_contract(d)
    assert r["die_area_budget_um"] == "1300x1300"
    assert r["die_area_source"], r


def test_a_pixel_resolution_is_NOT_a_die(tmp_path):
    """PAIRED HALF #1. `1024x768` carries no length unit and no die label."""
    d = _doc(tmp_path, "| Display | 1024x768 |\n| Frame buffer | 640x480 |\n")
    r = F.extract_floorplan_contract(d)
    assert r["die_area_budget_um"] is None, r


def test_an_array_shape_is_NOT_a_die(tmp_path):
    """PAIRED HALF #2. A `16x16` PE array is the shape this must never size a
    floorplan from — and it is the reason the LABEL is required, not just the
    unit."""
    d = _doc(tmp_path, "| PE array | 16 x 16 |\n| Tiles | 32 x 32 |\n")
    r = F.extract_floorplan_contract(d)
    assert r["die_area_budget_um"] is None, r


def test_a_dimension_with_a_unit_but_no_die_label_is_refused(tmp_path):
    """The sharper half of the label rule: a length-unit dimension that is NOT
    a die (a package, a pad ring pitch table) must not be adopted."""
    d = _doc(tmp_path, "| Package body | 400 x 400 um |\n")
    r = F.extract_floorplan_contract(d)
    assert r["die_area_budget_um"] is None, r


def test_the_keyword_forms_still_work(tmp_path):
    """Regression guard: the new recogniser runs LAST, so a document carrying a
    canonical `DIE_AREA` rect must still win by the old path."""
    d = _doc(tmp_path, "DIE_AREA = [0 0 500 700]\n"
                       "| Die size | 2400 x 2400 um |\n")
    r = F.extract_floorplan_contract(d)
    assert r["die_area_budget_um"] == "500x700", r


def test_the_two_published_cells_now_resolve():
    """Real data, and the measurement that justified the change."""
    import pytest
    seen = 0
    for name, expect in (("edge_llm_accel", "2400x2400"),
                         ("u_hawaii_adc", "1300x1300")):
        d = _CORPUS / name
        if not (d / "phase1").is_dir():
            continue
        seen += 1
        r = F.extract_floorplan_contract(d)
        assert r["die_area_budget_um"] == expect, (name, r)
    if seen == 0:
        pytest.skip("published corpus not checked out")


def test_a_cell_that_states_no_die_stays_None():
    """The other direction on real data: spm states no die size and must not
    acquire one."""
    import pytest
    d = _CORPUS / "spm" / "v1.5.65_sky130A"
    if not (d / "phase1").is_dir():
        pytest.skip("cell not checked out")
    r = F.extract_floorplan_contract(d)
    assert r["die_area_budget_um"] is None, r
