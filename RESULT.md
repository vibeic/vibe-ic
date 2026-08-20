# RESULT — three REQUESTS TO THE LANDER, paid

Base: `origin/land/ppa-tf` @ `bb90724dcd7ebe8d31474d5245a54fdce112b527`
(14 squash commits `v1.11.19..v1.11.32` on `867de428`).
Branch: `jreq/lander-three`. Not pushed to `main`. No plugin version bumped.
No baseline written. `flow/phase1_phase2_phase3.yaml` untouched.
`tools/ci/protected_landing_transition.json` untouched.

Three requests, three independent changes, three tests, three mutation arms.

| | change | test | mutation arm |
|---|---|---|---|
| R1 | `docs/PPA_INTERFACES.md` §4 (+24 lines) | `test_ppa_interfaces_section4_owns_invocation.py` | 1 named test red |
| R2 | `schemas/ppa/readme_hint.v1.schema.json` (new) | `test_ppa_readme_hint_schema.py` | 28 red |
| R3 | `programs/phase3_one_shot_runner.py` (+26 lines, 0 removed) | `test_multicorner_sta_reports_declare_their_basis.py` | 9 red |

---

## R1 — §4 gives tool INVOCATION an owner

### What changed

`docs/PPA_INTERFACES.md` §4 assigned tool PARSING to `_ppa/backends/*` and
assigned tool INVOCATION to nobody. One line added to the module map:

```
_ppa/backends/exec.py    ONE container invocation: command, mounts, cwd,
                         cpu-seconds, tool version, invocation provenance
```

plus three paragraphs after the existing no-policy rule: the measurement the
jppa-runner lane made (6,111 of the runner's 8,745 PPA lines anchor on eleven
invocation helpers, and cannot be extracted into a module this document never
named), the rule `exec.py` inherits from the parsers (no thresholds, no
verdicts, no policy), and an explicit statement that this is an OWNERSHIP line
and not a schedule.

**The functions were NOT moved.** That extraction is large, it needs its own
A/B, and it belongs to whoever does it. What is fixed here is that the contract
was silent where it should give an answer.

The prose names no version number. Assigning one is the landing step's job, and
a document that predicts its own version is wrong the moment the queue reorders.

### The test

`programs/tests/test_ppa_interfaces_section4_owns_invocation.py` — 7 tests.

It does **not** grep for `exec.py`. It parses the fenced module map out of §4
and asks whether any entry's description carries both an invocation word and a
tool word, or whether the section prose says outright that invocation stays in
the runner. Either is an answer; the test fails only on SILENCE. That is
deliberate — the brief allowed "invocation stays in the runner forever" as the
alternative answer, and `test_the_checker_accepts_the_stays_in_the_runner_answer`
proves the checker accepts it.

Four fixtures, per §7:

* positive — `test_section_4_names_an_owner_for_tool_invocation` on the shipped doc;
* negative — `test_the_checker_rejects_the_map_as_it_shipped` runs the same
  checker over `_PRE_FIX_SECTION_4`, the verbatim map at `bb90724dc`, and
  requires SILENT. A checker that cannot fail against the pre-fix text proves
  nothing about the fix;
* vacuous — `test_a_missing_section_refuses_instead_of_passing_quietly`: the
  section reader raises `[CANNOT CHECK]` rather than returning `""`, because an
  empty string satisfies every `not in` assertion in the file;
* control — `test_section_4_still_assigns_tool_parsing`. Parsing was never the
  silent half. If this fails together with the positive, the checker has stopped
  discriminating rather than the document having changed.

### Mutation arm — measured

`git stash push -- docs/PPA_INTERFACES.md`, re-run:

```
FAILED test_ppa_interfaces_section4_owns_invocation.py::test_section_4_names_an_owner_for_tool_invocation
FAILED test_ppa_interfaces_section4_owns_invocation.py::test_the_invocation_owner_carries_no_policy
2 failed, 5 passed
```

The 5 that stay green are the non-vacuity, negative and control fixtures. They
must not depend on the fix, and they do not.

---

## R2 — `schemas/ppa/readme_hint.v1.schema.json`

### What changed

`readme_ppa_extractor.py` has stamped `"schema": "vibeic.ppa.readme_hint.v1"`
into every document it writes since `v1.11.31`, and §5 requires that id to
resolve to a file in `schemas/ppa/`. It did not. The file now exists: Draft
2020-12, `$id` `vibeic.ppa.readme_hint.v1` — the bare-name `$id` form that
`contract.v1`, `power.v1` and `run_manifest.v1` already use.

**Derived from the emissions, not from the code.** The program was run and its
output read; every constraint in the schema is a fact about a document that was
produced. Three verdicts, three document shapes, all three covered:

