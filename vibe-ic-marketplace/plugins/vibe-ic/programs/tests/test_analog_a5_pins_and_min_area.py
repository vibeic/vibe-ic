"""A5 draws a macro's PINS, and leaves no gencell polygon below minimum area
(analog decision q2-pin-layer, and the M2.d lane).

MEASURED on u_hawaii_adc (ihp-sg13g2, vibeic-eda 0.3.79):

  * A5 labelled every declared port at a ZERO-AREA point on its metal2 rail.
    Magic moved each label onto the via under it, a point label writes no pin
    boundary to GDS, and the A8 abstract (`gds read` + `lef write`) came out
    with SIZE and OBS and ZERO pins on both blocks.
  * IHP's extra DRC deck failed Mn.d on both blocks: 20 (ldo) and 302
    (delta_sigma) Metal2 islands of 0.0812 / 0.058 um2 under 0.144 um2. Every
    one is the gencell's own UNLABELLED bottom gate contact, which the PDK's
    MOS generator carries to metal2 and this emitter never routed.

After the change, on the same blocks and image: 4 and 7 PINs (supplies on the
top strap pair's vertical layer, USE POWER/GROUND; signals on the lowest free
vertical layer, touching the bottom edge), and 0 Metal2 islands below the
minimum area in the flat GDS, with IHP's main + extra decks reporting no rule
the unchanged emitter did not already report.

These tests replay the producer through the fake stage the A5 suite already
uses (`test_analog_a5_layout_emit.FakeStage`), with a PDK tech LEF added, so
they run with no container. Every assertion reads the Magic SCRIPT the emitter
hands to the tool, or the record it writes, never an internal helper — so the
unchanged emitter answers them wrongly instead of failing to import.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

import analog_a5_layout_emit as A5E
import test_analog_a5_layout_emit as T

# A tech LEF shaped like a real one: a device contact before the first metal,
# alternating directions, and the DC current density the EM rule is read
# from. Generic names: nothing here is a PDK's.
TECH_LEF = """VERSION 5.8 ;
LAYER CONT
  TYPE CUT ;
END CONT
LAYER M1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.48 ;
  WIDTH 0.16 ;
  DCCURRENTDENSITY AVERAGE 1 ;
END M1
LAYER V1
  TYPE CUT ;
  DCCURRENTDENSITY AVERAGE 0.4 ;
END V1
LAYER M2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.48 ;
  WIDTH 0.2 ;
  DCCURRENTDENSITY AVERAGE 2 ;
END M2
LAYER V2
  TYPE CUT ;
  DCCURRENTDENSITY AVERAGE 0.4 ;
END V2
LAYER M3
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.48 ;
  WIDTH 0.2 ;
  DCCURRENTDENSITY AVERAGE 2 ;
END M3
LAYER V3
  TYPE CUT ;
  DCCURRENTDENSITY AVERAGE 0.4 ;
END V3
LAYER M4
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.48 ;
  WIDTH 0.2 ;
  DCCURRENTDENSITY AVERAGE 2 ; #mA/um
END M4
LAYER V4
  TYPE CUT ;
  DCCURRENTDENSITY AVERAGE 0.4 ;
END V4
LAYER M5
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.48 ;
  WIDTH 0.2 ;
  DCCURRENTDENSITY AVERAGE 2 ;
END M5
LAYER TV1
  TYPE CUT ;
  DCCURRENTDENSITY AVERAGE 1.4 ;
END TV1
LAYER TM1
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 2.28 ;
  WIDTH 1.64 ;
  DCCURRENTDENSITY AVERAGE 15 ;
END TM1
LAYER TV2
  TYPE CUT ;
END TV2
LAYER TM2
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 4 ;
  WIDTH 2 ;
