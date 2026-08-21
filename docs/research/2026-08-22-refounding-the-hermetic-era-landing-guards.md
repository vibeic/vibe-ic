# Re-founding the thirteen hermetic-era landing guards — a PROPOSAL

**Status: design A is now IMPLEMENTED on this branch (see the tail of this
document). B, C and D remain design only.** It exists so the policy call in
`2026-08-21-main-red-triage-v1_11_66-findings.md` (escalation 3) can be decided
against a concrete alternative instead of in the abstract.

## The problem, in one paragraph

Thirteen end-to-end guards in `test_landing_merge_verdict.py` do not exercise the
properties they name. One root cause — the landing arms became hermetic — through
two mechanisms: ten depend on test-only env knobs that
`_LAND_REVIEWED_ENV_NAMES` correctly scrubs, and three plant tampers that a
read-only object-exact subject correctly defeats. **The runner is right in both
cases.** The guards are addressed to a world where the arm inherited the parent's
environment and ran in a mutable checkout.

The obvious repair — add six names to the allowlist and bind-mount a host probe
directory — is the one option I recommend AGAINST. It punches a test-only hole
through the isolation boundary that produces the property being tested, in the
landing gate, on protected AUTHORITY/RUNTIME paths. A guard that requires
weakening the thing it guards is not a guard.

## What already crosses the boundary, legitimately

No new channel is needed. Four exist and are attested:

| channel | carries | direction |
|---|---|---|
| arm receipt (`hermetic_landing_arm_receipt.py`) | `arm`, `artifacts` (path/digest/size/permissions), `result_exit_code`, `completion`, `inputs`, `mount_sources` | arm -> parent |
| `/evidence` volume | anything the arm writes; published via `publish_validated_arm_artifact` | arm -> parent |
| `landing_completion_record.py` | per-gate journal, `append --state PASS\|FAIL\|SKIP\|REPORT` + `finish` | arm -> parent |
| `GATEKEEPER_VERIFY_ARM` | arm identity | parent -> arm (already forwarded) |

Plus one the tests already control and have been ignoring: **the subject tree and
the corpus are inputs.** A condition expressed as data crosses; a condition
expressed as an env flag does not.

## The four re-foundings

### A. "Did arm X actually run?" — replaces the `.started` markers (G6 + 3 others)

Today: the stub writes `$PROBE_DIR/${ARM}.started` to an unmounted host path.

**CORRECTED.** My first version of this said "assert on the arm receipt". **That
is not implementable and I should have checked before recommending it as the
cheapest item.** The receipts live under `RUN="$(mktemp -d -t gkverify.XXXXXX)"`
(`gatekeeper-verify-merge.sh:276`) — a directory the verifier creates for itself
and never tells the caller about. `_verify()` returns only the process result and
the `--json` verdict document. A test has no path to those files.

The real answer is better, and it was already in front of me: **the verdict
document itself carries per-arm evidence**, and one existing test already uses it
as a liveness check —

```python
assert doc["base_land"] is not None, "arm A2 never ran, so the gate tier was asserted"
```

(`test_end_to_end_a_known_good_branch_is_allowed`, green in both lanes today.)

So all four arms are observable from the object `_verify()` already returns:

| arm | assertion | source |
|---|---|---|
| A2 | `doc["base_land"] is not None` | `landing_merge_verdict.py:1838` |
| B2 | `doc["land"] is not None` | `:1831` |
| A1 | `base_total > 0` | `:404` |
| B1 | `candidate_total > 0` | `:405` |

No receipts, no temp directory, no env knob, and **no new plumbing of any kind** —
the data already crosses and one test already reads it.

**Second correction: A closes ONE test, not four.** I wrote "G6 + 3 others"
without checking. Only G6 asserts `.started` markers; the other `.started`
reference is inside the planted stub, and `cleanup.started` is a different,
host-written, working channel. A is still first in the order — it is now nearly
free — but it is worth one test, not four, and the escalation should be read
with that number.

### B. The interrupt/cleanup guarantee (G4, both tests)

