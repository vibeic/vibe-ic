#!/usr/bin/env python3
"""emitter_population_pin_check.py — an emitter that PRINTS a population and a
test that PINS it are two statements of one fact, and they must move together.

THIS GATE BLOCKS (rc=1).

THE DEFECT, MEASURED 2026-08-21
===============================
A lane added a THIRD repair to a post-route block. It correctly moved the
emitter's own printed denominator from two to three:

    puts "SPEF_REPAIR_PARTIAL: $_prr_refused of 3 repairs refused"
    if {$_prr_refused >= 3} { ... }
    ... "($_prr_refused/3)" ...

and left the test asserting the OLD ratio. The population moved and the pin did
not, so the test failed for the right reason with the wrong message — a reader
meeting `2 != 3` learns nothing about the third repair.

It is the same shape as a stale census tripwire, and the remedy is the same one
this repository already applies there: a member arriving must force a human to
SAY THE NUMBER OUT LOUD.

TWO CHECKS, BECAUSE THE FACT IS STATED IN TWO PLACES
=====================================================
CHECK A — THE EMITTER AGAINST ITSELF. An emitted script that increments a
counter at K sites and then states a LITERAL denominator for that counter is
making two statements of one population. K is observable and so is the literal,
so they are compared. This is the half that catches the lane on the way in: add
a fourth repair, and `of 3` is wrong before any test runs.

    denominators recognised:  $X >= D    $X == D    $X/D    $X of D
    D < 2 is ignored: `$X > 0` is "any at all", not a population.

CHECK B — THE TEST AGAINST THE EMITTER. A test that names exactly one program
and quotes a population phrase (`... of N <tail>`) whose `<tail>` the emitter
also states must quote one of the emitter's OWN values for that tail. A pin
naming a number the emitter cannot produce is stale by construction.

WHAT IS READ: THE EMITTED SCRIPT, NOT THE FILE THAT PRINTS IT
=============================================================
Both checks read only the strings a program EMITS — never its docstrings, and
never its `#` comments, which do not reach the AST at all. Measured on this tree
before that exclusion existed for the phrase half: 3 findings, ALL THREE false,
and all three the same shape — a narrative sentence in a module or test docstring
("PR #862 is the subtler half. Its author reported \"4 of 4 behavioural\"")
matched against a different narrative sentence elsewhere. Prose recounting what
a number USED TO BE is not a pin, and a guard that reddens on the history a file
records would make recording history expensive. After the exclusion: 0 findings
over the same corpus.

CHECK A read the RAW FILE and so had none of that protection, which was a defect
and is fixed here: a docstring saying a repair is REMOVED and that there is no
`incr _n` left for it contributed a phantom MEMBER, and a sentence recounting a
retired `$_n >= 3` threshold contributed a phantom DENOMINATOR — so a truthful
emitter was refused for disagreeing with a number nobody had stated.

AND THE SCRIPT ITSELF IS ASKED FOR ITS POLARITY (vibe-ic#712)
=============================================================
Removing prose about the code does not remove prose: an emitted script carries
Tcl comments and `puts` messages, and English there denies as readily as it
declares — `# the retry path does not incr _n`, `# $_n >= 4 is no longer the
threshold`. A reader that matches the first and not the `not` in it counts a
DENIAL as a member. So every increment site and every literal denominator is
asked, through the ONE vocabulary in `_prose_polarity`, whether the statement it
sits in denies it; what that refuses is PRINTED, never quietly dropped.

`phrases_of` is not asked the same question, and the difference is structural, not
an oversight: it reads `of <N> <tail>`, a statement of how big a set IS. A
message that denies something else in the same breath ("no repair applied, 0 of 3
repairs refused") still states that population correctly, and suppressing the pin
comparison there would disarm CHECK B — the half that catches the measured defect
— in the silent direction.

WHAT WAS TRIED AND REJECTED — matching every `assert "<literal>" in <text>` in a
test against the verbatim source of the program it names. Measured over 1619
single-program test files: 6062 pins examined, 2345 "unsatisfied". Almost none
were defects. Emitters TEMPLATE their output (`f"{n} of {m} failures"`), so the
finished string a test asserts on is not, and must not be, a literal anywhere in
the emitter. A predicate that fires on 2345 legitimate pins is not a guard.

Narrowing to POPULATION phrases with a HARD-CODED denominator is what makes the
question answerable: those are the only ones where the emitter states the number
itself, and therefore the only ones where a test can disagree with it.

WHAT K IS: A COUNT, OR A LOWER BOUND
====================================
K is the number of `incr` sites written IN THE SOURCE. An emitter that builds
each repair through a HELPER is honest and states a real population, and this
guard used to refuse it: "incremented at 1 site(s) but its comparison
denominator says 3". That was recorded as a limitation and left alone.

IT IS NO LONGER LEFT ALONE, because the reason recorded for leaving it was
wrong. `multiplied_counters` decides, PER COUNTER, whether K is a count or a
lower bound: the `incr X` literal lives inside a function body, and that
function is called more than once. Where it is a lower bound:

    sites > denominator   STILL REFUSED -- a lower bound that exceeds the
                          stated population cannot be explained by emitting
                          more, so the disagreement is real
    sites < denominator   NOT DECIDABLE -- the shortfall is exactly what a
                          helper called N times produces. Printed, counted in
                          the head, carried in the JSON as `not_determined`,
                          never silently skipped

THE LANE DEFECT IS STILL CAUGHT. "Add a fourth repair and `of 3` is wrong before
any test runs" is `sites > denominator`, which stays decidable.

THE REACH IS PRINTED, ALWAYS
============================
This guard's population is small, and a verdict that does not say so would
overstate itself. Every run prints the counters and the pins it examined. A PASS
over zero of both is reported as VACUOUS, never as a pass.

EXIT CODES
==========
    0  every population this guard COMPARED agrees with its own site count, and
       every test pin it compared names a value its emitter states.

       NOT "every population agrees". Some may have been WITHHELD -- declined
       because K is only a lower bound, or not counted because the statement
       DENIES them, or in a source that would not parse. The head line states
       how many of each, always, and a reader taking rc=0 to mean the whole tree
       was checked is reading more than this exit code carries.
    1  REFUSED — the emitter line, the test line and the two values are printed
    2  VACUOUS — nothing was compared, and the run says WHICH of four, because
       each is a different claim and only one of them is about the tree:
         `corpus-holds-no-program`   the directory holds no program at all, so
                                     nothing here is a statement about any tree
         `declined-every-comparison` every population that exists was withheld
                                     above -- the one worth coming back to
         `source-bytes-substituted`  the sources were read through byte
                                     substitution, so a population may not have
                                     survived to be seen
         `no-population-stated-twice` the tree was read and states none
       Announced through `_vacuous_exit`. Pinned against the code by
       `test_the_documented_vacuous_reasons_are_the_ones_emitted` -- this list
       said TWO for three commits after the third and fourth were added.
    3  the command line was rejected (`_gate_usage_exit`)

HOW CI RUNS IT, WHICH IS WHY 2 IS NOT 0
=======================================
`tools/ci/repo_hygiene_gates.sh` wires it as `run "a printed population agrees
with its pin"`, and `run` is `_dispatch 0 0`: rc 2 FAILS the suite. It is not
`run_tolerating_uncheckable`, which exists for probes that need a clean tree and
treats rc 2 as "could not check". So "this is NOT a pass" is enforced by the
wiring and not merely asserted in the text above -- change one and the other
stops meaning what it says.

USAGE
-----
    emitter_population_pin_check.py [--programs DIR] [--tests DIR] [--json OUT]
    --json -   puts the report document on stdout and the human report on
               stderr, the spelling 34 programs in this corpus share

THE REACH, AND WHY IT IS FOUR
============================
On the tree this ships in, the verdict reads `3 emitted counter denominator(s)
and 1 test pin(s) COMPARED out of a corpus of 1238 program(s) and 2727 test(s)
SCANNED`, and three-out-of-1238 invites the conclusion that the extractor is
blind to almost everything. It is not. Measured on 8efee1b4ce:

    programs whose EMITTED script contains `incr `   : 4
      yielding a counter with a literal denominator  : 1   (3 denominators)
      with no numeric comparison on that counter     : 3

THE PIN SIDE, AND THE TWENTY-FOUR IT DOES NOT REACH
===================================================
`pins_unmatched` counts pins dropped because the named program states no literal
for that phrase. It does NOT count pins in a test whose named program emits no
matchable phrase at all: `if not em: continue` fires first, before `pins_of` is
ever called. Sized on cd8687da8b, so the limit is a number rather than an
admission:

    test files                                         : 2727
      naming no program in this corpus                 : 1104
      naming a program that emits no matchable phrase  : 1396
        of those, carrying a pin nobody looked at      :   18   (24 pins)

Each of those 24 is correctly undecidable -- a program that states no `of N ...`
anywhere offers nothing for a pin to disagree with -- and the reach sentence
already in the verdict describes them exactly. Reaching them means calling
`pins_of` on every parsed test instead of on the 227 that clear `em`: 3.58s on
top of 9.47s, +38%. The previous commit refused a +42% walk to carry one
disclosure number, and this is the same trade at the same price, so it gets the
same answer. Reproduce either figure by walking `tests/` with `pins_of`.

BOTH ARE MEDIANS OF FIVE, and that is not pedantry. Both figures were first
taken from a SINGLE run, and both are the whole reason work was refused rather
than done -- a decision resting on one timing rests on whatever else the machine
was doing that second. Re-measured at this tip: the program 9.36-9.58s and
222 MB peak RSS across five runs, the `pins_of` sweep 3.57-3.61s, the
`emitted_script_of` walk 3.98-4.06s. They held, and the walk was understated:
41% was really 42%. Elsewhere on this branch a single timing did NOT hold -- one
19.4s reading of the census gate against three of 10.9-11.3s at the same load --
so the habit is worth the seconds it costs.

DEGENERATE TAILS. `PHRASE` takes `of <digits> <words>`, and 9 of the corpus's
81 emitter tails are junk that prose produced: `and`, `or`, `L`, `V`, `Gb`,
`MHz`, `APs`, `Cat`. A pin matching one of those would produce a comparison,
and a comparison against junk can produce a WRONG red -- the worst outcome
this file has. Measured: no test in the corpus pins any of the nine, so the
risk is theoretical rather than live. Tightening `PHRASE` on no evidence of
harm would narrow the extractor to fix a fault nobody has, which is the trade
this file argues against everywhere else, so it is recorded and not acted on.

(81, not the 82 an earlier revision of this paragraph recorded. The missing
one is `links dangling`, and it is the comment rule working on the shipped
tree rather than on a fixture: `benchmark_evidence_publish.py` emits

    # directory was later renamed: 83 of 83 links dangling. Measured on the

and that sentence is a HISTORY, not a claim the script makes. Before
`_in_an_emitted_comment`, 83 was a value that emitter "states", so a test
pinning the retired 83 would have matched it and raised nothing. One phantom
claim, in a corpus of 1238 programs, and it was live.)


The other three state a membership and never state a threshold, so there is no
second statement for the first to disagree with -- nothing was skipped. The
phenomenon is RARE; the reach is not narrow. That is checkable rather than
asserted: `test_no_counter_with_a_threshold_is_silently_missed` walks every
program on every run and holds the RELATIONSHIP -- a counter with both a
membership and a literal threshold must yield a comparison -- rather than the
number 4, which goes stale the day a lane adds an emitter, and a stale reach
claim is how this kind of file starts lying.


--json, AND WHAT IT CARRIES
---------------------------
A machine-readable report with no written schema is a contract nobody can rely
on, and this one grew three keys without gaining one. All seven, so a consumer
need not read the source:

    tool                 this program's name
    counters_examined    emitted denominators actually COMPARED -- not "seen".
                         A comparison this guard declined is not counted here
    pins_examined        test pins actually compared, same rule
    findings             the refusals. `check` is "emitter-self" (a counter's
                         site count against its own printed denominator) or
                         "pin-against-emitter" (a test pinning a value the
                         emitter does not state). Non-empty <=> exit 1
    denied_by_polarity   matches NOT counted because the statement denies them.
                         `where` / `what` / `matched` / `denial`
    not_determined       populations declined because K is a LOWER BOUND, not a
                         count. `program` / `counter` / `increment_sites` /
                         `denominator` / `denominator_kind` / `emitted_per_site`
    corpus               what was SCANNED: {"programs": P, "tests": T}. Not a
                         count of what could be compared -- see THE REACH.
                         A count of comparisons made carries no meaning without
                         it -- "0 compared" out of 214 programs and out of an
                         empty directory are the same number and not the same
                         fact. vibe-ic#1200.
    pins_unmatched       pins found in a test whose named program states no
                         literal for that phrase -- typically because the
                         program computes the value. Nothing to compare, so not
                         a finding; counted because the alternative is dropping
                         it in silence. It counts pins from tests that named a
                         program which emits SOMETHING; the limit is SIZED under
                         THE REACH, not merely admitted.
    substituted          sources whose BYTES would not decode as UTF-8. Read with
                         substitution, so the text analysed is not the file; what
                         substitution mangles goes unmatched, and an unmatched
                         population is silently narrower reach. Reported, not
                         absorbed. REACH, not verdict.
    unparsed             sources nothing was examined in, either shape:
                         "<name>:<line>: <msg>" for one that would not parse,
                         "<path>: <reason>" for one that would not OPEN --
                         `rglob` yields broken symlinks, directories named
                         `*.py`, and files the runner may not read

The last three are REACH, not verdict: they say what was withheld. A consumer
that reads `findings` alone and ignores them is reading exit 0 as "the tree is
clean" when it may mean "what I could compare was clean".

WHY `[NOT DECIDABLE]` AND NOT THIS REPO'S `[CANNOT DETERMINE]`
--------------------------------------------------------------
Because they are different tiers, and borrowing the established word would make
this output lie. `[CANNOT DETERMINE]` is a VERDICT-level marker here -- 34 uses
across the corpus, every one of them accompanying rc 2, "nothing was audited,
which is not a clean pass"; `prose_polarity_consulted_check` itself prints it
that way. `[NOT DECIDABLE]` is PER ITEM: one population was declined while the
run carries on and may still exit 0.

Printing the verdict-level word beside a rc=0 run would tell a reader the whole
check was inconclusive when one line of it was. The item-level markers this
program prints -- `[POPULATION]` (the original), `[POLARITY]`, `[UNPARSED]`,
`[NOT DECIDABLE]` -- name the THING at issue and leave the verdict to the last
line. Recorded because "make the vocabulary consistent" is a reasonable-looking
change that would break this.

chip-AGNOSTIC: Python and Tcl text structure. No design, PDK, vendor or SKU.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import _atomic_artefact as _atomic
import _gate_usage_exit as _usage
import _vacuous_exit as _vac
from _prose_polarity import is_denied, sentence_scope

TOOL = "emitter_population_pin_check"

#: A population phrase in emitted prose: "<n> of <D> <tail>". The tail is one or
#: two identifier-ish words, which is what makes two statements of the SAME
#: population recognisable as such without a hand-written pairing list.
PHRASE = re.compile(
    r"\bof\s+(\d{1,5})\s+"
    r"([A-Za-z_][A-Za-z_()\[\]/-]*(?:\s+[A-Za-z_][A-Za-z_()\[\]/-]*)?)")

#: A Tcl counter increment. The emitted scripts in this tree are Tcl; the shape
#: is `incr <name>` and every site is one member of the population.
INCR = re.compile(r"\bincr\s+([A-Za-z_][A-Za-z0-9_]*)\b")

#: Denominators a counter may carry. `>` is absent on purpose: `$X > 0` is a
#: presence test, and `$X > 3` would mean "more than all of them".
_DEN_TEMPLATES = (
    ("comparison", r"\$%s\s*(?:>=|==)\s*(\d+)"),
    ("ratio", r"\$%s\s*/\s*(\d+)"),
    ("prose", r"\$%s\s+of\s+(\d+)"),
)

#: Below this a literal is a presence test, not a population.
def read_source(path: Path) -> Tuple[str, int]:
    """The source, and how many bytes had to be SUBSTITUTED to obtain it.

    `errors="replace"` is the right reader for a guard -- it never raises, so
    one bad file cannot take the census down. But it means the text analysed
    is NOT the file: undecodable bytes become U+FFFD, and a phrase, counter
    name or denial word that substitution lands in stops matching. The
    population it belonged to is then never compared, and nothing says so --
    a run that read a mangled file reports the same full reach as one that
    read a clean tree.

    That is the silent narrowing this program exists to refuse, so the
    substitution is measured here and printed with the rest of the reach.
    Detected by a STRICT decode rather than by counting U+FFFD in the result,
    because a file may legitimately contain that character and a guard that
    cannot tell the two apart invents reach caveats for clean sources."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8"), 0
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        return text, text.count("\ufffd")


