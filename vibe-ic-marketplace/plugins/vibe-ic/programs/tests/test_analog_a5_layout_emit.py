"""Unit tests for `analog_a5_layout_emit` — A5's producer.

The program shells out to Magic inside an EDA container. These tests do NOT
need one: `Stage.sh` / `Stage.put_text` / `Stage.get` are the seam, and a fake
stage stands in for the container, replaying PDK text and gencell output that
was CAPTURED from a real PDK. The one thing a fake can never prove — that
Magic really draws these devices — was measured separately, and the numbers
are quoted where they matter.

The contract has five invariants and every one of them has an arm here:

  A (I1)  a legal geometry the emitter has never drawn before is DRAWN. This
          is the arm that matters: an emitter that refuses everything also
          refuses the bug.
  B (I2)  a sub-minimum geometry is refused BY NAME, with the rule and the
          FILE, before any probe — never as an AssertionError tuple.
  C (I3)  the bulk-tap search covers the WHOLE structure on the PDK's grid
          and takes the maximum, not the first hit of a ladder.
  D (I4)  a shortfall is DRAWN and RECORDED as a structured deviation naming
          the adjudicator; it is never a refusal and never a silent pass.
  E (I5)  an unreachable tool or PDK is ENV_UNAVAILABLE with the thing NAMED
          and a non-zero exit, and no layout.mag is written.
"""
from __future__ import annotations

import json
import re
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

import analog_a5_layout_emit as A5E
import analog_a5_pdk_device_limits as A5L


# ── PDK text, captured from a real magic PDK ─────────────────────────────
# Two gencell blocks for one model, so `fet_limits`' min-across-blocks rule is
# exercised: the PDK permits 0.13, and taking the LAST match would refuse a
# legal 0.13 um device.
FET_TCL = """
proc pdkns::xx_lv_nmos_defaults {} {
    return {w 0.35 l 0.13 m 1 nf 1 diffcov 100 \\
\t\ttopc 1 botc 1 poverlap 0 doverlap 1 lmin 0.13 wmin 0.15 \\
\t\tclass mosfet guard 1 glc 1 doports 1}
}
proc pdkns::xx_hv_nmos_defaults {} {
    return {w 0.35 l 0.45 m 1 nf 1 diffcov 100 \\
\t\ttopc 1 botc 1 poverlap 0 doverlap 1 lmin 0.45 wmin 0.15 \\
\t\tclass mosfet guard 1 glc 1 doports 1}
}
"""
RES_TCL = """
proc pdkns::rr_defaults {} {
    return {w 0.50 l 2.00 m 1 nx 1 wmin 0.50 lmin 0.50 class resistor \\
\t\tguard 1 doports 1}
}
"""
DRC_TECH = """
 width  m1  180  "Metal1 width < 0.18um (rule M1.a)"
 spacing m1 m1 180 touching_ok \\
\t"Metal1 spacing < 0.18um (rule M1.b)"
"""

# The technology file's LAYER TABLE — the shape a magic PDK ships, with this
# fake PDK's own type names. It is a required PDK read (`read_pdk`), because
# which conductor plane a drawn type occupies is the PDK's answer and not a
# spelling convention: `pdkcapcontact` below is a contact from a capacitor
# plate to metal3, and nothing in its NAME says so.
MAGIC_TECH = """
tech
 format 33
 pdktech
end

planes
 well,w
 active,a
 metal1,m1
 metal2,m2
 cap1,c1
 metal3,m3
end

types
 well nwell,nw
 active pdiff,pd
 active pdiffc,pdc
 active nsubdiff,nsd
 active nsubdiffcont,nsc,nsubdiffc
 active pdksubcont,pdksc
 active poly,p
 active polycont,pc
 metal1 metal1,m1,met1
 metal1 via1,v1
 -metal1 m1fill
 metal2 metal2,m2,met2
 metal3 metal3,m3,met3
 cap1 pdkcap,pcap
 cap1 pdkcapcontact,pdkcapc,pdkcc
end

contact
 nsc      nsubdiff   metal1
 pdc      pdiff      metal1
 pdksc    nsubdiff   metal1
 pc       poly       metal1
 via1     metal1     metal2
 pdkcc    pdkcap     metal3
 stackable
end
"""

# One gencell child, exactly the shape Magic writes: `magscale 1 2` so the
# rectangles are internal units, `rlabel` coordinates internal regardless,
# a four-bar guard ring on a contact type, and four ports.
CHILD_MAG = """magic
tech pdktech
magscale 1 2
timestamp 1
<< nsubdiffcont >>
rect -128 202 128 234
rect -206 -156 -174 156
rect 174 -156 206 156
rect -128 -234 128 -202
<< pdiffc >>
rect -100 -60 -76 60
rect 76 -60 100 60
<< polycont >>
rect -20 128 20 160
<< labels >>
rlabel nsubdiffcont 0 -218 0 -218 0 B
port 1 nsew
rlabel pdiffc -88 0 -88 0 0 D
port 2 nsew
rlabel pdiffc 88 0 88 0 0 S
port 3 nsew
rlabel polycont 0 144 0 144 0 G
port 4 nsew
<< properties >>
string FIXED_BBOX -190 -218 190 218
<< end >>
"""

# A device whose guard ring is genuinely too tight for the tap clearance
# floor: every position on the ring is level with a terminal contact. This is
# the geometry arm D needs, and it is a SEPARATE fixture rather than a lowered
# floor, because lowering the floor to produce a deviation would prove
# nothing about the floor.
TIGHT_CHILD = """magic
tech pdktech
magscale 1 2
timestamp 1
<< pdksubcont >>
rect -106 -60 -90 0
rect -106 0 -90 60
rect 90 -60 106 60
<< pdiffc >>
rect -52 -30 -28 30
rect 28 -30 52 30
<< polycont >>
rect -8 32 8 48
<< labels >>
rlabel pdksubcont 0 -68 0 -68 0 B
port 1 nsew
rlabel pdiffc -40 0 -40 0 0 D
port 2 nsew
rlabel pdiffc 40 0 40 0 0 S
port 3 nsew
rlabel polycont 0 40 0 40 0 G
port 4 nsew
<< properties >>
string FIXED_BBOX -106 -60 106 60
<< end >>
"""

PROBE_MAG = """magic
tech pdktech
magscale 1 2
timestamp 1
<< checkpaint >>
rect 0 0 1 1
use childcell  p0
timestamp 1
transform 1 0 190 0 1 218
box -190 -218 190 218
<< end >>
"""

SCALE_LINE = "A5SCALE 200000 1 2\n"


