#!/usr/bin/env python3
# The module docstring is RAW: it quotes the declaration rule, which contains
# `[ \t]` and `\s`, and a non-raw docstring turns those into a DeprecationWarning
# about an invalid escape -- a warning emitted by the file that explains the rule.
r"""advisory_clause_states_its_reason.py — an advisory gate must say WHY it is
advisory.

ENFORCEMENT: blocking

The defect
----------
MEASURED on main at v1.13.78 (93235bdf3): 84 of the flow's 232 gate clauses
sit in the `advisory_program_exit_zero` slot. That slot RUNS the program and RECORDS the
verdict and can never stop the step, by construction. A third of the gate
population cannot block, and NOTHING in this tree asks a single one of those
clauses to justify it.

Advisory is frequently the right answer. `flow_gate_enforcement_audit` says so
in its own words: turning audit-only gates into blocking ones is a flow owner's
decision with real blast radius. THE DEFECT IS NOT THE SLOT. The defect is that
the slot is SILENT, so these two are byte-identical to every reader and every
program:

    a gate deliberately wired advisory because its finding is a disclosure
    a gate quietly moved to advisory this morning to make a red go away

`closed_loop_metric_reaches_its_producer` is the case that prompted this. It is
wired advisory only, it reports `21 declared edge(s); REACHABLE=0`, and it
blocks nothing, forever. Read its source and read its clause and there is no way
to tell which of the two sentences above it is.

AND THE REASON EXISTS. It is in 457185ead, the commit that wired the clause:

    ADVISORY, and not from caution: UNREACHABLE is a fact about the tree's
    CAPABILITIES, not a defect a change introduced. Every one of these edges
    was declared before this program existed, and refusing on them would
    redden every landing over debt no change owns.

That is a good reason, and it is deliberate policy rather than a downgrade —
which is what makes it the sharpest possible statement of the defect. THE
REASON IS NOT MISSING; IT IS UNREACHABLE. It sits in the one place that cannot
be read from the wiring site, that no program in this tree consults, and that
does not update when the wiring changes: a reader who rewires that clause
tomorrow will not find it, and a reader who wonders about it today has to know
to run `git log -S` over a 7000-line YAML file.

MEASURED over all 84, and this is the census this gate was written from.
84 clauses in 78 distinct programs — `stage_on_pass_review` is wired six times,
once per stage, since v1.13.63 moved the on-pass stages into `steps:`, and
`flow_compliance_check` twice, since v1.13.78 gave the review a verdict source
with an executed producer:

    declare `ENFORCEMENT: advisory` (says WHAT)              63
    declare no enforcement intent at all                     21
    state a REASON where the clause or the gate can show it  84
    state a reason in the COMMIT that wired the clause       28   (heuristic;
                                                                  see below)

A declaration of WHAT is fully satisfied by a gate somebody downgraded an hour
ago; only WHY distinguishes them, and until 2026-08-31 WHY was written 28 times
into a medium no reader of the clause will reach. THE REGISTER IS NOW EMPTY: all
82 clauses carry `advisory_reason:` and the recorded set tightened 77 -> 0. The
row above reads 84 for that reason and not because the rule was loosened.

WHAT THOSE 82 REASONS SAY, and why they are not invented prose. Each is a
MEASUREMENT, from a four-way classification of the whole population:

    NOT-YET-CLEAN  61   can refuse; advisory is a ratchet position. The reason
                        states the NOTCH — the rc that clause's own declared
                        command returned on a real completed run tree
                        (14 rc 1, 30 rc 0, 17 rc 2).

                        rc 1 IS NOT THE SAME FACT IN EVERY GATE, and reading it
                        as one produced the first wrong reason this register
                        carried. Measured over all 18 rc-1 clauses: exactly one,
                        `dfm_screen_check`, declares rc 1 as a NON-failure tier
                        (0 PASS / 1 PASS_WITH_ADVISORIES / 2 vacuous SKIP) and
                        its own docstring says the flow MUST wire it advisory.
                        Its reason called that a swallowed refusal and told a
                        future reader to promote it to blocking, which would
                        fail every run raising any advisory. Corrected, and the
                        clause moved to CENSUS where it belongs.
    DEMOTED        13   wired blocking (7) or in the refusing `optional` slot
                        (6) and moved here. The reason names the commit and
                        quotes its stated justification. `integration_spec_audit`
                        was demoted on the premise that it PASSED; it returns
                        files_passed 0 on a real run today.
    CANNOT-REFUSE   7   no input reaches a non-zero exit — proved by planting a
                        real violation and recording rc 0. 2 are `*_check`
                        programs with a defect predicate they cannot act on;
                        5 are producers/classifiers wired into a gate slot.
    CENSUS          3   measures a population and records it; correctly
                        advisory, permanently.

A reason invented to satisfy a checker informs nobody, which is why the register
comment refuses that. A reason that is a measurement is not invented, and every
one of these can be re-derived from the tree that produced it.

The 28 is a heuristic over commit prose — a message naming the wiring together
with a causal clause — and it was spot-checked in both directions rather than
published raw. It is a FLOOR on how much of this was decided deliberately, not
a count of gates that are fine.

What counts as a stated reason
------------------------------
TWO CHANNELS, checked in this order:

  1. THE CLAUSE.   `advisory_reason: "<why>"` beside `command:` in the flow
                   definition. Preferred: it is per-CLAUSE, so a program wired
                   advisory in one step and blocking in another can answer for
                   each independently. (No gate is wired in two slots today —
                   measured, `advisory ∩ blocking` and `advisory ∩ optional`
                   are both empty — but a per-gate-only rule would become wrong
                   silently on the day one is.)
  2. THE SOURCE.   `ADVISORY_REASON: <why>` in the gate program, read as a
                   DECLARATION by `flow_gate_enforcement_audit.declaration_re`
                   and inside its `DECL_WINDOW_BYTES` window.

CHANNEL 2 REUSES THAT READER RATHER THAN RESTATING IT. The prefix set, the
`[ \t]`-not-`\s` rule and the "a declaration OPENS its line" anchoring are one
rule; a rule re-typed at a second token is a rule with two values, which this
repo landed v1.13.46 and v1.13.39 to stop. `declaration_re` is a builder in
that file and this program passes it a different token. So the #886 property
comes along for free and is not re-derived: a docstring that MENTIONS
`ADVISORY_REASON:` mid-sentence while discussing the convention is not a
declaration, and this file's own paragraph above does not declare one.

The window comes along too, with its own lesson. A reason pushed past
`DECL_WINDOW_BYTES` by two paragraphs of prose above it is PRESENT AND UNREAD.
This gate reports that case as `UNREAD_PAST_WINDOW` and names the byte offset,
because "you did not write one" and "you wrote one where nothing reads it" are
different repairs and printing them the same way sends the author to the wrong
one.

A reason must be a REASON
-------------------------
The check is worthless if `ADVISORY_REASON: TBD` satisfies it. Rejected:

  * empty, or whitespace only;
  * a PLACEHOLDER — the exact set is `PLACEHOLDER_TOKENS`, and it is listed
    THERE and not restated here for the same reason the declaration shape is a
    builder rather than a second copy. Matched on WORD BOUNDARIES and only when
    the value is NOTHING BUT such tokens, so `<PLACEHOLDER>`, `[TBD].` and
    `TODO / FIXME` are all refused while a sentence containing one of the words
    is not. A value with no letters or digits in it at all (`?`, `-`) reaches
    the length floor below and is refused there. v1.13.59 landed today because placeholder
    detection matched SUBSTRINGS and reddened a correct document over the
    legal macro name `block_XXXa`. A rule that reddens correct input is a rule
    that gets switched off, so a reason that happens to CONTAIN one of these
    words in a sentence is accepted: `"the XXX corner has no model, so this
    can only report"` is a reason, and `"XXX"` is not;
  * a restatement of the wiring rather than a reason for it. "advisory",
    "advisory only", "non-blocking", "does not block", "informational",
    "see above", "as discussed" answer WHAT, which the slot already said;
  * shorter than `MIN_REASON_CHARS` raw characters, which is the floor this
    tree already applies to `absent_condition_reason`, or carrying fewer than
    `MIN_REASON_LETTERS` letters, so that padding cannot pay a length floor.

A FLOOR IS ON EFFORT. This gate cannot judge whether a reason is TRUE, does not
try, and says so in its own output — a pass here is evidence that somebody was
asked and answered, never that the answer was reviewed.

Why this gate is BLOCKING and not advisory
------------------------------------------
STATED, because a gate about undeclared enforcement intent that left its own
undeclared would be a joke, and because the brief that produced it named this
as the trap.

An advisory version of this check would be ITS OWN SUBJECT: an unjustified
advisory clause asserting that advisory clauses must be justified. It would
also be the 78th member of the population it measures, and it would prove
nothing about any of the 77 — a finding that cannot refuse is a finding that
depends on somebody reading the log.

The objection to BLOCKING is real and is the reason most checks in this class
end up advisory: 77 of 77 failed on day one, a gate that reddens everything gets
routed around, and v1.13.59's own words are "a false positive does not merely
cost a review; it costs the check". `gate_mutation_fixture_check` faced the
identical arithmetic (83 gates, 0 fixtures) and wrote down the answer this
repo uses:

    a SHRINK-ONLY register. The 77 are RECORDED. The gate exits 0 while
    printing the whole gap, and exits 1 on the 78th.

THE REGISTER IS NOW EMPTY (2026-08-31). All 84 clauses state a reason, the
recorded set tightened 77 -> 0, and `previous_size` is 77. So the paragraph
above describes how this gate SHIPPED, not how it stands: there is no longer a
standing dispensation, and the next silent advisory clause is rc 1 with nothing
to fall back on. That is the state a shrink-only register exists to reach.

So this gate BLOCKS ON EVERY FUTURE SILENT ADVISORY CLAUSE and DISCLOSES the
77 existing ones. `_ratchet_baseline.shrunk()` returns `previous & current`,
so no argument to the recording path can add a member; and a recorded entry
that no longer offends is a TIGHTENING, reported and recordable, never failed —
a ratchet that fails when it tightens makes "fix nothing" the cheapest way to
stay green.

THE REGISTER IS NOT A LIST OF ANSWERS. Its entries are findings awaiting their
author. This program's author did not write those 77 gates and did not invent
reasons for them: a reason invented to satisfy a checker satisfies the checker
and informs nobody, which is strictly worse than the silence it replaces. Each
entry is paid by the gate's OWN author stating why, or by rewiring it.

Where it runs
-------------
`tools/ci/repo_hygiene_gates.sh`, the blocking repo-hygiene tier, beside
`flow_gate_enforcement_audit` whose reader it borrows. Declared with `run`, not
`run_tolerating_uncheckable`: it reads two files from a tree handed to it by
absolute path and needs no network, no container and no run directory.

Exit codes
----------
    0  every advisory clause states a reason, or is a RECORDED entry of the
       shrink-only register. A tightening is reported here, never failed.
    1  a clause with no stated reason that the register does not record; or a
       recorded entry DELETED from the register rather than paid (it comes
       straight back as new, which is the point); or a reason that is a
       placeholder, empty, or a restatement of the wiring.
    2  THE QUESTION COULD NOT BE PUT: the flow definition is absent or does not
       parse with the flow engine's own loader; the programs directory is
       absent; the register file is absent, unreadable or states no measurement;
       or the flow parses and contains ZERO advisory clauses. The last one is
       deliberate — an empty population is NOT OBSERVED, not PASS, and a
       zero-denominator sweep reporting clean is the failure this repo already
       names in `gate_zero_denominator_refuses_check`.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402
import _ratchet_baseline as _ratchet  # noqa: E402
import flow_gate_enforcement_audit as _fgea  # noqa: E402

_HERE = Path(__file__).resolve().parent

#: The slot this gate is about. Checked against the audit's own slot list so
#: the two cannot drift into asking about different slots -- and checked with a
#: RAISE rather than an `assert`, which `python -O` deletes. A gate whose one
#: safety check is optional at runtime is a gate with no safety check.
ADVISORY_SLOT = "advisory_program_exit_zero"
if ADVISORY_SLOT not in _fgea._GATE_SLOTS:  # pragma: no cover - import guard
    raise RuntimeError(
        f"{ADVISORY_SLOT!r} is not one of the gate slots the flow engine "
        f"dispatches on ({_fgea._GATE_SLOTS}); this gate would examine nothing "
        f"and report it as clean.")

#: The clause key that carries a per-clause reason.
CLAUSE_KEY = "advisory_reason"

#: The source-declaration token. The SHAPE is `_fgea.declaration_re`'s; only
#: the token is ours. `(.*)` and not `(\S.*)`: an EMPTY value must be matched
#: and then REFUSED as empty, not silently read as "no declaration present".
#: Those are different findings and the author's repair differs.
REASON_TOKEN = "ADVISORY_REASON"
_REASON_RE = _fgea.declaration_re(REASON_TOKEN, r"(.*)$")

#: Read from the audit, never re-typed. Measured 2026-08-22 in that file: two
#: paragraphs of prose above a declaration moved it to byte 4371 and silently
#: undid it.
WINDOW = _fgea.DECL_WINDOW_BYTES

#: Placeholders, matched on WORD BOUNDARIES (v1.13.59) and only when EVERY
#: word of the value is one of them — see `_placeholder_of`. Exercised
#: exhaustively over THIS tuple by
#: `test_every_placeholder_token_is_actually_refused`, so a token added here
#: and never wired up cannot sit untested.
PLACEHOLDER_TOKENS = ("TODO", "TBD", "FIXME", "XXX", "N/A", "NA", "NONE",
                      "WIP", "PLACEHOLDER", "PENDING", "UNKNOWN")

#: Values that restate the WIRING instead of giving a reason for it. The slot
#: already says the gate is advisory; repeating it answers nothing.
_RESTATEMENT_RE = re.compile(
    r"^(?:it\s+is\s+|this\s+is\s+|because\s+)?"
    r"(?:advisory(?:\s+only)?|non[- ]?blocking|does\s+not\s+block|"
    r"informational|advises|records\s+only|reports\s+only|"
    r"see\s+above|see\s+below|as\s+discussed|as\s+stated|by\s+design)"
    r"[.\s]*$", re.IGNORECASE)

#: THE FLOOR IS THE REPO'S EXISTING ONE, not a new number. This tree already
#: requires a clause-level reason to be substantive:
#: `flow_condition_reachability_check.MIN_ABSENT_CONDITION_REASON` and
#: `flow_compliance_check._MIN_ABSENT_CONDITION_REASON` are both 40, held equal
#: to each other by a test because "two hand-kept numbers are two numbers that
#: drift". A THIRD, different floor for the neighbouring question "why is this
#: clause advisory" would be a third number to drift, so this one is 40 as
#: well and `test_the_reason_floor_is_the_repos_own` fails if that stops being
#: true -- which forces the decision to be RE-MADE rather than to drift.
#:
#: THE SECOND NUMBER IS NOT A DUPLICATE OF THE FIRST; it measures something the
#: first cannot see. The repo's floor is `len(why) < 40` on the RAW string, so
#: forty punctuation marks pay it in full. `MIN_REASON_LETTERS` is the floor on
#: LETTERS, which is what makes padding not a reason. It is deliberately the
#: lower of the two: it exists to catch a value that is not prose, not to
#: second-guess a terse author who cleared the repo's own bar.
#:
#: A floor is on EFFORT. Neither number is a claim that the reason is TRUE, and
#: this gate says so in its own output.
MIN_REASON_CHARS = 40
MIN_REASON_LETTERS = 24

#: Verdicts. `UNREAD_PAST_WINDOW` is separate from `NO_REASON` because the
#: repairs differ: move the declaration up, versus write one.
OK = "STATED"
NO_REASON = "NO_REASON"
UNREAD = "UNREAD_PAST_WINDOW"
EMPTY = "EMPTY"
PLACEHOLDER = "PLACEHOLDER"
RESTATEMENT = "RESTATES_THE_WIRING"
TOO_SHORT = "TOO_SHORT"
MISSING_SOURCE = "GATE_SOURCE_ABSENT"

_OFFENDING = (NO_REASON, UNREAD, EMPTY, PLACEHOLDER, RESTATEMENT, TOO_SHORT,
              MISSING_SOURCE)


class NotChecked(RuntimeError):
    """The question could not be put. Always rc 2, never a shorter finding
    list: a census over an unread population reads exactly like a clean one."""


def _strip_quotes(value: str) -> str:
    """The declaration's right-hand side without its own closing docstring
    quotes or trailing comment furniture.

    A one-line docstring declaration (`\"\"\"ADVISORY_REASON: x\"\"\"`) carries
    the closing quotes inside the captured value. They are punctuation of the
    container, not of the reason, and counting them toward `MIN_REASON_CHARS`
    would let three quote characters pay for a quarter of the floor.
    """
    v = value.strip()
    for q in ('"""', "'''", '"', "'"):
        if v.endswith(q):
            v = v[: -len(q)].rstrip()
            break
    return v.strip()


