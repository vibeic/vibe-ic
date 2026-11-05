#!/usr/bin/env python3
"""vibe-ic#2122 — a DIE owes its own seal ring a band, and nothing may be
sealed into it.

WHERE THE BAR COMES FROM. Not this repo's opinion: three runs of the SAME PDK
generator and the SAME sign-off deck on one gf180mcuD die (vibeic-eda#189,
re-measured in vibe-ic#2122):

    the ring alone, on an empty 503 um die                    16, all density
    that ring around the run's own core, which filled         1,359,531
      (0,0;503,503) — GR.4 1,299,340 · GR.2 24,652 · PL.6 7,205 · …
    the same core moved 28.5 um inward, 560 um die                     0

19,826 core shapes sat inside the 16 um ring band. The generator, the ring and
the deck were all correct. The DIE was too small by the ring's band plus the
deck's own marker clearance — `sealring_edge_width = 16` in the generator's own
cell library, and GR.2's `comp.separation(guard_ring_mk, 10.um)` in the deck —
and the flow sized the die to the core and then sealed the ring on in place,
reporting `seal_ring.state = PASS`.

Every test below breaks something that fix defends and requires the failure:

  * the margin is INVENTED rather than read           -> the parsers here read
                                                         the PDK's own words
  * the technology says nothing                       -> NOT_MEASURED by name,
                                                         and the floorplan is
                                                         byte-for-byte today's
  * a core in the band is sealed anyway               -> die_finishing REFUSES,
                                                         naming the clearance
  * the refusal cannot fail                           -> the same fixture one
                                                         micron the other side
                                                         of the boundary seals
  * a pinned die is grown out from under its operator -> only the core moves
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _klayout_launch as KL                                  # noqa: E402
import _progress_run as _pr                                   # noqa: E402
import _seal_ring_margin as SRM                               # noqa: E402
import die_finishing_gen as DFG                               # noqa: E402


# ── the derivation: the PDK's own words, and nothing else ───────────────────

def test_the_band_is_read_from_the_generators_own_cell_library():
    """`sealring_edge_width = 16` — discovered by what the name SAYS (a seal,
    a width), not by matching one PDK's spelling of it."""
    text = ("sealring_edge_width = 16\n"
            "sealring_corner_radius = 4\n"
            "metal1_width = 3\n")
    assert SRM.band_declarations(text) == [("sealring_edge_width", 16.0)]
    # A generator that spells it differently is read the same way.
    assert SRM.band_declarations("SealBandWidth = 20\n") == [
        ("SealBandWidth", 20.0)]
    # And a width that is not the seal's is not the seal's.
    assert SRM.band_declarations("dummy_fill_width = 7\n") == []


def test_the_clearance_is_read_from_the_decks_own_separation_rule():
    deck = ("  gr2_l1 = comp.separation(guard_ring_mk, 10.um)\n"
            "  gr2_l1.output('GR.2', 'GR.2 : … prime die COMP: 10')\n"
            "  gr2_l1 = nwell.separation(guard_ring_mk, 10.um)\n"
            "  gr2_l1.output('GR.2', 'GR.2 : … prime die NWELL: 10')\n"
            "  other = comp.separation(some_other_mk, 4.um)\n")
    got = SRM.clearance_declarations(deck)
    assert [d["um"] for d in got] == [10.0, 10.0]
    assert {d["rule"] for d in got} == {"GR.2"}
    assert [d["prime_layer"] for d in got] == ["comp", "nwell"]
    # The marker is matched on WHAT IT IS. A deck that names it differently is
    # read; a separation to something that is not a guard-ring marker is not.
    other = SRM.clearance_declarations(
        "  x = poly.separation(dieGuardRingMarker, 12.5.um)\n")
    assert [d["um"] for d in other] == [12.5]
    assert SRM.clearance_declarations(
        "  x = poly.separation(nwell, 12.um)\n") == []