def _mag_from_script(script: str) -> str:
    """The `.mag` Magic would have written for this layout script.

    A fake cannot draw, but it CAN reflect faithfully: every `magic::gencell`
    becomes the cell instance Magic creates for it, and every `box`+`paint`
    pair becomes the rectangle it paints. That is enough for the A5 gate,
    which is a text parse over exactly those two things."""
    out = ["magic", "tech pdktech", "timestamp 1", "<< checkpaint >>"]
    pending = None
    for line in script.splitlines():
        tok = line.split()
        if not tok:
            continue
        if tok[0] == "box" and len(tok) == 5:
            pending = tok[1:]
        elif tok[0] == "paint" and pending:
            out.append("rect " + " ".join(pending))
        elif line.startswith("magic::gencell"):
            out += [f"use childcell  {tok[2]}", "timestamp 1",
                    "transform 1 0 0 0 1 0", "box 0 0 1 1"]
    out.append("<< end >>")
    return "\n".join(out) + "\n"


def test_internal_rail_anchors_are_not_top_level_labels():
    """Only declared pins may become Magic extraction interface metadata.

    The routing plan records rail anchors in ``plan.ports`` for geometry
    bookkeeping.  Magic promotes a top-cell label to an extracted subckt
    port, so emitting an undeclared anchor widens the A3 interface.  This
    checks only the metadata boundary; the native extraction still decides
    whether a physical open remains.  The declared-pin path remains covered
    by the pin tests below.
    """
    plan = A5E.Plan()
    plan.ports = [("nbias", 10, 20)]
    plan.port_nets = ["vdd", "vss", "vref", "vout"]
    script = A5E.layout_tcl("blk", plan, "/stage")
    assert "label nbias " not in script
    assert "port make" not in script


def test_body_tap_contact_is_derived_from_tech_residues():
    """The body tap must use the PDK's local-to-metal1 contact.

    The Sky130 body label is on a device-contact layer, not on metal1.  A
    guessed via stack leaves the extracted B terminals on ``d9/B``; this
    control requires the producer to derive the bridge from the technology
    contact table and to refuse the answer when that bridge is absent.
    """
    class Layers:
        connects = {
            "viali": ("locali", "metal1"),
            "via1": ("metal1", "metal2"),
        }
        plane_of = {"locali": "locali", "metal1": "metal1",
                    "metal2": "metal2"}
        canon = {"li": "locali", "m1": "metal1"}
        contact_heads = [("mcon", ("li", "m1"))]

    class NoBridge:
        connects = {"via1": ("metal1", "metal2")}
        plane_of = Layers.plane_of

    assert A5E.body_tap_contact_layer(Layers()) == "viali"
    assert A5E.body_tap_metal_contact_layer(Layers()) == "mcon"
    assert A5E.body_tap_local_layer(Layers()) == "locali"
    assert A5E.body_tap_contact_layer(NoBridge()) is None
    assert A5E.body_tap_metal_contact_layer(NoBridge()) is None
    assert A5E.body_tap_local_layer(NoBridge()) is None


def test_direct_m1_body_tap_uses_declared_ring_residue(tmp_path, monkeypatch):
    """A gencell contact that already reaches Metal1 needs no bridge tile.

    The fixture's ``nsc nsubdiff metal1`` declaration is the authority: the
    ring contact itself carries the body to M1.  The producer must therefore
    suppress the locali-to-M1 shortfall without naming that contact or
    inventing a PDK-specific alias.  A missing M1 residue remains a real
    shortfall (the negative assertion below).
    """
    layers = A5L.layer_identity(MAGIC_TECH, "MAGIC_TECH fixture")
    cell = A5E.parse_cell(CHILD_MAG, layers)
    ring = A5E.ring_layer_of(cell)
    assert ring == "nsubdiffcont"
    assert A5E.body_tap_direct_m1_layer(layers, ring) == ring

    class MissingM1:
        canon = {"ring": "ring", "active": "active", "locali": "locali"}
        connects = {"ring": ("active", "locali")}
        plane_of = {"ring": "active", "active": "active",
                    "locali": "locali"}

    assert A5E.body_tap_direct_m1_layer(MissingM1(), "ring") is None

    project = _project(
        tmp_path,
        ".subckt blk d g s b\nxm1 d g s b xx_lv_nmos w=1u l=0.5u\n.ends\n",
    )
    rc, doc = _run(monkeypatch, project, FakeStage())
    rep = doc["blocks"]["blk"]
    assert rc == A5E.RC_OK, doc
    assert rep["result"] == "OK", rep
    assert rep["bulk_tap"]["examined"] == 1
    assert not [d for d in rep["deviations"]
                if d["quantity"] == "body_tap_contact_layer"]


class FakeStage:
    """Stands in for the container, and records what was asked of it."""

    def __init__(self, *, magic=True, pdk=True, drc=True, tech=True,
                 open_ok=True, layout=True, child=None):
        self._child = child or CHILD_MAG
        self.path = "/stage"
        self.host_tmp = None
        self._magic, self._pdk, self._drc = magic, pdk, drc
        self._tech = tech
        self._open_ok, self._layout = open_ok, layout
        self.scripts: dict = {}
        self.commands: list = []

    def open(self):
        return (True, "") if self._open_ok else (False, "no container here")

    def put_text(self, text, name):
        self.scripts[name] = text
        return True, ""

    def get(self, name, dst):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        if name == "a5probe.mag":
            Path(dst).write_text(PROBE_MAG)
            return True, ""
        if name.endswith(".mag") and name != "layout.mag":
            Path(dst).write_text(self._child)
            return True, ""
        if name == "layout.mag":
            if not self._layout:
                return False, "no such file"
            Path(dst).write_text(_mag_from_script(
                self.scripts.get("__layout__", "")))
            return True, ""
        if name.endswith(".gds"):
            Path(dst).write_bytes(b"\x00\x06\x00\x02\x00\x258")
            return True, ""
        return False, "no such file"

    def sh(self, cmd, timeout=900):
        self.commands.append(cmd)
        if cmd.startswith("cd ") and "ls -1 *.mag" in cmd:
            return 0, "childcell.mag\nlayout.mag\n", ""
        if cmd.startswith("command -v magic"):
            return (0, "/bin/magic\n", "") if self._magic else (1, "", "")
        if cmd.startswith("cat "):
            path = cmd.split(None, 1)[1].strip("'\"")
            if path.endswith("-fet.tcl"):
                return (0, FET_TCL, "") if self._pdk else (1, "", "cat: no")
            if path.endswith("-drc.tech"):
                return (0, DRC_TECH, "") if self._drc else (1, "", "cat: no")
            if path.endswith(".tech"):
                return (0, MAGIC_TECH, "") if self._tech else (1, "", "cat: no")
            if path.endswith("-res.tcl"):
                return 0, RES_TCL, ""
            return 1, "", "cat: no such file"
        if cmd.startswith("ls "):
            return 0, "/pdk/x-fet.tcl /pdk/x-res.tcl\n", ""
        if "magic -dnull" in cmd:
            tag = re.search(r"(\S+)\.tcl$", cmd)
            name = tag.group(1) if tag else ""
            if name == "a5probe":
                return 0, SCALE_LINE + "A5_PROBE_OK\n", ""
            self.scripts["__layout__"] = self.scripts.get(f"{name}.tcl", "")
            return 0, "A5_LAYOUT_OK\n", ""
        return 0, "", ""

    def close(self):
        pass


