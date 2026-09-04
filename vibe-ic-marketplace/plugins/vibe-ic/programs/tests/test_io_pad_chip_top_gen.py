#!/usr/bin/env python3
"""The producer that instantiates the IO pad cells, and its refusals.

WHAT THESE TESTS ARE THE CONTROL FOR
====================================
Before this producer existed, `pad_assignment_gen` refused every design on the
chip path for a reason it stated in its own docstring: the four side lists and
`SIGNAL_MAP` name NETLIST INSTANCES, and no step of this flow instantiated an
IO cell, so there were no instances to name. MEASURED on one benchmark IC and
one open 5 V PDK at plugin 1.15.65:

    pad_assignment_gen rc=1 — "3 of 8 answered ... still owes 10 of the 13
    variables `pad_ring_gen` requires"

`test_the_producer_closes_the_owed_set` is the BIDIRECTIONAL control for that:
one fixture tree, `pad_assignment_gen` run twice, differing only in whether the
producer has run. Without it five variables are owed and the program refuses;
with it none of the five is. `test_removing_the_record_puts_the_owed_set_back`
runs the same control as a MUTATION, so a guard that only ever sees the fixed
state cannot pass by coincidence.

The remaining tests pin REFUSALS. They matter more than the happy path: a pad
ring that is wrong is a pin-out nobody chose wearing the artefact of one
somebody did, and the value of this producer is that it declines to invent the
parts nobody stated.

`test_the_die_the_ring_needs_is_the_three_terms_pad_ring_gen_subtracts` pins
the arithmetic that two separate measured refusals came out of — first the
corner term, then the edge-spacing term — against the exact expression
`pad_ring_gen.side_width` uses.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

GEN = PROGRAMS / "io_pad_chip_top_gen.py"
ASSIGN = PROGRAMS / "pad_assignment_gen.py"

#: The five variables that were owed because nothing instantiated a pad.
INSTANCE_NAMED_VARS = ("PAD_SOUTH", "PAD_EAST", "PAD_NORTH", "PAD_WEST",
                       "SIGNAL_MAP")

DOC = """---
layer: L3
---

# L3 — External Interface

The I/O cell library is delegated to the PDK i/o pad defaults.

## Physical Pad Placement

| Pad side | signals |
|---|---|
| **South (S)** | `rst` |
| **East (E)** | `clk` |
| **North (N)** | `d[w-1:0]` |
| **West (W)** | `q` |

## Design Parameters

| Parameter | default |
|---|---|
| `w` | 2 |
"""

SPEC = {
    "top_module": "core",
    "top_ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "d", "direction": "input", "width": 2, "msb": 1, "lsb": 0},
        {"name": "q", "direction": "output", "width": 1},
    ],
}

GROUP_DOC = """---
layer: L3
---

# L3 — External Interface

The I/O cell library is delegated to the PDK i/o pad defaults.

## Physical Pad Placement

