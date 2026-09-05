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
    """An internal net the connectivity checker would call FLOATING_NODE must
    be caught HERE, by the producer, rather than shipped for a checker to
    reject.

    ROUND 17 — THE MUTATION CHANGED, AND WHY. This test used to turn the
    3-terminal divider legs into 2-terminal caps, on the premise that "a
    2-terminal device is invisible to the connectivity parser". It is not,
    and has not been since `analog_netlist_connectivity_check._device_nets`
    was corrected to parse a two-net device — the whole point of that fix was
    that a switched-capacitor circuit, where the signal ENTERS through a
    capacitor, is not a defect. This file's pre-check kept the old floor of 3
    as a literal and so did this test, and together they refused a netlist the
    checker itself accepts (measured: a modulator's summing node, reached by a
    transistor gate and two capacitor plates, reported IR_NOT_RENDERABLE).

    The floor now comes from `analog_netlist_connectivity_check.
    MIN_DEVICE_NETS`, so the mutation here makes a node that is genuinely
    touched ONCE — which is what FLOATING_NODE means and has always meant.
    """
    p, _ = _emit(tmp_path, [block("vreg_alpha", "ldo", LDO_SPEC)])

    def mutate(ir):
        # Move ONE terminal of ONE device onto a fresh internal net, so that
        # net is touched by exactly one device pin and by nothing else.
        ir["internal_nets"] = list(ir["internal_nets"]) + ["n_orphan"]
        for d in ir["devices"]:
            if d["name"] == "r1":
                d["nets"] = ["n_orphan"] + list(d["nets"][1:])
                break
    _mutate_ir(p, "vreg_alpha", mutate)

    cp = run_prog(A3, p)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert not (bdir(p, "vreg_alpha") / "vreg_alpha.sp").exists()
    gap = read_json(bdir(p, "vreg_alpha") / "netlist_gap.json")
    assert gap["status"] == "IR_NOT_RENDERABLE"
    assert any("FLOATING_NODE" in s for s in gap["problems"]), gap["problems"]
    assert any("n_orphan" in s for s in gap["problems"]), gap["problems"]


def test_a_capacitor_terminated_internal_net_is_NOT_rejected(tmp_path):
    """The CONTROL for the row above, and the shape the old premise refused: a
    node reached by a transistor gate and two capacitor plates is a
    switched-capacitor summing node, not a floating one, and the producer must
    emit it."""
    p, _ = _emit(tmp_path, [block("vreg_alpha", "ldo", LDO_SPEC)])

    def mutate(ir):
        for d in ir["devices"]:
            if d["name"] in ("r1", "r2"):
                d["role"] = "cap"
                d["nets"] = d["nets"][:2]
    _mutate_ir(p, "vreg_alpha", mutate)

    cp = run_prog(A3, p)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert (bdir(p, "vreg_alpha") / "vreg_alpha.sp").is_file()


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


# ═══ THE SWITCHED-CAPACITOR INTEGRATOR IS ACTUALLY SWITCHED ════════════════
# WHY THIS IS HERE AND NOT A STRING MATCH. The `delta_sigma` entry emitted an
# integrator whose sampling and feedback capacitors were HARD-WIRED to the
# summing node: only their far plates were switched. That is not an SC
# integrator. Each capacitor delivers +C*(V-vcm) on one clock edge and takes
# the same charge straight back on the next, so the NET transfer per clock
# PERIOD is zero and the loop filter does not accumulate.
#
# MEASURED, ngspice, on the deck this producer emits: the last integrator's
# output sampled at one fixed clock phase moved -2.1 uV per clock over the
# first 16 clocks of every conversion window where the capacitor ratio demands
# +2431 uV — one part in a thousand, and the wrong sign. With the summing-node
# plates switched and nothing else changed, the same measurement on the same
# deck reads thousands of uV per clock with the sign charge conservation
# requires for this branch, repeatable to 0.1 uV across windows.
#
# The assertion is a property of the emitted TOPOLOGY, not of the deck's text:
# a rename, a re-ordering, a different PDK's device names or a different stage
# count all leave it standing, and it can only be satisfied by wiring the
# circuit correctly.
_SC_RAILS = frozenset({"vdd", "vss", "0"})