class CielSky130Stage(FakeStage):
    """A Ciel sky130A tree: consolidated Tcl/tech filenames only."""

    TECH_LEF = """VERSION 5.8 ;
LAYER met1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  PITCH 0.48 ;
  WIDTH 0.14 ;
  DCCURRENTDENSITY AVERAGE 1 ;
END met1
LAYER via1
  TYPE CUT ;
END via1
LAYER met2
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  PITCH 0.48 ;
  WIDTH 0.14 ;
  DCCURRENTDENSITY AVERAGE 1 ;
END met2
"""
    CIEL_TECH = (
        DRC_TECH + MAGIC_TECH
    )

    def sh(self, cmd, timeout=900):
        if cmd.startswith("cat "):
            path = cmd.split(None, 1)[1].strip("'\"")
            if path.endswith("sky130A-fet.tcl") or \
                    path.endswith("sky130A-drc.tech"):
                return 1, "", "cat: no such file"
            if path.endswith("/sky130A.tcl"):
                return 0, FET_TCL + RES_TCL, ""
            if path.endswith("/sky130A.tech"):
                return 0, self.CIEL_TECH, ""
            if path.endswith("sky130_fd_sc_hd__nom.tlef"):
                return 0, self.TECH_LEF, ""
        if cmd.startswith("ls "):
            if "techlef" in cmd:
                return 0, "/pdk/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef\n", ""
            return 0, "/pdk/sky130A/libs.tech/magic/sky130A.tcl\n", ""
        return super().sh(cmd, timeout)


def _project(tmp_path: Path, netlist: str, block: str = "blk") -> Path:
    d = tmp_path / "proj" / "phase3" / "analog" / block
    d.mkdir(parents=True)
    (d / f"{block}.sp").write_text(netlist)
    return tmp_path / "proj"


def _install(monkeypatch, stage: FakeStage):
    monkeypatch.setattr(A5E, "Stage", lambda container, host_tmp: (
        setattr(stage, "host_tmp", host_tmp) or stage))


def _run(monkeypatch, project: Path, stage: FakeStage, *extra):
    _install(monkeypatch, stage)
    out = project / "emit.json"
    rc = A5E.main([str(project), "--block", "blk", "--container", "c",
                   "--pdk-root", "/pdk", "--family", "x",
                   "--gencell-tcl", "/pdk/x-fet.tcl",
                   "--drc-tech", "/pdk/x-drc.tech",
                   "--json", str(out), *extra])
    return rc, json.loads(out.read_text()) if out.is_file() else {}


def test_default_ciel_resolver_uses_consolidated_pdk_files():
    stage = CielSky130Stage()
    facts, why = A5E.read_pdk(stage, "/pdk", "sky130A", None, None)
    assert facts is not None, why
    assert facts.sources["gencell_tcl"].endswith("/sky130A.tcl")
    assert facts.sources["drc_tech"].endswith("/sky130A.tech")
    assert facts.sources["tech_lef"].endswith("/sky130_fd_sc_hd__nom.tlef")
    assert facts.m1_space_um == 0.18


class _RealFilesystemStage:
    """Run resolver probes through a real bash filesystem, not canned output."""

    def __init__(self):
        self.commands = []

    def sh(self, cmd, timeout=120):
        self.commands.append(cmd)
        cp = subprocess.run(["bash", "-lc", cmd], capture_output=True,
                             text=True, timeout=timeout)
        return cp.returncode, cp.stdout, cp.stderr


@pytest.mark.parametrize("family", ["gf180mcuD", "gf180mcu"])
def test_ciel_tech_lef_glob_expands_on_real_filesystem(tmp_path, family):
    """A registry wildcard reaches bash and keeps sorted-first semantics."""
    pdk_root = tmp_path / "pdk root with spaces"
    root = (pdk_root / "ciel" / "gf180mcu" / "versions" / "v1"
            / "gf180mcuD" / "libs.ref" / "gf180mcu_fd_sc_mcu7t5v0"
            / "techlef")
    root.mkdir(parents=True)
    first = root / "gf180mcu_fd_sc_mcu7t5v0__nom.tlef"
    second = root / "zz__nom.tlef"
    first.write_text("VERSION 5.8 ;\n")
    second.write_text("VERSION 5.8 ;\n")
    stage = _RealFilesystemStage()

    got = A5E._resolved_tech_lef(stage, str(pdk_root), family)

    assert got == str(first)
    assert any("ls -1d " in c and "*__nom.tlef" in c
               for c in stage.commands), stage.commands


def test_pin_layers_align_lef_routing_with_magic_metal_identity():
    """Sky130's leading li1 does not become the writer's metal1 level."""
    lef = "\n".join(
        f"LAYER {name}\n TYPE ROUTING ;\n DIRECTION {direction} ;\n"
        f"END {name}"
        for name, direction in (
            ("li1", "VERTICAL"), ("met1", "HORIZONTAL"),
            ("met2", "VERTICAL"), ("met3", "HORIZONTAL"),
            ("met4", "VERTICAL"), ("met5", "HORIZONTAL")))
    magic = "\n".join(
        ["tech", "planes"]
        + [f"  metal{i},m{i},met{i}" for i in range(1, 6)]
        + ["end", "types"]
        + [f"  metal{i} m{i} met{i} metal{i}" for i in range(1, 6)]
        + ["end"])
    layers = A5L.layer_identity(magic, "Magic layer fixture")

    signal, supply, basis = A5E.pin_layers(
        A5E.tech_lef_layers(lef), [1, 2, 3, 4, 5], layers)

    assert basis["leading_non_magic_routing_layers"] == ["li1"]
    assert basis["routing_layers"] == ["met1", "met2", "met3", "met4", "met5"]
    assert (signal, supply) == (3, 4)
    assert basis["signal_layer"] == "met3"
    assert basis["supply_layer"] == "met4"


def test_pin_spec_metadata_uses_the_same_trimmed_lef_table():
    """LEF names in the record follow the Magic-aligned levels."""
    lef = "\n".join(
        f"LAYER {name}\n TYPE ROUTING ;\n DIRECTION {direction} ;\n"
        f"END {name}"
        for name, direction in (
            ("li1", "VERTICAL"), ("met1", "HORIZONTAL"),
            ("met2", "VERTICAL"), ("met3", "HORIZONTAL"),
            ("met4", "VERTICAL"), ("met5", "HORIZONTAL")))
    magic = "\n".join(
        ["tech", "planes"]
        + [f"  metal{i},m{i},met{i}" for i in range(1, 6)]
        + ["end", "types"]
        + [f"  metal{i} m{i} met{i} metal{i}" for i in range(1, 6)]
        + ["end"])
    facts = A5E.PdkFacts()
    facts.tech_lef = A5E.tech_lef_layers(lef)
    facts.layers = A5L.layer_identity(magic, "Magic layer fixture")
    facts.sources["tech_lef"] = "/pdk/sky130.tlef"
    facts.tech_lef_sha256 = "fixture"
    geo = A5E.Geo(A5L.deck_rules(DRC_TECH), 0.18, 100, 0.30, 0.15)

    spec, basis = A5E.pin_spec_for(
        ["vdd", "vout"], {"vdd": "vdd"}, {}, facts, geo)

    assert basis["routing_layers"] == ["met1", "met2", "met3", "met4", "met5"]
    assert spec["ports"]["vdd"]["lef_layer"] == "met4"
    assert spec["ports"]["vout"]["lef_layer"] == "met3"


