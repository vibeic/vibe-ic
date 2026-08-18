# Open-platform enhancement plan

Derived from four source studies read at pinned revisions, all in this directory:

| study | read at | file |
|---|---|---|
| OpenROAD / ORFS | binary `26Q3-1392-g3bf15a279a`, ORFS `c9c22caf` | `LEARN_FROM_OPENROAD_GAPS.md` |
| LibreLane | `bf8cc13c` (3.0.10) | `librelane_gap_list.md` |
| wafer.space precheck | `ghcr.io/wafer-space/gf180mcu-precheck:main`, RUN against our published GDS | `2026-08-19-wafer-space-precheck-gap-analysis.md` |
| deepseek-harness | `99f6f02fe` (dsh-0.1.0-rc.7) | `2026-08-19-deepseek-harness-source-study.md` |

Nothing below is a survey finding. Every item names a file:line on one side and a
file:line — or an absence, searched and stated — on ours.

---

## The thesis

**Four independent studies found one defect wearing four costumes: the evidence
is produced, and then nothing refuses on it.**

- OpenROAD §1 — we generate the post-layout equivalence proof and do not enforce it.
- OpenROAD §2 — the placer returns its own legality verdict; we catch it and
  demote it to a warning.
- LibreLane GAP 1 — Magic writes its extraction complaints to `feedback.txt`;
  we read the commands we sent, never the complaints that came back.
- wafer.space — an external, non-self-defined refusal exists and is free to run;
  we have never run it.

