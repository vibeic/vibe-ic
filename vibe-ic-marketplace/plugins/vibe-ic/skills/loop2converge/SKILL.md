---
name: loop2converge
description: >-
  The closed convergence loop for ANY benchmark subject — open-benchmark Evaluation,
  benchmark IC (doc→GDS), or IP-cell (doc→LEF/GDS). RUN the canonical front door,
  CLASSIFY every FAIL as flow / gate / tool, CONVERGE it by fixing the layer that owns
  it, PROVE the fix in the plugin cache against the real artefacts BEFORE promoting it,
  then CAPTURE it as a PR to the repo that owns the layer (vibe-ic plugin, or the
  vibeic-eda fork). Use when: "converge the benchmark", "make spm pass", "loop2converge",
  "why did the benchmark fail", "run benchmark and fix it", "把 benchmark 收斂", "讓它
  pass", "benchmark 跑完有 fail 要修", or after ANY /vibe-ic-all or /vibe-ic-benchmark
  run that did not reach its target. Complements `benchmark-enhancement-capture` (which
  routes a recovery to the right file) by owning the OUTER loop: run → classify →
  converge → prove → PR → re-run.
---

# loop2converge — run, classify, converge, prove, capture, re-run

The loop exists because a benchmark number that nobody converged is a number nobody
learns from, and a fix that never leaves a cache is a fix that dies with the session.

    ┌─ 1 RUN ─────► 2 CLASSIFY ─────► 3 CONVERGE ─────► 4 PROVE ─────► 5 CAPTURE ─┐
    │  canonical      flow / gate       fix the layer     in the CACHE   PR to the │
    │  front door     / tool            that OWNS it      first          owning repo│
    └──────────────────────── 6 RE-RUN, and repeat until the target ───────────────┘

The loop is CLOSED: step 6 re-enters step 1 on the upgraded plugin. It terminates on
the subject's own target, never on "we ran out of findings".

---

## 1 — RUN, through the ONE front door

### 1.0 — Upgrade FIRST, and prove the upgrade took

**Before any run: upgrade the vibe-ic plugin AND the vibeic-eda MCP to the newest
version, then prove BOTH are actually serving it.** This is step ZERO of every tick,
including the re-entry from step 6 — a loop that converges against last tick's binaries
is measuring a tree that no longer exists, and its findings are re-discoveries of things
already fixed.

    /plugin update vibe-ic          # plugin: pull the newest marketplace version
    docker pull <vibeic-eda image>  # tool:   pull the newest fork image
    # then, and this is the part that is skipped:
    eda_doctor                      # ask the SERVER what it is serving

**An install is not a binding.** MEASURED 2026-08-29: the plugin was upgraded to
1.12.51 and `eda_doctor` still reported `plugin_programs_dir: …/1.11.94/programs`. An
MCP server keeps serving the version it BOOTED with; nothing about `plugin update`
reaches an already-running server. Every finding produced in that window described
1.11.94 while the report said 1.12.51.

So the upgrade is not complete until you have READ BACK, from the running server, that
it is serving the version you installed:

| what to read back | says what |
|---|---|
| `eda_doctor` → `plugin_programs_dir` | which plugin version the MCP will actually execute |
| `eda_doctor` → the EDA image digest/label | which fork build the tools come from |
| the plugin's own version in the run's report | what the flow believes it is |

If `plugin_programs_dir` names an older version, the fix is a **session restart** so the
MCP re-registers — not a re-run, and never a hand-edit of the cache to make the numbers
agree. Record the three read-back values in the tick's report; a tick that cannot name
the versions it ran did not measure anything nameable.

**Never edit the installed cache to carry a fix into a run.** The cache is where a fix
is PROVEN (step 4), never where it LIVES. A cache edit that reaches a run makes the
number describe a tree that exists on exactly one machine.

### 1.1 — The entry itself

There is exactly one entry, whatever the subject is. Do not hand-roll a harness; that
is how a benchmark number stops measuring the product (see `open-benchmark-methodology`
RULE 0).

| subject | entry | target |
|---|---|---|
| benchmark IC (doc→GDS) | `/vibe-ic-all <project> --pdk <pdk> --ic-name <ic>` | `flow_compliance_check` exit 0 |
| IP-cell (doc→LEF) | same runner, IP route | LEF + GDS emitted, the 37.5 gate reached |
| open benchmark | `/vibe-ic-benchmark <bench>` | the highest HONEST pass@1 |

Stage the INPUT ONLY. §4.05: the design documents and nothing else — no oracle, no
golden, no prior run's results. A staging that carries a result is not a clean run and
its number means nothing.

