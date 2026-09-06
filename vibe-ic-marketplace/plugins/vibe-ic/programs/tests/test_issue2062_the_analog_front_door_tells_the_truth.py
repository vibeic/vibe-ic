"""vibe-ic#2062 — the analog front door tells the truth.

Four defects, each measured on a real run of a real cell (u_hawaii_adc,
ihp-sg13g2, image 0.3.46) and each pinned here in BOTH directions: the fixed
behaviour, and a deliberate break that must turn it red again.

  R1   the rung-2 (container-installed) PDK result set no `drc_deck` /
       `lvs_deck`, and `analog_one_shot_runner._try_native_a6_pv` returns None
       unless one of them is set — so A6's native per-block PV was abandoned
       BEFORE it named a tool, and the step FAILed `A6_PV_*_NO_EVIDENCE` for
       every project whose PDK comes from the image. Measured: as shipped
       `run_block_pv` returned ran=False in 0.00 s; with the image's own two
       decks in the result it ran 17 s and returned DRC 0 / LVS match.

  R12  the PVT corner call site passed no `deck_text`, so `sim_deadline_s("")`
       returned the 120 s FLOOR for every corner while the sized base run one
       function away passed the deck and got 7200. Eight of nine corners of a
       51.2 us transient were cut and published as arithmetic. Fixed twice
       over: the deck reaches the call, AND no corner is ended by a clock.

  R12c a corner that was ATTEMPTED and produced nothing is reported
       NOT_COMPLETED with the simulator's own words, and carries NO number —
       an arithmetic spread in the same column as a measurement is what made
       the grid unreadable.

  R6   `pdk_revision_resolve` derives the PDK tree from absolute library paths
       in the run's own `*.log` files. The corner DECK names three; ngspice's
       stdout names none; so a run that really did read the PDK recorded
       "PDK revision NOT RECORDED" and `benchmark_evidence_publish` would
       refuse to stage it. The log now carries what the deck loaded.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import analog_pdk_availability as APA          # noqa: E402
import analog_real_corner_sweep as ARS         # noqa: E402
import analog_a4_corner_sweep_check as A4      # noqa: E402


# ── R1: the rung-2 result carries the installed PDK's own sign-off decks ───
_TREE = {
    "/foss/pdks": ["sky130A", "ihp-sg13g2"],
    "/foss/pdks/ihp-sg13g2/libs.tech": ["ngspice", "klayout", "magic",
                                        "netgen"],
    "/foss/pdks/ihp-sg13g2/libs.tech/ngspice": ["models"],
    "/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models": ["cornerMOSlv.lib"],
    "/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/drc": ["ihp-sg13g2.drc"],
    "/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/lvs": ["sg13g2.lvs"],
}


def _lister(tree):
    def L(path):
        return sorted(tree.get(path.rstrip("/"), []))
    return L


def test_R1_a_container_installed_pdk_offers_its_own_signoff_decks():
    r = APA.resolve_pdk("ihp-sg13g2", lister=_lister(_TREE))
    assert r["rung"] == 2 and r["available"] is True
    assert r["drc_deck"] == (
        "/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/drc/ihp-sg13g2.drc")
    assert r["lvs_deck"] == (
        "/foss/pdks/ihp-sg13g2/libs.tech/klayout/tech/lvs/sg13g2.lvs")


def test_R1_the_decks_are_the_ones_A6_can_actually_RUN():
    """A resolver that hands A6 a deck it refuses as `unknown` is the same
    silent hole one step later, so the candidate extensions come from the
    consumer's own engine map."""
    import analog_a6_native_pv as PV
    r = APA.resolve_pdk("ihp-sg13g2", lister=_lister(_TREE))
    assert PV.deck_kind(r["drc_deck"]) != "unknown"
    assert PV.lvs_deck_kind(r["lvs_deck"]) != "unknown"