| Pad side | signals |
|---|---|
| **North (N)** | payload data bus |
| **South (S)** | address + control valid / ready |
| **East (E)** | `clk` / `rst` |
| **West (W)** | status pin(s) |
"""

GROUP_SPEC = {
    "top_module": "core",
    "top_ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "i_payload_data", "direction": "input", "width": 2,
         "msb": 1, "lsb": 0},
        {"name": "o_payload_data", "direction": "output", "width": 2,
         "msb": 1, "lsb": 0},
        {"name": "o_address", "direction": "output", "width": 1},
        {"name": "o_control_valid", "direction": "output", "width": 1},
        {"name": "i_control_ready", "direction": "input", "width": 1},
        {"name": "o_status", "direction": "output", "width": 1},
    ],
}


def _macro(name: str, cls: str, w: float = 10.0, h: float = 100.0,
           pins=()) -> str:
    body = [f"MACRO {name}", f"  CLASS {cls} ;", f"  SIZE {w:.3f} BY {h:.3f} ;"]
    for pin, use in pins:
        body += [f"  PIN {pin}", "    DIRECTION INOUT ;", f"    USE {use} ;",
                 f"  END {pin}"]
    body += [f"END {name}", ""]
    return "\n".join(body)


#: A library in the distribution layout `_pad_ring.discover_io_lefs` reads.
#: No real PDK is copied and no vendor, foundry or process name appears.
CORNER_W = 40.0
PAD_W = 10.0
EDGE = 5.0

FULL_MACROS = (
    _macro("testlib_io__in", "PAD INPUT", PAD_W, 100.0, [("PAD", "SIGNAL")])
    + _macro("testlib_io__bi", "PAD INOUT", PAD_W, 100.0, [("PAD", "SIGNAL")])
    + _macro("testlib_io__fill", "PAD SPACER", 1.0, 100.0)
    + _macro("testlib_io__cor", "ENDCAP BOTTOMLEFT", CORNER_W, CORNER_W)
)
FULL_TERMINALS = "testlib_io__in/PAD testlib_io__bi/PAD"


def _pdk(root: Path, *, macros: str = FULL_MACROS,
         terminals: str = FULL_TERMINALS, edge: float = EDGE) -> Path:
    lef = root / "testpdk" / "libs.ref" / "testlib_io" / "lef"
    lef.mkdir(parents=True)
    (lef / "testlib_io.lef").write_text(macros)
    tech = root / "testpdk" / "libs.tech" / "someflow" / "testlib_io"
    tech.mkdir(parents=True)
    cfg = ['set ::env(PAD_SITE_NAME) "IO_Site"',
           'set ::env(PAD_CORNER_SITE_NAME) "COR_Site"',
           f'set ::env(PAD_EDGE_SPACING) "{edge:g}"',
           'set ::env(PAD_CORNER) "$::env(PAD_CELL_LIBRARY)__cor"',
           'set ::env(PAD_FILLERS) "$::env(PAD_CELL_LIBRARY)__fill"']
    if terminals:
        cfg.append(f'set ::env(PAD_PLACE_IO_TERMINALS) "{terminals}"')
    (tech / "config.tcl").write_text("\n".join(cfg) + "\n")
    return root


def _project(tmp: Path, *, doc: str = DOC, spec=None) -> Path:
    proj = tmp / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "L3_external_interface.md").write_text(doc)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(SPEC if spec is None else spec))
    return proj


def _run(script: Path, proj: Path, pdk_root: Path, extra=()):
    return subprocess.run(
        [sys.executable, str(script), str(proj),
         "--pdk-root", str(pdk_root), "--pdk", "testpdk", *extra],
        capture_output=True, text=True)


def _record(proj: Path) -> dict:
    return json.loads(
        (proj / "reports" / "phase3" / "io_pad_chip_top.json").read_text())


def _owed(report: Path) -> list:
    """The variables `pad_assignment_gen` says are still owed.

    It carries them on the FINDING, not at the top level, so reading a
    top-level `owed` key returns an empty list for a refusing run as well as a
    satisfied one — which would make every assertion below vacuous in the
    flattering direction.
    """
    obj = json.loads(report.read_text())
    out = []
    for f in obj.get("findings") or []:
        out.extend(f.get("variables_owed") or [])
    return out


# --------------------------------------------------------------------------- #
# the happy path — asserted, not assumed, because every refusal below is
# measured against it
# --------------------------------------------------------------------------- #
def test_one_pad_instance_per_declared_pin(tmp_path):
    proj = _project(tmp_path)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert res.returncode == 0, res.stdout + res.stderr
    rec = _record(proj)
    # 5 declared pins: rst, clk, d[1], d[0], q — the bus expanded one pad per
    # bit by the design's OWN rule, read by `_l_doc_pad_placement`.
    assert len(rec["pad_instances"]) == 5, rec["pad_instances"]
    masters = {r["master"] for r in rec["pad_instances"].values()}
    assert masters <= {"testlib_io__in", "testlib_io__bi"}, masters
    # The master came off the LEF CLASS record, not off a name table.
    inp = [i for i, r in rec["pad_instances"].items()
           if r["direction"] == "input"]
    assert all(rec["pad_instances"][i]["master"] == "testlib_io__in"
               for i in inp)
    v = (proj / rec["chip_top_verilog"]).read_text()
    for master in masters:
        assert master in v


def test_named_port_groups_resolve_without_a_design_specific_name_table(
        tmp_path):
    """A group row is a real declaration when port identifiers resolve it.

    This is not fuzzy prose matching: every semantic atom of each selected
    port occurs in the row, bus bits are still taken from L9, and the record
    exposes the exact statement-to-port mapping for review.
    """
    proj = _project(tmp_path, doc=GROUP_DOC, spec=GROUP_SPEC)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert res.returncode == 0, res.stdout + res.stderr
    rec = _record(proj)
    mapped = {r["side"]: r["matched_ports"]
              for r in rec["pad_group_resolution"]}
    assert mapped == {
        "N": ["i_payload_data", "o_payload_data"],
        "S": ["o_address", "o_control_valid", "i_control_ready"],
        "W": ["o_status"],
    }
    assert sum(len(v) for v in rec["derived_answers"]
               ["pad_order_by_side"].values()) == 10


def test_an_unresolved_group_is_refused_not_applied_to_every_port(tmp_path):
    doc = GROUP_DOC.replace("status pin(s)", "observability pins")
    proj = _project(tmp_path, doc=doc, spec=GROUP_SPEC)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "PAD_GROUP_UNRESOLVED" in res.stdout + res.stderr
    assert not (proj / "phase3/stage3/pnr/chip_top_io.v").exists()


def test_the_terminal_name_comes_from_the_library_not_from_a_constant(tmp_path):
    """A pad's signal pin is not always called `PAD`. The library states it in
    `PAD_PLACE_IO_TERMINALS`, and the emitted connection must use that name."""
    macros = (_macro("testlib_io__in", "PAD INPUT", PAD_W, 100.0,
                     [("ASIG", "SIGNAL")])
              + _macro("testlib_io__bi", "PAD INOUT", PAD_W, 100.0,
                       [("ASIG", "SIGNAL")])
              + _macro("testlib_io__fill", "PAD SPACER", 1.0, 100.0)
              + _macro("testlib_io__cor", "ENDCAP BOTTOMLEFT", CORNER_W,
                       CORNER_W))
    proj = _project(tmp_path)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk", macros=macros,
                              terminals="testlib_io__in/ASIG "
                                        "testlib_io__bi/ASIG"))
    assert res.returncode == 0, res.stdout + res.stderr
    v = (proj / _record(proj)["chip_top_verilog"]).read_text()
    assert ".ASIG(" in v and ".PAD(" not in v, v[:400]


def test_a_design_that_declares_no_pad_placement_writes_nothing(tmp_path):
    """Nobody was asked. No chip top, no record of instances, and
    `pad_assignment_gen` keeps the branch it has today."""
    proj = _project(tmp_path, doc="# L3\n\nNothing about pads.\n")
    res = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert res.returncode == 2, res.stdout
    assert not (proj / "phase3/stage3/pnr/chip_top_io.v").exists()


# --------------------------------------------------------------------------- #
# refusals
# --------------------------------------------------------------------------- #
def test_an_absent_io_library_is_refused_not_worked_around(tmp_path):
    proj = _project(tmp_path)
    empty = tmp_path / "emptypdk"
    (empty / "testpdk").mkdir(parents=True)
    res = _run(GEN, proj, empty)
    assert res.returncode != 0, res.stdout
    assert "NO_IO_LIBRARY" in res.stdout + res.stderr


def test_a_pad_placement_naming_a_port_the_design_does_not_declare_is_refused(
        tmp_path):
    """The document and the port list disagree, and choosing between them is
    not this producer's decision."""
    # ADDED, not renamed: renaming a placed port leaves it on no edge and the
    # producer refuses that first, with a different rule. The question here is
    # the other one — a side naming a net the design does not declare.
    doc = DOC.replace("`rst`", "`rst`、`nonesuch`")
    proj = _project(tmp_path, doc=doc)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert res.returncode == 1, res.stdout
    assert "SIDE_NAMES_UNKNOWN_PORT" in res.stdout + res.stderr
    assert "nonesuch" in res.stdout + res.stderr


