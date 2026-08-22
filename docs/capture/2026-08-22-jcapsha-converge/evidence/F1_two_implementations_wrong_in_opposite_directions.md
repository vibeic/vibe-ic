# I implemented the corrected F1 rule to measure it, and it is wrong too

The previous evidence file ends by stating the decidable rule:

    an absence verdict must interpolate THE COLLECTION IT ITERATED --
    the actual list of things opened -- not a count of it, and not a
    word that sounds like a place.

That was a suggestion. This file turns it into a measurement, and the
measurement refuses it. Probe: `F1_rule_population_probe.py` (NOT SHIPPED),
run over `programs/` on `origin/main` at `a4caccefe`.

## What the probe reported

    absence verdicts                     : 25
    IN SCOPE (a collection was searched) : 24
      carry the collection               : 9
      WOULD BE REFUSED                   : 15
    OUT OF SCOPE (nothing iterated)      : 1

15 of 24 refused is 62% of the state we shipped. Before writing that number
down as the rule's population, I read the refusals it names.

## The first two I read are exemplary disclosures

`_ppa/backends/openroad.py:1071`

    d = Path(pnr_dir)
    if not d.is_dir():
        o.refuse("RUN_DIR_ABSENT", f"{d}: not a directory")

It names the exact path. There is nothing more to disclose. The probe put it
"in scope" because `js` and `records` are iterated ELSEWHERE in the same
function, over unrelated things.

`otp_image_check.py:176`

    if not ver_path.exists():
        findings.append(Finding("FILE_MISSING", "error",
                                f"OTP image not found: {ver_path}"))

Also names the exact path. Also a false positive.

## So the probe's error is structural, and visible in its own output

It attributes to a refusal every iteration anywhere in the enclosing function.
Its own printout gives it away — `(scope searched: ['e'])`,
`(scope searched: ['image'])`, `(scope searched: ['PR', 'args', 'decls',
'findings'])`. Those are not the collection the refusal is about; several are
not collections at all.

**The number 15 is not the rule's population and must not be quoted as one.**
It is the population of "absence verdicts in functions that iterate something",
which is a different question and a nearly useless one.

## Two implementations, wrong in opposite directions

| implementation | predicate | what it gets wrong |
|---|---|---|
| shipped in the prior lane | the message mentions a word from a 57-word locus vocabulary | PASSES the real pre-fix refusal; 2 false positives on main |
| this probe | the message interpolates a name the enclosing function iterated | refuses 15, and the sampled ones are model disclosures |

Neither error is visible from inside its own implementation. The first looks
clean because 29 of 31 pass; the second looks thorough because it finds 15.
Both are measuring something adjacent to the question.

## What the question actually needs

Both cases the probe got wrong are decided by ONE thing it does not look at:
**the condition that raised the refusal.**

    if not d.is_dir():      -> the subject is `d`, and the message names `d`.
    if site is None:        -> the subject is the lookup that returned None,
                               and THAT is what the pre-fix message did not
                               disclose the provenance of.

So the rule is "an absence verdict must name the subject of the condition that
raised it" — a dataflow question from the refusal back to its guard, not a
property of the enclosing scope and not a property of the message's vocabulary.
That is still deterministic and still Bucket A. It is also real program work,
not a predicate tweak, and it is not being done tonight under a freeze.

## The verdict this produces

F1 does NOT ship, and the reason is now two independent measurements rather
than one. I stopped here rather than trying a third predicate, because at this
point I would be iterating shapes until one came out green on today's corpus,
and a predicate arrived at that way is fitted to the corpus, not to the rule.