def test_R1_MUTATION_without_the_decks_the_native_A6_path_is_abandoned():
    """BOTH DIRECTIONS. `_try_native_a6_pv` returns None unless one deck is
    set — which is the whole defect — so a result without them must still
    reach that None, or this fix is guarding nothing."""
    r = APA.resolve_pdk("ihp-sg13g2", lister=_lister(_TREE))
    assert r.get("available") and (r.get("drc_deck") or r.get("lvs_deck"))
    broken = dict(r, drc_deck=None, lvs_deck=None)
    assert not (broken.get("available")
                and (broken.get("drc_deck") or broken.get("lvs_deck")))


def test_R1_family_affinity_picks_the_signoff_deck_not_a_helper():
    """LOAD-BEARING, and measured: one open PDK ships six files matching the
    deck glob in ONE directory, and plain alphabetical order puts a per-rule
    helper first and the sign-off runset fourth."""
    tree = dict(_TREE)
    tree["/foss/pdks/sky130A/libs.tech"] = ["ngspice", "klayout"]
    tree["/foss/pdks/sky130A/libs.tech/ngspice"] = ["models"]
    tree["/foss/pdks/sky130A/libs.tech/ngspice/models"] = ["x.lib"]
    tree["/foss/pdks/sky130A/libs.tech/klayout/drc"] = [
        "aaa_helper.rb.drc", "sky130A_mr.drc", "zzz_other.rb.drc"]
    tree["/foss/pdks/sky130A/libs.tech/klayout/lvs"] = ["sky130.lvs"]
    r = APA.resolve_pdk("sky130A", lister=_lister(tree))
    assert r["drc_deck"].endswith("sky130A_mr.drc"), r["drc_deck_candidates"]
    # ...and every candidate is published, never silently one of six.
    assert len(r["drc_deck_candidates"]) == 3


def test_R1_a_project_that_stages_its_own_pdk_is_UNTOUCHED(tmp_path):
    """Rung 1 already set both decks. The real benchmark cell stages its own
    `input/pdk/`, so it resolves at rung 1 and this change cannot reach it —
    which is exactly why the control matters."""
    proj = tmp_path / "p"
    (proj / "input/pdk/klayout/tech/drc").mkdir(parents=True)
    (proj / "input/pdk/klayout/tech/lvs").mkdir(parents=True)
    (proj / "input/pdk/models").mkdir(parents=True)
    (proj / "input/pdk/models/corner.lib").write_text(".subckt x a\n.ends\n")
    (proj / "input/pdk/klayout/tech/drc/mypdk.drc").write_text("report('x')\n")
    (proj / "input/pdk/klayout/tech/lvs/mypdk.lvs").write_text("schematic\n")
    r = APA.resolve_pdk("mypdk", project=str(proj))
    assert r["rung"] == 1 and r["source"] == "project_custom_pdk"
    assert r["drc_deck"].endswith("mypdk.drc")


# ── R12: no corner is ended by a clock ────────────────────────────────────
class _Fine:
    returncode = 0
    stdout = "vavg = 6.000000e-01\nMEAS density= 0.6  swing= 1.0\n"


def _stub(monkeypatch, seen, cp=_Fine):
    def fake(container, cmd, timeout=120):
        seen["timeout"] = timeout
        return cp()
    monkeypatch.setattr(ARS, "_docker", fake)
    monkeypatch.setattr(ARS, "_resolve_ngspice", lambda c: "ngspice")
    monkeypatch.setattr(ARS, "_supports_json_measure", lambda c, b: False)


def test_R12_a_corner_run_is_given_no_deadline(monkeypatch):
    """GNU `timeout` documents DURATION 0 as "disable the associated timeout",
    measured both directions on this image (coreutils 9.4)."""
    seen = {}
    _stub(monkeypatch, seen)
    ARS._run_ngspice("c", "/tmp/d.sp", deck_text="tran 0.5n 51200n\n",
                     run_to_completion=True)
    assert seen["timeout"] == 0


