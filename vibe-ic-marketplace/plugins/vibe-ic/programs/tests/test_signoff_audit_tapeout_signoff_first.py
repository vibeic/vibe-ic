"""2026-07-27 — Step 36 (tapeout checklist) certified sign-off it never saw.

Two defects, both measured on a COMPLETED spm x ihp-sg13g2 run
(~/campaign_pr427/spm/converge_ihp-sg13g2) against main @ v1.7.36:

D1 — existence-only netlist/timing slots (the #437a bug class, fixed for DRC
     only). `_check_tapeout` credited `_has_files(...)[0]`: an unranked,
     unsorted `rglob` pick. The run's checklist therefore read

         TAPEOUT_NETLIST_EXISTS  phase2/stage2/dft/scan_netlist_prelim.v
         TAPEOUT_TIMING_EXISTS   steps/10_pre_layout_sta_multi_corner/
                                 pre_pnr_timing.rpt

     while the post-route netlist `phase3/stage3/pnr/spm_pnr.v` (100847 B)
     and the post-route STA `phase3/stage3/sta/post_route_timing.rpt` sat in
     the same project. Worse, the post-route netlist matched NONE of the four
     netlist globs (`*netlist*.v`, `*synth*.v`, `*gate*.v`, `*mapped*.v`), so
     it could not have been cited even by a perfect ranker — the DECLARATION
     was wrong, not just the ordering.

D2 — no LVS pillar at all. `lvs_tapeout_signoff_check` (the tapeout-tier LVS
     gate that refuses to credit a netgen POWER_PIN_ONLY waiver as a genuine
     match) has existed since v1.3.94 and is invoked by NOTHING in the
     executed flow. Step 36 signed off a tape-out with zero
     layout-vs-schematic evidence: threshold was 4-of-4 over
     {gds, netlist, timing, drc}.

FIX: rank netlist/timing candidates sign-off-first, extend the netlist glob so
the canonical post-route netlist is matchable, REFUSE to credit either slot
when every candidate declares itself a pre-sign-off intermediate, and add a
fifth LVS pillar delegating substance to the existing tapeout-tier checker
(threshold 5-of-5).

Nothing is loosened: every slot that was required is still required, and two
new ways to FAIL were added. On the real completed run the verdict is
unchanged (5/5 PASS) but the citations are now the post-route netlist, the
post-route STA and a genuine netgen match.

chip-AGNOSTIC: synthetic project trees + generic netgen transcripts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import signoff_audit as sa  # noqa: E402
import _gdsii  # noqa: E402
import _si_signoff_fixture  # noqa: E402


# --- netgen transcripts (shared shape with test_lvs_tapeout_signoff.py) ----
_LVS_MATCH = """\
Subcircuit summary:
Circuit 1: top                          |Circuit 2: top
Number of devices: 812                  |Number of devices: 812
Netlists match uniquely.
Final result: Circuits match uniquely.
"""

_LVS_POWER_PIN_ONLY = """\
Top level cell failed pin matching.
Cell pin lists for top and top do not match.
  VPWR|(no matching pin)
  VGND|(no matching pin)
  VPB |(no matching pin)
  VNB |(no matching pin)
Final result: Netlists do not match.
"""

_LVS_SIGNAL_NET = """\
Top level cell failed pin matching.
Cell pin lists for top and top do not match.
  (no pin, node is /_54440_/Y)
  (no pin, node is /_54441_/Y)
  data_out[7]|(no matching pin)
