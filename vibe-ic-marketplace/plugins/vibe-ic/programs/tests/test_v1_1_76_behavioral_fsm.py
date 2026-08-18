#!/usr/bin/env python3
"""test_v1_1_76_behavioral_fsm.py — pins behavioral_fsm_synth.py.

behavioral_fsm_synth solves the STRICT mechanically-complete subset of the
behavioral-prose Moore-FSM family — the canonical hard case — and is HONEST about
the AI-floor for the rest. Three shapes FIRE (all host-verified to 0 mismatches
against the VerilogEval dataset reference):

  (A) Moore-LATCHED sequence detector  -> Prob096_review2015_fsmseq  (1101, latched)
  (B) reset-PULSE counter              -> Prob095_review2015_fsmshift (4 cycles)
  (C) strict directional bump+fall FSM -> Prob142_lemmings2 (4-state memory)

Everything whose transitions are woven into narrative MUST SKIP (a wrong FSM is far
worse than a SKIP, §4.05). The FLOOR map below records, per resisting problem, the
exact sentence a general parser cannot mechanically turn into a complete unambiguous
transition table — confirming an independent blind read is required.

Run from the programs/ dir or via the suite; iverilog cases auto-skip if the tool
is absent, but the GENERATE + SKIP-discipline assertions always run.
"""
import os
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.dirname(_HERE)
if _PROGRAMS not in sys.path:
    sys.path.insert(0, _PROGRAMS)

import behavioral_fsm_synth as bfsm  # noqa: E402
import moore_fsm_table_emit as moore_emit  # noqa: E402
from _hostpaths import corpus_path, require_repo  # noqa: E402

# Dataset location (host-scoring is best-effort; absent dataset -> those cases skip).
_DS = str(corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl"))
_HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_GATES = Path(_PROGRAMS).parent / "benchmark" / "gates_atomic.py"


def _prompt(name):
    p = os.path.join(_DS, name + "_prompt.txt")
    if not os.path.exists(p):
        pytest.skip(f"dataset prompt absent: {name}")
    return open(p, errors="replace").read()


def _host_score(name, rtl):
    """Compile generated rtl + ref + test; return mismatch count (int) or skip."""
    ref = os.path.join(_DS, name + "_ref.sv")
    tst = os.path.join(_DS, name + "_test.sv")
    if not (os.path.exists(ref) and os.path.exists(tst)):
        pytest.skip(f"dataset ref/test absent: {name}")
    with tempfile.TemporaryDirectory() as d:
        dut = os.path.join(d, "dut.sv")
        sim = os.path.join(d, "sim")
        with open(dut, "w") as f:
            f.write(rtl)
        c = subprocess.run(["iverilog", "-g2012", "-o", sim, dut, ref, tst],
                           capture_output=True, text=True)
        assert c.returncode == 0, f"compile failed for {name}:\n{c.stderr}"
        r = subprocess.run(["vvp", sim], capture_output=True, text=True)
        out = r.stdout + r.stderr
        import re
        m = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)", out)
        assert m, f"no mismatch line for {name}:\n{out}"
        return int(m.group(1)), int(m.group(2))


def _directional_prompt(omit=(), extra=""):
    """Literal re-skin of Shape C: no benchmark name or canonical port spelling."""
    clauses = {
        "outputs": (
            "The two walking states are moving left (move_left is 1) and moving "
            "right (move_right is 1)."),
        "left_map": "If the walker is hit on the left, it will move right.",
        "right_map": "If the walker is hit on the right, it will move left.",
        "both_map": "If hit on both sides at once, it will reverse direction.",
        "fall_output": (
            "When support=0, the walker will fall and fall_alarm is 1."),
        "resume": (
            "When support reappears, it will resume moving in the same direction "
            "as before the fall."),
        "fall_bump": (
            "Being hit while falling does not affect the moving direction."),
        "loss_bump": (
            "Being hit in the same cycle as support disappears does not affect "
            "the moving direction."),
        "landing_bump": (
            "When support reappears while still falling, being hit does not affect "
            "the moving direction."),
        "moore": "Implement this as a Moore state machine.",
        "reset": (
            "reset_signal is positive edge triggered asynchronous resetting the "
            "walker to move left."),
        "clock": (
            "All sequential logic is triggered on the positive edge of the clock."),
    }
    body = " ".join(v for k, v in clauses.items() if k not in set(omit))
    return (
        " - input clock\n - input reset_signal\n - input hit_left\n"
        " - input hit_right\n - input support\n - output move_left\n"
        " - output move_right\n - output fall_alarm\n\n" + body + " " + extra)