def test_R12_the_deadline_machinery_is_UNCHANGED_for_a_caller_that_asks(
        monkeypatch):
    """The control that keeps this from being a blanket removal: a caller that
    does NOT opt out still gets the deck-scaled deadline, and the 120 s floor
    is still the floor."""
    seen = {}
    _stub(monkeypatch, seen)
    ARS._run_ngspice("c", "/tmp/d.sp", deck_text="tran 0.5n 51200n\n")
    assert seen["timeout"] == ARS.sim_deadline_s("tran 0.5n 51200n\n") > 120


def test_R12_the_corner_call_site_hands_the_deck_over():
    """The pre-existing guard greps this source for `deck_text=tb`, which is
    the BASE run's call site — and the PVT call site next to it was the broken
    one, so the guard passed through the whole defect. Both sites are named
    here, by their own kwargs."""
    src = (_PROGRAMS / "analog_real_corner_sweep.py").read_text()
    assert "deck_text=tb, run_to_completion=True" in src     # base run
    assert "deck_text=deck, run_to_completion=True" in src   # PVT corner


# ── R12c: an attempted corner that produced nothing says why ──────────────
def test_R12c_a_healthy_run_produces_no_not_completed_record():
    """The control that gives the record meaning: it must not appear on a run
    that worked."""
    assert ARS.not_completed_record("all fine\n", {"rc": 0}, True, 0.6,
                                    "x.log") is None


def test_R12c_a_nonconvergent_corner_is_named_in_the_simulators_own_words():
    raw = ("doAnalyses: TRAN:  Timestep too small\n"
           "trouble with node xdut.nbias\n")
    rec = ARS.not_completed_record(raw, {"rc": 1, "deadline_s": 0,
                                         "run_to_completion": True},
                                   False, None, "pvt_ss_m40c.ngspice.log")
    assert rec["reason_class"] == "SIMULATOR_NONCONVERGENCE"
    assert any("trouble with node" in c for c in rec["cause"])
    assert rec["ngspice_log"] == "pvt_ss_m40c.ngspice.log"


def test_R12c_a_not_completed_corner_publishes_NO_number():
    """An arithmetic spread in the same column as a measurement is what made
    the grid unreadable. The estimate IS available for this cell and is
    deliberately withheld."""
    grid, executed = ARS.build_pvt_grid(
        1.2, "b.log", {("tt", "27c"): {"value": 1.2, "ok": True,
                                       "log": "b.log"}}, 0.05,
        not_completed={("ss", "m40c"): {
            "reason_class": "SIMULATOR_NONCONVERGENCE",
            "cause": ["trouble with node x"], "ngspice_log": "l.log"}})
    assert executed == 1
    bad = [c for c in grid if c["name"] == "ss_m40c"][0]
    assert bad["_provenance"] == "NOT_COMPLETED"
    assert bad["vout_v"] is None
    assert bad["not_completed"]["cause"] == ["trouble with node x"]
    # a corner that was never ATTEMPTED (no model section) still derives
    other = [c for c in grid if c["name"] == "ff_125c"][0]
    assert other["_provenance"] == "DERIVED" and other["vout_v"] is not None


# ── the A4 gate blocks on its own record's NOT_MEASURED ───────────────────
def _proj(tmp_path, doc, block="ldo"):
    b = tmp_path / "phase3" / "analog" / block
    b.mkdir(parents=True)
    (b / "corner_results.json").write_text(json.dumps(doc))
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": block, "type": block}]}))
    return tmp_path


def _doc(executed=9, total=9, full=True, unaccounted=0):
    corners = []
    for i in range(total):
        if i < executed:
            corners.append({"name": f"c{i}", "simulator_run": True,
                            "vout_v": 1.2, "_provenance": "real_ngspice"})
        elif i < executed + unaccounted:
            corners.append({"name": f"c{i}", "simulator_run": False,
                            "vout_v": 1.19, "_provenance": "DERIVED"})
        else:
            corners.append({"name": f"c{i}", "simulator_run": False,
                            "vout_v": None, "_provenance": "NOT_COMPLETED",
                            "not_completed": {
                                "reason_class": "SIMULATOR_NONCONVERGENCE",
                                "cause": ["trouble with node x"]}})
    return {"block": "ldo", "corners": corners, "total_corners": total,
            "corners_executed": executed, "full_pvt_sweep_executed": full,
            "netlist_provenance": "a3_netlist",
            "design_content": "structure_and_geometry",
            "spec_results": [{"name": "vout", "status": "PASS",
                              "value": 1.2, "target": 1.2,
                              "tolerance_pct": 0.05}]}


