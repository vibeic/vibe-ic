"""v0.3.15 — #509 round-4: the runner picked the PRE-PnR synth netlist
(spare=0, clkbuf=0) as the LVS schematic, but the routed layout (DEF)
carries PnR-inserted spares + CTS clock buffers → netgen mismatch even
though the field's manual run (using the POST-PnR netlist) matched
uniquely. Field lesson #512: the netlist CHOICE was the blind spot.

Fix: _v0_3_15_select_lvs_netlist prefers the post-PnR netlist (pnr dir)
and sanity-checks the pre-vs-post signature — if the layout DEF has
PnR-inserted cells but the chosen netlist has none, switch to a post-PnR
netlist whose cell population matches. chip/PDK-AGNOSTIC.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


def _mk(tmp_path, synth_body, pnr_body, def_body):
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text(synth_body)
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top_pnr.v").write_text(pnr_body)
    (pnr / "chip_top.def").write_text(def_body)
    return tmp_path, pnr / "chip_top.def"


_PRE = "module chip_top();\nsky130_fd_sc_hd__inv_2 _0_ (.A(a));\nendmodule\n"
_POST = ("module chip_top();\nsky130_fd_sc_hd__inv_2 _0_ (.A(a));\n"
         "sky130_fd_sc_hd__dfrtp_1 spare_dff_0 (.CLK(n));\n"
         "sky130_fd_sc_hd__clkbuf_4 clkbuf_0_0 (.A(c));\nendmodule\n")
_DEF_WITH_SPARES = ("COMPONENTS 3 ;\n"
                    "- _0_ sky130_fd_sc_hd__inv_2 ;\n"
                    "- spare_dff_0 sky130_fd_sc_hd__dfrtp_1 ;\n"
                    "- clkbuf_0_0 sky130_fd_sc_hd__clkbuf_4 ;\n"
                    "END COMPONENTS\n")
_DEF_NO_SPARES = ("COMPONENTS 1 ;\n- _0_ sky130_fd_sc_hd__inv_2 ;\n"
                  "END COMPONENTS\n")


def test_picks_post_pnr_when_layout_has_pnr_cells(tmp_path):
    proj, deff = _mk(tmp_path, _PRE, _POST, _DEF_WITH_SPARES)
    nl, reason = R._v0_3_15_select_lvs_netlist(proj, "chip_top", deff)
    assert nl is not None and nl.name == "chip_top_pnr.v", reason
    assert "post-PnR" in reason


def test_signature_counts_spares_and_clkbufs():
    assert R._v0_3_15_count_pnr_inserted(_PRE) == 0
    assert R._v0_3_15_count_pnr_inserted(_POST) >= 2   # spare + clkbuf


def test_pre_pnr_synth_rejected_when_layout_has_spares(tmp_path):
    # even though synth/<top>_synth.v exists and was the OLD pick, it must
    # NOT be chosen when the layout carries PnR cells it lacks.
    proj, deff = _mk(tmp_path, _PRE, _POST, _DEF_WITH_SPARES)
    nl, _ = R._v0_3_15_select_lvs_netlist(proj, "chip_top", deff)
    assert nl.read_text() == _POST   # the post-PnR body, not _PRE


def test_default_priority_when_no_pnr_cells(tmp_path):
    # a flat design with no spares/clkbufs in layout → default priority
    # (pnr-dir first) still returns a valid netlist, no crash.
    proj, deff = _mk(tmp_path, _PRE, _PRE, _DEF_NO_SPARES)
    nl, reason = R._v0_3_15_select_lvs_netlist(proj, "chip_top", deff)
    assert nl is not None


def test_none_when_no_netlist(tmp_path):
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    deff = tmp_path / "phase3" / "stage3" / "pnr" / "chip_top.def"
    deff.write_text(_DEF_NO_SPARES)
    nl, reason = R._v0_3_15_select_lvs_netlist(tmp_path, "chip_top", deff)
    assert nl is None and "no netlist" in reason


# ── #512 doctrine landed in lvs-triage skill ─────────────────────────

def test_512_diff_inputs_doctrine_in_skill():
    skill = (PROGRAMS.parent / "skills" / "lvs-triage" / "SKILL.md").read_text()
    import re
    assert re.search(r"diff.*input", skill, re.I)
    assert re.search(r"field.*recipe.*runner", skill, re.I)
    # the two worked-evidence cases must be cited.
    assert "#508" in skill and "#509" in skill
