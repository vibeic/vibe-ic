"""#613 — the sign-off GDS carried none of the ports the DEF declared.

Measured on a real run (IHP SG13G2 `u_hawaii_adc`): `filled.def` says
`PINS 20 ;`, all placed with layers, and the streamed
`phase3/stage4/gds/u_hawaii_adc.gds` top cell holds 0 text labels. Extraction
then emits `.subckt u_hawaii_adc` with no ports at all and every schematic port
resolves to an anonymous node, so that step could never reach PASS no matter how
correct the layout was.

THREE INDEPENDENT DEFECTS, and only the first was filed.

1. THE TRIGGER WAS A PREDICTION, NOT A MEASUREMENT. The restore pass already
   existed and ran only where a bridge config declared `port_label_restore`, on
   the premise "OSS PDKs keep native streamout". Measured on the tracked corpus
   the premise predicts nothing in either direction — sky130A sha256 77/77 and
   subservient 31/31 get their labels natively with no config; the IHP run got
   0 of 20 with no config. Whether the labels are IN THE FILE is a fact of the
   artefact, readable the moment streamout finishes.

2. THE PRODUCER AND THE CONSUMER OF ITS OWN CONTRACT DISAGREED ABOUT WHAT A
   METAL LAYER IS. `def_gds_port_power_restore` matched `^MET(\\d+)$`;
   `klayout_pdk_lvs`, which READS the datatype it writes, has always matched
   `^(?:MET|METAL|M)(\\d+)$`. On a PDK naming its layers `Metal1 … Metal5` every
   pin fell through to the datatype-0 catch-all — which the extractor binds to
   m1 ALONE, so a pin above m1 names nothing or names whatever m1 wire passes
   under it. Silently the pre-v1.3.93 behaviour that file exists to have fixed.

3. THE SAME HARDCODED NAME APPEARED IN THREE PLACES, and the third was the
   quiet one: `parse_power_rails` scanned for `(MET\\d+)` literally, so on such a
   PDK it found ZERO rail segments — no marker painted, follow-pin rails left
   physically disjoint. The issue found one instance; there were three.

THE TECH-LEF ROUTING ORDER IS DELIBERATELY NOT A FALLBACK, and the reason is
measured: sky130 declares `li1` as TYPE ROUTING, so met1's POSITION in that
order is 2 while the datatype contract numbers it 1. Resolving by position would
shift every sky130 label by one.

CALIBRATION BEFORE THE PREDICATE WAS CHOSEN: blocking on "a placed pin with no
label" flips 0 of the 4 real sign-off GDS on this host (sha256 77/77,
sha256_magic 77/77, spm 36/36, subservient 31/31 — exact string match, both
streamout engines).
"""
from __future__ import annotations

import importlib
import json
import pathlib
import struct
import sys

import pytest
import yaml

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

PWR = importlib.import_module("def_gds_port_power_restore")
GSC = importlib.import_module("gds_substance_check")
CEN = importlib.import_module("gds_port_label_check")
KLVS = importlib.import_module("klayout_pdk_lvs")


# ── a real GDSII stream, built record by record ─────────────────────────────
def _rec(rt: int, payload: bytes = b"") -> bytes:
    if len(payload) % 2:
        payload += b"\x00"
    return struct.pack(">HH", len(payload) + 4, rt) + payload


def _name(s: str) -> bytes:
    b = s.encode("ascii")
    return b + (b"\x00" if len(b) % 2 else b"")


def _text_element(layer: int, dt: int, x: int, y: int, s: str) -> bytes:
    return (_rec(0x0C00)                                  # TEXT
            + _rec(0x0D02, struct.pack(">h", layer))      # LAYER
            + _rec(0x1602, struct.pack(">h", dt))         # TEXTTYPE
            + _rec(0x1003, struct.pack(">ii", x, y))      # XY
            + _rec(0x1906, _name(s))                      # STRING
            + _rec(0x1100))                               # ENDEL