def test_a_library_with_no_master_for_a_direction_is_refused(tmp_path):
    """Only a SPACER and a corner: nothing that can bring a signal out."""
    macros = (_macro("testlib_io__fill", "PAD SPACER", 1.0, 100.0)
              + _macro("testlib_io__cor", "ENDCAP BOTTOMLEFT", CORNER_W,
                       CORNER_W))
    proj = _project(tmp_path)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk", macros=macros, terminals=""))
    assert res.returncode == 1, res.stdout


# --------------------------------------------------------------------------- #
# the die the ring needs
# --------------------------------------------------------------------------- #
def test_the_die_is_the_three_terms_pad_ring_gen_subtracts(tmp_path):
    """THE ARITHMETIC, PINNED AGAINST ITS CONSUMER.

    `pad_ring_gen.side_width` computes, for each side,

        side = (die extent) - 2 * PAD_EDGE_SPACING - 2 * (corner extent)

    so a die sized without either term refuses a ring that fits. BOTH were
    measured as real refusals before this test existed: without the corner
    term the side came out negative on all four sides at once, and with the
    corner term but not the edge term the north side was short by exactly
    twice the library's declared 26 um spacing. This asserts the SAME three
    terms, computed from the fixture's own declared widths, so a change to
    either program that drops one of them reddens here.
    """
    proj = _project(tmp_path)
    assert _run(GEN, proj, _pdk(tmp_path / "pdk")).returncode == 0
    req = _record(proj)["die_required_um"]
    # The north side carries the 2-bit bus; the longest side decides the die.
    longest = 2 * PAD_W
    assert req["die_side_um"] == 2 * EDGE + 2 * CORNER_W + longest, req
    assert req["edge_spacing_um"] == EDGE
    assert req["corner_width_um"] == CORNER_W


