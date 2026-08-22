# A worktree mount silently disables `suite_write_guard`

_Measured 2026-08-22 on host `8hd-3`, same sha (`facc28860`), same image
(`ghcr.io/vibeic/vibeic-eda:0.3.16`), same flags, two trees. Repository tooling
only: no design, PDK, vendor or part identifier appears._

## The claim

Running the suite against a git **worktree** mounted into the container loses
`suite_write_guard` and several git-dependent tests. Nothing fails loudly; one
line scrolls past and the run reports success.

## Why

A worktree's `.git` is a FILE, not a directory:

    gitdir: /home/reyerchu/vibe-ic/.git/worktrees/_jdm_wt

That path is outside the `/subject` mount, so `git rev-parse` cannot resolve the
repository in-container. Everything that needs git degrades — correctly, and
that is the point: the tools are honest, the READER is the failure.

## The A/B

| tree | `test_program_inventory_no_drift.py` | write guard |
|---|---|---|
| worktree, mounted `:ro` | **4 failed**, 19 passed | `WRITE_GUARD_NOT_CHECKED: git rev-parse --show-toplevel exited 128` |
| real `git clone`, same sha | **23 passed** | `[PASS] suite_write_guard` |

The four failures are the HARNESS, not the repository. `gen_program_inventory.py`
answers rc 2 NOT CHECKED because `enumerated_from` cannot be established, and the
test asserts rc 0. Repairing those tests to skip would weaken four real tests to
accommodate a mount.

## The half that matters

The failures are visible and get investigated. `WRITE_GUARD_NOT_CHECKED` does
not: it is one line in a run that ends `209 passed`. The guard proving a pytest
session wrote nothing into the shipped tree was therefore absent from an entire
night of verification evidence on this branch, and nothing about the output said
so unless you went looking for it.

`NOT CHECKED is not a pass` is doctrine here and the tool obeys it. The doctrine
is only worth anything if the line is READ.

## What to do

For any run whose result will be quoted as evidence — a regression before a
push, a claim in a report, an A/B in a findings document — clone:

    git clone --branch <branch> /home/reyerchu/vibe-ic /home/reyerchu/AI_IC_design/<dir>

and mount that. Worktrees remain right for editing and fast iteration; they are
not right as the tree a verification claim rests on.

This document does not propose making a NOT-CHECKED write guard fail the suite.
That is a landing owner's call: it would turn every worktree-based run red, and
the honest line is already printed. The defect measured here is that it is
printed into a stream nobody reads.
