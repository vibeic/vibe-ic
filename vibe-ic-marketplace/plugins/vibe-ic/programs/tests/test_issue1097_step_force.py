"""S6 (vibe-ic#1097) — `--force-step`: re-run one step, and NOTHING else changes.

ORFS ships `do-2_1_floorplan` beside `2_1_floorplan` (`flow/Makefile:366-405`)
so a caller can bypass make's UP-TO-DATE judgement. Measured here at
`a38902d1`: `grep -rl -- '--force-step' programs/*.py` -> 0 files.

The load-bearing distinction, and the reason this module is not in
`step_preflight`:

    FRESHNESS   "may this cached artefact be reused by THIS build?"   <- bypassed
    CORRECTNESS "does this step have the inputs the flow says it reads?" <- NOT

`test_forcing_a_step_does_NOT_bypass_the_input_contract` is the pin.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import step_force as SF  # noqa: E402


# --------------------------------------------------------------------------- #
# The flag itself
# --------------------------------------------------------------------------- #
def test_an_unknown_kind_is_REFUSED_not_ignored():
    """A typo that forces nothing leaves the operator believing a step re-ran
    when it did not — they then read a cached result and conclude the bug is
    elsewhere. Refusing is the only honest answer."""
    with pytest.raises(SF.UnknownStep) as e:
        SF.resolve(["pnrr"])
    assert "names no forceable step" in str(e.value)
    assert "pnr" in str(e.value)          # names the alternatives


def test_a_known_kind_resolves_and_round_trips():
    assert SF.resolve(["pnr"]) == {"pnr"}
    assert SF.resolve(["PNR", " gds "]) == {"pnr", "gds"}
    assert SF.as_env_value(["gds", "pnr"]) == "gds,pnr"   # sorted, reproducible


def test_unset_means_nothing_is_forced():
    assert SF.forced({}) == set()
    assert SF.is_forced("pnr", {}) is False


def test_the_env_channel_is_read():
    env = {SF.ENV: "pnr,gds"}
    assert SF.forced(env) == {"pnr", "gds"}
    assert SF.is_forced("pnr", env) is True
    assert SF.is_forced("synth", env) is False


def test_the_disclosure_says_freshness_only():
    """Carried into the step's own `detail`, so the published report can
    explain why an artefact changed. A banner in a log is lost."""
    d = SF.disclosure("pnr")
    assert "forced by --force-step pnr" in d
    assert "freshness" in d
    assert "input contract was still enforced" in d


# --------------------------------------------------------------------------- #
# The declared kinds are PINNED to the runner, not guessed
# --------------------------------------------------------------------------- #
def test_the_declared_kinds_match_the_runner():
    """A fourth producer added at a call site must fail HERE rather than
    silently becoming unforceable — which would be a flag that looks like it
    covers the flow and does not."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    used = set(re.findall(r"_producer_cache_valid_for\(\s*[^,]+,\s*\"(\w+)\"",
                          src))
    assert used, "no _producer_cache_valid_for call sites found — parse broke"
    assert used == set(SF.KNOWN_KINDS), (
        f"runner uses {sorted(used)}, step_force declares "
        f"{sorted(SF.KNOWN_KINDS)}")


# --------------------------------------------------------------------------- #
# THE BOUNDARY — this is the test that keeps the flag honest
# --------------------------------------------------------------------------- #
def test_forcing_a_step_does_NOT_bypass_the_input_contract():
    """`step_preflight` must not know this flag exists.

    A `--force-step` that dispatched a step whose declared inputs are absent
    would be precisely the switch
    `test_step_preflight.py::test_there_is_no_switch_that_turns_a_refusal_into_a_pass`
    bans — "a weakening switch would make the refusal decorative". Forcing
    means "do the work again", never "do it blind".
    """
    pf = (_PROGRAMS / "step_preflight.py").read_text(encoding="utf-8")
    assert "step_force" not in pf, "the freshness flag reached the input contract"
    assert SF.ENV not in pf
    # And the landed ban itself still holds, re-stated on the S6 side so a
    # future re-wiring fails in the PR that does it.
    envs = set(re.findall(r"os\.environ\.get\(\s*([A-Za-z_]+|\"[^\"]+\")", pf))
    assert envs <= {"STRICT_ENV"}, f"S6 introduced an env knob: {envs}"


# --------------------------------------------------------------------------- #
# The wiring: one predicate, three call sites
# --------------------------------------------------------------------------- #
def test_the_freshness_predicate_denies_reuse_when_forced(tmp_path, monkeypatch):
    """The behaviour, driven through the REAL predicate rather than a copy."""
    import phase3_one_shot_runner as R

    out = tmp_path / "pnr"
    out.mkdir()
    monkeypatch.setenv(SF.ENV, "pnr")
    ok, msg = R._producer_cache_valid_for(out, "pnr")
    assert ok is False, (ok, msg)
    assert "forced by --force-step pnr" in msg
    # a kind that was NOT forced is untouched by this mechanism: it takes the
    # module's ordinary path and its answer is whatever the identity record
    # says — the flag must not silently invalidate the whole cache.
    ok2, msg2 = R._producer_cache_valid_for(out, "gds")
    assert "forced by --force-step" not in msg2, msg2


def test_the_hook_is_wired_before_the_ordinary_path(tmp_path, monkeypatch):
    """Forcing must win over every other reuse verdict, and be ATTRIBUTABLE.

    The first version of this asserted only `after is False`. That passes
    without the wiring at all: an empty directory has no producer-identity
    record, so the ordinary path already denies reuse and the test was vacuous
    — it survived the red arm. The verdict alone cannot distinguish "denied
    because forced" from "denied because stale", so the assertion is on the
    DISCLOSURE, which only the force hook can produce.
    """
    import phase3_one_shot_runner as R
    out = tmp_path / "synth"
    out.mkdir()

    monkeypatch.delenv(SF.ENV, raising=False)
    _, msg_unforced = R._producer_cache_valid_for(out, "synth")
    assert "forced by --force-step" not in msg_unforced, msg_unforced

    monkeypatch.setenv(SF.ENV, "synth")
    forced_ok, msg_forced = R._producer_cache_valid_for(out, "synth")
    assert forced_ok is False, msg_forced
    # The load-bearing half: the reason is the FORCE, not whatever the
    # identity record happened to say.
    assert "forced by --force-step synth" in msg_forced, msg_forced
    assert msg_forced != msg_unforced


# --------------------------------------------------------------------------- #
# PAIRED GUARD
# --------------------------------------------------------------------------- #
def test_forcing_NOTHING_leaves_every_kind_alone():
    """The always-fires guard.

    An `is_forced` that returned True unconditionally passes every positive
    test above. It dies here: with the channel unset, no kind is forced, and
    with one kind set the OTHERS are still not.
    """
    assert SF.forced({}) == set()
    for k in sorted(SF.KNOWN_KINDS):
        assert SF.is_forced(k, {}) is False, k
    env = {SF.ENV: "pnr"}
    others = sorted(set(SF.KNOWN_KINDS) - {"pnr"})
    assert others, "need a second kind for this guard to mean anything"
    for k in others:
        assert SF.is_forced(k, env) is False, k