def _placeholder_of(value: str) -> Optional[str]:
    """The placeholder token this value IS, or None.

    WORD BOUNDARIES, and WHOLE-VALUE. v1.13.59: `PLACEHOLDER_TOKENS` matched as
    substrings reported the legal macro name `block_XXXa` as an unresolved
    placeholder in a document that had none, and the lesson recorded there is
    that a rule which reddens correct input is a rule that gets switched off.

    So the test is not "does this value contain TBD" — a sentence may — but
    "is this value nothing but placeholders and punctuation". Measured both
    ways in the tests: `XXX` is refused, and a reason whose text happens to
    contain `block_XXXa` or the words `the TODO list` is accepted.
    """
    # `/` survives the split so `N/A` stays ONE word; everything else that is
    # not alphanumeric is a separator, which is what makes `<PLACEHOLDER>`,
    # `[TBD]` and `TBD.` the same value as `TBD`.
    # A token must carry at least one alphanumeric to be a WORD; `/` survives
    # the split only so `N/A` stays one word, and a lone `/` (as in
    # `TODO / FIXME`) is punctuation. Counting it as a word made a value of
    # nothing but two placeholders read as "has a non-placeholder word", which
    # is the escape hatch this predicate exists to close.
    words = [w for w in re.sub(r"[^A-Za-z0-9/]+", " ", value).split()
             if re.search(r"[A-Za-z0-9]", w)]
    if not words:
        return None
    upper = {t.upper() for t in PLACEHOLDER_TOKENS}
    hits = [w for w in words if w.upper() in upper]
    # WHOLE-VALUE, not "contains". `block_XXXa` splits to `block`, `XXXa`, and
    # neither is a placeholder token; a sentence mentioning `the TODO list` has
    # non-placeholder words beside it. Only a value made of NOTHING but these
    # tokens is one.
    return hits[0].upper() if len(hits) == len(words) else None