def _fake_pdk(tmp_path, band="sealring_edge_width = 16\n",
              clearance="  g = comp.separation(guard_ring_mk, 10.um)\n"
                        "  g.output('GR.2', 'GR.2 : … : 10')\n"):
    """A PDK laid out the way a PDK is laid out, with only the two texts the
    derivation reads. `None` for either leaves that link genuinely absent."""
    root = tmp_path / "pdks"
    tech = root / "testpdk" / "libs.tech" / "klayout" / "tech"
    (tech / "pymacros" / "sealring_cells").mkdir(parents=True)
    (tech / "drc" / "rule_decks").mkdir(parents=True)
    (tech / "scripts").mkdir(parents=True, exist_ok=True)
    if band is not None:
        (tech / "pymacros" / "sealring_cells"
         / "draw_sealring.py").write_text(band)
    if clearance is not None:
        (tech / "drc" / "rule_decks" / "guard_ring.rb").write_text(clearance)
    return str(root), "testpdk", str(root / "testpdk")


def _sh(cmd):
    cp = _pr.run(["sh", "-c", cmd], capture_output=True, text=True)
    return cp.returncode, cp.stdout


def test_the_margin_is_the_band_plus_the_clearance_and_names_its_chain(
        tmp_path):
    _root, _name, pdk_dir = _fake_pdk(tmp_path)
    got = SRM.derive(pdk_dir, _sh)
    assert got["band_um"] == 16.0
    assert got["clearance_um"] == 10.0
    assert got["margin_um"] == 26.0
    assert got["not_measured"] == {}
    # Every link NAMES the file it came from, so the chain is checkable.
    assert "draw_sealring.py" in got["band_basis"]
    assert "guard_ring.rb" in got["clearance_basis"]
    assert "GR.2" in got["clearance_basis"]


def test_a_measured_band_outranks_the_generators_declared_parameter(tmp_path):
    """The consumer that has already SEEN the ring passes what it measured."""
    _root, _name, pdk_dir = _fake_pdk(tmp_path)
    got = SRM.derive(pdk_dir, _sh, band_um=18.0,
                     band_basis="the ring's measured inner extent")
    assert got["margin_um"] == 28.0
    assert got["band_basis"] == "the ring's measured inner extent"


@pytest.mark.parametrize("band,clearance,missing", [
    (None, "  g = comp.separation(guard_ring_mk, 10.um)\n", "band_um"),
    ("sealring_edge_width = 16\n", None, "clearance_um"),
])
def test_an_unread_link_is_a_named_NOT_MEASURED_never_a_default(
        tmp_path, band, clearance, missing):
    _root, _name, pdk_dir = _fake_pdk(tmp_path, band=band, clearance=clearance)
    got = SRM.derive(pdk_dir, _sh)
    assert got["margin_um"] is None
    assert missing in got["not_measured"], got
    assert SRM.NOT_MEASURED in got["margin_basis"]
    # The reason NAMES what could not be read, so it can be chased.
    assert pdk_dir in got["not_measured"][missing]


def test_a_read_that_hit_the_size_cap_says_so_instead_of_answering(
        tmp_path, monkeypatch):
    """A cap that fires is a read that did not finish: the last file came back
    cut and its declarations are missing from the parse. Answering from a
    partial read is worse than saying it could not be read."""
    _root, _name, pdk_dir = _fake_pdk(
        tmp_path,
        band="sealring_edge_width = 16\n" + ("# pad\n" * 200000))
    val, why = SRM.ring_band_um(pdk_dir, _sh)
    assert val is None, "a truncated read must not answer"
    assert "cap" in why and "read only in part" in why


def test_two_disagreeing_seal_widths_are_NOT_MEASURED_not_a_choice(tmp_path):
    """Choosing between two foundry numbers is exactly what this must not do."""
    _root, _name, pdk_dir = _fake_pdk(
        tmp_path, band="sealring_edge_width = 16\nsealring_outer_width = 24\n")
    val, why = SRM.ring_band_um(pdk_dir, _sh)
    assert val is None
    assert "16" in why and "24" in why and "foundry data" in why


# ── the die and the core: pure arithmetic, no PDK, no container ─────────────

























# ── the refusal, on a real KLayout, both ways ───────────────────────────────