Final result: Netlists do not match.
"""


# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------
def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _lvs(proj: Path, blob: str = _LVS_MATCH) -> Path:
    return _write(proj / "reports" / "phase3" / "lvs.rpt", blob)


def _four_slots(proj: Path) -> Path:
    """gds + a sign-off-grade netlist + a sign-off-grade STA + clean DRC.
    Deliberately NO LVS report — the D2 fixture."""
    _gdsii.write_declared_streamout(proj, "top.gds")
    _write(proj / "phase3" / "stage3" / "pnr" / "top_pnr.v",
           "module top(); endmodule\n")
    _write(proj / "phase3" / "stage3" / "sta" / "post_route_timing.rpt",
           "slack (MET) 0.10\n")
    _write(proj / "drc_signoff.rpt", "Total violations: 0\n")
    # 2026-07-28: tape-out mode gained an SI (crosstalk-delay) blocking
    # condition. This fixture is about slot ranking, so it carries a PROVED
    # SI verdict — without one every case here would collapse onto the
    # SI refusal and stop discriminating what it exists to pin.
    _si_signoff_fixture.write_proved_si_report(proj)
    return proj


def _finding(result, rule):
    for f in result.findings:
        if f.rule == rule:
            return f
    return None


def _rel(result, rule, proj: Path) -> str:
    f = _finding(result, rule)
    assert f is not None, f"{rule} not among {[x.rule for x in result.findings]}"
    return Path(f.file).relative_to(proj).as_posix()


# ===========================================================================
# D1 — netlist slot: the post-route netlist must be matchable AND preferred
# ===========================================================================
def test_postroute_netlist_is_matchable_and_outranks_synth_output(tmp_path):
    """The measured defect: `phase3/stage3/pnr/<top>_pnr.v` matched none of
    the netlist globs, so a root-level gate-level netlist was cited as THE
    tape-out netlist. The root-level file is scanned before subdirectories,
    so the pre-fix pick is deterministic."""
    _four_slots(tmp_path)
    _lvs(tmp_path)
    _write(tmp_path / "top_gate.v", "module top(); endmodule\n")

    r = sa._check_tapeout(tmp_path)
    assert _rel(r, "TAPEOUT_NETLIST_EXISTS", tmp_path) == \
        "phase3/stage3/pnr/top_pnr.v"
    assert r.summary["evidence"]["netlist"] is True


def test_prelim_dft_netlist_never_outranks_the_postroute_netlist(tmp_path):
    """The exact shape of the real run: a DFT `*_prelim.v` next to a synth
    netlist next to the post-route netlist."""
    _four_slots(tmp_path)
    _lvs(tmp_path)
    _write(tmp_path / "phase2" / "stage2" / "dft" / "scan_netlist_prelim.v",
           "module top(); endmodule\n")
    _write(tmp_path / "phase2" / "stage2" / "synth" / "netlist.v",
           "module top(); endmodule\n")

    r = sa._check_tapeout(tmp_path)
    assert _rel(r, "TAPEOUT_NETLIST_EXISTS", tmp_path) == \
        "phase3/stage3/pnr/top_pnr.v"


def test_only_prelim_netlist_does_not_certify_the_netlist_slot(tmp_path):
    """A preliminary netlist is not the netlist a tape-out is signed off on.
    The gate DISCLOSES what it found and still refuses to credit the slot."""
    _gdsii.write_declared_streamout(tmp_path, "top.gds")
    _write(tmp_path / "phase2" / "stage2" / "dft" / "scan_netlist_prelim.v",
           "module top(); endmodule\n")
    _write(tmp_path / "phase3" / "stage3" / "sta" / "post_route_timing.rpt",
           "slack (MET)\n")
    _write(tmp_path / "drc_signoff.rpt", "Total violations: 0\n")
    _lvs(tmp_path)

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["netlist"] is False
    assert r.passed is False
    f = _finding(r, "TAPEOUT_NETLIST_PRESIGNOFF_ONLY")
    assert f is not None and f.severity == "ERROR"
    # the disclosure names the artefact it refused
    assert "scan_netlist_prelim.v" in f.message


# ===========================================================================
# D1 — timing slot: post-route STA preferred, pre-layout STA never certifies
# ===========================================================================
def test_postroute_sta_outranks_a_generic_root_level_timing_report(tmp_path):
    _four_slots(tmp_path)
    _lvs(tmp_path)
    _write(tmp_path / "partial_timing.rpt", "some timing text\n")

    r = sa._check_tapeout(tmp_path)
    assert _rel(r, "TAPEOUT_TIMING_EXISTS", tmp_path) == \
        "phase3/stage3/sta/post_route_timing.rpt"


def test_steps_mirror_symlink_loses_the_tie_to_the_real_file(tmp_path):
    """`steps/` mirrors phase3 artefacts through symlinks; the evidence must
    cite the canonical file, not a duplicate of it."""
    _four_slots(tmp_path)
    _lvs(tmp_path)
    mirror = tmp_path / "steps" / "23_post_route_sta" / "post_route_timing.rpt"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.symlink_to(tmp_path / "phase3" / "stage3" / "sta"
                      / "post_route_timing.rpt")

    r = sa._check_tapeout(tmp_path)
    assert _rel(r, "TAPEOUT_TIMING_EXISTS", tmp_path) == \
        "phase3/stage3/sta/post_route_timing.rpt"


def test_only_pre_layout_sta_does_not_certify_the_timing_slot(tmp_path):
    """The measured citation was `pre_pnr_timing.rpt`. When that is ALL a
    project has, the timing slot must not be credited at all."""
    _gdsii.write_declared_streamout(tmp_path, "top.gds")
    _write(tmp_path / "phase3" / "stage3" / "pnr" / "top_pnr.v",
           "module top(); endmodule\n")
    _write(tmp_path / "phase3" / "stage3" / "sta" / "pre_pnr_timing.rpt",
           "slack (MET)\n")
    _write(tmp_path / "drc_signoff.rpt", "Total violations: 0\n")
    _lvs(tmp_path)

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["timing"] is False
    assert r.passed is False
    f = _finding(r, "TAPEOUT_TIMING_PRESIGNOFF_ONLY")
    assert f is not None and f.severity == "ERROR"
    assert "pre_pnr_timing.rpt" in f.message


def test_project_checked_out_under_a_draft_directory_is_not_penalised(tmp_path):
    """The pre-sign-off markers are matched on the IN-PROJECT path only, so a
    project living under e.g. /home/x/draft/ is unaffected."""
    proj = tmp_path / "draft" / "proj"
    _four_slots(proj)
    _lvs(proj)
    r = sa._check_tapeout(proj)
    assert r.summary["evidence"]["netlist"] is True
    assert r.summary["evidence"]["timing"] is True


# ===========================================================================
# D2 — the LVS pillar
# ===========================================================================
def test_tapeout_without_any_lvs_evidence_cannot_pass(tmp_path):
    """THE defect: gds + netlist + timing + clean DRC and no LVS report of
    any kind used to be a 4-of-4 tape-out sign-off."""
    _four_slots(tmp_path)

    r = sa._check_tapeout(tmp_path)
    assert r.summary["threshold"] == 5
    assert r.summary["evidence"]["lvs"] is False
    assert r.summary["evidence_count"] == 4
    assert r.passed is False
    assert _finding(r, "TAPEOUT_LVS_EXISTS").severity == "ERROR"
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 1


def test_lvs_slot_never_cites_the_drc_report_as_lvs_evidence(tmp_path):
    """The tapeout-tier checker's own locator falls back to a bare `*.rpt`
    glob; signoff_audit must not inherit that, or a DRC report becomes 'LVS
    evidence'."""
    _four_slots(tmp_path)  # carries drc_signoff.rpt, no LVS report
    r = sa._check_tapeout(tmp_path)
    assert r.summary["lvs_report"] == ""
    assert _finding(r, "TAPEOUT_LVS_EXISTS").file == ""