def _sp_cards(sp_text):
    """`([(name, [nets])], {ports})` for the `X` cards of one deck. Geometry
    (`w=`/`l=`) is dropped, so the last remaining token is the model and the
    ones before it are the nets — the same shape every PDK binding produces."""
    ports, devs = set(), []
    for ln in sp_text.splitlines():
        s = ln.strip()
        if s.lower().startswith(".subckt"):
            ports |= set(s.split()[2:])
        elif s.lower().startswith("x"):
            toks = s.split()
            devs.append((toks[0], [t for t in toks[1:] if "=" not in t][:-1]))
    return devs, ports


def _switch_groups(mos, excl):
    """`{frozenset(drain, source): {gate: body}}` — one entry per switch GROUP,
    so the two halves of a CMOS transmission gate collapse into one throw.

    Only PASS devices are groups: both drain and source non-rail. That excludes
    every amplifier device, whose source is a rail, so an output node is not
    mistaken for a switched one.

    The gate is kept PER DEVICE with its BODY, not merged into a set. That
    distinction is the whole point: both halves of every transmission gate here
    carry the same two gate nets, so a throw identified only by `{clk, nclkb}`
    is indistinguishable from any other throw — including one wired to conduct
    on the SAME phase, which shorts the summing node to the reference instead
    of alternating with it. Keeping the body lets `_n_gate` recover which half
    is the n-channel one, and THAT is what carries the phase."""
    groups = {}
    for _n, nets in mos:
        if nets[0] in _SC_RAILS or nets[2] in _SC_RAILS:
            continue
        groups.setdefault(frozenset((nets[0], nets[2])), {})[nets[1]] = nets[3]
    return groups


def _n_gate(throw):
    """The gate net of a throw's N-CHANNEL half, by the file's own body rule
    (NMOS bodies to ground, PMOS bodies to the positive rail). `None` when the
    throw is not a transmission gate whose halves sit on different bodies."""
    ns = [g for g, body in throw.items() if body == "vss"]
    return ns[0] if len(ns) == 1 else None


def _two_position(node, groups):
    """The throws of `node` if it is a TWO-POSITION switch, else `{}`.

    `{far node: n-gate}` for every switch group joining `node` to a non-RAIL
    node. Ports are throws like any other: the first stage samples the block's
    own input pin, so excluding ports here would drop the very branch the
    change is about. A node with fewer than two throws is not a switch at all —
    it is welded to whatever it reaches, which is the defect this file exists
    to catch."""
    throws = {}
    for k, gates in groups.items():
        if node not in k:
            continue
        far = next(iter(k - {node}), None)
        if far is None or far in _SC_RAILS:
            continue
        throws[far] = _n_gate(gates)
    return throws if len(throws) >= 2 else {}


