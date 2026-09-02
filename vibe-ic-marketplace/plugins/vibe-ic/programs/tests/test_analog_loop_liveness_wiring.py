#!/usr/bin/env python3
"""`analog_loop_liveness_check` had a CLI, a judgement, and no population.

THE FINDING, MEASURED at 279b2e499 on a clean checkout of `origin/main`:

    gates: 651   unwired: 27 (baseline 26)
    [FAIL] 1 gate(s) newly consulted by no automatic verdict:
       analog_loop_liveness_check

It is the 27th, it is the only one, and the two shipped-register tests in
`test_shipped_gate_is_wired_register_holds_no_pending_shrink.py` were red on
exactly that gap. The register may only SHRINK, so "record it as accepted
debt" is not available; the gate had to be wired.

IT COULD NOT HONESTLY BE WIRED, AND THAT WAS THE REAL DEFECT.
`analog_loop_liveness_check` reads `--samples-json`: `{node: [values...]}` plus
a time vector, over the nodes `analog_a2_topology_emit` declares under
`LIVENESS_NODES_KEY`. A2 declares the ROLES. Nothing in `programs/` emitted the
SAMPLES: `analog_real_corner_sweep` writes the `.measure.json` scalars and the
`corner_results.json` record, and no program anywhere in the tree emitted a
per-timepoint waveform in that shape. Wiring the gate anyway would have
declared it over a population nobody can open — a vacuous pass on every design,
which is precisely the shape that gate exists to refuse:

    "a null result is only evidence if the thing that would have produced a
     non-null result was RUNNING"

So the missing half was a PRODUCER — `analog_loop_liveness_samples_emit` — and
these tests hold BOTH halves to the standard the gate itself sets:

  * the argv the producer builds is EXECUTED against the shipped checker, so a
    flag renamed on either side is a red rather than a silently dropped
    liveness condition (`test_the_shipped_checker_accepts_...`);
  * a dead window still reads NOT_MEASURED with rc 2, and a live one reads
    LIVE with rc 0, over samples in exactly the shape the producer emits;
  * the producer REFUSES, by name, on each of the four ways the export can be
    hollow, and writes NO samples file when it does — including removing a
    stale one, because an old file is exactly as good as an empty one to a
    checker that cannot tell how old it is;
  * the node list is A2's, not this producer's: monkeypatching A2's own table
    moves the producer's answer, and no design net name is spelled in the
    producer's source.

chip-AGNOSTIC throughout: every fixture net is invented here, and the one place
a real net name could leak in is asserted against.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import analog_a2_topology_emit as a2                      # noqa: E402
import analog_loop_liveness_check as chk                  # noqa: E402
import analog_loop_liveness_samples_emit as emit          # noqa: E402
import gate_is_wired_check as giw                         # noqa: E402

CHECKER = PROGRAMS / "analog_loop_liveness_check.py"
PRODUCER = PROGRAMS / "analog_loop_liveness_samples_emit.py"
RUNNER = PROGRAMS / "analog_one_shot_runner.py"

#: A block type invented for these tests. It is NOT in A2's library; every test
#: that needs one installs it, so nothing here depends on which circuit classes
#: the shipped library happens to carry today.
FAKE_TYPE = "unit_test_loop_block"
ROLES = {"reset": "n_rst_probe", "feedback": "n_fb_probe",
         "decision": "n_dec_probe"}


# ── fixtures ──────────────────────────────────────────────────────────────
def _live_samples(n=64, vdd=1.2):
    """A window in which all three conditions hold: the reset releases, the
    feedback takes both states with a full-rail span, and the decision
    resolves."""
    t = [i * 1e-9 for i in range(n)]
    rst = [vdd if i < 4 else 0.0 for i in range(n)]
    fb = [vdd if (i // 4) % 2 else 0.0 for i in range(n)]
    dec = [vdd if (i // 8) % 2 else 0.0 for i in range(n)]
    return {"t": t, ROLES["reset"]: rst, ROLES["feedback"]: fb,
            ROLES["decision"]: dec}


def _dead_samples(n=64, vdd=1.2):
    """The measured shape this whole gate comes from: reset asserted for the
    whole window, feedback pinned at one reference, quantiser never resolving.
    Every arithmetic result over it is correct and certifies nothing."""
    s = _live_samples(n, vdd)
    s[ROLES["reset"]] = [vdd] * n
    s[ROLES["feedback"]] = [vdd] * n
    s[ROLES["decision"]] = [vdd * 0.5] * n
    return s


def _argv_for(samples_path: Path):
    """The argv the producer builds, assembled from the SAME table the
    producer uses — so this test cannot pass while the producer's own mapping
    is wrong."""
    argv = ["--samples-json", str(samples_path), "--time-key", emit.TIME_KEY]
    for role in sorted(ROLES):
        argv += [emit.ROLE_TO_CHECKER_FLAG[role], ROLES[role]]
    return argv


def _write(tmp_path: Path, samples) -> Path:
    p = tmp_path / "samples.json"
    p.write_text(json.dumps(samples))
    return p


def _project(tmp_path: Path, *, block="blk", btype=FAKE_TYPE) -> Path:
    proj = tmp_path / "proj"
    bdir = proj / "phase3" / "analog" / block
    bdir.mkdir(parents=True)
    (bdir / "topology.json").write_text(json.dumps({
        "block": block, "block_type": btype,
        "rails": {"vdd": "vdd", "vss": "vss"},
        "internal_nets": sorted(ROLES.values()),
    }))
    return proj


def _declaring_type() -> str:
    """A block type the SHIPPED A2 library declares liveness nodes for, chosen
    at run time. Named nowhere here: a test that spelled one would go stale the
    day the library renames a circuit class, and it would be this file
    restating a declaration that belongs to A2."""
    for name, entry in sorted(a2.LIBRARY.items()):
        if entry.get(a2.LIVENESS_NODES_KEY):
            return name
    pytest.skip("A2's library declares no liveness nodes for any block type")


def _run_producer(proj: Path, block="blk"):
    cp = subprocess.run([sys.executable, str(PRODUCER), str(proj),
                         "--block", block],
                        capture_output=True, text=True)
    try:
        rec = json.loads(cp.stdout)
    except Exception:
        rec = {}
    return cp, rec


# ── 1. the two halves speak the same argv ─────────────────────────────────
def test_the_shipped_checker_accepts_the_argv_the_producer_builds(tmp_path):
    """EXECUTED, not asserted about. `ROLE_TO_CHECKER_FLAG` is a table in one
    program naming flags declared in another; nothing but running it proves
    the two still agree. A dropped flag would not error — the checker would
    report that condition NOT_DECLARED and refuse every window, which reads as
    a dead loop rather than as a broken wire."""
    p = _write(tmp_path, _live_samples())
    cp = subprocess.run([sys.executable, str(CHECKER), *_argv_for(p)],
                        capture_output=True, text=True)
    out = json.loads(cp.stdout)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert out["result"] == "LIVE", out
    states = {c["condition"]: c["state"] for c in out["conditions"]}
    assert states == {"reset_released": "LIVE",
                      "feedback_switching": "LIVE",
                      "decision_resolving": "LIVE"}, out
    # No condition may be NOT_DECLARED: that is what a stale flag name looks
    # like, and it is not distinguishable from a dead loop by exit code alone.
    assert "NOT_DECLARED" not in json.dumps(out)


def test_every_role_the_producer_maps_is_a_flag_the_checker_declares():
    """The other direction: A2's three roles are the three the checker
    judges, and the producer's table covers exactly them."""
    assert set(emit.ROLE_TO_CHECKER_FLAG) == {"reset", "feedback", "decision"}
    src = CHECKER.read_text()
    for flag in emit.ROLE_TO_CHECKER_FLAG.values():
        assert f'ap.add_argument("{flag}"' in src, flag


