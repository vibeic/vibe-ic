---
name: ppa-diagnose
description: Explain why a PPA number is where it is — which paths, cells, nets or flow decisions account for a timing, power or area result — starting from what the deterministic diagnosis already found and adding only falsifiable hypotheses on top. Use when the user says "why is timing failing", "where is the area going", "what is burning the power", "diagnose this PPA result", or when a closure loop needs a reason before it needs a candidate.
---

# PPA Diagnose

## The boundary this skill lives inside

This skill produces an **evidence-linked report of causes and falsifiable
hypotheses**. It never produces a gate verdict and it never decides what to do
about what it finds. Program-First is not a style here: the deterministic
diagnosis in `_ppa/agent_router.py` runs first, its output is quoted with its
exit code, and this skill starts where that program stopped.

The reason for that order is measured, repeatedly, in this repository: a model
asked to explain a failure will produce an explanation whether or not it has the
evidence, and the explanation is fluent either way. Anchoring to the program's
output makes the boundary between "the parser found this" and "I inferred this"
visible in the document itself, which is the only place a later reader can check
it.

A hypothesis that no artefact could refute is not a hypothesis. Each one in the
report names the observation that would kill it.

## When to use

Trigger when the user:
- Has a PPA number they did not expect and wants the cause
- Is about to spend tool iterations and wants a reason to aim them
- Has a `_ppa/feasibility.py` refusal and wants to know what drove it
- Needs the input `ppa-optimize` turns into actuator candidates

## Inputs to gather

1. The metric in question, with its full scope, from `ppa-measure`
2. The deterministic diagnosis: which program was run, its exit code, its output
3. The detail artefacts the program read — path reports, cell histograms, net
   reports, congestion maps, activity files
4. What changed since the last known-good run, if anything
5. Which parts of the design are off limits to change

## Workflow

1. **Run the program first and quote it.** `Program-first: <program> rc=<n>`,
   then its findings, before anything you inferred. If the program could not run,
   say so on that line — an absent diagnosis and a clean diagnosis are different
   facts and this report must not print them the same way.
2. **Separate observation from inference, physically.** `## Program-first
   findings` holds what was parsed. `## Hypotheses` holds what you concluded.
   A reader must be able to delete the second section and still have a true
   document.
3. **Make each hypothesis refutable.** State the observation that would kill it
   and the artefact that observation lives in. "Congestion in region X is driving
   the detour" is refutable by a congestion map; "the tool made a bad choice" is not.
4. **Rank by evidence, not by plausibility.** The hypothesis with the most direct
   artefact support goes first, even when a different one is more interesting.
5. **Say what you could not settle.** `## Residual questions` is not optional
   padding: an empty one is a claim that the evidence was sufficient, and that
   claim is usually false.
6. **Hand off explicitly.** Name the next skill and what you are handing it.
   An implicit escalation is how a diagnosis becomes an action nobody approved.

## Do not

- Do not skip the program and diagnose from the artefacts directly. The program's
  output is the anchor; without it this report has no falsifiable half.
- Do not present a hypothesis in the same section as a parsed finding, and do not
  round an inference up into an observation by attaching a number to it.
- Do not recommend an actuator move here. That is `ppa-optimize`, and it needs
  the rollback and remeasurement fields this report does not carry.
- Do not report a cause you could not see the artefact for. "I could not read it"
  and "I read it and found nothing" must print differently.
- Do not treat an exit code of 2 as a clean result. It means the program reached
  no conclusion, and a diagnosis built on it inherits that.

## Output format

The deliverable is one markdown report. The template below is the whole shape.

    # PPA Diagnosis — <metric> on <design>

    Verdict authority: _ppa/feasibility.py - this report states no pass/fail of its own.

    ## Summary
    <the metric, its scope, and the leading evidenced cause>

    Program-first: _ppa/agent_router.py rc=2

    ## Program-first findings

    | finding | artefact | sha256 |
    |---|---|---|
    | 12 of 14 failing endpoints share net <n> | sta/paths.rpt | sha256:3f9a1c7d |

    rc=2 means the router reached no conclusion on the remaining 2 endpoints;
    they are carried into Residual questions below rather than assumed clean.

    ## Hypotheses

    ### H1 — the shared net is a high-fanout clock-enable
    Evidence: 12 of 14 endpoints share it; fanout 214 in <artefact>
    Refuted by: a fanout report showing fanout below the buffering threshold
    Confidence basis: direct artefact support, no inference step

    ### H2 — congestion in region <r> forces detours on those paths
    Evidence: detour ratio 1.8 on 9 of the 12, from <artefact>
    Refuted by: a congestion map showing that region below the utilization limit

    ## Residual questions

    | question | why it is unresolved |
    |---|---|
    | what drives the other 2 endpoints | router exited 2; no path detail was produced |

    ## Evidence

    | artefact | sha256 | tool |
    |---|---|---|
    | phase3/stage3/sta/paths.rpt | sha256:b204e8a1 | opensta |

    Handoff: /ppa-optimize, carrying H1 as the actuator candidate and H2 as the
    fallback if the H1 remeasurement refutes it

    Next: run /ppa-optimize

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/ppa-diagnose/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed, exit 2 =
the checker could not read one of its own inputs and reached no conclusion.

**Your task is not complete until the audit returns PASS.**
