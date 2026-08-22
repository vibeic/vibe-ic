#!/usr/bin/env python3
"""#404 round 4 — the instrument E3d says a resolver must pass before it lands.

E3d's own text ends:

    "A resolver may only land here once this gate can CHECK the resolved value
     against a statement the resolver did not write; until then the resolution
     is reported, not trusted."

That statement exists, and it is in the published tree. The design's shipped
netlists declare every top-level port at a width synthesis already elaborated:

    benchmark-data/ic/spm/v1.5.66_gf180mcuD/phase2/stage2/synth/netlist.v:8
        input [31:0] x;

against an L9 entry that says `size-1:0`.

WHAT THIS IS NOT
================
It is NOT an oracle, and claiming otherwise would be the same overclaim #404
withdrew a resolver for. `phase2/stage1/rtl/spm.v` opens

    // Authored from the L1-L9 design documents only (clean-room, §4.05).

so the RTL is DOWNSTREAM of the very L9 entry under test and synthesis is
downstream of that. If L9 is wrong the netlist inherits the error, and
agreement proves nothing.

    IT CAN PROVE A RESOLUTION WRONG. IT CANNOT PROVE ONE RIGHT.

That asymmetry is the whole value. #404's worst measured failure — an L12
scan-chain `N = 4` sizing a data bus the design documents and ships as 32 —
produced a number no artefact in the tree agreed with, and nothing noticed.
Against the shipped netlist it is a contradiction. "Indistinguishable" becomes
"distinguishable in the failing direction", which is the direction that
matters, and the corroborating half stays honest: agreement does NOT clear the
finding.

MEASURED over the published corpus (15 cells with an L9):

    multiple netlists agree on every port      10
    no published netlist                        4   -> {} , never a pass
    one file, same port name at two widths      1   -> ibex, see below

The last one changed the design. `ibex` declares `multdiv_operand_a_i` at 32
AND 33 bits in ONE file, because a port name is unique only within a module.
A whole-file scan would have manufactured a contradiction on a clean design.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
_GATE = importlib.import_module("l17_channel_catalog_consumer_contract_check")

_CORPUS = _PROGRAMS.parents[3] / "benchmark-data" / "ic"


def _publish(d: Path, rels) -> None:
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    for r in rels:
        subprocess.run(["git", "-C", str(d), "add", r], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", "publish"], check=True)


def _write(d: Path, rel: str, body: str) -> str:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return rel


def _netlist(module: str, ports: str, extra: str = "") -> str:
    return f"module {module}(...);\n{ports}\nendmodule\n{extra}"


# ── the reader ─────────────────────────────────────────────────────────────
def test_an_elaborated_width_is_read_off_the_top_module(tmp_path):
    """THE LOAD-BEARING CASE — the real shape, `input [31:0] x;`."""
    d = tmp_path / "cell"
    rel = _write(d, "phase2/stage2/synth/netlist.v",
                 _netlist("spm", "  input [31:0] x;\n  output p;\n"))
    _publish(d, [rel])
    assert _GATE.shipped_netlist_port_widths(d) == {"x": 32, "p": 1}


def test_a_port_name_that_is_not_unique_across_modules_is_refused(tmp_path):
    """The shape `ibex` has: the same port name at 32 and 33 bits in ONE file,
    in two different modules.

    Note honestly what this pins and what it does not. TWO independent rules
    produce `{}` here — module scoping, and the "two answers means no answer"
    filter — so a mutant that removes only the first still passes this. The
    discriminators for module scoping are
    `test_the_top_is_the_module_nothing_instantiates` and the real-data
    `test_ibex_is_refused_on_real_data`; both red when it is removed. This test
    pins the OUTCOME on the shape that motivated the design."""
    d = tmp_path / "cell"
    rel = _write(d, "phase2/stage2/synth/netlist.v",
                 _netlist("core", "  input [31:0] op_a;\n")
                 + _netlist("alu", "  input [32:0] op_a;\n"))
    _publish(d, [rel])
    # Neither module instantiates the other, so there is no unique top and the
    # file says nothing — rather than saying two things.
    assert _GATE.shipped_netlist_port_widths(d) == {}


def test_the_top_is_the_module_nothing_instantiates(tmp_path):
    """With a real hierarchy the answer is the TOP's ports, not the leaf's."""
    d = tmp_path / "cell"
    rel = _write(d, "phase2/stage2/synth/netlist.v",
                 _netlist("top", "  input [31:0] x;\n  leaf u0 (.a(x));\n")
                 + _netlist("leaf", "  input [7:0] a;\n"))
    _publish(d, [rel])
    assert _GATE.shipped_netlist_port_widths(d) == {"x": 32}


def test_two_netlists_that_disagree_are_not_evidence(tmp_path):
    """The same refusal one level up: if the tree ships two answers, it has
    none."""
    d = tmp_path / "cell"
    rels = [_write(d, "phase2/stage2/synth/a_netlist.v",
                   _netlist("spm", "  input [31:0] x;\n")),
            _write(d, "phase2/stage2/synth/b_netlist.v",
                   _netlist("spm", "  input [15:0] x;\n"))]
    _publish(d, rels)
    assert _GATE.shipped_netlist_port_widths(d) == {}


def test_an_untracked_netlist_is_not_read(tmp_path):
    """#447: the question is what a reader RECEIVES, not what is on this
    disk. A published cell with an untracked leftover must answer from the
    published file."""
    d = tmp_path / "cell"
    rel = _write(d, "phase2/stage2/synth/netlist.v",
                 _netlist("spm", "  input [31:0] x;\n"))
    _publish(d, [rel])
    _write(d, "phase2/stage2/synth/scratch_netlist.v",
           _netlist("spm", "  input [3:0] x;\n"))     # after the commit
    assert _GATE.shipped_netlist_port_widths(d) == {"x": 32}


def test_a_netlist_reached_through_a_tracked_link_is_not_read(tmp_path):
    """#404 — the same #447 question, through the door the PATH filter left
    open.

    The link IS tracked, so the path filter above waves it through, and the
    reader then DEREFERENCES it into a target the tree does not carry. A
    clean clone gets a dangling link and answers `{}`; a host that kept its
    run output answers 4. Same commit, two answers.

    MEASURED on this repo when this landed: 172 tracked symlinks, 43 pointing
    outside the index, 6 of them `.v` files this very reader globs — which
    made 3 of 15 published cells answer differently on the two trees.

    The assertion is `{}`, the clean-clone answer, WITH the target present on
    disk — so a reader that still dereferences fails here rather than passing
    for the wrong reason."""
    d = tmp_path / "cell"
    _write(d, "run_output/netlist.v", _netlist("m", "  input [3:0] x;\n"))
    link = d / "phase2" / "stage2" / "synth" / "netlist.v"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to("../../../run_output/netlist.v")
    _publish(d, ["phase2/stage2/synth/netlist.v"])       # the LINK, not target
    assert link.read_text().strip().endswith("endmodule")   # readable HERE
    assert _GATE.shipped_netlist_port_widths(d) == {}


def test_a_netlist_reached_through_a_link_the_tree_DOES_carry_is_read(tmp_path):
    """The paired half. 128 of this repo's 172 tracked links point at tracked
    files; refusing those would drop content a clean clone does receive."""
    d = tmp_path / "cell"
    _write(d, "run_output/netlist.v", _netlist("m", "  input [3:0] x;\n"))
    link = d / "phase2" / "stage2" / "synth" / "netlist.v"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to("../../../run_output/netlist.v")
    _publish(d, ["run_output/netlist.v", "phase2/stage2/synth/netlist.v"])
    assert _GATE.shipped_netlist_port_widths(d) == {"x": 4}


def test_no_published_netlist_yields_nothing_not_a_default(tmp_path):
    """4 of 15 corpus cells ship none. `{}` leaves every rail exactly as it
    was; a default would have invented agreement."""
    d = tmp_path / "cell"
    rel = _write(d, "phase1/generated_docs/L1_DATASHEET.json", "{}")
    _publish(d, [rel])
    assert _GATE.shipped_netlist_port_widths(d) == {}


# ── the rail ───────────────────────────────────────────────────────────────
def _project(tmp_path: Path, ports, netlist: str = None, parameters=None) -> Path:
    d = tmp_path / "cell"
    gd = d / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "dut"}))
    body = {"top_ports": ports}
    if parameters is not None:
        body["parameters"] = parameters
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": body}))
    (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(
        json.dumps({"fields": {"channels": []}}))
    if netlist is not None:
        _write(d, "phase2/stage2/synth/netlist.v", netlist)
    return d


def _resolver_writing(value):
    original = _GATE._consumer.derive_signals

    def resolving(l17, l9):
        signals = original(l17, l9)
        for sig in signals:
            if sig.get("width") is None:
                sig["width"] = value
        return signals
    return resolving


def _categories(project):
    findings, _info = _GATE.audit(project)
    return [f.category for f in findings]


_SYMBOLIC = [{"name": "acc_o", "direction": "output",
              "width": "the accumulator is 48 bits in this configuration",
              "width_symbolic": "ACC_W-1:0"}]


def test_a_resolution_the_shipped_netlist_refutes_is_CONTRADICTED(
        tmp_path, monkeypatch):
    """THE LOAD-BEARING CASE for the rail — #404's own worst failure, now
    caught. A resolver writes 4; the design ships the port at 48."""
    project = _project(tmp_path, _SYMBOLIC,
                       netlist=_netlist("dut", "  output [47:0] acc_o;\n"),
                       parameters=[{"name": "ACC_W", "default": "4"}])
    monkeypatch.setattr(_GATE._consumer, "derive_signals", _resolver_writing(4))
    cats = _categories(project)
    assert "PORT_WIDTH_CONTRADICTS_SHIPPED_NETLIST" in cats, cats
    assert "PORT_WIDTH_SYMBOL_UNCORROBORATED" not in cats, cats


def test_agreement_does_NOT_clear_the_finding(tmp_path, monkeypatch):
    """THE HONEST HALF, and the one that keeps this from becoming an oracle.
    The netlist is authored downstream of the layer under test, so a matching
    number is not proof. The resolution stays UNCORROBORATED — reported, not
    trusted. If this ever goes silent, a resolver has bought a green light."""
    project = _project(tmp_path, _SYMBOLIC,
                       netlist=_netlist("dut", "  output [47:0] acc_o;\n"),
                       parameters=[{"name": "ACC_W", "default": "48"}])
    monkeypatch.setattr(_GATE._consumer, "derive_signals", _resolver_writing(48))
    cats = _categories(project)
    assert "PORT_WIDTH_SYMBOL_UNCORROBORATED" in cats, cats
    assert "PORT_WIDTH_CONTRADICTS_SHIPPED_NETLIST" not in cats, cats


def test_without_a_netlist_the_rail_behaves_exactly_as_before(
        tmp_path, monkeypatch):
    """Regression guard for the 4 corpus cells that publish none."""
    project = _project(tmp_path, _SYMBOLIC,
                       parameters=[{"name": "ACC_W", "default": "4"}])
    monkeypatch.setattr(_GATE._consumer, "derive_signals", _resolver_writing(4))
    cats = _categories(project)
    assert "PORT_WIDTH_SYMBOL_UNCORROBORATED" in cats, cats
    assert "PORT_WIDTH_CONTRADICTS_SHIPPED_NETLIST" not in cats, cats


def test_the_current_consumer_still_reports_UNRESOLVED_and_names_the_width(
        tmp_path):
    """The rail that fires TODAY. The consumer refuses (correctly), and the
    finding now carries the width the design SHIPS — turning "state the width
    as an integer" into a sentence a reader can act on."""
    project = _project(tmp_path, _SYMBOLIC,
                       netlist=_netlist("dut", "  output [47:0] acc_o;\n"))
    findings, _ = _GATE.audit(project)
    row = [f for f in findings
           if f.category == "PORT_WIDTH_UNRESOLVED_BY_CONSUMER"]
    assert row, [f.category for f in findings]
    assert row[0].evidence["ports"][0]["shipped_netlist_width"] == 48