# ── 2. a dead window is NOT_MEASURED, never a pass ────────────────────────
def test_a_dead_window_is_not_measured_with_rc_2(tmp_path):
    p = _write(tmp_path, _dead_samples())
    cp = subprocess.run([sys.executable, str(CHECKER), *_argv_for(p)],
                        capture_output=True, text=True)
    out = json.loads(cp.stdout)
    assert cp.returncode == 2, cp.stdout
    assert out["result"] == "NOT_MEASURED", out
    assert "measurement_withheld" in out


# ── 3. the producer fails closed, by name, and writes nothing ─────────────
def test_producer_refuses_when_the_runner_simulated_no_transient(tmp_path):
    """The negative control. A project whose analog runner never ran leaves no
    deck and no ngspice log; the producer must say so and write NO samples —
    the checker then has nothing to read, which is the only honest outcome."""
    proj = _project(tmp_path, btype=_declaring_type())
    cp, rec = _run_producer(proj)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert rec.get("verdict") == "REFUSED", rec
    assert "has not simulated a transient" in rec["reason"], rec
    assert not (proj / "phase3" / "analog" / "blk"
                / emit.SAMPLES_NAME).exists()


def test_a_refusal_removes_a_stale_samples_file(tmp_path):
    """A samples file from an earlier run is exactly as good as an empty one
    to a checker that cannot tell how old it is: it would report LIVE over a
    window that no longer has a simulation behind it."""
    proj = _project(tmp_path, btype=_declaring_type())
    stale = proj / "phase3" / "analog" / "blk" / emit.SAMPLES_NAME
    stale.write_text(json.dumps(_live_samples()))
    cp, rec = _run_producer(proj)
    assert cp.returncode == 2
    assert not stale.exists(), rec
    assert rec.get("stale_samples_removed")