This is the one I previously called unfixable, and I was wrong about why. The
blocker I named was `os.kill(arm_pid, 0)` — a host-namespace assertion about a
container-namespace process. That blocker is real but **irrelevant**, because the
property is not "that PID is gone", it is "the arm was reaped and left nothing
behind". Both halves are observable from the host without the pid:

1. **The container is gone** — CONFIRMED FROM SOURCE, and better than I first
   wrote it. `hermetic_candidate_runner.py:1889` passes
   `--label ai.vibeic.hermetic-run=<run_id>` on create, and `:749-751` VALIDATES
   that label back from `container inspect` and refuses on mismatch — so the
   label is load-bearing already, not incidental. Better still, the
   infrastructure containers carry DISTINCT labels:
   `ai.vibeic.hermetic-provision` (`:1086`) and `ai.vibeic.hermetic-export`
   (`:1147`). So the assertion can name the candidate container exactly —
   `docker ps -a --filter label=ai.vibeic.hermetic-run=<run_id>` empty — without
   the name-substring fallback M15's test had to use.
2. **The worktrees are gone** — already asserted today, already works.
3. **Cleanup announced itself** — `cleanup.started/reaped/done` are written by the
   VERIFIER on the host and already work. M13 measured exactly this: those three
   markers appear, and only those.

