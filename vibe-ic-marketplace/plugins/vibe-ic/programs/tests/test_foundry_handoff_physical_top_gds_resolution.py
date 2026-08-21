"""foundry_handoff_package_check — resolve the chip GDS by the ACTUAL physical
PnR top, not only L1.ic_name / L9.top_module.

Field observation (caravel_user_project × sky130A): Step 35 FAILed with
FOUNDRY_HANDOFF_CHIP_GDS_MISSING on a project whose chip GDS was correctly
present and non-empty. The backend resolves the synthesizable top structurally
(the RTL instantiation-graph root — `_resolve_asic_top_structural`) and names
every artefact (netlist / DEF / GDS) after it. For standard caravel that top is
`user_project_wrapper`, while L1.ic_name (and L9.top_module) is the project name
`caravel_user_project`. The gate derived the expected GDS basename only from the
L-doc names, so `user_project_wrapper.gds` matched nothing.

Fix: the gate also resolves the ACTUAL physical top from backend artefacts
(the DEF `DESIGN <name> ;` record — the top cell the GDS is streamed from; and
`link_design <name>` in the PnR TCL as a fallback) and accepts a NON-EMPTY,
non-scribe GDS whose basename matches it. This widens recognition by EXACT
identity of the routed database's top — it never passes vacuously:

  * chip GDS genuinely absent           → still FAIL (CHIP_GDS_MISSING);
  * only a 0-byte GDS matches           → still FAIL (empty ≠ deliverable);
  * a real chip GDS named after the
    physical top (ic_name ≠ top)        → PASS.

chip-AGNOSTIC: synthetic generic fixtures, no chip literals.
"""
import json
import subprocess
import sys
from pathlib import Path

CHECKER = (Path(__file__).resolve().parent.parent
           / "foundry_handoff_package_check.py")

_GDS_MAGIC = b"\x00\x06\x00\x02"


