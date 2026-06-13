"""ORGANIC #625 [MEDIUM] — the L6 FSM prose state-to-state walker captured the
transition VERB itself (TRANSITIONS / RETURNS / GOES / MOVES / WHEN) as a
spurious FSM state name. e.g. "the FSM transitions to LOAD; RUN transitions to
DONE; returns to IDLE" yielded bogus states TRANSITIONS and RETURNS alongside
the real ones. This is the English transition-VERB axis, DISTINCT from #606
(register/address-map names + data-movement "to" clauses).

OBSERVED (round-1 v1.0.18 field-verification of #606): a genuine-FSM fixture
("IDLE on reset; transitions to LOAD; transitions to RUN; RUN transitions to
DONE; returns to IDLE" + arrow IDLE -> LOAD -> RUN -> DONE) captured TRANSITIONS
and RETURNS as fsm_states alongside the real IDLE/RUN/DONE.

Fix: when the state-to-state operator is the bare word `to` (not an arrow) and
the FROM-endpoint is a bare English transition/control verb, suppress ONLY that
from-endpoint. The to-endpoint (the transition OBJECT) is ALWAYS promoted, and
arrow-form matches keep both endpoints, so a real state named RETURN_STATE /
WAIT in object or arrow position survives.

POSITIVE (#625): the issue's fixture yields NO TRANSITIONS/RETURNS; the real
IDLE/RUN/DONE are preserved.

NEGATIVE no-leak:
  - a compound state RETURN_STATE (contains "RETURN") in arrow position is
    NOT suppressed.
  - a real state WAIT in arrow position is NOT suppressed.
  - the to-endpoint (object) is promoted even when the from is a verb.
  - the bare verb deny-list is EXACT-token (RETURN != RETURN_STATE).

chip-AGNOSTIC: grammar-role + verb deny-list, no chip name. The issue's
discriminating sentence is embedded verbatim.
"""
import json
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase1_doc_one_shot_runner as P  # noqa: E402

# the #625 fixture, verbatim
REAL_L2 = (
    "# L2\n\n## Control FSM\n"
    "The control state machine: IDLE on reset; transitions to LOAD; "
    "transitions to RUN; RUN transitions to DONE; returns to IDLE.\n"
    "Arrow form: IDLE -> LOAD -> RUN -> DONE\n"
)

_RE = P._V1_6_484_FSM_STATE_TO_STATE_RE


def _l6_states(l2_text):
    proj = Path(tempfile.mkdtemp())
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    res = P.gen_l6_control_logic(proj, {"L2_architecture.md": l2_text})
    data = json.loads(Path(res.path).read_text())
    states = data.get("fsm_states") or data.get("states") or []
    return sorted(s.get("name") for s in states if isinstance(s, dict))


def _first(s):
    for m in _RE.finditer(s):
        return m
    return None


def test_e2e_transition_verbs_not_captured():
    names = _l6_states(REAL_L2)
    assert "TRANSITIONS" not in names
    assert "RETURNS" not in names


def test_e2e_real_states_preserved():
    # NO-LEAK: the genuine arrow/object states survive (#606 no-leak still held).
    names = _l6_states(REAL_L2)
    assert {"IDLE", "RUN", "DONE"} <= set(names), names


def test_helper_word_to_verb_from_suppressed():
    assert P._v1_6_625_is_transition_verb_from(_first("RUN transitions to DONE")) is True
    assert P._v1_6_625_is_transition_verb_from(_first("returns to IDLE")) is True


def test_helper_arrow_never_suppressed():
    # arrow form keeps both endpoints even if the from looks verb-ish.
    m = _first("RETURN_STATE -> IDLE")
    assert m is not None and P._v1_6_625_is_transition_verb_from(m) is False


def test_no_leak_compound_and_real_states_in_arrow():
    for s, frm in (("RETURN_STATE -> IDLE", "RETURN_STATE"),
                   ("WAIT -> RUN", "WAIT")):
        m = _first(s)
        assert m is not None and m.group("from_state") == frm
        # not a verb → from-endpoint promoted (not suppressed)
        assert P._v1_6_625_is_transition_verb_from(m) is False


def test_object_endpoint_always_kept():
    # the to-endpoint (object) is promoted even when from is a verb: the regex
    # captures `transitions to RUN_STATE` with to=RUN_STATE.
    m = _first("transitions to RUN_STATE")
    assert m is not None
    assert P._v1_6_625_is_transition_verb_from(m) is True  # from suppressed
    assert m.group("to_state") == "RUN_STATE"  # object captured & kept


def test_verb_set_is_exact_token():
    assert "TRANSITIONS" in P._V1_6_625_TRANSITION_VERBS
    assert "RETURNS" in P._V1_6_625_TRANSITION_VERBS
    assert "GOES" in P._V1_6_625_TRANSITION_VERBS
    assert "RETURN_STATE" not in P._V1_6_625_TRANSITION_VERBS
    assert "WAIT" not in P._V1_6_625_TRANSITION_VERBS