The TERM-ignoring arm still needs planting, and it can be, without any env knob:
commit a **sentinel file into the subject tree** and guard the stub's hang on
`[ -f /subject/<sentinel> ] && [ "$GATEKEEPER_VERIFY_ARM" = "B2" ]`. The tree
crosses (the runtime snapshot is materialized from the clone's base) and
`GATEKEEPER_VERIFY_ARM` is already on the allowlist. It cannot fire in a real
landing, because a real base does not carry the sentinel — which is a stronger
safety property than an env flag, since an env flag can be set by accident and a
committed sentinel cannot.

### C. The three tamper guards

The tamper is already defeated structurally. Two changes make the guards say so:

1. Assert the **structural** property directly — the arm's binds are read-only.
   This is done: M15 added `test_a_read_write_subject_bind_refuses_before_the_candidate_starts`
   with a proven mutation arm, and it passes in both lanes.
2. Re-point the three tests at the OUTCOME rather than the exit code: assert the
   verified **tree digest** in the receipt equals the expected one — i.e. the
   tamper did not take — and that the refusal names the planted test as a new
   failure. Changing `rc == 2` to `rc == 1` **alone** is not acceptable: it turns
   them green while they still tamper nothing, which is a hand-added green that
   cannot fail.

### D. The corpus-transition pair (G5 and the M14 test)

Today both express "the corpus is expanded" as `GATEKEEPER_STUB_ROUTED_TRANSITION=1`,
an env flag that cannot arrive.

Proposed: express it as **data**. `--corpus` is a real mount the test already
controls; supply a base corpus and a candidate corpus that genuinely differ. The
transition is then computed by the real producer from real inputs, which is what
the test claims to be testing. This also retires the `.get(..., [])` that M14
had to harden, because the key will be present when the producer actually runs.

### D's feasibility is UNVERIFIED — flagged before someone builds it

Design A was ranked first and specified against an artifact no test can reach. I
corrected it only because I went looking. **D rests on the same kind of
assumption and has not had the same check**, so it is flagged here rather than
left for whoever picks it up.

D says: express "the corpus is expanded" as data, by giving the base arm and the
candidate arm corpora that genuinely differ. Whether a TEST can make them differ
is the open question, and the source points both ways:

* **For:** `gatekeeper-verify-merge.sh:798` materializes the B2 corpus with
  `--checkout "$BENCHMARK_B2" --subject-repo "$WT_CAND"` — the checkout is built
  with reference to the CANDIDATE subject worktree, so materialization is
  subject-aware, and `BENCHMARK_A2`/`BENCHMARK_B2` are genuinely separate trees.
* **Against:** `:1237` passes a single `$BENCHMARK_SHA` for both, and `_verify()`
  supplies exactly one `VIBE_IC_BENCHMARK_DATA` checkout. On that reading the two
  directories exist for ISOLATION — which is precisely what
  `..._b2_corpus_mutation_is_post_attested_and_norecord` guards, that B2 cannot
  mutate what A2 reads — and not for differing content.

Both cannot be right about what a test controls. The system must support an
EMPTY→expanded transition somehow, because that is G5's whole subject; what is
unknown is whether a test can DRIVE it, or whether it only arises from a real
benchmark-data pin moving between two real commits.

**The question to answer before building D:** does the A2 corpus ever differ in
CONTENT from the B2 corpus in a single verification, and if so, what makes it
differ — the subject tree, the benchmark-data pin, or something the test cannot
reach? If the answer is the third, D is not implementable as written and the two
corpus tests need a different re-founding than the one proposed here.

**The general rule this earns, and it applies to B and C as well as D:** every
"just express it through channel X" claim in this document needs channel X
checked before the item is ranked. A survived that check only after being
rewritten. B's channel is confirmed (the container label, from source). C's is
confirmed (M15, implemented and passing in both lanes). **D's is not.**

## What this costs, honestly

* Thirteen tests rewritten, in a file inside the protected closure. Not small.
* **B and D need a fixture that can supply two corpora and a sentinel commit.**
  That is new test scaffolding, not a one-line change.
* C partially exists already (M15).
* A is the cheapest and closes four tests.

**Suggested order: A, then C, then D, then B** — cheapest and most independent
first, and each is separately landable.

## What I did NOT verify

**RETRACTED CAVEAT.** I first closed this document by saying the container label
in B was read only from the fake-docker profile, that the real runner's behaviour
was unconfirmed, and that this host could not check it. All three were wrong, and
one grep settled them: the label is set at `hermetic_candidate_runner.py:1889`
and validated at `:749-751`, which is a source fact requiring neither the strong
tier nor a live daemon.

**"This host cannot check it" is a claim like any other and needs testing before
it is written down.** That is the same lesson as the retractions in the findings
document, arrived at once more — this time while writing a caveat rather than a
finding, which is if anything the easier place to be careless.

**SECOND RETRACTED CAVEAT.** I also wrote that "a receipt-based liveness check is
sufficient for G6" was my judgement rather than a measurement. That caveat is
obsolete because the design it hedged is gone: receipts are unreachable from a
test, and A now rests on `doc["base_land"]`/`doc["land"]`, which an existing
green test already asserts for exactly this purpose. The hedge was on the wrong
sentence — the thing I should have checked was not whether receipts were
*sufficient* but whether they were *reachable*, and they are not.

What remains genuinely unverified, and stands: **none of this is implemented or
run.** B and D still need new fixture scaffolding (a sentinel commit; a two-corpus
fixture), and neither is sketched here beyond the mechanism.


# ===== A: IMPLEMENTED =====

`test_end_to_end_candidate_wave_precedes_parallel_isolated_base_wave` is
re-founded and **renamed** to `test_end_to_end_every_arm_of_both_waves_actually_ran`.

It now asserts all four arms from the verdict document — `base_land` (A2),
`land` (B2), `base_total > 0` (A1), `candidate_total > 0` (B1) — and no longer
touches the probe directory. **RED before, GREEN after**, and the green is
earned: it is stronger than what it replaces, because a marker proved an arm
STARTED and a record proves it COMPLETED.

**The assertions discriminate** — this is not a green that cannot fail.
`base_total == 0` is an explicitly guarded and disclosed condition
(`landing_merge_verdict.py:121`, `:848`), and `base_land is None` is a real
branch (`:1213`) that the document emits as `null` (`:1838`). All four read
values that genuinely take the failing value.

**What I did NOT restore, and said so in the docstring:** ordering. The old name
promised "B1/B2 finish before A artifacts exist; A1/A2 then run in parallel", and
**marker existence never showed that either** — the markers were liveness, and
the verdict document carries no timestamps. So the test was mis-named relative to
its own assertions before the hermetic migration, not because of it. I renamed it
to what it actually checks rather than leave a name that over-promises. A real
ordering guard needs per-arm completion times, which `landing_completion_record.py`
could carry but does not surface to the verdict today. **That is a genuine
reduction in claimed coverage and it should be read as one** — the coverage was
never there; only the claim was.