def _proj(tmp_path, ic_name="gadget_project", physical_top="gadget_core",
          gds_name=None, gds_bytes=_GDS_MAGIC + b"real-nonempty-gds",
          with_def=True, with_link_design=False):
    """Build a project whose ACTUAL physical top (DEF DESIGN / link_design)
    differs from L1.ic_name. `gds_name` defaults to `<physical_top>.gds`;
    pass gds_name=None with gds_bytes=None to omit the chip GDS entirely."""
    p = tmp_path / ic_name
    # L1.ic_name — the design-intent / project name.
    gen = p / "phase1" / "generated_docs"
    gen.mkdir(parents=True)
    (gen / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": ic_name}))
    # Required foundry-handoff members (non-empty, no TODO, real pdk). All
    # FOUR kit members the pack generator emits are written here so these
    # tests isolate the CHIP-GDS resolution they are about: an incomplete kit
    # resolves SKIP, which is not a chip-GDS verdict either way, so the
    # PASS-direction cases above could not be stated at all without it. (The
    # gate's `_REQUIRED_FILES` used to name only mask_spec + wat_plan, which is
    # a separate defect fixed alongside this; the scribe-line frame is
    # satisfied by the generator's own `.PENDING_FOUNDRY.txt` note when the
    # foundry has not supplied a .gds.)
    #
    # The FAIL-direction cases do NOT depend on this: a proved chip-GDS ERROR
    # outranks kit incompleteness in the gate's verdict ladder, and
    # test_signoff_medlow_backlog_gaps.py pins that on a deliberately
    # incomplete kit.
    hd = p / "phase3" / "stage4" / "foundry_handoff"
    hd.mkdir(parents=True)
    (hd / "mask_spec.json").write_text(json.dumps(
        {"pdk": "examplepdk_sc_hd", "cell_count": 7}))
    (hd / "wat_plan.json").write_text(json.dumps(
        {"pdk": "examplepdk_sc_hd", "structures": ["gadget"]}))
    (hd / "corner_test_vectors.json").write_text(json.dumps(
        {"pdk": "examplepdk_sc_hd", "cell_count": 7}))
    (hd / "scribe_line_layout.PENDING_FOUNDRY.txt").write_text(
        "scribe_line_layout.gds is FOUNDRY-SUPPLIED and is NOT generated "
        f"here.\n# design: {ic_name}\n")
    # Physical top evidence.
    pnr = p / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    if with_def:
        (pnr / "routed.def").write_text(
            'VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\n'
            f"DESIGN {physical_top} ;\n"
            "UNITS DISTANCE MICRONS 1000 ;\nEND DESIGN\n")
    if with_link_design:
        (pnr / "pnr.tcl").write_text(
            "# comment mentioning link_design followed by a read_def\n"
            f"read_verilog {physical_top}_synth.v\n"
            f"link_design {physical_top}\n")
    # Chip GDS (optional).
    if gds_bytes is not None:
        name = gds_name or f"{physical_top}.gds"
        gdsdir = p / "phase3" / "stage4" / "gds"
        gdsdir.mkdir(parents=True)
        (gdsdir / name).write_bytes(gds_bytes)
    return p


def _run(p):
    out = p / "gate.json"
    r = subprocess.run([sys.executable, str(CHECKER), str(p),
                        "--json", str(out)], capture_output=True, text=True)
    return r.returncode, json.loads(out.read_text())


def _rules(rep):
    return [f["rule"] for f in rep["findings"]]


def test_gds_matched_by_physical_def_top_when_icname_differs(tmp_path):
    """The GDS named after the physical DEF top is accepted even though
    L1.ic_name differs — the reported caravel failure."""
    p = _proj(tmp_path)
    rc, rep = _run(p)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS", rep
    assert "gadget_core" in rep["physical_top_candidates"]
    assert rep["chip_gds"].endswith("gadget_core.gds")


def test_link_design_fallback_when_no_def(tmp_path):
    """With no DEF, the physical top is recovered from `link_design` in the
    PnR TCL — and only the real command, not comment prose."""
    p = _proj(tmp_path, with_def=False, with_link_design=True)
    rc, rep = _run(p)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS", rep
    assert rep["physical_top_candidates"] == ["gadget_core"], rep


def test_still_fails_when_chip_gds_genuinely_missing(tmp_path):
    """NEGATIVE CONTROL: physical top resolves, but no chip GDS exists — the
    gate must still FAIL (never widen into a vacuous pass)."""
    p = _proj(tmp_path, gds_bytes=None)
    rc, rep = _run(p)
    assert rc == 1, rep
    assert rep["verdict"] == "FAIL", rep
    assert "FOUNDRY_HANDOFF_CHIP_GDS_MISSING" in _rules(rep), rep


def test_zero_byte_chip_gds_rejected(tmp_path):
    """NEGATIVE CONTROL: a 0-byte GDS matching the physical top is NOT a
    deliverable — the non-empty guard must keep the gate FAILing. Placed
    under stage4/gds/ (outside foundry_handoff/) so this exercises the
    _find_chip_gds guard, not the zero-byte-member scan."""
    p = _proj(tmp_path, gds_bytes=b"")
    rc, rep = _run(p)
    assert rc == 1, rep
    assert rep["verdict"] == "FAIL", rep
    assert "FOUNDRY_HANDOFF_CHIP_GDS_MISSING" in _rules(rep), rep


def test_scribe_only_still_fails(tmp_path):
    """NEGATIVE CONTROL: only a scribe-line/frame GDS present (no real chip
    GDS) must FAIL — the anti-scribe guard is preserved under the widening."""
    p = _proj(tmp_path, gds_name="scribe_line_layout.gds",
              gds_bytes=_GDS_MAGIC + b"frame")
    rc, rep = _run(p)
    assert rc == 1, rep
    assert rep["verdict"] == "FAIL", rep
    assert ("FOUNDRY_HANDOFF_SCRIBE_ONLY" in _rules(rep)
            or "FOUNDRY_HANDOFF_CHIP_GDS_MISSING" in _rules(rep)), rep
