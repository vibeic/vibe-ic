"""The L6 walker parsed the transition, kept both endpoints, and threw the edge away.

WHAT WAS MEASURED (#1004)
=========================
Re-running the shipped ``phase1_one_shot_runner`` over every published run
root that carries redistributable input documents (74 of 107; the other 33
carry no ``input/docs/`` and are NO-INPUT, not zero): 16 roots emit
``L6.fsm_states``, and exactly ONE emits a transition.

The cause is not that the documents are silent. ``_V1_6_484_FSM_STATE_TO_STATE_RE``
matches ``<from_state> <op> <to_state>``, runs the entire guard chain over the
match (FSM-context anchor, C-pointer reject, data-movement reject,
bare-word-prose reject, transition-verb reject), promotes BOTH endpoints into
``fsm_states[]`` -- and discards the arrow. A published spec whose state table
reads ``INITIALIZING -> LISTENING  (initialization complete)`` therefore
yielded five states and zero transitions, and the consuming gate reported
``L6 declares 0 transitions ... a conforming phase 2 would receive a state
enum with no transition information at all``.

WHY THIS IS A REPAIR AND NOT "MAKE THE EXTRACTOR EMIT MORE"
===========================================================
An edge is retained only when BOTH endpoints are in the FINAL ``fsm_states[]``.
It therefore asserts nothing the layer had not already asserted -- same
evidence line, same two tokens, same guards -- it adds the relation between two
facts already published. Measured on the same 74 roots: transitions 12 -> 19
(+7, every one verifiable against its source line), states 107 -> 107
(UNCHANGED: the change promotes no state), and no L9 or L6 entry gained.

THE LIMIT THIS TEST PINS, RATHER THAN HIDES
===========================================
An edge is exactly as true as its endpoints. Where the STATE walker already
publishes a false state, the graph over it inherits that error --
``test_edge_never_names_a_state_the_layer_does_not_publish`` is the guarantee
actually made (no dangling target, by construction), and it is not the stronger
guarantee that every endpoint is a real state. The state walker's precision is
out of scope here and was not touched.

NEGATIVE CONTROL
================
Every test drives the shipped runner end-to-end, so each fails BEHAVIOURALLY
against the byte-identical pre-fix program (transitions == 0) rather than
raising on a symbol the pre-fix module does not export.

chip-AGNOSTIC: invented state names, a generic bring-up sequence, and Markdown
direction notation. No chip, vendor, PDK, process or protocol literal
participates.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_RUNNER = _PROGRAMS / "phase1_one_shot_runner.py"


# A state table in the canonical `A -> B  (trigger)` shape.
_FSM_DOC = """# Control Logic

## Link bring-up state machine

The link controller is a finite state machine. Its state table is:

    ARMED     -> PRIMED      (calibration complete)
    PRIMED    -> STREAMING   (peer credit received)
    STREAMING -> ARMED       (credit timeout)
"""

# The same ARROW GLYPH used for something that is not a control relation.
# Kept in its own document so the FSM-context anchor of the state walker
# cannot reach it -- neither endpoint becomes a state, so neither may
# become a transition endpoint either.
_PIN_DOC = """# External Interface

## Pin directions

Each row records which side drives the wire. These arrows are direction
notation for a physical connection; they are not a control relation, and
nothing on this page names a controller, a sequencer, or a mode.

    TXDATA : outbound payload   (COREBLOCK -> PADRING)
    RXDATA : inbound payload    (PADRING -> COREBLOCK)
