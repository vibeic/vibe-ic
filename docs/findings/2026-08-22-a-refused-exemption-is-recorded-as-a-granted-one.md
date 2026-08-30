# `_dispatch` records a REFUSED exemption as a GRANTED one, and the same shape is in three more setters

_Measured 2026-08-22 on host `8hd-8`, against `origin/main` at `ae78abb28`
(v1.11.70). Every number below was produced by driving the shipped
`tools/ci/_gate_dispatch.sh` in a live shell and reading its own
`--summary-json` record; nothing is quoted from the issue without being
reproduced first. Pure repository landing machinery — no design, PDK, vendor or
part identifier appears._

Closes the measurement half of vibe-ic#1770. It does **not** land the fix, for
the reason stated at the top of the next section.

## THE BLOCKER, FIRST: no protected transition can be built at this base

`tools/ci/_gate_dispatch.sh` is one of the 47 paths pinned by
`tools/ci/protected_landing_transition.json` and named in
`REQUIRED_AUTHORITY_PATHS`, so its bytes can only move through a base-authorised
PREPARE/ACTIVATE transition. At this base that transition cannot be built at
all — not by this candidate and not by any other:

```
$ python3 -c "... protected_landing_transition.build_receipt(
      object_repo='.', base='ae78abb28', candidate='ae78abb28', ...)"
Refusal: protected tuple matches neither authorised atomic state
```

That is a **null** transition — base and candidate are the same commit — and it
still refuses. `build_receipt` computes
`base_state_id = _match_state(base_files, base_manifest)` *before* it classifies
the candidate, so STEADY, PREPARE and ACTIVATE all die on the base. The live
47-tuple at `ae78abb28` hashes to neither authorised state on **12** paths:

| | |
|---|---|
| manifest `current.id` | `eda-image-decouple-v1-next` — 12 mismatches |
| manifest `next.id` | `activated-at-lane-parallel-window` — 12 mismatches |

```
tools/ci/_gate_dispatch.sh
tools/ci/landing_completion_record.py
tools/ci/repo_hygiene_gates.sh
tools/ci/routed_def_corpus.py
tools/gatekeeper-land.sh
vibe-ic-marketplace/plugins/vibe-ic/programs/_corpus_location.py
vibe-ic-marketplace/plugins/vibe-ic/programs/_prose_polarity.py
vibe-ic-marketplace/plugins/vibe-ic/programs/ci_harness_timeout_ceiling_check.py
vibe-ic-marketplace/plugins/vibe-ic/programs/hygiene_finding_delta.py
vibe-ic-marketplace/plugins/vibe-ic/programs/landing_merge_verdict.py
vibe-ic-marketplace/plugins/vibe-ic/programs/repo_hygiene_parallel.py
vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_coverage.py
```

This continues the count in
[`2026-08-22-protected-tuple-drift-has-grown-from-two-to-eleven.md`](2026-08-22-protected-tuple-drift-has-grown-from-two-to-eleven.md):
2 at `81cd5321b`, 11 at `a4caccefe` (v1.11.69), **12 at `ae78abb28` (v1.11.70)**.

**What the transition needs that this work cannot supply:** a BASE commit whose
live 47-tuple equals one of its own manifest's two authorised states. Supplying
one means landing a manifest re-authorisation on `main` — and by the refusal
above that re-authorisation cannot itself be validated by this validator, so it
could only go in through the plain lander, which is the one path that never
consults it. Both halves are outside this work: the first is a push to `main`,
the second is routing around the transition. **The fix below is therefore
measured, proven and quoted, and deliberately not committed.**

Blob identities, so an ACTIVATE can be rendered against them without re-deriving:

| state | sha1 | sha256 | bytes |
|---|---|---|---|
| live at `ae78abb28` | `9895a128d98d4bb6a87a48df9c180f181e1a0579` | `e4088103…10198d` | 100548 |
| with the fix | `2c1242c8e0585ba8e3206d4d621a0693e5f73760` | `f9f7b220…0c54b9` | 101169 |

## The defect, reproduced rather than trusted

Driving the real dispatcher over an attested-population loop whose producer
prints nothing, with `uncheckable_until 2999-01-01` armed in front of it:

| channel | before | after |
|---|---|---|
| console | `NOT CHECKED (rc 2, BLOCKING; no exemption)` | unchanged |
| record `exempt_until` | `"2999-01-01"` | `null` |
| record `exemption_expired` | `false` | `false` |
| record `not_checked_unexempted` | `[]` | `[<the row>]` |
| record `wiring_errors` | 1 | 1 |
| exit code | 2 | 2 |