def sc_integrator_report(sp_text):
    """Every switched-capacitor CHARGE BRANCH in a deck, found STRUCTURALLY.

    A summing node `S` is a node that is (a) a transistor GATE — the
    amplifier's inverting input, (b) one plate of a capacitor whose other plate
    `O` is NOT a gate — the amplifier's output, and (c) shorted to that same `O`
    by a switch — the per-conversion reset across the integrating capacitor.
    Nothing else in a modulator has that shape, so no device or net NAME is
    needed to find it.

    A BRANCH capacitor is then found from its BOTTOM plate, never from the
    summing node: a capacitor one of whose plates is a two-position switched
    node. That enumeration is the load-bearing choice. Enumerating instead the
    capacitors that already reach `S` through a switch makes the branch whose
    switches are MISSING invisible to the report, so the check passes exactly
    the topology it exists to reject.

    For each branch the report gives what the parasitic-insensitive
    arrangement requires and nothing weaker:
      * `top_throws`  — the summing-node plate must ALSO be two-position
        switched. If it is not, the plate is welded and the branch returns its
        charge on the next half cycle.
      * `reaches`     — one of those throws must be a summing node.
      * `reference`   — the other throw must be the SAME node the bottom plate
        returns to. A plate that "samples" against an arbitrary internal node,
        or against the capacitor's own other plate, moves no charge.
      * `complementary` — the two throws must conduct on OPPOSITE phases,
        compared by the n-channel half's gate. Two throws on the same phase
        short the summing node to the reference.
    """
    devs, ports = _sp_cards(sp_text)
    excl = _SC_RAILS | ports
    caps = [(n, nets) for n, nets in devs if len(nets) == 2]
    mos = [(n, nets) for n, nets in devs if len(nets) == 4]
    gates = {nets[1] for _n, nets in mos}
    groups = _switch_groups(mos, excl)

    summing = {}
    for cn, (a, b) in caps:
        for S, O in ((a, b), (b, a)):
            if S in excl or O in excl or S not in gates or O in gates:
                continue
            if frozenset((S, O)) in groups:
                summing[S] = {"integrating_cap": cn, "amp_out": O}

    # A CHARGE BRANCH is a capacitor BOTH of whose plates are two-position
    # switched, neither of which is a summing node or an amplifier output.
    # Enumerating branches this way — from the capacitor, never from the
    # summing node — is the load-bearing choice in this file. Enumerating the
    # capacitors that ALREADY reach a summing node through a switch makes the
    # branch whose summing-node switches are MISSING invisible to the report,
    # so the check would pass exactly the topology it exists to reject.
    branches = {}
    for cn, (a, b) in caps:
        if a in excl or b in excl:
            continue
        if {a, b} & (set(summing) | {v["amp_out"] for v in summing.values()}):
            continue
        ta, tb = (_two_position(a, groups), _two_position(b, groups))
        if not ta or not tb:
            continue
        # the TOP plate is the one that reaches a summing node; when neither
        # does, the branch is broken and either orientation reports it.
        if set(tb) & set(summing):
            bot, top, bt, tt = a, b, ta, tb
        else:
            bot, top, bt, tt = b, a, tb, ta
        gs = [tt[n] for n in tt]
        branches[cn] = {
            "bottom_plate": bot, "top_plate": top,
            "bottom_throws": sorted(bt), "top_throws": sorted(tt),
            "reaches": sorted(set(tt) & set(summing)),
            "top_reference": sorted(set(tt) - set(summing)),
            "shared_reference": sorted((set(tt) - set(summing)) & set(bt)),
            "n_gates": gs,
            "complementary": (None not in gs) and len(set(gs)) == len(gs),
        }

    for S, st in summing.items():
        st["hard_wired_caps"] = sorted(cn for cn, nets in caps if S in nets)
        st["branches"] = {cn: b for cn, b in branches.items()
                          if S in b["reaches"]}
    return summing, branches


DS_SPEC = [{"name": "order", "target": 2.0, "unit": ""},
           {"name": "vdd", "target": 1.2, "unit": "V"},
           {"name": "osr", "target": 64.0, "unit": ""},
           {"name": "enob", "target": 12.0, "unit": "bit"},
           {"name": "vref", "target": 1.0, "unit": "V"},
           {"name": "fclk", "target": 4.0, "unit": "MHz",
            "min": 0.1, "max": 4.0}]
DS_ORDER = 2

# Invented process constants. The entry refuses a family it has no MEASURED
# record for, which is correct and is not what this test is about, so the
# fixture stages one of its own rather than reaching for a real PDK's.
DS_PDK_RECORD = {"measured": {
    "_schema": 1, "nominal_corner": "typ",
    "corners": {"typ": {
        "params": {"cap_area_ff_per_um2": 1.5, "cap_perim_ff_per_um": 0.04,
                   "rsheet_ohm_per_sq": 260.0, "r_per_um_ohm": 520.0,
                   "r_end_ohm": 0.0, "vth_n_extracted_v": 0.2,
                   "vth_p_extracted_v": 0.33, "k_prime_n_ua_per_v2": 328.0,
                   "k_prime_p_ua_per_v2": 74.0},
        "sections": [], "devices": {}, "bias": {}, "fit": {},
        "not_measured": {}}}}}


