---
name: ppa-benchmark
description: Set up a PPA comparison between two or more arms — tool versions, flow configurations, RTL variants, PDKs — by declaring each arm, the conditions that make them comparable, and the residual unfairness that survives. Scoring is done by an independent program, never by this skill. Use when the user says "compare these flows", "A/B the PnR settings", "did the new tool version help", "benchmark PPA", or "is this comparison fair".
---

# PPA Benchmark

## The boundary this skill lives inside

This skill produces a **structured comparison plan and an evidence-linked
report of what was run**. It never scores the arms and it never names a winner.
The score comes from `_ppa/benchmark.py` per `docs/PPA_INTERFACES.md` §4, which
reads the same canonical records and is the only thing allowed to rank them.

The separation exists because the party that designs a comparison is the party
best placed to design it in favour of an answer, usually without meaning to. A
skill that both sets the arms and declares the winner has no step at which that
can be noticed. Splitting them means the arm definition is an artefact that can
be read back and disagreed with before the number exists.

So the deliverable's hardest section is not the results. It is
`Known unfairness:` — the list of ways the comparison is still not apples to
apples. An empty list there is a claim, and it is written `NONE_KNOWN`, never
left blank.

## When to use

Trigger when the user:
- Wants to know whether a tool version, flow setting or RTL variant helped
- Is choosing between configurations and needs a defensible comparison
- Suspects an earlier comparison was unfair and wants it restated
- Needs arm definitions a scorer program can consume

## Inputs to gather

1. The arms: what differs between them, in exactly one dimension per arm if possible
2. What is held constant: RTL revision, PDK, SDC, seed, machine, tool container
3. The metrics that decide the comparison, and their scope
4. How many runs per arm — one run of a stochastic flow is a sample, not a result
5. Whether the arms were run on the same host under the same load

## Workflow

1. **Write the arms down before running anything.** An arm added after the
   results are in is a different experiment; if one is added, say so and restate
   the whole comparison rather than appending a row.
2. **Fix the held-constant set explicitly.** Name the RTL hash, the PDK, the SDC
   hash. "Same design" is not a fairness condition; a hash is.
3. **Declare the seed policy.** A flow with a random seed compared across one run
   per arm measures the seed. State runs-per-arm and whether the seed is fixed.
4. **Match the scope across arms.** Arms whose numbers come from different
   stages, corners or activity bases are not comparable, and the comparison is
   `UNDETERMINED` rather than close.
5. **Record load and wall clock beside every timing number.** A runtime measured
   on a loaded host is a measurement of the host. If load was not recorded, that
   metric is `NOT_MEASURED`, not an approximate figure.
6. **List the residual unfairness.** Everything you could not equalize goes in
   `Known unfairness:`. This is the section a reader uses to decide how much of
   the eventual score to believe.
7. **Hand the records to the scorer.** Name it, and stop there.

## Do not

- Do not name a winner, rank the arms, or describe one arm as better. That is
  the scorer's output.
- Do not compare arms whose metric scope differs, and do not normalize across a
  scope difference to make them comparable — the normalization is the assumption
  under test.
- Do not drop an arm that produced no result. An arm that crashed is a result:
  it is `NOT_MEASURED` with a reason, and removing it silently makes the
  surviving arms look uniformly successful.
- Do not report a benchmark number obtained by special-casing the benchmark. A
  configuration that is only used when the design is recognized as the benchmark
  is not a flow improvement; it is a measurement of the recognizer.
- Do not leave `Known unfairness:` blank. Write `NONE_KNOWN` and mean it.

## Output format

The deliverable is one markdown report. The template below is the whole shape.

    # PPA Benchmark — <question being asked>

    Verdict authority: _ppa/benchmark.py - this report ranks nothing.
    Independent scorer: _ppa/benchmark.py

    ## Summary
    <what differs between the arms and what the comparison can and cannot settle>

    Fairness conditions: identical RTL sha256:3f9a1c7d, identical PDK gf180mcuD,
    identical SDC sha256:b204e8a1, fixed seed 7, 3 runs per arm, same host
    Known unfairness: arm B ran on an extracted netlist and arm A did not

    ## Arms

    ### A — baseline
    arm_id: baseline-default
    Differs by: nothing; this is the reference
    Runs: 3

    ### B — raised routing effort
    arm_id: route-effort-high
    Differs by: routing effort medium -> high
    Runs: 3

    ## Results per arm

    | arm_id | metric | status | value | unit | scope | source sha256 |
    |---|---|---|---|---|---|---|
    | baseline-default | area.core_um2 | MEASURED | 118420 | um2 | post_route | sha256:77c1de40 |
    | route-effort-high | area.core_um2 | NOT_MEASURED | - | - | post_route | - |

    ## Evidence

    | artefact | sha256 | tool |
    |---|---|---|
    | runs/A/reports/route.rpt | sha256:0a5b93f6 | openroad |

    Next: run /ppa-diagnose

Arm results travel as canonical records, one per cell of the table:

```json
{
  "schema": "vibeic.ppa.metric.v1",
  "metric": "area.core_um2",
  "status": "MEASURED",
  "value": 118420.0,
  "unit": "um2",
  "scope": {"stage": "post_route", "mode": "functional", "arm_id": "baseline-default"},
  "source": {"path": "runs/A/reports/route.rpt", "sha256": "sha256:e61d2c88",
             "tool": "openroad", "parser": "ppa_metric_extract.py"}
}
```

Serialize with `programs/_ppa/canonical_json.py` and nothing else.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/ppa-benchmark/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed, exit 2 =
the checker could not read one of its own inputs and reached no conclusion.

**Your task is not complete until the audit returns PASS.**
