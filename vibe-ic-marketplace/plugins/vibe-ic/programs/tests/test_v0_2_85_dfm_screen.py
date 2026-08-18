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
    # FIXED ASSERTION (was `rep["rc"] == 0`). That line encoded the defect as
    # the expected behaviour: it pinned the ADVISORY tier and the CLEAN tier
    # onto the same exit code, which is exactly why every finding this screen
    # raised was invisible to the flow gate. rc 1 == "screen ran and raised an
    # advisory"; it is wired in the non-blocking `advisory_program_exit_zero`
    # slot, so it still cannot fail Step 35 (asserted in
    # test_step35_dfm_advisory_slot.py).
    assert rep["rc"] == 1
    assert rep["verdict"] == "PASS_WITH_ADVISORIES"
    assert rep["via_redundancy"]["single_cut_fraction"] > 0.9
    assert any(f["category"] == "VIA_REDUNDANCY_LOW" for f in rep["findings"])


def test_balanced_via_mix_passes(tmp_path):
    p = _proj(tmp_path, extra_single=0)    # 1 single vs 1 dual = 50%
    rep = DFM.audit(p)
    assert rep["verdict"] == "PASS"
    # DIRECTION-1 GUARD: a clean screen must keep exit code 0. Separating the
    # tiers must not make a finding-free run look like a finding.
    assert rep["rc"] == 0
    assert any(f["category"] == "VIA_REDUNDANCY_OK" for f in rep["findings"])


def test_density_is_cross_reference_not_duplicate_gate(tmp_path):
    # flow v2.3.1 three-natures split: Step 34 OWNS the density gate; the
    # DFM screen only cross-references its result (advisory).
    import json as _json
    p = _proj(tmp_path, fillers=0, util=10.0)
    g = p / "reports" / "phase2" / "gates"
    g.mkdir(parents=True)
    (g / "metal_fill_density.json").write_text(_json.dumps(
        {"summary": {"pass": False, "errors_count": 1}}))
    rep = DFM.audit(p)
    # FIXED ASSERTION (was `rep["rc"] == 0`, commented "never a duplicate
    # FAIL"). The intent — Step 35 must not duplicate Step 34's density FAIL —
    # is preserved and is now enforced where it belongs: by the flow wiring
    # this program in the NON-BLOCKING advisory slot, not by the program
    # flattening its own verdict onto rc 0. A Step-34 failure IS a DFM
    # advisory, and an advisory that reports rc 0 reports nothing.
    assert rep["rc"] == 1
    assert rep["verdict"] == "PASS_WITH_ADVISORIES"
    assert rep["density_ref"]["step34_pass"] is False
    assert any(f["category"] == "DENSITY_REF"
               and f["severity"] == "WARNING" for f in rep["findings"])


def test_density_ref_absent_is_info(tmp_path):
    p = _proj(tmp_path)
    rep = DFM.audit(p)
    assert any(f["category"] == "DENSITY_REF"
               and f["severity"] == "INFO" for f in rep["findings"])


def test_advanced_node_escalates_foundry_side(tmp_path):
    p = _proj(tmp_path)
    lib = p / "input" / "pdk" / "liberty"
    lib.mkdir(parents=True)
    (lib / "example_sc_7nm_tt.lib").write_text("library(x){}")
    rep = DFM.audit(p)
    assert rep["process_nm"] == 7 and rep["advanced_node"] is True
    assert all(i["status"] == "DESIGNER_COLLAB_REVIEW"
               for i in rep["foundry_side"])
    assert any(f["category"] == "ADVANCED_NODE_DFM" for f in rep["findings"])


def test_mature_node_keeps_foundry_side(tmp_path):
    p = _proj(tmp_path)
    lib = p / "input" / "pdk" / "liberty"
    lib.mkdir(parents=True)
    (lib / "example_sc_180nm_tt.lib").write_text("library(x){}")
    rep = DFM.audit(p)
    assert rep["process_nm"] == 180 and rep["advanced_node"] is False
    assert all(i["status"] == "FOUNDRY_SIDE" for i in rep["foundry_side"])


def test_foundry_side_items_disclosed_not_executed(tmp_path):
    p = _proj(tmp_path)
    rep = DFM.audit(p)
    items = {i["item"].split(" ")[0]: i["status"] for i in rep["foundry_side"]}
    assert items["OPC"] == "FOUNDRY_SIDE"
    assert items["RET"] == "FOUNDRY_SIDE"
    assert items["PSM"] == "FOUNDRY_SIDE"
    assert "28nm" in rep["advanced_node_note"]


def test_canonical_artifact_written(tmp_path):
    # FIXED ASSERTION (was `DFM.main([str(p)]) == 0`). The default fixture has
    # 1 single-cut + 1 dual-cut use = 50%, so it raises NO advisory and the
    # exit code is still 0 — but pinning "main returns 0" on a fixture that
    # happens to be clean also pinned it for fixtures that are not. Assert the
    # artifact independently of the tier, and the tier explicitly.
    p = _proj(tmp_path, extra_single=0)
    assert DFM.main([str(p)]) == 0
    assert (p / "reports" / "phase3" / "dfm_screen.json").is_file()


def test_canonical_artifact_written_on_the_advisory_tier_too(tmp_path):
    """A screen that RAISED a finding must still write the Step-35 artifact.

    Step 35's blocking half is `files_exist reports/phase3/dfm_screen.json`;
    if the advisory exit code suppressed the write, separating the tiers would
    have converted an advisory into a hard MISSING.
    """
    p = _proj(tmp_path, extra_single=18)
    assert DFM.main([str(p)]) == 1
    canon = p / "reports" / "phase3" / "dfm_screen.json"
    assert canon.is_file()
    assert json.loads(canon.read_text())["verdict"] == "PASS_WITH_ADVISORIES"


def test_vacuous_skip_without_inputs(tmp_path):
    # DIRECTION-1 GUARD: the rc-2 "nothing to screen yet" convention is
    # untouched by the tier split — flow_compliance_check maps rc 2 to
    # VACUOUS_PASS and that must keep working.
    rep = DFM.audit(tmp_path)
    assert rep["rc"] == 2