def test_a_library_declaring_no_edge_spacing_contributes_zero_not_a_default(
        tmp_path):
    proj = _project(tmp_path)
    pdk = _pdk(tmp_path / "pdk", edge=0.0)
    assert _run(GEN, proj, pdk).returncode == 0
    req = _record(proj)["die_required_um"]
    assert req["edge_spacing_um"] == 0.0
    assert req["die_side_um"] == 2 * CORNER_W + 2 * PAD_W


# --------------------------------------------------------------------------- #
# THE BIDIRECTIONAL CONTROL
# --------------------------------------------------------------------------- #
def test_the_producer_closes_the_owed_set(tmp_path):
    """ONE tree, `pad_assignment_gen` twice, the producer's record the only
    difference.

    RED DIRECTION (the pre-fix state, reproduced rather than described): with
    no record, the four side lists and `SIGNAL_MAP` are owed and the program
    refuses — exactly what it reported for every design on the chip path.

    GREEN DIRECTION: with the record present, none of the five is owed.

    The assertion is on the OWED SET, not the exit code, so it stays a
    statement about these five variables even if another is owed for an
    unrelated reason.
    """
    proj = _project(tmp_path)
    pdk = _pdk(tmp_path / "pdk")
    report = proj / "pa.json"

    before = _run(ASSIGN, proj, pdk, ("--json", str(report)))
    assert before.returncode == 1, before.stdout
    owed_before = json.dumps(_owed(report))
    for var in INSTANCE_NAMED_VARS:
        assert var in owed_before, (var, owed_before)

    assert _run(GEN, proj, pdk).returncode == 0

    after = _run(ASSIGN, proj, pdk, ("--json", str(report)))
    owed_after = _owed(report)
    for var in INSTANCE_NAMED_VARS:
        assert not any(str(o).startswith(var) for o in owed_after), (
            f"{var} is still owed after the producer ran", owed_after)
    assert after.returncode == 0, after.stdout


def test_removing_the_record_puts_the_owed_set_back(tmp_path):
    """The control's other end, run as a MUTATION rather than asserted."""
    proj = _project(tmp_path)
    pdk = _pdk(tmp_path / "pdk")
    report = proj / "pa.json"
    assert _run(GEN, proj, pdk).returncode == 0
    assert _run(ASSIGN, proj, pdk, ("--json", str(report))).returncode == 0

    (proj / "reports" / "phase3" / "io_pad_chip_top.json").unlink()
    res = _run(ASSIGN, proj, pdk, ("--json", str(report)))
    assert res.returncode == 1
    owed = json.dumps(_owed(report))
    for var in INSTANCE_NAMED_VARS:
        assert var in owed, (var, owed)


def test_the_two_tcl_spelled_variables_are_resolved_and_checked(tmp_path):
    """`PAD_CORNER` and `PAD_FILLERS` are spelled with a Tcl substitution in
    the library's own config, so `parse_pad_env_declarations` correctly returns
    neither and they stayed owed. The producer expands the ONE substitution it
    has measured — the library the LEFs were read from — and publishes the
    result only after confirming it is a macro that library carries."""
    proj = _project(tmp_path)
    pdk = _pdk(tmp_path / "pdk")
    assert _run(GEN, proj, pdk).returncode == 0
    d = _record(proj)["derived_answers"]
    assert d["pad_corner_master"] == "testlib_io__cor"
    assert d["pad_fillers"] == ["testlib_io__fill"]


