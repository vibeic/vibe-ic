"""Unit tests for `analog_a3_netlist_emit` — the A3 netlist PRODUCER.

THE ONE THAT MATTERS
====================
`test_a_block_with_no_extractable_spec_yields_no_netlist` is the control that
stops this becoming a fancier template table. Two blocks of the SAME circuit
class sit side by side; one carries a bound spec and one does not. The
topology library could render both — and rendering the second would produce a
`.sp` that passes the A3 gate, passes all four netlist checkers, simulates,
and is about the template. It must not appear ANYWHERE in the tree.

`test_the_producer_has_no_netlist_of_its_own_to_fall_back_on` is the same
property from the other side: remove the A2 IR and the producer has nothing
left to emit, because it holds no per-type deck table.

Nothing here reaches into the producer's internals: the programs are driven
as subprocesses and every assertion is about an artefact on disk or the rc of
a shipped checker.
"""
from __future__ import annotations

import json
import os

import pytest

from not_verified_tier import PROBE_PRESENT, probe, probe_skip_reason
from _analog_producer_fixture import (
    A1, A2, A3, GATE_A3, NETLIST_CHECKERS, block, make_project, run_prog,
    bdir, read_json, all_sp_files)

LDO_SPEC = [{"name": "Vout", "target": 1.8, "unit": "V"},
            {"name": "Vin", "target": 3.0, "unit": "V"}]
LDO_SPEC_WITH_REF = LDO_SPEC + [{"name": "Vref", "target": 0.6, "unit": "V"}]


def _emit(tmp_path, blocks, *a3args):
    p = make_project(tmp_path, blocks)
    run_prog(A1, p)
    run_prog(A2, p)
    return p, run_prog(A3, p, *a3args)


# ═══ THE CONTROL ═══════════════════════════════════════════════════════════
def test_a_block_with_no_extractable_spec_yields_no_netlist(tmp_path):
    p, cp = _emit(tmp_path, [
        block("vreg_alpha", "ldo", LDO_SPEC),
        block("vreg_beta", "ldo", specs=None),      # same class, no number
    ])
    assert cp.returncode == 0, cp.stderr

    # The library COULD have rendered the second block: it has a topology.
    assert (bdir(p, "vreg_beta") / "topology.json").is_file(), (
        "this test is only meaningful if the topology was available and the "
        "producer declined anyway")

    emitted = {f.name for f in all_sp_files(p)}
    assert "vreg_alpha.sp" in emitted
    assert not any(f.startswith("vreg_beta") for f in emitted), (
        f"a netlist was emitted for a block with no bound spec: {emitted}. "
        f"It would pass every gate and every number it produced would be "
        f"about the template.")

    gap = read_json(bdir(p, "vreg_beta") / "netlist_gap.json")
    assert gap["status"] == "NO_SPEC_NO_NETLIST"
    assert gap["netlist_written"] is False
    assert gap["topology_available"] is True, (
        "the gap must say the topology WAS available, or a reader cannot "
        "tell a declined render from a missing upstream")
    assert gap["ai_handoff"]["skill"] == "analog-netlist-gen"
    assert gap["unblocked_by"]

    # And the gate keeps reporting the honest deferral, not a defect.
    assert run_prog(GATE_A3, p, "--block", "vreg_beta").returncode == 2
    assert run_prog(GATE_A3, p, "--block", "vreg_alpha").returncode == 0


def test_the_producer_has_no_netlist_of_its_own_to_fall_back_on(tmp_path):
    """Spec present, A2 IR removed. A producer carrying a per-block-type deck
    table would still emit something here; this one must not."""
    p, _ = _emit(tmp_path, [block("vreg_alpha", "ldo", LDO_SPEC)])
    (bdir(p, "vreg_alpha") / "topology.json").unlink()
    (bdir(p, "vreg_alpha") / "vreg_alpha.sp").unlink()

    cp = run_prog(A3, p)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert not (bdir(p, "vreg_alpha") / "vreg_alpha.sp").exists()
    gap = read_json(bdir(p, "vreg_alpha") / "netlist_gap.json")
    assert gap["status"] == "NO_TOPOLOGY_IR"


# ═══ the positive case, judged by the shipped checkers ═════════════════════
def test_the_emitted_netlist_passes_the_a3_gate_and_all_four_checkers(tmp_path):
    p, cp = _emit(tmp_path, [block("vreg_alpha", "ldo", LDO_SPEC)])
    assert cp.returncode == 0, cp.stderr
    sp = bdir(p, "vreg_alpha") / "vreg_alpha.sp"
    assert sp.is_file()

    gate = run_prog(GATE_A3, p, "--block", "vreg_alpha")
    assert gate.returncode == 0, gate.stdout + gate.stderr
    for checker in NETLIST_CHECKERS:
        r = run_prog(checker, p)
        assert r.returncode == 0, (
            f"{checker.name} rejected the emitted netlist: "
            f"{r.stdout}{r.stderr}")

    text = sp.read_text(encoding="utf-8")
    assert ".subckt vreg_alpha" in text and ".ends vreg_alpha" in text
    assert "/foss/pdks/" in text, "no model library include"
    assert ".end\n" not in text.replace(".ends", ""), (
        "an included subcircuit file must not carry a terminating .end — it "
        "truncates the testbench that includes it")
    # Passives are PDK subcircuits, not R/C cards: the connectivity checker
    # parses only X cards with >= 3 nets.
    body = [ln for ln in text.splitlines()
            if ln and ln[0].lower() in "rcm" and not ln.startswith("*")]
    assert not body, f"primitive device cards leaked into the netlist: {body}"