MIN_POPULATION = 2

#: What ends a RECORD in the text `counters` reads. The subject is an emitted
#: SCRIPT, and a script is line-structured: a command and the line above it are
#: unrelated records, and a `#` comment ends at its own newline. `_prose_polarity`
#: owns the reach and takes this declaration, rather than this file growing a
#: private copy of "where does a statement end" -- which is the divergence that
#: module exists to end.
#:
#: WHICH WAY TO ERR, DECIDED BY WHICH FAILURE IS SILENT. Without a record break
#: the reach runs 240 characters through unrelated commands, so one
#: `puts "no repair applied"` retracts every denominator printed near it and this
#: BLOCKING gate quietly stops comparing anything. With it, a denial wrapped
#: across two emitted lines is missed and a phantom member is counted -- which is
#: a REFUSAL a reader sees, and answers. Loud beats silent, so the break is
#: declared. What polarity does refuse is printed on every run for the same
#: reason.
_RECORD_BREAKS = ("\n",)


def _emitted_nodes(tree: ast.Module) -> List[ast.Constant]:
    """The `ast.Constant` behind every emitted string.

    THE ONE PLACE that decides what counts as emitted. `emitted_script_of` wants
    the text, `pins_of` wants the node so it can ask what the surrounding code
    does with it, and a second copy of this rule is how the two would come to
    disagree about which strings are prose about the code.

    PROSE ABOUT THE CODE IS NOT THE SCRIPT, AND THIS IS WHERE THAT IS DECIDED.
    A string that is an expression STATEMENT is never emitted: it is the module,
    class or function docstring, or a block comment written as a string. A `#`
    comment never reaches the AST at all, so it is gone by construction. Both
    are prose recounting what the code does, or what a number USED TO BE, and
    neither is a statement of the population the emitted script carries.

    An f-string docstring's PARTS are skipped with it. `ast.walk` reaches each
    inner `Constant` on its own, so skipping the `JoinedStr` node alone would
    let the same prose back in through the other door.
    """
    skip: Set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Expr) and isinstance(n.value,
                                                  (ast.Constant, ast.JoinedStr)):
            for part in ast.walk(n.value):
                skip.add(id(part))
    #: UNORDERED. Only `emitted_script_of` needs source order -- a script read
    #: out of order is not the script -- and it sorts for itself. `phrases_of`
    #: and `pins_of` key by tail and by node, so sorting for them answered a
    #: question neither asks.
    #:
    #: COUNTED, because the sentence here first said "a sort per file across
    #: every test in the tree" and that was wrong twice over. On the shipped
    #: tree this runs 1047 times against 2727 test files, and the majority are
    #: not tests at all: 814 come from `phrases_of` (once per named PROGRAM,
    #: cached) and 227 from `pins_of`, which main reaches only for a test whose
    #: named emitter actually states a phrase. The saving is real and small,
    #: like the laziness in `pins_of`; the reason to do it is that the callers
    #: do not need the order.
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in skip]