A second, thinner thread runs underneath: **we test a proxy where the property is
available.** `placement_legality_check.py` tests a DEF *status field* rather than
legality. `checker_execution_wiring_audit` counted a *name in a sentence* as an
execution path (#1347, fixed). 61 of 62 gate-carrying steps *re-parse prose*
where the tool would hand us the number (`step_metrics.py` says so itself).

The plan is ordered by consequence on silicon, not by effort.

---

## W1 — BE SUBMITTABLE  (P0 — today we are not)

**Evidence.** The wafer.space precheck was RUN, offline (`--network=none`),
against `benchmark-data/ic/spm/…/chip_top.gds` (sha256 `fb08d9ed…`). It
**failed at stage 3 of 16**; stages 4–16 never executed.

```
Stage 1  Read the Layout        OK
Stage 2  Check Top-Level Name   PASS
Stage 3  Check Slot Size        FAIL, exit 255
         [Error]: Layer 'GUARD_RING_MK' is not used.
```

Four independent refusals, none of which any gate of ours can currently raise:

| refusal | their check | ours |
|---|---|---|
| seal ring `GUARD_RING_MK` (167/5) absent | `check_size.py:65-74` | **absent** — two programs mention "guard ring"; one screens *cells* for latch-up, one parses the *words* "no seal ring". Neither examines a layout. |
| die size ≠ slot size | `check_size.py:100-109` | absent |
| Pad layer (37/0) absent | `check_mask.drc:14` | absent |
| 4 ID cells absent | `generate_id.py:50-64` | absent |

**Build.** `tapeout_readiness_check` — a gate that RUNS the shuttle's own
precheck container against the artefact we are about to publish, and fails the
run on its exit code. Not a reimplementation of their rules: their container is
the authority, and reimplementing it would recreate exactly the "our own bar"
problem this workstream exists to remove.

**This also closes #1744**, whose defect is that `mpw_precheck` still targets a
shuttle that stopped operating in 2025 — our only external refusal interface
points at nothing.

**Acceptance.** The gate fails on today's `chip_top.gds` with the four refusals
named, and passes only after all four are fixed. Revert the gate, watch a
known-bad GDS pass, restore it.

**Why first.** The other workstreams make us *better*. This one makes us
*submittable*, and it hands us a pass bar we did not write ourselves — the thing
a self-checking platform can never generate for itself.

---

## W2 — ENFORCE THE PROOFS WE ALREADY PRODUCE  (P0/P1)

Three items. Each costs almost nothing to build, because the evidence already
exists and is already computed; what is missing is the refusal.

### W2.1 — post-layout equivalence must be fatal (DEAD DIE)

ORFS runs `run_lec_test` after `repair_timing` mutates the netlist inside CTS,
and the stage DIES on a difference (`flow/scripts/lec_check.tcl:60`). Our
`lec_post_layout_check.py` is *stronger than theirs* — it treats a VACUOUS or
UNPROVEN proof as a FAIL — and it is not wired to abort the flow.

**Acceptance.** A netlist-changing repair cannot leave the stage. Prove by
mutating the netlist post-CTS and watching the stage die.

### W2.2 — the placer's own legality verdict must not be demoted (DEAD DIE)

`check_placement` without `-no_abort` raises DPL-33 on a non-zero violation
count, so "an illegal placement can never be mistaken for a legal one by a caller
that ignores the result". We call it and demote the result to a WARN, and our
own `placement_legality_check.py` tests the DEF STATUS FIELD instead — it cannot
see off-site placement, row overlap, or an off-grid instance.

**Acceptance.** Plant an overlapping instance; today's gate passes it; the fixed
gate fails it with the tool's own violation count.

### W2.3 — read the extraction tool's error channel (DEAD CHIP with a clean report)

LibreLane counts `Illegal overlap` out of Magic's `feedback.txt`, publishes it as
`magic__illegal_overlap__count`, and gates it at threshold 0 between
`SpiceExtraction` and `LVS`. Searched our whole plugin for
`illegal.{0,3}overlap`: **0 files**. `magic_extract_spice_emit.py` validates that
the TCL we send *contains* `extract all` — the command, never the complaint that
came back.

**Acceptance.** An extraction that produced illegal overlaps must not be able to
reach a clean signoff report.

---

## W3 — MEASURE, DO NOT RE-PARSE PROSE  (P1 — the substrate under every number)

Every ORFS stage runs through one 21-line wrapper with `-metrics`
(`flow/scripts/flow.sh:15`); `checkMetadata.py` then compares NAMED quantities
against the design's rules. **The number that is gated is the number the tool
computed.**

Our `step_metrics.py` is an explicit adoption of that idea and states its own
coverage in its docstring: it wires **one** gate as a worked example, and **the
other 61 gate-carrying steps do not emit**. `grep -n '\-metrics '` across
`phase3_one_shot_runner.py` and `mcp-eda/`: no call site. We never ask the tool
for its numbers; we read its prose afterwards.

This is why it is the substrate: a log-format change silently blinds a check,
and the check reports PASS while blind.

**Build.** Route `-metrics` through the one-shot runner; migrate the 61 steps to
consume named metrics; keep the prose parser only as a cross-check that must
AGREE, and fail on disagreement rather than preferring either.

**Acceptance.** Change a tool's log wording in a fixture. Today: the gate still
passes. After: the gate is unaffected, because it reads the metric — and a
deliberately disagreeing pair fails.

---

## W4 — NOTHING TO CHECK IS A FAILURE  (P1)

`util/checkMetadata.py:49-51` — an empty rule set is `sys.exit(1)`; a rule whose
metric is absent is `[ERROR] Value not found` + `sys.exit(1)`. This also catches
a SKIPped stage: `SKIP_DETAILED_ROUTE=1` still produces a GDS and `make finish`
still succeeds, but the missing `detailedroute__route__drc_errors` fails
`make metadata-check`.

Our idiom is the opposite: `optional_program_exit_zero`.

This is the same family as the two defects this repo already fixed by hand —
`no tests ran` read as zero failures (#1705, an absent ratchet baseline is NOT
CHECKED, never a measurement of zero) — and it is still the default elsewhere.

**Build.** An empty corpus, an absent metric, and a skipped stage each become a
FAIL by default across the gate dispatcher; any genuine exemption must be
declared per-gate with a reason string, and the declaration itself gated.

**Acceptance.** Empty every corpus in a scratch tree. Today: green. After: red,
naming which corpus was empty.

---

## W5 — A SIGNOFF THAT CANNOT BE REPRODUCED IS NOT A SIGNOFF  (P2)

LibreLane GAP 5: the PDK revision a run signed off against is never recorded, so
a signoff cannot be re-derived later. Ours has the same hole.

**Build.** Stamp the resolved PDK revision (and the tool digests already
available) into the run manifest, and gate on its presence.

**Acceptance.** A run whose manifest lacks a resolved PDK revision cannot publish.

---

## W6 — THE PUBLISHED NUMBERS MUST NOT BE FORGEABLE  (P0 for credibility)

Filed as **#1745**, measured, not argued: in `sv-iv-analyze:284-299` the
`no_mismatch` flag is latched and never cleared, and the DUT shares the
simulator's stdout. Two samples with **identical wrong logic** scored 50%,
because the second printed `Mismatches: 0 in 20 samples` itself. The simulator
said `Mismatches: 20 in 20` for both.

The honest-wrong control FAILS, so the check is not vacuous — it is
**forgeable**, which is worse: it discriminates correctly until someone forges,
and a forgeable PASS is indistinguishable from a real one in the published table.

Second defect in the same issue: never-attempted problems leave the
DENOMINATOR. One real pass plus three unattempted reported `pass_rate 50.00`
over a denominator of 1, with no row and no warning.

**Build.** (a) refuse any submitted RTL that contains the harness's own verdict
tokens, before scoring; (b) restore the third state — attempted-and-passed,
attempted-and-failed, **never-attempted** — and never let never-attempted drop
out of the denominator silently.

**Acceptance.** The forged sample is refused; the unattempted set appears in the
denominator with its own row.

---

## W7 — INVARIANTS LIVE NEXT TO THE CODE THEY CONSTRAIN  (P3)

deepseek-harness verdict, counted in the clone: 54 top-level packages, 226 leaf
packages, **219 `invariant.ts` files**. We are **AHEAD on enforcement** — our
gates are stronger and adversarially tested — and **BEHIND on locality**: our
rules live centrally, so a contributor editing a module cannot see the rule that
binds it without going somewhere else.

We are also BEHIND on one property of their session log: append-only with replay
and fork, so an interrupted turn can be repaired rather than restarted. We are
AHEAD on scope/permission primitives and on sandboxing.

**Build.** A per-package invariant file, enforced by the existing gates, so the
rule sits where the code that must obey it sits. Adopt the append-only/replayable
run log for long campaigns.

---

## Order, and what it buys

| | workstream | class | buys |
|---|---|---|---|
| 1 | W1 submittable | blocking | we can send a chip at all, against a bar we did not write |
| 2 | W2 enforce existing proofs | DEAD DIE ×3 | three ways a dead die currently reaches signoff |
| 3 | W6 unforgeable numbers | credibility | every number we publish through that path |
| 4 | W4 nothing-to-check fails | false-clean | removes the whole false-green family |
| 5 | W3 measure not parse | substrate | makes W2/W4 durable instead of prose-dependent |
| 6 | W5 reproducible signoff | ships-late | a signoff that survives being questioned |
| 7 | W7 invariant locality | quality | contributors see the rule where they break it |

W1 and W2 are the only ones that change whether a chip lives. W3 is the one that
decides whether the rest keeps working next quarter.

---

## The honest caveat

Three of these four studies are gap lists against upstream projects. Each study
also recorded where **upstream is worse than us** and where **upstream checks
cannot fail** — those sections exist in each file and were not cherry-picked
away. Adopt selectively: the point is not that they are better, it is that four
independent readings found the same shape of hole in us, and that shape has a
name.