**Long runs must survive your turn.** `setsid nohup … &` with a done-file, then poll.
A turn that ends takes the run's reader with it and the deliverable is never written.

**The run holds a lock.** A second invocation answering `CONCURRENT_RUN_REFUSED` is the
runner protecting you, not an obstacle. Never remove a lock whose holder pid is alive.

---

## 2 — CLASSIFY every FAIL: flow, gate, or tool

**Do this before touching anything.** The three have different owners, different fixes,
and different repos, and the cost of guessing is a fix in the wrong layer that the next
run re-breaks.

| class | what it looks like | who owns it |
|---|---|---|
| **FLOW** | a step is ordered, declared or gated wrongly; a dependency edge states order but not data; a record is written where a later verdict can pre-empt it | `flow/phase1_phase2_phase3.yaml` + the runner |
| **GATE** | the checker's verdict does not follow from its evidence; it reads a superseded number; it renders a capability gap as a defect in the subject; it cannot reach its own refusal | `programs/*_check.py` |
| **TOOL** | the EDA binary itself is wrong, crashed, or was fed the wrong inputs | the **vibeic-eda fork** — a DIFFERENT repo, a DIFFERENT PR |

### The classification is not obvious, and here is how it goes wrong

**A cascade is not a root cause.** Count the blast radius from the code, not from the
report. MEASURED 2026-08-29: five FAILs were attributed to one upstream FAIL, and the
attribution was refuted structurally — the voiding branch only rewrites a step already
`PASS`, so it can never write `FAIL` or `MISSING`. The five were three independent
facts. *Before* declaring a cascade, find the line that would have to write the
downstream status and check that it can.

**A tool crash is not a graded result.** MEASURED: an at-speed ATPG died two seconds
into a 1995-second budget (`ERROR: No SAT model available for cell …`) because
gate-levelisation read the wrong PDK's Liberty — and the gate rendered that as
`TDF test-coverage 0.0% < floor 90.0%`. "The tool aborted" and "this design scores 0%"
are different facts and only one is about the design. Corrected, the same netlist
measured **100.0%**. Whenever a coverage, count or percentage is 0 or 1, ask what the
population was before you believe the number.

**A missing record is not missing work.** MEASURED: spare cells were inserted, tied off
and FIRM-locked at `pnr.tcl:442`, ~200 lines before routing — but the RECORD is written
by Python at the tail of the same step, with thirteen early returns between the plan and
the emit. The run took one. Step 18 was the only step in the band whose evidence is
100% Python-tail-written; every other step keeps a TCL-written DEF that the tool lands
regardless. **A step's evidence must not be hostage to a later step's verdict.**

**The tool may adjudicate its own numbers — read it.** MEASURED: OpenROAD publishes a
routing-loop count AND a post-route verification count, and says in the same log which
one ships (`[WARNING DRT-0701] … The published result is the verified one`). Nothing
parsed that line, so the reader took the superseded number, the metric and the prose
disagreed, and the step failed on the disagreement. One unparsed line, four reds.

**A refusal you cannot satisfy in either direction is a defect in the refusal.**
MEASURED: a ledger returned `expired` when its gates FAILed and `stale` when they
PASSed — no tree satisfied it. When a check has no reachable green, fix the check.

---

## 3 — CONVERGE: pick the disposition the evidence supports

Exactly four outcomes. Choose by evidence, never by what is least work, and write down
what would change your mind.

* **FIX_PLUGIN** — a real defect. Name the file, the line, the new behaviour, and what
  makes it chip-AGNOSTIC. A fix that only works for this design is not a fix.
* **FIX_TOOL** — the defect is in the forked EDA tool. It goes to the **vibeic-eda**
  repo as its own PR. Never paper over a tool bug downstream in the plugin.
* **DECLARE_NA** — genuinely does not apply to this route/PDK, and the flow should SAY
  so rather than fail. Quote the yaml clause and state the N/A predicate.
* **WAIVE_EVIDENCE** — it applies but cannot run here. Name the missing capability, and
  carry evidence + ticket id + `review_required: true`. **A waiver missing any of those
  is fabrication with paperwork.**
* **REFUSE** — you cannot honestly reach any of the above. This is a SUCCESS. Say why.

### What convergence NEVER means