def _boundary(layer: int) -> bytes:
    pts = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
    return (_rec(0x0800)
            + _rec(0x0D02, struct.pack(">h", layer))
            + _rec(0x0E02, struct.pack(">h", 0))
            + _rec(0x1003, b"".join(struct.pack(">ii", *p) for p in pts))
            + _rec(0x1100))


def _sref(cell: str) -> bytes:
    return (_rec(0x0A00)
            + _rec(0x1206, _name(cell))
            + _rec(0x1003, struct.pack(">ii", 0, 0))
            + _rec(0x1100))


def _structure(name: str, body: bytes) -> bytes:
    return (_rec(0x0502, b"\x00" * 24) + _rec(0x0606, _name(name))
            + body + _rec(0x0700))


def build_gds(top: str, top_labels, child_labels=("A", "B")) -> bytes:
    """A two-structure library: a child cell carrying its OWN pin texts, and a
    top cell that instantiates it. The child's labels are what make a
    LIBRARY-WIDE text count useless for this question."""
    child = _structure("leafcell",
                       _boundary(1)
                       + b"".join(_text_element(100, 1, 0, 0, s)
                                  for s in child_labels))
    body = _boundary(2) + _sref("leafcell")
    for i, s in enumerate(top_labels):
        body += _text_element(100, 1, i * 10, 0, s)
    return (_rec(0x0002, struct.pack(">h", 600))
            + _rec(0x0102, b"\x00" * 24)
            + _rec(0x0206, _name("LIB"))
            + _rec(0x0305, b"\x00" * 16)
            + child + _structure(top, body)
            + _rec(0x0400))


def _seed_layout(path):
    """A REAL input layout, because :func:`restore` opens one.

    The tests below used to hand `restore` a GDS path that DOES NOT EXIST and
    lean on the run stopping at the `pya`-absent disclosure before it looked.
    That premise is false wherever KLayout is installed — which is the pinned
    landing image `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2...` (`pya` at
    /usr/local/lib/python3.12/dist-packages/pya/__init__.py) and the fleet
    hosts alike — and there the call reached `pya.Layout().read()` and died with
    `RuntimeError: Unable to open file ... (errno=2)`: a defect of the fixture,
    which proves nothing about the subject in either direction.

    Where KLayout IS present the seed is written BY KLayout, so it is valid by
    construction and no hand-rolled GDSII byte string can drift from what the
    reader accepts. Where it is absent `restore` returns the disclosed rc 3
    before opening anything, so these bytes are never read.
    """
    try:
        import pya
    except Exception:                        # noqa: BLE001 — absence is a state
        path.write_bytes(b"")
        return
    layout = pya.Layout()
    layout.create_cell("chip")
    layout.write(str(path))


def _def(design: str, pins, layer="Metal2", declared=None):
    n = declared if declared is not None else len(pins)
    recs = "".join(
        f"    - {p} + NET {p} + DIRECTION INPUT + USE SIGNAL\n"
        f"      + LAYER {layer} ( -70 -70 ) ( 70 70 )\n"
        f"      + PLACED ( {1000 * (i + 1)} 2000 ) N ;\n"
        for i, p in enumerate(pins))
    return (f"VERSION 5.8 ;\nDESIGN {design} ;\n"
            f"UNITS DISTANCE MICRONS 1000 ;\n"
            f"PINS {n} ;\n{recs}END PINS\nEND DESIGN\n")


def _project(tmp_path, design, pins, top_labels, layer="Metal2", declared=None):
    g = tmp_path / "phase3" / "stage4" / "gds"
    g.mkdir(parents=True)
    (g / f"{design}.gds").write_bytes(build_gds(design, top_labels))
    d = tmp_path / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "routed.def").write_text(_def(design, pins, layer, declared),
                                  encoding="utf-8")
    return tmp_path


def _run(project, extra=()):
    out = project / "cen.json"
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / "gds_port_label_check.py"),
         str(project), "--json", str(out), *extra],
        capture_output=True, text=True)
    rep = json.loads(out.read_text()) if out.is_file() else {}
    return r.returncode, (r.stdout + r.stderr), rep