class _LocalRunner:
    """The in-process runner the other die-finishing tests use, plus the `sh`
    the deck read needs."""
    kind = "test"
    detail = "in-process"

    def cpath(self, p):
        return str(p)

    def covers(self, p):
        return True

    def exists(self, p):
        return Path(str(p)).is_file()

    def klayout_bin(self):
        return "klayout"

    def run_argv(self, argv, env, timeout=1800):
        full = dict(os.environ)
        full.update({k: str(v) for k, v in env.items()})
        cp = _pr.run([str(a) for a in argv], capture_output=True, text=True,
                     env=full)
        return cp.returncode, cp.stdout, cp.stderr

    def run(self, script, env, path_keys=(), timeout=1800):
        return self.run_argv([sys.executable, str(script)], env,
                             timeout=timeout)


#: The die, the ring's band and the core lattice's pitch, in um. The lattice is
#: on the SAME layer the ring is drawn on, which is what makes it the deck's
#: business: GR.2/GR.4/GR.6 fire on prime-die geometry that shares a layer with
#: the ring. Pitch 4 / width 2 so no box straddles the band edge — a fixture
#: whose own arithmetic decides the answer is not a fixture.
_DIE_UM = 200.0
_BAND_UM = 16.0
_PITCH_UM = 4.0
_BOX_UM = 2.0