def _directional_module_prompt():
    """Checked-in de-identified real benchmark doc shape (no hidden oracle)."""
    fixture = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "real_benchmark", "directional_bump_fall_moore_prompt.md")
    return fixture.read_text()


def _named_directional_fixture_prompt():
    """Checked-in Shape-C text with one explicit actor in every noun clause."""
    prompt = _directional_module_prompt()
    replacements = (
        ("for a creature", "for a Lemming"),
        ("If it is bumped on the left",
         "In particular, if a Lemming is bumped on the left "
         "(by receiving a 1 on bump_left)"),
        ("the creature will fall", "the Lemming will fall"),
        ("When ground reappears, it will resume",
         "When the ground reappears (ground=1), the Lemming will resume walking"),
        ("areset is a\npositive edge triggered asynchronous reset, resetting "
         "the machine to walk left.",
         "areset is positive edge triggered asynchronous reseting the Lemming "
         "machine to walk left."),
    )
    for old, new in replacements:
        assert old in prompt
        prompt = prompt.replace(old, new)
    assert bfsm.synth(prompt) is not None
    return prompt


# --------------------------------------------------------------------------- #
# POSITIVES — all three shapes FIRE and (when iverilog is present) host-verify 0.
# --------------------------------------------------------------------------- #
def test_latched_sequence_detector_fires():
    """(A) Prob096 — latched 1101 detector. Generated, not None."""
    rtl = bfsm.synth(_prompt("Prob096_review2015_fsmseq"))
    assert rtl is not None
    assert "module TopModule" in rtl
    # KMP table for 1101 (S=0,S1,S11,S110,Done) + a latched output on the accept state.
    assert "ACCEPT = 3'd4" in rtl
    assert "state == ACCEPT" in rtl
    # absorbing accept state self-loops on both bits
    assert "3'd4: nstate = data ? 3'd4 : 3'd4" in rtl


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_latched_sequence_detector_host_zero_mismatch():
    rtl = bfsm.synth(_prompt("Prob096_review2015_fsmseq"))
    assert rtl is not None
    mm, total = _host_score("Prob096_review2015_fsmseq", rtl)
    assert mm == 0, f"Prob096 had {mm}/{total} mismatches"
    assert total > 0


def test_reset_pulse_counter_fires():
    """(B) Prob095 — assert for 4 cycles then 0 forever. Generated, not None."""
    rtl = bfsm.synth(_prompt("Prob095_review2015_fsmshift"))
    assert rtl is not None
    assert "module TopModule" in rtl
    assert "DONE = 3'd4" in rtl                    # 4 active cycles, Done is state 4
    assert "shift_ena = (state != DONE)" in rtl


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_reset_pulse_counter_host_zero_mismatch():
    rtl = bfsm.synth(_prompt("Prob095_review2015_fsmshift"))
    assert rtl is not None
    mm, total = _host_score("Prob095_review2015_fsmshift", rtl)
    assert mm == 0, f"Prob095 had {mm}/{total} mismatches"
    assert total > 0


def test_directional_bump_fall_fires():
    """(C) Prob142 — every prose fact closes a four-state directional walker."""
    rtl = bfsm.synth(_prompt("Prob142_lemmings2"))
    assert rtl is not None
    assert "module TopModule" in rtl
    assert "S_WALK_LEFT" in rtl and "S_WALK_RIGHT" in rtl
    assert "S_FALL_LEFT" in rtl and "S_FALL_RIGHT" in rtl
    assert "posedge clk or posedge areset" in rtl


