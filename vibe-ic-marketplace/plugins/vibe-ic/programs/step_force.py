#!/usr/bin/env python3
"""step_force.py — re-run ONE step without re-running the phase. vibe-ic#1097 S6.

Adopted from OpenROAD-flow-scripts. `flow/Makefile:366-405` ships `do-2_1_floorplan`
beside `2_1_floorplan`; the reason is written at `:366-384` — it lets an external
build system bypass make's UP-TO-DATE judgement and execute the stage anyway.

Measured on this tree at `a38902d1` before writing a line:

    grep -rl -- '--force-step' programs/*.py   ->   0 files

So a close-loop repair re-runs the whole phase to re-test one step.

WHAT "BYPASS THE DEPENDENCY JUDGEMENT" TRANSLATES TO HERE — AND WHAT IT DOES NOT
===============================================================================
In make, the dependency judgement is *"is this target older than its
prerequisites"*. It is a FRESHNESS question, not a correctness gate. `do-` skips
the freshness test; it does not let a stage run without the files it reads.

This repo has both, and they are different objects:

  FRESHNESS   `_producer_cache_valid_for` / `_pnr_cache_valid_for` in
              `phase3_one_shot_runner` — "may this cached artefact be reused by
              THIS build?"  <-- this is make's question, and this is what
              `--force-step` bypasses.

  CORRECTNESS `step_preflight` — "does this step have the inputs the flow says
              it reads?"  <-- this is NOT make's question, and `--force-step`
              MUST NOT bypass it.

Conflating the two would be a real regression, and there is a landed test that
says so in as many words: `test_step_preflight.py::
test_there_is_no_switch_that_turns_a_refusal_into_a_pass` bans every
`os.environ.get` in `step_preflight` except `STRICT_ENV`, because "a weakening
switch would make the refusal decorative". A `--force-step` that dispatched a
step whose declared inputs are absent would be exactly that switch.

So this module lives OUTSIDE `step_preflight`, is consulted only by the
freshness predicates, and `test_forcing_a_step_does_NOT_bypass_the_input_contract`
pins the boundary. Forcing means "do the work again", never "do it blind".

AN UNKNOWN TOKEN IS REFUSED, NOT IGNORED
========================================
`--force-step pnrr` that silently forces nothing is worse than no flag at all:
the operator believes they re-ran PnR, reads a cached result, and concludes the
bug is elsewhere. `resolve()` raises on any token that is not a declared kind.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""

from __future__ import annotations

import os
from typing import FrozenSet, Iterable, List, Optional, Set

#: The environment channel. A flag on one runner cannot reach a predicate deep
#: in another module without threading a parameter through call sites that
#: `step_preflight.py:20-40` documents as un-wrappable, so the flag SETS this
#: and the predicate READS it. Named on the runner's own CLI as
#: `--force-step`.
ENV = "VIBEIC_FORCE_STEP"

#: The producer-identity kinds a run can force, i.e. the artefact classes whose
#: freshness `_producer_cache_valid_for` adjudicates.
#:
#: PINNED, NOT GUESSED: `test_the_declared_kinds_match_the_runner` asserts this
#: set equals the `kind=` literals actually passed at the runner's call sites,
#: so a fourth producer added there fails this module's test rather than
#: silently becoming unforceable.
KNOWN_KINDS: FrozenSet[str] = frozenset({"synth", "pnr", "gds"})


class UnknownStep(ValueError):
    """A token that names no forceable step. Loud by construction."""


def _split(raw: str) -> List[str]:
    out: List[str] = []
    for chunk in str(raw).replace(",", " ").split():
        c = chunk.strip().lower()
        if c:
            out.append(c)
    return out


def resolve(tokens: Iterable[str]) -> Set[str]:
    """Validate and normalise. Raises `UnknownStep` on anything unrecognised.

    The whole point of raising: a typo that forces nothing leaves the operator
    believing a step re-ran when it did not, which is the class of defect this
    repo removes from instruments one at a time.
    """
    got = {t.strip().lower() for t in tokens if str(t).strip()}
    bad = sorted(got - set(KNOWN_KINDS))
    if bad:
        raise UnknownStep(
            f"--force-step: {', '.join(bad)} names no forceable step. "
            f"Known: {', '.join(sorted(KNOWN_KINDS))}. Refusing rather than "
            f"forcing nothing, because a run that silently forced nothing "
            f"reads exactly like one that re-ran the step.")
    return got


def forced(env: Optional[dict] = None) -> Set[str]:
    """The forced set for this process. Empty when the flag was not given.

    Invalid content in the environment is treated as EMPTY here rather than
    raising: this is read from inside a freshness predicate on a hot path, and
    the validation belongs at the CLI boundary where the operator can see the
    error. `resolve()` is what the runner calls when parsing the flag.
    """
    e = os.environ if env is None else env
    raw = e.get(ENV) or ""
    if not raw:
        return set()
    return {t for t in _split(raw) if t in KNOWN_KINDS}


def is_forced(kind: str, env: Optional[dict] = None) -> bool:
    """Is `kind`'s cached artefact to be treated as stale for this build?"""
    return str(kind).strip().lower() in forced(env)


def as_env_value(tokens: Iterable[str]) -> str:
    """The value to put in `ENV`. Sorted so a run is reproducible from its log."""
    return ",".join(sorted(resolve(tokens)))


def disclosure(kind: str, env: Optional[dict] = None) -> str:
    """The sentence the step's own `detail` carries when it was forced.

    Carried into the published report and not only to stderr, for the reason
    `_producer_cache_valid_for`'s docstring gives about its own disclosure: a
    banner in a log is lost, and the JSON report is what every downstream gate
    and every human reads. A forced re-run that looked identical to a natural
    one would make the report unable to explain why the artefact changed.
    """
    return (f"forced by --force-step {kind}: the cached {kind} artefact was "
            f"treated as stale for this build (freshness bypass only — the "
            f"step's declared input contract was still enforced)")
