# Addendum to the self-tape-out adjudication

The adjudication itself is `next/six-shuttle-refusals-readjudicated-on-the-self-tapeout-path`,
frozen inside batch 72 at `803b0c6f7`. **Its six verdicts are unchanged and nothing here
moves one.** This directory carries what was measured AFTER that freeze, because the
branch it belongs on cannot be pushed to.

## 1. An arm was reported as possibly stalled. It is not — measured

The observation from outside was `pid 422722`, state S, **2.4 CPU-seconds against 20
hours** of wall clock, log static.

**`422722` is the `docker exec` CLIENT, not the compute process.** The openroad is
`423747`. Sampled 60 s apart:

```
422722  docker exec client   state S   wchan=futex_wait_queue   240 -> 240 ticks   delta 0
423747  openroad             state R   wchan=0            8771283 -> 8777282 ticks  delta 5999
```

**5 999 ticks in 60 s is 99.98 % of one core, sustained.** `wchan=0` — blocked on
nothing; not D-state, not on a lock. The client sleeping while the container computes is
what a healthy `docker exec` looks like, and its 2.4 CPU-seconds over 20 hours is
correct behaviour for it rather than a symptom.

Container `jself-eda` up 21 h; the bind mount resolves and is writable from inside; the
log is static because **the full-die diamond rung emits nothing until it terminates** —
recorded before this question was asked, and demonstrated by the J88 probe, which was
silent for 13 m 28 s and then printed.

**Nothing was restarted, and nothing needed to be.**

## 2. That same log shows the arm reached the rung the report has been waiting on

Its movable area fell **6 035 072.38 → 5 871 407.05 µm²**, a drop of **163 665.33 µm²**,
and the log now carries

```
POST_HOLD_CLKBUF_DOWNSIZE swapped=2098 -> gf180mcu_fd_sc_mcu7t5v0__clkbuf_4
```

**The die-3300 arm is on rung 6**, the clkbuf downsize — the rung J83 measured at
2 344 → 303 and J86/J88 traced to `-root_buf`. J79's **P2** (*if any arm prints OK, the
token is `clkswap` or later*) is now under live test. **P3 is not scorable yet**: no
post-swap residual has printed.

## 3. A third in-the-wild sighting of the inverted guard

Immediately after the swap line, that arm printed:

```
POST_HOLD_CLKBUF_DOWNSIZE_NONFATAL:
```

— **an empty `_NONFATAL:` on the SUCCESS path**, which is the defect
`next/clkbuf-downsize-diagnostic-is-inverted` (`f99979a73`, in batch 72) fixes. Third
independent sighting, on a third arm.

## 4. And the defect in MY OWN registered predicate

`posthold_verdict_predicate.py` printed

> NOT YET — 0 of 5 arms have printed a post-hold verdict and **none has reached the
> clkswap rung**

directly under its own table showing `clkswap=yes 2098` for die 3300. **A summary
contradicting its own rows** — the defect caught in J86 (`at-or-over-50-sites=0` beside
rows reading 50.0) and again in J92, here in the one place it is least excusable: a
predicate registered in advance so that it could not be shaped after the fact.

**The RULE is untouched and was correct** — P3 genuinely cannot be scored until a
post-swap residual prints. **Only the sentence was wrong**, and it is now computed from
the same data the table is:

```
NOT YET — 0 of 5 arms have printed a post-hold verdict.
1 arm(s) HAVE reached the clkswap rung (3300) but none has printed a post-swap
residual yet, so P3 is not scorable.
```

Editing a registered predicate is normally forbidden. This is a message, not a rule, the
distinction is stated in the file at the point of the change, and the rule's behaviour
is identical before and after: `rc 2`, unanswered.

## 5. The arm is on rung 9 of 9, and that constrains what the predicate can still say

Read structurally, the post-swap blocks in the die-3300 arm's log map onto
`pnr.tcl:8341-8364` one for one:

```
swapped=2098
  DPL  ±500 / ±100      -> rung 6  detailed_placement (default)          no OK
  DPL  ±5892 / ±841     -> rung 7  clkswap-full-die (3300 um ≈ 5892 sites) no OK
  DPL  ±500 / ±100      -> rung 8  -use_diamond_legalizer                 no OK
  DPL  header only, still running
                        -> rung 9  -use_diamond_legalizer, full-die   <- HERE
```

**It is on the last rung.** What it prints next is terminal for this arm:
`POST_HOLD_LEGALIZE_OK disp=diamond-full-die`, or `POST_HOLD_LEGALIZE_FAILED`.

That fixes what J79's registered predicate can still do, and it is worth writing down
BEFORE the answer rather than after:

