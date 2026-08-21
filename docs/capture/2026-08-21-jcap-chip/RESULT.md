# jcap-chip — the CAPTURE loop's third step, run over the chip path, the sign-off producers and the harness

agent `jcap-chip` · 2026-08-21 · branch **`jcap/chip-identity-captures`**, pushed
to `origin`, one commit, cut from `a00f53f20` = `origin/main` = **v1.11.66**.
**No version bump. Nothing pushed to `main`. No baseline written. No gate implemented** —
this pass produces the RECORDS and the emitted sketches; a separate lane builds them.

| | |
|---|---|
| records | `jcap-chip/recoveries.json` — **17** |
| emitted | `jcap-chip/candidates/` — 2 rule-sketch files (13 rules), 2 backlog YAML, 1 forked-tool YAML, 1 discard log, `summary.json` |
| command | `python3 vibe-ic-marketplace/plugins/vibe-ic/programs/enhancement_emit.py --records jcap-chip/recoveries.json --out-dir jcap-chip/candidates` |
| result | accepted on the first run, **0 unrouted**, 13 A-rules routed to 2 program files |

## Count per bucket

| bucket | n | where it went |
|---|--:|---|
| **A** — deterministic rule | **13** | 8 → `programs/phase3_one_shot_runner.py`, 5 → `programs/plugin_change_pytest_gate.py` |
| **T** — fix belongs in the forked tool | **1** | `ORGANIC-20260821-downgraded-abort-has-no-completion-record.yaml` |
| **C** — right bucket, large engineering | **2** | two backlog YAML |
| **D** — honestly discarded | **1** | `bucket_D_discarded.md` |
| **B** — needs natural-language judgment | **0** | none of the 17 needed it; every one reduces to a regex, a structure, or a table lookup |

### The emitter's two refusals are real, so the clean run means something

The brief warns that `enhancement_emit.py` refuses a B/C record with no
`why_not_bucket_a` and a docstring carrying a bare underscore-bearing
identifier. It accepted all 17 first time, which is only evidence if the
refusals actually fire. Both were exercised as negative controls against
mutated copies of my own records:

```
docstring "...must resolve the source_path before writing it."
  -> ValueError: docstring contains a bare underscore-bearing identifier
     ('source_path'); refusing.
the Bucket-C record with why_not_bucket_a deleted
  -> PROGRAM-FIRST GATE FAILED — Bucket B/C downgrades need why_not_bucket_a
```

Both refusals were obeyed rather than worked around: the records were written in
general-pattern language from the start.

---

## THE SEAM: artefact identity

Every source in this cluster is one instance of the same defect. An artefact that
does not say **which design, which stage, which inputs, which limit and which
runtime** it is about can be attributed to any of them — and the honest verdict
for such an artefact is *undetermined*, never a pass. The repo has now measured
this five ways:

1. two designs producing **byte-identical** sign-off report bytes;
2. a power number that **could not move when the design moved**, because the
   session linked the pre-layout netlist while its header claimed post-layout;
3. sign-off timing reports with **no stage stamp at all**, so 48 of 56 rows were
   dropped from the evidence set rather than refused;
4. a checker answering about a **shared tree the caller did not name**, because
   an environment pointer outranked an explicit argument;
5. a test failure charged to the **tree** when it was caused by the **runtime**.

The one rule the brief asks for, stated once: **a produced artefact must carry the
identity of the thing it measured, and a reader that cannot establish that
identity must return an undetermined verdict, never a pass.** The corollary the
originating lane measured and that is captured here as its own record: **an
identity stamp is not a measurement** — an artefact whose stamp is present and
correct and which carries no result is refused *with its binding still reported
true*.

---

## ALREADY-PROGRAM — 15 rules that already exist, and which program enforces each

The skill's own measure is that ~63% of "extractable rules" are already programs.
Here it was higher. **Every row below was verified by me on `origin/main` at
v1.11.66**, not taken from the source write-ups.

