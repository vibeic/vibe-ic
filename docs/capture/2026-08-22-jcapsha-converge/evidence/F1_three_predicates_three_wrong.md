# Three predicates for F1, three wrong, each in a different direction

This closes F1 with an answer rather than a suggestion. I stated a rule, wrote
it, found it wrong, stated a better one, wrote that, and found it wrong too —
and the third failure is the one that settles the question.

## Attempt 3: "name the SUBJECT OF THE CONDITION that raised the refusal"

This was my own prescription at the end of the previous evidence file. Written
as `F1_rule_population_probe2.py`: walk from the refusal UP to the `if` whose
test decides it is reached, take the names in that test, require the message to
interpolate one. On `origin/main` a4caccefe:

    absence verdicts          : 25
      names its guard subject : 13
      DOES NOT                : 11
      no guarding `if`        :  1

It flags all four `PAD_SITE_NOT_FOUND` sites — the original defect — which the
word-list predicate passed. That looked like the answer. Then I read what it
refuses.

## It refuses the exemplar

`pad_ring_gen.py:712`, the POST-FIX message that F1's own fix wrote:

    site = lib.resolve_site(name)
    if site is None:
        return _fail("PAD_SITE_NOT_FOUND",
            f"{var}={name!r} is declared by neither PDK view this run "
            f"resolved: {len(lib.sites)} LEF SITE record(s) from {len(lefs)} "
            f"LEF(s) and {len(lib.declared_sites)} tech-view declaration(s) "
            f"from {len(lib.site_declarations)} config file(s). ...")

That is the gold standard for this rule: it names BOTH views, with counts of
each, and says the thing is declared by neither. **The predicate refuses it**,
because the guard's subject is `site` and the message never mentions `site` —
it mentions `lib.sites`, `lefs`, `lib.declared_sites`, `lib.site_declarations`.

Two more of the same shape: `pad_ring_check.py:155` names `def_rel` where the
guard tests `def_path` — the same path by a different name — and
`ppa_report_gen.py:254` names the field in backticks where the guard tests the
variable.

## Why that is the end of the line, and not a fourth attempt

The three failures are not three bugs. They are three different WRONG QUESTIONS:

| attempt | asks | why it is wrong |
|---|---|---|
| 1 — the prior lane's | does the message mention a locus WORD? | passes the pre-fix refusal, which said `LEF(s)`; 2 false positives |
| 2 — mine | does it interpolate something the FUNCTION iterated? | attributes unrelated iterations; refuses paths that name themselves exactly |
| 3 — mine | does it name the SUBJECT of the guarding condition? | refuses the exemplar, because the subject is the thing SOUGHT and the disclosure is about where it was SOUGHT |

The right question is none of these. `if site is None` — the subject is `site`;
what a reader needs is not `site` but **the set of places consulted to answer
whether `site` exists**, which lives one hop back, inside
`lib.resolve_site(name)`, and is only visible by following `site` to its
definition and then asking what THAT consulted. That is a reaching-definitions
walk across a method boundary. Deterministic, still Bucket A in principle, and
well past what a predicate over one call site can decide.

**I stopped here deliberately.** I have now been wrong three times, each time in
a way that was invisible from inside the implementation and visible in ten
minutes of reading its output. A fourth shape tried tonight would be selected
by whether it comes out green on today's 25 call sites, which is fitting to the
corpus and not to the rule — the thing this whole branch is about.

## The status this produces

F1 does NOT ship. That is a measured verdict, not a deferral:

* the existing implementation is blind to the case it was written for;
* two independent replacements, one of them my own prescription, are each
  refuted by their own output;
* the decidable form needs interprocedural reaching-definitions, which is real
  program work and not a predicate tweak.

The rule itself is unchanged and correct, and the exemplar of it is already in
the tree at `pad_ring_gen.py:712` — which is worth saying, because a rule with
a working instance and no checker is in better shape than the reverse.