Never fabricate an artefact the flow was meant to produce. Never author a coverage
number. Never relax a rule deck, hand-edit a GDS, move a pin, or delete a spare/ECO
cell. Never `--write-baseline` on a hygiene gate, *including when the gate asks*. Never
narrow a gate's population so it stops finding things. Never declare a data dependency
that does not exist — MEASURED, that would flip an honest `MISSING` into
`DEFERRED-BY-UPSTREAM` and **manufacture an excuse for work that was actually done**,
which is the same family of offence as fabricating the artefact.

---

## 4 — PROVE IT IN THE CACHE, before the repo

This is the step that makes the loop trustworthy, and it is the one most often skipped.

1. Patch the **installed plugin cache** (`~/.claude/plugins/cache/.../<version>/`).
2. Run the fixed code against **the real artefacts of the failed run** — the actual log,
   the actual metrics JSON, the actual netlist. A synthetic fixture proves the fix
   handles your idea of the input, not the input.
3. **Confirm the cache's base is byte-identical to `main`** before believing the result.
   Otherwise you measured something that is not what will land.
4. **Falsify in both directions.** Remove the fix: the failure must return *with the same
   message*. Restore: green. A fix whose absence does not reappear is not a fix.
5. **Ship a CONTROL that stays green both ways** — an input the fix must NOT change.
   Without one, the fix is satisfied by code that rewrites every input's answer.
6. Assert the **exact** exit code. Never `rc != 0`: a check demoted from rc 1 to rc 2
   once passed 362 tests that asserted `!= 0`.

Then measure **two arms** — the candidate and pristine `main` — on a module list
**pinned once** and used unchanged on both. Re-deriving the list per tree is what makes
an A/B meaningless: a list derived from the candidate names files absent on main and
pytest answers `rc 4, no tests ran`. Compute new-red as a set difference **by node id in
Python**, never with `comm`.

### Say plainly what the fix does NOT do

A plugin fix takes effect on the **next** run. It does not change the verdict of the run
that found it, and an operator who expects the existing report to improve is one step
from hand-patching artefacts. MEASURED: reconciling the two DRC readings moved pnr from
`ROUTE_DRC_METRIC_DISAGREEMENT` to `ROUTE_NOT_CONVERGED` — **still FAIL**, but now about
the design instead of about a parser. That is the honest outcome and it is the point.

---

## 5 — CAPTURE: a PR to the repo that owns the layer

| the fix is in | repo | note |
|---|---|---|
| a program, gate, flow yaml, skill or command | **vibe-ic** | version bump + regenerate the inventory |
| an EDA binary or its packaging | **vibeic-eda fork** | never a plugin-side band-aid |

The PR body carries, at minimum: what was **measured** (real numbers), **why this side
is wrong** rather than the other, the **falsification in both directions**, both arms'
counts, and an explicit **"WHAT THIS DOES NOT DO"**.

Record refusals too. A disposition you considered and rejected belongs in the body —
the next reader will reach for it, and the reason it was wrong is the expensive part.

If the inventory gate refuses the push (`gen_program_inventory.py --check` rc 1), that
is the gate working. Regenerate, correct the counts it names by file and line, and say
so in the body. Adding one file makes every place that states a count stale.

Then route the recovery through **`benchmark-enhancement-capture`** so it lands in the
right program/skill and the next blind run auto-recovers it.

---

## 6 — RE-RUN, and the termination rule

Upgrade the plugin (and the EDA image if that was the layer), **restart the session so
the MCP re-registers** — MEASURED: an MCP server keeps serving the plugin version it
booted with, so an un-restarted session measures the OLD plugin while reporting the new
version — then re-run the same subject from a clean staging.

**Terminate on the subject's target, not on effort:**

* benchmark IC — `flow_compliance_check` exit 0, or `PASS_WITH_WAIVERS` where every
  waiver carries evidence + ticket + `review_required: true`
* IP-cell — the LEF/GDS deliverables exist and the 37.5 gate is reached
* open benchmark — the highest pass@1 that survives §4.05 and the tool-substitution
  disclosure

**A run whose FAIL is honest is a converged run.** If the evidence says this subject
cannot reach PASS on this PDK, say so and name exactly what stands in the way. A
truthful `FAIL` naming a real unrepaired violation is worth more than a green nobody
can defend — and it is the only outcome that survives someone checking.

## Summary

Run through the one front door → classify each FAIL as flow / gate / tool → converge by
fixing the layer that owns it → prove it in the cache against real artefacts with a
falsification and a control → PR it to the owning repo → upgrade, restart, re-run.

Next: run `/vibe-ic-all` (or `/vibe-ic-benchmark`) on the subject, then classify every
FAIL per §2 before changing anything.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/loop2converge/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