def test_directional_bump_fall_checked_in_real_shape_fires():
    rtl = bfsm.synth(_directional_module_prompt())
    assert rtl is not None
    assert "S_WALK_LEFT" in rtl and "S_FALL_RIGHT" in rtl


def test_directional_bump_fall_canonical_table_all_32_rows():
    roles = {
        "bump_left": "hit_left", "bump_right": "hit_right",
        "ground": "support", "walk_left": "move_left",
        "walk_right": "move_right", "falling": "fall_alarm",
    }
    table = moore_emit.parse_table(bfsm._directional_fall_table(roles))
    assert table is not None
    assert table["reset"] == ("WALK_LEFT", True, True)
    assert sum(len(row) for row in table["trans"].values()) == 32
    for state in ("WALK_LEFT", "WALK_RIGHT", "FALL_LEFT", "FALL_RIGHT"):
        for left in (0, 1):
            for right in (0, 1):
                for support in (0, 1):
                    bits = f"{left}{right}{support}"
                    if state == "WALK_LEFT":
                        expected = "FALL_LEFT" if not support else (
                            "WALK_RIGHT" if left else "WALK_LEFT")
                    elif state == "WALK_RIGHT":
                        expected = "FALL_RIGHT" if not support else (
                            "WALK_LEFT" if right else "WALK_RIGHT")
                    elif state == "FALL_LEFT":
                        expected = "WALK_LEFT" if support else "FALL_LEFT"
                    else:
                        expected = "WALK_RIGHT" if support else "FALL_RIGHT"
                    assert table["trans"][state][bits] == expected
    assert table["mout"] == {
        "WALK_LEFT": {"move_left": 1, "move_right": 0, "fall_alarm": 0},
        "WALK_RIGHT": {"move_left": 0, "move_right": 1, "fall_alarm": 0},
        "FALL_LEFT": {"move_left": 0, "move_right": 0, "fall_alarm": 1},
        "FALL_RIGHT": {"move_left": 0, "move_right": 0, "fall_alarm": 1},
    }


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_directional_bump_fall_host_zero_mismatch():
    rtl = bfsm.synth(_prompt("Prob142_lemmings2"))
    assert rtl is not None
    mm, total = _host_score("Prob142_lemmings2", rtl)
    assert mm == 0, f"Prob142 had {mm}/{total} mismatches"
    assert total > 0


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_directional_bump_fall_gate_replaces_wrong_authored_toggle(tmp_path):
    """The production atomic emit path consumes the registry result, not only tests."""
    prompt = _directional_prompt()
    wrong = """module TopModule(
 input clock, input reset_signal, input hit_left, input hit_right, input support,
 output move_left, output move_right, output fall_alarm);
 reg dir;
 always @(posedge clock or posedge reset_signal)
   if (reset_signal) dir <= 0;
   else if (hit_left || hit_right) dir <= ~dir;
 assign move_left = !dir && support;
 assign move_right = dir && support;
 assign fall_alarm = !support;
endmodule
"""
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "ProbWalker_prompt.txt").write_text(prompt)
    run = tmp_path / "run"
    work = run / "work" / "ProbWalker"
    work.mkdir(parents=True)
    (work / "spec.yaml").write_text("design:\n  name: TopModule\n")
    (work / "sample.sv").write_text(wrong)
    proc = subprocess.run(
        [sys.executable, str(_GATES), "--prob", "ProbWalker",
         "--workdir", str(run / "work"), "--dataset", str(ds),
         "--prompt-suffix", "_prompt.txt", "--top-module", "TopModule"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    gates = json.loads((work / "gates.json").read_text())
    assert gates["hard_gates_pass"] is True
    assert gates["steps"]["deterministic_synth"]["applied"] is True
    assert gates["steps"]["deterministic_synth"]["kind"] == "behavioral_fsm"
    emitted = (run / "samples" / "ProbWalker_sample01.sv").read_text()
    assert "S_FALL_LEFT" in emitted and "S_FALL_RIGHT" in emitted
    assert "hit_left || hit_right" not in emitted


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK NEGATIVES — the narrative behavioral FSMs MUST SKIP (>=5).
# Each carries a FLOOR-proof: the sentence a general parser cannot mechanically
# convert into a complete unambiguous transition table. SKIP, never a guess.
# --------------------------------------------------------------------------- #
# FLOOR MAP — (problem, resisting-sentence quote, why it resists mechanical parse)
_FLOOR_NEGATIVES = [
    (
        "Prob127_lemmings1",
        'if a Lemming is bumped on the left (by receiving a 1 on bump_left), it '
        'will walk right',
        "The two states (walk_left/walk_right) are never NAMED as states — they are "
        "OUTPUTS — and the arc is a SEMANTIC direction inversion (bump-left -> walk "
        "RIGHT). No 'in state X, on cond -> state Y' sentence exists to parse.",
    ),
    (
        "Prob152_lemmings3",
        'If more than one of these conditions are satisfied, fall has higher '
        'precedence than dig, which has higher precedence than switching directions.',
        "The precedence ordering across fall/dig/switch plus the DIGL/DIGR latent "
        "state split must be synthesised from narrative — there is no transition "
        "table; a parser cannot derive the 6-state machine mechanically.",
    ),
    (
        "Prob155_lemmings4",
        'if a Lemming falls for more than 20 clock cycles then hits the ground, it '
        'will splatter and cease walking, falling, or digging',
        "A hidden 5-bit fall-duration COUNTER with a '>20 then ground' guard and a "
        "DEAD absorbing state — none of which is stated as states/arcs; deriving the "
        "counter datapath from prose is genuine NL understanding.",
    ),
    (
        "Prob128_fsm_ps2",
        'discard bytes until we see one with in[3]=1. We then assume that this is '
        'byte 1 of a message, and signal the receipt of a message once all 3 bytes '
        'have been received',
        "The bit-index gate (in[3]), the 3-byte count, the done-in-the-NEXT-cycle "
        "pulse, and the re-arm-on-in[3] semantics are described purely behaviorally; "
        "the state set (BYTE1..DONE) is unnamed and the re-arm arc is implicit.",
    ),
    (
        "Prob133_2014_q3fsm",
        'Once in state B the FSM examines the value of the input w in the next three '
        'clock cycles. If w = 1 in exactly two of these clock cycles, then the FSM '
        'has to set an output z to 1',
        "A sliding 3-cycle window with a population-count == 2 acceptance: the "
        "binary counting tree (S10/S11/S20/S21/S22) must be SYNTHESISED, it is not "
        "tabulated — genuine combinatorial-state inference.",
    ),
    (
        "Prob139_2013_q2bfsm",
        'When x has produced the values 1, 0, 1 in three successive clock cycles, '
        'then g should be set to 1 on the following clock cycle. While maintaining '
        'g = 1 the FSM has to monitor the y input. If y has the value 1 within at '
        'most two clock cycles, then the FSM should maintain g = 1 permanently',
        "A multi-phase controller (f-pulse -> 101-detect -> g -> y-within-2-window) "
        "whose phases and the 2-cycle y deadline are narrative; the 9-state machine "
        "is not enumerated anywhere.",
    ),
    (
        "Prob074_ece241_2014_q4",
        'Input x goes to three different two-input gates: an XOR, an AND, and a OR '
        'gate. Each of the three gates is connected to the input of a D flip-flop '
        'and then the flip-flop outputs all go to a three-input NOR gate',
        "This is a STRUCTURAL gate-network description (per-bit feedback equations), "
        "not a state-transition FSM at all; there is no enumerable state list to "
        "extract — it needs datapath synthesis from the wiring prose.",
    ),
    (
        "Prob136_m2014_q6",
        ' - input  reset',
        "The arrow diagram IS complete, but the prompt states NOTHING about the reset "
        "(no reset state, no sync/async, no active level) — only the port exists. "
        "full_moore_fsm_synth already SKIPs it for this reason; guessing reset->first "
        "state/active-high/sync would be a §4.05 leak.",
    ),
    (
        "Prob148_2013_q2afsm",
        'There is a priority system, in that device 0 has a higher priority than '
        'device 1, and device 2 has the lowest priority.',
        "The diagram is DEFECTIVE for a mechanical parser: state D has NO outgoing "
        "arcs and the A->D condition literally duplicates A->A; D's transitions and "
        "the request priority must be read from PROSE, not the diagram.",
    ),
]


@pytest.mark.parametrize("name,quote,_why", _FLOOR_NEGATIVES,
                         ids=[n for n, _, _ in _FLOOR_NEGATIVES])
def test_floor_negatives_skip_and_proof(name, quote, _why):
    """Each narrative behavioral FSM SKIPs (None), and its FLOOR-proof sentence is
    actually present in the prompt (the proof is grounded, not invented)."""
    text = _prompt(name)
    assert bfsm.synth(text) is None, (
        f"§4.05 LEAK: {name} must SKIP (narrative FSM, no mechanical table) but fired")
    # the resisting sentence is really in the prompt (proof is doc-grounded).
    norm = " ".join(text.split())
    qn = " ".join(quote.split())
    assert qn in norm, f"FLOOR-proof quote not found verbatim in {name} prompt"


# --------------------------------------------------------------------------- #
# Extra no-leak guards: the three shapes must not over-fire on near-miss prompts.
# --------------------------------------------------------------------------- #
def test_no_overfire_on_unrelated_clk_reset_modules():
    """A plain clk+reset prompt with no latch/pulse phrasing must SKIP."""
    txt = (
        "module TopModule ( input clk, input reset, output q );\n"
        "A simple register that loads its previous value. Reset is active high "
        "synchronous.\n")
    assert bfsm.synth(txt) is None


def test_no_overfire_pulse_requires_full_phrasing():
    """A prompt that merely mentions 'N cycles' without the assert+then-0-forever
    tail must SKIP (the count alone is not the reset-pulse shape)."""
    txt = (
        " - input  clk\n - input  reset\n - output q\n"
        "The signal q toggles for 4 clock cycles in some unrelated way. Reset is "
        "active high synchronous.\n")
    assert bfsm.synth(txt) is None


def test_no_overfire_sequence_requires_latch():
    """A stated sequence WITHOUT a latched-forever output must SKIP — that is the
    Mealy-pulse case mealy_sequence_synth owns, never ours."""
    txt = (
        " - input  clk\n - input  reset\n - input  data\n - output z\n"
        "Detect the sequence 1101 and pulse z high for one cycle. Reset is active "
        "high synchronous.\n")
    assert bfsm.synth(txt) is None


def test_no_overfire_missing_reset_spec_sequence():
    """Latched sequence detector with NO sync/async or level stated must SKIP."""
    txt = (
        " - input  clk\n - input  reset\n - input  data\n - output z\n"
        "Search for the sequence 1101; once found set z to 1 forever until reset.\n")
    # no 'synchronous'/'asynchronous' and no active level -> reset under-specified
    assert bfsm.synth(txt) is None


@pytest.mark.parametrize(
    "missing",
    ["outputs", "left_map", "right_map", "both_map", "fall_output", "resume",
     "fall_bump", "loss_bump", "landing_bump", "moore", "reset", "clock"],
)
def test_directional_bump_fall_requires_every_semantic_fact(missing):
    assert bfsm.synth(_directional_prompt(omit={missing})) is None


@pytest.mark.parametrize(
    "extension",
    [
        "The walker can also dig when dig_enable is high.",
        "After a 20-cycle timer threshold it will splatter and die.",
        "It may jump or climb in additional states.",
        "This is a Mealy controller.",
        "The direction changes only after two clock cycles.",
        "After landing it pauses for one cycle.",
        "A special recovery mode applies near obstacles.",
        "The same rules apply except when both obstacle inputs are high.",
        "When hit on the left, it may remain moving left.",
        "If support=0 while hit_left=1, it moves right instead of falling.",
        "Being hit on both sides causes no direction change.",
        "A hit while falling toggles stored direction.",
        "On the landing cycle, a hit changes direction.",
    ],
)
def test_directional_bump_fall_rejects_advanced_or_conflicting_features(extension):
    assert bfsm.synth(_directional_prompt(extra=extension)) is None


@pytest.mark.parametrize(
    "old,new",
    [
        ("fall_alarm is 1", "fall_alarm is 0"),
        ("Implement this as a Moore state machine.",
         "This is not a Moore state machine."),
        ("hit on the left, it will move right",
         "hit on the left, it will not move right"),
        ("support=0, the walker will fall",
         "support=0, the walker will not fall"),
        ("it will resume moving in the same direction",
         "it will not resume moving in the same direction"),
        ("asynchronous resetting the walker",
         "asynchronous not resetting the walker"),
        ("positive edge of the clock", "falling edge of the clock"),
    ],
)
def test_directional_bump_fall_rejects_negated_required_fact(old, new):
    mutated = _directional_prompt().replace(old, new)
    assert mutated != _directional_prompt()
    assert bfsm.synth(mutated) is None


@pytest.mark.parametrize(
    "old,new",
    [
        ("All sequential logic is triggered on the positive edge of the clock.",
         "The clock drives all sequential logic."),
        ("reset_signal is positive edge triggered asynchronous resetting the "
         "walker to move left.",
         "reset_signal is an asynchronous reset that puts the walker to move left."),
    ],
)
def test_directional_bump_fall_rejects_unbound_edge_or_polarity(old, new):
    mutated = _directional_prompt().replace(old, new)
    assert mutated != _directional_prompt()
    assert bfsm.synth(mutated) is None


@pytest.mark.parametrize(
    "conflict",
    [
        "The controller also has an IDLE state.",
        "There is also an ERROR state used after landing.",
        "There is a state for recovery after landing.",
        "reset_signal is also active-low.",
        "State actually updates on negedge clock.",
    ],
)
def test_directional_bump_fall_rejects_later_contradiction(conflict):
    assert bfsm.synth(_directional_prompt(extra=conflict)) is None


@pytest.mark.parametrize(
    "mealy_clause",
    [
        "move_left is also combinationally driven by hit_left.",
        "fall_alarm depends directly on support in the same cycle.",
        "Outputs may depend on current inputs as well as state.",
        "support directly drives fall_alarm combinationally.",
        "While falling, move_left is 1.",
        "When moving left, move_right is also 1.",
    ],
)
def test_directional_bump_fall_rejects_implicit_mealy_output(mealy_clause):
    assert bfsm.synth(_directional_prompt(extra=mealy_clause)) is None


def test_directional_bump_fall_rejects_active_low_support_role():
    prompt = _directional_prompt().replace("input support", "input support_n")
    prompt += " support_n is active-low and indicates present support at zero."
    assert bfsm.synth(prompt) is None


@pytest.mark.parametrize(
    "reset_name",
    [
        "areset_n",
        "reset_n_i",
        "areset_n_i",
        "reset_ni",
        "reset_b",
        "reset_bar",
        "reset_l",
        "no_reset",
        "not_reset",
        "reset_disable",
    ],
)
def test_directional_bump_fall_rejects_noncanonical_reset_names(reset_name):
    """Shape C emits active-high reset only for its finite positive aliases."""
    prompt = _directional_module_prompt().replace("areset", reset_name)
    assert prompt != _directional_module_prompt()
    assert bfsm.synth(prompt) is None


@pytest.mark.parametrize(
    "old,new",
    [
        ("input ground,", "input no_ground,"),
        ("input ground,", "input ground_absent,"),
        ("input bump_left,", "input no_bump_left,"),
        ("input bump_left,", "input bump_left_disable,"),
    ],
)
def test_directional_bump_fall_rejects_noncanonical_role_identifiers(old, new):
    """Role names come from a finite positive grammar, never token containment."""
    prompt = _directional_module_prompt().replace(old, new)
    assert prompt != _directional_module_prompt()
    assert bfsm.synth(prompt) is None


_ACTOR_IDENTITY_MUTATIONS = (
    (r"if a Lemming is bumped", "if a Wall is bumped"),
    (r"the Lemming will fall", "the Clock will fall"),
    (r"the Lemming machine\s+to\s+walk\s+left",
     "the Robot machine to walk left"),
)


@pytest.mark.parametrize("pattern,replacement", _ACTOR_IDENTITY_MUTATIONS)
def test_directional_bump_fall_binds_one_actor_across_every_clause(
        pattern, replacement):
    prompt = _named_directional_fixture_prompt()
    mutated, count = re.subn(pattern, replacement, prompt, count=1)
    assert count == 1
    assert bfsm.synth(mutated) is None


def test_directional_bump_fall_rejects_multiple_actor_identity_mutations():
    prompt = _named_directional_fixture_prompt()
    for pattern, replacement in _ACTOR_IDENTITY_MUTATIONS:
        prompt, count = re.subn(pattern, replacement, prompt, count=1)
        assert count == 1
    assert bfsm.synth(prompt) is None


def test_directional_bump_fall_does_not_collapse_distinct_actor_identifiers():
    prompt = _named_directional_fixture_prompt().replace("Lemming", "robot_")
    prompt = prompt.replace(
        "if a robot_ is bumped", "if a robot_s is bumped", 1)
    assert bfsm.synth(prompt) is None


@pytest.mark.parametrize("role", ["hit_left", "hit_right"])
def test_directional_bump_fall_rejects_active_low_bump_role_name(role):
    prompt = _directional_prompt().replace(f"input {role}", f"input {role}_n")
    assert bfsm.synth(prompt) is None


@pytest.mark.parametrize("role", ["clock", "reset_signal"])
def test_directional_bump_fall_requires_scalar_clock_and_reset(role):
    prompt = _directional_prompt().replace(
        f"input {role}", f"input [1:0] {role}")
    assert bfsm.synth(prompt) is None


@pytest.mark.parametrize("role", ["clock", "hit_left", "move_left"])
def test_directional_bump_fall_rejects_packed_one_bit_port(role):
    prompt = _directional_prompt().replace(
        f"input {role}" if role != "move_left" else f"output {role}",
        f"input [7:7] {role}" if role != "move_left"
        else f"output [7:7] {role}")
    assert bfsm.synth(prompt) is None


@pytest.mark.parametrize(
    "first,second",
    [("input bump_left,", "input bump_right,"),
     ("output walk_left,", "output walk_right,")],
)
def test_directional_bump_fall_rejects_port_order_rewrite(first, second):
    prompt = _directional_module_prompt()
    prompt = prompt.replace(
        f"{first}\n    {second}", f"{second}\n    {first}")
    assert bfsm.synth(prompt) is None


def test_directional_bump_fall_rejects_cross_direction_port_interleave():
    prompt = _directional_module_prompt()
    old = (
        "input clk,\n"
        "    input areset,\n"
        "    input bump_left,\n"
        "    input bump_right,\n"
        "    input ground,\n"
        "    output walk_left,\n"
        "    output walk_right,\n"
        "    output aaah")
    new = (
        "input clk,\n"
        "    output walk_left,\n"
        "    input areset,\n"
        "    output walk_right,\n"
        "    input bump_left,\n"
        "    output aaah,\n"
        "    input bump_right,\n"
        "    input ground")
    assert old in prompt
    assert bfsm.synth(prompt.replace(old, new)) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda text: text.replace(
            "input ground,", "input ground, // 0 means support is present"),
        lambda text: text.replace(
            "input clk,", "input clk, // falling keeps walk_left high"),
        lambda text: text + (
            "\nmodule Extra(input x /* While falling, walk_left remains "
            "asserted */);\n"),
    ],
)
def test_directional_bump_fall_rejects_annotated_or_extra_module_header(mutation):
    assert bfsm.synth(mutation(_directional_module_prompt())) is None