* `OK` — the `skills/ppa-predict` preflight invocation, verbatim;
* `CONFLICT` — a README number contradicting an L-doc at a matched scope;
* `CANNOT_CHECK` — the unreadable-input path.

Beyond shape, the schema encodes the four invariants the program guarantees
structurally, so a document that breaks one is invalid rather than merely odd:

1. `authority: HINT` and `authoritative: false` are **constants**, as is
   `hint_ignored: true` on every comparison and `inputs.rtl_read: false`. The
   "a README never outranks an L-doc" guarantee is structural in the code; it is
   structural here too.
2. `span_status` and the span **agree**: `RECORDED` requires both a span and a
   `sha256:` digest, `NO_SPAN_RECORDED` requires both null. A hint claiming a
   recorded span and carrying none is the provenance gap the status exists to
   expose.
3. `verdict` and the body agree **in both directions**: `CONFLICT` requires a
   non-empty `conflicts`, and every other verdict requires an empty one.
4. `CANNOT_CHECK` carries a `reason`, `read: false` and no hints; `OK`/`CONFLICT`
   require `inputs`, `authority_records` and `document_sha256`. "I could not
   read it" and "I read it and found nothing" must never serialize the same.

Per-array `resolution`/`reason` pinning means a conflict that resolves to
`AGREE`, or an undetermined comparison reported as `VALUE_MISMATCH`, is invalid.

### The test

`programs/tests/test_ppa_readme_hint_schema.py` — 30 tests.

* POSITIVE — the CLI is run three times in a tmp tree and each emitted document
  is validated. `test_the_positive_corpus_is_not_vacuous` pins that the corpus
  actually exercises the branches the negatives mutate: ≥10 hints, a real
  conflict, a real undetermined comparison, harvested authority, a sub-block
  hint, a vendor hint, a string-valued hint, a null-valued hint, and a
  markdown-table hint. A schema validated only against near-empty documents
  constrains nothing.
* NEGATIVE — 21 fixtures, one mutation each, applied to a document that
  validates. Each asserts the unmutated base validates FIRST, so a negative can
  never go green for an unrelated reason.
* `test_the_fallback_validator_is_an_honest_substitute` and
  `test_every_ref_is_a_local_pointer` — see the environment note below.
* SKIP DISCIPLINE — `pytest.importorskip("jsonschema", reason=...)` names what
  was not checked. A schema test that passes quietly when it cannot load a
  validator is that defect wearing a green tick.

### Mutation arm — measured

Remove `schemas/ppa/readme_hint.v1.schema.json`, re-run:

```
2 passed, 28 errors
```

(the two survivors are the path-convention pin and the CLI-emission fixture,
neither of which reads the schema).

### Environment note that shaped this test

This host ships `jsonschema` **3.2.0**, which has no `Draft202012Validator`.
The test prefers it, falls back to `Draft7Validator`, and then **pins that the
fallback is honest**: the schema must contain no keyword the two drafts read
differently, and every `$ref` must be a local JSON pointer (the bare-name `$id`
is not a resolvable URL, so a remote ref would send a validator to a host that
does not exist). The fallback is disclosed by a test rather than hidden by a
`try/except`. See the requests below — this same gap fails 33 tests at the
base commit, before any change of mine.

---

## R3 — the two multi-corner sign-off reports declare their stage

### What changed

`programs/phase3_one_shot_runner.py`, **+26 lines, 0 removed, 0 moved, 0
reformatted** — two stanza headers and two lines that feed them.

`_emit_corner_spef_sta._stanza` (`sta_spef_multicorner.rpt`) now emits, after
its `=== SETUP/HOLD ... ===` banner:

```tcl
puts $_f "STA_BASIS: POST_ROUTE_SPEF"
puts $_f "STA_BASIS_LIBERTY: <the liberty this stanza read>"
```

`_emit_mcorner_ocv_sta._pass` (`sta_mcorner_ocv.rpt`) emits the same pair — but
**not the same literal**, because this stanza does not read the same things:

| what the stanza read | stamp |
|---|---|
| routed netlist + a corner SPEF | `POST_ROUTE_SPEF` |
| routed netlist, no SPEF for this corner | `POST_ROUTE_NO_SPEF` |
| synth-netlist fallback, no SPEF | `PRE_LAYOUT_ESTIMATE` |

Its SPEF is per corner and may be absent (`spef_disc = "no-SPEF (netlist-only)"`
was already in the banner), and its netlist falls back to the synth netlist when
no routed one exists. All three values are already in `_sta_basis.BASIS_TOKENS`
/ `_ppa.timing._STAGE_BY_STAMP`, and `POST_ROUTE_NO_SPEF` is a **different
stage** there from `POST_ROUTE_SPEF` — rounding either up to the flattering one
would be exactly the lie the stamp exists to prevent. The two supporting lines
are a `_routed_netlist` flag set where the netlist is resolved.