def emitted_script_of(tree: ast.AST) -> str:
    """The emitted strings of a parsed module as ONE flat text, one record
    per line.

    STILL FLAT, for the reason `counters_of` still gives: the emitted script is
    assembled from many adjacent string literals, and a block-aware reader would
    have to re-implement that assembly to answer a question the flat text already
    answers. What changed is WHICH text -- the script, not the file that prints
    it.

    JOINED WITH A NEWLINE rather than concatenated, so two literals that are not
    adjacent in the real script (anything assembled through a call between them)
    cannot fuse into one statement and lend each other a polarity. Nothing that
    was matchable stops being matchable: in the raw file those same two literals
    were already separated by a quote, a newline and the next line's indentation,
    so no pattern here could span the seam then either.
    """

    return "\n".join(v for _, _, v in sorted(
        (n.lineno, n.col_offset, n.value) for n in _emitted_nodes(tree)))


def _in_an_emitted_comment(script: str, at: int) -> bool:
    """True when the EMITTED line holding `at` is a Tcl comment.

    Not a polarity question, which is why it is answered here rather than by
    `_prose_polarity`: this set claims to hold every phrase the emitter CAN
    PRINT, and a comment is not printed. Reading one as printable is wrong on
    the set's own terms, whatever the comment says.

    It matters because the failure is a FALSE PASS, the silent direction. An
    emitted script carrying

        # the summary no longer prints "of 3 repairs refused"
        puts "PARTIAL: $_n of 2 repairs refused"

    offered BOTH 3 and 2 as values the emitter states, so a test still pinning
    the retired 3 was found in that set and raised nothing -- a denial counted
    as a confirmation, #712's own shape, in a function the #712 gate does not
    audit (`_writes_a_declared_value` is False here, for reasons of spelling
    recorded in `phrases_of`).

    A LINE, not a scope: only the text before the match on its own line is
    examined, so `puts "# of 3 things"` -- a printed line that happens to carry
    a hash -- is kept. Dropping that would be the false refusal `phrases_of`
    exists to avoid, and this fix must not buy one direction with the other."""
    start = script.rfind("\n", 0, at) + 1
    return script[start:at].lstrip().startswith("#")