# ── 2. the producer and the consumer must agree on what a metal name is ─────
@pytest.mark.parametrize("name,idx", [
    ("MET1", 1), ("met1", 1), ("MET7", 7),
    ("Metal1", 1), ("METAL5", 5), ("metal3", 3),   # the #613 PDK's own naming
    ("M1", 1), ("m4", 4),
    ("VIA1", 0), ("li1", 0), ("poly", 0), ("TopMetal1", 0), ("", 0),
])
def test_the_one_resolver(name, idx):
    assert PWR.metal_index(name) == idx


@pytest.mark.parametrize("name", ["MET1", "met3", "Metal1", "METAL5", "M2",
                                  "VIA1", "li1", "poly", "TopMetal2"])
def test_producer_and_consumer_classify_the_same_names_the_same_way(name):
    """LOAD-BEARING, and the #613 root cause. `klayout_pdk_lvs` READS the
    datatype `def_gds_port_power_restore` writes; when the two disagreed about
    which names are metals, every label on a `Metal<n>` PDK landed on the
    catch-all the consumer binds to m1 alone."""
    m = KLVS._METAL_RE.match(name)
    assert PWR.metal_index(name) == (int(m.group(1)) if m else 0)


def test_the_routing_order_is_not_used_as_a_fallback():
    """A measured negative result, kept so it is not "improved" back in:
    sky130's tech LEF declares `li1` TYPE ROUTING, so met1's POSITION in the
    routing order is 2 while the datatype contract numbers it 1."""
    assert PWR.metal_index("met1") == 1
    assert PWR.metal_index("li1") == 0, (
        "li1 resolving to a metal index means positions leaked in")


# ── 3. the third, quiet instance: the SPECIALNETS scan ──────────────────────
_RAILS = """\
DESIGN chip ;
UNITS DISTANCE MICRONS 1000 ;
SPECIALNETS 2 ;
- VDD ( * VDD )
  + ROUTED {m1} 800 + SHAPE FOLLOWPIN ( 0 5000 ) ( 145000 * )
  NEW {m4} 1600 ( 2240 0 ) ( 2240 145000 )
  + USE POWER ;
- VSS ( * VSS )
  + ROUTED {m1} 800 + SHAPE FOLLOWPIN ( 0 0 ) ( 145000 * )
  NEW {m4} 1600 ( 24640 0 ) ( 24640 145000 )
  + USE GROUND ;
END SPECIALNETS
END DESIGN
"""


def test_rails_are_found_on_a_metal_n_pdk():
    """Before #613 this returned {} — no marker painted, follow-pin rails left
    physically disjoint — with nothing in any report saying so."""
    rails = PWR.parse_power_rails(_RAILS.format(m1="Metal1", m4="Metal4"))
    assert set(rails) == {"VDD", "VSS"}
    assert {s[5] for segs in rails.values() for s in segs} == {"Metal1", "Metal4"}


def test_the_met_n_pdk_is_unchanged():
    """THE ACCEPT CASE — the generalised scan must read the old naming
    identically, segment for segment."""
    old = PWR.parse_power_rails(_RAILS.format(m1="MET1", m4="MET4"))
    new = PWR.parse_power_rails(_RAILS.format(m1="Metal1", m4="Metal4"))
    assert [len(v) for v in old.values()] == [len(v) for v in new.values()] == [2, 2]


def test_the_strap_exclusion_survives_the_generalisation():
    """The follow-pin minimum is what keeps an upper-metal strap from painting a
    marker that projects down onto every signal beneath it (a measured 87 false
    shorts). It must still pick the LOWEST metal, on either naming."""
    rails = PWR.parse_power_rails(_RAILS.format(m1="Metal1", m4="Metal4"))
    idx = [PWR.metal_index(s[5]) for segs in rails.values() for s in segs]
    assert min(idx) == 1
    assert sum(1 for i in idx if i != 1) == 2