The liberty differs between the two emitters and each stamp names its own: the
RC-axis report reads ONE process library across its corners, the process-OCV
report reads a different library per corner. A stamp copied from the
single-corner emitter would have named one library for a report that read two.

The fix is in the step's own tool. `_ppa/timing.py::_stage_for` is unchanged and
still refuses to infer a stage from a filename — see the control test.

### The test — by PRODUCING the reports, not by reading the source

`programs/tests/test_multicorner_sta_reports_declare_their_basis.py` — 12 tests.

Each emitter writes a real `.tcl`. The fake `_docker_exec` here runs that `.tcl`
through a real `tclsh` with `proc unknown {args} { return "" }`, so every STA
verb evaluates to the empty string while `open` / `puts` / `close` / `catch` /
`if` are the genuine article. What lands on disk is the emitter's own bytes,
produced by the emitter's own recipe. Every assertion is made on that file.

Produced `sta_spef_multicorner.rpt` (excerpt):

```
# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
# SETUP corner: max-RC   HOLD corner: min-RC
=== SETUP (max-RC corner, SPEF=max, liberty=/pdk/openpdk/.../typ.lib) ===
STA_BASIS: POST_ROUTE_SPEF
STA_BASIS_LIBERTY: /pdk/openpdk/libs.ref/stdcells/lib/typ.lib
...
=== HOLD (min-RC corner, SPEF=min, liberty=/pdk/openpdk/.../typ.lib) ===
STA_BASIS: POST_ROUTE_SPEF
STA_BASIS_LIBERTY: /pdk/openpdk/libs.ref/stdcells/lib/typ.lib
```

Produced `sta_mcorner_ocv.rpt` (excerpt) — note the per-corner liberty:

```
=== SETUP corner: process=SS liberty=.../slow.lib, SPEF=core_top.max.spef ===
STA_BASIS: POST_ROUTE_SPEF
STA_BASIS_LIBERTY: /pdk/openpdk/libs.ref/stdcells/lib/slow.lib
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
...
=== HOLD corner: process=FF liberty=.../fast.lib, SPEF=core_top.min.spef ===
STA_BASIS: POST_ROUTE_SPEF
STA_BASIS_LIBERTY: /pdk/openpdk/libs.ref/stdcells/lib/fast.lib
```

Coverage:

* every stanza of each report is stamped, not just the first — one stamp at the
  top of a two-corner report leaves the second corner undeclared once the two
  are read apart;
* the no-SPEF and synth-netlist-fallback stamps are each produced and asserted;
* THE CONSEQUENCE — the produced report is handed to the real downstream reader,
  `_ppa.backends.opensta.parse_report` → `_ppa.timing._stage_for`, which now
  returns `stage="post_route_extracted"` with `gap is None`, for both reports.
  That is the `stage: null` row the jppa-timing lane had to write, gone;
* CONTROL — `test_the_reader_still_degrades_loudly_on_a_report_with_no_stamp`
  feeds an unstamped multi-corner report to the same reader and requires
  null-with-a-reason. The stage must still come from the stamp and never from
  the filename; if this ever goes green-by-inference, the fix has been undone
  downstream;
* non-vacuity — two tests assert the produced files have real content and two
  stanzas before anything is asserted about their stamps;
* skip discipline — `tclsh` absent SKIPS with a named reason.

### Mutation arm — measured

`git stash push -- programs/phase3_one_shot_runner.py`, re-run:

```
9 failed, 3 passed
```

Red: both `..._declares_its_basis`, `..._every_stanza_...`, both
`..._names_the_..._liberty`, `..._says_no_spef_when_it_read_none`,
`..._says_pre_layout_when_it_read_the_synth_netlist`, and both
`test_the_ppa_timing_reader_now_gets_a_stage[...]`.
Green: the two non-vacuity tests and the degrade-loudly control — correctly, as
none of them depends on the fix.

---

## A/B — by TEST ID, against `origin/land/ppa-tf`

Not by count. The whole `programs/tests` suite was **not** run (measured load
276 / 0 free memory is the standing reason); the selection is every test file
this change can reach, derived by grep over `programs/tests/`: the files that
read `PPA_INTERFACES.md`, the files that read `schemas/ppa/`, the files that
mention `STA_BASIS`, the files that name either STA emitter, the
`readme_ppa_extractor` tests, the runner PPA-function ledger, the chip-agnostic
guard and the program-inventory drift gate — **42 files before, 45 after** (the
three added are mine).