"""


def _run_phase1(tmp_path: Path, docs: dict) -> dict:
    """Run Phase 1 through the shipped runner and return L6."""
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    for name, body in docs.items():
        (d / name).write_text(body, encoding="utf-8")
    # Measured at ~3s for this input; the 60s bound is the harness ceiling
    # (`ci_harness_timeout_ceiling_check`), i.e. ~20x headroom, so THIS call
    # fails the test on a hang rather than the harness killing the session.
    proc = _pr.run([sys.executable, str(_RUNNER), str(tmp_path)],
                          capture_output=True, text=True)
    l6 = tmp_path / "phase1" / "generated_docs" / "L6_CONTROL_LOGIC.json"
    assert l6.is_file(), (
        "Phase 1 emitted no L6 (rc=%s)\n%s"
        % (proc.returncode, proc.stdout[-3000:]))
    return json.loads(l6.read_text())


def _states(l6: dict) -> list:
    return [s for s in (l6.get("fsm_states") or []) if isinstance(s, dict)]


def _edges(l6: dict) -> list:
    out = []
    for s in _states(l6):
        for t in (s.get("transitions") or []):
            out.append((s.get("name"), t))
    return out


def test_a_stated_transition_reaches_l6(tmp_path):
    """NEGATIVE CONTROL — fails BEHAVIOURALLY pre-fix (0 transitions)."""
    l6 = _run_phase1(tmp_path, {"L6_control.md": _FSM_DOC})
    pairs = {(f, str(t.get("to"))) for f, t in _edges(l6)}
    assert pairs, (
        "the document states three transitions in the canonical `A -> B` "
        "shape and L6 carries none: %r" % ([s.get("name") for s in _states(l6)],))
    assert ("ARMED", "PRIMED") in pairs, pairs
    assert ("PRIMED", "STREAMING") in pairs, pairs
    assert ("STREAMING", "ARMED") in pairs, pairs


def test_trigger_is_quoted_from_the_document_not_paraphrased(tmp_path):
    """The parenthetical the document puts after the arrow is the trigger,
    carried verbatim -- an invented trigger would be a new claim."""
    l6 = _run_phase1(tmp_path, {"L6_control.md": _FSM_DOC})
    triggers = {str(t.get("trigger") or "") for _, t in _edges(l6)}
    assert "calibration complete" in triggers, triggers
    assert "peer credit received" in triggers, triggers
    for tr in triggers:
        if tr:
            assert tr in _FSM_DOC, (
                "trigger %r is not a verbatim span of the source document" % tr)


def test_edge_never_names_a_state_the_layer_does_not_publish(tmp_path):
    """THE GUARANTEE — no dangling target, by construction.

    This is what the consuming gate's A3 requirement asks for, satisfied at
    the producer instead of being checked after the fact."""
    l6 = _run_phase1(tmp_path, {"L6_control.md": _FSM_DOC,
                                "L3_pins.md": _PIN_DOC})
    published = {str(s.get("name")).upper() for s in _states(l6)}
    assert published, "fixture produced no states at all"
    for frm, t in _edges(l6):
        assert str(frm).upper() in published, (frm, published)
        assert str(t.get("to")).upper() in published, (t, published)


def test_an_arrow_that_is_not_a_control_relation_yields_no_transition(tmp_path):
    """TIGHTENING GUARD — the same glyph in a direction table must not
    become an edge. Its endpoints never become states, so the
    both-endpoints rule takes the edge down with them."""
    l6 = _run_phase1(tmp_path, {"L6_control.md": _FSM_DOC,
                                "L3_pins.md": _PIN_DOC})
    names = {str(s.get("name")).upper() for s in _states(l6)}
    assert "COREBLOCK" not in names and "PADRING" not in names, names
    for frm, t in _edges(l6):
        assert "PADRING" not in (str(frm).upper(), str(t.get("to")).upper()), t


def test_recovering_edges_promotes_no_state(tmp_path):
    """TIGHTENING GUARD — the state list must be byte-identical with and
    without the transition-bearing document's edges being recovered.

    An extractor that emits MORE STATES in order to emit transitions would
    have traded one defect for a worse one; this pins that it does not."""
    docs = {"L6_control.md": _FSM_DOC, "L3_pins.md": _PIN_DOC}
    l6 = _run_phase1(tmp_path, docs)
    assert [s.get("name") for s in _states(l6)] == ["ARMED", "PRIMED",
                                                    "STREAMING"], \
        [s.get("name") for s in _states(l6)]


def test_a_target_the_state_walker_declined_to_promote_is_not_published(tmp_path):
    """TIGHTENING GUARD — the DESTINATION half of the membership rule.

    Edge collection is anchor-free (see the producer's note: the anchor is a
    state-promotion guard and an edge promotes nothing), so a long state table
    yields edge candidates from rows the state walker's ±300-char window never
    reached. Those rows' endpoints are not states. If only the SOURCE endpoint
    were checked, every such row would publish a transition into a state the
    layer does not declare -- exactly the dangling target the consuming gate
    exists to reject. This drives that case with a table long enough to run
    past the window."""
    rows = [f"PHASE{i:02d}" for i in range(40)]
    table = "\n".join(f"    {a} -> {b}   (step done)"
                      for a, b in zip(rows, rows[1:]))
    doc = ("# Control Logic\n\n## Sequencer state machine\n\n"
           "The sequencer is a finite state machine. Its state table is:\n\n"
           + table + "\n")
    l6 = _run_phase1(tmp_path, {"L6_control.md": doc})
    published = {str(s.get("name")).upper() for s in _states(l6)}
    edges = _edges(l6)
    assert edges, "fixture produced no transitions at all"
    assert len(published) < len(rows), (
        "fixture no longer exercises the case: the state walker promoted "
        "every row, so no edge has an unpromoted target")
    dangling = [t for _, t in edges
                if str(t.get("to")).upper() not in published]
    assert dangling == [], (
        "transition(s) published naming a target the layer does not "
        "declare: %r" % (dangling,))


def test_no_transition_when_the_document_states_none(tmp_path):
    """ZERO MUST STAY ZERO — a document with states and no stated edge
    must not acquire one."""
    doc = ("# Control Logic\n\n## Modes\n\n"
           "The sequencer is a finite state machine with an ARMED state, "
           "a PRIMED state, and a STREAMING state. Each is entered by the "
           "host writing the mode field; the document does not describe "
           "which state follows which.\n")
    l6 = _run_phase1(tmp_path, {"L6_control.md": doc})
    assert _edges(l6) == [], _edges(l6)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