* **P1** — *no arm prints `POST_HOLD_LEGALIZE_OK disp=full-die`*. **Held on this arm**,
  and now unfalsifiable by it: it went through rung 5 and printed no OK there.
* **P2** — *if any arm prints OK, the token is `clkswap` or later*. **Cannot be refuted
  by this arm.** Rungs 6, 7 and 8 have passed with no OK, so the only OK still available
  to it is `disp=diamond-full-die`, which is a later token. P2 survives this arm whatever
  it does — which is a weaker outcome than P2 being confirmed, and is said as such.
* **P3** — *the clkswap rung's residual falls strictly below 2 296*. **NOT SCORABLE on
  this arm, and probably never will be**: it printed **no `Violations remain` line at all**
  after the swap. Four DPL blocks, four `DPL-0009` headers, no residual. The pre-swap
  rungs did print one. **I am not going to explain that difference from the log alone** —
  it is one arm, and the honest statement is that P3's input does not exist here.

  > **← THIS BULLET IS SUPERSEDED. See §6 and §7.** Both of its claims are wrong. The
  > arm *does* print a post-swap residual, under the diamond legaliser's name
  > (`Total Placement Failures`) rather than the NegotiationLegaliser's; and **P3 is
  > scorable and CONFIRMED** on the die-3800 arm, which reached the same rung on the
  > counter the band was measured with (`2307 → 300`). The refusal to explain the
  > difference from one arm's log was right; the difference is explained in §6 from
  > five. The bullet is kept as written rather than edited, because it is what was
  > believed when it was published.

**No verdict moves and none can.** `edge_llm_matmul_accel` is UNDETERMINED because no
layout exists for it, which is §7's wall and is unrelated to which rung a legalizer
reaches. The predicate was always about what the rung PRINTS, never about the chip.

---

## 6. The residual section 5 said did not exist — it exists, under the other legaliser's name

Section 5 above reported that the die-3300 arm printed **no residual at all** after the
clkbuf swap, and concluded that **P3 was "NOT SCORABLE on this arm, and probably never
will be"**. It declined to explain the difference from one arm's log, which was the
right instinct. **Both halves of that are now corrected by measurement.**

The arm prints a residual on every post-swap rung. It prints it as

```
Total Placement Failures:        320          <- DPL-1101, the DIAMOND legaliser
```

not as

```
[WARNING DPL-0701] ... Violations remain: 300 <- the NegotiationLegaliser
```

Section 5 grepped for `Violations remain`. That string is genuinely absent from that
arm — and **absence of the label was read as absence of the thing.** This is J94's
defect with the sign flipped: J94 withdrew a comparison made because two searches
*shared* a name; this one drew a conclusion because one search *did not share* a name.

### Why that one arm, and not the other four — measured 5 for 5

`-use_diamond_legalizer` appears at `pnr.tcl:313`, the last rung of the INITIAL
placement ladder. Only an arm whose initial placement FAILS ever executes it. **From
that call onward, every `detailed_placement` in the session uses the diamond legaliser
— including the calls that pass no flag at all.**

```
arm        initial placement      DPL-1101 diamond calls   DPL-0701 negotiation calls
die 3300   INITIAL_DPL_FAILED     15                       5   (all of them BEFORE the first diamond call)
die 3800   INITIAL_DPL_OK          0                       11
die 4200   INITIAL_DPL_OK          0                        9
die 5153   INITIAL_DPL_OK          0                        9
die 5434   INITIAL_DPL_OK          0                        9
```

Negotiation calls in the die-3300 log after its first diamond call: **0**.
Same OpenROAD binary on all five (`26Q3-1535-g543c33894f`), and the post-hold ladder
Tcl is byte-identical between the 3300 and 3800 arms (`diff` of the
`hold_repair`..`POST_HOLD_LEGALIZE_FAILED` span is empty).

**Honesty about what this does NOT settle.** Two latches are consistent with all five
runs and these runs cannot separate them: the *flag* persisting, or the *initial-
placement failure* that leads to the flag being what persists. They are perfectly
confounded here, because reaching the flagged rung IS the consequence of failing. What
is measured is the observable — the legaliser used by later UNFLAGGED calls differs
between arms, and nothing else about those calls does. Separating the two needs a run
that passes the flag without having failed, and no arm has done that.

## 7. P3 is scorable after all — on a different arm, and it is CONFIRMED

The die-3800 arm reached the same rung **on the counter J79's band was measured with**:

```
die 3800   rung 1  2352   rung 2  2352   rung 3  2344   rung 4  2340   rung 5  2307
           << POST_HOLD_CLKBUF_DOWNSIZE swapped=2089 >>
           rung 6  300                                          <- the clkswap rung
```