```
before  37 failed, 1015 passed   (bb90724dc, clean tree)
after   37 failed, 1064 passed   (this branch)

NEW failures (after \ before):   (none)
FIXED        (before \ after):   (none)
```

**Zero new failing test IDs.** +49 passing = the three new files.

The 37 that fail on both sides are pre-existing at `bb90724dc` and are listed
under the requests below; none of them is touched by this branch.

Also run green outside the selection: `test_canned_prose_must_not_outlive_the_fact`,
`test_chip_agnostic_guard` (13 passed) — the two hygiene gates a new doc
paragraph and four new files could plausibly reach.

Repo artefacts are English only. No foundry name, process node, SKU or chip
codename appears in any file, fixture or commit message of this branch; the
fixtures use `openpdk` / `Fabric A` / `Vendor One` / `core_top`.

---

## REQUESTS TO THE LANDER

Five, in the shape §6 asks for: things found in files this branch does not own,
or work it deliberately did not do.

### 1. A shipped gate reports a DESIGN FINDING when it cannot load a validator (§1 violation)

`programs/ppa_contract_check.py:158` calls `jsonschema.Draft202012Validator`
unguarded. On any host whose `jsonschema` predates 4.0 — this one ships 3.2.0 —
that is an uncaught `AttributeError`, and an uncaught exception exits **1**.
Measured at `bb90724dc`, before any change:

```
$ python3 programs/ppa_contract_check.py --contract c.json ; echo rc=$?
AttributeError: module 'jsonschema' has no attribute 'Draft202012Validator'
rc=1
```

Per §1, rc=1 in that program means "this contract document is invalid" — a claim
about the design. A run that never loaded a validator made it. This is the exact
defect §1 was written against ("two shipped gates refused with a bare
`SystemExit`"), in a third gate. It wants rc=3 (BAD INVOCATION / internal error)
with a `[REFUSE]` marker, or an explicit dependency floor. Contract lane's file;
not touched here.

### 2. The same gap makes 33 test IDs red at the base commit

All 33 non-inventory baseline failures in the A/B above trace to it:
`test_ppa_metrics_schema_agreement.py` (20), `test_ppa_contract.py` (12),
`test_ppa_contract_fixtures.py` (1). They are red on `origin/land/ppa-tf` with a
clean tree. Either pin `jsonschema>=4` for the suite, or give those tests the
disclosed-fallback treatment `test_ppa_readme_hint_schema.py` uses. This is a
dependency decision, not a code fix, which is why it is a request.

### 3. Two docstrings in `_ppa/` now describe the pre-R3 tree

Both are the timing lane's files and both are now stale in their factual claims:

* `programs/_ppa/backends/opensta.py`, module docstring: lists dialect C as
  "the only dialect that stamps its own basis", and shows the A and B samples
  without a stamp. A and B now stamp.
* `programs/_ppa/timing.py`, `_stage_for` docstring: "the two MULTI-corner
  sign-off emitters ... stamp nothing at all". They do now.

The **behaviour** both paragraphs justify is unchanged and still right — the
stage is read from the stamp and never inferred from a filename, and
`test_the_reader_still_degrades_loudly_on_a_report_with_no_stamp` keeps it
honest. Only the measured claims have expired. Left for the owning lane rather
than edited here.

### 4. `_ppa/backends/exec.py` is named but does not exist yet

R1 assigned the ownership; it did not do the extraction. The eleven helpers
(`_docker_exec`, `_docker_exec_raw`, `_container_mounts`, `_to_container_path`,
`_container_cpu_seconds`, `_tool_version`, `_tool_from_command`,
`_split_shell_chain`, `_log_invocation`, `_hash_declared_outputs`,
`_tool_status_not_the_log_sinks`) are still in the runner. Whoever moves them
owns that A/B. Note that `programs/tests/test_ppa_runner_extraction_ledger.py`
already permits the ledger to SHRINK freely, so the extraction needs no change
there.

### 5. The generated counters are stale, and this branch adds to two populations

`programs/tests/test_program_inventory_no_drift.py` is red at `bb90724dc` with a
clean tree (4 IDs, including `test_stated_counts_in_the_documents_match_the_tree`
and a not-a-count sentence, "and all 56 EDA/device tools", that has been
reworded out of its document). That is pre-existing.

This branch adds 3 files to `test_files` and `programs_tree_all_py`. Both
counters and `programs/INDEX.md` are lander-owned and generated, so they were
NOT regenerated here — regenerating against one base produces a manifest that
matches no merged tree. Regenerate after this lands, together with whatever else
lands in the same batch.