@pytest.mark.parametrize(
    "preamble",
    [
        "In the world where aaah is low, Lemmings",
        "In the world where walk_right is high during left motion, Lemmings",
    ],
)
def test_directional_bump_fall_rejects_semantic_output_preamble(preamble):
    prompt = _prompt("Prob142_lemmings2")
    prompt = prompt.replace("In the\nLemmings' 2D world, Lemmings", preamble)
    assert bfsm.synth(prompt) is None


# --------------------------------------------------------------------------- #
# Generality guard: the parser is NOT keyword-overfit to any SKU/word.
# A re-skinned latched detector with a DIFFERENT sequence + renamed ports fires;
# a re-skinned pulse with a different N fires — proving structure, not keywords.
# --------------------------------------------------------------------------- #
def test_general_other_sequence_and_ports():
    txt = (
        " - input  clk\n - input  rst_n\n - input  serial_in\n - output found\n"
        "The block searches for the pattern 10110 in serial_in and must set found "
        "to 1, forever, until reset. Reset is active low synchronous.\n")
    rtl = bfsm.synth(txt)
    assert rtl is not None
    assert "serial_in" in rtl and "found" in rtl
    # 10110 -> accept state 5; active-low sync reset honoured.
    assert "ACCEPT = 3'd5" in rtl
    assert "if (!rst_n)" in rtl