def test_a_block_type_declaring_no_liveness_nodes_is_a_gap_not_a_failure(
        tmp_path):
    proj = _project(tmp_path, btype="a_type_with_no_declaration")
    cp, rec = _run_producer(proj)
    assert cp.returncode == 2
    assert rec["verdict"] == "NOT_DECLARED", rec
    assert a2.LIVENESS_NODES_KEY in rec["reason"]


def test_a_net_the_deck_does_not_draw_is_refused_by_name():
    deck = ".subckt s a b\nr1 a b 1k\n.ends\nx1 a b s\n"
    with pytest.raises(emit.Refusal) as e:
        emit.resolve_vector(deck, ROLES["reset"])
    assert ROLES["reset"] in str(e.value)
    assert "drawn nowhere" in str(e.value)


def test_a_net_drawn_under_two_instances_is_refused():
    deck = (".subckt s a b\nr1 a n_probe 1k\nr2 n_probe b 1k\n.ends\n"
            "x1 a b s\nx2 a b s\n")
    with pytest.raises(emit.Refusal) as e:
        emit.resolve_vector(deck, "n_probe")
    assert "instantiate" in str(e.value)


def test_a_top_level_net_resolves_without_an_instance_prefix():
    assert emit.resolve_vector("r1 vdd 0 1k\n", "vdd") == "v(vdd)"


def test_wrdata_with_a_misaligned_time_column_is_refused():
    """`wrdata` emits one (scale, value) pair PER VECTOR. If the scale columns
    disagree the columns did not come from one sweep, and a per-node verdict
    over misaligned time is arithmetic on nothing."""
    good = "0 1 0 2\n1 1 1 2\n2 1 2 2\n"
    t, cols = emit.parse_wrdata(good, 2)
    assert t == [0.0, 1.0, 2.0] and cols == [[1.0] * 3, [2.0] * 3]
    bad = "0 1 0 2\n1 1 9 2\n2 1 2 2\n"
    with pytest.raises(emit.Refusal) as e:
        emit.parse_wrdata(bad, 2)
    assert "did not come from one sweep" in str(e.value)


def test_one_sample_row_is_not_a_window():
    with pytest.raises(emit.Refusal) as e:
        emit.parse_wrdata("0 1\n", 1)
    assert "not a window" in str(e.value)


def test_a_deck_with_no_transient_cannot_be_probed():
    with pytest.raises(emit.Refusal) as e:
        emit.probe_deck(".control\nop\n.endc\n", ["v(a)"], "/tmp/x")
    assert "no transient here" in str(e.value)