def test_a_segment_whose_layer_does_not_resolve_is_dropped_not_guessed():
    """A generic layer token had to be read to reach `metal_index`, so the scan
    can now SEE tokens it must not accept — `MASK 2 ( … ) ( … )` is DEF syntax,
    not a rail."""
    d = _RAILS.format(m1="Metal1", m4="Metal4").replace(
        "NEW Metal4 1600 ( 2240 0 ) ( 2240 145000 )",
        "NEW MASK 2 ( 2240 0 ) ( 2240 145000 )")
    rails = PWR.parse_power_rails(d)
    assert all(PWR.metal_index(s[5]) for segs in rails.values() for s in segs)
    assert len(rails["VDD"]) == 1


# ── the restore refuses rather than binding everything to the catch-all ─────
def test_restore_refuses_when_no_pin_layer_resolves(tmp_path, capsys):
    """LOAD-BEARING. datatype 0 is consumed as "this label is on m1"; for a pin
    above m1 that names nothing or names a foreign net. When NOT ONE name
    resolves there is no way to tell which, so the honest outcome is a refusal
    — not a GDS that looks labelled."""
    dp = tmp_path / "x.def"
    dp.write_text(_def("chip", ["a", "b"], layer="TopMetal1"), encoding="utf-8")
    rc = PWR.restore(str(tmp_path / "in.gds"), str(dp),
                     str(tmp_path / "out.gds"))
    assert rc == 4, rc
    assert "TopMetal1" in capsys.readouterr().err
    assert not (tmp_path / "out.gds").exists(), "the GDS was rewritten anyway"


def test_the_refusal_does_not_fire_when_the_names_resolve(tmp_path, capsys):
    """THE ACCEPT CASE. A DEF whose pin layer names RESOLVE must get PAST the
    DEF-level refusal and go on to do the work.

    THE PREMISE THIS TEST SHIPPED WITH WAS FALSE, and the correction is the
    input, not the claim. It asserted the run reached "the pya-absent
    disclosure (rc 3)" — a statement about the HOST, not about the DEF — and it
    arranged for that by naming a GDS that does not exist. Everywhere KLayout
    is installed the run got as far as `pya.Layout().read()` and raised instead,
    so the assertion below was never evaluated at all. See `_seed_layout`.

    The invariant is unchanged and now actually reached: rc 4 is the refusal,
    `Metal2` resolves through `metal_index`, so rc 4 is not what comes back and
    the REFUSED line is not printed. Where KLayout is present the call runs to
    completion; where it is not it stops at the disclosure. Neither is 4, which
    is the whole claim, and the claim is now measured in both."""
    dp = tmp_path / "x.def"
    dp.write_text(_def("chip", ["a"], layer="Metal2"), encoding="utf-8")
    gds_in = tmp_path / "in.gds"
    _seed_layout(gds_in)
    rc = PWR.restore(str(gds_in), str(dp), str(tmp_path / "out.gds"))
    err = capsys.readouterr().err
    assert rc != 4, "a resolvable Metal<n> name was refused"
    assert "REFUSED" not in err, err


# ── the census: per structure, by name, paired by the design's own name ─────
def test_a_top_with_no_labels_is_found_even_though_the_library_has_plenty(tmp_path):
    """The exact #613 shape, and why the count is PER STRUCTURE: the library
    carries the leaf cell's own pin texts, so a library-wide count is non-zero
    for a top cell with none."""
    p = _project(tmp_path, "chip", ["a", "b", "c"], top_labels=())
    rc, out, rep = _run(p)
    assert rc == 1, out
    f = rep["files"][0]
    assert f["verdict"] == "NO_LABELS"
    assert f["top_labels"] == 0 and f["labels_total_in_library"] == 2
    assert "cannot pin-match" in f["reason"]


def test_a_fully_labelled_top_passes(tmp_path):
    p = _project(tmp_path, "chip", ["a", "b", "c"], top_labels=("a", "b", "c"))
    rc, out, rep = _run(p)
    assert rc == 0, out
    assert rep["files"][0]["verdict"] == "OK"


