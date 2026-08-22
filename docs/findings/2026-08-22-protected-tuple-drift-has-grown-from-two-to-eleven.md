# The protected tuple's drift has grown from two paths to eleven, and nothing re-measured it

_Measured 2026-08-22 on host `8hd-3`. Three trees, all named by sha:
`origin/main` at `81cd5321b` (the sha the earlier finding used), `origin/main` at
`a4caccefe` (v1.11.69), and `jdistmat/matrix-distil` merged onto the latter.
Pure repository landing machinery: no design, PDK, vendor or part identifier
appears._

## What this adds to the existing finding

[`2026-08-22-protected-tuple-on-main-matches-neither-state.md`](2026-08-22-protected-tuple-on-main-matches-neither-state.md)
established, with `tools/ci/protected_landing_transition.py` itself, that
`main`'s protected tuple matches neither authorised state and that **no landing
of any kind can produce a receipt**. That finding stands. This one reports that
the condition has since got substantially worse, and that nothing in the tree
noticed.

## The measurement

`content_pinned_authority_verified_only_at_merge.py` reads the same manifest and
reports every pinned path whose content hashes to NEITHER `current` nor `next`.

| tree | pinned paths | hashing to neither |
|---|---|---|
| `origin/main` @ `81cd5321b` | 47 | **2** |
| `origin/main` @ `a4caccefe` | 47 | **11** |
| that, plus `jdistmat/matrix-distil` | 47 | 12 |

**The two at `81cd5321b` are exactly the two the earlier finding names** —
`tools/ci/repo_hygiene_gates.sh` (differs from `current` and from `next`) and
`programs/landing_merge_verdict.py` (a third state). The instrument used here
and the verifier's own code, run by a different author on a different host,
agree path for path. That agreement is why the second row can be trusted.

## The nine that drifted since

    tools/ci/_gate_dispatch.sh
    tools/ci/landing_completion_record.py
    tools/ci/routed_def_corpus.py
    tools/gatekeeper-land.sh
    programs/_corpus_location.py
    programs/ci_harness_timeout_ceiling_check.py
    programs/hygiene_finding_delta.py
    programs/repo_hygiene_parallel.py
    programs/tests/test_matrix_63x8_coverage.py

Two of these are worth naming separately. The earlier finding recorded
`tools/gatekeeper-land.sh` and `programs/ci_harness_timeout_ceiling_check.py` as
sitting at `next` — correctly activated, the half of the ACTIVATE that had
landed. **Both have been edited again since**, so the one part of that
transition that was in an authorised state no longer is. The repair surface has
grown, not shrunk, while the transition stayed open.

## Why nobody saw it

The manifest is verified at MERGE time. Between merges nothing compares a pin
against the tree, so a path can drift on any landing and the tree stays silent
until the next receipt is attempted — at which point the refusal names the
tuple, not the commit that moved it. Nine paths drifted across 214 commits with
no signal. The earlier finding said the verdict "arrives at the wrong time";
this is what that costs once it has run for a while.

## What is NOT claimed

That any of the nine edits was wrong. Each may be a perfectly good change. The
defect is that a protected path moved without the manifest being re-rendered to
authorise it, so the tree can no longer say which state it is supposed to be in.

## The twelfth path

`programs/_prose_polarity.py` is `jdistmat/matrix-distil`'s own and is expected:
that branch edits an authority path, and its lander must re-render the manifest
before landing. It is listed here only so the count is not mistaken for eleven
becoming twelve on main.
