"""ORGANIC #732 — auto-emit SOURCE_MANIFEST.json on the PRE-STAGED-vendor-RTL
catalog-glue path.

DEFECT (round-11 v1.0.77 6-IC clean-room; OpenTitan-AES reused-IP SoC):
  Reused-IP / catalog-glue designs reach phase2 via TWO entry paths:
    (1) catalog-pull — ip_catalog_pull.pull_all_catalog_matches copies the IP
        and (since #711) auto-emits phase2/stage1/rtl/SOURCE_MANIFEST.json.
    (2) pre-staged vendor RTL — input/vendor_rtl/ is already populated, so
        design_one_shot_runner.step_rtl_gen WAIVES immediately with
        fallback_skill=catalog-glue-author and RETURNS — it never queries the
        catalog, never calls ip_catalog_pull, and (pre-#732) never emitted the
        manifest.
  Because l9_rtl_pin_consistency_check.load_source_manifest() returns None when
  the file is absent, ALL reused-IP relaxations (#659 struct-bus flatten /
  tie-off, #711 rename, #712 exposed-output) were DEAD CODE on path (2) and the
  gating pin check hard-FAILed with 'L9 <-> RTL top pin/direction mismatch'.
  The keystone artifact only ever got written by AI hand-authoring.

FIX (chip-AGNOSTIC):
  staged_rtl_reused_ip_manifest_emit.emit_prestaged_reused_ip_manifest emits a
  minimal keystone {reused_ip:true, ip_list:[…], rtl_strategy:..., generated_by:
  'phase2_runner_prestaged'} when input/vendor_rtl/ is populated and no manifest
  yet exists; step_rtl_gen calls it on the pre-staged WAIVE. MERGE-preserving:
  never clobbers a hand-authored tie_offs / flattened_buses / renamed_interfaces
  block (mirrors ip_catalog_pull.py:496-509).

§4.05 NO-LEAK: emits ONLY when input/vendor_rtl/ holds ≥1 .v/.sv file (the exact
  reused-IP WAIVE condition). A non-reused design (no vendor_rtl) gets NO manifest
  → never receives a spurious reused_ip:true.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import staged_rtl_reused_ip_manifest_emit as SRM  # noqa: E402
import l9_rtl_pin_consistency_check as G  # noqa: E402
import design_one_shot_runner as R  # noqa: E402


_VENDOR_AES_SV = """\
module aes_core (
  input        clk_i,
  input        rst_ni,
  output       alert_n_o
);
endmodule
"""

_VENDOR_TLUL_V = """\
module tlul_adapter_reg (input clk_i, input rst_ni);
endmodule
"""


def _make_prestaged_project(root: Path) -> Path:
    """A reused-IP project with input/vendor_rtl/ populated (the pre-staged
    catalog-glue path) — no manifest yet."""
    vd = root / "input" / "vendor_rtl"
    (vd / "aes").mkdir(parents=True, exist_ok=True)
    (vd / "tlul").mkdir(parents=True, exist_ok=True)
    (vd / "aes" / "aes_core.sv").write_text(_VENDOR_AES_SV)
    (vd / "tlul" / "tlul_adapter_reg.v").write_text(_VENDOR_TLUL_V)
    return root


# ── (a) pre-staged WAIVE path emits the keystone manifest ───────────────────
def test_a_helper_emits_keystone_manifest(tmp_path):
    """END-STATE: emit_prestaged_reused_ip_manifest writes a keystone manifest
    with reused_ip:true + generated_by:phase2_runner_prestaged, ip_list derived
    from the staged module names."""
    proj = _make_prestaged_project(tmp_path)
    out = SRM.emit_prestaged_reused_ip_manifest(proj)
    assert out is not None
    assert out == proj / "phase2" / "stage1" / "rtl" / "SOURCE_MANIFEST.json"
    mf = json.loads(out.read_text())
    assert mf["reused_ip"] is True
    assert mf["generated_by"] == "phase2_runner_prestaged"
    assert mf["rtl_strategy"] == "catalog_lookup_plus_ai_glue"
    # ip_list derived from `module <name>` decls in the staged files
    assert set(mf["ip_list"]) == {"aes_core", "tlul_adapter_reg"}


def test_a_step_rtl_gen_emits_on_prestaged_waive(tmp_path):
    """END-STATE: driving the REAL step_rtl_gen on a pre-staged reused-IP
    project (rtl_gen=null class) WAIVES to catalog-glue-author AND emits the
    keystone manifest as a side effect."""
    proj = _make_prestaged_project(tmp_path)
    # digital_cmd_driven: rtl_gen=null, fallback=spec-to-rtl, NOT pure-analog —
    # the input/vendor_rtl/ branch fires before the catalog/analog branches.
    res = R.step_rtl_gen(proj, "digital_cmd_driven")
    assert res.status == "WAIVED"
    assert res.extras.get("fallback_skill") == "catalog-glue-author"
    assert "source_manifest_emitted" in res.extras
    mf_path = proj / "phase2" / "stage1" / "rtl" / "SOURCE_MANIFEST.json"
    assert mf_path.is_file()
    mf = json.loads(mf_path.read_text())
    assert mf["reused_ip"] is True
    assert mf["generated_by"] == "phase2_runner_prestaged"


# ── (b) MERGE: a pre-existing hand-authored manifest survives ───────────────
def test_b_merge_preserves_hand_authored_blocks(tmp_path):
    """§4.05 + MERGE: a hand-authored manifest carrying tie_offs /
    flattened_buses / renamed_interfaces is NEVER clobbered — the emit only
    (re)asserts the keystone keys and setdefault()s generated_by."""
    proj = _make_prestaged_project(tmp_path)
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps({
        "reused_ip": True,
        "generated_by": "hand-author",
        "tie_offs": ["clk_edn_i", "edn_i", "edn_o"],
        "flattened_buses": [{"l9": "tl", "rtl": ["tl_a_*", "tl_d_*"]}],
        "renamed_interfaces": [{"l9": ["o_sram_addr"],
                                "rtl": ["o_sram_waddr"]}],
        "ip_list": ["my_curated_list"],
    }))
    out = SRM.emit_prestaged_reused_ip_manifest(proj)
    assert out is not None
    mf = json.loads(out.read_text())
    # hand-authored relaxation blocks survive UNTOUCHED
    assert mf["tie_offs"] == ["clk_edn_i", "edn_i", "edn_o"]
    assert mf["flattened_buses"] == [{"l9": "tl", "rtl": ["tl_a_*", "tl_d_*"]}]
    assert mf["renamed_interfaces"] == [{"l9": ["o_sram_addr"],
                                         "rtl": ["o_sram_waddr"]}]
    # hand-authored generated_by NOT overwritten (setdefault)
    assert mf["generated_by"] == "hand-author"
    # a richer hand-authored ip_list NOT clobbered by the thinner derived one
    assert mf["ip_list"] == ["my_curated_list"]
    # keystone still asserted
    assert mf["reused_ip"] is True


# ── (c) §4.05 NO-LEAK: non-reused / no-vendor_rtl project gets NO manifest ──
def test_c_noleak_no_vendor_rtl_no_manifest(tmp_path):
    """§4.05: a project with NO input/vendor_rtl/ at all gets no manifest — a
    non-reused design never receives a spurious reused_ip:true."""
    out = SRM.emit_prestaged_reused_ip_manifest(tmp_path)
    assert out is None
    assert not (tmp_path / "phase2" / "stage1" / "rtl"
                / "SOURCE_MANIFEST.json").exists()


def test_c_noleak_empty_vendor_rtl_no_manifest(tmp_path):
    """§4.05: an EMPTY input/vendor_rtl/ (dir present, no .v/.sv) is NOT the
    reused-IP WAIVE path — still no manifest."""
    (tmp_path / "input" / "vendor_rtl").mkdir(parents=True, exist_ok=True)
    out = SRM.emit_prestaged_reused_ip_manifest(tmp_path)
    assert out is None
    assert not (tmp_path / "phase2" / "stage1" / "rtl"
                / "SOURCE_MANIFEST.json").exists()


def test_c_noleak_step_rtl_gen_non_reused_no_manifest(tmp_path):
    """§4.05 through the runner: step_rtl_gen on a non-reused project (no
    vendor_rtl) does NOT emit a manifest and does NOT report
    source_manifest_emitted."""
    res = R.step_rtl_gen(tmp_path, "digital_cmd_driven")
    # No vendor RTL → falls through past the pre-staged branch (here it WAIVES
    # to spec-to-rtl after the catalog query). Either way: no manifest.
    assert "source_manifest_emitted" not in res.extras
    assert not (tmp_path / "phase2" / "stage1" / "rtl"
                / "SOURCE_MANIFEST.json").exists()


# ── (d) the emitted manifest makes load_source_manifest() return non-None ──
def test_d_emitted_manifest_makes_relaxations_live(tmp_path):
    """END-STATE: after the emit, load_source_manifest() returns a non-None
    dict with reused_ip:true — so the #659/#711/#712 relaxations are LIVE
    (they all short-circuit to the strict path when it returns None)."""
    proj = _make_prestaged_project(tmp_path)
    # BEFORE: no manifest → relaxations dead
    assert G.load_source_manifest(proj) is None
    SRM.emit_prestaged_reused_ip_manifest(proj)
    # AFTER: manifest live
    data = G.load_source_manifest(proj)
    assert data is not None
    assert data.get("reused_ip") is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── ORGANIC (GAP-E2E-8) — EMPTY reconciliation scaffold in the auto-manifest ──
# The minimal auto-manifest carried no renamed_interfaces / flattened_buses, so a
# REUSED-IP whose genuine interface differs from the L9 doc abstraction (SERV's
# split SRAM ports) hit an l9_rtl_pin_consistency completion-audit FAIL with
# nothing to reconcile against. The auto-manifest now emits the two keys as EMPTY
# lists + a note. §4.05 NO-LEAK: an EMPTY scaffold reconciles ZERO ports, so the
# gate verdict is byte-for-byte UNCHANGED (a real mismatch still FAILs).
def test_gap_e2e8_emits_empty_reconciliation_scaffold(tmp_path):
    proj = _make_prestaged_project(tmp_path)
    out = SRM.emit_prestaged_reused_ip_manifest(proj)
    mf = json.loads(out.read_text())
    assert mf.get("renamed_interfaces") == []
    assert mf.get("flattened_buses") == []
    assert "_reconciliation_scaffold_note" in mf


def test_gap_e2e8_empty_scaffold_reconciles_nothing(tmp_path):
    # §4.05 NO-LEAK: the empty scaffold must reconcile ZERO port groups — the
    # gate's renamed-group extraction returns [] so the verdict is unchanged.
    proj = _make_prestaged_project(tmp_path)
    out = SRM.emit_prestaged_reused_ip_manifest(proj)
    mf = json.loads(out.read_text())
    assert G._manifest_renamed_groups(mf) == []


def test_gap_e2e8_preserves_hand_authored_pairing(tmp_path):
    # MERGE-preserving: a populated renamed_interfaces block is NOT clobbered by
    # the scaffold, and it reconciles the real pairing.
    proj = _make_prestaged_project(tmp_path)
    out = SRM.emit_prestaged_reused_ip_manifest(proj)
    mf = json.loads(out.read_text())
    mf["renamed_interfaces"] = [
        {"l9": ["sram_data"], "rtl": ["sram_wdata", "sram_rdata"]}]
    out.write_text(json.dumps(mf))
    out2 = SRM.emit_prestaged_reused_ip_manifest(proj)   # re-emit
    mf2 = json.loads(out2.read_text())
    assert mf2["renamed_interfaces"] == [
        {"l9": ["sram_data"], "rtl": ["sram_wdata", "sram_rdata"]}]
    groups = G._manifest_renamed_groups(mf2)
    assert groups == [({"sram_data"}, {"sram_wdata", "sram_rdata"})]
