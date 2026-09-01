#!/usr/bin/env python3
"""A P0 disposition that names a home the tree does not have.

WHY THIS EXISTS
===============
At the historical #804/#559 base, `flow_compliance_check` registered 246
structural gates; 36 rejected the argv the umbrella built and returned no
verdict. Thirty-two of the 36 -- not all of them; this file used to say
"each", and counting them is how that was found -- carry a written DISPOSITION in one of the registers in that
module (`_NOT_A_PROJECT_GATE`, `_SEMANTIC_ARGV_UNDRIVABLE`,
`_ZERO_DENOMINATOR_CLASSIFICATION`, `_UNDRIVABLE_BY_STRUCTURAL_UMBRELLA`). Those
registers are good — they record "I examined it and dismissed it" where the next
reader will find it.

Issue #1968 closes that runtime population with explicit umbrella invocation
contracts. This checker now treats those declarations as real backing and
holds the unbacked-claim residual at zero; the historical census below remains
the negative-control rationale.

But a disposition can say two very different things, in the same voice:

  (a) "READY -- wired into tools/ci/repo_hygiene_gates.sh"
  (b) "KEEP registered, driven at the final acceptance gate, after the
       report-producing steps have run."

(a) is a STATEMENT OF FACT and it is true: that script invokes that program.
(b) is present tense and reads exactly like (a), and it is not true of this
tree. Nothing invokes `warn_acceptance_policy_check` -- not a flow step, not a
runner, not a CI script, not a workflow. The named home was never built.

RE-DERIVED 2026-08-05 at b85d68ac -- the tree that carries #804, so this census
is taken against the umbrella that publishes `registered_gate_count` /
`invoked_gate_count` / `not_invocable_gate_count` and emits ``INCOMPLETE`` when
a registered gate never validly invoked. Over the population below: 19
dispositions make no active home-claim at all (they say "unwired", "settle X
first", "NOT READY" -- honest about being parked), 3 make an active claim that
is BACKED by a real invocation, and **14 make an active claim that nothing in
the tree backs**.

The consequence is this repo's own recurring shape, one level up: the register
measures *that someone thought about the gate*, and it is read as *the gate is
covered*. `p0_gate_invocability_drift_check` pins how many gates cannot be
invoked by the umbrella; nothing pins how many are promised a home that does
not exist. A gate parked with "driven from the FPGA-compile step" and a gate
genuinely driven from the FPGA-compile step are indistinguishable to every
reader and to every program.

WHAT THIS DOES NOT DO
=====================
It does not wire anything, and it does not fail the 14. Turning them red today
would block every landing on prose, and the fix for each is a different piece
of engineering (a step that does not exist yet, a schema question, an
instrument). It pins the size of the problem so it cannot grow silently, and it
prints the residual on every run, pass or fail -- the same shape, and for the
same reason, as `p0_gate_invocability_drift_check`.

THE POPULATION, which is not the pin
====================================
The population is EVERY gate the registry writes a disposition about, UNION the
gates `p0_gate_invocability_drift_check` pins. Not the pin alone -- that was
this file's own version of the defect it detects. The pin is one list of 36
names; the dispositions are written by hand into four registers, and nothing
requires the two to agree. A disposition written for a gate that is NOT in the
pin -- a gate that got wired and dropped out of the pin while its stale claim
stayed behind, a register grown for an invocable gate -- was outside the loop
entirely, so its broken promise could never be counted, printed, or failed on.
Measured at b85d68ac the two sets happen to line up in the direction that
matters (32 dispositions across four registers -- `_NOT_A_PROJECT_GATE` 4,
`_SEMANTIC_ARGV_UNDRIVABLE` 4, `_ZERO_DENOMINATOR_CLASSIFICATION` 8,
`_UNDRIVABLE_BY_STRUCTURAL_UMBRELLA` 16 -- all 36 pinned gates covered, 4 of
them with no disposition written), and "they happen to line up today" is exactly
the property a derived population does not have to depend on.
`dispositions_outside_pin` is printed on every run so the day they diverge is
visible rather than silent.

The promise is only ever written under the `disposition` key, checked and not
assumed: the ten sub-keys the four registers use (`scope`, `measured`,
`requires`, `design_value`, `why_no_umbrella`, `verdict`, `gate_denominator`,
`corpus_probe`, `category`, `disposition`) were swept with `_ACTIVE_CLAIM` and
**0** claim-shaped strings sit outside `disposition`. That is a measurement of
today's tree, not a guarantee -- it is recorded here so the next reader can
re-run it rather than assume it.

THE PREDICATE, and the three ways it is easy to get wrong
=========================================================
`measured (subset of) KNOWN_UNBACKED`. Subset, not a count: a count lets a
newly-unbacked claim hide behind one that got wired.

WRONG WAY 1 -- treating any mention as an invocation. `tools/ci/
repo_hygiene_gates.sh` contains the line "A third, `phase1_gate_contract_check`,
is deliberately NOT here." A substring search on the bare gate name reads that
comment as a driver and clears the gate. The reference must look like an
invocation, so the match is on ``<gate>.py`` -- the thing you type to run it.
The same file's flow-yaml mention of `openroad_tcl_deprecation_check` is prose
too ("the DECLARED INVERSE of ..."); its real backing is the ``.py`` invocation
in the CI script, and only the tighter predicate finds the right one for the
right reason.

WRONG WAY 2 -- narrowing the claim-detector until the residual is zero. Every
term in `_ACTIVE_CLAIM` is answerable from the register text, and the guard
`_NOT_A_CLAIM` exists because the first draft of this file matched "READY"
inside "**NOT READY**" and reported `phase1_gate_contract_check` -- a
disposition that is explicitly and correctly parked -- as an unbacked promise.
That false positive is pinned as a test. The three BACKED gates are the other
half of the same control: if a future edit tightens the detector until nothing
matches, the residual goes to zero AND those three stop being recognised as
claims, and `test_a_backed_claim_is_still_recognised_as_a_claim` goes red.

WRONG WAY 3 -- a claim detector that only recognises the phrasings it was built
from. The first draft required the preposition to sit immediately after the
verb: ``driven (at|from|by|explicitly)``. `protocol_gap_check`'s disposition
reads

    "KEEP registered, driven per-protocol from the L-layer spec that states
     the inter-frame gap."

which is the SAME promise, in the same present tense, as
`crc_seed_consistency_check`'s "KEEP registered, driven from the
vector-generation step that produces its input" -- and nothing in the tree
invokes `protocol_gap_check.py` either (checked over the whole repository: no
flow step, no runner, no orchestrator, no CI script, no workflow; the
`eda_rtl_audit` MCP enum names the bare token and supplies only an rtl_dir,
which cannot satisfy `--end-signal/--bus-idle/--min-cycles`, so it is not the
L-layer home the disposition names). One hyphenated adverb between the verb and
its preposition was the whole difference between counted and invisible. The
detector now allows a short bounded modifier there.

...and the over-correction that widening invites, pinned as its own test:
`scope_periodic_pulse_check` reads "KEEP registered, driven ONLY WHERE the
instrument is attached. No CI runner and no per-project umbrella can satisfy
it." That is the register being honest that no home exists, and a detector
widened to ``driven .* (at|from|by|where)`` reads it as a promise -- the same
inversion as WRONG WAY 2, one remove out. The window may not cross a fullstop
or a comma either, or "Nothing is driven. Everything at this tier is parked."
and "not driven, and the argv is built by the umbrella" both become claims.

Exit: 0 subset holds, 1 a newly-unbacked claim appeared, 2 could not measure.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

RC_OK, RC_DRIFT, RC_CANNOT_MEASURE = 0, 1, 2

#: The module whose registers carry the dispositions. Read with `ast`, never
#: imported: importing `flow_compliance_check` to inspect its own tables runs a
#: 46-thousand-line module for four dict literals.
REGISTRY_MODULE = "flow_compliance_check.py"

#: An active present-tense claim that the gate IS driven from a named place.
#: "driven at/from/by/explicitly", "wired into", "READY".
#:
#: A short modifier may sit between the verb and its preposition, because the
#: register writes "driven per-protocol from the L-layer spec" for the same
#: promise it writes "driven from the vector-generation step" for (WRONG WAY 3).
#: The window is bounded three ways, and every bound is a false positive it was
#: measured to prevent:
#:
#:   `.;:!?`   a fullstop is not an adverb -- without it, "Nothing is driven.
#:             Everything at this tier is parked." matches on `driven ... at`;
#:   `,`       a comma ends the clause -- without it, "driven, and the argv is
#:             built by the umbrella" matches on `driven ... by`;
#:   40 chars  a preposition four clauses later is not this verb's.
#:
#: What it still must NOT match is `scope_periodic_pulse_check`'s "driven only
#: where the instrument is attached" -- no `at`/`from`/`by` stands alone in it
#: ("attached" is not `\bat\b`), and adding `where` to the preposition set is
#: the over-correction pinned by `test_driven_only_where_is_not_a_home_claim`.
_ACTIVE_CLAIM = re.compile(
    r"\bdriven\b[^.;:!?,]{0,40}?\b(?:at|from|by|explicitly)\b"
    r"|\bwired\s+into\b|\bREADY\b")

#: ... and the negations that use the same words. Checked FIRST. A disposition
#: that opens "NOT READY." is the register being honest about a gate it parked;
#: reading it as a promise inverts the meaning of the entry.
_NOT_A_CLAIM = re.compile(r"\bNOT\s+READY\b|\bnot\s+(?:yet\s+)?wired\b")

#: Where a gate can actually be driven from. Globs are relative to the repo
#: root. Kept as data so a new driver surface is one row, not a code change.
DRIVER_GLOBS: Tuple[str, ...] = (
    "vibe-ic-marketplace/plugins/vibe-ic/flow/*.yaml",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/*one_shot_runner*.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/*orchestrat*.py",
    "tools/ci/*.sh",
    ".github/workflows/*.yml",
)

#: MEASURED 2026-08-05, re-derived at b85d68ac (the tree carrying #804), over
#: the derived population: the 36 gates pinned by
#: `p0_gate_invocability_drift_check.KNOWN_NOT_INVOCABLE` UNION every gate the
#: registry writes a disposition about. Each entry's disposition makes an active
#: home-claim and NO file in `DRIVER_GLOBS` invokes `<gate>.py`.
#:
#: This list does not endorse any of them. A name is DELETED when the gate is
#: wired or its disposition stops claiming a home -- never kept with a note,
#: because under a subset predicate a stale name is a free slot for the next
#: broken promise.
# Issue #1968 backs the historical 14 through the P0 umbrella's closed
# invocation-contract registry. A future unbacked claim is therefore new.
KNOWN_UNBACKED: Tuple[str, ...] = ()


def claims_a_home(disposition: str) -> bool:
    """True when the disposition asserts the gate IS driven from somewhere.

    The negation guard runs first and wins: "NOT READY" contains "READY".
    """
    if _NOT_A_CLAIM.search(disposition or ""):
        return False
    return bool(_ACTIVE_CLAIM.search(disposition or ""))


def read_dispositions(registry_path: Path,
                      unreadable: Optional[List[str]] = None) -> Dict[str, str]:
    """Every ``{gate: {"disposition": "..."}}`` entry in the registry module.

    Walks module-level dict assignments with `ast` and collects any nested dict
    carrying a ``disposition`` key. Register-name-agnostic on purpose: a fifth
    register added later is picked up without editing this file, which is the
    failure mode a hard-coded list of register names would have.

    `unreadable`, if given, collects the gates whose disposition VALUE is not a
    literal `ast` can evaluate -- an f-string, a `"a" + b` concatenation, a name.
    That is not a curiosity: dropping such a value silently files the gate under
    "wrote no disposition", which is the same disappearance this whole checker
    exists to stop, reached by a formatting choice instead of a wording one. The
    caller turns a non-empty list into rc 2 -- CANNOT MEASURE, because an
    unreadable promise is not a read one.
    """
    tree = ast.parse(registry_path.read_text(errors="replace"))
    out: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            value = node.value
        else:
            continue
        if not isinstance(value, ast.Dict):
            continue
        for key, val in zip(value.keys, value.values):
            if not (isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and isinstance(val, ast.Dict)):
                continue
            for subkey, subval in zip(val.keys, val.values):
                if (isinstance(subkey, ast.Constant)
                        and subkey.value == "disposition"):
                    try:
                        out[key.value] = " ".join(
                            ast.literal_eval(subval).split())
                    except (ValueError, SyntaxError, TypeError,
                            MemoryError, RecursionError):
                        if unreadable is not None:
                            unreadable.append(key.value)
    return out


def driver_blobs(repo_root: Path,
                 globs: Sequence[str] = DRIVER_GLOBS) -> List[str]:
    """The text of every file a gate could be driven from."""
    blobs: List[str] = []
    for pattern in globs:
        for path in sorted(repo_root.glob(pattern)):
            if path.is_file():
                blobs.append(path.read_text(errors="replace"))
    return blobs


def is_invoked(gate: str, blobs: Sequence[str]) -> bool:
    """True when some driver names ``<gate>.py``.

    The bare gate name is NOT enough: the driver surface contains prose about
    gates it deliberately does not run (WRONG WAY 1 in the module docstring).
    """
    return any(f"{gate}.py" in blob for blob in blobs)


def read_invocation_contracts(registry_path: Path) -> Set[str]:
    """Gate names in the closed P0 invocation-contract registry.

    The production value is ``MappingProxyType({...})``; accepting a literal
    dict as well keeps synthetic tests small. Anything dynamic is unreadable
    and therefore contributes no backing (fail-closed).
    """
    tree = ast.parse(registry_path.read_text(errors="replace"))
    for node in tree.body:
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign)
                   else [])
        if not any(isinstance(t, ast.Name) and
                   t.id == "_STRUCTURAL_GATE_INVOCATION_CONTRACTS"
                   for t in targets):
            continue
        value = node.value
        if (isinstance(value, ast.Call) and len(value.args) == 1
                and not value.keywords):
            value = value.args[0]
        try:
            contracts = ast.literal_eval(value)
        except (ValueError, SyntaxError, TypeError, MemoryError,
                RecursionError):
            return set()
        if not isinstance(contracts, dict):
            return set()
        return {str(k) for k in contracts if isinstance(k, str)}
    return set()


def measure(repo_root: Path,
            gates: Sequence[str],
            registry_path: Optional[Path] = None
            ) -> Tuple[List[str], List[str], List[str]]:
    """``(unbacked, backed, no_claim)`` over ``gates``, all sorted."""
    if registry_path is None:
        registry_path = (repo_root / "vibe-ic-marketplace" / "plugins"
                         / "vibe-ic" / "programs" / REGISTRY_MODULE)
    dispositions = read_dispositions(registry_path)
    blobs = driver_blobs(repo_root)
    contracts = read_invocation_contracts(registry_path)
    unbacked: List[str] = []
    backed: List[str] = []
    no_claim: List[str] = []
    for gate in sorted(gates):
        text = dispositions.get(gate, "")
        if not claims_a_home(text):
            no_claim.append(gate)
        elif gate in contracts or is_invoked(gate, blobs):
            backed.append(gate)
        else:
            unbacked.append(gate)
    return unbacked, backed, no_claim


def population(pinned: Sequence[str],
               dispositions: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """``(population, dispositions_outside_pin)``.

    The population is the UNION, not the pin. The pin answers "which gates
    cannot be invoked"; the registers answer "what did we say about a gate".
    Nothing keeps the two aligned, so a disposition written about a gate the pin
    does not list -- a stale claim left behind after the gate got wired, a
    register grown for an invocable gate -- would be examined by nobody. That is
    this file's own defect turned on itself: a register read as coverage.
    """
    outside = sorted(set(dispositions) - set(pinned))
    return sorted(set(pinned) | set(dispositions)), outside


def _pinned_gates(programs_dir: Path) -> List[str]:
    """`p0_gate_invocability_drift_check.KNOWN_NOT_INVOCABLE`, read not retyped.

    One of the two population sources; see `population`.
    """
    src = (programs_dir / "p0_gate_invocability_drift_check.py").read_text(
        errors="replace")
    for node in ast.parse(src).body:
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign)
                   else [])
        for target in targets:
            if (isinstance(target, ast.Name)
                    and target.id == "KNOWN_NOT_INVOCABLE"):
                return list(ast.literal_eval(node.value))
    raise LookupError("KNOWN_NOT_INVOCABLE not found")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Pin the P0 dispositions that name a home the tree does "
                     "not have."))
    parser.add_argument("--repo-root", default=".",
                        help="repository root (default: cwd)")
    parser.add_argument("--json", help="write the structured result here")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    programs_dir = (repo_root / "vibe-ic-marketplace" / "plugins"
                    / "vibe-ic" / "programs")
    registry = programs_dir / REGISTRY_MODULE
    if not registry.is_file():
        print(f"CANNOT MEASURE: {registry} not found", file=sys.stderr)
        return RC_CANNOT_MEASURE
    unreadable: List[str] = []
    try:
        pinned = _pinned_gates(programs_dir)
        dispositions = read_dispositions(registry, unreadable)
    except (OSError, LookupError, ValueError, SyntaxError) as exc:
        print(f"CANNOT MEASURE: {exc}", file=sys.stderr)
        return RC_CANNOT_MEASURE
    if unreadable:
        # NOT rc 1. A disposition this program could not read is not a
        # disposition it judged, and "I could not tell" must never leave here
        # wearing the exit code of "I checked and it is fine".
        print(f"CANNOT MEASURE: {len(unreadable)} disposition value(s) are not "
              f"literals this program can read "
              f"({', '.join(sorted(unreadable))}). Silently dropping them would "
              f"file the gate under 'wrote no disposition'. Write the "
              f"disposition as a plain string literal.", file=sys.stderr)
        return RC_CANNOT_MEASURE

    gates, outside_pin = population(pinned, dispositions)

    unbacked, backed, no_claim = measure(repo_root, gates, registry)
    recorded = set(KNOWN_UNBACKED)
    new = sorted(set(unbacked) - recorded)
    fixed = sorted(recorded - set(unbacked))

    # The residual, printed on EVERY run. A number only visible on failure is a
    # number nobody watches.
    print(f"P0 dispositions over {len(gates)} gates "
          f"({len(pinned)} pinned not-invocable, {len(dispositions)} with a "
          f"written disposition, {len(outside_pin)} of those outside the pin): "
          f"{len(unbacked)} claim a home nothing backs, "
          f"{len(backed)} claim a home that is real, "
          f"{len(no_claim)} make no claim")
    for gate in outside_pin:
        print(f"  outside-pin  {gate}")
    for gate in unbacked:
        print(f"  UNBACKED  {gate}")
    for gate in backed:
        print(f"  backed    {gate}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "program": "p0_disposition_backing_check",
            "summary": {
                "examined": len(gates),
                "pinned": len(pinned),
                "with_disposition": len(dispositions),
                "dispositions_outside_pin": len(outside_pin),
                "unbacked": len(unbacked),
                "backed": len(backed),
                "no_claim": len(no_claim),
                "pass": not new,
            },
            "population": gates,
            "dispositions_outside_pin": outside_pin,
            "unbacked": unbacked,
            "backed": backed,
            "no_claim": no_claim,
            "newly_unbacked": new,
            "recorded_but_no_longer_unbacked": fixed,
        }, indent=2) + "\n")

    if new:
        print(f"\nFAIL: {len(new)} disposition(s) newly claim a home nothing "
              f"in the tree backs: {', '.join(new)}", file=sys.stderr)
        print("Wire the gate, or reword the disposition to stop asserting a "
              "home it does not have.", file=sys.stderr)
        return RC_DRIFT
    if fixed:
        print(f"\nNOTE: {len(fixed)} recorded name(s) no longer unbacked "
              f"({', '.join(fixed)}) — delete them from KNOWN_UNBACKED.")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