def phrases_of(tree: ast.AST) -> Dict[str, Set[Tuple[str, int]]]:
    """``{tail: {(value, lineno)}}`` -- every population phrase the emitter CAN
    print.

    NOT ASKED FOR POLARITY, and the asymmetry with `pins_of` below is measured, not
    stylistic. This set is the answer to "what values does this emitter state?",
    and a value missing from it makes a CORRECT pin look stale. An emitter that
    prints `puts "no repair applied; 0 of 3 repairs refused"` does state
    `of 3 repairs refused`; suppressing it because the same message also says
    "no" would refuse a correct test -- the same false refusal `pins_of` exists to
    stop, pointed the other way.

    AND THE POLARITY GATE CLEARS THIS FUNCTION FOR A MECHANICAL REASON, NOT FOR
    THAT ARGUMENT. Recorded here because the two are easily confused and the
    argument is the load-bearing one. `prose_polarity_consulted_check` asks
    `_searches_prose and _writes_a_declared_value`; the second half returns
    False here for two reasons that are both about SPELLING:

      * `m` is bound by a `for` TARGET, and `_match_derived_names` walks only
        `ast.Assign`, so the match never enters `derived` and the predicate
        returns False before it looks at any write at all; and
      * the write is `out.setdefault(KEY, set()).add(VALUE)`, and the predicate
        reads `setdefault`'s DEFAULT (`args[1:]`) but neither its key nor the
        value pushed into the container it returns.

    MEASURED over this tree, by widening each in turn: the first alone reveals
    35 further polarity-blind extractors, the second alone 35, and both together
    80 (224 -> 304 findings). Only with BOTH closed does the scan reach this
    function. So the clearance is an artefact of how the write is spelled, and
    a reader must not take it as the gate having agreed with the paragraph
    above.

    AND THAT PREDICATE CANNOT SIMPLY BE WIDENED, which is the part that turns
    this from a to-do into a design constraint. MEASURED by doing it: closing
    just the `for`-target half in the gate's own source takes the census
    213 -> 253 and the gate to rc=1, and the route its FAIL message names then
    refuses --

        [FAIL] refusing to write a baseline that GREW (213 -> 253). It is a
               debt register, not a waiver list.

    -- because the baseline MAY ONLY SHRINK. That rule is right, and it is why
    the gate is sealed against its own improvement: a sharper predicate makes 40
    pre-existing extractors visible at once, and they are exactly the category
    the baseline exists for ("extractors that predate the vocabulary are
    recorded, not failed"), yet the register cannot take them. The only honest
    routes are to fix all 40 first, or to change the gate's own rule -- both
    decisions well above a fix to this file.

    AND THE DECIDING REASON IS NOT DEFERENCE, IT IS THE CONSEQUENCE. Sharpening
    the predicate HERE would take `prose_polarity_consulted_check` to rc=1 on
    the whole tree -- the exact gate this branch exists to turn green, on the
    exact batch it exists to unblock. A branch that fixes one polarity-blind
    extractor and blocks the batch on forty is not a fix; it is the original
    finding multiplied. The sharpening has to travel on its own, with its own
    forty repairs, and not ride in beside this.

    (That 40 is larger than the 35 an earlier wrapper-based measurement gave:
    edited into the source, `for`-target names also propagate through the
    transitive loop that follows, so they carry one hop further. The wrapper
    measured a weaker widening than the real one. Re-derived at this branch's
    tip the figures are 41 / 37 / 88 -- a little higher because this file itself
    grew; the numbers move with the tree and are re-derived, never re-read.)

    AND THIS DEFERRAL WAS RE-OPENED, not merely restated. The sibling limitation
    under "WHAT K IS" was deferred on a reason that turned out to answer a
    weaker question -- it rejected one coarse SKETCH of a repair and generalised
    that to the repair itself -- and it was implemented once a narrower design
    was measured. The same suspicion was put to this one, and it survives, for a
    structurally different reason: there is no narrow version. All three
    widenings were tried at this tip and the SMALLEST exposes 37 pre-existing
    extractors:

        `for`-target gap alone          213 -> 254   (+41)
        setdefault(k, ...).add(v) alone 213 -> 250   (+37)
        both                            213 -> 301   (+88)

    None of those is fixable inside a branch about one extractor, and the debt
    register cannot take them. The objection here is to the GATE'S OWN
    STRUCTURE, which measurement confirms, and not to a sketch of mine, which
    measurement refuted.

    IF THAT PREDICATE IS EVER WIDENED, this function will be flagged and NEITHER
    of the gate's two registers fits it. `_NOT_PROSE` is for input in a formal
    grammar with no negation form, and this is real English. The baseline is a
    debt register of extractors that SHOULD consult polarity and do not, and
    this one measurably should not. The honest resolution at that point is a
    third answer -- "reads prose, and correctly does not honour a denial" -- not
    a stretched entry in either.
    """

    out: Dict[str, Set[Tuple[str, int]]] = {}
    for node in _emitted_nodes(tree):
        for m in PHRASE.finditer(node.value):
            if _in_an_emitted_comment(node.value, m.start()):
                continue
            out.setdefault(m.group(2).strip(), set()).add(
                (m.group(1), node.lineno))
    return out


def denies_containment(node: ast.AST, parent: Dict[int, ast.AST]) -> Optional[str]:
    """The Python construct by which the statement around `node` DENIES it, or
    None.

    THE PIN SIDE IS NOT PROSE, and that is the whole reason this is a grammar
    walk rather than a call to `_prose_polarity`. A test denies a containment in
    exactly the ways the LANGUAGE provides -- `not in`, `not`, `!=`, `is not`,
    `assertNotIn`, `assertIsNot*`, `assertFalse` -- and those are productions of
    Python's grammar, unambiguous and enumerable, the same argument the polarity
    gate's own `_NOT_PROSE` register makes about LEF, DEF and Liberty.

    ENUMERABLE IS A CLAIM, SO THE ENUMERATION WAS TESTED RATHER THAN TRUSTED,
    and it was short by two. `is not` (`ast.IsNot`, which `assertIsNot` reaches
    but the bare operator did not) and `assertFalse("..." in x)` -- a Call that
    denies the containment inside it -- both read as PINS, which puts the false
    refusal this function exists to stop straight back for those spellings.
    `assertTrue` and `assertEqual` are deliberately absent: they AFFIRM, and
    treating them as denials would drop real pins.

    AND A COMPARISON ONLY DENIES A LITERAL IT IS A SIDE OF. `script().count(
    "of 3 x") != 0` affirms the phrase, and reading that `!=` as a denial drops
    a real pin -- SILENTLY, because CHECK B then compares one fewer thing and
    still prints PASS. So the Compare forms require the literal to be a DIRECT
    operand. The cost is the other direction and it is the loud one: a denial
    written around a computed operand (`"of ".strip() not in x`) is missed, and
    a missed denial produces a REFUSAL a reader can answer. Same rule as
    `_RECORD_BREAKS`: when the two errors are not symmetric, take the one that
    announces itself.

    MEASURED over six realistic assertion spellings, the prose vocabulary got
    THREE of them wrong, in both directions:

        assert "of 3 repairs refused" in script(), "no PARTIAL line"
            the assertion MESSAGE carries "no" -> a real pin dropped
        assert "of 3 repairs refused" in script()   # not 2 any more
            a trailing comment carries "not" -> a real pin dropped
        self.assertNotIn("of 3 repairs refused", script())
            "assertNotIn" has no word boundary before "Not" -> denial MISSED,
            which puts the false refusal this function exists to stop straight
            back

    Both directions matter and neither is cosmetic: a dropped pin is CHECK B
    quietly comparing less than it read, and a missed denial is a correct test
    refused. The grammar walk gets all six right.

    THE CLIMB STOPS AT THE ENCLOSING STATEMENT. A negation further out belongs
    to different code -- an `if not x:` wrapping the whole test body does not
    deny this assertion -- so the walk answers for one statement and no more.
    """
    cur = node
    while True:
        up = parent.get(id(cur))
        if up is None:
            return None
        if isinstance(up, ast.UnaryOp) and isinstance(up.op, ast.Not):
            return "not"
        if isinstance(up, ast.Compare) and cur is node \
                and (cur is up.left or cur in up.comparators):
            # THE LITERAL ITSELF MUST BE A SIDE OF THE COMPARISON -- `cur is
            # node` says we have not climbed through anything yet.
            # `script().count("...") != 0` AFFIRMS the phrase, and reading its
            # `!=` as a denial drops a real pin -- silently, since CHECK B then
            # compares one fewer thing and still prints PASS. There the
            # comparison is about the COUNT and the literal is an argument to
            # it; testing "is the operand the literal" is not enough, because
            # the operand IS the call.
            if any(isinstance(o, ast.NotIn) for o in up.ops):
                return "not in"
            if any(isinstance(o, ast.NotEq) for o in up.ops):
                return "!="
            if any(isinstance(o, ast.IsNot) for o in up.ops):
                return "is not"
        if isinstance(up, ast.Call) and isinstance(up.func, ast.Attribute) \
                and (up.func.attr.startswith("assertNot")
                     or up.func.attr.startswith("assertIsNot")
                     or up.func.attr == "assertFalse"):
            return up.func.attr
        # THE STOP IS FOR CLARITY, NOT FOR CORRECTNESS, and that is measured
        # rather than assumed: every form this walk tests for -- UnaryOp,
        # Compare, Call -- is an `ast.expr`, and an expression is never the
        # parent of a statement. Counted over this tree: 602,938 edges whose
        # child is a statement, across 3,965 files; their parents are
        # statements (491,973), Module (104,129) and ExceptHandler (6,836),
        # and ZERO are expressions. So nothing the walk looks for can appear
        # above this point and deleting the stop cannot change an answer --
        # which is why the mutation sweep could not kill it. Keeping it says
        # where the question ends. `test_the_statement_stop_rests_on_a_true
        # _premise` fails if a form that is NOT an expression is ever added
        # to the walk, because that is what would make this reasoning false.
        if isinstance(up, ast.stmt):
            return None
        cur = up