def test_the_probe_adds_exactly_one_line_to_the_runners_own_deck():
    """The claim this producer makes is that it exports the transient the
    runner ALREADY ran. That claim is only true if it changes nothing else."""
    deck = ("* head\nv1 a 0 1\n.control\ntran 1n 10n\n"
            "meas tran m find v(a) at=5n\n.endc\n.end\n")
    probed = emit.probe_deck(deck, ["v(a)"], "/out.dat")
    before = deck.splitlines()
    after = probed.splitlines()
    assert len(after) == len(before) + 1
    added = [ln for ln in after if ln not in before]
    assert added == ["wrdata /out.dat v(a)"]
    assert after.index("wrdata /out.dat v(a)") == after.index("tran 1n 10n") + 1


# ── 4. the node list belongs to A2 ────────────────────────────────────────
def test_the_node_list_is_read_from_a2_not_restated(tmp_path):
    ir = {"block_type": FAKE_TYPE}
    assert emit.declared_liveness_nodes(ir) == {}
    a2.LIBRARY[FAKE_TYPE] = {a2.LIVENESS_NODES_KEY: dict(ROLES)}
    try:
        assert emit.declared_liveness_nodes(ir) == ROLES
    finally:
        a2.LIBRARY.pop(FAKE_TYPE, None)


def test_an_ir_that_carries_the_key_wins_over_the_library():
    """The IR is the artefact that survived A2's port binding; a library entry
    is the fallback for an IR emitted before the key was carried into it."""
    a2.LIBRARY[FAKE_TYPE] = {a2.LIVENESS_NODES_KEY: dict(ROLES)}
    try:
        ir = {"block_type": FAKE_TYPE,
              a2.LIVENESS_NODES_KEY: {"reset": "n_renamed"}}
        assert emit.declared_liveness_nodes(ir) == {"reset": "n_renamed"}
    finally:
        a2.LIBRARY.pop(FAKE_TYPE, None)


def test_the_producer_spells_no_design_net_of_its_own():
    """chip-AGNOSTIC, checked rather than promised: the nets A2's shipped
    library declares must not appear as literals in the producer's source."""
    src = PRODUCER.read_text()
    declared = {net for entry in a2.LIBRARY.values()
                for net in (entry.get(a2.LIVENESS_NODES_KEY) or {}).values()}
    assert declared, "A2 declares no liveness nodes at all — nothing to check"
    leaked = sorted(n for n in declared if n in src)
    assert not leaked, leaked


# ── 5. the gate is actually reachable ─────────────────────────────────────
def test_the_runner_invokes_the_checker_in_executable_text():
    """`gate_is_wired_check.executable_text` is the tree's own rule for what
    counts as a call: docstrings and comments are stripped first, because a
    NAME IS NOT A CALL. Asserted through that same function so this test
    cannot be satisfied by a comment."""
    text = giw.executable_text(RUNNER, RUNNER.read_text())
    assert CHECKER.stem in text, (
        f"{RUNNER.name} does not reach {CHECKER.stem} from executable text")
    assert PRODUCER.stem in text, (
        f"{RUNNER.name} does not reach {PRODUCER.stem} from executable text")


def test_the_checker_is_not_in_the_unwired_register():
    """The register may only shrink, so the gate has to leave it by being
    wired — never by being recorded."""
    reg = json.loads((PROGRAMS / "gate_is_wired_baseline.json").read_text())
    names = reg.get("unwired") or reg.get("gates") or []
    assert CHECKER.stem not in names, (
        f"{CHECKER.stem} is recorded as accepted debt; it is wired now")


# ── 6. the composed verdict, end to end, with no simulator ────────────────
def test_a_project_that_never_simulated_composes_to_not_measured(tmp_path):
    """THE NEGATIVE CONTROL, through the wiring rather than through either
    half alone. A project whose analog runner never ran must reach the same
    tier the gate itself returns for a dead window — NOT_MEASURED — and never
    a pass. "I could not look" must not render like "I looked and it was
    fine": that is the finding this whole track came from."""
    sys.path.insert(0, str(PROGRAMS))
    import analog_one_shot_runner as runner
    proj = _project(tmp_path, btype=_declaring_type())
    rec = runner._loop_liveness(proj, "blk", "no-such-container-for-this-test")
    assert rec["result"] == "NOT_MEASURED", rec
    assert rec["stage"] == "samples_producer"
    assert "has not simulated a transient" in rec["reason"], rec


