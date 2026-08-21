# CAPTURE — the matrix, the flow, and the landing machinery

Branch `jcap/matrix-capture`, cut from `origin/main` **`e36d81c0a`** (v1.11.33).
Nothing pushed to main. No plugin version bumped. No baseline written. No gate
implemented — this pass produces the RECORDS and the emitted sketches.

    benchmark-data/capture/2026-08-21-jcap-matrix/
      recoveries.json                                 11 records
      candidates/bucket_A_*_rule_sketches.py          10 sketches, routed per step
      candidates/bucket_C_backlogs/ORGANIC-*.yaml     1 backlog
      candidates/summary.json

Emitted with:

    python3 programs/enhancement_emit.py \
      --records recoveries.json --out-dir candidates/

It accepted all eleven on the first run. No field was scrubbed and no refusal was
worked around: every record was written as a general PATTERN from the start, with
every identifier either in backticks or replaced by the thing it names.

## Where the numbers come from

**The working checkout is v1.10.39; every measurement in these records was taken
on `e36d81c0a` (v1.11.33)**, in a detached worktree, because that is the tree the
lanes describe. The emitter stamps `plugin_version` from the manifest of the
plugin *doing the emitting*, so left alone it would have written `1.10.39` onto a
record whose evidence is a different tree. Each record therefore carries an
explicit `plugin_version: 1.11.33` and a `measured_on_commit` field. That is the
field working as documented — the author-supplied value wins — and it is worth
saying out loud, because a provenance field that silently names the emitter's
tree instead of the measured one is unreadable as wrong.

## Count per bucket

| bucket | n | |
|---|---:|---|
| T — forked EDA tool | **0** | see "the one I did not file" below |
| **A — deterministic rule** | **10** | the default, and where everything landed |
| B — needs natural-language judgment | **0** | nothing in this cluster needed it |
| C — right bucket, large engineering | **1** | with `why_not_bucket_a` |
| D — non-generalizable | **0** | |

Ten of eleven are Bucket A. That is not a flattering result, it is the cluster:
these lanes were all measuring machinery against itself, and machinery is exactly
what a structural predicate can read.

## The records

Each names the measurement that produced it, and answers both halves of the
question the skill exists for — would it have fired on the ORIGINAL defect, and
would it fire on a DIFFERENT instance of the same class.

### The richest seam — declared, wired, selected, and stopping nothing

Four lanes hit this from four directions in one day. The brief asks whether ONE
rule can find the rest by construction rather than by somebody noticing. It can,
and the discriminator is structural.

**A1 · registry is the iteration domain.** An enforcement whose finding-emitting
loop iterates an opt-in registry examines only what somebody volunteered. Empty
registry, clean verdict, denominator zero — and the verdict is byte-identical to
one earned by inspection.

Measured on `e36d81c0a`: **29** tracked registry files scanned, **3** with every
collection empty, and the structural test separates them cleanly —

| registry | rows | structure | verdict |
|---|---:|---|---|
| `gate_red_since.json` | 0 | finding-emitting `for row in ledger` at line 194 | **the defect** |
| `tool_diagnostic_id_acceptance.json` | 0 | consulted inside a loop over derived entries | correct filter |
| `tracked_symlink_target_baseline.json` | 0 | no finding-emitting loop over it | correct filter |

1 finding, 0 false positives. Beside it, on the same commit: the hygiene suite
reports `declared 85 | ran 85 | decided 75 | PASS 67 | FAIL 8 | NOT_CHECKED 10`
— eight live reds, zero acknowledgement rows, and the gate exits
`[PASS] every red is NEW or owned by a live, unexpired acknowledgement`. The
deadline lane found the line where the bound is read; this is the line that
decides it is never reached, and it is findable without knowing either.

**A6 · spawned gate whose status is discarded.** Two instances, two lanes:
`phase3_one_shot_runner.py:40886` spawns the compliance checker with
raise-on-failure off, binds no result, and sits inside a handler that catches
everything — under a comment calling it *"This direct, BLOCKING flow_compliance
re-run."* And `full_suite_run_check.py`, 294 lines, measured 0 occurrences of
`subprocess`, `Popen`, `check_output`, `os.system`, `returncode` and `rc`: a gate
whose subject is whether a run happened, with no way to start one or read one.

**A4 · invocation proved by parse not by text.** `flow_step_executor_coverage_check.py`
contains no syntax-tree parse; it concatenates the runners and applies a regular
expression to **3,055,921** bytes of which **1,472,929 (48%)** are docstring and
comment. Its own docstring says a step with no dispatching producer *"can only
ever be MISSING, and that is the root cause of middle steps silently skipped"* —
which is what happened: three producers declared by two path steps appear **zero**
times in any runner on this commit, in code tokens or in prose tokens. A second
lane measured the mirror on the consumption side: 5 of 7 runners name the
compliance checker in prose only, and a text scan graded 3 of them as consumers.