def pins(text: str) -> Tuple[Dict[str, Set[Tuple[str, int]]],
                             List[Tuple[str, int, str]]]:
    """``({tail: {(value, lineno)}}, [(phrase, lineno, denial)])`` for the SOURCE
    of a test file -- `pins_of` for a caller that has already parsed, and that is
    where the reasoning lives, because that is the one `main` calls.
    """
    try:
        return pins_of(ast.parse(text))
    except SyntaxError:
        return {}, []


def pins_of(tree: ast.AST) -> Tuple[Dict[str, Set[Tuple[str, int]]],
                                    List[Tuple[str, int, str]]]:
    """``({tail: {(value, lineno)}}, [(phrase, lineno, denial)])`` -- what a test
    PINS, and what it turned out to be DENYING instead, from an
    already-parsed module. `pins` is the text-taking wrapper.

    A pin is an ASSERTION that the emitter states the value. This is not one:

        assert "of 3 repairs refused" not in script()

    It asserts the opposite -- that the emitter no longer says it -- and it is
    how a test correctly records that a population MOVED. Read as a pin it is
    compared against an emitter that now says 4, and the guard refuses a correct
    test for "the population moved and the pin did not" when the test is
    asserting exactly that the population moved. MEASURED against a
    self-consistent 4-site emitter: rc=1, one finding, both files correct. Same
    shape as #706, on the pin side.

    WHAT ASKS THE QUESTION is `denies_containment`, a walk over Python's own
    negation grammar rather than `_prose_polarity` -- see the measurement there
    for why, and note that `counters_of` on the OTHER side of this file does read
    real English and does consult the vocabulary. The two subjects differ; the
    readers follow the subjects.

    WHAT IT REFUSES IS RETURNED, not dropped -- a pin the guard declined to
    compare is a pin it did not check, and this file prints its reach.


    THE PARENT MAP IS BUILT ONLY IF THERE IS A PHRASE TO JUDGE. It costs a walk
    of the whole tree plus a dict entry per node, and the great majority of test
    files carry no `of <N> <tail>` at all, so paying for it before knowing there
    is a question is paying to answer a question nobody asked.

    IT IS WORTH A FEW PERCENT, AND THE NUMBER THAT USED TO BE HERE WAS WRONG.
    This said the laziness took the guard "from ~32s back to ~21s". It did not:
    that 11 seconds was a per-program AST cache introduced in the same commit,
    which held ~820 trees live at 596 MB peak and slowed every allocation in the
    run. The cache is gone; re-measured against an EAGER variant of this one
    function with nothing else changed, interleaved and with the eager arm
    FIRST so the ordering bias that produced the original figure could not
    repeat:

        eager   9.25  9.19  8.83 s user
        lazy    9.14  8.65  8.79 s user

    -- a few tenths of a second, close to this host's noise floor. The laziness
    stays because not paying before the question is asked is right, not because
    it buys eleven seconds. A number in a docstring is a claim; this one was
    measuring the wrong thing and is corrected rather than quietly dropped.
    """
    kept: Dict[str, Set[Tuple[str, int]]] = {}
    refused: List[Tuple[str, int, str]] = []
    carrying = [(n, list(PHRASE.finditer(n.value))) for n in _emitted_nodes(tree)]
    carrying = [(n, hits) for n, hits in carrying if hits]
    if not carrying:
        return kept, refused
    parent: Dict[int, ast.AST] = {}
    for n in ast.walk(tree):
        for child in ast.iter_child_nodes(n):
            parent[id(child)] = n
    for node, hits in carrying:
        word = denies_containment(node, parent)
        for m in hits:
            tail = m.group(2).strip()
            if word:
                refused.append((f"of {m.group(1)} {tail}", node.lineno, word))
                continue
            kept.setdefault(tail, set()).add((m.group(1), node.lineno))
    return kept, refused


def counters(text: str) -> Tuple[List[Tuple[str, int, List[Tuple[str, int]]]],
                                 List[Tuple[str, str, str]]]:
    """``([(name, increment_sites, [(kind, D)])], [(what, matched, denial)])``
    for the SOURCE of a program -- `counters_of` for a caller that has already
    parsed, and that is where the reasoning lives, because that is the one
    `main` calls.
    """
    try:
        return counters_of(ast.parse(text))
    except SyntaxError:
        return [], []


def counters_of(tree: ast.AST) -> Tuple[
        List[Tuple[str, int, List[Tuple[str, int]]]],
        List[Tuple[str, str, str]]]:
    """``([(name, increment_sites, [(kind, D)])], [(what, matched, denial)])``
    from an already-parsed module. `counters` is the text-taking wrapper.

    THE SUBJECT IS THE EMITTED SCRIPT, not the file that prints it -- see
    `emitted_script_of`. Read flat, for the reason this function always gave.

    POLARITY (vibe-ic#712). The script is read for two claims -- a MEMBERSHIP
    (`incr X`) and a THRESHOLD (`$X >= D`) -- and a script states both in English
    as readily as it states them in Tcl:

        # the retry path does not incr _n; it re-issues the command
        # $_n >= 4 is no longer the threshold, the fourth repair was removed
        puts "no repair could be applied"

    A reader that matches the first line and not the word `not` in it counts a
    DENIAL as a member; the population it reports is then confidently wrong, and
    it refuses a truthful emitter for disagreeing with a number nobody stated.
    That is #706 (`pdk_target`) in the counting direction. So every match is
    asked, through the ONE vocabulary in `_prose_polarity`, whether the statement
    it sits in denies it.

    WHAT POLARITY REFUSED IS RETURNED, NOT DROPPED. This guard prints its reach
    on every run; a reach that shrank because a denial was believed is part of
    the reach, and a guard that quietly counts less than it read is the failure
    this file is built to catch one level up.
    """
    src = emitted_script_of(tree)

    def denial(m: "re.Match[str]") -> Optional[str]:
        """The word by which the emitted statement around `m` DENIES it."""
        lo, hi = sentence_scope(src, m.start(), m.end(),
                                extra_breaks=_RECORD_BREAKS)
        return is_denied(src[lo:hi])

    refused: List[Tuple[str, str, str]] = []
    names: Dict[str, int] = {}
    for m in INCR.finditer(src):
        word = denial(m)
        if word:
            refused.append(("increment", m.group(0), word))
            continue
        # A COMMENTED `incr` IS NOT A SITE, and this is the SILENT
        # direction: `# incr _n for the third repair, added later` carries no
        # denial word, so it was COUNTED, and an emitter that really increments
        # twice then AGREED with its stated denominator of 3. A real
        # disagreement, masked by a line that never executes.
        #
        # AFTER the polarity consult, not before. A denied `incr` almost always
        # lives in a comment, so checking this first turned a REPORTED
        # `[POLARITY]` refusal into a silent skip -- measured, it took 11 tests
        # with it -- and trading a false pass for a disclosure loss is not a
        # trade this file may make. In this order nothing that was reported
        # becomes silent; only what was wrongly counted stops being counted.
        #
        # Nor is the skip itself reach: a comment is not a claim the script
        # makes, and this program does not report every line that stated
        # nothing. What polarity refuses IS a claim, in text meant to be read,
        # and that is why it is printed.
        if _in_an_emitted_comment(src, m.start()):
            continue
        names[m.group(1)] = names.get(m.group(1), 0) + 1
    rows = []
    for name, sites in sorted(names.items()):
        dens: List[Tuple[str, int]] = []
        for kind, tmpl in _DEN_TEMPLATES:
            for m in re.finditer(tmpl % re.escape(name), src):
                value = int(m.group(1))
                if value < MIN_POPULATION:
                    continue
                word = denial(m)
                if word:
                    refused.append((f"{kind} denominator", m.group(0), word))
                    continue
                # A threshold stated only in a COMMENT is not a threshold the
                # script states to anyone; counting it invents the second
                # statement this file exists to compare the first against.
                # After polarity, for the reason given at the `incr` scan.
                if _in_an_emitted_comment(src, m.start()):
                    continue
                if (kind, value) not in dens:
                    dens.append((kind, value))
        if dens:
            rows.append((name, sites, dens))
    return rows, refused