def _a4(project, block="ldo"):
    import subprocess
    return subprocess.run(
        [sys.executable, str(_PROGRAMS / "analog_a4_corner_sweep_check.py"),
         str(project), "--block", block, "--json", str(project / "a4.json")],
        capture_output=True, text=True)


def test_A4_a_real_nine_of_nine_record_still_PASSES(tmp_path):
    """THE CONTROL THAT MATTERS. The measured 9/9 ldo record must still pass —
    if it does not, this is a broken gate, not a fixed one."""
    cp = _a4(_proj(tmp_path, _doc()))
    assert cp.returncode == 0, cp.stderr[-2000:]


@pytest.mark.parametrize("label,doc", [
    ("the measured record: 1 of 9, full_pvt false",
     _doc(executed=1, full=False, unaccounted=8)),
    ("a 9/9 record that denies its own claim",
     _doc(executed=9, full=False)),
    ("one corner quietly filled with arithmetic",
     _doc(executed=8, full=True, unaccounted=1)),
])
def test_A4_a_record_whose_own_fields_say_NOT_MEASURED_BLOCKS(
        tmp_path, label, doc):
    cp = _a4(_proj(tmp_path, doc))
    assert cp.returncode == 1, (label, cp.stdout, cp.stderr)
    rpt = json.loads((tmp_path / "a4.json").read_text())
    assert rpt["verdict"] == "INCOMPLETE", label
    assert rpt["reason_class"] == "NOT_MEASURED", label


def test_A4_a_corner_reported_NOT_COMPLETED_with_a_cause_is_ACCOUNTED_FOR(
        tmp_path):
    """Accounted for is not the same as executed: this record does not claim a
    full sweep, so it still blocks — but it blocks naming the CLAIM, not the
    corner, because that corner said why."""
    cp = _a4(_proj(tmp_path, _doc(executed=8, full=False)))
    assert cp.returncode == 1
    rpt = json.loads((tmp_path / "a4.json").read_text())
    nm = [f for f in rpt["findings"]
          if f["rule"] == "A4_PVT_SWEEP_NOT_MEASURED"][0]
    assert nm["unaccounted_corners"] == []


def test_A4_a_not_completed_record_with_NO_cause_is_not_an_account(tmp_path):
    """A `not_completed` key carrying no cause is the same silence one field
    deeper."""
    doc = _doc(executed=8, full=False)
    doc["corners"][-1]["not_completed"] = {}
    cp = _a4(_proj(tmp_path, doc))
    rpt = json.loads((tmp_path / "a4.json").read_text())
    nm = [f for f in rpt["findings"]
          if f["rule"] == "A4_PVT_SWEEP_NOT_MEASURED"][0]
    assert nm["unaccounted_corners"] == ["c8"], rpt
    assert cp.returncode == 1


# ── R6: the run's own log names the libraries the deck loaded ─────────────
def test_R6_the_log_head_names_the_absolute_libraries_the_deck_loaded():
    deck = (".lib /foss/pdks/fam/libs.tech/ngspice/models/cornerMOSlv.lib tt\n"
            ".include /foss/pdks/fam/libs.tech/ngspice/models/diodes.lib\n"
            "tran 1n 100n\n.end\n")
    head = ARS.deck_library_header(deck)
    assert "cornerMOSlv.lib" in head and "diodes.lib" in head
    import pdk_revision_resolve as PRR
    found = PRR._ABS_LIB_RE.findall(head)
    assert len(found) == 2, head


def test_R6_a_deck_with_no_absolute_include_gets_NO_header():
    """The control: a line that appears unconditionally says nothing when it
    appears."""
    assert ARS.deck_library_header("* self-contained\ntran 1n 1n\n.end\n") == ""