def classify_reason(raw: Optional[str]) -> Tuple[str, str]:
    """(verdict, normalised value) for a reason value that WAS found."""
    if raw is None:
        return NO_REASON, ""
    value = _strip_quotes(raw)
    if not value:
        return EMPTY, ""
    ph = _placeholder_of(value)
    if ph:
        return PLACEHOLDER, value
    if _RESTATEMENT_RE.match(value):
        return RESTATEMENT, value
    if (len(value) < MIN_REASON_CHARS
            or len(re.sub(r"[^A-Za-z]", "", value)) < MIN_REASON_LETTERS):
        return TOO_SHORT, value
    return OK, value


def _source_reason(programs: Path, gate: str) -> Tuple[str, str]:
    """Read channel 2. Returns (verdict, value).

    `UNREAD_PAST_WINDOW` requires an otherwise-valid declaration BEYOND the
    window: a placeholder past the window is still a placeholder, and telling
    its author to move it up would be advice toward a value that would then be
    refused anyway.
    """
    stem = gate if gate.endswith(".py") else gate + ".py"
    path = programs / stem
    if not path.is_file():
        return MISSING_SOURCE, ""
    text = path.read_text(errors="replace")
    m = _REASON_RE.search(text[:WINDOW])
    if m:
        return classify_reason(m.group(1))
    beyond = _REASON_RE.search(text, WINDOW)
    if beyond:
        verdict, value = classify_reason(beyond.group(1))
        if verdict == OK:
            return UNREAD, f"at byte {beyond.start()} (window is {WINDOW})"
        return verdict, value
    return NO_REASON, ""


