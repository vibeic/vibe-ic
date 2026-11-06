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
        body += _text_element(100, 1, 1000 * (i + 1), 2000, s)
    return (_rec(0x0002, struct.pack(">h", 600))
            + _rec(0x0102, b"\x00" * 24)
            + _rec(0x0206, _name("LIB"))
            + _rec(0x0305, _gds_real8(0.001) + _gds_real8(1e-9))
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


# SPM1200: actual DEF PORT/FIXED grammar and real GDS UNITS/XY, neutral names.
def _gds_real8(value):
    exponent = 64
    while value and value < 1 / 16:
        value *= 16
        exponent -= 1
    while value >= 1:
        value /= 16
        exponent += 1
    return bytes([exponent]) + int(value * 2**56).to_bytes(7, 'big')


def _witness_input(tmp_path, status='FIXED', xy=(1000, 2000), label='a',
                   orientation='N', units=2000, gds_unit=1e-9):
    # DEF anchor (2000,4000) DBU = (1,2) um. Offset rectangle forces
    # orientation semantics to matter instead of a symmetric box hiding them.
    dp = tmp_path / 'routed.def'
    dp.write_text('VERSION 5.8 ;\nDESIGN chip ;\n'
        + (f'UNITS DISTANCE MICRONS {units} ;\n' if units else '') +
        'PINS 1 ;\n - a + NET a + DIRECTION INPUT\n + PORT\n'
        ' + LAYER Metal5 ( -100 -100 ) ( 100 100 )\n'
        + (f' + {status} ( 2000 4000 ) {orientation} ;\n' if status else ';\n') +
        'END PINS\nEND DESIGN\n')
    body = _boundary(81)
    if label: body += _text_element(81, 10, *xy, label)
    gp = tmp_path / 'chip.gds'
    gp.write_bytes(_rec(0x0002, struct.pack('>h', 600)) + _rec(0x0102,b'\0'*24)
        + _rec(0x0206,_name('LIB')) + _rec(0x0305, _gds_real8(0.001)+_gds_real8(gds_unit))
        + _structure('chip',body) + _rec(0x0400))
    return gp,dp