def _emit_modulator(tmp_path):
    p = make_project(tmp_path, [block("mod_alpha", "delta_sigma", DS_SPEC)])
    rec = p / "analog/_pdk_char/analog_device_params.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps(DS_PDK_RECORD), encoding="utf-8")
    run_prog(A1, p)
    run_prog(A2, p)
    cp = run_prog(A3, p)
    assert cp.returncode == 0, cp.stderr
    sp = bdir(p, "mod_alpha") / "mod_alpha.sp"
    assert sp.is_file(), "no netlist to state a topology property about"
    return sc_integrator_report(sp.read_text(encoding="utf-8"))


def test_every_sampling_capacitor_reaches_the_summing_node_through_a_switch(
        tmp_path):
    summing, branches = _emit_modulator(tmp_path)

    # The stages must be THERE. Without this the whole property is satisfiable
    # by emitting an integrator with no summing node at all.
    assert len(summing) == DS_ORDER, (
        f"the declaration binds order {DS_ORDER}, so the deck must carry "
        f"{DS_ORDER} switched-capacitor summing nodes; found {sorted(summing)}")

    # And the CHARGE BRANCHES must be there — enumerated from their bottom
    # plates, so a branch whose summing-node switches are missing is still
    # counted here and fails below rather than vanishing from the report.
    # Order 2 CIFB: one sampling and one DAC branch per stage.
    assert len(branches) == 2 * DS_ORDER, (
        f"expected {2 * DS_ORDER} switched charge branches (a sampling and a "
        f"feedback branch per stage); found {sorted(branches)}")

    for S, st in sorted(summing.items()):
        # (1) ONLY the integrating capacitor is welded to the virtual ground.
        assert st["hard_wired_caps"] == [st["integrating_cap"]], (
            f"summing node {S} carries capacitors {st['hard_wired_caps']} "
            f"wired straight onto it; only the integrating capacitor "
            f"{st['integrating_cap']} may be. A sampling or feedback "
            f"capacitor with its summing-node plate hard-wired hands the "
            f"charge back on the next half cycle: net zero per clock period, "
            f"and the loop filter never accumulates.")

    for cn, b in sorted(branches.items()):
        # (2) the summing-node plate is a SWITCH, not a weld.
        assert len(b["top_throws"]) >= 2, (
            f"branch capacitor {cn}: its bottom plate {b['bottom_plate']} is "
            f"switched between {b['bottom_throws']}, but its other plate "
            f"{b['top_plate']} has throws {b['top_throws']} — fewer than two, "
            f"so that plate is welded and the branch cannot transfer charge.")

        # (3) and one of its throws is a summing node.
        assert b["reaches"], (
            f"branch capacitor {cn}: plate {b['top_plate']} is switched "
            f"between {b['top_throws']}, none of which is a summing node, so "
            f"the sampled charge never reaches an integrator.")

        # (4) the OTHER throw is the same reference the bottom plate returns
        #     to — not merely "some internal node", and never the capacitor's
        #     own other plate, either of which transfers nothing.
        assert b["shared_reference"] == b["top_reference"], (
            f"branch capacitor {cn}: its summing-node plate {b['top_plate']} "
            f"returns to {b['top_reference']}, which its bottom plate "
            f"{b['bottom_plate']} does not reach (that plate throws to "
            f"{b['bottom_throws']}). BOTH plates must return to the SAME "
            f"reference node, or the charge the branch delivers is not the "
            f"difference the design states — a plate 'sampled' against an "
            f"arbitrary node, or against the capacitor's own other plate, "
            f"transfers nothing.")

        # (5) and the two throws alternate. Compared by the n-channel half's
        #     gate, because both halves of every transmission gate here carry
        #     the same PAIR of gate nets and a set comparison cannot tell a
        #     complementary pair from two throws that conduct together.
        assert b["complementary"] is True, (
            f"branch capacitor {cn}: the two throws on plate "
            f"{b['top_plate']} do not conduct on opposite phases "
            f"(throws {b['top_throws']}, n-side gates "
            f"{sorted(str(g) for g in b['n_gates'])}). "
            f"Two throws on the same phase short the summing node to the "
            f"reference instead of alternating with it.")