def census(flow: Path, programs: Path) -> List[dict]:
    """Every advisory clause with its reason verdict, in document order.

    Raises `NotChecked` rather than returning a short list for anything that
    means "could not look".
    """
    if not flow.is_file():
        raise NotChecked(f"flow definition not found: {flow}")
    if not programs.is_dir():
        raise NotChecked(f"programs directory not found: {programs}")
    try:
        clauses = _fgea.clauses_in_flow(flow)
    except _fgea.FlowGrammarError as exc:
        raise NotChecked(str(exc)) from exc
    rows: List[dict] = []
    for idx, c in enumerate(clauses):
        if c["slot"] != ADVISORY_SLOT:
            continue
        gate = c["gate"] or "<unparsed-command>"
        cmd = c["command"] if isinstance(c["command"], str) else ""
        raw = c["clause"].get(CLAUSE_KEY)
        if isinstance(raw, str):
            verdict, value = classify_reason(raw)
            channel = "clause"
        else:
            verdict, value = _source_reason(programs, gate)
            channel = "source"
        rows.append({"gate": gate, "verdict": verdict, "channel": channel,
                     "value": value, "command": cmd, "order": idx,
                     "section": c["section"]})
    if not rows:
        raise NotChecked(
            f"{flow} parsed and declares ZERO `{ADVISORY_SLOT}` clauses. An "
            f"empty population is NOT OBSERVED, not a clean census: a sweep "
            f"over nothing reports the same green as a sweep that found "
            f"nothing wrong.")
    return rows