def test_genuine_lvs_match_credits_the_slot_and_reaches_5_of_5(tmp_path):
    _four_slots(tmp_path)
    _lvs(tmp_path, _LVS_MATCH)

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["lvs"] is True
    assert r.summary["evidence_count"] == 5
    assert r.summary["lvs_verdict"] == "GENUINE_MATCH"
    assert r.passed is True
    assert r.summary["verdict_tier"] == "PASS"
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 0


def test_power_pin_only_lvs_is_a_waiver_and_never_a_bare_pass(tmp_path):
    """POWER_PIN_ONLY is a reasoned TRIAGE waiver, not a tape-out match: it
    may reach the threshold but must carry the #651 waiver rc + sentinel."""
    _four_slots(tmp_path)
    _lvs(tmp_path, _LVS_POWER_PIN_ONLY)

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["lvs"] == "power_pin_only_waived"
    assert r.summary["lvs_power_pin_only_waived"] is True
    assert r.passed is True
    assert r.summary["verdict_tier"] == "PASS_WITH_WAIVERS"
    assert _finding(r, "TAPEOUT_LVS_POWER_PIN_WAIVED").severity == "WARNING"
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == sa.WAIVER_EXIT_CODE


def test_signal_net_lvs_mismatch_fails_the_tapeout(tmp_path):
    _four_slots(tmp_path)
    _lvs(tmp_path, _LVS_SIGNAL_NET)

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["lvs"] is False
    assert r.passed is False
    assert _finding(r, "TAPEOUT_LVS_MISMATCH").severity == "ERROR"
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 1


def test_incomplete_lvs_compare_is_missing_evidence_not_a_pass(tmp_path):
    _four_slots(tmp_path)
    _lvs(tmp_path, "Reading netlist file 'top.spice'\nsubcircuit summary\n")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["lvs"] is False
    assert r.passed is False
    assert _finding(r, "TAPEOUT_LVS_INCOMPLETE") is not None