END TM2
"""
LEF_PATH = "/pdk/x/libs.ref/lib/lef/x_tech.lef"

# CUT scalars are area density. At the fixture's painted .3um x .3um
# cuts these values express its intended .4/1.4mA individual-cut limits.
TECH_LEF = TECH_LEF.replace('DCCURRENTDENSITY AVERAGE 0.4 ;',
                          'DCCURRENTDENSITY AVERAGE 4.444444444444445 ;')
TECH_LEF = TECH_LEF.replace('DCCURRENTDENSITY AVERAGE 1.4 ;',
                          'DCCURRENTDENSITY AVERAGE 15.555555555555556 ;')

# The Metal2 minimum-area rule, in the deck grammar the emitter already reads.
DRC_TECH = T.DRC_TECH + ' area allm2 144000 200 "Metal2 area < %a (M2.d)"\n'
DRC_TECH += ''.join(f' width v{k}/m{k} 300 "Via{k} minimum cut width"\n' for k in range(1,7))

# THE MEASURED SHAPE, in the fake PDK: a MOS child with a gate contact at BOTH
# ends of the gate, each carried to metal2 through its own via1, and only the
# TOP one labelled. The bottom one's metal2 is 28 x 30 lambda = 840 lambda2
# against a 1440 lambda2 (0.144 um2) rule.
ISLAND = (-14, -87, 14, -57)            # lambda, child coordinates
FLOATING_CHILD = T.CHILD_MAG.replace(
    "<< polycont >>\nrect -20 128 20 160\n",
    "<< polycont >>\nrect -20 128 20 160\nrect -20 -160 20 -128\n"
    "<< via1 >>\nrect -20 -160 20 -128\n"
    "<< metal2 >>\nrect -28 -174 28 -160\nrect -28 -128 28 -114\n"
    "rect -28 -160 -20 -128\nrect 20 -160 28 -128\n")

NETLIST = (".subckt blk vp vn a y\n"
           "xm1 y a vn vn xx_lv_nmos w=1u l=0.5u\n"
           "xm2 vp a y vn xx_lv_nmos w=1u l=0.5u\n"
           ".ends\n")
PORTS = ["vp", "vn", "a", "y"]


class LefStage(T.FakeStage):
    """The A5 suite's fake stage, plus the PDK's tech LEF."""

    def __init__(self, *, lef=True, **kw):
        super().__init__(**kw)
        self._lef = lef

    def sh(self, cmd, timeout=900):
        if cmd.startswith("ls -1 ") and "libs.ref" in cmd:
            self.commands.append(cmd)
            return (0, LEF_PATH + "\n", "") if self._lef else (2, "", "")
        if cmd.startswith("cat ") and cmd.split(None, 1)[1].strip(
                "'\"").endswith(".lef"):
            self.commands.append(cmd)
            return (0, TECH_LEF, "") if self._lef else (1, "", "no")
        if cmd.startswith("cat ") and cmd.split(None, 1)[1].strip(
                "'\"").endswith("-drc.tech"):
            self.commands.append(cmd)
            return 0, DRC_TECH, ""
        return super().sh(cmd, timeout)


def _project(tmp_path: Path, current_ma=1.0) -> Path:
    project = T._project(tmp_path, NETLIST)
    blk = project / "phase3" / "analog" / "blk"
    (blk / "topology.json").write_text(json.dumps(
        {"ports": PORTS, "rails": {"vdd": "vp", "vss": "vn"}}))
    specs = [{"name": "vout", "target": 1.2, "unit": "V"}]
    if current_ma is not None:
        specs.append({"name": "iout", "target": current_ma / 2,
                      "max": current_ma, "unit": "mA"})
    (blk / "spec.json").write_text(json.dumps({"specs": specs}))
    return project


def _emit(tmp_path, monkeypatch, stage, current_ma=1.0):
    project = _project(tmp_path, current_ma)
    rc, doc = T._run(monkeypatch, project, stage)
    script = stage.scripts.get("a5layout_blk.tcl", "")
    return rc, doc.get("blocks", {}).get("blk", {}), script


def _pin_labels(script: str) -> dict:
    """{net: {box, layer, then}} for every label the script writes, with the
    three lines that follow it."""
    lines = script.splitlines()
    out = {}
    for i, line in enumerate(lines):
        m = re.match(r"^label (\S+) FreeSans \S+ \S+ \S+ \S+ \S+ (\S+)$", line)
        if not m or i == 0:
            continue
        box = [int(v) for v in lines[i - 1].split()[1:5]] \
            if lines[i - 1].startswith("box ") else None
        out[m.group(1)] = {"box": box, "layer": m.group(2),
                           "then": lines[i + 1:i + 4]}
    return out


def _paints(script: str) -> list:
    """[(layer, (x1, y1, x2, y2))] for every `box` + `paint` pair."""
    out, pending = [], None
    for line in script.splitlines():
        tok = line.split()
        if len(tok) == 5 and tok[0] == "box":
            pending = tuple(int(v) for v in tok[1:])
        elif len(tok) == 2 and tok[0] == "paint" and pending:
            out.append((tok[1], pending))
    return out


# ══ every declared port is a RECTANGLE on the layer the PDK gives it ══════════
def test_every_declared_port_is_a_rectangle_on_its_pin_layer(tmp_path,
                                                             monkeypatch):
    """Supplies on the vertical layer of the top strap pair (M6 here), signals
    on the lowest vertical layer above the routing that is no strap layer
    (M4), each a box with AREA, followed by the port index, class and use."""
    rc, rep, script = _emit(tmp_path, monkeypatch, LefStage())
    assert rc == A5E.RC_OK, rep
    labels = _pin_labels(script)
    want = {"vp": ("metal6", "power"), "vn": ("metal6", "ground"),
            "a": ("metal4", "signal"), "y": ("metal4", "signal")}
    got = {}
    for net, (layer, use) in want.items():
        lab = labels.get(net, {})
        box = lab.get("box") or [0, 0, 0, 0]
        got[net] = (lab.get("layer"), box[2] > box[0] and box[3] > box[1],
                    lab.get("then"))
    assert got == {
        net: (layer, True, [f"port make {PORTS.index(net) + 1}",
                            "port class inout", f"port use {use}"])
        for net, (layer, use) in want.items()}, got


def test_a_signal_pin_touches_the_bottom_and_a_supply_spans_the_block(
        tmp_path, monkeypatch):
    """A router reaches a pin of a `-hide` abstract only at the boundary, and
    a strap crosses a supply only if it spans the block."""
    rc, rep, script = _emit(tmp_path, monkeypatch, LefStage())
    paints = _paints(script)
    bottom = min(b[1] for _l, b in paints)
    top = max(b[3] for _l, b in paints)
    labels = _pin_labels(script)
    boxes = {n: (labels.get(n) or {}).get("box") or [1, 1, 1, 1]
             for n in PORTS}
    assert [boxes["a"][1], boxes["y"][1]] == [bottom, bottom], boxes
    assert [boxes["vp"][3], boxes["vn"][3]] == [top, top], (boxes, top)


def test_the_pins_are_sized_by_the_declared_current_and_the_lef_em_rule(
        tmp_path, monkeypatch):
    """1.0 mA declared; the tech LEF's DCCURRENTDENSITY gives 2 mA/um on the
    signal layer and area density equivalent to 0.4 mA per painted cut:
    a strip at
    least 0.5 um wide and 3 cuts per via level, and the record names the rule
    it used."""
    rc, rep, script = _emit(tmp_path, monkeypatch, LefStage())
    pins = {p["net"]: p for p in rep.get("pins", [])}
    y = pins.get("y", {})
    assert (y.get("width_um", 0) >= 0.5, y.get("cuts_per_via", 0) >= 3,
            "DCCURRENTDENSITY" in str((y.get("em") or {}).get("rule")),
            (y.get("em") or {}).get("current_mA")) == (True, True, True, 1.0), y
    assert pins.get("vp", {}).get("cuts_per_via", 0) >= 3, pins
    # and the script DRAWS them: three via2 squares in the signal pin's stack
    lab = (_pin_labels(script).get("y") or {}).get("box") or [0, 0, 0, 0]
    via2 = [b for l, b in _paints(script) if l == "via2"
            and lab[0] - 200 <= b[0] <= lab[2] + 200]
    assert len(via2) >= 3, via2


def test_without_a_declared_current_the_pin_is_minimum_width_and_says_so(
        tmp_path, monkeypatch):
    rc, rep, _s = _emit(tmp_path, monkeypatch, LefStage(), current_ma=None)
    pins = {p["net"]: p for p in rep.get("pins", [])}
    assert (pins.get("y", {}).get("em") or {}).get("result") == \
        "NOT_MEASURED", pins


def test_without_a_tech_lef_no_pin_layer_is_guessed(tmp_path, monkeypatch):
    """No tech LEF: the record says the pins were NOT DETERMINED, and no port
    is labelled on a layer this program chose on its own."""
    rc, rep, script = _emit(tmp_path, monkeypatch, LefStage(lef=False))
    assert (rep.get("pins_basis") or {}).get("result") == "NOT_DETERMINED", rep
    assert not [l for l in _pin_labels(script).values()
                if l["layer"] in ("metal4", "metal6")]


# ══ no gencell polygon is left below the deck's minimum area ═════════════════
def _island_component_area(script: str, origin) -> int:
    """The area of the Metal2 polygon the unlabelled gate contact ends up in:
    the island as the gencell drew it, flood-filled through every metal2 the
    script paints. Rasterised in lambda over a window around the island."""
    ox, oy = origin
    ix1, iy1, ix2, iy2 = (ISLAND[0] + ox, ISLAND[1] + oy,
                          ISLAND[2] + ox, ISLAND[3] + oy)
    R = 200
    wx, wy = ix1 - R, iy1 - R
    size = (ix2 - ix1) + 2 * R
    grid = [[False] * (size + 1) for _ in range(size + 1)]
    rects = [(ix1, iy1, ix2, iy2)] + [b for l, b in _paints(script)
                                       if l == "metal2"]
    for (x1, y1, x2, y2) in rects:
        for x in range(max(x1, wx), min(x2, wx + size)):
            for y in range(max(y1, wy), min(y2, wy + size)):
                grid[x - wx][y - wy] = True
    seen, stack = set(), [((ix1 + ix2) // 2 - wx, (iy1 + iy2) // 2 - wy)]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        x, y = p
        if not (0 <= x < size and 0 <= y < size) or not grid[x][y]:
            continue
        seen.add(p)
        stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return len(seen)


def _device_origin(script: str) -> tuple:
    """Where the first device's child lands: the box the gencell was called
    at, plus the placement the probe block measured."""
    lines = script.splitlines()
    i = next(k for k, l in enumerate(lines) if l.startswith("magic::gencell"))
    bx, by = (int(v) for v in lines[i - 1].split()[1:3])
    tx, ty = A5E._gl.parse_use_transforms(T.PROBE_MAG)["p0"]
    return bx + int(tx), by + int(ty)


def test_an_unrouted_gate_contact_is_brought_to_the_minimum_area(
        tmp_path, monkeypatch):
    """THE M2.d DEFECT. The bottom gate contact's metal2 is 840 lambda2; the
    polygon it sits in once the layout is drawn must hold 1440."""
    rc, rep, script = _emit(tmp_path, monkeypatch,
                            LefStage(child=FLOATING_CHILD))
    assert rc == A5E.RC_OK, rep
    area = _island_component_area(script, _device_origin(script))
    assert area >= 1440, area


def test_the_island_census_is_recorded_with_what_became_of_each(
        tmp_path, monkeypatch):
    rc, rep, _s = _emit(tmp_path, monkeypatch, LefStage(child=FLOATING_CHILD))
    f = rep.get("floating_device_metal") or {}
    assert (f.get("below_min_area"), f.get("left"),
            f.get("grown", 0) + f.get("bridged", 0)
            + f.get("joined", 0)) == (2, 0, 2), f
    assert {p["net"] for p in f.get("patches", [])} == {"a"}, f


def test_a_child_with_nothing_unrouted_gets_no_patch(tmp_path, monkeypatch):
    """The control: the plain child has no unlabelled metal, so nothing is
    painted for it and the census says it examined the devices."""
    rc, rep, _s = _emit(tmp_path, monkeypatch, LefStage())
    f = rep.get("floating_device_metal") or {}
    assert (f.get("examined"), f.get("below_min_area"), f.get("patches")) \
        == (2, 0, []), f
