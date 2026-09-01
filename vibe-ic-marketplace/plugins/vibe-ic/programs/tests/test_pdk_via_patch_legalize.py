"""Regression tests for routing-aware legalization of explicit VIA landings."""

import sys
import json
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as runner  # noqa: E402


def _illegal_techlef() -> str:
    return """VERSION 5.7 ;
MANUFACTURINGGRID 0.005 ;
LAYER route_b
  TYPE ROUTING ;
  MINWIDTH 0.280 ;
  AREA 0.1444 ;
END route_b
LAYER cut_bc
  TYPE CUT ;
END cut_bc
LAYER route_c
  TYPE ROUTING ;
  MINWIDTH 0.280 ;
  AREA 0.1444 ;
END route_c
VIA transition_bc DEFAULT
  LAYER cut_bc ;
    RECT -0.130 -0.130 0.130 0.130 ;
  LAYER route_b ;
    RECT -0.140 -0.190 0.140 0.190 ;
  LAYER route_c ;
    RECT -0.190 -0.140 0.190 0.140 ;
END transition_bc
VIARULE transition_bc_gen GENERATE
  LAYER route_b ;
    ENCLOSURE 0.010 0.060 ;
  LAYER route_c ;
    ENCLOSURE 0.060 0.010 ;
  LAYER cut_bc ;
    RECT -0.130 -0.130 0.130 0.130 ;
END transition_bc_gen
END LIBRARY
"""


def test_explicit_via_landings_are_grown_from_the_layers_own_rules():
    """A 0.28 x 0.38 landing is 0.1064 square units, below the layer's
    independently-declared 0.1444 minimum.  The least centered grid-aligned
    growth is the literal 0.38 x 0.38 rectangle on both orientations.
    """
    from pdk_via_patch_legalize import legalize_via_patches

    fixed, report = legalize_via_patches(_illegal_techlef())

    assert "RECT -0.190 -0.190 0.190 0.190 ;" in fixed
    assert fixed.count("RECT -0.190 -0.190 0.190 0.190 ;") == 2
    assert report["changed_patch_records"] == 4
    assert report["changed_rectangles"] == 2
    assert report["changed_enclosures"] == 2

    assert {row["form"] for row in report["changes"]} == {"VIA", "VIARULE"}
    assert {row["before_area"] for row in report["changes"]} == {"0.1064"}
    assert {row["after_area"] for row in report["changes"]} == {"0.1444"}
    assert fixed.count("ENCLOSURE 0.060 0.060 ;") == 2
    assert report["remaining_via_rule_violations"] == 0


def test_legal_explicit_via_is_byte_identical():
    """The transform is a no-op when the PDK's own landing already meets both
    rules; a healthy tech LEF must not be reformatted or otherwise rewritten.
    """
    from pdk_via_patch_legalize import legalize_via_patches

    src = _illegal_techlef().replace(
        "RECT -0.140 -0.190 0.140 0.190 ;",
        "RECT -0.190 -0.190 0.190 0.190 ;",
    ).replace(
        "RECT -0.190 -0.140 0.190 0.140 ;",
        "RECT -0.190 -0.190 0.190 0.190 ;",
    ).replace(
        "ENCLOSURE 0.010 0.060 ;",
        "ENCLOSURE 0.060 0.060 ;",
    ).replace(
        "ENCLOSURE 0.060 0.010 ;",
        "ENCLOSURE 0.060 0.060 ;",
    )
    fixed, report = legalize_via_patches(src)

    assert fixed == src
    assert report["changed_patch_records"] == 0
    assert report["remaining_via_rule_violations"] == 0


def test_generated_viarule_enclosures_are_grown_from_cut_extent_and_rules():
    """The generated form is independent evidence: its routing patch is the
    cut bounding box plus twice ENCLOSURE, not a routing-layer RECT.
    """
    from pdk_via_patch_legalize import legalize_via_patches

    src = _illegal_techlef().replace(
        "RECT -0.140 -0.190 0.140 0.190 ;",
        "RECT -0.190 -0.190 0.190 0.190 ;",
    ).replace(
        "RECT -0.190 -0.140 0.190 0.140 ;",
        "RECT -0.190 -0.190 0.190 0.190 ;",
    )
    fixed, report = legalize_via_patches(src)

    assert fixed.count("ENCLOSURE 0.060 0.060 ;") == 2
    assert report["changed_rectangles"] == 0
    assert report["changed_enclosures"] == 2
    assert {row["form"] for row in report["changes"]} == {"VIARULE"}
    assert report["remaining_via_rule_violations"] == 0


def test_phase3_stages_one_derived_techlef_and_all_consumers_share_it(tmp_path):
    """The remediation is useful only when downstream PnR, stream-out and
    sign-off consume the same derived LEF through their shared PdkConfig.
    """
    project = tmp_path / "project"
    out_dir = project / "phase3/stage3/pnr"
    source = tmp_path / "source.tlef"
    source.write_text(_illegal_techlef())
    pdk = runner.PdkConfig(
        name="neutral", liberty="unused.lib", tech_lef=str(source),
        cell_lef="unused.lef", cell_gds=None, site="unit",
        drc_deck=None, metal_prefix="route_",
    )

    result = runner._stage_via_legalized_tech_lef(
        project, pdk, "unused-container", out_dir)

    staged = out_dir / "active_via_legalized.tlef"
    report_path = project / "reports/pdk_via_patch_legalization.json"
    report = json.loads(report_path.read_text())
    assert result["status"] == "APPLIED"
    assert pdk.tech_lef == str(staged)
    assert staged.is_file()
    assert staged.read_text().count(
        "RECT -0.190 -0.190 0.190 0.190 ;") == 2
    assert report["source_tech_lef"] == str(source)
    assert report["derived_tech_lef"] == str(staged)
    assert report["changed_patch_records"] == 4
    assert report["changed_rectangles"] == 2
    assert report["changed_enclosures"] == 2

    # step_pnr has one bounded redispatch path.  Its second call receives the
    # already-mutated shared PdkConfig and must not overwrite the APPLIED
    # provenance with a misleading NOT_NEEDED report about the derived file.
    repeated = runner._stage_via_legalized_tech_lef(
        project, pdk, "unused-container", out_dir)
    repeated_report = json.loads(report_path.read_text())
    assert repeated["status"] == "APPLIED"
    assert repeated_report["status"] == "APPLIED"
    assert repeated_report["source_tech_lef"] == str(source)