def test_a_missing_label_is_named_not_merely_counted(tmp_path):
    """A count says how many are unnamed; the name says which port to look at."""
    p = _project(tmp_path, "chip", ["a", "b", "c"], top_labels=("a", "c"))
    rc, _out, rep = _run(p)
    assert rc == 1
    f = rep["files"][0]
    assert f["verdict"] == "MISSING_LABELS"
    assert f["missing_labels"] == ["b"]


def test_a_naming_convention_difference_is_reported_as_one(tmp_path):
    """Both directions, so `VDD!` labels for `VDD` pins read as a convention
    mismatch instead of sending the reader after a missing label."""
    p = _project(tmp_path, "chip", ["VDD", "VSS"], top_labels=("VDD!", "VSS!"))
    rc, _out, rep = _run(p)
    assert rc == 1
    f = rep["files"][0]
    assert f["missing_labels"] == ["VDD", "VSS"]
    assert f["labels_matching_no_pin"] == ["VDD!", "VSS!"]
    assert "convention" in f["reason"]


def test_a_declared_but_unplaced_pin_is_disclosed_and_never_blocks(tmp_path):
    """A pin in the `PINS n ;` header with no placement has no geometry to
    attach a label to. Counting it as missing would fail a design for a defect
    it does not have."""
    p = _project(tmp_path, "chip", ["a", "b"], top_labels=("a", "b"),
                 declared=5)
    rc, out, rep = _run(p)
    assert rc == 0, out
    f = rep["files"][0]
    assert f["pins_declared"] == 5 and f["pins_placed"] == 2
    assert f["pins_unplaceable"] == 3
    assert "cannot be labelled" in out


def test_a_def_that_does_not_describe_this_gds_is_not_measured(tmp_path):
    """sha256's pnr dir holds DEFs for TWO designs — `chip_top` and `sha256` —
    and the sign-off GDS is `sha256`. Taking "the routed DEF" would compare
    chip_top's pins against a GDS that does not contain chip_top and call the
    answer zero. Pairing is by the DEF's own `DESIGN <name> ;`."""
    p = _project(tmp_path, "chip", ["a"], top_labels=())
    (p / "phase3" / "stage3" / "pnr" / "routed.def").write_text(
        _def("some_other_design", ["a"]), encoding="utf-8")
    rc, out, rep = _run(p)
    assert rc == CEN.RC_CANNOT_MEASURE, out
    assert rep["files"][0]["verdict"] == "NOT_MEASURED"
    assert "VACUOUS_PASS" in out


def test_the_right_def_is_picked_when_several_are_offered(tmp_path):
    """THE ACCEPT CASE of the pairing: the wrong-design DEF beside the right one
    must not suppress the measurement."""
    p = _project(tmp_path, "chip", ["a", "b"], top_labels=("a", "b"))
    (p / "phase3" / "stage3" / "pnr" / "chip_top.def").write_text(
        _def("chip_top", ["z"]), encoding="utf-8")
    rc, out, rep = _run(p)
    assert rc == 0, out
    assert rep["files"][0]["top_cell"] == "chip"


def test_a_project_with_no_gds_is_a_disclosed_skip(tmp_path):
    rc, out, _rep = _run(tmp_path)
    assert rc == CEN.RC_CANNOT_MEASURE
    assert out.lstrip().startswith("VACUOUS_PASS")


def test_a_gds_that_is_not_a_gds_is_not_a_design_finding(tmp_path):
    """Counting labels in a damaged stream counts an artefact of the damage.
    `gds_substance_check` owns that verdict; this one declines to add a second,
    wrong one."""
    p = _project(tmp_path, "chip", ["a"], top_labels=("a",))
    (p / "phase3" / "stage4" / "gds" / "chip.gds").write_bytes(b"not a gds")
    rc, _out, rep = _run(p)
    assert rc == CEN.RC_CANNOT_MEASURE
    assert "not a valid stream" in rep["files"][0]["reason"]


