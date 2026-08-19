# Can the 63 x 9 matrix redden on CONTENT, or only on ABSENCE?

Measured 2026-08-19 against `origin/main` at `397b3f25f` and RE-MEASURED at
`74ac9fa78` after a rebase, in the `vibeic-eda` container. Every figure below
was re-taken at `74ac9fa78`; where the two commits disagree the later one is
quoted and the change is named (only row 8 moved — see it). The published corpus is not in this checkout
(vibe-ic#1723); every corpus figure below was read from a clone of
`vibeic/benchmark-data` at `beb3bd57f` pointed at by
`VIBE_IC_BENCHMARK_DATA`, and the command that produced it is quoted beside it.

## The question

A cell of this matrix reddens when a declared artefact is MISSING. The
question is whether any cell reddens when the artefact is **present and
wrong** — present at the declared path, non-empty, tracked, and carrying bytes
that are not what the declaration means. A check that cannot tell those apart
is an existence check wearing the clothes of a correctness check.

Line numbers below are an aid, measured at `74ac9fa78`; the SYMBOL is the
citation, because a line-moving commit rots the number and not the name.

## The nine rows

| # | dimension | what makes the cell red TODAY | can PRESENT-BUT-WRONG redden it? | what it would have to read |
|---|-----------|-------------------------------|----------------------------------|-----------------------------|
| 1 | `wiring` | `test_d1_gate_is_wired_in` (`test_matrix_d1_wiring.py:868`): a declared gate program with no file under `programs/` (`ch.unresolved`), a program the REAL executor never dispatched (`unreached`), or a gate reachable through zero channels (`assert ch.any`, :968). | **N/A — not its subject.** D1's artefact is the gate DECLARATION, not a run output. Its own present-but-wrong case — a program that exists, is declared, and is never reached — is already the `unreached` red, and it drives the real `_evaluate_gate` rather than reading the yaml. | nothing further. |
| 2 | `falsifiable` | `test_d2_gate_has_a_reachable_fail` (`test_matrix_d2_falsifiable.py:1989`): `assert reds` (:2054) requires at least one blocking clause to reach a **content-earned** FAIL on a deliberately-broken project; a red graded `ABSENCE_RED` is explicitly refused as evidence. | **YES — already, and this is the model for the rest.** D2 is the one dimension that separates a red earned by the artefact being absent from a red earned by what the artefact says (`DEMONSTRATIONS` vs `ABSENCE_RED`), and it registers the clauses it could not redden in `UNREDDENED` instead of counting them. `test_d2_a_present_but_wrong_json_field_is_still_a_real_red` and `test_d2_a_files_exist_clause_is_satisfied_by_a_zero_byte_file` hold both halves. | nothing — no change made here. |
| 3 | `outputs_produced` | `test_d3_required_outputs_are_produced` (`test_matrix_d3_outputs_produced.py:2336`) -> `audit_step` -> `resolve` (:1414). Refused a match only for: 0 bytes, symlink, untracked at HEAD, ledger `unwritten`, ledger `unattributed`. | **WAS NO — every one of those five is answerable from a directory listing plus `git ls-files`; not one opened the file. NOW YES:** `kind_conformance` (:1364) refuses a match whose bytes do not parse as the kind its declared path names, reported as the sixth category `Rejected.malformed`. | done — see *What changed*. |
| 4 | `criteria_match` | `test_d4_gate_measures_what_it_claims` (`test_matrix_d4_criteria_match.py:487`): a gate command the program's own CLI REJECTS (`_assert_cli_contract`), a declared `required_outputs` entry named nowhere the gate reads (`_assert_artefacts_grounded`), or a files-only gate whose claim and deliverable diverge. | **N/A — not its subject.** D4 compares the gate's DECLARATION against the gate's CODE. Both are present in every run; there is no artefact whose bytes could be wrong. | nothing further. |
| 5 | `deps_correct` | `test_d5_blocks_on_covers_the_real_dependency_graph` (`test_matrix_d5_deps_correct.py:900`) -> `d5_problems` (:631): unresolved / duplicate / self / forward `blocks_on` edges, missing or phantom producer edges. | **N/A — not its subject.** Purely a graph over the flow yaml and the gate programs' AST. No run artefact is opened at any point. | nothing further. |
| 6 | `skip_discipline` | `test_d6_skip_discipline` (`test_matrix_d6_skip_discipline.py:1581`): legs L1..L7 over EMPTY, SEEDED, FLOW_COMPLETE and (new) WRONG_CONTENT synthetic projects. | **WAS NO — the earlier reading of this row said so and said it was the wrong lever. HALF OF THAT IS OVERTURNED BY MEASUREMENT, and the half that stands is named below.** Every fixture in this module was CONTENT-FREE (`_seed` writes `{}` / `module stub_top; endmodule` / `stub`), so "present" and "present and correct" were the same input. **NOW YES for the PASS half:** leg L7 (`_leg7_pass_is_not_awarded_over_unread_content`) charges a step that resolves to a plain `PASS` under BOTH the stub fixture and a WRONG_CONTENT fixture — same paths, same count, well-formed documents of the wrong kind — AND declares a blocking executable clause. | **Done for the PASS half; the earlier row's objection stands for the SKIP half.** The objection was that D6 grades the TIER and a content mutation would merely move the step to a different tier which D6 would grade correctly either way. That is true of a step that SKIPS — and false of a step that PASSES, because there is no honester tier for it to move to: a plain PASS over bytes the gate never read is the same defect L1b names on an empty tree, one fixture later. The measurement settles it rather than the argument: 17 WRONG_CONTENT fixtures were built (one per pass-tier scenario), **five steps move from a pass tier to FAIL** (14, 28, 30, 32, 38), so the fixture discriminates — and **step 38 does not move**, with a BLOCKING `foundry_handoff_package_check` exiting 0 while `mask_spec.json`, `wat_plan.json` and `corner_test_vectors.json` hold `1234` and `scribe_line_layout.gds` holds a JSON document. |
| 7 | `outputs_list_complete` | `test_d7_required_outputs_list_is_complete` (`test_matrix_d7_outputs_list_complete.py:303`) -> `G.findings_for`: rules W1/W2 over the step's own AST plus the observed write record — an artefact the step writes unconditionally and never declares. | **N/A — not its subject.** The subject is the step's SOURCE and its write record, i.e. which paths get written, never what is in them. | nothing further. |
| 8 | `missing_caught` | `test_d8_missing_caught` (`test_matrix_d8_missing_caught.py:773`): `probe_positive` (:594) requires a PASS-tier verdict with every declared output synthesized, and `probe_negative` (:615) requires `check_step` to return `MISSING` naming the entry once exactly one is removed. | **NO, and the fixture says so out loud.** `_materialize` seeds each output with `fixture_body`, which is `"d8 fixture artefact\n"` for every suffix outside `{.json,.jsonl,.v,.sv}`, and `check_step` returns PASS-tier on it. The dimension's own question is about ABSENCE by construction — "when a declared output IS missing, which mechanism catches it". The present-but-wrong case is no longer unasked here: `d4136c305` added `wrong_body` (:342) beside `fixture_body` (:274) and swept both. It reports the blindness; the CELL still reddens only on absence. | **STILL NOT DETERMINED AS A CELL PREDICATE — and since `d4136c305` the fact is INSTRUMENTED on main.** That commit landed `_content_arm_sweep` + `CONTENT_ARM_AS_MEASURED` (:1602): two trees differing in the bytes of ONE declared output and nothing else, compared on `check_step`'s whole verdict signature. **Absence moves the verdict 16 of 16; content moves it 0 of 16**, twelve of them by disclosing `VACUOUS_PASS` and four (steps 1, 32, 35, 38) by answering a plain PASS. So the row is now a PINNED measurement rather than an untested claim — but the pin RECORDS the blindness, it does not redden the cell on it. Making it redden is still the third arm named here: it fires on `flow_compliance_check.check_step` on day one, because the `required_outputs` layer there (`_resolve_required_output`) is a glob-and-stat with no byte read. That is a FLOW-level change reaching all 63 steps and every user project; it is measured and named here rather than half-landed. |
| 9 | `output_is_correct` (not shipped) | Two instruments, no flow gate. `tools/d9_flow_gate_reality.py` decides MOVES/DARK by a two-arm mutation whose arm B **deletes** the declared outputs. `tools/d9_content_census.py` adds arm C, which **corrupts** them in place. | **YES via arm C — and until this change nobody could run it.** Both instruments resolved the corpus from `REPO/benchmark-data`, which left the repository at v1.10.56 (#1723), so at `397b3f25f` both exit rc=2 without measuring. | done — see *What changed*. The absence/content gap is now a measured number, below. |

### Dimension 8's NOT DETERMINED, measured rather than asserted

The claim above — that `check_step`'s `required_outputs` layer never reads a
byte — is not an inference from the source. Driven through d8's own
`_materialize` on step 8 (one literal `.json` entry) with the same `PASS_GATE`
substitution the dimension uses, so the only thing under test is the outputs
layer:

```
step 8 required_outputs: ['reports/phase2/sdc_check.json']
  kind-correct JSON                             -> status='PASS'  evidence=['reports/phase2/sdc_check.json']
  PRESENT AND WRONG (not JSON)                  -> status='PASS'  evidence=['reports/phase2/sdc_check.json']
  PRESENT AND WRONG (valid JSON, wrong shape)   -> status='PASS'  evidence=['reports/phase2/sdc_check.json']
```

Three different files, one verdict. The declared artefact discharges the
declaration by existing. That is the flow-level shape of the same defect d3
carried, and closing it there is a change to `_resolve_required_output` that
reaches all 63 steps and every user project — named here, not half-landed.

Re-run at `74ac9fa78` (`scratch/probe_d8.py`): the three lines above reproduce
verbatim. It now sits beside an independent measurement of the same claim that
landed on main in the meantime — `d4136c305`'s `_content_arm_sweep`, which
drives each step's OWN gate instead of substituting `PASS_GATE`, and reports
content moving the verdict **0 of 16** against absence moving it 16 of 16. The
two do not overlap: **step 8 is not in that population of 16**
(`CONTENT_ARM_AS_MEASURED`, :1602), because its own gate never reaches a
PASS-tier verdict on the synthetic tree, so the sweep cannot ask it anything.
Substituting `PASS_GATE` is what makes the outputs layer answerable for a step
in that state, and the answer is the same one: PASS on all three bodies.

## What the ninth dimension measures once it can run

`tools/d9_content_census.py`, 63 steps against 91 published runs, one run per
step (`--limit-per-step 1`; 117 (step,run) pairs dropped by that cap and the
report says so):

| verdict | n | steps |
|---------|---|-------|
| CONTENT-SENSITIVE | 22 | D1 3 5 11 DT1 12 13 A4 A6 A7 A8 18 22 DT2 DT3 24 26 27 28 31 33 37 |
| **EXISTENCE-ONLY** | **6** | **4 7 A1 A2 A3 A5** |
| DARK | 5 | 2 8 25 34 36 |
| INCONCLUSIVE | 4 | 9 14 16 29 |
| NO-DENOMINATOR | 23 | 6 10 FS1 A9 15 17 19 20 21 23 30 32 38 39 M1 M2 M3 M4 40 41 42 43 44 |
| NO-BLOCKING-RULER | 3 | 1 35 P0 |

The six EXISTENCE-ONLY steps are the finding in its exact form: the gate's
verdict is identical on the published artefact and on the same artefact with
its bytes corrupted, and changes only when the file is deleted. Verbatim, from
the census:

```
[EXISTENCE-ONLY] step 4  cpu_functional_oracle_waiver_check: A=CLEAN/rc=0 C=CLEAN/rc=0 B=NO-INPUT/rc=2
[EXISTENCE-ONLY] step 7  pvt_matrix_check:                   A=CLEAN/rc=0 C=CLEAN/rc=0 B=NO-INPUT/rc=2
[EXISTENCE-ONLY] step A1 analog_a1_spec_extract_check:       A=CLEAN/rc=0 C=CLEAN/rc=0 B=NO-INPUT/rc=0
[EXISTENCE-ONLY] step A2 analog_a2_topology_select_check:    A=CLEAN/rc=0 C=CLEAN/rc=0 B=NO-INPUT/rc=0
[EXISTENCE-ONLY] step A3 analog_a3_netlist_gen_check:        A=CLEAN/rc=0 C=CLEAN/rc=0 B=NO-INPUT/rc=0
[EXISTENCE-ONLY] step A5 analog_a5_layout_check:             A=CLEAN/rc=0 C=CLEAN/rc=0 B=NO-INPUT/rc=0
```

It is a LOWER BOUND on content-blindness in one direction only: a gate scored
CONTENT-SENSITIVE genuinely read bytes, because a verdict cannot follow bytes
it never read. A gate scored EXISTENCE-ONLY read no byte THAT MATTERED to this
mutation; a different corruption might move it.

Read this beside the frozen absence figure in `tools/d9_reality/d9_reality.json`
— `moves_today: 31` of 63 — which is what a DELETION arm reports. The page that
renders it already says so in its own words ("after DELETING the step's own
declared outputs"), so the two numbers do not contradict; they answer different
questions, and only one of them is D9's.

## What changed

**Dimension 3 — a content predicate, and a mutation that reddens the cell.**
`resolve` gains `kind_conformance`: a match is refused when its bytes are not
of the kind its own declared path names, reported as `Rejected.malformed` and
rendered "PRESENT AND WRONG" rather than folded into "missing". A suffix the
table does not know returns "no opinion", never "conformant", and the ungraded
remainder is a published number, not a silence.

The grammar covers twelve suffixes: `.json` (an object or an array), `.xml` /
`.lyrdb`, `.gds` / `.gds2` (the GDSII HEADER record), `.spef`, `.def`, `.lef`,
`.lib`, `.v` / `.sv`, `.mag`.

MEASURED FOR FALSE POSITIVES BEFORE IT WAS WIRED IN, over the **611 resolvable
`(step, run root, entry)` triples** the corpus pointer reaches — every declared
output of every step in every admissible run root, not a sample:

    gradeable            472
    no gradeable suffix  139   (.rpt 89, .md 20, .sby 6, .sdc 6, .done 5,
                                .flag 4, .txt 3, .yml 2, .sp 2, .report 2)
    FALSE POSITIVES        0

Per suffix: `.json` 422, `.v` 28, `.xml` 7, `.gds` 5, `.mag` / `.lef` / `.lib`
/ `.spef` 2 each, `.lyrdb` / `.def` 1 each. Coverage of the DECLARATION rather
than the corpus, printed by the cell census on every run: **120 of 171**
declared output alternatives have a gradeable kind; 51 do not.

THE `.json` RULE IS NOT `json.loads`. It requires the document to be an object
or an array. `json.loads` alone accepts `1234` and `"PASS"`, and 422 of the 611
triples — 69% of the whole population — are `.json`, so a predicate that
stopped at "it parses" would leave the majority kind able to hold a number and
read as a report. The empty ARRAY is still accepted, because
`reports/phase2/lint/rtl_hygiene.json` and
`reports/phase2/lint/rom_init_lint.json` are legitimately `[]` in all eight
admissible run roots and a rule that refused them would redden 16 correct
artefacts. Both halves are asserted in
`test_d3_the_cell_reddens_on_a_corrupt_declared_output` (arm D), and removing
the object-or-array clause makes that arm fail — so it is load-bearing, not
decorative.

`.gds` IS graded here, and an earlier draft of this document said it should not
be, on the grounds that `gds_substance_check` and `gds_topcell_name_check`
already ship as blocking gates over those bytes and a second opinion would be a
duplicate ruler that can only disagree. The reasoning is right and the
conclusion does not follow: the rule here is the HEADER record alone, which is
the weakest statement anyone can make about a GDSII file, so every file it
refuses is refused by those gates too and no disagreement is constructible.
This module ALREADY reads GDS bytes for step A8
(`test_d3_a8_gds_in_a_run_root_is_a_real_hardmacro_layout`), so the duplicate-
ruler line was in a different place from where it was drawn.

**Dimension 6 — leg L7, and the fixture that discriminates.**
Every fixture in the D6 probe was content-free: `_seed` writes `{}` for a
`.json`, `module stub_top; endmodule` for a `.v`, and `stub` for everything
else. "Present" and "present and correct" were therefore the same input, and a
gate that never opened its inputs was indistinguishable from one that opened
them and approved. `WRONG_CONTENT` is the SEEDED project with the same paths,
the same count and different BYTES — each file a well-formed document of the
wrong kind (`1234` at a `.json`, a JSON object elsewhere). It is built only
where the baseline landed on a pass tier, because "was this PASS earned" has no
subject on a step that already FAILs; that keeps the module's wall clock where
it was (77 s before, 58-68 s after) instead of doubling it to answer a question
about nothing.

L7 charges a step that resolves to a plain `PASS` under BOTH fixtures AND
declares a blocking executable clause. Measured:

    WRONG_CONTENT fixtures built                    17
    steps that MOVE from a pass tier to FAIL         5   (14, 28, 30, 32, 38)
    steps that PASS on wrong content                 3   (1, 35, 38)
      ...of which excluded as files_exist-only       2   (1, 35)
      ...charged                                     1   (38)

The five movers are the control: a fixture that moved nothing would make every
L7 green a statement about the fixture. Steps 1 and 35 are excluded BY
DECLARATION and named in `test_d6_l7_the_exclusion_is_named_not_silent` — their
only blocking clause is `files_exist`, which IS an existence check and says so
in the yaml; whether the flow should have declared more is dimension 4's
question. Step 38 is the residue and the finding: `foundry_handoff_package_
check` is BLOCKING and exits 0 with `mask_spec.json`, `wat_plan.json` and
`corner_test_vectors.json` holding `1234` and `scribe_line_layout.gds` holding
a JSON document. Its FLOW_COMPLETE arm DOES fail on wrong content, which
localises the gap precisely: the checker reads content, just not the content of
the outputs this step declares.

It is in `_DEFERRED_L7_UNREAD_CONTENT` with the same paired guards
`_DEFERRED_L6_SKIPS` already has — the register may only SHRINK, an entry that
stops describing a live defect reddens until it is deleted, and a separate test
recomputes the charge WITHOUT the register so the leg cannot quietly stop
charging while the register still looks like it is tracking a hole. Emptying
the register turns `test_d6_skip_discipline[step38]` red and nothing else:
`1 failed, 61 passed, 16 deselected, 1 xfailed`.

Row 6 of the table above previously read NOT DETERMINED with the note that
forcing a content question onto D6 would "put two rulers on one fact". That
holds for a step that SKIPS and does not hold for a step that PASSES: a skip
has an honester tier to move to and D6 grades the move correctly either way,
whereas a plain PASS over unread bytes has no honester tier — it is the same
defect leg L1b names on an empty tree, one fixture later.

**Dimension 9 — the instruments can reach the corpus again.**
`corpus_clone()` / `run_path()` / `tracked_files()` in
`tools/d9_flow_gate_reality.py` read `VIBE_IC_BENCHMARK_DATA` — the same
pointer the test suite already uses — and `tools/d9_content_census.py` goes
through them. Run ids keep their `benchmark-data/` prefix everywhere, so a
figure measured against a clone is quotable against the published tree without
translation. A pointer that is SET and WRONG refuses instead of degrading to
"no corpus", and `verify_corpus_clean` now asks the tree the runs were actually
read from — before this it ran `git status -- benchmark-data` inside a
repository that no longer has that path and answered CLEAN whatever the clone
looked like.

The absence instrument runs again too, and says so about itself: with the same
pointer, `tools/d9_flow_gate_reality.py --limit-per-step 1 --jobs 6` exits 0
over 91 runs, reports `read_from: "clone via VIBE_IC_BENCHMARK_DATA"`, and ends
`corpus_clean_after_sweep: true` — the sweep deletes and rewrites only inside
throwaway copies. Its `moves_today` from that shallow run is 25, not the 31 in
the committed report, because one run per step is a smaller sample and not a
regression; the committed report is left as it was rather than replaced by a
shallower measurement of a corpus that has itself moved on (91 runs here
against the 107 it was taken over).

## Where dimension 3's predicate STOPS, and the three candidate rules measured and refused

`kind_conformance` grades WELL-FORMEDNESS. It refuses a `.json` that is not
JSON. It does NOT refuse a `.json` that parses and says the wrong thing, so the
brief's strictest reading — "corrupt the CONTENT while keeping it present and
**well-formed**, and show the cell goes red" — is answered for the malformed
class and **NOT DETERMINED for the semantic class**. That is a measured limit,
not an omission; three candidate rules were built as probes and each was
refused by what the corpus actually contains. Measured at `74ac9fa78` over the
3 admissible run roots, 62 resolved `.json` + 1 `.xml`. RE-MEASURED over the
full 8 admissible roots the pointer reaches (422 resolved `.json` of 611
triples) the two refusals hold and grow with the population: the empty-document
rule costs **16** false positives (the same two lint reports in all eight
roots) and the self-report-contract rule **190** over 28 distinct step/path
pairs — every `phase1/generated_docs/L*.json`, `phase1/analog/*/spec.json` and
`phase3/stage3/cts/clock_plan.json` is a DATA document that was never a verdict
report:

| candidate rule | what it would refuse | measurement | verdict |
|---|---|---|---|
| **empty document** — a parsed doc carrying nothing (`null`, `{}`, `[]`) | the parsed-level analogue of the existing 0-byte rule | 60 non-empty, `null` 0, `{}` 0, **`[]` 2** — `reports/phase2/lint/rtl_hygiene.json` and `reports/phase2/lint/rom_init_lint.json`, both written by the two `rtl_hygiene_lint` / `rom_init_lint` clauses at flow yaml :724-725, where the empty list IS the clean result | **REFUSED.** The rule would redden two artefacts that are correct, and "no findings" is the outcome a lint report exists to be able to state. |
| **self-attribution** — the artefact's own bytes name who emitted it, and it is not this step | a valid report sitting at another step's declared path | 30 of 60 carry a self-identifying key (`program` 20, `tool` 13, `gate` 2, `emitted_by` 1, `_pmd` 0); of the 20 carrying `program`, only **7 name a program this step's gate invokes** and **13 name the PRODUCER instead** — `reports/lec.json` says `lec_run` where the gate is `lec_equivalence_check`, `reports/phase3/lvs.json` says `eda_report_audit:lvs` where the gate is `lvs_report_check` | **REFUSED — 13 false positives out of 20 gradeable.** The field records the WRITER; the flow declares the CHECKER. Comparing them reddens correct artefacts. Which step wrote a path is D7's subject and the write ledger's, not a byte this rule can read. |
| **schema conformance** — validate the parsed doc against a declared schema | a well-formed report with the wrong fields | the flow declares no schema per `required_outputs` entry. Where a schema exists it already SHIPS as its own gate — `rtl_bug_report_schema_check` (flow yaml :731 — `optional_program_exit_zero` inside the step's `all_of`, so blocking whenever the claim it grades exists) and `analog_hil_report_schema_check` (:2547, advisory); `json_schema_check.py` is driven from `skills/phase1/compliance.yaml`, not from the flow | **DUPLICATE RULER where it applies, no declaration where it does not.** (An earlier draft cited the same reasoning to keep `.gds` out of the kind table; that citation is withdrawn under *What changed* — a HEADER-record check refuses a strict subset of what the shipped GDS gates refuse, so it cannot disagree with them, whereas a schema opinion genuinely can.) |

So the honest statement of what changed in dimension 3 is: an artefact that is
present and is not the KIND its declared path names now reddens the cell; an
artefact that is present, is that kind, and is semantically wrong still does
not, and closing that needs the flow to declare what each output should
contain — which is a declaration change, not a check.

## Reproduce

```sh
# D3 — the content predicate and its two mutation controls
docker exec vibeic-eda bash -lc '
  cd <repo>/vibe-ic-marketplace/plugins/vibe-ic &&
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest \
    programs/tests/test_matrix_d3_outputs_produced.py -q -p no:randomly -s \
    -k "unparseable or corrupt_declared or kind_table"'

# D3 — the whole dimension against the published corpus
docker exec vibeic-eda bash -lc '
  cd <repo>/vibe-ic-marketplace/plugins/vibe-ic &&
  PYTHONDONTWRITEBYTECODE=1 VIBE_IC_BENCHMARK_DATA=<clone> \
  python3 -m pytest programs/tests/test_matrix_d3_outputs_produced.py -q -p no:randomly'

# D6 — leg L7, its exclusion register and the fixture control
docker exec vibeic-eda bash -lc '
  cd <repo>/vibe-ic-marketplace/plugins/vibe-ic &&
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest \
    programs/tests/test_matrix_d6_skip_discipline.py -q -p no:randomly'

# D6 — the discrimination proof: empty `_DEFERRED_L7_UNREAD_CONTENT` in a
# throwaway copy and exactly step 38 goes red
#   -> 1 failed, 61 passed, 16 deselected, 1 xfailed

# D9 — the content census over 63 steps
docker exec vibeic-eda bash -lc '
  cd <repo> && PYTHONDONTWRITEBYTECODE=1 VIBE_IC_BENCHMARK_DATA=<clone> \
  python3 tools/d9_content_census.py --out /tmp/d9_content.json --limit-per-step 1'
```

The first two refused candidate rules above are ONE probe, run against the
same corpus pointer; the third is a claim about the flow yaml and is read
there. The probe imports the dimension's own module, so the population is
exactly the artefacts the cell accepts today — no second resolver:

```python
# python3, from <repo>, with VIBE_IC_BENCHMARK_DATA set
import json, importlib.util, sys, collections
from pathlib import Path
PLUG = Path("vibe-ic-marketplace/plugins/vibe-ic").resolve()
sys.path[:0] = [str(PLUG), str(PLUG/"programs"), str(PLUG/"programs/tests")]
spec = importlib.util.spec_from_file_location(
    "d3", PLUG/"programs/tests/test_matrix_d3_outputs_produced.py")
m = importlib.util.module_from_spec(spec)
sys.modules["d3"] = m          # the module's dataclasses need it registered
spec.loader.exec_module(m)
roots, tally = m.run_roots(), collections.Counter()
for sid in m.F.step_ids():
    gate_programs = {c.command.split()[0]
                     for c in m.F.gate_clauses(sid) if getattr(c, "command", None)}
    for entry in m.F.required_outputs(sid):
        hit, _ = m.resolve_anywhere(entry, sid)
        if hit is None or not hit.path.lower().endswith(".json"):
            continue
        doc = json.loads((roots[hit.root].path / hit.path).read_text())
        tally["EMPTY " + type(doc).__name__ if doc in (None, {}, [])
              else "non-empty"] += 1
        if not isinstance(doc, dict):
            continue
        tally["self-identifying" if any(
            k in doc for k in ("_pmd", "emitted_by", "program", "tool", "gate"))
            else "anonymous"] += 1
        writer = doc.get("program")
        if isinstance(writer, str) and writer.strip():
            tally["program field names THIS step's gate"
                  if writer.split(":")[0] in gate_programs
                  else "program field names the PRODUCER, not the gate"] += 1
for k, v in sorted(tally.items()):
    print(f"{v:4d}  {k}")
```

At `74ac9fa78`, against the clone at `beb3bd57f`, it prints:

```
   2  EMPTY list
  30  anonymous
  60  non-empty
   7  program field names THIS step's gate
  13  program field names the PRODUCER, not the gate
  30  self-identifying
```