**300 < 2296. P3 is CONFIRMED**, on the NegotiationLegaliser, against the 2296–2418
band that same legaliser produced. On its own arm the collapse is **2307 → 300, −87.0 %**.

The die-3300 arm agrees — `2329 → 320`, **−86.3 %** — but that is **corroboration and
is deliberately not the score**, because it is the diamond legaliser's counter and the
band is not. J94's rule is applied here in the direction that costs something: the
second arm would have made the result look stronger, and it is held back.

```
arm        P1                                  P2                        P3
die 3300   HELD (unfalsifiable by this arm)    SURVIVES (not confirmed)  CORROBORATION ONLY  320
die 3800   HELD (unfalsifiable by this arm)    SURVIVES (not confirmed)  CONFIRMED           300 < 2296
die 4200   NOT YET (inside rung 5)             NOT YET                   NOT YET
die 5153   NOT YET (inside rung 5)             NOT YET                   NOT YET
die 5434   NOT YET (inside rung 5)             NOT YET                   NOT YET
```

**P1** — *no arm prints `POST_HOLD_LEGALIZE_OK disp=full-die`* — now held on **two**
arms, both of which are past rung 5 with no OK and can no longer refute it.
**P2** — *if any arm prints OK the token is `clkswap` or later* — survives on those two
without being confirmed by either, which is weaker than confirmation and is said so.

`posthold_ladder_score.py` in this directory is the scorer. It runs **nine positive
controls before it reads a real log** and aborts if any fails: P3 must be able to print
REFUTED on a synthetic post-swap residual inside the band, must refuse to score off the
diamond counter, must say NOT YET both before the swap and while the rung is in flight,
and P1 and P2 must each be refutable. A scorer that can only say CONFIRMED measures
nothing.

## 8. Rung 8 bought nothing, and section 6 explains why

On the die-3300 arm the post-swap ladder reads

```
rung 6  clkswap            +/- 500 / +/- 100     320
rung 7  clkswap-full-die   +/- 5892 / +/- 841    274      <- recovered 46
rung 8  diamond            +/- 500 / +/- 100     274      <- recovered 0
rung 9  diamond-full-die   +/- 5892 / +/- 841    still running
```

Rung 8 is `detailed_placement -use_diamond_legalizer` at the default displacement.
**On this arm that is the same call as rung 6**, which was already the diamond
legaliser at the same bound. The ladder's design intent at rungs 8–9 is *"displacement
did not help, so change algorithm"* — and for any design whose initial placement failed,
**that escape hatch was spent before the post-hold ladder began.** It recovers 0, which
is what a repeated call should recover.

This is chip-AGNOSTIC and is recorded rather than acted on: it costs a design that has
already failed initial placement two extra full legalisation passes that cannot differ
from ones it has already run.

## 9. The swap frees 2.7 % of movable area — and the build-to die still does not move

```
die 3300  swapped=2098   6 035 072.38 -> 5 871 407.05  = -163 665.33 um2  (-2.712 %)
die 3800  swapped=2089   6 054 418.68 -> 5 891 043.11  = -163 375.57 um2  (-2.698 %)
```

The two agree to **289.76 um²**, 0.18 % of the reduction. And **J83's probe predicted
the 3800 figure at 163 375.56 um² before that arm reached the rung; the arm itself
prints 163 375.57** — a match to **0.01 um²** on 163 thousand, which is the probe
methodology verified against the thing it was reconstructing.

That raises a fair question about a number this adjudication publishes: the build-to
die is sized from each arm's post-hold movable area, and the swap makes that area
smaller. `downsize_die_sensitivity.py` answers it, after a control that must reproduce
the published 6138.9 / 6164.9 um to 0.1 um before it prints any counterfactual:

```
                 DIE pre-swap   DIE post-swap   change
movable low         6138.9         6066.1       -72.8 um  (-1.185 %)
movable high        6164.9         6092.4       -72.4 um  (-1.175 %)
```

**The published band keeps the PRE-swap area, deliberately.**
`POST_HOLD_CLKBUF_DOWNSIZE` is not an area optimisation — it is the ladder's last-resort
legalisation rescue, reaching into a placed, CTS-ed, hold-repaired block to swap ~2 090
clock buffers down to `clkbuf_4` for no reason other than that the legaliser could not
otherwise fit them. Sizing a die from what that leaves would be quoting a die that only
holds the design after its clock tree has been weakened to make it fit, **and quoting it
without the timing that weakening costs** — no arm re-times after the swap, and the
ladder does not ask it to. The 72.8 um is recorded as the cost of the rescue rather
than banked as a smaller chip.

**And the verdict is unmoved under either reading**: 6.066 mm and 6.139 mm are both far
above the 2.862 mm pad floor, so `edge_llm_matmul_accel` is CORE-limited either way.
That is the only thing the six rows turn on.

