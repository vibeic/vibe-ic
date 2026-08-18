# Can the 63 x 9 matrix redden on CONTENT, or only on ABSENCE?

Measured 2026-08-19 against `origin/main` at `397b3f25f`, in the
`vibeic-eda` container. The published corpus is not in this checkout
(vibe-ic#1723); every corpus figure below was read from a clone of
`vibeic/benchmark-data` at `beb3bd57f` pointed at by
`VIBE_IC_BENCHMARK_DATA`, and the command that produced it is quoted beside it.

## The question

A cell of this matrix reddens when a declared artefact is MISSING. The
question is whether any cell reddens when the artefact is **present and
wrong** — present at the declared path, non-empty, tracked, and carrying bytes
that are not what the declaration means. A check that cannot tell those apart
is an existence check wearing the clothes of a correctness check.

Line numbers below are an aid, measured at `397b3f25f`; the SYMBOL is the
citation, because a line-moving commit rots the number and not the name.

## The nine rows

| # | dimension | what makes the cell red TODAY | can PRESENT-BUT-WRONG redden it? | what it would have to read |
|---|-----------|-------------------------------|----------------------------------|-----------------------------|
| 1 | `wiring` | `test_d1_gate_is_wired_in` (`test_matrix_d1_wiring.py:868`): a declared gate program with no file under `programs/` (`ch.unresolved`), a program the REAL executor never dispatched (`unreached`), or a gate reachable through zero channels (`assert ch.any`, :968). | **N/A — not its subject.** D1's artefact is the gate DECLARATION, not a run output. Its own present-but-wrong case — a program that exists, is declared, and is never reached — is already the `unreached` red, and it drives the real `_evaluate_gate` rather than reading the yaml. | nothing further. |
| 2 | `falsifiable` | `test_d2_gate_has_a_reachable_fail` (`test_matrix_d2_falsifiable.py:1989`): `assert reds` (:2054) requires at least one blocking clause to reach a **content-earned** FAIL on a deliberately-broken project; a red graded `ABSENCE_RED` is explicitly refused as evidence. | **YES — already, and this is the model for the rest.** D2 is the one dimension that separates a red earned by the artefact being absent from a red earned by what the artefact says (`DEMONSTRATIONS` vs `ABSENCE_RED`), and it registers the clauses it could not redden in `UNREDDENED` instead of counting them. `test_d2_a_present_but_wrong_json_field_is_still_a_real_red` and `test_d2_a_files_exist_clause_is_satisfied_by_a_zero_byte_file` hold both halves. | nothing — no change made here. |
| 3 | `outputs_produced` | `test_d3_required_outputs_are_produced` (`test_matrix_d3_outputs_produced.py:2336`) -> `audit_step` -> `resolve` (:1414). Refused a match only for: 0 bytes, symlink, untracked at HEAD, ledger `unwritten`, ledger `unattributed`. | **WAS NO — every one of those five is answerable from a directory listing plus `git ls-files`; not one opened the file. NOW YES:** `kind_conformance` (:1364) refuses a match whose bytes do not parse as the kind its declared path names, reported as the sixth category `Rejected.malformed`. | done — see *What changed*. |
| 4 | `criteria_match` | `test_d4_gate_measures_what_it_claims` (`test_matrix_d4_criteria_match.py:487`): a gate command the program's own CLI REJECTS (`_assert_cli_contract`), a declared `required_outputs` entry named nowhere the gate reads (`_assert_artefacts_grounded`), or a files-only gate whose claim and deliverable diverge. | **N/A — not its subject.** D4 compares the gate's DECLARATION against the gate's CODE. Both are present in every run; there is no artefact whose bytes could be wrong. | nothing further. |
| 5 | `deps_correct` | `test_d5_blocks_on_covers_the_real_dependency_graph` (`test_matrix_d5_deps_correct.py:900`) -> `d5_problems` (:631): unresolved / duplicate / self / forward `blocks_on` edges, missing or phantom producer edges. | **N/A — not its subject.** Purely a graph over the flow yaml and the gate programs' AST. No run artefact is opened at any point. | nothing further. |
| 6 | `skip_discipline` | `test_d6_skip_discipline` (`test_matrix_d6_skip_discipline.py:1581`): legs L1..L6 over an EMPTY and a SEEDED synthetic project, each asserting a skip / vacuous-pass surface is conditioned on a runtime fact and reported at a tier that is not the plain PASS bucket. | **NO, and it is the wrong lever.** D6 grades the TIER a verdict is reported at, not the bytes that produced it. Its analogous defect — a `VACUOUS_PASS` folded into `pass_count` — is already leg L3c. A content mutation would change which tier the gate lands on and D6 would grade the new tier correctly either way. | **NOT DETERMINED as a content question.** To notice a corrupt artefact D6 would have to acquire an opinion about correctness, which is D9's question and not this one. Forcing it here would put two rulers on one fact. |
| 7 | `outputs_list_complete` | `test_d7_required_outputs_list_is_complete` (`test_matrix_d7_outputs_list_complete.py:303`) -> `G.findings_for`: rules W1/W2 over the step's own AST plus the observed write record — an artefact the step writes unconditionally and never declares. | **N/A — not its subject.** The subject is the step's SOURCE and its write record, i.e. which paths get written, never what is in them. | nothing further. |
| 8 | `missing_caught` | `test_d8_missing_caught` (`test_matrix_d8_missing_caught.py:696`): `probe_positive` (:517) requires a PASS-tier verdict with every declared output synthesized, and `probe_negative` (:538) requires `check_step` to return `MISSING` naming the entry once exactly one is removed. | **NO, and the fixture says so out loud.** `_materialize` seeds each output with `fixture_body`, which is `"d8 fixture artefact\n"` for every suffix outside `{.json,.jsonl,.v,.sv}`, and `check_step` returns PASS-tier on it. The dimension's own question is about ABSENCE by construction — "when a declared output IS missing, which mechanism catches it" — so a present-but-wrong artefact is out of its scope by definition, not by oversight. | **NOT DETERMINED — deliberately not attempted here.** A third arm ("all outputs present, one of them corrupt, and `check_step` must not certify") reddens on `flow_compliance_check.check_step` on day one, because the `required_outputs` layer there (`_resolve_required_output`) is a glob-and-stat with no byte read. That is a FLOW-level change reaching all 63 steps and every user project; it is measured and named here rather than half-landed. |
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
`resolve` gains `kind_conformance`: a match is refused when its bytes do not
parse as the kind its own declared path names (`.json` -> `json.loads`,
`.xml` -> `ElementTree`), reported as `Rejected.malformed` and rendered
"PRESENT AND WRONG" rather than folded into "missing". A suffix the table does
not know returns "no opinion", never "conformant", and the ungraded remainder
is a published number, not a silence.

Measured before it was wired in, over the 3 admissible run roots reachable
through the corpus pointer: `resolve_anywhere` evidences **99** entries, of
which **62 `.json` + 1 `.xml` + 2 `.gds`** have a checkable kind and **63 of 63
JSON/XML parse**. So the rule is green on every artefact this repository can
point at and is exercised only by its controls. `.gds` is deliberately NOT
graded here: `gds_substance_check` and `gds_topcell_name_check` already ship as
blocking gates over those bytes, and a second, weaker opinion would be a
duplicate ruler that can only disagree with the shipped one.

Coverage, printed by the cell census on every run: **96 of 171** declared
output alternatives have a gradeable kind; 75 do not (`.rpt .v .def .lef .lib
.sdc .sp .spef .gds .log .md ...`).

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

# D9 — the content census over 63 steps
docker exec vibeic-eda bash -lc '
  cd <repo> && PYTHONDONTWRITEBYTECODE=1 VIBE_IC_BENCHMARK_DATA=<clone> \
  python3 tools/d9_content_census.py --out /tmp/d9_content.json --limit-per-step 1'
```