**A3 · declared invocation accepted by its own parser.** The exit status a parser
returns when it refuses is the same status this flow reserves for input-not-
applicable, so a misdeclared invocation scores in a passing tier forever and the
failure points the wrong way — the worse the run, the more certainly it passes.
Measured: **113** declared clauses, 1 static candidate, and driving that program's
parser shows it is a subcommand false positive, so the live count is **0 of 113**.
The class did occur (a release-documents generator, twice among 24 findings) and
its sibling population is not clean: **36 of 246** umbrella-registered checkers
reject the argument vector the umbrella builds.

**A2 · declaration searched only inside a truncated window.** Control pair driven
through the real predicate: a byte-identical declaration returns `blocking` at
byte 26 and `None` at byte **5121**. On this commit 42 of 42 declarations sit
inside the window, so the rule adds no finding today and prevents the 43rd — the
class occurred at byte **8249** and was reported as *"declares no intent at all"*.
Second shape, another lane: a fixed-width TAIL window whose verdict flips between
a 30-character and a 40-character scratch root. Sweep denominator: **44** head
slices of 100 characters or more.

**A7 · content-pinned authority verified only at merge.** **47** protected paths
carry content hashes; the repository-wide hygiene script mentions the manifest
exactly once and that occurrence is a COMMENT. The obligation is real, correct,
and arrives at the one person who cannot act on it. Signal is **WARN** on purpose:
a mismatch on a branch that edits an authority path is the expected state, and
blocking would refuse the change the manifest exists to record.

**A8 · reference control resolved through a mutable ref.** A control has to be
built from a state that stays vulnerable. Syntax-tree census: **31** revision-
reading process calls, exactly **1** resolving a branch-shaped name in a revision
position — live on this commit — and the other 30 read the working-tree pointer
against a fixture the test just created, correctly not flagged. The naive form of
the same search returns 15 sites across 12 files, **13 of them prose**. A second
lane hit the same class from the coverage side: a guard whose subject set comes
from a diff against that same moving name collected 116 cases in one clone and 12
in another, off one tree.

### The second seam — population pins

**A5 · population pin without its member set.** POSITIVE CONTROL, driven through
the repository's own accessor: the live flow yields **69** step ids; applying ONE
departure and ONE arrival to a copy yields **69** again. The count is unchanged;
the member set changed, symmetric difference of exactly two ids. Census over the
matrix family: **9** population pins, **0** member-set pins — 9 of 9 blind to a
compensating change by arithmetic, not by accident.

That is the shape the brief describes. It occurred: one lane found three
coexisting populations for one grid (67, 68, and 68 in a published figure) against
a live 69, delta measured as two arrivals and one departure, with the pins
*"restated for the departure only."* A second found a kind-by-kind pin stale in the
same move as its own sum, invisible because the sum asserted first. A third is not
drift at all — a pin that **never matched the tree it was written against**, proven
by an empty diff of both its inputs between the authoring commit and the
measurement. The fix_action carries the one-sided variant too: a membership
assertion placed inside the branch that filters INTO a population can only ever
see a member arriving.

### The other two

**A9 · denial that constitutes the value it appears to negate** (routed to the
fact extractor). A blanket denial check inverts the sentences in which the denial
IS the value. Measured: a lane fixed 2 of 3 offending extractors and measured the
third repair failing — the same guard broke **4** previously passing tests, because
the fixture sentence granting freedom spells that freedom with a denial. Reverted,
and left open rather than closed with a repair that inverts what the function
exists to read.

**A10 · wall-clock bound standing in for a verdict** (WARN). One identifier
appeared as a NEW red on a candidate arm and was not one: re-run serially in
isolation on an idle host at load 2.9 it measured **8 of 8 failing on BOTH arms**,
so the base arm's green in the family run was a FALSE GREEN. Its diagnostic reads
*"did not advance for > 0.45s — killed as hung, not slow."* A single sample per side
would have filed it as damage the change had done.

### The one C, with the sentence the ladder demands

**C1 · a landing's gate verdict is not recoverable from the repository.**

> A deterministic rule can detect a missing attestation trailer, but there is no
> trailer to detect: the landing tool must first be changed to write its verdict
> into the commit, and every commit already on the branch needs a stated
> disposition before any rule can refuse anything. The exact input a program would
> see today is a commit message whose only evidence is a free-text sentence
> somebody chose to type, and no predicate over that text can distinguish a
> landing that ran the gates and passed from one that never started them.

Measured: **16 of 16** commits in one batch carry a skip statement verbatim in the
commit body — including one whose body also records that an earlier round was
refused for three new reds. The commit that introduced the flow step behind a whole
family of failures carries no gate statement at all. The local marker the landing
tool writes is **absent** from the clone and never enters a commit; the hook
directory holds only sample files with no override configured, so the bypass lane
was never armed and a plain push would have enforced exactly as much as a forced
one.