def test_the_netlist_carries_provenance_naming_its_two_inputs(tmp_path):
    p, _ = _emit(tmp_path, [block("vreg_alpha", "ldo", LDO_SPEC)])
    d = bdir(p, "vreg_alpha")
    header = (d / "vreg_alpha.sp").read_text(encoding="utf-8")
    for needle in ("_provenance: producer=analog_a3_netlist_emit",
                   "topology.json sha256=", "spec.json sha256=",
                   "_provenance: design_content=",
                   "_provenance: library_nominal_params=",
                   "_provenance: model_lib=",
                   "_provenance: simulation_verified="):
        assert needle in header, f"the netlist header does not state `{needle}`"

    side = read_json(d / "netlist_provenance.json")["_provenance"]
    assert side["has_own_netlist_template"] is False
    assert side["rendered_from"]["topology_json"]["sha256"]
    assert side["rendered_from"]["spec_json"]["sha256"]
    assert side["design_content"] in ("structure_only",
                                      "structure_and_geometry")
    assert side["design_content_meaning"]


def test_an_unsized_netlist_records_the_sizing_handoff_it_did_not_do(tmp_path):
    """Every device parameter the bound spec did not reach is unsolved
    SIZING. A netlist that converges reads as a netlist that was designed
    unless the artefact names what it did not do, and who does it."""
    p, _ = _emit(tmp_path, [block("vreg_alpha", "ldo", LDO_SPEC)])
    prov = read_json(bdir(p, "vreg_alpha")
                     / "netlist_provenance.json")["_provenance"]
    ho = prov["ai_handoff"]
    assert ho and ho["skill"] == "analog-sizing", prov
    assert ho["scope"] == "device_geometry"
    assert ho["unsized_params"] == prov["library_nominal_params"]
    assert ho["unsized_params"], "an all-nominal netlist claimed nothing was "\
                                 "left unsized"


def test_design_content_distinguishes_a_sized_netlist_from_a_class_one(tmp_path):
    """Vout alone cannot fix the divider ratio, so nothing reaches the
    devices and the artefact must say `structure_only`. Add the reference and
    a device parameter really is solved against the spec — and the geometry
    changes."""
    a, _ = _emit(tmp_path / "a", [block("vreg_alpha", "ldo", LDO_SPEC)])
    pa = read_json(bdir(a, "vreg_alpha") / "netlist_provenance.json")
    assert pa["_provenance"]["design_content"] == "structure_only"
    assert pa["_provenance"]["spec_bound_params"] == []

    b, _ = _emit(tmp_path / "b", [block("vreg_alpha", "ldo",
                                        LDO_SPEC_WITH_REF)])
    pb = read_json(bdir(b, "vreg_alpha") / "netlist_provenance.json")
    assert pb["_provenance"]["design_content"] == "structure_and_geometry"
    assert pb["_provenance"]["spec_bound_params"] == ["r1.l"]

    def divider(project):
        for ln in (bdir(project, "vreg_alpha")
                   / "vreg_alpha.sp").read_text().splitlines():
            if ln.startswith("xr1 "):
                return ln
        return ""
    assert divider(a) != divider(b), (
        "the bound reference changed the divider ratio and the netlist is "
        "byte-identical — no spec value actually reached a device")


# ═══ rejection paths: a bad netlist is never left on disk ══════════════════
def _mutate_ir(project, blockname, fn):
    p = bdir(project, blockname) / "topology.json"
    ir = json.loads(p.read_text())
    fn(ir)
    p.write_text(json.dumps(ir, indent=2))
    sp = bdir(project, blockname) / f"{blockname}.sp"
    if sp.is_file():
        sp.unlink()


def test_an_internal_net_visible_to_no_checker_is_rejected_before_emission(
        tmp_path):
    """A 2-terminal device is invisible to the connectivity parser. If the
    only OTHER pin on an internal net comes from one, the net reads as
    FLOATING_NODE. The producer must catch that itself rather than ship a
    netlist a checker will reject."""
    p, _ = _emit(tmp_path, [block("vreg_alpha", "ldo", LDO_SPEC)])

    def mutate(ir):
        # Turn the 3-terminal divider legs into 2-terminal caps so `vfb`
        # loses every visible pin but the differential-pair gate.
        for d in ir["devices"]:
            if d["name"] in ("r1", "r2"):
                d["role"] = "cap"
                d["nets"] = d["nets"][:2]
    _mutate_ir(p, "vreg_alpha", mutate)

    cp = run_prog(A3, p)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert not (bdir(p, "vreg_alpha") / "vreg_alpha.sp").exists()
    gap = read_json(bdir(p, "vreg_alpha") / "netlist_gap.json")
    assert gap["status"] == "IR_NOT_RENDERABLE"
    assert any("FLOATING_NODE" in s for s in gap["problems"]), gap["problems"]


