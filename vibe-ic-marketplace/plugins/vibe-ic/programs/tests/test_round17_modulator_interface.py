"""Round 17 of the u_hawaii_adc acceptance: the modulator's declared boundary,
and the difference between "it simulates" and "it works".

Round 16 closed the physical gates (sign-off DRC 184 -> 0, netgen matching
POWER-AWARE over 77,863 instances, every analysed STA corner MET) and stopped
on one INTERFACE disagreement: the corpus declares `delta_sigma` as
`vdd vss vin vrefp vrefn clk bit_out`, every pin citing its document line, and
the A2 topology library drew `vdd vss vin vcm rst vout`. Three of those four
were not naming — they were structure. This module pins what round 17 did
about it.

  1. THE BOUNDARY IS THE DESIGN'S. `vcm` stops being a pin because the block
     now generates the common mode on-chip from the DECLARED differential
     reference pair; `clk` becomes a pin because the switched-capacitor
     integrators now have switches; `bit_out` is the output of a quantiser
     the entry now contains, not the loop filter's output renamed. The port
     binder, which round 16 correctly had REFUSING the rename (3 leftovers
     against 4), is now an identity map with no refusal.

  2. A CASCADE OF INVERTING STAGES ALTERNATES IN SIGN. A feedback branch
     driven from one node into every summing node is negative feedback at the
     odd stages and POSITIVE feedback at the even ones. The stage template
     grew `{alt}`, which cycles through the entry's `alternates` list; an
     entry that declares none gets "" and takes the identical path.

  3. `last_out` IS NOT NECESSARILY A PORT. The cascade's last output now
     feeds the quantiser, so it ends on an internal net. What has to hold
     either way is that the name RESOLVES, and `library_invariants` now says
     so.

  4. ONE RULE, WRITTEN DOWN TWICE, GETS FIXED ONCE. `analog_netlist_
     connectivity_check` was corrected to see two-terminal devices;
     `analog_a3_netlist_emit._validate_ir` kept the old floor of three nets
     as a literal, and its pre-check then refused a switched-capacitor
     netlist the checker itself accepts. The floor is now exported by the
     checker and read by the emitter.

  5. A SUPPLY PIN IS NOT CONNECTED THROUGH THE NETLIST. `analog_macro_rtl_
     interface_check` called a macro's LEF PG pin absent from the RTL
     blackbox "a pin the digital top never connects ... it floats in
     silicon". On round 16's die every one of those terminals was bound by
     POWER INTENT, `PG_NET_OWNERSHIP_AUDIT` was clean and netgen matched
     POWER-AWARE — while this gate failed A8 for the absence of a port that
     is not supposed to exist. Supplies are now disclosed by name and the
     verdict is decided on the SIGNAL pins.

  6. "RENDERS AND SIMULATES" IS NOT "WORKS". The closed modulator converges
     and drives `bit_out` rail to rail at a bitstream density of 0.51 that
     does not move across the input's full range. Eight structural arms are
     recorded in the entry itself, and `analog_topology_behaviour_check`
     refuses the block on its own author's record.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import analog_a2_topology_emit as a2  # noqa: E402
import analog_a3_netlist_emit as a3  # noqa: E402
import analog_netlist_connectivity_check as conn  # noqa: E402
import analog_macro_rtl_interface_check as iface  # noqa: E402
import analog_topology_behaviour_check as beh  # noqa: E402

#: The interface the corpus declares for the modulator, every pin citing a
#: document line in `input/interfaces/analog_blocks.sp`. Written out here so a
#: change to the library that walks away from it fails LOUDLY.
DECLARED = ["vdd", "vss", "vin", "vrefp", "vrefn", "clk", "bit_out"]

ENTRY = a2.LIBRARY["delta_sigma"]


# ── 1. the boundary is the design's ───────────────────────────────────────
def test_the_entry_draws_the_interface_the_design_declares():
    assert sorted(ENTRY["ports"]) == sorted(DECLARED)


def test_vcm_and_rst_left_the_boundary_and_are_not_silently_gone():
    """The corpus states both are INTERNAL to the topology. `vcm` must
    therefore still EXIST — as an internal net — or the block has simply
    lost its common-mode reference rather than generating one."""
    assert "vcm" not in ENTRY["ports"]
    assert "vcm" in ENTRY["internal_nets"]
    assert "rst" not in ENTRY["ports"]
    assert "rst" not in ENTRY["internal_nets"]


def test_the_common_mode_is_generated_from_the_declared_reference_pair():
    """Two matched devices across vrefp..vrefn, and `vcm` DRIVEN from their
    tap. Without them `vcm` is an internal net nothing drives, which is the
    same defect as the pin it replaced.

    The assertion is on that INTENT, not on the tap's name. It used to
    require the tap to be `vcm` itself; since v1.16.44+ the tap feeds a
    unity-gain buffer whose output is `vcm`, because a 67.2 kohm divider
    cannot hold a node ten switched terminals commutate onto (measured: the
    reference moved 0.1196 V across the input range, six times harder than
    the signal). The intent holds more strongly now, so the test follows the
    intent."""
    div = [d for d in ENTRY["devices"] if d["role"] == "res"
           and {"vrefp", "vrefn"} & set(d["nets"])]
    assert len(div) == 2, [d["name"] for d in div]
    touched = {n for d in div for n in d["nets"]}
    assert {"vrefp", "vrefn"} <= touched
    # the tap is whatever net the two halves share besides the rails
    tap = (set(div[0]["nets"]) & set(div[1]["nets"])) - {"vss", "vdd"}
    assert len(tap) == 1, tap
    tap = tap.pop()
    # and `vcm` must be DRIVEN — either it is the tap, or something whose
    # input is the tap drives it
    if tap != "vcm":
        drivers = [d for d in ENTRY["devices"]
                   if d["nets"][0] == "vcm" and d["role"] in ("nmos", "pmos")]
        assert drivers, "vcm is neither the tap nor driven by any device"
        fed = [d for d in ENTRY["devices"]
               if len(d["nets"]) > 1 and d["nets"][1] == tap]
        assert fed, f"nothing reads the divider tap {tap!r}"


def test_the_declared_clock_actually_switches_something():
    """`clk` is a pin because the circuit uses it. A sampling capacitor with
    no switches is a capacitor, and that is what the old entry drew.

    ROUND 18: `stage` is a LIST of groups now — the integrator cascade and
    the conversion-window counter — so this reads the group the switches are
    in rather than indexing a dict that no longer exists."""
    st = a2._stage_groups(ENTRY)[0]
    gated = [d for d in st["devices"] if len(d["nets"]) == 4
             and d["nets"][1] in ("clk", "nclkb")]
    assert len(gated) >= 4, [d["name"] for d in gated]


def test_bit_out_is_a_quantiser_decision_not_the_loop_filters_output():
    """The cascade's last output is an INTERNAL net, and `bit_out` is driven
    by devices that are not in the stage template. Renaming the integrator
    output to `bit_out` would pass every other test in this file."""
    _cascade = a2._stage_groups(ENTRY)[0]
    assert _cascade["last_out"] not in ENTRY["ports"]
    assert _cascade["last_out"] in ENTRY["internal_nets"]
    drivers = [d for d in ENTRY["devices"] if d["nets"][0] == "bit_out"]
    assert drivers, "nothing on the block drives the declared output"


def test_the_feedback_dac_reaches_the_declared_reference_pair():
    """A modulator without a DAC branch is a loop filter. The branch has to
    touch BOTH declared reference ends or the loop is not closed around the
    declared full scale."""
    dac = [d for d in ENTRY["devices"]
           if d["nets"][0] in ("ndac", "ndacb")]
    ends = {n for d in dac for n in d["nets"]}
    assert {"vrefp", "vrefn"} <= ends
    gates = {d["nets"][1] for d in dac}
    assert gates <= {"bit_out", "nqb"} and gates, gates


def test_the_binder_is_now_an_identity_map_with_no_refusal():
    mapping, refusal = a2.bind_ports_to_declaration(ENTRY["ports"], DECLARED)
    assert refusal is None
    assert {k: v for k, v in mapping.items() if k != v} == {}


def test_the_binder_still_refuses_a_rename_it_cannot_prove():
    """The CONTROL for the test above. Round 16's refusal was right and must
    stay reachable: three leftovers against four is not a unique answer."""
    mapping, refusal = a2.bind_ports_to_declaration(
        ["vdd", "vss", "vin", "vcm", "rst", "vout"], DECLARED)
    assert mapping == {}
    assert refusal and "PORT_BINDING_AMBIGUOUS" in refusal


# ── 2. the alternating feedback node ──────────────────────────────────────
def _expand(entry, order=2):
    # ROUND 18: the entry also carries a counter group whose count comes from
    # the declared OSR, so the expansion needs that row bound too.
    # vref and vdd are `requires_bound` for this entry: the incremental
    # coefficient set is DERIVED against the reference and the swing the
    # core supply leaves, so a declaration that binds neither has no
    # coefficients. This fixture stands in for a real declaration.
    return a2.expand_stages(entry, {"order": float(order), "osr": 256.0,
                                    "vref": 1.0, "vdd": 1.2})


def test_the_dac_branch_alternates_with_the_stages_parity():
    devices, _nets, _ex, rec = _expand(ENTRY)
    assert rec["stages"] == 2
    s1 = [d for d in devices if d["name"] == "mn_dacs1"][0]
    s2 = [d for d in devices if d["name"] == "mn_dacs2"][0]
    assert "ndac" in s1["nets"] and "ndacb" not in s1["nets"]
    assert "ndacb" in s2["nets"]


def test_an_entry_that_declares_no_alternates_substitutes_nothing():
    """The control that keeps every other entry on its old path."""
    entry = json.loads(json.dumps(ENTRY))
    entry["stage"] = [a2._stage_groups(entry)[0]]
    entry["stage"][0].pop("alternates")
    entry["stage"][0]["devices"] = [
        {"name": "m{i}", "role": "nmos", "function": "f",
         "nets": ["a{i}", "n{alt}", "vss", "vss"], "w": 1.0, "l": 1.0}]
    devices, _n, _e, _r = _expand(entry)
    assert [d["nets"][1] for d in devices if d["name"].startswith("m")
            and d["name"][1:].isdigit()] == ["n", "n"]


def test_every_other_library_entry_expands_to_its_own_lists_unchanged():
    """The corpus-wide control. Not one of the shipped entries other than
    the modulator declares a stage, so `expand_stages` must hand each of
    them back exactly what the library holds — no `{alt}`, no record."""
    for btype, entry in sorted(a2.LIBRARY.items()):
        if btype == "delta_sigma":
            continue
        devices, nets, exprs, rec = a2.expand_stages(entry, {})
        assert rec is None, btype
        assert devices == list(entry.get("devices") or []), btype
        assert nets == list(entry.get("internal_nets") or []), btype
        assert exprs == list(entry.get("device_param_exprs") or []), btype


# ── 3. last_out, and the invariant that now covers it ─────────────────────
def test_the_shipped_library_satisfies_every_invariant():
    assert a2.library_invariants() == []


def test_a_stage_ending_on_an_undeclared_name_is_refused_by_name():
    entry = json.loads(json.dumps(ENTRY))
    entry["stage"][0]["last_out"] = "a_name_nothing_declares"
    problems = a2.library_invariants({"x": entry})
    assert any("last_out" in p for p in problems), problems


def test_an_unverified_behaviour_record_must_say_what_would_close_it():
    entry = json.loads(json.dumps(ENTRY))
    entry["behaviour_record"]["next"] = ""
    entry["behaviour_record"]["diagnosis"] = ""
    problems = a2.library_invariants({"x": entry})
    assert any("`next`" in p for p in problems), problems
    assert any("`diagnosis`" in p for p in problems), problems


# ── 4. one rule, one copy ─────────────────────────────────────────────────
def test_the_emitter_reads_the_checkers_floor_instead_of_holding_a_copy():
    assert a3._conncheck is conn
    assert conn.MIN_DEVICE_NETS == 2


def test_the_connectivity_checker_counts_a_two_terminal_device():
    """The floor the emitter reads has to be the floor the checker applies,
    or exporting it changed nothing."""
    assert conn._device_nets("xc1 a b cap_model w=1u l=1u") == ["a", "b"]
    assert conn._device_nets("xr1 a b") is None


def test_a_summing_node_reached_only_through_capacitors_is_not_refused():
    """MEASURED: this exact shape — a node touched by one transistor GATE and
    two capacitor plates — was reported FLOATING_NODE by the emitter's
    pre-check and the netlist was never written."""
    findings = []
    ok = conn._check_subckt(
        "sc", ["vdd", "vss", "vin", "out"],
        ["xm1 nd vsum vss vss nmos_model w=1u l=1u",
         "xcs vin vsum cap_model w=1u l=1u",
         "xci vsum out cap_model w=1u l=1u",
         "xm2 out nd vdd vdd pmos_model w=1u l=1u"],
        "t.sp", findings)
    assert ok, [f.message for f in findings]


def test_a_node_with_a_single_terminal_is_still_floating():
    """The CONTROL. Lowering the floor must not turn off the rule."""
    findings = []
    ok = conn._check_subckt(
        "sc", ["vdd", "vss", "out"],
        ["xm1 nd ndangle vss vss nmos_model w=1u l=1u",
         "xm2 out nd vdd vdd pmos_model w=1u l=1u"],
        "t.sp", findings)
    assert not ok
    assert any(f.rule == "FLOATING_NODE" for f in findings)


# ── 5. a supply pin is bound by power intent ──────────────────────────────
def test_a_supply_absent_from_the_rtl_is_disclosed_and_does_not_fail():
    d = iface.compare(macro_pins=["vdd", "vss", "a", "b"],
                      rtl_ports=["a", "b"], rails=["vdd", "vss"])
    assert d["missing_in_rtl"] == []
    assert d["supplies_bound_by_power_intent"] == ["vdd", "vss"]


def test_a_signal_absent_from_the_rtl_still_fails():
    """The CONTROL for the row above. Excluding supplies must not excuse a
    signal pin, which is the disagreement the gate exists to report."""
    d = iface.compare(macro_pins=["vdd", "vss", "a", "b"],
                      rtl_ports=["a"], rails=["vdd", "vss"])
    assert d["missing_in_rtl"] == ["b"]


def test_a_pin_the_topology_does_not_call_a_rail_is_not_excused():
    """The exclusion is driven by the topology's OWN rail declaration, not
    by how a name looks. A block that declares no rails excuses nothing."""
    d = iface.compare(macro_pins=["vdd", "vss", "a"],
                      rtl_ports=["a"], rails=[])
    assert d["missing_in_rtl"] == ["vdd", "vss"]
    assert d["supplies_bound_by_power_intent"] == []


# ── 6. renders and simulates is not works ─────────────────────────────────
def test_the_modulator_entry_records_that_it_does_not_yet_convert():
    rec = ENTRY["behaviour_record"]
    assert rec["verified"] is False
    assert rec["arms"] and rec["diagnosis"] and rec["next"]


def test_the_gate_refuses_a_block_whose_own_record_says_not_demonstrated(
        tmp_path):
    d = tmp_path / "phase3" / "analog" / "m"
    d.mkdir(parents=True)
    (d / "topology.json").write_text(json.dumps(
        {"behaviour_record": {"claim": "c", "verified": False,
                              "diagnosis": "d", "next": "n", "arms": ["a"]}}))
    r = beh.check_block(tmp_path, "m")
    assert r["claimed"] and r["verified"] is False


def test_the_gate_passes_a_block_that_states_no_claim(tmp_path):
    """The control that keeps every other design's block unaffected: an IR
    with no `behaviour_record` is SKIPPED, not failed and not silently
    passed as if it had been measured."""
    d = tmp_path / "phase3" / "analog" / "m"
    d.mkdir(parents=True)
    (d / "topology.json").write_text(json.dumps({"ports": ["a"]}))
    r = beh.check_block(tmp_path, "m")
    assert r["claimed"] is False
    rc = beh.main([str(tmp_path), "--block", "m"])
    assert rc == 0


def test_the_gate_fails_the_run_when_a_claim_is_not_demonstrated(tmp_path):
    d = tmp_path / "phase3" / "analog" / "m"
    d.mkdir(parents=True)
    (d / "topology.json").write_text(json.dumps(
        {"behaviour_record": {"claim": "c", "verified": False,
                              "diagnosis": "d", "next": "n", "arms": ["a"]}}))
    assert beh.main([str(tmp_path), "--block", "m"]) == 1


def test_the_gate_passes_a_demonstrated_claim(tmp_path):
    """The other CONTROL: the gate must be able to say yes, or it is a
    refusal with only one direction."""
    d = tmp_path / "phase3" / "analog" / "m"
    d.mkdir(parents=True)
    (d / "topology.json").write_text(json.dumps(
        {"behaviour_record": {"claim": "c", "verified": True,
                              "how": "measured"}}))
    assert beh.main([str(tmp_path), "--block", "m"]) == 0


def test_the_gate_is_run_by_the_analog_runner_and_not_only_by_this_file():
    """A gate nothing invokes is a gate that never fires. Round 16 landed
    the same lesson for the macro/RTL interface check."""
    src = (_PROGRAMS / "analog_one_shot_runner.py").read_text()
    assert "analog_topology_behaviour_check.py" in src


def test_the_gate_runs_as_a_program(tmp_path):
    d = tmp_path / "phase3" / "analog" / "m"
    d.mkdir(parents=True)
    (d / "topology.json").write_text(json.dumps({"ports": ["a"]}))
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "analog_topology_behaviour_check.py"),
         str(tmp_path), "--block", "m"],
        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_the_behaviour_record_reaches_the_rendered_markdown():
    """The verdict has to be in the artefact a human opens, not only in the
    JSON a gate reads."""
    ir = {"behaviour_record": ENTRY["behaviour_record"]}
    md = "\n".join(a2._render_behaviour_section(ir))
    assert "NOT DEMONSTRATED" in md
    assert ENTRY["behaviour_record"]["next"] in md


def test_an_ir_with_no_record_renders_no_section():
    assert a2._render_behaviour_section({"ports": []}) == []