**No verdict moves.** `edge_llm_matmul_accel` remains **UNDETERMINED** — because no
finished layout exists for it, which is the flow wall of §7 and has nothing to do with
which rung a legaliser reaches. The predicates were always about what the rung PRINTS.

## 10. The closing check: the headline re-derived from its own rows

Three times in this work a summary has disagreed with the table directly beneath it —
J86 (`at-or-over-50-sites=0` beside rows reading 50.0), J92 (a value collision), and
§4 of this addendum (a registered predicate whose summary said "none has reached the
clkswap rung" above its own row reading `clkswap=yes 2098`). One shape, three sightings:
**a summary computed separately from the rows it sits on top of.**

This dispatch edited both the headline and section 6 of the adjudication, so the
headline was re-derived FROM the six-row table rather than re-read:

```
headline says NOT FEASIBLE=2 UNDETERMINED=4 | rows give 2 / 4  -> MATCH

  u_hawaii_adc             NOT FEASIBLE
  edge_llm_accel           NOT FEASIBLE
  caravel_user_project     UNDETERMINED
  opentitan_aes            UNDETERMINED
  ibex                     UNDETERMINED
  edge_llm_matmul_accel    UNDETERMINED
```

`summary_matches_its_rows.py` is run against a synthetic table with a deliberately
wrong headline first and must report MISMATCH before it is allowed to read the real
report. All six rows classify; none falls through to `?`.

Two further audits were re-run after the edits, because editing a report is exactly
when its self-checks stop being decorative:

* **`cite_audit`** (J68) — every `file:line` the report publishes, re-resolved. It
  **caught this dispatch's own edit**: a new `pnr.tcl:313` near the top of the report
  became the nearest named citation above three BARE `` `:NNN` `` continuations that
  belong to `phase3_one_shot_runner.py`, and all three silently re-pointed at a
  9 716-line file. Fixed by making the three EXPLICIT rather than by moving the new
  citation out of their way — so their meaning no longer depends on what is written
  above them. Back to **rc 0**.
* **`stale_figure_audit`** (J92) — **rc 0**, 9 superseded figures across 3 904 lines,
  every occurrence still sitting in a context that marks it superseded.

## 11. The item the report published as OPEN has ANSWERED — `POST_HOLD_LEGALIZE_FAILED`

At **22:20:11** on 2026-08-22 the die-3300 arm printed the ladder's terminal line
(`pnr.tcl:8364`). Nine rungs, then:

```
  rung 5  disp +/-5892/841   illegal = 2329      (full-die)
  --- POST_HOLD_CLKBUF_DOWNSIZE swapped=2098
  rung 6  disp +/-500/100    illegal =  320      <- -86.3 %, the whole recovery
  rung 7  disp +/-5892/841   illegal =  274
  rung 8  disp +/-500/100    illegal =  274      <- 0
  rung 9  disp +/-5892/841   illegal =  274      <- 0
  === POST_HOLD_LEGALIZE_FAILED
```

Rungs 8 and 9 are the ladder's "change algorithm" escape hatch. On this arm they buy
**nothing**, because §6's finding holds to the end: the diamond flag has been live since
`pnr.tcl:313`, so they re-run a call already made. The last rung's own summary —
**rip-up-and-replace recovered 0 of 274** after a full-die diamond search moved 99.89 %
of 258 306 cells — is the sharpest available statement about this placement.

**No verdict moves.** The row is decided on **area**: build-to **6.139–6.171 mm**, and
3.300 mm is the smallest arm of five, a die the report never proposed building. What it
removes is a hedge — *"the ladder has four more rungs"* is no longer true on this arm.

§5's registered prediction held on every clause: **P1 CONFIRMED terminally** (all nine
rungs spent, no `OK` at any token), **P2 survives without confirmation** exactly as that
section said it would, **P3** already CONFIRMED on the die-3800 arm by §7.

Two controls came with it. The **decay ledger** bracketed the event — `none yet` on the
run before, the verdict **48 s** later — and flagged three stale pins in **itself**,
including a substring proxy (`grep -c jself`) that my own `next/jself` push broke while
the claim it stood for stayed true; it is now measured **by name with a positive
control** (`controls/branch_claim_by_name.py`). And the tree's own
`placement_legality_check`, whose test fixtures are synthetic, was run on **real** data
for the first time: **FAIL** on this arm citing both markers, **PASS** on the die-3800
arm beside it — while **both report `0 unplaced`**, so the status-token check cannot tell
them apart and the placer's own verdict is the only thing that can.

Detail: `../selftapeout-adjudication/findings.md` §J98, evidence in
`../selftapeout-adjudication/probes/j98/`.