def test_pin_stack_boxes_supports_a_direct_metal2_signal_pin():
    """A signal selected on metal2 has no via sequence to enumerate."""
    geo = SimpleNamespace(
        via_pad={1: 13, 2: 14},
        long_half={2: 2},
        wire={2: 30},
        rules_via_space=lambda _k: 1,
    )

    paint, bars = A5E._pin_stack_boxes(100, 200, 2, 2, geo, 1)

    assert bars[2] == (85, 185, 115, 215)
    assert paint == [("metal2", bars[2])]


def test_pin_site_without_a_clear_position_is_refused_not_drawn():
    """A pin fallback must not manufacture a known cross-net short."""
    plan = A5E.Plan()

    class NoClear:
        def clear(self, *_args):
            return False

    geo = SimpleNamespace(
        via_pad={1: 13, 2: 14},
        long_half={2: 2, 3: 2},
        wire={2: 30, 3: 30},
        space={2: 4, 3: 4},
        default_space=4,
        rules_via_space=lambda _k: 1,
    )
    pin_spec = {"ports": {"sig": {
        "index": 1, "rail": False, "level": 3,
        "direction": "HORIZONTAL", "width_lam": 10, "cuts": 1,
        "lef_layer": "met3", "lef_type": "ROUTING", "use": "signal",
    }}}

    with pytest.raises(A5E.Refusal, match="pin_site_clearance"):
        A5E._draw_pins(plan, ["sig"], {"sig": (100, 100, 200, 120)},
                       pin_spec, geo, NoClear(), 500, 16)
    assert plan.shapes == []


# A device the PDK permits and this emitter has never drawn: the round-20
# geometry, `w=1.0u l=0.5u`, against a PDK wmin of 0.15 um.
LEGAL_NARROW = ".subckt blk d g s b\nxm1 d g s b xx_lv_nmos w=1u l=0.5u\n.ends\n"


# ══ ARM A (I1) — a legal geometry is DRAWN, whatever this emitter has seen ══
def test_arm_a_a_legal_narrow_device_is_drawn_not_refused(tmp_path,
                                                          monkeypatch):
    """THE arm that matters. Round 20's generator refused `w=1.0u l=0.5u`
    against a PDK wmin of 0.15 um because its notion of drawable was the set
    of widths it had probed. An emitter that refuses everything also refuses
    the bug, so this test is the one that keeps the others honest."""
    project = _project(tmp_path, LEGAL_NARROW)
    rc, doc = _run(monkeypatch, project, FakeStage())
    assert rc == A5E.RC_OK, doc
    rep = doc["blocks"]["blk"]
    assert rep["result"] == "OK", rep
    assert (project / "phase3" / "analog" / "blk" / "layout.mag").is_file()
    assert (project / "phase3" / "analog" / "blk"
            / "layout_provenance.json").is_file()


def test_arm_a_there_is_no_width_list_anywhere_in_the_emitter():
    """The defect was a LIST of drawable widths. The fix is not a longer
    list; it is the absence of one. Every geometry bound this program applies
    must arrive from the PDK at run time."""
    src = Path(A5E.__file__).read_text()
    body = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    body = re.sub(r'""".*?"""', "", body, flags=re.S)
    for name in ("wmin", "lmin"):
        for m in re.finditer(rf"{name}\s*=\s*([0-9.]+)", body):
            pytest.fail(f"{name} is hard-coded to {m.group(1)} in the emitter")


def test_arm_a_a_width_beyond_the_probed_set_still_resolves_its_limits():
    """`limits_for` answers from the PDK for any width, because it never
    looks at a width at all — it looks the MODEL up."""
    facts = A5E.PdkFacts()
    facts.mos_limits = A5L.fet_limits(FET_TCL)
    facts.gencells = A5L.gencell_defaults(FET_TCL, "/pdk/x-fet.tcl")
    facts.sources["gencell_tcl"] = "/pdk/x-fet.tcl"
    lmin, wmin, src = facts.limits_for("xx_lv_nmos")
    assert (lmin, wmin) == (0.13, 0.15)
    assert src == "/pdk/x-fet.tcl"
    # Every MOS the PDK declares must be answered, not only some of them.
    # MEASURED on ihp-sg13g2: keying the limits on the model name that
    # happens to appear on the same line as `lmin` files the high-voltage
    # block's numbers under the LOW-voltage model (they share a `compatible`
    # list) and answers for NO high-voltage model at all — 2 of 4, and the
    # LDO in the measured design is built entirely from the 2 that were
    # missing. The declaring `proc` is the owner.
    got = A5L.fet_limits(FET_TCL)
    assert got == {"xx_lv_nmos": (0.13, 0.15),
                   "xx_hv_nmos": (0.45, 0.15)}, got


# ══ ARM B (I2) — refused BY NAME, with the rule and the FILE, before probe ══
SUBMIN = ".subckt blk d g s b\nxm1 d g s b xx_lv_nmos w=0.1u l=0.5u\n.ends\n"


def test_arm_b_sub_minimum_is_refused_by_name_with_the_rule_and_the_file(
        tmp_path, monkeypatch):
    project = _project(tmp_path, SUBMIN)
    stage = FakeStage()
    rc, doc = _run(monkeypatch, project, stage)
    assert rc == A5E.RC_FORBIDDEN
    rep = doc["blocks"]["blk"]
    assert rep["result"] == "FORBIDDEN"
    said = " ".join(rep["refusals"])
    assert "m1" in said                    # the DEVICE, by name
    assert "w=0.1" in said                 # the VALUE
    assert "wmin=0.15" in said             # the RULE
    assert "xx_lv_nmos" in said            # the MODEL
    assert "/pdk/x-fet.tcl" in said        # the FILE the rule came from


def test_arm_b_the_refusal_happens_before_any_probe(tmp_path, monkeypatch):
    """`before any probe` is part of the contract, not a nicety: a probe of a
    forbidden device is a tool error whose message is about Magic, not about
    the rule that was broken."""
    project = _project(tmp_path, SUBMIN)
    stage = FakeStage()
    _run(monkeypatch, project, stage)
    assert not any("magic -dnull" in c for c in stage.commands), stage.commands


