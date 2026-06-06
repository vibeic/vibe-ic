"""v0.2.85 — Step 35 DFM screen (the user-directed DFM/OPC/RET
decision, honestly scoped for an open-source 130-180nm flow).

Pins:
  * redundant-via ratio counted from the routed DEF (ROWCOL r*c>1 =
    multi-cut); high single-cut fraction → WARNING advisory, never a
    fabricated FAIL (no via-doubling repair pass exists in OpenROAD);
  * CMP density delegation: metal_fill_density_check ERRORs are the
    screen's ERRORs (FAIL);
  * OPC / RET / SRAF / PSM are NAMED FOUNDRY_SIDE disclosure items —
    present at the correct flow position, never designer-executed;
  * canonical artifact reports/phase3/dfm_screen.json always written
    when the screen ran; vacuous SKIP when nothing to screen.

chip-AGNOSTIC: DEF structure fixtures only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dfm_screen_check as DFM  # noqa: E402

_DEF_TMPL = """\
VERSION 5.8 ;
DESIGN top ;
VIAS 2 ;
- via_single + VIARULE vr + CUTSIZE 200 200 + ROWCOL 1 1 ;
- via_dual + VIARULE vr + CUTSIZE 200 200 + ROWCOL 1 2 ;
END VIAS
NETS 2 ;
- n1 ( u1 A ) + ROUTED met1 ( 0 0 ) via_single ( 10 10 ) {extra}
 ;
- n2 ( u2 B ) + ROUTED met2 ( 5 5 ) via_dual ;
END NETS
"""


def _proj(tmp_path, extra_single=8, fillers=100, util=99.0):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    extra = " ".join(f"via_single ( {i} {i} )" for i in range(extra_single))
    body = _DEF_TMPL.format(extra=extra)
    (pnr / "routed.def").write_text(body)
    # filled.def strictly larger than routed.def (fill substance, v0.2.75)
    (pnr / "filled.def").write_text(body + "# FILLS\n" + "x" * 600)
    (pnr / "metal_fill.done").write_text("done")
    rpt = tmp_path / "reports"
    rpt.mkdir()
    (rpt / "density.json").write_text(json.dumps({
        "filler_instances": fillers, "row_utilization_pct": util}))
    return tmp_path


def test_high_single_cut_fraction_is_advisory_warning(tmp_path):
    p = _proj(tmp_path, extra_single=18)   # 19 single vs 1 dual = 95%
    rep = DFM.audit(p)
    assert rep["rc"] == 0
    assert rep["verdict"] == "PASS_WITH_ADVISORIES"
    assert rep["via_redundancy"]["single_cut_fraction"] > 0.9
    assert any(f["category"] == "VIA_REDUNDANCY_LOW" for f in rep["findings"])


def test_balanced_via_mix_passes(tmp_path):
    p = _proj(tmp_path, extra_single=0)    # 1 single vs 1 dual = 50%
    rep = DFM.audit(p)
    assert rep["verdict"] == "PASS"
    assert any(f["category"] == "VIA_REDUNDANCY_OK" for f in rep["findings"])


def test_density_error_fails_the_screen(tmp_path):
    # 0 fillers + rows not full + def not larger → metal-fill substance
    # ERROR (v0.2.75) → DFM screen FAIL
    p = _proj(tmp_path, fillers=0, util=10.0)
    rep = DFM.audit(p)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL"
    assert rep["density"]["errors"] >= 1


def test_foundry_side_items_disclosed_not_executed(tmp_path):
    p = _proj(tmp_path)
    rep = DFM.audit(p)
    items = {i["item"].split(" ")[0]: i["status"] for i in rep["foundry_side"]}
    assert items["OPC"] == "FOUNDRY_SIDE"
    assert items["RET"] == "FOUNDRY_SIDE"
    assert items["PSM"] == "FOUNDRY_SIDE"
    assert "28nm" in rep["advanced_node_note"]


def test_canonical_artifact_written(tmp_path):
    p = _proj(tmp_path)
    assert DFM.main([str(p)]) == 0
    assert (p / "reports" / "phase3" / "dfm_screen.json").is_file()


def test_vacuous_skip_without_inputs(tmp_path):
    rep = DFM.audit(tmp_path)
    assert rep["rc"] == 2
