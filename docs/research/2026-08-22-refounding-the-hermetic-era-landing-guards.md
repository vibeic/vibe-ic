# Re-founding the thirteen hermetic-era landing guards — a PROPOSAL

**Status: DESIGN ONLY. Nothing here is implemented and no protected path is
touched by this document.** It exists so the policy call in
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

Proposed: assert on the **arm receipt**, which the parent already has and already
validates. `A2.started` becomes *"the A2 receipt exists, its `arm` field is A2,
and its `completion` is complete"*. Strictly stronger than the marker — the
receipt is digest-attested and the marker was an empty file anyone could touch.

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

What remains genuinely unverified, and stands: none of this is implemented or
run, and the judgement that a receipt-based liveness check is *sufficient* for
what G6 wanted is mine, not a measurement.