The emitted YAML is left in `candidates/bucket_C_backlogs/` and **not** copied into
`community/backlogs/`: that zone is the field-agent's, and the scope guard denies
writes to it from any other identity. Filing it is one `cp` and a field-agent.

## ALREADY-PROGRAM — what I found and what enforces it

Grepped `programs/` before writing any record. These are real, and none of them
got a duplicate sketch:

| the rule | the program that already enforces it |
|---|---|
| a gate nothing invokes | `gate_is_wired_check.py` (blocking on a NEW unwired gate) |
| a checker only its own test runs | `checker_execution_wiring_audit.py` (blocking on a NEW test-only checker) |
| a declared invocation the program's parser refuses | `p0_gate_invocability_drift_check.py` — **over the umbrella registry**, 36 of 246 non-invocable, recorded as a VERDICT not a skip |
| a check disabled by exactly the situation it was written for | `flow_condition_reachability_check.py` |
| a comment or docstring counted as a declaration | `hdl_declaration_scan_strips_comments_check.py` — **for hardware-description scans** |
| a prose-reading extractor that ignores polarity | `prose_polarity_consulted_check.py` (live, and red on the shipped tree) |
| the polarity scope itself | `_prose_polarity.sentence_scope`, two callers |
| an ERROR diagnostic no verdict reads | `error_diagnostic_consumed_check.py` |
| producer tokens a consumer's mapper never recognises | `verdict_token_propagation_check.py` |
| an assertion pinned to a corpus census | `corpus_cardinality_pin_scan.py` |
| stated counts in bound documents vs the tree | `gen_program_inventory.py --check` (caught five clobbered lines in a shipped document) |
| a declared path with no manifest entry | `d3_manifest_declaration_parity_check.py` |
| a non-atomic write to a declared report | `atomic_artifact_write_check` |
| a blocking clause no input can redden | `test_matrix_d2_falsifiable.py` — it found the step-33 clause itself |
| a derived figure gone stale | `tools/gen_matrix_63x8_census.py --check-figures`, ~1.07 s |

**Three of my records are population extensions of a program that already exists,
and each says so in its own `notes`:** A3 extends the invocability probe from the
umbrella registry to the flow document; A4 is the comment-stripping discipline the
hardware-description scan already enforces, applied to the program-invocation
population; A9 is the piece missing from the polarity gate's own remedy. Building
any of them as a new standalone checker would be the duplication the skill warns
about.

**One correction to the wiring picture, for the implementing lane.** A1 is *not* a
duplicate of the two wiring audits. Both of those ask whether anything invokes a
gate, and both are satisfied here: the gate IS invoked, runs, and returns. The
uncovered question is what its verdict was computed over.

## The one I did NOT file, and why

`test_a_pinless_abstract_is_never_staged` — a layout tool exiting on a signal
rather than returning a diagnostic status — reads like Bucket T. It is not filed.
The independent triage measured it at **image 4 of 13, host 13 of 13**, and the
lane that saw the crash saw it once and wrote down that the message is *"a symptom
on 4 draws in 13, not a proven mechanism."* Bucket T requires a golden sample, a
bad sample and a concrete tool enhancement; I have one draw and no golden. Filing
it would assert a mechanism nobody measured, which is worse than not filing it.
It belongs to whichever lane decides which arm tells the truth, and that decision
is named in that lane's own hand-off.

There is no Bucket D. Nothing in this cluster is non-generalizable, and none of
the four forbidden reasons applies to any of it.

## For the lane that implements these

* **The sketch signature is the emitter's template, not the contract.** Every
  Bucket-A sketch comes out as `rule_<name>(sample_text, ports)`. Nine of these
  ten rules take a tree or a path, not a sample and a port list. Take the
  `pattern` and the `fix_action`; the signature is scaffolding.
* **Four of the ten currently find zero on `e36d81c0a`** — A2 (42 of 42 inside the
  window), A3 (0 of 113), and the compensating case of A5 (which is invisible by
  construction, which is the point). They are re-entry guards, and each record
  states the instance that DID occur so nobody has to take the zero on faith.
* **Six find at least one live instance today**: A1 (1), A4 (3 undispatched
  producers), A5 (9 of 9 count-only pins), A6 (2), A7 (47 paths unguarded before
  merge), A8 (1).
* **A3's subcommand resolution is load-bearing, not a refinement.** The static
  form reports exactly one false positive on the declared population, and it is a
  program whose modes are subcommands. Resolve them or the rule ships a lie.
* **A7 is WARN and must stay WARN.** Blocking it refuses the change the manifest
  exists to record.

## Compliance

* Branch pushed; `main` not touched, not pushed to.
* No version bump: `plugin.json` and both marketplace manifests untouched.
* No `--write-baseline` on any gate. No `UNREDDENED` registration.
* No gate implemented and no gate weakened.
* Added lines scanned: English only; no foundry name, process node, SKU or
  codename; the only PDK identifiers anywhere in this branch are open ones.