# ── real data ──────────────────────────────────────────────────────────────
def test_the_three_spm_cells_carry_the_shipped_width_as_evidence():
    """Real corpus. These are the cells `cross_layer_reference_check` has been
    failing on since v1.6.90, and the number they ship is 32."""
    if not _CORPUS.is_dir():
        pytest.skip("published corpus not checked out")
    cells = ("spm/v1.5.58_ihp-sg13g2", "spm/v1.10.18_sky130A",
             "spm/v1.9.96_gf180mcuD")
    seen, absent = 0, []
    for name in cells:
        d = _CORPUS / name
        if not d.is_dir():
            absent.append(name)
            continue
        seen += 1
        assert _GATE.shipped_netlist_port_widths(d).get("x") == 32, name
        findings, _ = _GATE.audit(d)
        rows = [f for f in findings
                if f.category == "PORT_WIDTH_UNRESOLVED_BY_CONSUMER"]
        assert rows, (name, [f.category for f in findings])
        port = rows[0].evidence["ports"][0]
        assert port["port"] == "x"
        assert port["shipped_netlist_width"] == 32, (name, port)
    if seen == 0:
        pytest.skip("spm cells not checked out")
    # DERIVED FROM THE ROSTER ABOVE, not typed beside it. The literal `3` was
    # `len(cells)` written a second time, so editing the roster silently made
    # the two disagree — and when a cell was withdrawn the message said "only 2
    # of 3" without naming which. The claim is unchanged: this test names
    # specific cells and a missing one is a real finding, not a smaller run.
    assert seen == len(cells), (
        f"{len(absent)} of the {len(cells)} cell(s) this test names are no "
        f"longer published: {absent}. Either they were withdrawn — in which "
        f"case pick their successors — or the roster is stale.")


def test_ibex_is_refused_on_real_data():
    """The false positive this design exists to avoid, on the design that
    produced it."""
    d = _CORPUS / "ibex"
    if not d.is_dir():
        pytest.skip("ibex not checked out")
    assert _GATE.shipped_netlist_port_widths(d) == {}