def test_general_other_pulse_count_and_polarity():
    txt = (
        " - input  clk\n - input  areset\n - output en\n"
        "Whenever the machine is reset, assert en for exactly 7 cycles, then 0 "
        "forever (until reset). areset is asynchronous active high.\n")
    rtl = bfsm.synth(txt)
    assert rtl is not None
    assert "DONE = 3'd7" in rtl                     # 7 active cycles
    assert "posedge areset" in rtl                  # async edge emitted


def test_general_directional_shape_with_renamed_ports():
    """Shape C recognizes functional roles and complete facts, not Prob142/SKU."""
    rtl = bfsm.synth(_directional_prompt(), "WalkerCore")
    assert rtl is not None
    assert "module WalkerCore" in rtl
    assert "hit_left" in rtl and "hit_right" in rtl and "support" in rtl
    assert "move_left" in rtl and "move_right" in rtl and "fall_alarm" in rtl
    assert "posedge clock or posedge reset_signal" in rtl


def test_general_directional_shape_with_renamed_story_noun():
    body = _directional_module_prompt()
    body = body.replace("for a creature", "for a robot")
    body = body.replace("the creature will fall", "the robot will fall")
    body = body.replace("resetting the machine to", "resetting the robot to")
    prompt = (
        "The game Robots involves creatures with fairly simple brains. "
        "So simple that we are going to model it using a finite state machine. "
        "In the Robots' 2D world, Robots can be in one of two states: walking "
        "left (walk_left is 1) or walking right (walk_right is 1). "
        + body)
    rtl = bfsm.synth(prompt)
    assert rtl is not None
    assert "module TopModule" in rtl


def test_benign_game_preamble_is_not_benchmark_noun_sensitive():
    """A consistently renamed story actor is not benchmark-noun sensitive."""
    for game, actor in (("Walkers", "walker"), ("Robots", "robot")):
        base = _directional_prompt().replace("walker", actor)
        prompt = (
            base
            + f" The game {game} involves critters with fairly simple brains."
        )
        assert bfsm.synth(prompt) is not None, game


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
