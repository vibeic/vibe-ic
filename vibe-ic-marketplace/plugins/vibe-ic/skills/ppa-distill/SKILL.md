---
name: ppa-distill
description: Turn a PPA recovery that worked into a case with evidence, a design fingerprint that bounds where it may be reused, and a draft of the deterministic rule it should eventually become. Use when the user says "capture this", "we should remember this fix", "distill the lesson", "promote this case", or after any closure loop where judgement recovered a result a program could not.
---

# PPA Distill

## The boundary this skill lives inside

This skill produces a **structured case record and a draft rule**. It never
produces a gate verdict, and it never promotes its own case. The lifecycle from
`RAW` to `PROGRAMMED` is owned by `_ppa/distillation.py` per
`docs/PPA_INTERFACES.md` §4, and every rung of that ladder is a program's
decision made against evidence this document supplies.

The failure this guards against is the one that makes a plugin worse the harder
it is used: a fix that worked once on one design gets written down as a rule,
the rule fires on a design it was never true for, and the fix is now a defect
that arrives with authority. The fingerprint is what stops that. A case that
cannot say which designs it applies to has not been distilled; it has been
remembered.

The draft rule is the point of the exercise. A case that stays prose is a case a
future author has to remember; a case that becomes a deterministic rule is one
nobody has to. Write the rule as something a program could execute, even while
the case is still `RAW` and nothing may execute it yet.

## When to use

Trigger when:
- A closure or recovery loop reached a result the deterministic path did not
- A diagnosis found a cause that the program-first diagnosis missed
- The same fix has now been applied on more than one design
- Someone asks for a case to be promoted a rung

## Inputs to gather

1. What failed, in metric terms and with scope — not "timing was bad"
2. What the deterministic path did, and where it stopped
3. What the judgement step did that changed the outcome
4. The before and after metric records, at matched scope
5. Everything about the design that might be why this worked: PDK, clock domain
   count, macro count, utilization, hierarchy depth, the flow and its version

## Workflow

1. **Write the case before writing the rule.** The case is what happened; the
   rule is what should happen next time. Deriving the second without recording
   the first produces a rule nobody can re-check.
2. **Bind the case to evidence.** Before and after records, with source hashes.
   A case whose improvement cannot be re-derived from artefacts is a story.
3. **Fingerprint the design, deliberately over-narrow.** List everything that
   might matter, including things you doubt. A fingerprint that is too narrow
   costs a missed reuse; one that is too broad costs a wrong rule firing on a
   design nobody checked. The costs are not symmetric.
4. **State the promotion criteria as a countable condition.** "Once we trust it"
   is not a criterion. "Reproduced on three designs with differing fingerprints,
   with no counter-example" is.
5. **Draft the rule as a program would run it.** Its input, its condition, its
   action, and the observation that would refute it. If you cannot write the
   condition, the case is not ready to be a rule and says so.
6. **Record the counter-examples too.** A design where this was tried and did not
   help is the most valuable row in the case, and it is the one that never gets
   written down.

## Do not

- Do not promote the case here. `Lifecycle:` records the rung it is on; the
  program moves it.
- Do not write a rule keyed on a design name, a chip name, a project name or any
  other identifier of one particular design. A rule that recognizes the design it
  was derived from is a lookup table, and it makes every benchmark number that
  touches it meaningless.
- Do not distil a case whose improvement was never remeasured at matched scope.
- Do not omit the counter-examples, and do not soften them into caveats.
- Do not record a case as evidence for itself. The before and after records come
  from `ppa-measure`, not from this document.

## Output format

The deliverable is one markdown case record. The template below is the whole shape.

    # PPA Case — <one line, what was recovered>

    Verdict authority: _ppa/distillation.py - this record promotes nothing itself.

    ## Summary
    <what the deterministic path could not do, and what judgement did instead>

    Lifecycle: RAW
    Design fingerprint: pdk=gf180mcuD, clock_domains=1, macros=0,
    utilization=0.62, hierarchy_depth=4, flow=orfs, flow_version=<v>

    ## Case

    What failed: timing.setup.wns_ns = -0.124 ns at post_route_extracted / ss
    Deterministic path: _ppa/agent_router.py rc=2, no path detail produced
    What judgement did: identified a high-fanout enable net from the shared-endpoint
    pattern and proposed buffering it before re-running PnR
    Result after: timing.setup.wns_ns = -0.031 ns, same scope, remeasured

    ## Counter-examples

    | design fingerprint | outcome | artefact |
    |---|---|---|
    | pdk=gf180mcuD, macros=3 | no improvement; congestion dominated | sha256:77c1de40 |

    ## Programmed rule draft

    Input: the failing-endpoint list from the STA path report
    Condition: at least 70% of failing endpoints share one net AND that net's
    fanout exceeds the technology buffering threshold
    Action: emit a buffering candidate for that net as a ppa-optimize actuator
    Refuted by: a run where the condition held and buffering did not improve WNS
    Promotion criteria: reproduced on 3 designs with differing fingerprints, with
    the counter-example table showing no unexplained failure

    ## Evidence

    | artefact | sha256 | tool |
    |---|---|---|
    | phase3/stage3/sta/paths.rpt | sha256:0a5b93f6 | opensta |

    Next: run /ppa-benchmark

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/ppa-distill/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed, exit 2 =
the checker could not read one of its own inputs and reached no conclusion.

**Your task is not complete until the audit returns PASS.**