def test_the_two_walkers_agree_on_the_text_total():
    """`parse_gds` is the validity authority and keeps its own byte-exact walk;
    `iter_records` is the content reader. Two walks over one format is how the
    counts drift apart, so they are pinned to each other."""
    data = build_gds("chip", ("a", "b", "c"))
    _f, st = GSC.parse_gds(data)
    cen = GSC.structure_text_census(data)
    assert sum(cen.text_per_structure.values()) == st.element_breakdown["TEXT"]


def test_the_top_cell_is_the_one_nothing_references():
    data = build_gds("chip", ("a",))
    cen = GSC.structure_text_census(data)
    assert cen.top_structures() == ["chip"]
    assert set(cen.structures) == {"leafcell", "chip"}


# ── 1. the runner trigger is the measurement, not the PDK class ─────────────
class _Pdk:
    def __init__(self, cfg=None):
        self.port_label_restore = cfg


def _runner(monkeypatch, verdicts, restore=(True, "restored: 3 I/O labels")):
    """Drive `_restore_port_labels_if_missing` with a scripted census."""
    P = importlib.import_module("phase3_one_shot_runner")
    seq = list(verdicts)
    calls = []
    techs = []

    def fake_census(_gds, _def, pdk_tech=None):
        # Recorded, not ignored: whether the design's PDK tech reaches the
        # census is the readability half of the same measurement, and a stub
        # that swallowed it would let the argument go unpassed again (#631).
        techs.append(pdk_tech)
        return seq.pop(0)

    monkeypatch.setattr(P, "_resolve_magic_gds_tech",
                        lambda *_a, **_k: "/pdk/x-GDS.tech")

    def fake_restore(*_a, **kw):
        calls.append(kw.get("force"))
        return restore

    monkeypatch.setattr(P, "_port_label_census", fake_census)
    monkeypatch.setattr(P, "_klayout_restore_port_labels", fake_restore)
    return P, calls, techs


def test_a_missing_label_triggers_the_restore_with_no_config(tmp_path, monkeypatch):
    """The whole #613 ask: an OSS PDK with no `port_label_restore` config, whose
    streamed GDS is measurably unlabelled, must get the pass."""
    P, calls, techs = _runner(monkeypatch,
                       [{"verdict": "NO_LABELS", "reason": "0 labels"},
                        {"verdict": "OK"}])
    ok, note = P._restore_port_labels_if_missing(
        tmp_path, "chip", _Pdk(None), "c", tmp_path / "a.gds", tmp_path / "a.def")
    assert ok and calls == [True], note
    assert "MEASURED" in note


def test_a_labelled_gds_is_left_alone(tmp_path, monkeypatch):
    """THE ACCEPT CASE, and the reason sky130A runs are byte-identical: the pass
    must not rewrite a GDS that already names its ports."""
    P, calls, techs = _runner(monkeypatch, [{"verdict": "OK"}])
    ok, note = P._restore_port_labels_if_missing(
        tmp_path, "chip", _Pdk(None), "c", tmp_path / "a.gds", tmp_path / "a.def")
    assert not ok and calls == [], note
    assert "OK" in note
    assert techs == ["/pdk/x-GDS.tech"], (
        "the census was asked about labels without being told which layers the "
        "design's own extractor reads — the #631 wiring leak, one layer in")


def test_the_config_still_forces_the_pass(tmp_path, monkeypatch):
    """Backward compatibility: a PDK that declares the restore keeps getting it
    unconditionally, even where the census would not have asked for it."""
    P, calls, techs = _runner(monkeypatch, [{"verdict": "OK"}, {"verdict": "OK"}])
    ok, note = P._restore_port_labels_if_missing(
        tmp_path, "chip", _Pdk({"any": 1}), "c",
        tmp_path / "a.gds", tmp_path / "a.def")
    assert ok and calls == [True], note
    assert "declares port_label_restore" in note


def test_a_restore_that_did_not_fix_it_is_not_reported_as_restored(tmp_path,
                                                                  monkeypatch):
    """LOAD-BEARING. The pass RE-MEASURES; a restore that ran and left the top
    cell unnamed reading as "restored" is the defect wearing the fix's report."""
    P, _calls, _techs = _runner(monkeypatch,
                        [{"verdict": "NO_LABELS", "reason": "0 labels"},
                         {"verdict": "NO_LABELS", "reason": "still 0"}])
    ok, note = P._restore_port_labels_if_missing(
        tmp_path, "chip", _Pdk(None), "c", tmp_path / "a.gds", tmp_path / "a.def")
    assert not ok
    assert "RAN AND DID NOT FIX IT" in note


