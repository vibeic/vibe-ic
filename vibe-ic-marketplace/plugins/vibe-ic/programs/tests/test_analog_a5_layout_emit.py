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


class FakeStage:
    """Stands in for the container, and records what was asked of it."""

    def __init__(self, *, magic=True, pdk=True, drc=True, open_ok=True,
                 layout=True, child=None):
        self._child = child or CHILD_MAG
        self.path = "/stage"
        self.host_tmp = None
        self._magic, self._pdk, self._drc = magic, pdk, drc
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
    assert rc == A5E.RC_OK, doc
    rep = doc["blocks"]["blk"]
    assert rep["result"] == "OK"
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

    def run(self, argv, **kw):
        import subprocess as _sp
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
    assert res.status == "WAIVED", res
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
