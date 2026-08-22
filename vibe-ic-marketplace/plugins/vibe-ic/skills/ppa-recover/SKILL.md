---
name: ppa-recover
description: Propose a bounded way out when a PPA closure loop has stalled, oscillated, regressed or crashed — naming the rollback point, the blast radius, and the condition under which recovery stops rather than looping. Use when the user says "the loop is stuck", "PnR keeps getting worse", "we regressed", "roll this back", "recover the run", or when a closure controller has exhausted its budget without converging.
---

# PPA Recover

## The boundary this skill lives inside

This skill produces a **structured recovery proposal**. It never produces a gate
verdict and it never performs the recovery. The controller that actuates is
`_ppa/closure.py` per `docs/PPA_INTERFACES.md` §4; this document is what it reads
before deciding whether to act.

The distinction matters most exactly here, because a stalled loop is the moment
at which the temptation to "just fix it" is strongest and the evidence is
weakest. A recovery that is proposed, bounded and reversible can be refused. A
recovery that is performed and then described cannot.

## When to use

Trigger when the user:
- Has a closure loop that stopped improving, or started getting worse
- Has a run that crashed part-way and needs to know what state it is in
- Has exhausted an iteration budget without meeting the target
- Suspects the loop is oscillating between two configurations

## Inputs to gather

1. The loop history: per round, the actuator moved and the metric that resulted
2. The run manifest for each round, so a rollback point can be named by hash
3. The failure mode as observed, not as interpreted — stall, oscillation,
   monotonic regression, crash, or budget exhaustion
4. What has already been rolled back, if anything
5. The remaining budget, and whether the caller is willing to spend it

## Workflow

1. **Classify the failure by its signature, not by its cause.** A stall (no
   change across N rounds), an oscillation (alternating between two states), a
   regression (monotonic worsening) and a crash need different recoveries, and
   the signature is readable from the loop history without a theory.
2. **Name the rollback point by hash.** "Before the last change" is not a state;
   a run-manifest sha256 is. If no manifest exists for the state you want to
   return to, that state is not reachable and the proposal says so instead of
   implying otherwise.
3. **State the blast radius.** Exactly what the recovery touches, and what it
   leaves alone. A recovery that quietly reaches into the RTL when the caller
   believed it was PnR-only is worse than no recovery.
4. **Give the loop a stop condition.** Not a retry count alone — a condition that
   is checkable from the metric history, so the loop can end without a human
   noticing it is still going. A recovery with no stop condition is a second
   stalled loop wearing the first one's clothes.
5. **Prefer returning to a known state over reaching a new one.** The purpose of
   recovery is to make the design reachable again, not to close it. Closure is
   `ppa-optimize`, afterwards, from solid ground.
6. **Preserve the failed evidence.** The artefacts from the failing rounds are
   what the next diagnosis reads. A recovery that overwrites them has destroyed
   the reason the loop stalled.

## Do not

- Do not hand-edit a layout, delete violating geometry, move pins by hand or
  relax a rule deck to get out of a stall. A state reached that way is worth less
  than the failure it replaced, and it is unreachable by any later re-run.
- Do not propose a recovery whose rollback point does not exist. Say the state is
  unreachable; that is a real finding about the run.
- Do not delete or overwrite the artefacts of the failing rounds.
- Do not describe the recovery as already applied, and do not report a metric for
  a state that has not been remeasured.
- Do not raise a budget as the recovery. A loop that stalled at 6 iterations
  usually stalls at 12; the stall is a finding, not a resourcing problem.
- Do not treat a crash as a stall. A crash means the state is unknown, and an
  unknown state is recovered by returning to a known one, not by continuing.

## Output format

The deliverable is one markdown proposal. The template below is the whole shape.

    # PPA Recovery Proposal — <design>, round <n>

    Verdict authority: _ppa/closure.py - this proposal states no pass/fail of its own.

    ## Summary
    <what the loop was doing, when it stopped being useful, and what state it is in now>

    ## Failure signature

    | round | actuator moved | timing.setup.wns_ns | area.core_um2 | manifest sha256 |
    |---|---|---|---|---|
    | 3 | density 0.62 -> 0.60 | -0.124 | 118420 | sha256:77c1de40 |
    | 4 | density 0.60 -> 0.58 | -0.121 | 119880 | sha256:0a5b93f6 |
    | 5 | density 0.58 -> 0.60 | -0.124 | 118420 | sha256:e61d2c88 |

    Classification: oscillation between rounds 3 and 5, period 2, no net movement

    ## Recovery proposal

    Rollback point: run manifest sha256:3f9a1c7d - the end of round 3, the last
    state whose artefacts are complete
    Blast radius: PnR configuration only; RTL, SDC and PDK untouched
    Stop condition: 2 consecutive rounds with no improvement beyond 0.005 ns, or
    the remaining 3-iteration budget is spent, whichever comes first
    Preserves: rounds 3-5 artefacts are retained under runs/round<N>/ and are not
    overwritten by the recovery

    ## What this does not fix
    <the underlying cause is not addressed here; name what still has to be diagnosed>

    ## Evidence

    | artefact | sha256 | tool |
    |---|---|---|
    | runs/round5/manifest.json | sha256:b204e8a1 | closure controller |

    Next: run /ppa-diagnose

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/ppa-recover/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed, exit 2 =
the checker could not read one of its own inputs and reached no conclusion.

**Your task is not complete until the audit returns PASS.**