def test_arm_b_no_assertion_tuple_reaches_the_caller(tmp_path, monkeypatch):
    """Round 20's shape was `AssertionError: ('mp_mkp1', 'no leg tap level')`.
    A tuple is not a refusal a reader can act on, and `assert` vanishes under
    `python -O`."""
    project = _project(tmp_path, SUBMIN)
    stage = FakeStage()
    _install(monkeypatch, stage)
    rc = A5E.main([str(project), "--block", "blk", "--container", "c",
                   "--pdk-root", "/pdk", "--family", "x",
                   "--gencell-tcl", "/pdk/x-fet.tcl",
                   "--drc-tech", "/pdk/x-drc.tech"])
    assert rc == A5E.RC_FORBIDDEN
    src = Path(A5E.__file__).read_text()
    src = re.sub(r'""".*?"""', "", src, flags=re.S)
    assert not re.search(r"^\s*assert\b", src, re.M), \
        "the emitter must refuse by message, never by assertion"


# ══ ARM C (I3) — the whole structure, on the grid, maximum not first hit ══
# One ring leg, and the terminals it must clear. In round 20 the scan started
# at the bulk label and walked UP; that label sits BELOW this leg, so two
# thirds of it was never examined.
LEG = [(-103, -78, -87, 78)]
PADS = [(-59, -15, -29, 15), (29, -15, 59, 15), (-15, 57, 15, 87)]


def test_arm_c_the_scan_reaches_the_end_of_the_leg_the_old_one_never_saw():
    got = A5E.choose_tap(LEG, PADS, [], pad_half=15)
    assert got is not None
    x, y, clear, rows_ok = got
    lo, hi = -78 + 15, 78 - 15
    assert lo <= y <= hi
    # the position taken is the MAXIMUM over the whole leg, not the first
    # position that clears some threshold
    best = max(
        min(A5E.box_separation((x0 - 15, yy - 15, x0 + 15, yy + 15), p) + 30
            for p in PADS)
        for x0 in (-95,) for yy in range(lo, hi + 1))
    assert clear == best


def test_arm_c_the_search_is_on_the_pdk_grid_not_a_stride():
    """A 25-lambda stride anchored on the bulk label missed the one legal
    band by ONE lambda. Every integer position on the bar is a candidate, so
    a one-lambda band cannot be stepped over: shrink the legal window to a
    single lambda and the scan still finds it."""
    pads = [(-120, -78, -70, 38), (-120, 44, -70, 200)]
    got = A5E.choose_tap([(-103, -78, -87, 78)], pads, [], pad_half=1)
    assert got is not None and got[1] == 41, got
    # a 25-lambda stride anchored at the leg's bottom steps straight over it
    assert 41 not in range(-77, 78, 25)


def test_arm_c_every_bar_of_the_ring_is_a_candidate_not_only_one():
    """Round 20 looked at the leftmost vertical leg alone. A ring has four
    bars, and the clearest position may be on any of them."""
    ring = [(-103, -78, -87, 78), (87, -78, 103, 78),
            (-103, 78, 103, 94), (-103, -94, 103, -78)]
    blocked = [(-120, -100, -70, 100)]     # the left leg is unusable
    got = A5E.choose_tap(ring, blocked, [], pad_half=8)
    assert got is not None and got[0] > 0, got


def test_arm_c_a_ring_too_small_to_tap_is_refused_by_name(tmp_path,
                                                          monkeypatch):
    """I5's other half: a structure that cannot host the connection at all.
    `choose_tap` returns None and the caller raises a NAMED refusal carrying
    what it measured — not an assertion."""
    assert A5E.choose_tap([(0, 0, 4, 4)], [], [], pad_half=15) is None


# ══ ARM D (I4) — drawn and RECORDED, never refused and never silent ══
def test_arm_d_a_shortfall_is_drawn_and_recorded_as_a_structured_record(
        tmp_path, monkeypatch):
    """A clearance floor is a PREDICTION. When the best position on the ring
    is under it the emitter DRAWS and records; round 20 measured both
    directions of this, 16 deviations -> 68 violations of 628 rules FAIL and
    no deviations -> 0 violations of 560 rules PASS."""
    project = _project(tmp_path, LEGAL_NARROW)
    rc, doc = _run(monkeypatch, project, FakeStage(child=TIGHT_CHILD))
    rep = doc["blocks"]["blk"]
    # NEVER REFUSED, which is what this arm is about: a shortfall does not
    # stop the emitter drawing, and the layout is on disk at the bottom.
    #
    # WHY THIS IS NOT `rc == RC_OK` ANY MORE, and why that is not a
    # weakening. This fixture is a device whose ring is deliberately too
    # tight, and on a device that small the escape islands of four terminals
    # genuinely MERGE: the short audit finds it, and a drawn short is now
    # blocking (`blocking_shorts`). So this fixture measures TWO things at
    # once and `rc == 0` could no longer tell them apart. The assertion below
    # says exactly what this arm was written to prove — the shortfall is
    # RECORDED and NOT refused — and then names the one condition that does
    # move the exit code here, so a short appearing or disappearing in this
    # fixture cannot pass unnoticed either way.
    assert rc != A5E.RC_REFUSED, doc
    assert rep["result"] != "REFUSED"
    assert (rc, rep["result"]) == (A5E.RC_FORBIDDEN, "SHORTED"), doc
    assert A5E.blocking_shorts(rep["deviations"]), rep["deviation_summary"]
    taps = [d for d in rep["deviations"]
            if d["quantity"] == "bulk_tap_clearance_lambda"]
    assert taps, rep["deviation_summary"]
    rec = taps[0]
    for field in ("device", "model", "w", "l", "quantity", "required",
                  "achieved", "shortfall", "adjudicator"):
        assert field in rec, field
    assert rec["device"] == "m1" and rec["model"] == "xx_lv_nmos"
    assert rec["shortfall"] == rec["required"] - rec["achieved"] > 0
    assert "A6" in rec["adjudicator"]
    # DRAWN, not refused
    assert (project / "phase3" / "analog" / "blk" / "layout.mag").is_file()


def test_arm_d_the_emitter_never_prints_a_drc_verdict_of_its_own(tmp_path,
                                                                monkeypatch):
    project = _project(tmp_path, LEGAL_NARROW)
    rc, doc = _run(monkeypatch, project, FakeStage(child=TIGHT_CHILD))
    blob = json.dumps(doc)
    assert not re.search(r"\bDRC (CLEAN|PASS|FAIL)\b", blob), blob[:400]
    assert "violations" not in blob


def test_arm_d_the_floor_is_never_lowered_to_make_the_emitter_pass(tmp_path,
                                                                  monkeypatch):
    """The recorded `required` is the floor the limits program derives from
    the deck plus this emitter's own declared pad size — not whatever the
    achieved value happened to be."""
    project = _project(tmp_path, LEGAL_NARROW)
    rc, doc = _run(monkeypatch, project, FakeStage(child=TIGHT_CHILD))
    rep = doc["blocks"]["blk"]
    assert rep["m1_space_um"] == 0.18
    terms = rep["tap_clearance_um"]["terms"]
    assert terms["m1_space_um"] == 0.18
    want = terms["m1_space_um"] + 2 * terms["tap_pad_half_um"]
    assert rep["tap_clearance_um"]["value"] == pytest.approx(want)
    taps = [d for d in rep["deviations"]
            if d["quantity"] == "bulk_tap_clearance_lambda"]
    assert taps[0]["required"] == round(want * rep["lambda_per_um"])