def test_an_empty_samples_file_would_not_buy_a_pass_either(tmp_path):
    """The producer refuses rather than writing a hollow file. This asserts
    the OTHER end of that rule holds too: had one been written, the checker
    reports every declared condition ABSENT and answers NOT_MEASURED with
    rc 2. There is no arrangement of an empty population that reads as a
    pass."""
    p = _write(tmp_path, {"t": [0.0, 1e-9, 2e-9, 3e-9]})
    cp = subprocess.run([sys.executable, str(CHECKER), *_argv_for(p)],
                        capture_output=True, text=True)
    out = json.loads(cp.stdout)
    assert cp.returncode == 2, cp.stdout
    assert out["result"] == "NOT_MEASURED", out
    assert {c["state"] for c in out["conditions"]} == {"ABSENT"}, out


def test_the_producers_own_probe_deck_is_never_mistaken_for_the_runners(
        tmp_path):
    """This program leaves its probe deck in the SAME directory it searches.
    Without the exclusion a second run would export a window from a deck THIS
    PROGRAM wrote rather than from one the runner ran — and the whole claim it
    makes is that those are the same transient."""
    sl = tmp_path / "phase3" / "analog" / "blk" / "sizing_loop"
    sl.mkdir(parents=True)
    deck = ".control\ntran 1n 10n\n.endc\n"
    for stem in ("run_x", "run_x" + emit.PROBE_INFIX):
        (sl / f"{stem}.sp").write_text(deck)
        (sl / f"{stem}.ngspice.log").write_text("ran")
    found = emit.runner_transients(tmp_path / "phase3" / "analog" / "blk")
    assert [p.name for p in found] == ["run_x.sp"], found


def test_a_deck_the_runner_never_ran_is_not_a_window(tmp_path):
    """The deck alone is not evidence: `analog_real_corner_sweep` claims
    `simulator_run: true` only for a corner whose ngspice log is on disk
    (#438(a)), and this uses the same rule."""
    bdir = tmp_path / "phase3" / "analog" / "blk"
    sl = bdir / "sizing_loop"
    sl.mkdir(parents=True)
    (sl / "run_x.sp").write_text(".control\ntran 1n 10n\n.endc\n")
    assert emit.runner_transients(bdir) == []
    (sl / "run_x.ngspice.log").write_text("ran")
    assert [p.name for p in emit.runner_transients(bdir)] == ["run_x.sp"]


def test_a_deck_with_no_transient_is_not_a_window(tmp_path):
    bdir = tmp_path / "phase3" / "analog" / "blk"
    sl = bdir / "sizing_loop"
    sl.mkdir(parents=True)
    (sl / "run_dc.sp").write_text(".control\nop\n.endc\n")
    (sl / "run_dc.ngspice.log").write_text("ran")
    assert emit.runner_transients(bdir) == []


def test_the_helper_that_reaches_the_checker_is_itself_called():
    """MUTATION-FOUND. `test_the_runner_invokes_the_checker_in_executable_text`
    is `gate_is_wired_check`'s own rule, and it is satisfied by the mere
    PRESENCE of `_loop_liveness` in the file — a mutation that deleted the call
    site and left the helper standing kept all 23 tests green while the gate
    ran nowhere. That is the same "a name is not a call" defect one level in,
    and it needs its own assertion: the helper must be CALLED, from outside its
    own definition."""
    import ast
    tree = ast.parse(RUNNER.read_text())
    defs = [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "_loop_liveness"]
    assert len(defs) == 1, "expected exactly one _loop_liveness definition"
    own = set(range(defs[0].lineno, (defs[0].end_lineno or defs[0].lineno) + 1))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "_loop_liveness"
             and n.lineno not in own]
    assert calls, (
        "_loop_liveness is defined and never called: the checker is reachable "
        "from this file's text and from nothing that executes")