def test_a_wrong_terminal_count_is_rejected_before_ngspice_sees_it(tmp_path):
    p, _ = _emit(tmp_path, [block("vreg_alpha", "ldo", LDO_SPEC)])

    def mutate(ir):
        for d in ir["devices"]:
            if d["role"] == "nmos":
                d["nets"] = d["nets"][:3]
    _mutate_ir(p, "vreg_alpha", mutate)

    cp = run_prog(A3, p)
    assert cp.returncode == 2
    assert not (bdir(p, "vreg_alpha") / "vreg_alpha.sp").exists()
    assert read_json(bdir(p, "vreg_alpha")
                     / "netlist_gap.json")["status"] == "IR_NOT_RENDERABLE"


def test_a_pmos_body_off_the_rail_is_rejected(tmp_path):
    p, _ = _emit(tmp_path, [block("vreg_alpha", "ldo", LDO_SPEC)])

    def mutate(ir):
        for d in ir["devices"]:
            if d["role"] == "pmos":
                d["nets"][-1] = ir["rails"]["vss"]
    _mutate_ir(p, "vreg_alpha", mutate)

    cp = run_prog(A3, p)
    assert cp.returncode == 2
    assert not (bdir(p, "vreg_alpha") / "vreg_alpha.sp").exists()


# ═══ the simulator is a capability, not a verdict ══════════════════════════
def test_an_unreachable_simulator_is_recorded_and_not_faked(tmp_path):
    p, cp = _emit(tmp_path, [block("vreg_alpha", "ldo", LDO_SPEC)],
                  "--verify-sim", "--container",
                  "a13_no_such_container_exists")
    assert cp.returncode == 0, (
        "an unreachable container is a capability gap; it must not turn A3 "
        "into a failure the checkers did not find")
    sim = read_json(bdir(p, "vreg_alpha")
                    / "netlist_provenance.json")["verification"]["simulation"]
    assert sim["simulation_verified"] is False
    assert sim["simulation_status"] == "NOT_VERIFIED_NO_SIMULATOR"
    assert ("simulation_verified=False status=NOT_VERIFIED_NO_SIMULATOR"
            in (bdir(p, "vreg_alpha") / "vreg_alpha.sp").read_text()), (
        "an unsimulated deck must say so in its own header, or a reader will "
        "take a converging-looking netlist for a converged one")


# vibe-ic#1283 — tri-state, not bool. The `except Exception: return False` this
# replaces recorded a probe that never finished as a container that is not
# there, so a saturated host silently turned the only ngspice-backed proof in
# this file into a green skip that claimed a fact about the host.
_CONTAINER_NAME = os.environ.get("VIBEIC_ANALOG_CONTAINER", "vibeic-eda")
_CONTAINER_STATE, _CONTAINER_DETAIL = probe(
    ["docker", "exec", _CONTAINER_NAME, "true"])
RUN_REMEDY = "bash tools/vibeic-eda/restart-eda.sh"


@pytest.mark.skipif(
    _CONTAINER_STATE != PROBE_PRESENT,
    reason=probe_skip_reason(_CONTAINER_STATE, _CONTAINER_DETAIL,
                             "EDA container with ngspice not reachable",
                             RUN_REMEDY))
def test_every_library_class_renders_a_netlist_that_actually_converges(
        tmp_path):
    """The acceptance bar for a topology-library entry is ngspice, not a
    gate. Each class here carries a bound spec so A3 will render it."""
    p, cp = _emit(tmp_path, [
        block("vreg_alpha", "ldo", LDO_SPEC),
        block("blk_alpha", "comparator",
              [{"name": "Vindiff", "target": 0.02, "unit": "V"}]),
        block("keeper_x", "pull", [{"name": "Reff", "target": 50000.0,
                                    "unit": "ohm"}]),
        block("tick_src", "oscillator", [{"name": "Vref", "target": 0.9,
                                          "unit": "V"}]),
    ], "--verify-sim")
    assert cp.returncode == 0, cp.stderr
    for name in ("vreg_alpha", "blk_alpha", "keeper_x", "tick_src"):
        side = read_json(bdir(p, name) / "netlist_provenance.json")
        sim = side["verification"]["simulation"]
        assert sim["simulation_status"] == "CONVERGED", (name, sim)
        assert sim["measurements"], (
            f"{name} converged and produced no measurement — a run that "
            f"measures nothing proves nothing")
