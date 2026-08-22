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
