#!/usr/bin/env python3
"""vibe-ic — a P0 disposition may not promise a home the tree does not have.

The register that records why each un-invocable gate stays un-invocable can say
"driven from the FPGA-compile step" about a gate nothing drives, in the same
present tense it uses for a gate that IS driven. Re-derived at b85d68ac (the
tree carrying #804): 14 gates in the population carry such a claim, and 3 carry
one that is real.

Every test here is BIDIRECTIONAL by construction, because the two ways to break
this check are opposite:

  * too loose  -> a parked disposition ("NOT READY", "unwired", "driven only
                  where the instrument is attached") is read as a broken
                  promise, and the residual is noise;
  * too tight  -> the detector is narrowed until nothing matches, the residual
                  goes to zero, and the 14 real ones are swallowed.

`test_not_ready_is_not_a_home_claim` pins the first (it is an ACTUAL false
positive the first draft produced, on `phase1_gate_contract_check`).
`test_a_backed_claim_is_still_recognised_as_a_claim` pins the second: a
detector tightened to zero stops recognising the three genuine claims too, and
this test goes red before the residual can be quietly emptied.

THE 14TH, and the population it was found in
============================================
`test_an_adverb_between_the_verb_and_its_preposition_is_still_a_claim` and
`test_protocol_gap_check_is_the_fourteenth_unbacked` pin a claim the first draft
could not see: "driven per-protocol from the L-layer spec" is the same promise
as "driven from the vector-generation step", and one hyphenated adverb between
the verb and its preposition was the whole difference between counted and
invisible.

`test_a_disposition_outside_the_pin_is_still_examined` pins the OTHER half: the
population is the pin UNION the registry, so a claim written about a gate the
pin does not list is counted. Its opposite,
`test_a_pinned_gate_with_no_disposition_is_still_examined`, pins that widening
to the registry did not DROP the pin -- four pinned gates have no disposition
written at all and must still be in the denominator.

The over-corrections that widening the detector invites are pinned too:
`test_driven_only_where_is_not_a_home_claim` (the register saying no home
exists, in the words a promise uses) and `test_a_fullstop_is_not_an_adverb`
(intervening words may not cross a sentence boundary).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import p0_disposition_backing_check as B  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

REPO_ROOT = PROGRAMS.parents[3]
PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"


# ---------------------------------------------------------------------------
# the claim detector — the two words that mean the opposite of each other
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "KEEP registered, driven at the final acceptance gate.",
    "KEEP registered, driven from the FPGA-compile step that emits the .qsf.",
    "KEEP registered, driven by the L-doc validators that supply the schema.",
    "KEEP registered, driven explicitly from the L-layer spec.",
    "READY — wired into tools/ci/repo_hygiene_gates.sh.",
])
def test_present_tense_home_claims_are_recognised(text):
    assert B.claims_a_home(text) is True


@pytest.mark.parametrize("text", [
    "NOT READY. Wiring it at the current scope buys a green over 7 of 29.",
    "KEEP registered, unwired. This is a schema question first.",
    "DISCLOSURE ONLY — plumbing deliberately not connected.",
    "",
])
def test_parked_dispositions_are_not_home_claims(text):
    assert B.claims_a_home(text) is False


# ---------------------------------------------------------------------------
# THE 14TH SHAPE — an adverb between the verb and its preposition
# ---------------------------------------------------------------------------

#: `protocol_gap_check`'s disposition, verbatim from the registry.
PROTOCOL_GAP_DISPOSITION = ("KEEP registered, driven per-protocol from the "
                            "L-layer spec that states the inter-frame gap.")

#: `scope_periodic_pulse_check`'s, verbatim. The register saying NO home exists,
#: using the same verb a promise uses.
SCOPE_PULSE_DISPOSITION = (
    "KEEP registered, driven only where the instrument is attached. No CI "
    "runner and no per-project umbrella can satisfy it, and a synthetic "
    "capture would make it assert about a trace nobody measured.")


@pytest.mark.parametrize("text", [
    PROTOCOL_GAP_DISPOSITION,
    "KEEP registered, driven per-project from the acceptance step.",
    "KEEP registered, driven once per corpus from the umbrella.",
])
def test_an_adverb_between_the_verb_and_its_preposition_is_still_a_claim(text):
    """The 14th shape. `driven <adverb> from X` is `driven from X`.

    The first draft required the preposition to sit immediately after the verb,
    so this promise — identical in tense, force and consequence to
    `crc_seed_consistency_check`'s "driven from the vector-generation step" —
    was filed under "makes no claim" and never counted.
    """
    assert B.claims_a_home(text) is True


@pytest.mark.parametrize("text", [
    SCOPE_PULSE_DISPOSITION,
    "KEEP registered, driven wherever an operator decides to run it.",
    "KEEP registered, driven wherever the instrument is attached.",
])
def test_driven_only_where_is_not_a_home_claim(text):
    """REVERSE — the over-correction widening invites, and must not make.

    "driven only where the instrument is attached" names no place in this tree;
    the very next sentence says no CI runner can satisfy it. A detector widened
    to `driven .* (at|from|by|where)` reads the register's honesty as a promise
    and reports a correctly-parked gate — WRONG WAY 2 at one remove.
    """
    assert B.claims_a_home(text) is False


def test_a_fullstop_is_not_an_adverb():
    """REVERSE — the window may not cross a sentence boundary.

    A window of `.{0,40}` matches "driven. Everything at" across the fullstop
    and turns a parked disposition into a claim. Excluding sentence punctuation
    from the class is what stops it, and this is the test that goes red if a
    later edit relaxes it to a plain `.`.
    """
    parked = ("KEEP, unwired. Nothing is driven. Everything at this tier is "
              "parked until the schema question is settled.")
    assert "driven" in parked and " at " in parked   # the trap is really there
    assert B.claims_a_home(parked) is False          # and it is not taken


def test_a_comma_ends_the_clause():
    """REVERSE — the second bound. Without the comma in the excluded class,
    "not driven, and the argv is built BY the umbrella" reads as `driven ... by`
    and a disposition describing the umbrella becomes a promise about a home.
    """
    parked = ("KEEP registered, not driven, and the argv is built by the "
              "umbrella from values no scan can supply.")
    assert "driven" in parked and " by " in parked
    assert B.claims_a_home(parked) is False


def test_a_preposition_four_clauses_later_is_not_this_verbs():
    """REVERSE — the third bound. An unbounded window makes every sentence
    containing both words a claim."""
    parked = ("KEEP registered, driven — and this long parenthetical wanders "
              "well past forty characters before it gets anywhere near a "
              "preposition — from CI.")
    assert B.claims_a_home(parked) is False


def test_not_ready_is_not_a_home_claim():
    """The exact false positive the first draft of the checker produced.

    `phase1_gate_contract_check`'s disposition opens "NOT READY." and the naive
    `\\bREADY\\b` matched inside it, reporting a deliberately-parked gate as a
    broken promise. Reading a refusal as an assertion inverts the register.
    """
    parked = "NOT READY. Wiring it at the current scope buys a green over 7 of 29."
    assert "READY" in parked                      # the trap is really there
    assert B.claims_a_home(parked) is False       # and it is not taken


# ---------------------------------------------------------------------------
# the driver predicate — a mention is not an invocation
# ---------------------------------------------------------------------------

def test_a_comment_mention_is_not_an_invocation():
    """WRONG WAY 1: `tools/ci/repo_hygiene_gates.sh` contains the line
    "A third, `phase1_gate_contract_check`, is deliberately NOT here."
    A bare-name search reads that as a driver and clears the gate."""
    comment = ("# A third, `phase1_gate_contract_check`, is deliberately "
               "NOT here. Its scope is too narrow.\n")
    assert "phase1_gate_contract_check" in comment          # bare name present
    assert B.is_invoked("phase1_gate_contract_check", [comment]) is False


def test_a_real_invocation_is_an_invocation():
    """The reverse of the case above — same gate name, invocation form."""
    line = 'run "hygiene" "$PLUGIN" python3 programs/some_gate_check.py\n'
    assert B.is_invoked("some_gate_check", [line]) is True


# ---------------------------------------------------------------------------
# end-to-end over a synthetic tree — FORWARD and REVERSE in one fixture
# ---------------------------------------------------------------------------

def _tree(tmp_path: Path, dispositions: dict, driver_body: str = "",
          pinned=None) -> Path:
    """A minimal repo shaped like the real one.

    `pinned` defaults to the disposition keys — the aligned case. Passing it
    explicitly is how the two population sources are made to DISAGREE, which is
    the case the real tree cannot exhibit today and the reason the population is
    derived rather than taken from either source alone.
    """
    programs = tmp_path / PLUGIN_REL / "programs"
    programs.mkdir(parents=True)
    (tmp_path / PLUGIN_REL / "flow").mkdir(parents=True)
    (tmp_path / "tools" / "ci").mkdir(parents=True)
    (tmp_path / "tools" / "ci" / "hygiene.sh").write_text(driver_body or "#\n")
    body = ["_REGISTER = {"]
    for gate, text in dispositions.items():
        body.append(f'    "{gate}": {{"disposition": {text!r}}},')
    body.append("}")
    (programs / B.REGISTRY_MODULE).write_text("\n".join(body) + "\n")
    (programs / "p0_gate_invocability_drift_check.py").write_text(
        "KNOWN_NOT_INVOCABLE = (\n"
        + "".join(f'    "{g}",\n'
                  for g in (dispositions if pinned is None else pinned))
        + ")\n")
    return tmp_path


def test_a_claim_with_no_driver_is_reported_unbacked(tmp_path):
    """FORWARD: the defect this check exists to catch."""
    root = _tree(tmp_path, {
        "promised_gate_check": "KEEP registered, driven at the acceptance gate.",
    })
    unbacked, backed, no_claim = B.measure(
        root, ["promised_gate_check"],
        root / PLUGIN_REL / "programs" / B.REGISTRY_MODULE)
    assert unbacked == ["promised_gate_check"]
    assert backed == [] and no_claim == []


def test_a_backed_claim_is_still_recognised_as_a_claim(tmp_path):
    """REVERSE — the anti-tighten-to-zero control.

    Same disposition wording as the forward case; the ONLY difference is that a
    driver invokes it. It must land in `backed`, not vanish. A detector
    narrowed until the residual is zero fails here, because `backed` empties at
    the same moment `unbacked` does.
    """
    root = _tree(tmp_path, {
        "promised_gate_check": "KEEP registered, driven at the acceptance gate.",
    }, driver_body="python3 programs/promised_gate_check.py --project-dir .\n")
    unbacked, backed, no_claim = B.measure(
        root, ["promised_gate_check"],
        root / PLUGIN_REL / "programs" / B.REGISTRY_MODULE)
    assert backed == ["promised_gate_check"]
    assert unbacked == [] and no_claim == []


def test_a_parked_gate_is_neither_backed_nor_unbacked(tmp_path):
    """The third bucket must stay a bucket: parking is not a promise."""
    root = _tree(tmp_path, {
        "parked_gate_check": "KEEP registered, unwired. Settle the schema first.",
    })
    unbacked, backed, no_claim = B.measure(
        root, ["parked_gate_check"],
        root / PLUGIN_REL / "programs" / B.REGISTRY_MODULE)
    assert no_claim == ["parked_gate_check"]
    assert unbacked == [] and backed == []


# ---------------------------------------------------------------------------
# the ratchet — it must be able to FAIL
# ---------------------------------------------------------------------------

def _run(root: Path, out: Path):
    return _pr.run(
        [sys.executable, str(PROGRAMS / "p0_disposition_backing_check.py"),
         "--repo-root", str(root), "--json", str(out)],
        capture_output=True, text=True)


def test_a_newly_unbacked_claim_fails(tmp_path, monkeypatch):
    """A 14th broken promise exits 1. Without this, the check cannot fail and
    clearing both other bars would be meaningless."""
    root = _tree(tmp_path, {
        "brand_new_gate_check": "KEEP registered, driven from the step that emits it.",
    })
    out = tmp_path / "r.json"
    proc = _run(root, out)
    assert proc.returncode == B.RC_DRIFT, proc.stdout + proc.stderr
    payload = json.loads(out.read_text())
    assert payload["newly_unbacked"] == ["brand_new_gate_check"]
    assert payload["summary"]["pass"] is False


def test_a_recorded_name_that_got_wired_still_exits_zero(tmp_path):
    """Fixing a gate must not fail the ratchet — subset, not equality."""
    root = _tree(tmp_path, {
        "warn_acceptance_policy_check":
            "KEEP registered, driven at the final acceptance gate.",
    }, driver_body="python3 programs/warn_acceptance_policy_check.py --project-dir .\n")
    out = tmp_path / "r.json"
    proc = _run(root, out)
    assert proc.returncode == B.RC_OK, proc.stdout + proc.stderr
    assert json.loads(out.read_text())["unbacked"] == []


# ---------------------------------------------------------------------------
# the POPULATION — the pin UNION the registry, and neither one alone
# ---------------------------------------------------------------------------

def test_a_disposition_outside_the_pin_is_still_examined(tmp_path):
    """FORWARD: a broken promise about a gate the pin does not list.

    The pin is one hand-written list of names; the dispositions are hand-written
    into four registers, and nothing makes them agree. Taking the population
    from the pin alone means a claim written about any gate outside it — a stale
    promise left behind when the gate got wired and dropped off the pin, a
    register grown for an invocable gate — is examined by nobody, counted in no
    residual, and can never fail. This checker's own defect, turned on itself.
    """
    root = _tree(tmp_path, {
        "pinned_gate_check": "KEEP registered, unwired. Settle the schema.",
        "outside_the_pin_check":
            "KEEP registered, driven from the acceptance step.",
    }, pinned=["pinned_gate_check"])
    out = tmp_path / "r.json"
    proc = _run(root, out)
    assert proc.returncode == B.RC_DRIFT, proc.stdout + proc.stderr
    payload = json.loads(out.read_text())
    assert payload["newly_unbacked"] == ["outside_the_pin_check"]
    assert payload["summary"]["examined"] == 2


def test_a_pinned_gate_with_no_disposition_is_still_examined(tmp_path):
    """REVERSE: widening to the registry must not DROP the pin.

    Four of the pinned gates have no disposition written at all. Replacing the
    pin with the registry — the tidy-looking version of this fix — silently
    shrinks the denominator by exactly those four, which is the
    disappearing-denominator shape #492 was about. They belong in `no_claim`,
    not outside the count.
    """
    root = _tree(tmp_path, {
        "documented_gate_check": "KEEP registered, unwired. Settle the schema.",
    }, pinned=["documented_gate_check", "undocumented_gate_check"])
    out = tmp_path / "r.json"
    proc = _run(root, out)
    assert proc.returncode == B.RC_OK, proc.stdout + proc.stderr
    payload = json.loads(out.read_text())
    assert payload["summary"]["examined"] == 2
    assert payload["no_claim"] == ["documented_gate_check",
                                   "undocumented_gate_check"]


def test_a_gate_in_neither_source_is_not_examined(tmp_path):
    """REVERSE: the population is the union of TWO sources, not "everything".

    The other over-correction a population widening invites is widening it to
    the whole 246-gate registry. Two hundred and ten invocable gates about which
    nobody wrote anything would land in `no_claim`, and the residual would stop
    meaning "how many recorded decisions are broken promises" — the denominator
    would grow until the numerator looked small. A gate that is neither pinned
    nor written about is not in the population.
    """
    root = _tree(tmp_path, {
        "documented_gate_check": "KEEP registered, unwired. Settle the schema.",
    }, pinned=["documented_gate_check"])
    (root / PLUGIN_REL / "programs" / "unrelated_gate_check.py").write_text(
        "# an ordinary invocable gate nobody wrote a disposition about\n")
    out = tmp_path / "r.json"
    proc = _run(root, out)
    assert proc.returncode == B.RC_OK, proc.stdout + proc.stderr
    payload = json.loads(out.read_text())
    assert payload["summary"]["examined"] == 1
    assert "unrelated_gate_check" not in (
        payload["unbacked"] + payload["backed"] + payload["no_claim"])


def test_missing_registry_cannot_measure(tmp_path):
    """Degrade loudly: an unreadable tree is rc 2, never a green rc 0."""
    (tmp_path / PLUGIN_REL / "programs").mkdir(parents=True)
    proc = _run(tmp_path, tmp_path / "r.json")
    assert proc.returncode == B.RC_CANNOT_MEASURE


def test_an_unparseable_registry_cannot_measure(tmp_path):
    """...and rc 2, not rc 1.

    Reading the registry moved ahead of `measure` so the population could be
    derived from it. `ast.parse` on a half-written module raises `SyntaxError`,
    which is not an `OSError` or a `LookupError` — uncaught it becomes a
    traceback and a process exit of 1, and 1 is this program's "a NEW broken
    promise appeared". A reader cannot tell a real finding from a parse error
    by the exit code, so it has to be rc 2.
    """
    root = _tree(tmp_path, {"a_gate_check": "KEEP registered, unwired."})
    (root / PLUGIN_REL / "programs" / B.REGISTRY_MODULE).write_text(
        "_REGISTER = {\n    'a_gate_check': {'disposition': \n")
    proc = _run(root, tmp_path / "r.json")
    assert proc.returncode == B.RC_CANNOT_MEASURE, proc.stdout + proc.stderr
    assert "CANNOT MEASURE" in proc.stderr


def test_a_disposition_that_is_not_a_literal_cannot_measure(tmp_path):
    """A promise made invisible by a FORMATTING choice, not a wording one.

    The `ast` reader evaluates the disposition value as a literal. An f-string,
    a `"a" + b` concatenation or a bare name is not one, and the value was
    dropped silently — which files the gate under "wrote no disposition", the
    exact disappearance this checker exists to stop, reached by a different
    route. rc 2 with the gate named, never a green rc 0.
    """
    programs = tmp_path / PLUGIN_REL / "programs"
    programs.mkdir(parents=True)
    (tmp_path / PLUGIN_REL / "flow").mkdir(parents=True)
    (tmp_path / "tools" / "ci").mkdir(parents=True)
    (tmp_path / "tools" / "ci" / "hygiene.sh").write_text("#\n")
    (programs / B.REGISTRY_MODULE).write_text(
        '_WHERE = "the acceptance step"\n'
        '_REGISTER = {\n'
        '    "formatted_gate_check": {"disposition": f"KEEP, driven at {_WHERE}."},\n'
        '}\n')
    (programs / "p0_gate_invocability_drift_check.py").write_text(
        'KNOWN_NOT_INVOCABLE = (\n    "formatted_gate_check",\n)\n')
    proc = _run(tmp_path, tmp_path / "r.json")
    assert proc.returncode == B.RC_CANNOT_MEASURE, proc.stdout + proc.stderr
    assert "formatted_gate_check" in proc.stderr


# ---------------------------------------------------------------------------
# the live tree — the corpus arm
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (REPO_ROOT / "tools" / "ci").is_dir(),
                    reason="not running inside a full repo checkout")
def test_current_tree_holds_the_subset(tmp_path):
    out = tmp_path / "r.json"
    proc = _run(REPO_ROOT, out)
    assert proc.returncode == B.RC_OK, proc.stdout + proc.stderr
    payload = json.loads(out.read_text())
    assert payload["newly_unbacked"] == []
    # The three genuinely-backed claims are the live half of the reverse
    # control: they PROVE the detector still recognises a claim after every
    # tightening, so the residual cannot be emptied by narrowing.
    assert payload["backed"], "no claim recognised at all — detector collapsed"
    assert payload["summary"]["examined"] == (
        payload["summary"]["unbacked"] + payload["summary"]["backed"]
        + payload["summary"]["no_claim"])


@pytest.mark.skipif(not (REPO_ROOT / "tools" / "ci").is_dir(),
                    reason="not running inside a full repo checkout")
def test_protocol_gap_check_is_the_fourteenth_unbacked(tmp_path):
    """The 14th, on the REAL tree — not a fixture.

    Its disposition names a home ("the L-layer spec that states the inter-frame
    gap") and nothing in the repository invokes `protocol_gap_check.py`: no flow
    step, no runner, no orchestrator, no CI script, no workflow. Before the
    adverb clause it sat in `no_claim`, indistinguishable from the twenty gates
    the register is honest about.
    """
    out = tmp_path / "r.json"
    proc = _run(REPO_ROOT, out)
    payload = json.loads(out.read_text())
    assert "protocol_gap_check" in payload["unbacked"], proc.stdout
    assert "protocol_gap_check" not in payload["no_claim"]
    assert "protocol_gap_check" in B.KNOWN_UNBACKED


@pytest.mark.skipif(not (REPO_ROOT / "tools" / "ci").is_dir(),
                    reason="not running inside a full repo checkout")
def test_scope_periodic_pulse_check_stays_parked_on_the_live_tree(tmp_path):
    """REVERSE on the REAL tree — the gate whose disposition uses the same verb
    to say the opposite. It must stay in `no_claim` across the widening."""
    out = tmp_path / "r.json"
    proc = _run(REPO_ROOT, out)
    payload = json.loads(out.read_text())
    assert "scope_periodic_pulse_check" in payload["no_claim"], proc.stdout
    assert "scope_periodic_pulse_check" not in payload["unbacked"]


@pytest.mark.skipif(not (REPO_ROOT / "tools" / "ci").is_dir(),
                    reason="not running inside a full repo checkout")
def test_live_population_covers_both_sources(tmp_path):
    """INVARIANT (not a control — it holds before and after): the denominator
    is the union, so it covers every pinned gate AND every gate with a written
    disposition. Both source lists are re-read here from disk rather than taken
    from the program, so the check is not the program agreeing with itself.
    """
    programs_dir = REPO_ROOT / PLUGIN_REL / "programs"
    pinned = set(B._pinned_gates(programs_dir))
    documented = set(B.read_dispositions(programs_dir / B.REGISTRY_MODULE))
    out = tmp_path / "r.json"
    proc = _run(REPO_ROOT, out)
    payload = json.loads(out.read_text())
    measured = set(payload["unbacked"] + payload["backed"]
                   + payload["no_claim"])
    assert pinned <= measured, sorted(pinned - measured)
    assert documented <= measured, sorted(documented - measured)
    assert payload["summary"]["examined"] == len(pinned | documented), (
        proc.stdout)