def test_a_corner_name_the_library_does_not_carry_is_not_published(tmp_path):
    """The other direction of the test above: the expansion is CHECKED, so a
    config naming a master the LEF has no MACRO for publishes nothing rather
    than a real-looking name."""
    proj = _project(tmp_path)
    root = tmp_path / "pdk"
    _pdk(root)
    cfg = root / "testpdk" / "libs.tech" / "someflow" / "testlib_io" / "config.tcl"
    cfg.write_text(cfg.read_text().replace("__cor", "__nosuchcorner"))
    assert _run(GEN, proj, root).returncode == 0
    assert _record(proj)["derived_answers"]["pad_corner_master"] is None


# --------------------------------------------------------------------------- #
# the conflict direction, at this producer's own call sites
#
# The producer folds every discovered IO LEF through `merge_source_records`
# twice -- once for the macro CLASSES, once for the macro SIZES -- and writes
# `on_conflict="richer"` at both. `policy_direction_pin_check` reported both
# sites UNPINNED on b309595f06 with ZERO candidate tests: no test file named
# this program together with the parameter or the callee, so nothing here could
# ever have died when the literal was flipped to `"sparser"`.
#
# ONE LEF IS NOT ENOUGH TO REACH THE PARAMETER, which is why the gap survived a
# file this size. Every fixture above ships a single library; a single source
# produces one `distinct` record per macro and `merge_source_records` returns
# it before `on_conflict` is read. Two libraries that both SPEAK about the same
# macro and disagree is the only input that reaches the branch, so that is what
# these build -- through the producer's CLI, in both discovery orders.
# --------------------------------------------------------------------------- #

#: Everything both libraries agree about in the two tests below.
AGREED_MACROS = (
    _macro("testlib_io__in", "PAD INPUT", PAD_W, 100.0, [("PAD", "SIGNAL")])
    + _macro("testlib_io__fill", "PAD SPACER", 1.0, 100.0)
    + _macro("testlib_io__cor", "ENDCAP BOTTOMLEFT", CORNER_W, CORNER_W)
)


def _pdk_two(root: Path, first: str, second: str, terminals: str) -> Path:
    """A PDK whose IO library ships TWO LEFs. `discover_io_lefs` returns them
    sorted by file name, so the caller decides the discovery order by choosing
    which text is written to which name."""
    lef = root / "testpdk" / "libs.ref" / "testlib_io" / "lef"
    lef.mkdir(parents=True)
    (lef / "a_first.lef").write_text(first)
    (lef / "z_second.lef").write_text(second)
    tech = root / "testpdk" / "libs.tech" / "someflow" / "testlib_io"
    tech.mkdir(parents=True)
    (tech / "config.tcl").write_text("\n".join([
        'set ::env(PAD_SITE_NAME) "IO_Site"',
        'set ::env(PAD_CORNER_SITE_NAME) "COR_Site"',
        f'set ::env(PAD_EDGE_SPACING) "{EDGE:g}"',
        'set ::env(PAD_CORNER) "$::env(PAD_CELL_LIBRARY)__cor"',
        'set ::env(PAD_FILLERS) "$::env(PAD_CELL_LIBRARY)__fill"',
        f'set ::env(PAD_PLACE_IO_TERMINALS) "{terminals}"']) + "\n")
    return root


def _both_orders(tmp_path: Path, rich: str, poor: str, terminals: str):
    """The producer run twice over the same two libraries, swapped."""
    out = []
    for i, (first, second) in enumerate(((rich, poor), (poor, rich))):
        proj = _project(tmp_path / f"run{i}")
        res = _run(GEN, proj, _pdk_two(tmp_path / f"pdk{i}", first, second,
                                       terminals))
        rec_path = proj / "reports" / "phase3" / "io_pad_chip_top.json"
        rec = json.loads(rec_path.read_text()) if rec_path.is_file() else {}
        out.append((res, rec))
    return out


def _masters(rec: dict):
    return sorted({r["master"] for r in (rec.get("pad_instances") or {}).values()})