def _project(tmp_path, core_from=0.0, core_to=_DIE_UM):
    """A project whose core is a lattice reaching from `core_from` to
    `core_to`. `core_from=0` is arm A — the shape the run actually built."""
    pya = pytest.importorskip("pya")
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("chip_top")
    li = ly.layer(pya.LayerInfo(10, 0))
    n = int(_DIE_UM * 1000)
    x = core_from
    while x + _BOX_UM <= core_to + 1e-9:
        y = core_from
        while y + _BOX_UM <= core_to + 1e-9:
            top.shapes(li).insert(pya.Box(
                int(x * 1000), int(y * 1000),
                int((x + _BOX_UM) * 1000), int((y + _BOX_UM) * 1000)))
            y += _PITCH_UM
        x += _PITCH_UM
    ly.write(str(pnr / "chip_top.gds"))
    (pnr / "routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN chip_top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        f"DIEAREA ( 0 0 ) ( {n} {n} ) ;\nEND DESIGN\n")
    return tmp_path


#: A generator that draws the ring where a real one draws it — a band INSIDE
#: the die, on the core's own layer, plus its marker layer. The band width is
#: this fixture's, passed in, so the test never depends on a PDK being present.
_GEN = '''import sys
import pya
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
src, dst = a["--input"], a["--output"]
w, h = float(a["--die-width"]), float(a["--die-height"])
ly = pya.Layout(); ly.read(src); top = ly.top_cell()
n = int(w * 1000)
b = int(%f * 1000)
band = (pya.Region(pya.Box(0, 0, n, n))
        - pya.Region(pya.Box(b, b, n - b, n - b)))
for spec in ((10, 0), (11, 0)):
    li = ly.layer(pya.LayerInfo(*spec))
    for p in band.each():
        top.shapes(li).insert(p)
ly.write(dst)
''' % _BAND_UM


def _generator(tmp_path):
    p = tmp_path / "gen_ring_inside.py"
    p.write_text(_GEN)
    return p


def _seal(project, tmp_path, monkeypatch, **pdk):
    monkeypatch.setattr(KL, "find_runner", lambda *a, **k: _LocalRunner())
    monkeypatch.setattr(DFG._kl, "find_runner", lambda *a, **k: _LocalRunner())
    return DFG.run(project, None, str(_generator(tmp_path)), None, None,
                   pdk.get("pdk_root"), pdk.get("pdk"), sys.executable,
                   None, None, None, None, True, None)


def test_a_core_that_reaches_the_die_edge_is_REFUSED_naming_the_clearance(
        tmp_path, monkeypatch):
    """ARM A — the shape the run built. 1.36 M sign-off violations came from
    sealing exactly this."""
    root, name, _dir = _fake_pdk(tmp_path)
    project = _project(tmp_path / "p", core_from=0.0)
    gds = project / "phase3" / "stage3" / "pnr" / "chip_top.gds"
    before = gds.read_bytes()
    res = _seal(project, tmp_path, monkeypatch, pdk_root=root, pdk=name)
    seal = res["seal_ring"]
    assert seal["state"] == "FAIL", json.dumps(res)[:2000]
    # The ring itself VERIFIED — this is not a ring failure wearing a new name.
    assert seal["ring_check"]["verdict"] == "PASS"
    cc = seal["core_clearance"]
    assert cc["state"] == "MEASURED"
    assert cc["clearance_um"] == 10.0
    assert cc["keep_box_um"] == [26.0, 26.0, 174.0, 174.0], cc
    assert cc["encroaching_polygons"] > 0
    assert cc["encroaching_by_layer"], cc
    # The refusal QUOTES the deck, so the reader can check it.
    assert "10.0 um" in seal["reason"]
    assert "GR.2" in seal["reason"]
    assert "guard_ring.rb" in seal["reason"]
    assert "vibe-ic#2122" in seal["reason"]
    # NOTHING IS SHIPPED. No finished die, no skip marker, no promotion.
    assert not (project / DFG._DEF_REL).is_file()
    assert not (project / DFG._SKIPPED_REL).is_file()
    assert gds.read_bytes() == before
    assert "gds_out" not in seal and "gds_out_unpromoted" in seal


def test_a_core_inset_by_the_derived_margin_SEALS(tmp_path, monkeypatch):
    """ARM B — the negative control, the other direction. Without it the
    refusal above could be a check that always fires.

    IT ASSERTS ONLY WHAT IS TRUE BOTH BEFORE AND AFTER THIS FIX — the die is
    sealed and a finished die is left behind. MEASURED: with the two changed
    blobs swapped back to v1.18.77 this test still passes and the four refusal
    tests fail, which is what makes the pair a direction and not a pair of
    assertions about a key that is simply new. What the fix ADDS to this arm is
    the next test, which is red on that base for the mechanical reason that the
    measurement did not exist.
    """
    root, name, _dir = _fake_pdk(tmp_path)
    project = _project(tmp_path / "p", core_from=26.0, core_to=174.0)
    res = _seal(project, tmp_path, monkeypatch, pdk_root=root, pdk=name)
    seal = res["seal_ring"]
    assert seal["state"] == "PASS", json.dumps(res)[:2000]
    assert (project / DFG._DEF_REL).is_file()
    assert not (project / DFG._SKIPPED_REL).is_file()


def test_the_inset_core_is_MEASURED_clear_not_merely_unrefused(
        tmp_path, monkeypatch):
    """A seal that happened is not evidence the opening was measured."""
    root, name, _dir = _fake_pdk(tmp_path)
    project = _project(tmp_path / "p", core_from=26.0, core_to=174.0)
    res = _seal(project, tmp_path, monkeypatch, pdk_root=root, pdk=name)
    cc = res["seal_ring"]["core_clearance"]
    assert cc["state"] == "MEASURED"
    assert cc["clearance_um"] == 10.0
    assert cc["keep_box_um"] == [26.0, 26.0, 174.0, 174.0], cc
    assert cc["encroaching_polygons"] == 0, cc
    assert cc["ring_layers_the_core_also_uses"], (
        "an empty population is NOT a clear core: if the ring shares no layer "
        "with the core this measurement has no denominator and says nothing")
    assert cc["population_empty"] is False


def test_a_zero_over_an_EMPTY_population_is_disclosed_not_read_as_clear(
        tmp_path, monkeypatch):
    """MEASURED on the ring-alone arm of the real experiment: a layout with
    nothing on any of the ring's layers reports `encroaching_polygons: 0`, and
    that reads exactly like a core standing back. It is not the same fact and
    it must not arrive wearing the same sentence."""
    pya = pytest.importorskip("pya")
    root, name, _dir = _fake_pdk(tmp_path)
    project = tmp_path / "p"
    pnr = project / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("chip_top")
    # A layer the RING is not drawn on, so the shared population is empty.
    li = ly.layer(pya.LayerInfo(200, 0))
    n = int(_DIE_UM * 1000)
    top.shapes(li).insert(pya.Box(n // 2 - 1000, n // 2 - 1000,
                                  n // 2 + 1000, n // 2 + 1000))
    ly.write(str(pnr / "chip_top.gds"))
    (pnr / "routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN chip_top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        f"DIEAREA ( 0 0 ) ( {n} {n} ) ;\nEND DESIGN\n")
    res = _seal(project, tmp_path, monkeypatch, pdk_root=root, pdk=name)
    seal = res["seal_ring"]
    assert seal["state"] == "PASS", json.dumps(res)[:2000]
    cc = seal["core_clearance"]
    assert cc["encroaching_polygons"] == 0
    assert cc["population_empty"] is True
    assert "EMPTY POPULATION" in seal["core_clearance_population_empty"]


def test_one_micron_the_wrong_side_of_the_boundary_still_REFUSES(
        tmp_path, monkeypatch):
    """The boundary itself, so the pair above cannot be two coarse arms of a
    check that is really testing something else."""
    root, name, _dir = _fake_pdk(tmp_path)
    project = _project(tmp_path / "p", core_from=25.0, core_to=174.0)
    res = _seal(project, tmp_path, monkeypatch, pdk_root=root, pdk=name)
    seal = res["seal_ring"]
    assert seal["state"] == "FAIL", json.dumps(res)[:2000]
    cc = seal["core_clearance"]
    assert cc["encroaching_polygons"] > 0
    assert cc["worst_encroachment_um"]["left_um"] == pytest.approx(1.0)


def test_a_deck_that_states_a_LARGER_clearance_refuses_a_core_that_cleared_10(
        tmp_path, monkeypatch):
    """The number is the DECK's, not this program's: change the deck and the
    verdict changes with it."""
    root, name, _dir = _fake_pdk(
        tmp_path,
        clearance="  g = comp.separation(guard_ring_mk, 20.um)\n"
                  "  g.output('GR.2', 'GR.2 : … : 20')\n")
    project = _project(tmp_path / "p", core_from=26.0, core_to=174.0)
    res = _seal(project, tmp_path, monkeypatch, pdk_root=root, pdk=name)
    seal = res["seal_ring"]
    assert seal["state"] == "FAIL", json.dumps(res)[:2000]
    assert seal["core_clearance"]["keep_box_um"] == [36.0, 36.0, 164.0, 164.0]


def test_an_unreadable_deck_is_NAMED_and_does_not_invent_a_clearance(
        tmp_path, monkeypatch):
    """A technology that has not spoken must not be answered for — and must not
    silently stop a flow that worked yesterday either."""
    root, name, _dir = _fake_pdk(tmp_path, clearance=None)
    project = _project(tmp_path / "p", core_from=0.0)
    res = _seal(project, tmp_path, monkeypatch, pdk_root=root, pdk=name)
    seal = res["seal_ring"]
    assert seal["state"] == "PASS", json.dumps(res)[:2000]
    assert SRM.NOT_MEASURED not in json.dumps(seal.get("core_clearance", {}))
    why = seal["core_clearance_not_measured"]
    assert "guard-ring-marker separation" in why
    assert str(Path(root) / name) in why
    assert seal["ring_check"].get("core_clearance") is None


def test_the_verifier_reports_the_opening_but_never_judges_it(
        tmp_path, monkeypatch):
    """`core_clearance` is REPORTED by the verifier and JUDGED by the producer.
    Folding it into the ring's own verdict would make one half's silence look
    like the other half's failure — the rule `id_cells` already follows."""
    root, name, _dir = _fake_pdk(tmp_path)
    project = _project(tmp_path / "p", core_from=0.0)
    res = _seal(project, tmp_path, monkeypatch, pdk_root=root, pdk=name)
    rc = res["seal_ring"]["ring_check"]
    assert rc["verdict"] == "PASS"
    assert rc["core_clearance"]["encroaching_polygons"] > 0