The `before` column reproduces the issue's own Measured table exactly. The
console and the record gave opposite answers about one gate: the sentence said
the purchase was refused, the field named for the question said it was bought.

The cause is that the append sits outside the branch that decides whether it
should happen:

```sh
  elif [ "$tolerate" -eq 2 ] && [ -n "$ex_until" ]; then
    _gate_wiring_error "… cannot consume an uncheckable exemption — an unknown
                        denominator must remain blocking"
  fi
  GATE_EX_UNTIL+=("$ex_until"); GATE_EX_WHY+=("$ex_why")     # <-- runs anyway
```

`_gate_wiring_error` appends to `GATE_WIRING_ERRORS` and returns; it does not
exit, so the append is reached on every path.

## The fix

```diff
     _gate_wiring_error "\"$label\" is a dispatcher-owned population refusal \
 and cannot consume an uncheckable exemption — an unknown denominator must \
 remain blocking"
+    #: AND THE REFUSAL MUST NOT BE RECORDED AS A GRANT. The append below is the
+    #: ONE place an exemption enters the record, and it is read BY INDEX beside
+    #: the label, so it cannot be moved inside the branches without giving one
+    #: gate another gate's date. Clearing the refused value here is that same
+    #: append made conditional: the row leaves `_dispatch` with NO exemption,
+    #: stays in `not_checked_unexempted` — the fail-safe field every landing
+    #: consumer reads — and the record then agrees with the sentence just
+    #: printed instead of contradicting it.
+    ex_until=""; ex_why=""
   fi
   GATE_EX_UNTIL+=("$ex_until"); GATE_EX_WHY+=("$ex_why")
```

**Why the value is cleared rather than the append moved into each branch.** The
file's own comment beside the sibling appends states the constraint: *"One
append per gate, at the SAME point as the label, because the record is read by
index: a scope appended on only some code paths would attribute one gate's scope
to another gate's verdict."* Four append sites in a four-way chain is four
chances to skew that index. Clearing the refused value is the same append made
conditional, with one site.

It is strictly tightening: it can only move a row from "exempt" to "not exempt",
and the exit code is 2 before and after — no red is turned green.

## The test, and the red proven in both directions

The two tests the issue names both move with the fix, from opposite directions,
so a repair that updates only one leaves the suite red:

1. `test_routed_def_corpus_dispatch.py::test_a_population_refusal_cannot_buy_an_uncheckable_exemption`
   pins the hazard as current behaviour — its last two assertions invert to
   `exempt_until is None` and `not_checked_unexempted == [_EMPTY_LABEL]`.
2. `test_population_refusal_cannot_be_bought_off.py::test_the_record_does_not_state_a_refused_exemption_as_a_granted_one`
   is `xfail(strict=True)` on the desired end state — the marker is deleted.

Both modules, run whole, on `ae78abb28` with those two edits applied:

```
RED   (edits, dispatcher unfixed)   2 failed, 24 passed
  E AssertionError: the population refusal carries an exemption date, so to
    every record-reading consumer an empty corpus is a bought refusal:
    {… 'exempt_until': '2999-01-01' …}     assert not '2999-01-01'
  E AssertionError: {'declared': 2, 'ran': 2, 'decided': 1, …}
    assert '2099-01-01' is None

GREEN (edits + the fix)             26 passed
```

The fix was then broken three ways and the red reappeared each time — including
a mutation of the **same shape as the defect**, which proves the tests are
sensitive to where the statement sits and not merely to its presence:

| mutation | result |
|---|---|
| clearing deleted entirely | 2 failed, 24 passed |
| clearing moved to *after* the append | 2 failed, 24 passed |
| half fix — clear `ex_why` only | 2 failed, 24 passed |

## The sweep: the same shape is in three more places

Every `_gate_wiring_error` call site in the file was read, and every `+=(`
append. The shape — a refusal, then a write of the refused value outside the
branch that refused it — appears in **three further setters**, all of them the
"declare something for the NEXT gate" family:

### 1. `uncheckable_until` — same shape, and this one is reachable by ordinary typing

Three refusals (a leftover exemption, a non-ISO date, a missing reason), then
`GATE_PENDING_UNTIL="$until"; GATE_PENDING_WHY="$why"` outside all of them.
Measured, on a `run_tolerating_uncheckable` gate reporting rc 2:

| armed | wiring error | record `exempt_until` | `not_checked_unexempted` |
|---|---|---|---|
| `uncheckable_until never "a stated reason"` | ISO-8601 refusal | `"never"` | `[]` |
| `uncheckable_until 2999-01-01 ""` | must-state-WHY refusal | `"2999-01-01"` | `[]` |
| *control:* `uncheckable_until 2999-01-01 "a stated reason"` | none | `"2999-01-01"` | `[]` |

The record is **identical** for a properly bought exemption and for one the
dispatcher refused in words. This is worse than the #1770 instance in two ways.
The #1770 combination is armed nowhere today; a mistyped date or a forgotten
reason is an ordinary human error available at every wiring site. And expiry is
a lexicographic compare against today —
`[[ "${GATE_EX_UNTIL[$i]}" < "$GATE_DISPATCH_TODAY" ]]` — so a refused
non-ISO string such as `never` sorts above every real date and the exemption is
**immortal**: it appears in neither `exemptions_expired` nor
`not_checked_unexempted`, and it never will.

As with #1770, nothing is unsafe today only because the run still exits 2 on
`wiring_errors`. The control row above is the proof of that dependency: with a
valid exemption the same run exits **0**, so `wiring_errors` is the only thing
separating the two.

**#1770's fix does not close this one**, and that was measured rather than
assumed: the two rows above are byte-identical against the shipped dispatcher
and against a locally fixed one. #1770 clears the refused value on `_dispatch`'s
mode-2 arm; this instance arms a pending exemption that then reaches an ordinary
`run_tolerating_uncheckable` gate through the granted path.

**It is now pinned**, because it would otherwise survive #1770's landing with no
guard at all — the same gap PR #1769 existed to close for #1770:
`programs/tests/test_refused_uncheckable_until_is_not_armed.py`, one
`xfail(strict=True)` end-state test over both refusals plus three controls.
The pin was proven to be live rather than decorative: with the analogous
one-line fix applied in a throwaway tree the two cases report
`XPASS(strict)` -> FAILED, so the day the defect is fixed the marker must be
deleted; the three control arms stay green under that same fix.

Only ONE direction is pinned here, deliberately. PR #1769 pinned #1770 from both
directions — an `xfail` on the end state and a sibling asserting the hazard as
current behaviour — which is why #1770 now needs two tests updated when it
lands. A second hazard-as-current-behaviour pin would double that burden for a
second defect; a strict `xfail` cannot be silently satisfied on its own, so one
is enough.

### 2. `gate_scope` — same shape, measured benign

Two refusals, then `GATE_PENDING_SCOPE="$*"`. On `gate_scope` with no path,
`$*` is empty, the recorded scope is `null` and the gate ran and decided
(`state: PASS`) — an empty scope is indistinguishable from no scope, which is
the "narrowing is opt-in" default. No hazard.

### 3. `gate_serial` — same shape, and it fails in the safe direction

Two refusals, then `GATE_PENDING_SERIAL=1`. A `gate_serial` with no stated
reason is refused in words and still serialises the gate. Running a gate alone
is the conservative outcome, so the recorded grant costs time, not safety.

### Deliberately NOT changed: the `tolerate == 0` arm of the same `if`

The middle branch of the same chain records its refused exemption too, and this
one must stay. Measured: an already-expired `uncheckable_until` in front of an
ordinary `run` gate is refused in words, the gate still reports `PASS`, and the
recorded date puts the label into `exemptions_expired` — a **second,
independent** refusal. Clearing it there would remove a refusal, i.e. turn a red
green, which is exactly what the #1770 fix is bounded not to do.

### The correct idiom is already in this file, twice

Two refusal sites do refuse *and* correct the value in the same branch:
`GATEKEEPER_HYGIENE_JOBS` that is not a positive integer is refused and then set
to `1`, and a `GATE_DISPATCH_ATTEST_POPULATION` that is not `0` or `1` is
refused and then set to `0`. Three sites out of five follow the wrong shape and
two follow the right one; the fix above makes it three right, and the two
remaining hazards are named here — one of them now pinned.

### One related site, different shape, already documented as deliberate

If `date -u +%F` cannot be read, `GATE_DISPATCH_TODAY` is left empty and every
`until` compares as not-yet-due — every exemption immortal. There is no append
outside a branch here; the file states the reliance on `wiring_errors` outright
and calls it fail-closed. Recorded for completeness, not as a defect of this
class.