def test_lvs_env_unavailable_backfills_as_a_disclosed_waiver(tmp_path):
    """`_read_phase3_env_unavailable_steps` has always returned 'lvs'; before
    the pillar existed there was no slot for it to credit. A container with
    no LVS tool is a DISCLOSED gap → PASS_WITH_WAIVERS, never a bare PASS."""
    _four_slots(tmp_path)
    _write(tmp_path / "reports" / "phase3_one_shot.json",
           json.dumps({"steps": [{"name": "lvs", "status": "ENV_UNAVAILABLE"}]}))

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["lvs"] == "env_unavailable"
    assert r.passed is True
    assert r.summary["verdict_tier"] == "PASS_WITH_WAIVERS"
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == sa.WAIVER_EXIT_CODE


# ===========================================================================
# DIRECTION-1 GUARDS — behaviour that must NOT change (pass on both trees)
# ===========================================================================
def test_guard_empty_project_still_fails_rc1(tmp_path):
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == 1


def test_guard_pdk_inputs_are_still_excluded_from_every_slot(tmp_path):
    """v0.52: `input/pdk/**` is an INPUT, never tape-out evidence — including
    for the newly-added `*pnr*.v` glob and the new LVS pillar."""
    _write(tmp_path / "input" / "pdk" / "gds" / "stdcell.gds", "pdk")
    _write(tmp_path / "input" / "pdk" / "verilog" / "stdcell_pnr.v", "module x;")
    _write(tmp_path / "input" / "pdk" / "verilog" / "stdcell_synth.v", "module y;")
    _write(tmp_path / "input" / "pdk" / "lvs" / "stdcell_lvs.rpt", _LVS_MATCH)

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence_count"] == 0
    # `.get` so this guard is tree-agnostic: it must hold identically before
    # and after the LVS pillar existed.
    assert not r.summary["evidence"].get("gds")
    assert not r.summary["evidence"].get("netlist")
    assert not r.summary["evidence"].get("lvs")


def test_guard_drc_signoff_report_still_outranks_the_router_report(tmp_path):
    """#437a: the DRC slot's own signoff-first ranking and violation-count
    substance rule are untouched."""
    _four_slots(tmp_path)
    (tmp_path / "drc_signoff.rpt").unlink()
    _lvs(tmp_path)
    _write(tmp_path / "drc_router.rpt", "detailed_route\nTotal violations: 0\n")
    _write(tmp_path / "drc_signoff.rpt",
           "<report-database>\n" + "<item>x</item>\n" * 7 + "</report-database>\n")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["drc"] is False
    f = _finding(r, "TAPEOUT_DRC_VIOLATIONS")
    assert f is not None and "7" in f.message and "signoff" in f.file


def test_guard_waiver_rc_and_sentinel_constants_unchanged():
    assert sa.WAIVER_EXIT_CODE == 3
    assert sa.WAIVER_EXIT_CODE not in (0, 1, 2)
    assert sa.WAIVER_STDOUT_SENTINEL == "PASS_WITH_WAIVERS:"


def test_guard_library_internal_drc_waiver_still_demotes_to_with_waivers(tmp_path):
    """#515: a nonzero-but-100%-library-internal signoff DRC still credits the
    DRC slot AS A WAIVER and still yields the distinct rc 3."""
    _four_slots(tmp_path)
    (tmp_path / "drc_signoff.rpt").unlink()
    # a synthesis-named netlist too, so this guard is tree-agnostic (the
    # pre-fix globs could not match phase3/stage3/pnr/<top>_pnr.v).
    _write(tmp_path / "top_synth.v", "module top(); endmodule\n")
    _lvs(tmp_path)
    items = "\n".join(
        "  <item>\n   <category>'li.3'</category>\n   <cell>'top'</cell>\n"
        "   <values><value>box: (0,0;1,1)</value></values>\n  </item>"
        for _ in range(11))
    _write(tmp_path / "drc_signoff.rpt",
           "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<report-database>\n"
           " <categories>\n  <category><name>li.3</name></category>\n"
           " </categories>\n <items>\n" + items + "\n </items>\n"
           "</report-database>\n")

    r = sa._check_tapeout(tmp_path)
    assert r.summary["evidence"]["drc"] == "library_internal_waived"
    assert r.summary["drc_library_internal_waived"] is True
    assert r.passed is True
    assert r.summary["verdict_tier"] == "PASS_WITH_WAIVERS"
    assert sa.main([str(tmp_path), "--mode", "tapeout"]) == sa.WAIVER_EXIT_CODE