def multiplied_counters(tree: ast.AST) -> Dict[str, int]:
    """``{counter: how many times its `incr` is emitted per written site}`` for
    counters whose K is only a LOWER BOUND.

    K COUNTS `incr` WRITTEN IN THE SOURCE, not times emitted. An emitter that
    builds each repair through a HELPER is honest and states a real population,
    and the guard refuses it: "incremented at 1 site(s) but its comparison
    denominator says 3". Recorded as a known limitation until it was measured
    properly.

    THE DETECTION IS PER-COUNTER AND NARROW: the `incr X` literal lives inside a
    FUNCTION BODY, and that function is called more than once in the module. An
    earlier, coarser sketch -- "the script is assembled through a call anywhere"
    -- was rejected because it fires on `phase3_one_shot_runner::_prr_refused`,
    whose literals sit in an expression with three `_est0104_recovery_tcl(...)`
    calls interleaved. MEASURED, this one does not: those literals are INLINE in
    `_postroute_repair_estimate_tcl`, which is called once. The rejection was of
    the sketch, not of the repair.

    MEASURED over the shipped tree: ten counters qualify (`_n`, `_duf`, `_skip`,
    `_rrc` and others), and `_prr_refused` -- the only counter that reaches a
    comparison at all -- is NOT among them. So no verdict this guard reaches
    today moves.

    ITS TWO FAILURE MODES, MEASURED, AND NEITHER IS SILENT -- which is why it
    is left this narrow rather than made cleverer:

      UNDER-FIRE   a helper that is a METHOD is missed: `calls` counts
                   `ast.Call` whose func is a plain `Name`, so `self._r(...)`
                   is not seen. The counter reads as a COUNT and the false
                   refusal returns for that shape -- LOUD, and answerable.
      OVER-FIRE    two lexical calls in EXCLUSIVE branches count as two, though
                   only one runs. The comparison is then DECLINED where it might
                   have been decidable -- conservative, and printed as
                   NOT DECIDABLE rather than passed.

    Extending it to `Attribute` calls would close the first and widen the
    second, and MEASURED over this corpus that trade buys nothing: of 29 `incr`
    literals in the six programs that contain one, ZERO are hosted by a method
    and 29 by a plain function. Machinery for a shape the corpus does not have,
    paid for in the silent direction.

    IT ASKS POLARITY, for the reason `counters_of` does and about the same text.
    A denied `incr` must not count as evidence of a multiplier here while being
    refused as a member there; two readers of one script that disagree about a
    denial is #711's divergence, and it was live in the first revision of this
    function.
    """
    parent: Dict[int, ast.AST] = {}
    for n in ast.walk(tree):
        for child in ast.iter_child_nodes(n):
            parent[id(child)] = n
    calls: Dict[str, int] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            calls[n.func.id] = calls.get(n.func.id, 0) + 1
    out: Dict[str, int] = {}
    for node in _emitted_nodes(tree):
        for m in INCR.finditer(node.value):
            # POLARITY FIRST, THEN THE COMMENT RULE -- the order `counters_of`
            # uses, and here it is load-bearing for a second reason. With the
            # comment rule first this consult became DEAD: measured, deleting
            # it outright left the ENTIRE suite green (88 tests then, and
            # the count is not the point), and
            # `test_a_DENIED_incr_cannot_excuse_a_real_disagreement` went on
            # passing for a reason other than the one it names. Unreachable
            # code that a test appears to cover is worse than no code.
            # POLARITY, THE SAME QUESTION `counters_of` ASKS OF THE SAME TEXT.
            # Without this the two readers disagree about one script: a denied
            # `incr` is refused as a member there and counted as evidence of a
            # multiplier here, so a GENUINE `sites < denominator` disagreement is
            # excused as NOT DECIDABLE -- the silent direction. Measured, rc went
            # 1 -> 0 on a real disagreement. That divergence-by-second-reader is
            # #711 exactly, which is the defect this whole file exists to answer.
            #
            # Scoped WITHIN the node, which is provably the same answer
            # `counters_of` gets: it scopes over the nodes joined by "\n" and
            # declares "\n" a record break, so no scope there crosses a node
            # boundary either.
            lo, hi = sentence_scope(node.value, m.start(), m.end(),
                                    extra_breaks=_RECORD_BREAKS)
            if is_denied(node.value[lo:hi]):
                continue
            # A COMMENTED `incr` is not evidence of a multiplier either, and
            # the two readers must not disagree about one script -- that
            # divergence is #711 itself.
            if _in_an_emitted_comment(node.value, m.start()):
                continue
            cur, host = node, None
            while id(cur) in parent:
                cur = parent[id(cur)]
                if isinstance(cur, ast.FunctionDef):
                    host = cur.name
                    break
            if host and calls.get(host, 0) > 1:
                out[m.group(1)] = max(out.get(m.group(1), 0), calls[host])
    return out


def named_program(tree: ast.AST, stems: Set[str]) -> Optional[str]:
    """The single program a test file names, or None if it names 0 or >1.

    Taken from imports and from ``"<stem>.py"`` path literals — the two ways a
    test in this tree reaches a program. A test naming several programs is left
    alone: which emitter a phrase belongs to would be a guess.

    TAKES THE PARSED TREE, not the text. Two reasons, and the first is honesty:
    parsing here and returning None on `SyntaxError` made a file this reader
    COULD NOT READ indistinguishable from one that names no program, so an
    unparseable test left the guard's reach silently. The caller parses, reports
    what it could not parse, and passes the tree. The second is cost -- CHECK B
    walks every test file in the tree and the parse is the single largest share
    of this guard's runtime, so parsing twice to ask two questions is the wrong
    shape.

    MEASURED, because "most" is what this said until it was checked and "most"
    means a majority: 3.59s of 9.31s over 3547 calls, so 39% -- the biggest
    single line item, not more than everything else together. The argument for
    parsing once is unchanged at 39%; the word was. (Median of three; first
    recorded as 41% from one run, which is the same magnitude and was not
    re-derived until it was.)

    MEASURE IT BY TIMING `ast.parse` DIRECTLY, not under cProfile. The profiler
    instruments Python-level calls and not the C-level parse, so it reports the
    same work as 15% of a total inflated to ~25s -- a reader who re-checks that
    way will conclude this paragraph is wrong by a factor of two and it is the
    instrument. Wrap `ast.parse`, run `main`, compare against wall clock; the
    call count 3547 is the same either way and is the thing to confirm you are
    measuring the right target.
    """
    found: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                root = a.name.split(".")[-1]
                if root in stems:
                    found.add(root)
        elif isinstance(n, ast.ImportFrom) and n.module:
            root = n.module.split(".")[-1]
            if root in stems:
                found.add(root)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) \
                and n.value.endswith(".py"):
            root = n.value[:-3].split("/")[-1]
            if root in stems:
                found.add(root)
    return next(iter(found)) if len(found) == 1 else None


