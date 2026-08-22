# Repairing the deadlocked protected tuple — rehearsed end to end

Measured 2026-08-22 against `origin/main` `a4caccefe` (v1.11.69).

## THE STATE THIS REPAIRS

`origin/main` matches **neither** authorised atomic state of its own
`tools/ci/protected_landing_transition.json`. Eleven of the 47 protected paths
differ from both. `build_receipt` establishes the BASE state first —

    protected_landing_transition.py:512
        base_state_id = _match_state(base_files, base_manifest)

— which runs before the candidate is considered at all. So with `base=main`
**every** call refuses, whatever the candidate is:

    base=origin/main candidate=origin/main   -> Refusal: protected tuple
                                                matches neither authorised
                                                atomic state

main cannot produce a receipt against itself. There is no STEADY, no PREPARE
and no ACTIVATE from here, and bundling the repair with a real protected move
does not help, because the refusal is on the base.

`build_bootstrap_receipt` is not a way out either: it refuses a `trusted_base`
that already carries a manifest (:598) and requires a `phase_a` whose live
tuple already equals `current` (:604). main is neither.

## THE REPAIR, AND THE PROOF THAT IT WORKS

Re-authorise the tuple: author a manifest whose `current` IS main's real
47-file tuple, and whose `next` is the state the next genuine protected change
produces. `parse_manifest` refuses `current.id == next.id` (:327) and a `next`
identical to `current` (:333), so the repair MUST name a real forthcoming
move — it cannot be standalone housekeeping.

Rehearsed in a throwaway worktree, with a synthetic one-line change to
`tools/ci/_gate_dispatch.sh` standing in for that move:

    P = repair commit   (manifest only, moves no protected byte)
    A = the protected change, landed on top of P

Result, using the shipped `build_receipt` and the shipped binding validator:

    BEFORE  main vs itself                 -> Refusal: matches neither state
    AFTER   P -> A                         -> BUILT
                                              operation      = ACTIVATE
                                              complete       = True
    validate_receipt_binding(P, A)         -> ACCEPTED
    negative control, the pair swapped     -> REFUSED
                                              "receipt base_commit does not
                                               bind the merge verdict"

The negative control matters: without it, "ACCEPTED" would only show the
validator says yes to things, not that it says no to the wrong ones.

Note that `candidate_gates` and `candidate_tests` are worktree DIRECTORIES
attested against the candidate commit, not JSON files. Passing files gives
`candidate worktree is not a directory`, which reads like a defect and is not.

## THE PART THAT MUST NOT BE GLOSSED

**The repair commit itself cannot be validated.** `build_receipt(base=main,
candidate=P)` refuses at :512 exactly like everything else, because the base is
still the drifted main. So the repair can only land through the plain lander —
the one path that does not consult this validator.

That is the same gap that produced the drift (see
`2026-08-22-protected-tuple-unenforced-on-the-landing-path.md`). The repair
therefore relies on the defect to fix the defect. That is a real cost and it is
the owner's to accept or refuse; the alternative is a change to
`protected_landing_transition.py` giving it an explicit, audited
re-authorisation path, which is a larger decision than this rehearsal.

## WHAT IS STILL THE OWNER'S TO CHOOSE

`next` cannot be invented here. It must be the tuple produced by the next real
protected-path change, so this repair is ready to render the moment that change
is named. `~/_jrows/rerender2.sh <target-ref> <transition-id> <next-id>` derives
the moved set, asserts one `--next-file` per moved path, and refuses unless the
shipped validator recognises both ends.