def _key(row: dict) -> str:
    """The register key. The GATE name, not the command: a command carries
    flags that change for reasons unrelated to whether a reason was stated, and
    a debt entry that goes stale when an unrelated flag moves is a register
    that has to be rewritten to stay green.

    ONE GATE CAN CARRY SEVERAL CLAUSES, so the register is SHORTER than the
    population and that difference is disclosed rather than left for a reader
    to trip over. MEASURED at v1.13.66: 82 advisory clauses, 77 distinct gates
    — `stage_on_pass_review` is wired six times, once per stage, after v1.13.63
    moved the on-pass stages into `steps:`.

    A gate leaves the register only when EVERY clause that names it states a
    reason (`now` is built from the offending rows, so one silent clause keeps
    the whole entry), which is the safe direction. What a gate-keyed register
    cannot do is let SIX clauses be paid by ONE sentence when the six have
    different reasons — for that the author uses the per-clause channel, and
    the printed report names each clause separately so the choice is visible.
    """
    return row["gate"]


def _label(row: dict, duplicated: "set[str]") -> str:
    """How a clause is NAMED in the report.

    A gate wired once is named by its gate. A gate wired several times is named
    with the document position of the clause, because six identical lines
    reading `stage_on_pass_review NO_REASON` tell a reader there is a problem
    and not WHICH of the six to open. That is the whole argument this gate
    makes about counts, applied to its own output.
    """
    if row["gate"] not in duplicated:
        return row["gate"]
    return f"{row['gate']} [clause @ document position {row['order']}]"


