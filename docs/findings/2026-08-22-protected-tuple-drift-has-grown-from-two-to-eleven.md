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

## Which landing moved each one

_Added 2026-08-22 on `next/protected-tuple-drift-attribution`, after the batch
carrying the finding above was frozen. Measurement only; no repair is attempted
here, and none can be attempted from a lane — see below._

The earlier finding leaves a landing owner two questions per drifted path: which
landing moved it, and was that move intended. The second is a judgement. The
first is archaeology, and it is done here so that eleven paths do not each have
to be traced by hand.

The manifest was rendered at `7a5c434d8` (2026-08-21, _"landing(PREPARE):
landing-lane-parallel-window-v1 — three protected paths move, the landing
runtime itself"_). Commits touching each drifted path on `origin/main` since
that render:

| path | commits | most recent |
|---|---:|---|
| `tools/ci/repo_hygiene_gates.sh` | 17 | `7d5fcd9ca` |
| `tools/ci/routed_def_corpus.py` | 5 | `8105c37f4` |
| `tools/gatekeeper-land.sh` | 4 | `377dd4e2e` |
| `programs/ci_harness_timeout_ceiling_check.py` | 3 | `377dd4e2e` |
| `programs/landing_merge_verdict.py` | 3 | `49777adc5` |
| `programs/tests/test_matrix_63x8_coverage.py` | 3 | `25c495aaa` |
| `tools/ci/_gate_dispatch.sh` | 2 | `3fbb0e3f2` |
| `tools/ci/landing_completion_record.py` | 1 | `4232a7301` |
| `programs/_corpus_location.py` | 1 | `d276311b3` |
| `programs/hygiene_finding_delta.py` | 1 | `49777adc5` |
| `programs/repo_hygiene_parallel.py` | 1 | `24a097287` |

**41 commits across the eleven paths.**

### The two that were previously in an authorised state

The earlier finding recorded `tools/gatekeeper-land.sh` and
`programs/ci_harness_timeout_ceiling_check.py` as sitting at `next` — the half
of the ACTIVATE for `landing-lane-parallel-window-v1` that had actually landed.
Both have been edited since, four and three times respectively, and both now
hash to neither state.

So the part of that transition which WAS authorised has been undone by ordinary
work. Nothing reported it at the time, because the manifest is compared against
the tree only at merge. This is the "the verdict arrives at the wrong time"
defect with a measured cost attached: an authorised state decayed over 41
commits and the first thing to notice was a receipt that could not be built.

### Why this changes nothing about who repairs it

It does not make the repair a lane's job. The refusal is raised on the BASE at
`build_receipt` line 512, before any candidate manifest is compared, so a lane
that renders a perfect PREPARE receives the identical refusal. What the table
above changes is only the cost of the owner's decision: each path now arrives
with the commits that moved it, rather than as a hash that matches nothing.

## The eleven split two ways, and the split is the owner's decision

_Computed against `origin/main` at `a4caccefe` from the manifest's own
`current.files` / `next.files` hashes — a path is "declared to move" iff the two
states disagree about it._

The transition `landing-lane-parallel-window-v1` declares **three** paths as
moving. Of the eleven that hash to neither state:

**A — the three declared to move, all three now past `next` (3 of 3)**

    tools/gatekeeper-land.sh
    programs/ci_harness_timeout_ceiling_check.py
    programs/landing_merge_verdict.py

These are the ACTIVATE itself. The earlier finding recorded the first two as
correctly sitting at `next` — the half that had landed — and only
`landing_merge_verdict.py` as a third state. **All three are now a third
state.** The authorised part of the transition has been fully undone by
ordinary work. For this group a re-render is a coherent repair: it authorises
the state they are actually in, and the question is only whether that state is
the intended destination.

**B — the eight that moved outside the transition (8)**

    tools/ci/_gate_dispatch.sh
    tools/ci/landing_completion_record.py
    tools/ci/repo_hygiene_gates.sh
    tools/ci/routed_def_corpus.py
    programs/_corpus_location.py
    programs/hygiene_finding_delta.py
    programs/repo_hygiene_parallel.py
    programs/tests/test_matrix_63x8_coverage.py

Nothing in this transition authorised any of these to move. A re-render here
would not repair anything — it would PHOTOGRAPH eight unauthorised moves and
record them as "the state we are leaving". Each needs a decision first: was the
move intended, and is the current content the content that should be pinned.

## Why the split matters more than the count

"Eleven paths drifted" reads as one problem of size eleven. It is two problems:
three paths where the transition's own intent is known and only the destination
is in question, and eight where no intent was ever recorded. The first group can
be resolved by the transition's author. The second cannot be resolved by anyone
without asking the landings named in the table above.