def test_arm_d_a_clean_block_records_no_deviation_at_all(tmp_path,
                                                         monkeypatch):
    """The other direction of the same measurement: the record must be able
    to be EMPTY, or a deviation list says nothing."""
    project = _project(tmp_path, LEGAL_NARROW)
    rc, doc = _run(monkeypatch, project, FakeStage())
    rep = doc["blocks"]["blk"]
    assert rep["result"] == "OK"
    assert [d for d in rep["deviations"]
            if d["quantity"] == "bulk_tap_clearance_lambda"] == []


# ══ ARM E (I5) — ENV_UNAVAILABLE, NAMED, non-zero, and NO layout.mag ══
@pytest.mark.parametrize("stage,tool,needle", [
    (FakeStage(open_ok=False), "docker/container", "container"),
    (FakeStage(magic=False), "magic", "magic"),
    (FakeStage(pdk=False), "pdk", "-fet.tcl"),
    (FakeStage(drc=False), "pdk", "-drc.tech"),
])
def test_arm_e_an_absent_capability_is_named_and_writes_nothing(
        tmp_path, monkeypatch, stage, tool, needle):
    project = _project(tmp_path, LEGAL_NARROW)
    rc, doc = _run(monkeypatch, project, stage)
    assert rc == A5E.RC_ENV_UNAVAILABLE
    assert doc["result"] == "ENV_UNAVAILABLE"
    assert doc["tool"] == tool
    assert "ENV_UNAVAILABLE" in doc["reason"]
    assert needle in doc["reason"], doc["reason"]
    assert not (project / "phase3" / "analog" / "blk" / "layout.mag").exists()


def test_arm_e_a_pdk_that_cannot_be_read_is_absent_never_a_default(
        tmp_path, monkeypatch):
    """The limits are DERIVED. A default would be a number nobody measured,
    and it would draw a device the PDK may not permit."""
    project = _project(tmp_path, LEGAL_NARROW)
    rc, doc = _run(monkeypatch, project, FakeStage(pdk=False))
    assert rc == A5E.RC_ENV_UNAVAILABLE
    assert "never a default" in doc["reason"]


def test_arm_e_magic_reporting_success_without_the_artefact_is_not_success(
        tmp_path, monkeypatch):
    project = _project(tmp_path, LEGAL_NARROW)
    rc, doc = _run(monkeypatch, project, FakeStage(layout=False))
    assert rc == A5E.RC_REFUSED
    assert doc["blocks"]["blk"]["result"] == "NO_ARTEFACT"


def test_arm_e_a_model_the_pdk_has_no_gencell_for_is_named(tmp_path,
                                                           monkeypatch):
    project = _project(
        tmp_path,
        ".subckt blk a b\nxq1 a b not_in_this_pdk w=1u l=1u\n.ends\n")
    rc, doc = _run(monkeypatch, project, FakeStage())
    assert rc == A5E.RC_REFUSED
    rep = doc["blocks"]["blk"]
    assert rep["result"] == "NO_GENCELL"
    assert "not_in_this_pdk" in rep["reason"]
    assert "does not invent a device" in rep["reason"]


# ══ what the PRODUCER must hand the rest of the flow ══
def test_the_provenance_names_the_producer_the_limits_and_their_files(
        tmp_path, monkeypatch):
    project = _project(tmp_path, LEGAL_NARROW)
    _run(monkeypatch, project, FakeStage())
    prov = json.loads((project / "phase3" / "analog" / "blk"
                       / "layout_provenance.json").read_text())
    assert prov["producer"] == "analog_a5_layout_emit"
    assert prov["version"] and prov["version"] != "unknown"
    assert prov["block"] == "blk"
    assert prov["devices"] == 1
    assert prov["pdk_limits"]["xx_lv_nmos"]["source"] == "/pdk/x-fet.tcl"
    assert prov["pdk_sources"]["drc_tech"] == "/pdk/x-drc.tech"
    assert isinstance(prov["deviations"], list)
    # the numbers the PDK does NOT state are declared as the generator's own
    assert prov["generator_geometry_um"]["wire_width"]
    assert prov["generator_geometry_um"]["via_pad_half"]


def test_the_layout_the_emitter_writes_passes_the_a5_gate(tmp_path,
                                                          monkeypatch):
    """`analog_a5_layout_check` must keep passing UNCHANGED on this
    producer's output — it is the gate that rejects an empty or stub-marked
    layout, and a producer that needs the gate relaxed has produced nothing."""
    import analog_a5_layout_check as A5C
    project = _project(tmp_path, LEGAL_NARROW)
    _run(monkeypatch, project, FakeStage())
    text = (project / "phase3" / "analog" / "blk" / "layout.mag").read_text()
    assert A5C._mag_geometry_count(text) > 0, text[:400]
    has_geo, why = A5C._layout_has_real_geometry(
        project / "phase3" / "analog" / "blk" / "layout.mag")
    assert has_geo, why