def _load_register(path: Path) -> List[str]:
    if not path.is_file():
        raise NotChecked(
            f"register not found: {path}. An unrecorded register is not an "
            f"empty one — every finding would read as accepted debt. Create "
            f"it with --write-baseline.")
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        raise NotChecked(f"register {path} is unreadable: {exc}") from exc
    known = doc.get("known")
    if not isinstance(known, list):
        raise NotChecked(
            f"register {path} states no readable measurement: `known` is "
            f"{type(known).__name__}, not a list. An explicitly EMPTY list is "
            f"a measurement and is accepted; a missing one is not.")
    return sorted({str(k) for k in known})


_REGISTER_COMMENT = (
    "Advisory flow clauses that state NO reason for being advisory "
    "(vibe-ic: advisory_clause_states_its_reason). MAY ONLY SHRINK. An entry "
    "is a FINDING AWAITING ITS AUTHOR, not a dispensation and not an answer. "
    "It is paid by that gate's own author stating why — `ADVISORY_REASON:` in "
    "the gate source inside the declaration window, or `advisory_reason:` on "
    "the clause — or by rewiring the clause out of the advisory slot. It is "
    "NOT paid by deleting the line: this gate recomputes the set every run, so "
    "a deleted entry returns as NEW and fails. A reason invented by someone "
    "other than the gate's author to clear an entry satisfies this checker and "
    "informs nobody, which is worse than the silence it replaces."
)