def test_guard_flow_mode_threshold_is_still_4_of_4(tmp_path):
    """The LVS pillar is tapeout-mode only; `--mode flow` is unchanged."""
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (tmp_path / "phase3" / "stage4" / "gds").mkdir(parents=True)
    _write(tmp_path / "sta_timing.rpt", "sta report")

    r = sa._check_flow(tmp_path)
    assert r.summary["threshold"] == 4
    assert r.summary["stage_count"] == 4
    assert r.passed is True


# ===========================================================================
# #797 — THE RANKER MATERIALISED THE LARGEST ARTEFACT A RUN PRODUCES.
#
# `_drc_rank` was `p.read_text(errors="replace")[:2000]`: decode the WHOLE
# file, then throw all but 2000 characters away. It is the `key=` of a
# `sorted()` over every `*drc*.rpt|log` an rglob of the project finds, and a
# router report is the biggest thing a run writes — measured 2026-08-04 at
# 2.48 GB / 94.9M lines on one cell (the largest report tracked in THIS repo
# is 11.7 MB, so the scale is not reproducible here; the mechanism is).
#
# Why that is a correctness bug and not a performance note: a checker that
# cannot finish gets killed, and downstream a killed checker is
# indistinguishable from one that ran and found nothing. The step's timeout
# arrives as the step's verdict.
#
# The head that decides is unchanged, so these tests pin BOTH halves: the read
# is bounded, and the ranking is byte-identical to what the unbounded read
# produced.
# ===========================================================================
def test_drc_rank_does_not_materialise_the_report_it_ranks(tmp_path):
    """THE property, measured rather than asserted about the source: rank a
    32 MiB report and require peak allocation to stay near the bound.

    Pre-fix this allocates the whole decoded file and fails."""
    import tracemalloc

    big = tmp_path / "drc_router.log"
    big.parent.mkdir(parents=True, exist_ok=True)
    with big.open("w") as fh:
        fh.write("<report-database>\n")
        chunk = "x" * 65536 + "\n"
        for _ in range(512):            # ~32 MiB
            fh.write(chunk)
    assert big.stat().st_size > 32 * 1024 * 1024

    tracemalloc.start()
    try:
        rank = sa._drc_rank(big)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert rank == 1, "the KLayout sign-off marker in the head must still rank 1"
    assert peak < 4 * 1024 * 1024, (
        f"ranking a {big.stat().st_size // (1024*1024)} MiB report peaked at "
        f"{peak // 1024} KiB — the read is not bounded")


def test_drc_rank_verdicts_are_unchanged(tmp_path):
    """Every rank the unbounded read produced, written out as literals so that
    deleting one deletes a visible line rather than silently shrinking a loop."""
    named = _write(tmp_path / "drc_signoff.rpt", "anything at all\n")
    klayout = _write(tmp_path / "a_drc.rpt", "<report-database>\n<items/>\n")
    router = _write(tmp_path / "b_drc.rpt", "detailed_route\nviolations 0\n")
    openroad = _write(tmp_path / "c_drc.rpt", "OpenROAD v2\nrouting\n")
    plain = _write(tmp_path / "d_drc.rpt", "some other tool\n")
    absent = tmp_path / "nope" / "e_drc.rpt"

    assert sa._drc_rank(named) == 0
    assert sa._drc_rank(klayout) == 1
    assert sa._drc_rank(router) == 2
    assert sa._drc_rank(openroad) == 2
    assert sa._drc_rank(plain) == 2
    assert sa._drc_rank(absent) == 3


def test_drc_rank_head_bound_is_the_same_2000_characters(tmp_path):
    """The bound is not widened by moving it into the read. A marker BEYOND
    the head was invisible to `[:2000]` and must stay invisible — otherwise
    this would be a silent behaviour change dressed as a resource fix."""
    inside = _write(tmp_path / "in_drc.rpt",
                    "z" * 1900 + "\n<report-database>\n")
    beyond = _write(tmp_path / "out_drc.rpt",
                    "z" * 5000 + "\n<report-database>\n")
    assert sa._drc_rank(inside) == 1
    assert sa._drc_rank(beyond) == 2
    assert sa._DRC_RANK_HEAD_CHARS == 2000
