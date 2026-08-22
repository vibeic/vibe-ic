# The protected tuple is not checked on the path landings actually take

Measured 2026-08-22 at `origin/main` 81cd5321b.

## THE STATE

`origin/main` right now matches **neither** authorised atomic state of its own
`tools/ci/protected_landing_transition.json`. Two of the 47 protected paths have
drifted from both:

    vibe-ic-marketplace/plugins/vibe-ic/programs/landing_merge_verdict.py
    tools/ci/repo_hygiene_gates.sh

Neither drift was announced by anything. They were found by running the shipped
validator by hand.

## WHY NOTHING CAUGHT THEM

    tools/gatekeeper-land.sh              0 references to protected_landing_transition
    tools/ci/repo_hygiene_gates.sh        1 — and it is a COMMENT, not a gate
    tools/gatekeeper-verify-merge.sh      9
    tools/gatekeeper-land-differential.sh 2

The validator exists, is thorough, and is wired only into the **differential and
verify-merge** paths. The plain lander — the one the owner's own ruling of
2026-08-21 identified as "the ONE path every landing actually takes, so it is
the only place where wiring it makes the check unavoidable" — does not consult
it at all. Neither does the hygiene set.

So a landing that moves a protected path and carries no transition is not
refused. It lands, main drifts, and the next reader finds out when some
unrelated protected-path operation refuses with a message that names neither the
file nor the landing responsible.

## IT IS NOT RARE

Every queued batch, scanned against the 47 paths:

    land/batch67-assembled       4 protected paths moved   no transition
    land/batch68-assembled       0                          n/a
    land/batch69-assembled       0                          n/a
    land/batch70-assembled       4                          no transition
    land/batchbig-assembled      8                          no transition

Three of five. This is how the batches are being assembled, not an oversight in
one of them — and it is the same mechanism that produced the two drifts already
on main.

## THE SHAPE, WHICH IS FAMILIAR

This repository has a validator nobody on the landing path calls. That is the
same defect the deadline row spent a week on: `gate_red_since_check` was correct,
tested, and reachable only through a program no workflow, hook or script ran.
The remedy was identical in form — the owner ruled it into
`tools/gatekeeper-land.sh`, because that is where a check becomes unavoidable.

The protected-tuple check wants the same ruling. It is not made here: the lander
is itself a protected path, so wiring it is a protected-path change, which needs
a transition — and the transition machinery is what is currently unenforced.
That is not circular in practice (a PREPARE can carry it), but it is an ordering
the owner should choose deliberately rather than discover.

## WHAT IS READY

`agent/jrows-prepare-for-batchbig` re-authorises both drifted paths by ZERO
bytes and declares the eight `land/batchbig-assembled` moves. Verified with the
shipped validator at both ends, and re-verified after the batch moved. Because
batchbig is a strict superset of 67 and 70, that one PREPARE covers all three.

---

## THE MACHINERY IS DEADLOCKED ON MAIN, AND THE WAY OUT IS MEASURED

Run the shipped verifier — `protected_landing_transition.py verify` — with
`--base origin/main` and EVERY candidate on offer:

    candidate = the batchbig PREPARE   rc 2  protected tuple matches neither authorised atomic state
    candidate = land/batchbig-assembled rc 2  (same)
    candidate = agent/jrows-eight-rows  rc 2  (same)

Nothing can verify against today's main. The reason is in `build_receipt`: it
establishes `base_state_id = _match_state(base_files, base_manifest)` BEFORE it
looks at the candidate at all, and main's own manifest recognises neither of
main's two possible states. So the refusal is about the BASE, and no candidate
can route around it.

`bootstrap` is not the escape: `:598` refuses a base that already carries a
manifest, and main carries one. It is for first adoption, not repair.

**So the protected-landing machinery has been unusable on main since the first
drift — which is exactly why three queued batches were assembled without
transitions. The mechanism was not ignored; it was unavailable.**

### THE WAY OUT, PROVEN

The PREPARE must land through the plain lander, which does not verify. That is
not a bypass — it is the only door, and it is the same door the drift came
through. After it lands:

    the PREPARE commit, under the manifest it carries
        -> reauthorised-at-81cd5321b        (main is a RECOGNISED state again)

and then batchbig, rebased onto it, verifies as a legitimate ACTIVATE. Measured,
with real candidate worktrees and the shipped verifier writing a receipt:

    [PASS] protected landing transition: ACTIVATE reauthorised-at-81cd5321b
                                                  -> batchbig-assembled
        operation : ACTIVATE
        from      : reauthorised-at-81cd5321b
        to        : batchbig-assembled

One correction to how I first tested this, because it is an easy trap: verifying
`--base <PREPARE> --candidate <batchbig branch as it stands>` refuses with
"PREPARE changed live protected bytes with the manifest". That is the harness,
not the transition — the raw branch still carries the OLD manifest, so
`build_receipt` reads it as a PREPARE rather than an ACTIVATE. The candidate has
to be batchbig REBASED onto the new base, which is what a landing actually does.

### ORDER

    1. agent/jrows-prepare-for-batchbig   via the plain lander (breaks the deadlock)
    2. land/batchbig-assembled            rebased onto it — verifies as ACTIVATE
    3. agent/jrows-on-batchbig            no protected paths, no pair needed


---

## THIS DELTA, MEASURED AGAINST THE BATCH IT LANDS ON

Two arms over the 72 non-matrix files `ci_targeted_test_select --base
origin/batchbig` picks for the 14 this delta changes, run at host load 6 after
three deferrals at loads of 26, 61 and 90 — a wall-clock minimum and several
gates in this repository are demonstrably load-sensitive, and a measurement
taken while the machine is saturated is not one:

    base (land/batchbig-assembled 0617b1dc6)   2 failed / 1934 passed
    candidate (this delta)                     1 failed / 1978 passed

    NEW on the candidate            0
    only on the base                1

The one only-on-base id is `test_the_bound_is_what_refuses_and_not_some_other_clause`,
and this delta genuinely FIXES it — deterministically, confirmed twice on each
arm (base fails 2/2, candidate passes 2/2). The cause is not luck: the batch
carries the pre-ceiling version of that test, which reports "its stated bound is
not what is deciding this" for a row where the CEILING is deciding — and the two
corpus rows are now 501 behind against `MAX_BOUND_COMMITS = 500`, so they walk
straight into it.

The one failure remaining on the candidate is on BOTH arms: batchbig's ninth
row, `PPA head-to-head records (cross-layer campaign)`, carries no
`bound_because`. Not introduced here, and not mine to fill in.

The three `test_matrix_*` files in the selection were run separately, one pytest
call each, and are **identical on both arms** — 6 failures, the same six
`test_d3_required_outputs_are_produced[stepNN]` ids, base and candidate. So the
selection is measured in full rather than in the part that was cheap to run:

    test_matrix_d1_wiring.py               82 passed          both arms
    test_matrix_d3_outputs_produced.py     6 failed, 52 passed  both arms
    test_matrix_d7_outputs_list_complete.py 97 passed          both arms

They are split out because that family is the one this repository records as
killing a session under load; at these sizes (4 s, 24 s, 34 s) they cost about a
minute an arm, which is why they could be run at load 55 when the 72-file arms
could not.