def _report(rows: List[dict], recorded: List[str], out=sys.stdout) -> Tuple[int, dict]:
    prev = set(recorded)
    offending = [r for r in rows if r["verdict"] in _OFFENDING]
    now = sorted({_key(r) for r in offending})
    new = [k for k in now if k not in prev]
    paid = _ratchet.departed(recorded, now)
    by_verdict: Dict[str, int] = {}
    for r in rows:
        by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1

    seen: Dict[str, int] = {}
    for r in rows:
        seen[r["gate"]] = seen.get(r["gate"], 0) + 1
    duplicated = {g for g, n in seen.items() if n > 1}

    print(f"advisory clauses examined: {len(rows)} "
          f"(in {len(seen)} distinct gate program(s))", file=out)
    if duplicated:
        print("  one program, several clauses — the register keys on the "
              "PROGRAM, so it is shorter than the population and an entry is "
              "paid only when EVERY one of its clauses states a reason:",
              file=out)
        for g in sorted(duplicated):
            print(f"    {g}  x{seen[g]}", file=out)
    for v in sorted(by_verdict):
        print(f"  {v:<22} {by_verdict[v]}", file=out)
    print(f"stating a reason: {by_verdict.get(OK, 0)} of {len(rows)}", file=out)

    if paid:
        print("", file=out)
        print(_ratchet.report_line("known", paid, len(prev), len(prev) - len(paid)),
              file=out)
        for k in paid:
            print(f"   (resolved) {k}", file=out)
        print(f"   Record it with:  advisory_clause_states_its_reason.py "
              f"{_ratchet.RECORD_FLAG}", file=out)

    if new:
        print("", file=out)
        print(f"[FAIL] {len(new)} advisory clause(s) state no reason and are "
              f"NOT recorded debt. An advisory gate that does not say why is "
              f"indistinguishable from one somebody downgraded to make a red "
              f"go away:", file=out)
        for r in offending:
            if _key(r) in prev:
                continue
            print(f"   {_label(r, duplicated)}  {r['verdict']}  "
                  f"(channel={r['channel']})"
                  + (f"  value={r['value']!r}" if r["value"] else ""), file=out)
        print(f"   State it as `{REASON_TOKEN}: <why>` opening a line in the "
              f"gate's first {WINDOW} bytes, or as `{CLAUSE_KEY}: \"<why>\"` "
              f"on the clause. This gate checks that a reason was GIVEN; it "
              f"cannot and does not check that it is true.", file=out)
        rc = 1
    else:
        rc = 0
        print("", file=out)
        print(f"[PASS] no NEW silent advisory clause "
              f"({len(now)} recorded as debt, {len(prev)} in the register)",
              file=out)
        if now:
            # EVERY ENTRY IS NAMED, not summarised to a count. The neighbouring
            # audit prints "115 gate(s) recorded as UNDECLARED" and that is the
            # right shape for its register; it is the wrong shape for THIS one.
            # The thesis of this gate is that a number cannot distinguish a
            # deliberate advisory from a quiet downgrade, so printing a number
            # here would reproduce the defect inside the disclosure meant to
            # expose it. The list is long on purpose: 77 named lines is what
            # the debt actually looks like.
            print(f"  DISCLOSURE — {len(offending)} advisory clause(s), in "
                  f"{len(now)} program(s), block nothing and say nothing about "
                  f"why. In flow document order. Recorded, not accepted:",
                  file=out)
            for r in offending:
                print(f"    {_label(r, duplicated)}  {r['verdict']}", file=out)
    return rc, {"examined": len(rows), "by_verdict": by_verdict,
                "offending": now, "new": new, "paid": paid,
                "rows": rows}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?",
                    help="repo root whose flow + programs are the SUBJECT "
                         "(default: this program's own installation)")
    ap.add_argument("--flow", help="flow definition YAML (overrides root)")
    ap.add_argument("--programs", help="programs dir (overrides root)")
    ap.add_argument("--baseline", help="shrink-only register")
    ap.add_argument("--json", help="write the report here")
    ap.add_argument("--write-baseline", action="store_true",
                    help="CREATE the register from this run. Refused once the "
                         "register exists: use " + _ratchet.RECORD_FLAG)
    ap.add_argument(_ratchet.RECORD_FLAG, dest="record_shrink",
                    action="store_true",
                    help="record a measured TIGHTENING (previous & current); "
                         "cannot add an entry")
    a = ap.parse_args(argv)

    if a.root:
        root = Path(a.root).resolve()
        plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        if not plugin.is_dir():
            plugin = root
    else:
        plugin = _HERE.parent
    flow = Path(a.flow) if a.flow else plugin / "flow" / "phase1_phase2_phase3.yaml"
    programs = Path(a.programs) if a.programs else plugin / "programs"
    bl_path = Path(a.baseline) if a.baseline else programs / "advisory_reason_baseline.json"

    try:
        rows = census(flow, programs)
    except NotChecked as exc:
        print(f"[NOT CHECKED] {exc}", file=sys.stderr)
        return 2

    now = sorted({_key(r) for r in rows if r["verdict"] in _OFFENDING})

    if a.write_baseline:
        if bl_path.is_file():
            print(f"[FAIL] {bl_path} already exists. --write-baseline records "
                  f"whatever this run measured, arrivals included, so on an "
                  f"existing register it is an amnesty and not a recording. "
                  f"Use {_ratchet.RECORD_FLAG} for a measured tightening.",
                  file=sys.stderr)
            return 1
        bl_path.write_text(json.dumps(
            {"_comment": _REGISTER_COMMENT, "previous_size": None,
             "known": now}, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {bl_path} ({len(now)} recorded)")
        return 0

    try:
        recorded = _load_register(bl_path)
    except NotChecked as exc:
        print(f"[NOT CHECKED] {exc}", file=sys.stderr)
        return 2

    if a.record_shrink:
        keep = _ratchet.shrunk(recorded, now)
        try:
            _ratchet.write_shrunk(
                bl_path,
                {"_comment": _REGISTER_COMMENT,
                 "previous_size": len(recorded), "known": keep},
                previous_by_register={"known": recorded},
                ensure_ascii=False)
        except _ratchet.ShrinkRefused as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 1
        print(f"recorded tightening: {len(recorded)} -> {len(keep)}")
        return 0

    rc, report = _report(rows, recorded)
    if a.json:
        # vibe-ic#1082: the declared report destination appears under its final
        # name only once it is complete, so a reader that finds the file finds
        # a whole document or nothing -- never a truncated one that
        # `required_outputs` would credit as produced.
        _aa.write_json(a.json, report, indent=2, ensure_ascii=False)
    return rc


if __name__ == "__main__":
    sys.exit(main())