| # | the rule the prose describes | the program that already enforces it | state |
|--:|---|---|---|
| 1 | a report-class artefact byte-identical across two different designs is an error | `cross_design_identity_check.py` | **exists, UNWIRED** — listed in `checker_execution_wiring_baseline.json` with the triage note *"unwired for lack of a CALLER, not for lack of an input"*. This is why two published cells' identical reports were only ever caught by a manual sweep. |
| 2 | a produced report names the design and the inputs it measured | `phase3_one_shot_runner._measured_subject` / `_measured_subject_lines` | **landed** — resolves the design plus each input with its hash and byte count |
| 3 | a report that names another design is refused | `eda_report_audit` + `erc_density_check` (`..._IS_ABOUT_ANOTHER_DESIGN`) | **landed** |
| 4 | a report that declares nothing is *undetermined*, not clean | `eda_report_audit.DESIGN_BINDING_NOT_DETERMINED`, `_check_report_design_binding` | **landed** — a third value beside true/false, spelled out |
| 5 | the stage stamp is read by ONE reader and its absence means *undeclared* | `_sta_basis.declared_basis` | **landed** — correct; the gap is entirely producer-side (record A2) |
| 6 | a field a checker READS must have a PRODUCER | `l_doc_field_producer_check.py` | **landed, blocking** — for document fields. Metric keys are the population it does not cover (record A5) |
| 7 | per-segment current density vs the limit read from the process kit's technology file | `em_current_density_check.py` | **landed** — the count the reliability axis wanted IS computed; the consumer read the raw measurement artefact instead (record A6) |
| 8 | no personal or absolute home path in shipped plugin source | `shipped_path_portability_check.py` | **landed** — shipped source only |
| 9 | no non-standard absolute include path in an analog deck | `analog_netlist_path_lint.py` | **landed** — analog decks only; generated digital analysis scripts are uncovered (record A4) |
| 10 | the pointer replaces a MISSING location, never a present one | `_corpus_location.py:56` — *"THE POINTER REPLACES A MISSING CORPUS; IT DOES NOT REPLACE A PRESENT ONE"*, test `named.is_dir()` at line 157 | **exists and is correct; BYPASSED** by three consumers (record A8) |
| 11 | which image a run actually executed is recorded and can be enforced | `container_image_provenance.py` | **landed** — for the flow's container, not for a test aggregate (record A9) |
| 12 | a red base may not excuse a finding this branch INTRODUCED | `hygiene_finding_delta.py` (#1498, refs #1553) | **landed** — and it ANSWERS the "not settled" question below |
| 13 | a prepared checkout must be self-contained | `landing_tier_checkout_preflight.py` | **landed** — proves self-containment, says nothing about WHICH revision (record A10) |
| 14 | the clock period from a table keyed by cell library, and the input delay as the declared fraction of it | `declared_clock_period.py` (`declared_period_ns:214`, `declared_io_delay_fraction:297`), landed v1.11.5 | **landed** — two values marked; the general "mark every read-or-defaulted value" rule did not land (record A13) |
| 15 | the generated inventory is not stale; a reported measurement names its provenance | `gen_program_inventory.py --check`, `result_md_audit_provenance_check.py` | **landed** |

### The one that closes an open question

One source lane recorded, as *"the biggest thing I found — and I could not settle
WHY"*, that a **blocking, always-run hygiene gate was red on `main` across 13
version-bearing landings** and nothing stopped them. It concluded the cause was
run history, not repo state.

It is repo state. `hygiene_finding_delta.py`'s own docstring states the mechanism:
the landing script prints **one line for the whole hygiene suite**, so the merge
verdict can subtract only that one label — *"the base's suite is red → the whole
label is excused, and a finding this branch INTRODUCED under it is invisible."*
A gate red at the base is excused at every subsequent landing, by design, at a
granularity of one. The rule that fixes it **already exists**; the same lane's
tier run measured that gate's own wiring test (the `#1498` subset-rule wiring test) among the failures that are real about `main`. So this is not a
new record — it is rule #12 above, existing and not in force.

---

## The 13 Bucket-A records

Each carries the measurement that produced it. Full text, with before/after
numbers and both generality answers, is in `recoveries.json`.

| rule | the measurement | fires on the original? | on a different instance? |
|---|---|:--:|:--:|
| `provenance_value_is_resolved_not_constant` | two cells' antenna report byte-identical, 487 B, `sha256 7c614562…`, citing a path the cell does not contain. **Residue verified by me on main**: the emitter writes the resolved input list and a *typed* sentence naming a fixed log path **in the same `write_text` call**; a second typed instance in another emitter | yes | yes |
| `signoff_report_states_its_stage` | 1 of 3 reports stamped; 48 of 56 timing rows refused as incomplete in scope; setup and hold both report an incomplete view set | yes | yes |
| `declared_basis_matches_the_session_inputs` | header claims post-layout; session links a 287-instance netlist and no parasitics against 3373 routed. 0.306 mW vs 0.573 mW — 46.6 % understated — clock group **0.000 mW** vs 33.7 % of real power | yes | yes |
| `emitted_script_paths_are_project_relative` | the emitted power deck links the netlist by the absolute run-trial path, so two runs of one configuration hash differently and the identity check refuses | yes | yes |
| `every_required_metric_key_has_a_producer` | the hold axis proves from one slack name; the extractor publishes the quantity under another; not measured on **every view of all six** timing artefacts | yes | yes |
| `measurement_only_artefact_is_not_a_verdict_source` | 2431 segments, max current 1.951e-4 A, **no limit and no count**; the emitter's own comment says it is not a sign-off verdict | yes | yes |
| `only_the_declaring_step_writes_its_output` | at one path: 811 B / 2 findings / scope populated, vs the delegate's 308 B / 1 finding / no scope keys — and a release tier graded the second | yes | yes |
| `explicit_argument_outranks_the_environment_pointer` | **reproduced by me on main**: 3 sites still spell it as an unconditional override; a checker given a 2-path subject reported a pass over 8309 paths of the shared tree. Fix branch: 21 of 23 close, 0 new, 0 regressions over 32 files | yes | yes |
| `test_aggregate_carries_its_runtime_identity` | 28 of 127 failures were one missing test plugin; 26 vanished on a second runtime; **five controlled arms** were needed to attribute them | yes | yes |
| `prepared_checkout_states_the_revision_it_holds` | a clone by branch name from a local path landed many releases back and did **not contain the commit under test** | yes | yes |
| `local_clone_does_not_borrow_objects` | **reproduced by me on main**: the option that prevents it occurs **zero times** in this repository's own source; two lanes hit the refusal and escaped it by hand | yes | yes |
| `printed_remedy_runs_as_printed` | the printed remedy verbatim returns an unexpected-option error, exit 1, command never run; with the entry point's leading argument it runs and returns the marker in 0.58 s | yes | yes |
| `generated_values_state_whether_they_were_read_or_defaulted` | a declared period of 24 signed off at the default 20 (a 20 % over-constraint) and a declared input delay of 4.8 emitted as a fixed 2. Three full runs: constraint moves, design still meets it; **5 of the table's 6 rows make sign-off stricter**, so the rule is not a relaxation | yes | yes |

One honest note on the first row: the rule fires on the original artefact because
that artefact's source key **was** a typed constant. It also fires on what the fix
left behind — an artefact now carrying two source claims, one of which can never
look wrong. Both are the same rule.

---

## The one honest sentence the ladder demands, per B/C/D/T record

**B — none.** Every candidate reduced to a regex, a file-existence test, a
structural comparison or a table lookup, and in each case I can name the exact
input and the exact decision. Writing "this needs judgment" for any of the 13
would have been the excuse the brief warns about.

**T — `downgraded-abort-has-no-completion-record` (`OpenROAD`).**
*A plugin-side rule can only enumerate the identifiers the fork has ALREADY
downgraded, so it is guaranteed to be one release behind and to fail in the
passing direction — the completion statement has to come from the tool that knows
it did not complete.* Grounded in the runner's own comment beside its error-marker
list, which records that each downgrade moves a condition out of the set the gate
can see **by construction**, and in the separately maintained warning scan that
had to be added for the identifier most recently downgraded from fatal.

**C — `artefact-consumer-index-misses-runtime-resolved-readers`.**
*A program cannot decide from a bare basename occurrence whether it is a read, a
write, or a name in a mapping table — the measured population is eight such
occurrences, several are not reads, and this module's own doctrine treats a false
finding as a defect to kill; deciding it needs source-level data-flow plus an
individual verdict on each of the eight.*

**C — `published-run-omits-the-inputs-its-reports-name`.**
*The check itself is a file-existence test and belongs in Bucket A; what is large
is that the publication contract has to be written, the whole existing corpus
measured against it, and runs re-published from a flow carrying the identity
stamps, because switching it on today fails the entire corpus for a reason that
predates the rule.*

**D — the four failing numbers a work order cited.**
*No artefact of the run that produced them is reachable from the host, so the
class of the defect is unknown and a record would capture a hypothesis in the
shape of a finding.* This is **not** "not a plugin gap" and **not** "design-side":
the generalisable half of that same episode IS captured, as records A9 and A10 —
a reported measurement that names neither the runtime nor the revision that
produced it cannot be attributed. What is discarded is these four numbers, not
their class.

---

## What I did NOT settle, and why

1. **Two of the 13 A-rules are already fixed on branches that are not landed.**
   `only_the_declaring_step_writes_its_output` is fixed on a branch its author
   could not push at all; `explicit_argument_outranks_the_environment_pointer` and
   `printed_remedy_runs_as_printed` are fixed on a branch that is pushed and
   unlanded. I verified on `origin/main` that **none** of the three fixes is in the
   default branch — the three override sites and the zero occurrences of the clone
   option are current state, not history. Whoever implements these should rebase
   the existing work rather than re-author it.

2. **Four records are routed to a step id that is not their home.**
   `benchmark/CAPTURE_ROUTING.json` has **no step for the repository's own landing
   and test harness**, so the four harness records (`explicit_argument_outranks…`,
   `test_aggregate_carries…`, `prepared_checkout_states…`, `local_clone_does_not…`,
   plus `printed_remedy_runs_as_printed`) were routed to `benchmark.verify_claim_done`
   — the plugin's own change-verification gate, the closest real entry — so their
   sketches would be emitted and reviewable rather than silently landing in
   `bucket_A_unrouted`. **Each record's `fix_action` names its real target file.**
   The missing step id is itself a gap in the routing table and is stated here
   rather than papered over.

3. **One source named in the brief was not in `/tmp/capture_lanes/`.**
   `j4reds2_RESULT.md` is absent from that directory; I found the lane's own copy
   at `~/_j4reds2/RESULT.md` and used it. Flagging it so the next reader of that
   directory does not conclude the lane produced nothing.

4. **The corpus numbers behind records C2 and A1 are SHA-bound and I did not
   re-measure them.** Two source lanes both record that the published corpus moved
   under them the same day — one measured 4 published cells, another recorded all
   4 being withdrawn. Every corpus count quoted here comes from those lanes and
   should be re-pinned before it is trusted at face value.

5. **I implemented no gate and swept no corpus.** Per the brief, this pass is the
   records and the sketches. Each sketch carries the emitter's own standing
   condition — *corpus-sweep required before merging, zero false positives* — and
   for `local_clone_does_not_borrow_objects` and
   `explicit_argument_outranks_the_environment_pointer` that sweep is the whole
   remaining risk, because both are source-level scans over the 1270 files in `programs/`.