def test_the_richer_class_record_is_what_makes_a_master_selectable(tmp_path):
    """SITE 1 -- the `parse_lef_macro_classes` fold.

    A macro record here is the CLASS STRING, so the fuller description is
    literally the longer one: one library calls `testlib_io__bi`
    `PAD INOUT`, the other only manages `PAD`. `CLASS_PREFERENCE` needs
    `PAD INOUT` for an output port, and `PAD` is not it. Keeping the fuller
    record instantiates the design; keeping the sparser one refuses it,
    NO_PAD_MASTER_FOR_DIRECTION, over a library that does carry the master.
    """
    rich = AGREED_MACROS + _macro("testlib_io__bi", "PAD INOUT", PAD_W, 100.0,
                                  [("PAD", "SIGNAL")])
    poor = AGREED_MACROS + _macro("testlib_io__bi", "PAD", PAD_W, 100.0,
                                  [("PAD", "SIGNAL")])
    terminals = "testlib_io__in/PAD testlib_io__bi/PAD"

    (res_a, rec_a), (res_b, rec_b) = _both_orders(
        tmp_path, rich, poor, terminals)

    assert res_a.returncode == 0, res_a.stdout + res_a.stderr
    assert res_b.returncode == 0, res_b.stdout + res_b.stderr
    assert _masters(rec_a) == _masters(rec_b) == ["testlib_io__bi",
                                                  "testlib_io__in"], (
        "the fuller CLASS record did not win the disagreement, in one order "
        "or in both")

    # The control: the sparser library ALONE really does refuse, so the
    # assertion above is about which record won and not about the fixture.
    proj = _project(tmp_path / "poor_alone")
    only = _run(GEN, proj, _pdk(tmp_path / "pdk_poor", macros=poor,
                               terminals=terminals))
    assert only.returncode == 1, only.stdout
    assert "NO_PAD_MASTER_FOR_DIRECTION" in only.stdout + only.stderr


def test_the_richer_size_record_decides_which_master_is_narrowest(tmp_path):
    """SITE 2 -- the `parse_lef_macros` fold, which is a SIZE and nothing else.

    A macro record here is a `(width, height)` pair of fixed arity, so "more
    content" is not what separates the two policies -- both are total orders
    over the same two numbers and `"richer"` takes the larger. It is still a
    direction and it is still observable: `_select_master` breaks a tie between
    two masters of the same class BY WIDTH, so which SIZE record won decides
    which master the design's output port is brought out on.

    Both libraries agree about every CLASS here. Only `testlib_io__bi`'s SIZE
    disagrees, so this site is measured on its own.
    """
    other = _macro("testlib_io__cb", "PAD INOUT", 50.0, 100.0,
                   [("PAD", "SIGNAL")])
    rich = AGREED_MACROS + other + _macro("testlib_io__bi", "PAD INOUT", 80.0,
                                          100.0, [("PAD", "SIGNAL")])
    poor = AGREED_MACROS + other + _macro("testlib_io__bi", "PAD INOUT", 20.0,
                                          100.0, [("PAD", "SIGNAL")])
    terminals = ("testlib_io__in/PAD testlib_io__bi/PAD "
                 "testlib_io__cb/PAD")

    (res_a, rec_a), (res_b, rec_b) = _both_orders(
        tmp_path, rich, poor, terminals)

    assert res_a.returncode == 0, res_a.stdout + res_a.stderr
    assert res_b.returncode == 0, res_b.stdout + res_b.stderr
    # 80 um wide beats 50, so the narrowest INOUT master is `__cb`.
    assert _masters(rec_a) == _masters(rec_b) == ["testlib_io__cb",
                                                  "testlib_io__in"], (
        "the larger (richer) SIZE record did not win the disagreement, in one "
        "order or in both")

    # The control: with the sparser record `__bi` is 20 um wide and wins the
    # same tie, so the assertion above is about which record won.
    proj = _project(tmp_path / "poor_alone")
    only = _run(GEN, proj, _pdk(tmp_path / "pdk_poor", macros=poor,
                                terminals=terminals))
    assert only.returncode == 0, only.stdout + only.stderr
    assert _masters(json.loads(
        (proj / "reports" / "phase3" / "io_pad_chip_top.json").read_text())
    ) == ["testlib_io__bi", "testlib_io__in"], (
        "precondition: the two SIZE records really do read differently")