def main(argv: Optional[List[str]] = None) -> int:
    here = Path(__file__).resolve().parent
    ap = _usage.GateArgumentParser(
        prog=TOOL,
        description="refuse an emitted population and its test pin that "
                    "disagree")
    ap.add_argument("--programs", type=Path, default=here)
    ap.add_argument("--tests", type=Path, default=here / "tests")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    if not args.programs.is_dir():
        return _usage.usage_error(TOOL, f"--programs {args.programs} is not a "
                                        f"directory")
    if not args.tests.is_dir():
        return _usage.usage_error(TOOL, f"--tests {args.tests} is not a "
                                        f"directory")
    # CHECKED BEFORE THE WORK, not after it. `--json <a directory>` used to run
    # the whole sweep and then die on IsADirectoryError -- a traceback wearing
    # rc 1, this program's REFUSAL code, so a mistyped argument was
    # indistinguishable from a population disagreement.
    if args.json is not None and str(args.json) != "-" and args.json.is_dir():
        return _usage.usage_error(TOOL, f"--json {args.json} is a directory")

    sources = {p.stem: p for p in sorted(args.programs.glob("*.py"))}
    findings: List[dict] = []
    denied: List[dict] = []
    #: Sources this guard tried to read and could not. NEVER silent: a reach
    #: that shrank because a file would not parse is still a shrunken reach, and
    #: the whole subject moved to the AST when `counters` stopped reading raw
    #: text -- before that a broken file was still regex-scanned, so this is the
    #: one direction that change could quietly lose.
    unparsed: List[str] = []
    #: Counters whose K is a LOWER BOUND, not a count -- see
    #: `multiplied_counters`. Printed, never silently skipped.
    undecidable: List[dict] = []
    substituted: List[dict] = []
    seen_substituted: Set[str] = set()

    def record_substitution(name: str, n: int) -> None:
        """Say once per FILE. Both readers on the program side reach the same
        source, and a reach report that counts one file twice is its own
        small lie -- the same rule `record_unparsed` follows."""
        if n and name not in seen_substituted:
            seen_substituted.add(name)
            substituted.append({"source": name, "characters": n})

    counters_examined = 0
    pins_examined = 0
    pins_unmatched = 0

    # ── CHECK A — the emitter against itself ────────────────────────────────
    text_cache: Dict[str, str] = {}

    seen_unparsed: Set[str] = set()

    def record_unreadable(name: str, e: OSError) -> None:
        """A path `rglob` yielded that will not OPEN.

        `rglob("test_*.py")` matches whatever bears the name: a broken symlink,
        a DIRECTORY called `test_x.py`, a file the runner has no permission on.
        Every one of them raised out of the read and took the whole census down
        with a traceback -- and out of a program whose refusal exit code is
        also 1, so a broken symlink in someone's tree was indistinguishable
        from a population disagreement, sending a reader hunting for a finding
        that did not exist.

        Recorded as `unparsed` rather than a tier of its own, because that list
        already means exactly this: nothing in it was examined. What differs is
        only WHY, and the message says which."""
        if name not in seen_unparsed:
            seen_unparsed.add(name)
            unparsed.append(f"{name}: {e.strerror or e}")

    def body(stem: str) -> str:
        if stem not in text_cache:
            try:
                text, n = read_source(sources[stem])
            except OSError as e:
                record_unreadable(sources[stem].name, e)
                text_cache[stem] = ""
            else:
                record_substitution(sources[stem].name, n)
                text_cache[stem] = text
        return text_cache[stem]

    def record_unparsed(name: str, e: SyntaxError) -> None:
        """Say once that a PROGRAM could not be read.

        Two readers on this side reach the same file -- CHECK A's `incr ` scan
        and `emitter_phrases` -- and a reach report that counts one file twice
        is its own small lie.

        THE TEST SIDE APPENDS DIRECTLY and does not need this: `rglob` yields
        each test once, and it records the full path rather than a basename
        because tests nest in subdirectories where a basename would be
        ambiguous. Two key spaces, deliberately, so this set cannot collide
        with a test path either."""
        if name not in seen_unparsed:
            seen_unparsed.add(name)
            unparsed.append(f"{name}:{e.lineno}: {e.msg}")

    # A TREE IS DERIVED FROM AND THEN DROPPED, NEVER CACHED. Caching them was
    # measured at 596 MB peak RSS against 221 MB for the pre-polarity revision
    # (3c3c51aee -- NAMED, because the batch head has since advanced onto
    # this work and no longer serves as a 'before')
    # -- ~820 program ASTs held live, two of them over 2 MB of source -- and the
    # allocator and GC pressure that buys makes EVERY parse in the run about
    # twice as slow, including parses of files the cache never touched. On this
    # fleet memory is a named constraint, so what is kept is the small derived
    # answer (a phrase dict, a bool) and never the tree it came from.
    for stem in sources:
        src = body(stem)
        if "incr " not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            record_unparsed(sources[stem].name, e)
            continue
        rows, refused = counters_of(tree)
        lower_bound = multiplied_counters(tree)
        del tree
        for what, matched, word in refused:
            denied.append({"where": sources[stem].name, "what": what,
                           "matched": matched, "denial": word})
        for name, sites, dens in rows:
            for kind, value in dens:
                if name in lower_bound and sites <= value:
                    # K IS A LOWER BOUND HERE, so ONLY `sites > denominator` is
                    # decidable: a lower bound that EXCEEDS the stated
                    # population cannot be explained by emitting more, and is
                    # left to the comparison below.
                    #
                    # EQUALITY IS NOT AGREEMENT EITHER, which the first version
                    # of this rule got wrong by testing `value != sites` first.
                    # The script emits sites x multiplier; two literal sites in
                    # a helper called three times emit SIX against a denominator
                    # of 2, and equality of the LITERAL count with the
                    # denominator was read as "agrees" -- measured, rc=0 with no
                    # finding. A number that cannot be compared cannot match.
                    undecidable.append({
                        "program": sources[stem].name, "counter": name,
                        "increment_sites": sites, "denominator": value,
                        "denominator_kind": kind,
                        "emitted_per_site": lower_bound[name],
                    })
                    continue
                # COUNTED ONLY ONCE IT IS ACTUALLY COMPARED. Counting a
                # comparison this guard then DECLINED overstates the reach and,
                # worse, keeps an all-declined run out of the VACUOUS tier: it
                # printed "every population stated twice agrees" having compared
                # none. Measured -- rc=0 on a run whose only counter was
                # undecidable.
                counters_examined += 1
                if value != sites:
                    findings.append({
                        "check": "emitter-self",
                        "program": sources[stem].name, "counter": name,
                        "increment_sites": sites,
                        "denominator": value, "denominator_kind": kind,
                    })

    # ── CHECK B — the test pin against the emitter ──────────────────────────
    phrase_cache: Dict[str, Dict[str, Set[Tuple[str, int]]]] = {}

    def emitter_phrases(stem: str):
        if stem not in phrase_cache:
            try:
                # The tree is a temporary: `phrases_of` returns a small dict and
                # the AST is unreachable the moment this returns.
                phrase_cache[stem] = phrases_of(ast.parse(body(stem)))
            except SyntaxError as e:
                record_unparsed(sources[stem].name, e)
                phrase_cache[stem] = {}
        return phrase_cache[stem]

    stems = set(sources)
    tests_seen = 0
    for test in sorted(args.tests.rglob("test_*.py")):
        tests_seen += 1
        try:
            text, n_sub = read_source(test)
        except OSError as e:
            record_unreadable(str(test), e)
            continue
        record_substitution(test.name, n_sub)
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            unparsed.append(f"{test}:{e.lineno}: {e.msg}")
            continue
        stem = named_program(tree, stems)
        if stem is None:
            continue
        em = emitter_phrases(stem)
        if not em:
            continue
        pinned, pin_refused = pins_of(tree)
        for phrase, lineno, word in pin_refused:
            denied.append({"where": f"{test}:{lineno}", "what": "test pin",
                           "matched": phrase, "denial": word})
        for tail, values in pinned.items():
            if tail not in em:
                # SAID, not skipped. A test pins `2 document(s)` and the program
                # it names emits `{docs} document(s)` -- a computed count, with
                # no literal for the pin to disagree with. Declining is right;
                # dropping it in silence is not, and this branch took 10 of the
                # corpus's 11 pins with nothing in the reach to show for it.
                pins_unmatched += len(values)
                continue
            emitted = {v for v, _ in em[tail]}
            emitted_lines = sorted({ln for _, ln in em[tail]})
            for value, lineno in sorted(values):
                pins_examined += 1
                if value not in emitted:
                    findings.append({
                        "check": "pin-against-emitter",
                        "test": str(test), "test_line": lineno,
                        "program": sources[stem].name,
                        "program_lines": emitted_lines,
                        "phrase": tail,
                        "pinned": value, "emitted": sorted(emitted),
                    })

    # COMPARED, not "examined". Both counts moved to mean what was actually
    # compared when a declined comparison stopped being counted as one made;
    # leaving the older word would have the head describe a different quantity
    # from the one it prints.
    head = (f"{counters_examined} emitted counter denominator(s) and "
            f"{pins_examined} test pin(s) COMPARED out of a corpus of "
            f"{len(sources)} program(s) and {tests_seen} test(s) SCANNED; {len(denied)} match(es) "
            f"not counted because the statement DENIES them; {len(unparsed)} "
            f"source(s) NOT examined because they would not parse; "
            f"{len(undecidable)} population(s) NOT DECIDABLE; "
            f"{len(substituted)} source(s) whose bytes were SUBSTITUTED to be "
            f"read at all; {pins_unmatched} test pin(s) the named program does "
            f"not state a literal for, so there was nothing to compare")
    report = {"tool": TOOL, "counters_examined": counters_examined,
              "corpus": {"programs": len(sources), "tests": tests_seen},
              "pins_unmatched": pins_unmatched,
              "pins_examined": pins_examined, "denied_by_polarity": denied,
              "unparsed": unparsed, "not_determined": undecidable,
              "substituted": substituted,
              "findings": findings}
    # `--json -` PUTS THE DOCUMENT ON STDOUT. 34 programs in this corpus
    # implement that spelling, and `_vacuous_exit` routes its sentinel to stderr
    # expressly because of it: "these gates support ``--json -``, which puts the
    # report document on stdout, and a sentinel line mixed into that stream
    # would make the document unparseable". This program had a `--json` flag and
    # none of that, so the convention produced a junk file NAMED `-`.
    #
    # Where it departs from those 34: they print the human report only when
    # --json is ABSENT, and this one keeps printing it -- to STDERR, so stdout
    # stays a parseable document. The reach is printed, always; suppressing it
    # to honour a convention would trade this file's own rule for someone's
    # output shape, and stderr costs the document nothing.
    to_stderr = False
    if args.json is not None:
        if str(args.json) == "-":
            print(json.dumps(report, indent=2))
            to_stderr = True
        else:
            try:
                _atomic.write_json(args.json, report)
            except OSError as e:
                return _usage.usage_error(
                    TOOL, f"--json {args.json} could not be written: "
                          f"{e.strerror or e}")
    out = sys.stderr if to_stderr else sys.stdout

    for u in undecidable:
        print(f"  [NOT DECIDABLE] {u['program']}: counter ${u['counter']} is "
              f"written at {u['increment_sites']} site(s) but its `incr` sits "
              f"in a helper called {u['emitted_per_site']}x, so that is a LOWER "
              f"BOUND, not a count; its {u['denominator_kind']} denominator "
              f"says {u['denominator']} and the shortfall is exactly what a "
              f"helper produces — NOT compared", file=out)
    for u in unparsed:
        print(f"  [UNPARSED] {u} — this guard could NOT read it, so nothing in "
              f"it was examined", file=out)
    for b in substituted:
        print(f"  [SUBSTITUTED] {b['source']}: {b['characters']} character(s) "
              f"of this file do NOT decode as UTF-8 and were replaced before "
              f"it was read, so what was analysed is not the file — any "
              f"population the replacement landed in went unmatched and is "
              f"NOT in the counts above", file=out)
    for d in denied:
        print(f"  [POLARITY] {d['where']}: {d['what']} `{d['matched']}` sits "
              f"in a statement that DENIES it (\"{d['denial']}\") and is NOT "
              f"counted", file=out)

    if counters_examined == 0 and pins_examined == 0:
        # WHY IT IS EMPTY, because the two reasons are not the same fact. "No
        # population is stated twice here" is FALSE when one was stated twice
        # and this guard declined to decide it -- and that sentence is the only
        # thing a reader gets on a path where nothing else was printed.
        withheld = len(undecidable) + len(denied) + len(unparsed)
        # AN EMPTY CORPUS IS FIRST, because every other reason is a claim
        # about programs that were read. Point this at a real but wrong
        # directory and the old answer was "no population is stated twice
        # here" -- true of an empty set, and it reads as "I checked".
        reason = ("corpus-holds-no-program" if not sources
                  else "declined-every-comparison" if withheld
                  else "source-bytes-substituted" if substituted
                  else "no-population-stated-twice")
        _vac.announce_vacuous(TOOL, reason)
        # THE REACH IS PRINTED ON THIS PATH TOO. A verdict of "nothing was
        # compared" is exactly the one a reader needs the reach for: it is the
        # difference between a tree that states no population twice and a tree
        # this guard could not read. Without it, a run whose reach was emptied
        # by unparseable sources -- or by polarity -- announced the empty result
        # and not the cause.
        said = ("the program corpus is EMPTY -- this directory holds no "
                "program at all, so nothing here is a statement about any "
                "tree" if not sources
                else "every population this tree states twice was WITHHELD from "
                "comparison above" if withheld
                else "no population survived the byte substitution above, so "
                "this tree may well state one twice" if substituted
                else "no emitted population is stated twice here")
        print(f"[VACUOUS] {TOOL}: {said}, so nothing was compared; this is NOT "
              f"a pass [{head}]", file=out)
        return _vac.RC_VACUOUS

    if findings:
        for f in findings:
            if f["check"] == "emitter-self":
                print(f"  [POPULATION] {f['program']}: counter ${f['counter']} "
                      f"is incremented at {f['increment_sites']} site(s) but "
                      f"its {f['denominator_kind']} denominator says "
                      f"{f['denominator']} — the emitter states one population "
                      f"twice and disagrees with itself", file=out)
            else:
                print(f"  [POPULATION] {f['test']}:{f['test_line']} pins "
                      f"\"of {f['pinned']} {f['phrase']}\", but "
                      f"{f['program']} (line(s) "
                      f"{', '.join(str(x) for x in f['program_lines'])}) states "
                      f"{', '.join(f['emitted'])} — the population moved and "
                      f"the pin did not", file=out)
        print(f"[FAIL] {TOOL}: {len(findings)} population(s) stated twice and "
              f"disagreeing [{head}]", file=out)
        return _vac.RC_FAIL

    print(f"[PASS] {TOOL}: every population stated twice agrees [{head}]", file=out)
    return _vac.RC_PASS


if __name__ == "__main__":
    sys.exit(main())