def test_labels_present_but_UNREADABLE_also_triggers_the_restore(tmp_path,
                                                                monkeypatch):
    """#631, the second half of #613's own argument.

    #613 established that a PDK CLASS predicts nothing and the readable fact is
    whether the labels are IN THE FILE. That argument applies to itself:
    PRESENCE predicts nothing either. A GDS whose 31 labels all sit on layer
    100 passes the presence census with `OK` and still extracts to a portless
    subckt, because the PDK's tech declares no layer 100 — which is exactly the
    state #630 measured on a real run, wearing a green report.

    So an `OK` verdict whose labels are measurably off every declared port
    layer must RE-RUN the restore, now with `--pdk-tech`, which writes them
    where the extractor looks.
    """
    P, calls, techs = _runner(
        monkeypatch,
        [{"verdict": "OK", "labels_extractor_readable": False},
         {"verdict": "OK", "labels_extractor_readable": True}])
    ok, note = P._restore_port_labels_if_missing(
        tmp_path, "chip", _Pdk(None), "c", tmp_path / "a.gds", tmp_path / "a.def")
    assert ok and calls == [True], note
    assert "no layer this PDK declares" in note, note


def test_an_UNKNOWN_readability_is_not_a_trigger(tmp_path, monkeypatch):
    """LOAD-BEARING, and the reason the predicate is three-state. When no tech
    resolved, the field is None — and re-running the restore on every design
    whose readability could not be established would rewrite the two shipped
    GDS that are byte-identical today, on no evidence at all."""
    P, calls, _t = _runner(
        monkeypatch, [{"verdict": "OK", "labels_extractor_readable": None}])
    ok, note = P._restore_port_labels_if_missing(
        tmp_path, "chip", _Pdk(None), "c", tmp_path / "a.gds", tmp_path / "a.def")
    assert not ok and calls == [], note


def test_an_unavailable_census_does_not_invent_a_verdict(tmp_path, monkeypatch):
    P, calls, techs = _runner(monkeypatch, [None])
    ok, note = P._restore_port_labels_if_missing(
        tmp_path, "chip", _Pdk(None), "c", tmp_path / "a.gds", tmp_path / "a.def")
    assert not ok and calls == []
    assert "census unavailable" in note


def test_the_pass_runs_on_both_streamout_engines():
    """Gating it on the KLayout path alone would make "which streamout ran"
    decide whether a sign-off GDS can be pin-matched. It is a post-streamout
    pass over the finished GDS, so it costs the Magic path nothing."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert code.count("_restore_port_labels_if_missing(") >= 3, (
        "the definition plus a call on each engine's branch")


# ── 3. the gate is in the flow, at the step the issue names ────────────────
def test_step_37_gates_on_port_labels():
    if not _FLOW.is_file():
        pytest.skip("flow file absent")
    d = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
    steps = [s for v in d.values() if isinstance(v, list)
             for s in v if isinstance(s, dict)]
    s37 = next(s for s in steps if s.get("id") == 37)
    cmds = [g.get("program_exit_zero", "") for g in s37["gate"]["all_of"]]
    assert any(c.startswith("gds_port_label_check") for c in cmds), cmds


def test_the_gate_is_reachable_through_the_flow_runner(tmp_path):
    """END TO END, through `flow_compliance_check`'s own invoker — a gate that
    only its own test runs is not wired."""
    FC = importlib.import_module("flow_compliance_check")
    p = _project(tmp_path, "chip", ["a", "b"], top_labels=())
    ok, ev = FC._check_program_exit_zero(
        p, "gds_port_label_check . --json reports/phase3/gds_port_labels.json")
    assert ok is False, ev
    assert "NO_LABELS" in str(ev)