def test_the_netlist_is_the_only_design_input_that_is_opened(tmp_path,
                                                             monkeypatch):
    """Section 4.05: the A3 netlist is design INPUT; no oracle, golden or
    harness artefact is ever read. The only paths this program opens are the
    netlist, the PDK files, and its own outputs."""
    project = _project(tmp_path, LEGAL_NARROW)
    bdir = project / "phase3" / "analog" / "blk"
    (bdir / "golden.gds").write_bytes(b"x" * 100)
    (bdir / "oracle.sp").write_text("* not for you\n")
    opened: list = []
    real_open = Path.read_text

    def spy(self, *a, **k):
        opened.append(str(self))
        return real_open(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", spy)
    _run(monkeypatch, project, FakeStage())
    for path in opened:
        assert "golden" not in path and "oracle" not in path, path


def test_the_emitter_names_no_pdk_family_and_no_design():
    """chip-AGNOSTIC, and PDK-family agnostic in the logic. The family and
    root are ARGUMENTS; the numbers come out of files the PDK ships."""
    src = Path(A5E.__file__).read_text()
    body = re.sub(r'""".*?"""', "", src, flags=re.S)
    body = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    body = body.replace('default="ihp-sg13g2"', "")
    for token in ("sg13", "sky130", "gf180", "ihp", "nangate", "asap7"):
        assert token not in body.lower(), f"{token} appears in the logic"


# ══ THE RUNNER: A5 now has a producer where it had a stub ══
class _Ran:
    """Records the argv the runner dispatched, and answers as asked."""

    def __init__(self, *, emit_rc=0, emit_out="", gate_rc=0, writes=None,
                 layout=None):
        self.argv: list = []
        self.emit_rc, self.emit_out = emit_rc, emit_out
        self.gate_rc, self.writes, self.layout = gate_rc, writes, layout

    def run(self, *args, **kw):
        # FAITHFUL DOUBLE — refuse exactly what the real `_progress_run.run`
        # refuses. A `**kw` stand-in is MORE PERMISSIVE than the real function:
        # it swallows an argument the real one has no parameter for, so the test
        # stays green while production raises TypeError. Binding the REAL
        # signature means the NEXT argument that drifts is caught too.
        import inspect as _inspect
        import subprocess as _sp
        import _progress_run as _real_pr
        _inspect.signature(_real_pr.run).bind(*args, **kw)
        argv = args[0]
        self.argv.append([str(a) for a in argv])
        name = Path(argv[1]).name
        if name == "analog_a5_layout_emit.py":
            if self.writes:
                self.writes()
            return _sp.CompletedProcess(argv, self.emit_rc, self.emit_out, "")
        if name == "analog_a5_layout_check.py":
            # the real gate answers rc=2 when the artefact is not there, and
            # that rc is what routes the runner to the producer at all
            if self.layout is not None and not self.layout.is_file():
                return _sp.CompletedProcess(argv, 2, "",
                                            "A5_LAYOUT_MISSING")
            return _sp.CompletedProcess(argv, self.gate_rc, "PASS: gate\n", "")
        return _sp.CompletedProcess(argv, 2, "", "artefact missing")


def _runner_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase3" / "analog" / "b").mkdir(parents=True)
    return proj


def test_the_runner_dispatches_the_emitter_at_a5(tmp_path, monkeypatch):
    """The producer is invoked where A4's real sweep is: after the gate has
    said the artefact is missing, and BEFORE any stub fallback."""
    import analog_one_shot_runner as AOSR
    proj = _runner_project(tmp_path)
    lay = proj / "phase3" / "analog" / "b" / "layout.mag"
    ran = _Ran(layout=lay, writes=lambda: lay.write_text("magic\nuse c i\n"))
    monkeypatch.setattr(AOSR, "_pr", ran)
    res = AOSR.step_for_block(proj, {"name": "b"}, "A5_layout", None)
    dispatched = [a for a in ran.argv
                  if Path(a[1]).name == "analog_a5_layout_emit.py"]
    assert dispatched, ran.argv
    assert "--block" in dispatched[0] and "b" in dispatched[0]
    assert "--container" in dispatched[0]
    assert res.status == "PASS", res
    assert "analog_a5_layout_emit" in res.detail


def test_the_runner_no_longer_has_a_stub_for_a5(tmp_path):
    """The `"x" * 400` padded `layout.mag` is gone, and nothing may put it
    back: it is the thing that stood where A5's producer should have been."""
    import analog_one_shot_runner as AOSR
    written = AOSR._emit_deterministic_stub(tmp_path, "b", "A5_layout")
    assert written == []
    assert not (tmp_path / "phase3" / "analog" / "b" / "layout.mag").exists()


def test_an_unreachable_tool_is_reported_by_name_and_writes_no_layout(
        tmp_path, monkeypatch):
    """The whole point of removing the stub. A run with no Magic must say
    which tool is missing — never leave a fabricated layout.mag behind, and
    never report an anonymous 'artefact missing'."""
    import analog_one_shot_runner as AOSR
    proj = _runner_project(tmp_path)
    said = json.dumps(
        {"result": "ENV_UNAVAILABLE", "tool": "magic",
         "reason": "ENV_UNAVAILABLE: `magic` is not on PATH in vibeic-eda."})
    ran = _Ran(layout=proj / "phase3" / "analog" / "b" / "layout.mag",
               emit_rc=2, emit_out=said)
    monkeypatch.setattr(AOSR, "_pr", ran)
    res = AOSR.step_for_block(proj, {"name": "b"}, "A5_layout", None)
    assert res.status == "NOT_MEASURED", res
    assert "ENV_UNAVAILABLE" in res.detail and "magic" in res.detail
    assert not (proj / "phase3" / "analog" / "b" / "layout.mag").exists()


def test_a_layout_that_fails_the_gate_is_a_named_fail_not_a_pass(
        tmp_path, monkeypatch):
    """The producer produces; the GATE still owns the verdict, on the
    artefact that is actually on disk."""
    import analog_one_shot_runner as AOSR
    proj = _runner_project(tmp_path)
    lay = proj / "phase3" / "analog" / "b" / "layout.mag"
    ran = _Ran(layout=lay, gate_rc=1,
               writes=lambda: lay.write_text("magic\n"))
    monkeypatch.setattr(AOSR, "_pr", ran)
    res = AOSR.step_for_block(proj, {"name": "b"}, "A5_layout", None)
    assert res.status == "FAIL", res


# ══ a refusal must not be quiet about what it left behind ══
def test_a_refusal_names_the_layout_an_earlier_run_left_behind(tmp_path,
                                                               monkeypatch):
    """MEASURED on the real PDK: draw a legal device, edit its width below
    the PDK minimum, re-run. The refusal is correct and `layout.mag` is still
    there from the first run — and the A5 gate reads geometry, not
    provenance, so it PASSes that layout for a netlist the PDK forbids.
    Deleting an artefact this run did not write is not this producer's call;
    saying so in the record it owns is."""
    project = _project(tmp_path, LEGAL_NARROW)
    rc, _ = _run(monkeypatch, project, FakeStage())
    assert rc == A5E.RC_OK
    bdir = project / "phase3" / "analog" / "blk"
    assert (bdir / "layout.mag").is_file()

    (bdir / "blk.sp").write_text(SUBMIN)
    rc, doc = _run(monkeypatch, project, FakeStage())
    assert rc == A5E.RC_FORBIDDEN
    rep = doc["blocks"]["blk"]
    assert "layout.mag" in rep["layout_present_before_this_run"]
    assert "EARLIER run" in rep["stale_layout_warning"]
    # and the record on disk agrees with the refusal, not with the old layout
    prov = json.loads((bdir / "layout_provenance.json").read_text())
    assert prov["result"] == "FORBIDDEN"


def test_a_netlist_this_program_cannot_read_is_named_not_a_traceback(
        tmp_path, monkeypatch):
    """A producer the runner calls must not raise out of itself: the runner
    reads its rc and its words, and a traceback is neither."""
    project = _project(tmp_path, "* no subckt anywhere in this file\n")
    rc, doc = _run(monkeypatch, project, FakeStage())
    assert rc == A5E.RC_REFUSED
    rep = doc["blocks"]["blk"]
    assert rep["result"] == "UNREADABLE_NETLIST"
    assert "subckt" in rep["reason"]


def test_mos_override_keeps_native_passive_generators_available():
    class SplitStage(FakeStage):
        def sh(self, cmd, timeout=900):
            if cmd.startswith('ls /override/'):
                return 0, '/override/custom-fet.tcl\n', ''
            return super().sh(cmd, timeout)
    facts, why = A5E.read_pdk(SplitStage(), '/pdk', 'x',
                             '/override/custom-fet.tcl', '/pdk/x-drc.tech')
    assert why == ''
    assert len(facts.gencells) == 3
    assert facts.gencells['rr']['source'] == '/pdk/x-res.tcl'
    assert facts.gencells['xx_lv_nmos']['source'] == '/override/custom-fet.tcl'


def test_device_footprint_wraps_without_changing_device_population(tmp_path, monkeypatch):
    deck = '.subckt blk d g s b\n' + ''.join(
        f'xm{i} d g s b xx_lv_nmos w=1u l=0.5u\n' for i in range(240)) + '.ends\n'
    project = _project(tmp_path, deck)
    captured = []
    original = A5E.build_plan
    def capture(*args, **kwargs):
        plan = original(*args, **kwargs)
        captured.append(plan)
        return plan
    monkeypatch.setattr(A5E, 'build_plan', capture)
    rc, doc = _run(monkeypatch, project, FakeStage())
    plan = captured[0]
    boxes = [s['box'] for s in plan.device_shapes + plan.shapes]
    width = (max(b[2] for b in boxes) - min(b[0] for b in boxes)) / 100
    assert width <= 1010, f'physical footprint is still one long row: {width} um'
    assert doc['blocks']['blk']['devices'] == 240
    assert len(plan.placement_rows) > 1
    assert not A5E.net_shorts(plan)


def test_native_inverter_terminal_escape_does_not_short_gate_to_supply():
    """Captured native contact geometry reproduces the gate/supply M3 short."""
    import ast
    from copy import deepcopy
    data = json.loads((Path(__file__).parent / 'fixtures/a5_native_contact_escape/inverter.json').read_text())
    tech = data['technology_text']
    facts = A5E.PdkFacts()
    facts.layers = A5L.layer_identity(tech, 'captured native technology')
    facts.layers.contact_heads = [
        (t[0], tuple(t[1:])) for line in A5L._tech_sections(tech).get('contact', [])
        if len(t := line.split()) >= 3 and t[0] != 'stackable']
    facts.gencells = data['gencells']
    devs = [
        {'name': 'mp', 'model': 'sg13_lv_pmos', 'nets': ['q', 'g', 'vp', 'vp'],
         'pars': {'w': 1., 'l': .5}, 'class': 'mosfet'},
        {'name': 'mn', 'model': 'sg13_lv_nmos', 'nets': ['q', 'g', 'vn', 'vn'],
         'pars': {'w': .5, 'l': .5}, 'class': 'mosfet'}]
    cells = {}
    for dev, text, delta in zip(devs, data['cells_mag'], data['deltas']):
        cell = A5E.parse_cell(text, facts.layers)
        cell['delta'] = delta
        cells[A5E.config_key(dev)] = cell
    rules = {key: {ast.literal_eval(k): v for k, v in values.items()}
             for key, values in data['routing_rules'].items()}
    geo = A5E.Geo(rules, .18, 100, .6, .35)
    plan = A5E.build_plan(devs, ['q', 'g', 'vp', 'vn'], cells, facts, geo, 88)
    assert len(A5E.net_shorts(plan)) == 0
    assert geo.wire[3] == 60, 'the preferred outer lane width is unchanged'
    # An incompatible minimum is not silently ignored to turn this case green.
    strict = deepcopy(rules)
    strict['metal_width_um'][3] = .6
    blocked = A5E.build_plan(devs, ['q', 'g', 'vp', 'vn'], cells, facts,
                             A5E.Geo(strict, .18, 100, .6, .35), 88)
    assert A5E.net_shorts(blocked)


def test_same_net_vias_keep_native_cut_spacing_but_allow_exact_reuse():
    rules = {'metal_space_um': {}, 'metal_width_um': {}, 'metal_area_um2': {},
             'via_width_um': {2: .2}, 'via_space_um': {2: .21},
             'via_surround_um': {}, 'via_surround_dir_um': {}}
    geo = A5E.Geo(rules, .18, 100, .6, .35)
    sites = A5E.Sites([{'net': 'vn', 'layer': 'via2', 'box': (0, 0, 20, 20)}], geo)
    assert sites.clear((25, 0, 45, 20), ['via2'], None, 'vn', island=True) is False
    assert sites.clear((50, 0, 70, 20), ['via2'], None, 'vn', island=True) is True
    assert sites.clear((0, 0, 20, 20), ['via2'], None, 'vn', island=True) is True


def test_same_net_landing_gap_is_not_a_spacing_waiver():
    rules = {'metal_space_um': {3: .21}, 'metal_width_um': {}, 'metal_area_um2': {},
             'via_width_um': {}, 'via_space_um': {},
             'via_surround_um': {}, 'via_surround_dir_um': {}}
    geo = A5E.Geo(rules, .18, 100, .6, .35)
    sites = A5E.Sites([
        {'net': 'q', 'layer': 'metal3', 'box': (0, 0, 80, 72)},
        {'net': 'q', 'layer': 'metal3', 'box': (0, 10, 300, 60)}], geo)
    assert sites.clear((100, 0, 180, 72), ['metal3'], None, 'q', island=True) is False
    assert sites.clear((110, 0, 190, 72), ['metal3'], None, 'q', island=True) is True
    assert sites.clear((70, 0, 150, 72), ['metal3'], None, 'q', island=True) is True


def test_via_candidate_clears_the_complete_departure_not_only_the_island():
    rules = {'metal_space_um': {2: .21, 3: .21},
             'metal_width_um': {2: .24, 3: .24},
             'metal_area_um2': {2: .144, 3: .144},
             'via_width_um': {2: .2}, 'via_space_um': {2: .21},
             'via_surround_um': {}, 'via_surround_dir_um': {(2, 2): .045, (2, 3): .045}}
    geo = A5E.Geo(rules, .18, 100, .6, .1)
    def context():
        plan = A5E.Plan()
        plan.paint('supply', 'metal3', 0, 0, 300, 60)
        plan.paint('signal', 'metal2', -200, 60, 200, 250)
        sites = A5E.Sites(plan.shapes, geo)
        plan.sites = sites
        return plan, sites
    def departure(x, y):
        half = geo.wire[3] // 2
        return [('metal3', (x - half, min(y, 148) - half,
                            x + half, max(y, 148) + half))]
    mutant, old_sites = context()
    x, y = A5E._via_stack(mutant, 'signal', 0, 84, 2, geo, top=3, sites=old_sites)
    assert not all(old_sites.clear(box, [layer], None, 'signal')
                   for layer, box in departure(x, y))
    fixed, sites = context()
    x, y = A5E._via_stack(fixed, 'signal', 0, 84, 2, geo, top=3,
                          sites=sites, departure=departure)
    assert all(sites.clear(box, [layer], None, 'signal')
               for layer, box in departure(x, y))
    for layer, box in departure(x, y):
        fixed.paint('signal', layer, *box)
    assert A5E.net_shorts(fixed) == []
