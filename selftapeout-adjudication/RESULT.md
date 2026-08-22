# RESULT — the SIX "NOT SUITABLE" verdicts, re-adjudicated on the SELF-TAPE-OUT path

## ALL SIX DECIDED

ALL SIX DECIDED — 2 NOT FEASIBLE (both UPHELD for reasons DIFFERENT from the
originals), 4 UNDETERMINED (all four original reasons OVERTURNED, each with the
constraint that actually binds on this path MEASURED). `edge_llm_matmul_accel`, the
last one open, is decided: CORE-limited, floor 4.522 mm, build-to **6.139–6.171 mm**
*(5.875–5.963 → 6.139–6.165 by J65; → 6.139–6.171 by J76, when the fifth arm's
post-hold block landed ABOVE the band four arms defined and a rule registered before
it answered required the correction upward)*, and never at any point
pad-limited. Not one of the six is refused by a pad budget
here.

**★ AND MAIN MOVED 673 COMMITS UNDER THIS REPORT — THE LEDGER CAUGHT IT AND ALL FOUR
ANCHORED CLAIMS SURVIVE (J91).** `origin/main` went `a4caccefe` (v1.11.69) →
**`ae78abb28`** (v1.11.70) mid-dispatch, and one of the 673 is a merge named
`fix/jpolarity-emitter-polarity` — close enough to my own clkbuf finding that reading the
subject would have been the wrong instrument. Each anchored claim was re-measured against
the new sha: **§7's wall is still there** (`pad_ring_gen.py` still 823 lines,
`PAD_INSTANCE_NOT_IN_BLOCK` ×2, still at line 730); **the clkbuf guard is still inverted**
at `:16109`; **`PLACEABLE_WIDTH_BOUND` is still printed and never consulted**; and
`cite_audit` still exits **0**. `phase3_one_shot_runner.py` did change (+20/−1) and both
branches merge with 0 conflicts — *a clean merge proves nothing about semantics*, so both
merged trees were **built and run**: **8 passed** and **27 passed**, plus **490 / 1
skipped** across the 17 files touching that emitter. **Neither fix is superseded and
neither needs a rebase.** This is the second time the ledger caught something nobody went
looking for; without that row the report would have gone on citing a superseded sha.

**★ RE-VERIFIED ON A LATER DISPATCH, AND NOTHING IN THE SIX MOVED (J79).** With every
row decided there is no measurement left that changes a verdict, so that dispatch went
at the CONTROLS instead. The two NOT FEASIBLE readings — the only two tiers that refuse
a chip — are now a **file** with **positive controls** rather than a hand-run command
(`meas/_j79/notfeasible_control.py`): 13 device flavors, tokens `03v3/05v0/06v0/10v0`,
**0** files naming 1.2 V, all four corner libs absent; 3 views, **587** OBS/LAYER/RECT
records, **0** mask-level views — **CONTROL HELD**, and a synthetic PDK carrying
`nfet_1v2` plus a synthetic design carrying a `.gds` both make it fail, so the `0`s are
a measurement and not a blind spot. `cite_audit` still exits **0**; `origin/main` is
still **`a4caccefe`** and still carries `PAD_INSTANCE_NOT_IN_BLOCK`, so §7's wall is
re-confirmed on today's main; the five-arm fixed point re-solves to every digit it
publishes. **And J78's "a predicate whose answer depends on when you ask it" was
followed out of the scripts and into THIS REPORT** — 18 published live-state readings
are now pinned in a decay ledger (`meas/_j79/decay_ledger.py`) and re-measured.
**Exactly one moved, and it is the half that never carried the sentence**: J74's remote
query, whose `0 matching jself` has held at every asking while the `67 heads` beside it
— a count of other people's branches — became **72** in under two hours. Both places
that published it now say which half is which. Every number the arms print reproduces
to the digit, and the four dwell ratios grew while staying true **because they are
published as lower bounds**. The dispatch found **three defects in its own instruments
and zero in the tree** — a binary `.gds` making `V1.2 Via1` read as a voltage, a `\b`
that cannot bound `nfet_1v2`, and a ledger comparing two vocabularies — which is the
argument for positive controls, made by the run rather than asserted.

**★ AND THE OPEN ITEM'S MECHANISM IS NOW MEASURED RATHER THAN ARGUED (J80) — one
10-minute probe, two predictions registered before it, both HELD.** The five arms are
inside rung 5 and may be for days, so the mechanism J79's P1/P2/P3 rest on was probed
on an artefact that already existed: the die-3800 arm's `post_cts.def`, a state **the
flow never measures** (it runs no `detailed_placement` between `PNR_STAGE: cts` and
`PNR_STAGE: hold_repair`). **Q1 said the post-CTS residual would be above 1 500; it is
2 345 — 99.66 % of the way from `before CTS` 312 to post-hold 2 352. So the phrase
"CTS and hold repair", which this report uses in several places, is measurably
"CTS": hold repair adds 222 cells, 3 644.04 µm² (0.06 % of movable) and moves the
residual by SEVEN.** **Q2 said the downsize rung would leave under 50 % of the pre-swap
residual; it leaves 12.7 % — 2 337 → 296, an 87.3 % collapse, and 296 is BELOW the 312
the design had before CTS ever ran.** The area it frees, **163 375.56 µm²**, matches the
number derived beforehand from the PDK's own `SITE ... SIZE 0.56 BY 3.92` and seven
`MACRO` widths **to 0.0048 µm²**, and `swapped=2089` matches the census taken before the
block ran. **So the arms are sitting in the rung with the worst return** — rungs 1–4 grow the
displacement bound 20× and move the residual by ≤12 in ~2350; rung 5 removes the bound
and, at the one arm far enough in to show it, has bought **255 of 2 296 (11.1 %) in
over ten hours of one core**, taking its phase-2 illegal count to 2 035 (J81) — **and
the flow's own next rung is aimed exactly at what is left.** *(An earlier draft of this
sentence said rung 5 "cannot help them" and that there is no legal site at any radius.
Both are refuted by the arm's own log and corrected here — J81. What survives is that
**2 035 of 2 296 cells have no legal site anywhere on the die**, which is the sharper
statement, and that ten hours of search buys what ten minutes of downsizing beats by
7×.)*
`PROBE_POSTSWAP_OK=0`: even after the swap the placement is not legal, so this is not a
manufactured pass, and P1/P2/P3 stay registered and unanswered.

**★ AND THE "POST-CTS, NOT POST-HOLD" CAVEAT IS NOW REMOVED BY MEASUREMENT (J83).** J80
had to bound the distance to the arms' own state by ARGUMENT. A second probe runs the
flow's own `repair_timing -hold` and removes it — **and it took THREE tries, each
eliminating a named cause with a run**: v1's hold repair was a no-op (`no estimated
parasitics`); v2 added the flow's own `estimate_parasitics -placement`, the warning
disappeared, and it was **still** a no-op; v3 added `set_propagated_clock` — a
TIMING-VIEW reconstruction that moves no cell and leaves the netlist byte-identical —
and printed **`Found 1341 endpoints with hold violations`, the arm's number exactly**,
**224 hold buffers against the arm's 222**, movable within **+0.0030 %**, and a rung-1
residual of **2 352, also the arm's exactly**. *(The entry control as FIRST written could
not have caught any of this: it allowed ±1 % on a cell count whose signal is 222 cells =
**0.057 %** — a tolerance **17× larger than its own signal**, which is a PASS decided
when the bound was chosen rather than when the measurement was taken. It was restated
with a bound smaller than the signal before v3 ran.)* **In that state, the flow's own
rung 6 takes the residual from 2 344 to 303 — −87.1 % — in SIXTEEN MINUTES**, on a state
five arms have been sitting in for between one and thirteen hours, freeing
**163 375.56 µm²** — the PDK-derived figure to **0.0048 µm²** for the second time. And
J80's argued bound turns out right to the digit: post-CTS `2 337 → 296`, post-hold
`2 344 → 303`, **the same offset of 7 on both sides of the swap, which is exactly what
hold repair moved the rung-1 residual by**. `PROBE_POSTSWAP_OK=0` still — the placement
is illegal afterwards, nothing says the chip closes, and rung 7 would face **303** stuck
cells instead of 2 344. **A chip-AGNOSTIC plugin defect fell out of it
and is fixed and pushed (§8): the downsize's own `catch` guard is inverted, so the rung
that is worth 87.3 % here could fail in TOTAL SILENCE.**

**As of this dispatch the row's floor rests on FIVE dies, not three: the initial-
placement verdict is monotone at every die measured** — FAILED at 3300 and at the
4 022 probe, OK at 4 522 / 3 800 / 4 200 / 5 153 and now **5 434, which answered a
predicate registered before it at 14:16:30 with `recovered 341/341` (J73)**. **And
both constants of the build-to figure are now DERIVED rather than fitted:**
`f` = `filltie` width / 2×`-distance` = **1.120/28.0 = 4.0000 % exactly** (J71) and
`S` = `ceil(0.02 × 191 615)` spare cells priced from the PDK's LEF = **98 437.16 µm²
to 0.00** (J70) — together they predict `DPL-0008` at every die and both stages with a
worst residual of **0.0032 µm²**, so the fixed term needs no third population. Three
mechanism sentences that were WRONG were corrected in the doing (J71, J72), and no
published number moved. **The build-to number was measured at three independent dies (J37)** and a
fourth on this dispatch — and the fourth is what showed it was NOT reproducing but
drifting with the probe, which is J65's correction below — and **the brief's own named pre-check,
`general_precheck`, has now been run on each of the six separately (J39)**, so the
four UNDETERMINED tiers are what that program answered ABOUT THAT CHIP rather than
what I inferred from the control. **On a re-dispatch (J49), every published figure
in the `edge_llm_matmul_accel` row was re-derived from the arms' raw OpenROAD lines
and reproduces to the digit it publishes** — the row does not rest on this report's
own prose. Nothing changed; the point of doing it is that it could have. The one
side-finding this job produced for the plugin was pushed to the remote **twice** — the
original sha kept unmoved, plus the same patch rebased and re-verified (J50, §8) —
and **both are now superseded by work that landed on main at 01:34 today, which I
established by running my own patch's test file against current main and getting 9 of
9 (J66), not by reading its commit subject.** **Neither branch is on the remote any
more (J74): re-queried on this dispatch, `git ls-remote --heads` returned **0** matching
`jself` out of 67 heads — and re-queried again on the NEXT dispatch, still **0**, now out
of **72** (J79).** The `0` is the half the sentence rests on and it has held at every
query; the total was never load-bearing and moved by 5 in under two hours, because it
counts other people's branches. *(That distinction is J79's, and it exists because a
standing ledger re-measured the line rather than re-reading it — the total is exactly
the kind of number that decays with nobody noticing.)* The original claim was true when
J50/J62/J66 measured it and expired without
anything recomputing it — the same decay class J62 was written to catch. Both commits
are preserved locally as a verified bundle plus format-patches with checksums
(`meas/_j68/bundles/`); nothing is lost, and nothing was lost that still had something
to land.

**Both NOT FEASIBLE verdicts were re-run from their sources on this dispatch, not
re-read from this report (J59).** They are the only two tiers that refuse a chip, so
they are the two where a failure to reproduce would move a verdict. `u_hawaii_adc`:
13 device flavors in the PDK, voltage tokens `03v3/05v0/06v0/10v0`, **0** files
naming 1.2 V anywhere under `libs.tech`, all four corner libs **ABSENT**.
`edge_llm_accel`: exactly three views (`.lef/.lib/.v`), **587** OBS/LAYER/RECT
records, **0** `*.gds`/`*.oas` under the design input tree. Every reading reproduces,
including J32's own correction. Neither verdict moved. **Re-run again on this
dispatch (J67) as a standing control: 13 flavors, tokens `03v3/05v0/06v0/10v0`, **0**
files naming 1.2 V under `libs.tech`; 3 views, **587** records, **0** `*.gds`/`*.oas`. Identical
to the digit both times.**

**And on this dispatch the one thing the row still listed as OPEN has an answer
(J51, §6).** The report had recorded that the post-hold legalizer's residual is flat
with die (2340 vs 2296) where the initial one is density-elastic (321 → 242), and
left the difference as an observation. Read across the CTS boundary, both arms' own
logs give the cause: **a +1 % cell count and a +4.8 % area increase from CTS and hold
repair multiply the illegal-cell count by 7.5–9.1×** (253 → 2296 at die 4200,
312 → 2352 at 3800). **The post-hold residual is therefore not a density effect and
is not evidence about die size** — which is why the arms sitting inside it neither
argues for a bigger die than this report publishes nor for a smaller one. The dwell
is priced the same way, against each arm's OWN initial full-die rung, which **ran the
identical window and terminated** (848 s / 1077 s). A **fourth arm is now running at
die 5153 µm — the core the then-published 5.875 mm build-to figure was derived from;
that figure has since been corrected to 6.139–6.165 mm (J65), which is why the probe's
own reading turns out to sit one iterate short** — as
a stated-in-advance test of exactly that claim (§6). Its answer moves no verdict
either way.

**And the cause now has a name and a cell count (J53).** Reading the runner arms' own
`placed.def` and `post_cts.def`: `clock_tree_synthesis`, invoked
`-buf_list {clkbuf_4} -root_buf {clkbuf_16}`, instantiated the **ROOT** master
**2 055 times** — the identical count at two different dies — where the control under
the same invocation instantiated it **once**. At 28.000 µm against `clkbuf_4`'s
7.840 µm, those 2 053 added cells are **225 337 µm² = 82.3 %** of everything CTS and
hold repair added. **The flow's own next-but-one rung (`clkswap`) downsizes exactly
them — 2 089 matching instances, 163 376 µm², ~60 % of the increase — so the three
arms are on rung 5 of 9 and not out of moves.** Recorded, not acted on: no `-root_buf`
was changed and nothing was downsized by hand. **The fourth arm's initial ladder has
also already refuted one of this report's own pieces of reasoning (J54)** — the
initial residual does not fall monotonically with die (409 → 321 → 242 → **282**), so
§6's dismissed linear extrapolation was the wrong shape rather than merely
implausible, and movable area is now flat to **0.87 % across a core that grows
145.6 %** at four dies. **One thing this dispatch published and then refuted with its
own evidence (J57):** a runtime exponent fitted to two rungs, killed minutes later by
a third rung sitting in a log already open on this disk. It is corrected where it was
made, the surviving claim is narrowed to the controlled pair it was measured on, and
no verdict ever rested on it.

**This dispatch corrected a headline number of its own and closed the one prediction
left hanging (J60, J61), both by reading the arms' raw logs rather than this report.**
The floor chain had been adding the pad ring to the core rectangle's upper
**coordinate** instead of to its **width**, so every die in it was 10.1 µm too large:
the measured floor is **4.522 mm (20.45 mm²)**, not 4.532 mm — the ratio it is quoted
at, **1.58×**, does not move, and the build-to chain never had the defect because it
sizes from area. The report had been carrying both conventions at once, each
internally consistent, which is why five re-derivations did not surface it. And the
fourth arm answered at 11:17:47: **`INITIAL_DPL_LEGALIZE_OK` at die 5153 — the
build-to die this report publishes, its INITIAL placement now confirmed to legalize
by RUNNING it rather than by sizing it.** *(That word `INITIAL` is a correction this
dispatch made to its own sentence — J64. The bare version read as the whole flow, and
at the post-hold stage the same die does NOT legalize on rungs 1–4. The build-to
figure is untouched because it never came from the legalizer.)* J58's two numeric
predictions for that rung are refuted by 1.8–1.9× and its directional one held; the
ladder's runtime turns out not to be monotone in die, span or stuck count, and its
recovery is all-or-nothing (0/409 where it fails, 100 % at all three dies where it
passes).

**The one prediction §6 had left open is now ANSWERED, and it HELD (J64).** §6 had
written down, before the rung could exist, that if the post-hold residual is created
by CTS and hold repair rather than by density then the fourth arm would reach
post-hold with a residual **near 2 300, not near 0, at roughly 25 %** utilisation. It
reached it at **11:48:22** and printed **2 418 illegal cells at 27.4 %** — the count
**+5.1 %** off the prediction, the utilisation **+2.4 points** off, and the
alternative it was posed against ("collapses toward zero") refuted by the whole
2 418. **The settled residual is now flat at three dies whose post-hold utilisation
spans 1.73× — 2 352 → 2 296 → 2 418, a 5.18 % spread while density falls by nearly
half** — **and a FOURTH die has since answered a predicate registered before it printed
(J77): 2 409 at 25.1 % utilisation, which is not merely inside the registered
2 200–2 500 band but inside the 2 296–2 418 range the three earlier dies already
occupied. The range does not widen by a digit while the utilisation span it covers
grows 1.73× → 1.88×, and the claim is tested below 27.4 % for the first time.**
*(Those are each die's FIRST post-hold block, which is the convention this sentence
uses; 3800's drifts 2352 → 2352 → 2344 → 2340 across its four rungs while the others
are constant, so "settled" is the wrong word for a first block and the last-block
comparison elsewhere in this report is 2340 vs 2296 — both are recorded at §6 and
neither moves the 5.18 % by more than a hundredth.)* — and post-hold movable area is flat to **0.98 % at FOUR dies across a core
that grows +145.6 %**, the fourth point landing *inside* the band the earlier three
already defined without widening it by a digit. The ladder's own runtimes say why the
older arms are slow: rungs 2 and 3 cost **16.4 s between them and changed nothing**,
so rung 5 (whole-die search) is the only expensive rung and the only one still open.


**And this dispatch corrected a headline number of its own, in the direction that
makes the chip harder (J65).** §6 had sized the build-to die by applying the flow's
utilisation target to each arm's measured post-CTS+hold `movable + fixed` area, seen
the answer drift with the probe, and bounded the drift as *"mildly self-referential
and 1.5 % is the size of that effect"*. **The fourth arm lands at 6.112 mm, outside
the 5.875–5.963 mm range that hedge produced** — and the effect does not need bounding
because it is solvable: both die-dependent terms are linear in the core area, measured
at four dies and not fitted (`f` = **4.000 %** of the core, stable to 0.206 % across
cores differing by 145.6 %; `S` = **98 437.16 µm², identical to the last digit at all
four**), so `A* = 4(M+S)/(1−4f)` closes it. **Build-to: 5.875–5.963 mm → 6.139–6.165
mm, 2.05×–2.08× → 2.145×–2.154×** — +4.75 % in edge, +9.7 % in area. The old figures
were that rule's first four iterates. **The verdict is untouched at both ends**: this
row is core-limited at every rung of §6's ladder, 1.64× through 2.15×, and no rung
puts a pad ring in front of it. The measured **4.522 mm floor does not move at all** —
it has no sizing rule in it. **And the defect class was then hunted in the other five
rows and the control, and cannot live there (J67)**: every one of them is sized either
from a perimeter fit with no area in it, or from a STATIC yosys `area.txt` that
contains no tapcell, PDN, spare or fill term — `edge_llm_matmul_accel` is the only row
driven far enough through PnR to have a measured post-place area at all, which is
exactly why it is the only one that could have carried it.


**This dispatch audited the one kind of claim the report had never checked — its own
coordinates — and 2 of the 10 distinct ones it published did not say what the
sentence claims (J68).** A `file:line`
reads as the hardest evidence there is, because it invites the reader to go look, and
nothing in a report ever recomputes it. `meas/_j68/cite_audit.py` resolves **every**
coordinate `RESULT.md` publishes against the tree its sentence is about and prints the
line's actual text beside the claim. Eight resolve exactly, including all six
`pnr.tcl` line numbers and the PDK's `.subckt nfet_05v0`. Two do not: the report cited
**the same constant at two different lines of `phase3_one_shot_runner.py`** — 12604
(right) and 12021 (a comment about `catch`/`_NONFATAL:` markers) — and carried the contradiction through six
passes because nothing ever compared one citation against another; and the sentence
naming where the flow *sizes* the auto die pointed at `:13497`, a `PIN-LIMITED`
diagnostic string four lines past the call, where the formula is actually
`_auto_die_side_um` at **`:12686`**, computed at **`:12700`**. **No number, no verdict
and no tier moves** — the constants themselves were re-read from the tree and
reproduced by J49 and J59 — what was wrong is where I told the reader to look, which
is a claim about their ability to check me rather than about the chip. A third,
`pad_ring_gen.py:730`, is **right on main (823 lines) and out of range in my own
worktree (662)**, and named neither: a coordinate without a tree is half a coordinate.
**The checker then caught a defect in its own author's correction**: rewritten to
extract coordinates from `RESULT.md` instead of from a list I typed, it failed on a
bare colon-and-line-number my own fix had just introduced as prose, which its
"inherit the last file named" rule attached to the wrong file — J68's finding landing on J68. **It then caught
it twice more**: once in the paragraph summarising the first catch, and then, after
that was fixed, once more on the sentence that *quoted* the bad form as an example —
because **a mechanical reader cannot tell a citation from a quotation of one.** So the
report no longer contains the bare form at all, in any role. Final state:
**16 published coordinates, 0 that resolve in no tree, exit 0** *(16 rather than 10
because the extractor expands the two line RANGES into their endpoints and the fixes
added three coordinates of their own; the single remaining flag is
`pad_ring_gen.py:730`, whose sentence now names main)*. The audit is kept as a
standing gate rather than a one-off pass.

**★ AND THE POST-HOLD PREDICATE ANSWERED AT 14:34, AND IT SPLIT (J76) — one published
number moves.** J67 registered two predictions about a block OpenROAD had not written.
**The flatness one is REFUTED**: post-hold movable landed at **6 069 060.66 µm²**,
**above** the four-arm band's top by **+14 642 µm² (+0.24 %)**, and the rule registered
for that branch — *"the fixed point moves UP and I correct the number in the direction
that makes the chip harder"* — binds. Re-solved on five arms from the raw logs:
**build-to 6.139–6.165 mm → 6.139–6.171 mm, 2.145×–2.154× → 2.145×–2.156×** (top
+6.3 µm; low end unmoved). **The printed-number one HELD, and it is the sharper of the
two**: it predicted `fix_ph` = 1 265 902.23 and `DPL-0009` = 24.9–25.1 % before the
block existed, against 61.4 / 47.3 / 39.1 / 27.4 % at the four earlier dies — measured
**1 264 887.41 (−0.080 %)** and **25.1 %, inside the band**. A curve fit has no reason
to land inside a 0.2-point window 12.4 points below the nearest arm. **The predicate's
stated REASON, however, is not what five points show, and the correction says so
rather than smuggling it in**: post-hold movable ordered by core runs 6.0351 → 6.0544
→ **5.9956** → 6.0357 → 6.0691 mm² — **not monotone**, the lowest sitting in the middle
of the range — so the spread simply widens from 0.98 % to **1.22 %** and the number
moves because the registered rule says it must, not because "movable grows" was
demonstrated. **`S` is now identical to the last digit at FIVE dies (spread 0.0000 µm²)**,
and **the verdict does not move**: core-limited at every rung, **1.64× through 2.156×**,
pad ring in front of it at none. **A THIRD predicate, registered at 14:48:27 while the
line did not exist, answered at 14:54:05 and HELD (J77)**: arm5's post-hold residual is
**2 409 at 25.1 % utilisation** — inside not just the registered 2 200–2 500 band but
inside the **2 296–2 418** range the three earlier dies already occupied, so the range
gains span (1.73× → 1.88× in utilisation) without gaining spread. The report's
"the post-hold residual is not a density effect" is now tested **below 27.4 % for the
first time**, and holds. Two paragraphs written earlier in this same dispatch
said "no published number moves"; they were true then and are marked where they stand.

**And the fifth arm's INITIAL block has landed, which tests J65's stated extrapolation
at the core it extrapolated TO (J69).** J65 had assumed movable area stays flat out to
a 29.2 mm² core, 11 % beyond anything measured. Arm5's core is **29 188 086.05 µm²**
and it prints **5 687 809.30 µm²** movable and **1 166 450.25 µm²** fixed — so **the
die-proportional term `f` now holds at FIVE dies across a core that grows 173.4 %**
(published on four across 145.6 %), spanning 3.9963–4.0048 %, and initial movable is
flat to **0.94 %** on the same span. *(Exactly ONE of the fixed point's two constants
is measurable here. `f` is read at the INITIAL block, which arm5 has printed; the
other constant `S` and the movable term `M` are **post-hold** quantities and still
rest on four dies — they are precisely what the registered predicate is waiting for,
and this entry does not borrow their answer.)*

**And the OTHER constant, the one nothing was waiting on, turned out to have a
description rather than a measurement — so it was counted (J70).** The report said `S`
was *"the spare/`dont_touch` block, a constant because the flow inserts a fixed set of
spares"*: an inference **from** the constancy, dressed as an account **of** it.
Counted in the arms' own `post_cts.def` and priced from the PDK's own LEF,
**`S` is the 3833 FIXED spare cells — 7 masters, 98 437.16 µm², to 0.00 µm², at both
dies checked.** The description was over by exactly the other half: the spare *block*
is **7 666 instances / 132 093.96 µm², 34.2 % larger**, because the 3833
`spare_tielo_*_drv` tie-low drivers are `PLACED` and not `FIXED`, so `DPL-0008` never
sees them and they sit inside `M` instead — 0.56 % of it, and part of why `M` is flat.
The whole chain now derives: `ceil(0.02 × 191 615) = 3833` from
`_DEFAULT_SPARE_DENSITY`, the seven counts from `_SPARE_CELL_MIX`'s weights, the area
from seven `SIZE` records. **And its die-independence gets a testable reason instead of
a coincidence**: the count is 2 % of `IFP-0105 = 191 615`, identical at all five arms —
had the flow taken it from the post-resize count, which grows **+40.5 %** with die
(J54), `S` would carry a die-dependent term and the fixed point would need a third one.
**No number moves.** `A*`, the build-to 6.139–6.165 mm and every verdict stand; what
moves is that the last unexplained constant in the central chain is now derived end to
end, and one sentence describing it was a third too big. *(That was true when written.
Two hours later the fifth arm's post-hold block moved the build-to band's top to
**6.171 mm** under a pre-registered rule — J76. `S` and the verdicts are untouched.)*

**Going after the OTHER constant the same way refuted a mechanism this report asserts
three times, and closed the chain (J71).** `f` is not a fitted constant either: taps at
`-distance 14.0` sit 28.0 µm apart, `filltie` is 1.120 µm wide, so **`f` = 1.120/28.0 =
4.0000 % exactly** — a PDK `SIZE` record over a flow constant — and from those two
numbers alone the tapcell COUNT at each of five dies is predicted to **±0.12 %** with
nothing fitted. `n_tapcells × 4.3904 µm²` then reproduces `DPL-0008` to **±0.00 µm² at
all five**, so the "**plus PDN**" the report attached to it adds exactly zero: PDN
straps are wiring, and `DPL-0008` counts COMPONENTS. **And the mechanism the report
gave for its own cell-count growth is wrong.** It says, in three places, that the count
running 346 888 → 487 266 (+40.5 %; +48.5 % at five arms) is *"because a larger die
means longer nets and the resizer buffers them"*, one of them adding that the movable
area stays flat *"because those extra cells are small and the resizer downsizes
elsewhere to pay for them"*. `DPL-0393` counts the **tapcells** too. Net of them the
design's own cell count is **249 591 / 249 797 / 247 441 / 248 524 / 249 329 — flat to
0.95 % across a core that grows 173.4 %.** There are no extra cells, nothing is being
downsized to pay for them, and the movable area is flat for the plain reason that it is
**the same population**; the whole +48.5 % is the tapcell lattice tracking the core by
construction. That also dissolves a tension the report had been carrying unnoticed — a
count growing 40 % beside an area flat to 0.94 % — which it had bridged with an
invented story instead of a subtraction. **J54's causal account of the stuck-cell
reversal loses its mechanism with it**; the reversal itself is untouched and now has a
fifth point, and what replaces the cause is named as a **hypothesis, not a finding**
(the fixed lattice overtakes the design's own population, 0.390 → 1.066 taps per design
cell across the turn), with the run that would test it named and **not** run, because a
lower residual bought by pruning taps would be a manufactured pass. **And with both halves counted, `DPL-0008` closes**: predicted
outright as `n_tapcells × 4.3904 + 98 437.16` at every die and both stages, **worst
residual 0.0032 µm² where `DPL` prints two decimals** — no third population is needed
anywhere. **No published number moves**: `f` = 4.000 % and `S` = 98 437.16 µm² are what
they were, the build-to stays 6.139–6.165 mm, the floor stays 4.522 mm, and all six
verdicts stand. *(The build-to half of that sentence expired at 14:34 — **6.139–6.171
mm** now, J76. `f`, `S`, the floor and all six verdicts did not.)* What "derived" buys is not accuracy — those digits were already right —
but a different kind of confidence: a fitted constant is only as good as its range, and
J65 exists precisely because a rule evaluated inside its range returned an iterate.
`f = 1.120/28.0` has no range.

**Refuting that mechanism left the load-bearing term `M` with NO explanation, so it was
measured too (J72).** A flat cell count does not give a flat area — the mix could move.
Censusing the movable population by master in two arms' `post_cts.def` and pricing it
from the LEF: the instance count moves by **+238 (+0.09 %)** and the **mix moves by
hundreds** — `buf_4` **−556** and `buf_8` **+432**, a −17 087 / +24 657 µm² trade, plus
`buf_2` +384 and `mux2_1` +221, for a net **+0.297 %** of movable area. So the resizer
is *not* idle on the bigger die; it does what "longer nets" predicts, **by swapping
buffer strengths rather than by adding cells**. `M` is flat because **the netlist is
the same netlist and the die's effect on it is a re-sizing, not an addition** — a
mechanism, measured, consistent with the published 0.98 % flatness. *(Bounded:
`post_cts.def` is written before hold repair and `post_hold.def` does not exist on any
arm yet, so this is the CTS-stage population at two dies. It explains the flatness; it
does not re-measure it.)* **The same census also confirms J71 from a second artefact
class** — `placed.def`'s movable count and area are **exactly** J71's
`DPL-0393 − tapcells` and the initial `DPL-0007`, at both dies, to the digit: a log
subtraction and a DEF census landing on the same numbers independently. **And one
published percentage was suspected, chased and could not be broken**: J53's *"82.3 % of
the CTS+hold movable increase"* reconstructed from the DEFs as +367 274.52 µm² against
a published 273 789.74 — a 34 % gap in a denominator, exactly the shape of a real
defect. It is not one. J53's baseline is the log's `before CTS` block and it
reconstructs to the last digit (273 789.74 and 277 499.62, 82.3 % and 81.2 %); mine was
wrong because **`placed.def` contains 0 `spare*` instances** — it is written before
spare insertion, so any DEF-measured CTS delta silently includes the 3 833 tie-low
drivers. Two defensible baselines 93 485 µm² apart, and J53's sentence is about the
other one. **J53 stands unchanged**, and it is written down because "I checked it and
it held" is a different claim from "I did not check it". And `f`, **published before this arm existed**, predicts
arm5's fixed area **11.3 % beyond the largest core it was fitted on** to within
**−0.086 %** of what OpenROAD printed — the strongest evidence in this report that
`f * core` is a mechanism and not a curve fit. *(Out of sample in the DATA; the
arithmetic is mine and post-hoc, so it is the weaker instrument and is reported as
such. The registered post-hold predicate is untouched and still waiting.)* The
stuck-cell reversal J54 found now has a **fifth point and is still rising —
409 → 321 → 242 → 282 → 341** — so two consecutive rises, not one wobble. **That predicate was registered at 13:44:44 —
while the log held eight `recovered 0/341` lines and no verdict, where it printed
`NOT YET` and exited 2 — and at 14:16:30 it ANSWERED and HELD (J73):
`recovered 341/341`, `INITIAL_DPL_LEGALIZE_OK disp=full-die 5434x5434`.** The
ladder's recovery is now **all-or-nothing at five dies** — 0/409, 321/321, 242/242,
282/282, 341/341, no partial anywhere. And the outcome that would have moved a
published number did **not** occur: a `0/341` refusal at a die **17.4 % larger in area
than one that legalizes** would have turned §6's **4.522 mm floor** into one point of
a band. Instead the initial verdict is **monotone in die at every die measured** —
FAILED at 3300 and at the 4 022 probe, OK at 4 522 / 3 800 / 4 200 / 5 153 / 5 434 —
so the floor stands where it was measured. Arm5's rung 5 cost **3 299.09 s**, the
longest successful one yet, and the runtime is still not monotone in die or in the
residual it recovers, exactly as J61 found. *(The first version of that five-die table
split each log at `PNR_STAGE: cts` and swept up the post-verdict legalizations,
reporting 5153 as 1/364 in 100.84 s where its rung 5 is 282/282 in 2 878.10 s; cutting
at the verdict line reproduces J51 and J61 to the digit — J73.)*


| IC | tier | one line |
|---|---|---|
| `u_hawaii_adc` | NOT FEASIBLE | upheld — needs 1.2 V, PDK's lowest device is **3.3 V (2.75×)**. The pin half OVERTURNED 8.5× |
| `edge_llm_accel` | NOT FEASIBLE | upheld — but for a reason its OWN docs give: declared completion criterion is **"tape-out simulation" on nangate45** (J43) |
| `caravel_user_project` | UNDETERMINED | original reason OVERTURNED — declares **SKY130A**, a **fixed** harness die and **`mpw_precheck`** (J45); 637 signal / 645 total bits, 0 die pins (J46) |
| `opentitan_aes` | UNDETERMINED | original reason OVERTURNED — 512/515 bits are a test wrapper's |
| `ibex` | UNDETERMINED | original reason OVERTURNED — 173/262 is a bus to on-die memory |
| `edge_llm_matmul_accel` | **UNDETERMINED — binding constraint MEASURED, original reason OVERTURNED** | CORE-limited, never pad-limited. Initial placement legalizes at a **4.522 mm** die (**1.58×** its 2.862 mm pad floor) and refuses at 4.022 mm — that is a measured FLOOR. The full flow needs **+7.52 / +7.51 / +7.26 / +7.13 %** more area after CTS **at four dies**; sized by the flow's own rule on it — **solved for self-consistency, not probed** — **6.139–6.171 mm = 2.145×–2.156×** the pad floor *(corrected this dispatch from 5.875–5.963 mm: that rung's area contains a term proportional to the die, so the old figures were its first iterates — J65)*. Its INITIAL placement is measured to legalize at the 5153 probe (J61); at post-hold the same die returns the **2 418**-cell residual §6 predicted for it before the rung existed (J64) |

---

agent `jself`, host 8HD-d / 192.168.1.112. PDK `gf180mcuD` (open).
Evidence: **`findings.md`** (J0–J91). Scripts `meas/`, synthesis `synth/`,
chip-path runs `proj/`, pad-ring probes `probe_padring/` and `meas/_probe_*`.
**★ And the rung-5 INTERIOR is now read rather than assumed silent (J81): the die-4200 arm broke a 10-hour silence at 15:59:23 and its full-die rung has recovered **255 of 2 296 (11.1 %)**, phase-2 illegal down to **2 035**; die 3800 has **31 of 2 340**; dies 5153 and 5434 are at **0**, on roughly half the CPU, so that is *not yet* rather than *never*. The rung works — it is just 7× worse than the next one (J80) at 60× the cost.**

**★ All five arms re-checked at 15:4x on a later dispatch (J79): alive, not assumed alive — sampled 20 s apart, all five `openroad` pids gained exactly 20 s of CPU (70 095→70 115 / 52 003→52 023 / 50 536→50 556 / 26 786→26 806 / 16 122→16 142 s), one full core each, host loadavg 16.50 on 32 cores and 85 GB free — and still 0 of 5 with a post-hold verdict printed.**

Live arms, re-checked **13:49**: `proj/edge_llm_matmul_accel` (die 3300, 13 h 50 m),
`proj/matmul_d3800` (full runner, die 3800, 10 h 03 m) and
`meas/matmul_fullflow/fullflow_4200` (die 4200, 9 h 52 m) — **all three past CTS+hold
and on the `POST_HOLD_LEGALIZE` ladder's full-die rung**, none yet at its verdict
(J37), all three still accumulating CPU (**65 208 / 47 111 / 45 524 s** re-read at
**14:18**, host loadavg ~15–22 on 32 cores — down from 18.7 at 12:03, so the wait is
not a starvation artefact that is getting worse). **That silence is priced rather than waited
on, and it is priced against the arms THEMSELVES rather than against the control: each
one's INITIAL ladder ran the identical full-die window and terminated, in 1 077 s and
848 s (J51) — **and that yardstick is now a RATIO (J75): the post-hold rung is the
same rung on ~7–9× the residual, and has already cost 3.0× / 4.6× / 8.3× / 40.6× its
own arm's initial rung-5 time without terminating** *(a lower bound from an mtime
proxy, comparing each arm to itself only, no runtime model fitted)* — and the fourth arm has now measured directly why the wait is on THAT
rung and no other, by running rungs 2 and 3 in 16.4 s between them for no change at
all (J64).** It does not move the row, and the row never depended on it. A run named
`fullflow_3800` ended `rc=137` at 04:10 and is superseded by `matmul_d3800` at the
same die. The **fourth arm**, `meas/matmul_fullflow/fullflow_5153` (die 5153 µm =
a 5122.88 µm core), started 10:13:12, cleared its initial ladder
(`INITIAL_DPL_LEGALIZE_OK disp=full-die 5153x5153` at 11:17:47, 2 878.10 s, 282/282
recovered — J61), **reached `PNR_STAGE: hold_repair` at 11:48:22 and ANSWERED the
post-hold prediction §6 had recorded before it could: 2 418 illegal cells at 27.4 %
utilisation, against a written-down "near 2 300 at roughly 25 %" (J64).** It has since
reached **its own rung 5** — the whole-die search the three older arms are sitting on —
with **19 940 s** of CPU at 13:49.

The **fifth arm**, `meas/matmul_fullflow/fullflow_5434` (die 5434 µm, a
**29 188 086.05 µm²** core = the fixed point's own core to **+0.015 %**), started
12:56:14 and has printed its **initial** DPL block: movable **5 687 809.30 µm²**, fixed
**1 166 450.25 µm²**, utilisation **23.5 %**, residual **341** — which puts the
die-proportional term `f` at FIVE dies across a core that grows **173.4 %** — and
tests it **11.3 % out of sample to −0.086 %**. `S` and `M` are post-hold and remain
at four (J69). **It cleared its initial ladder at 14:16:30** —
`recovered 341/341`, `INITIAL_DPL_LEGALIZE_OK disp=full-die 5434x5434`, rung 5 costing
**3 299.09 s** — which is the registered 13:44:44 predicate answering **HELD** (J73).
It reached `PNR_STAGE: hold_repair` at **14:34:07** and
**answered BOTH remaining registered predicates**: J67's fixed-point pair at 14:34
(flatness **REFUTED**, printed-number **HELD** — J76) and J77's residual predicate at
**14:54:05** (**HELD**, 2 409 at 25.1 %). It is now on **rung 3** of its post-hold
ladder — it has since reached **rung 5**, so **all five arms are now on the same
rung**, the whole-die search, arm5's residual constant at **2 409 across all four
rungs so far** (joining 4200 and 5153; 3800 remains the only die that drifts). **Every predicate this report registered in advance has been answered**, and
re-running all three at the end — expecting nothing — caught a **third instance of one
cut-defect (J78)**, this time inside the initial-ladder verdict instrument itself: its
answer had silently changed from `HELD` to `anomalous` because the run progressed past
CTS and its bound was the next stage marker rather than the verdict line. **The
recorded HELD was correct** — the raw log has `recovered 341/341` at line 515
immediately before `INITIAL_DPL_LEGALIZE_OK` at line 529 — but *a predicate whose
answer depends on when you ask it is not a predicate*. It now imports the shared
`logcut.initial_ladder()` that J75 created an hour earlier, and reproduces `HELD`. The
other two are structurally immune (both read the **first** block of their stage).
Plugin tree: own detached worktree `wt/` at **`7a47263f1`**, clean — my one commit on
top of `a00f53f20`, which was `origin/main` at v1.11.66 when the branch was cut (§8).
That branch is deliberately left unmoved and is now 30 commits behind; the second one,
`jself/pad-site-declared-in-pdk-tool-config-on-v1.11.68` @ **`f452ea45a`**, was pushed
and **NOT landed**. **★ As of 14:2x on that dispatch NEITHER is on the remote (J74)**, and
**still not on this one (J79)** — `git ls-remote --heads origin` returns **`0`**
matching `jself`, out of 67 heads then and **72** now. `f452ea45a`
survives here only as a loose object in a shared object store, so it is now preserved
as a **verified bundle** (`git bundle verify` → *is okay*, 2 refs, 8 941 bytes) plus
format-patches and `SHA256SUMS.txt` under `meas/_j68/bundles/`. The refs used to build
it are **per-worktree** (`refs/worktree/*`), because this worktree shares
`/home/reyerchu/vibe-ic/.git` with 60-plus others and its tag namespace is not mine to
write into.

**★ Both are now SUPERSEDED, and I measured that rather than inferred it (J66).**
Re-queried on this dispatch, `origin/main` is **`a4caccefe`** (v1.11.69) and the
branch is **1 ahead / 214 BEHIND** — the "1 ahead / 0 behind" this line used to carry
has expired. In those 214 commits, **`741a87cc1` (authored 01:34:54 today) fixes the
same defect by the same mechanism**: `PAD_FAKE_SITES` read out of
`libs.tech/<flow>/<io library>/config.tcl`. Same mechanism is not the same subject, so
I ran **my own patch's test file against current main** in the pinned image: 8 failed
on a NAME (`discover_io_tool_configs` → main's `discover_io_site_declarations`), and
with the assertions mapped onto main's `resolve_site()` accessor, **9 of 9 pass**.
Every behaviour my patch asserted — including *the LEF wins over the config* and *a
PDK with neither still refuses* — is on main today, and main additionally has
`PAD_SITE_DECLARATION_AMBIGUOUS`, which mine does not. **Main's version is a superset,
not an alternative.** There is nothing left in it to land, and I did not rebase it,
delete it, or open anything against main. *(This sentence used to end "the branch
stays on the remote as evidence of a finding". It does not stay — J74 re-queried the
remote on this dispatch and found 0 `jself` heads among 67. The evidence is now a
verified local bundle instead, which is a weaker place to keep it and is said so.)* *(Earlier drafts of this line named the BASE and called it the tree —
J49 — then named only the branch that is 30 behind — J62. This is the third correction
to it and the first that changes what it MEANS rather than which sha it points at.)*

**This dispatch re-derived the corrected headline with a SECOND, independent script
and put the one extrapolation it still rests on into a running measurement (J67).**
`meas/_j67/extract_dpl.py` re-extracts all four arms' DPL blocks from the raw
OpenROAD logs and re-solves the fixed point without reading a number out of this
report; **every published figure reproduces to the digit** — `f` = 4.000 %, `S` =
98 437.16 µm² identical at four dies *(five now — J76)*, build-to **6.139–6.165 mm**
*(**6.139–6.171 mm** since the fifth arm answered — J76)*, and the probe form
iterating 5872.8 → 6110.2 → 6147.2 → 6153.1 → 6154.0 → 6154.2. J65 had stated one
assumption — that movable area stays flat out to a 29.2 mm² core, 11 % beyond
anything measured — so a **FIFTH arm is now running at exactly that core** (sweep die
5434, `IFP-0102` = 29 188 086.05 µm², **+0.015 %** of the fixed point's own core), with
the pass/fail band written down before it answers. **And the die cap was re-established
BY EXECUTION rather than by reading, which found two things the reading missed: the
flow's congestion self-rescue (`_compute_loosened_die`) dies at the same 2000 µm
constant as the upsize loop, and the cap is ASYMMETRIC — above it the flow can still
shrink a die and can never grow one. Every one of the six rungs of that ladder makes
the die BIGGER, so 6.154 mm is the TIGHTEST die the flow's own machinery would ever
hand this design, and the pad ring is in front of it at none of them (§7).** My first
positive control for that probe was itself wrong — a 1900 µm die whose grown die was
already over the cap, so its `None` proved nothing — and it is recorded where it was
made rather than quietly replaced.

I read `/home/reyerchu/_gf180_priv/` and never write to it — **measured, not
asserted (J40)**: 0 files there modified since 05:12 and 0 since 08:50 (re-measured 09:19, J49), both their worktrees
`git status --porcelain` clean, and every file touched in my session window is part
of THEIR commit `5240ead2c` on THEIR branch or a `__pycache__` entry for THEIR
modules. **`sha256` is NOT one
of my six and I do not adjudicate it — `jpadsite` on 8HD-3 owns it**, because what
blocks it is our own `PAD_SITE_NOT_FOUND` and not a fact about the chip. It
appears here only as **the CONTROL** (§5): the smallest design that drives this
path end to end, so that "UNDETERMINED" on the rows above is a measured distance
rather than a shrug. `spm` and `subservient` are the shuttle arms' and are not
mine either.

---

## 0. The correction, as one line of arithmetic

Five of the six were refused with a number against **52**; `u_hawaii_adc` with a
number against **6**. Both constants come out of the shuttle operator's
`src/slot_defines.svh`. They are the pad inventory of a slot you *buy*. On the
self-tape-out path there is no slot file, so **"how many pads may this design
have?" is not a question that exists on this path.** The flow's own code asks a
different one:

```python
# pad_ring_gen._place, verbatim
side_width = (urx - llx) - 2*edge - 2*corner_sw
if total > avail:  ->  ERROR PAD_RING_DOES_NOT_FIT
```

Solved for the smallest square die that holds N pads, with the PDK's own numbers
(pad **75.000 µm**, corner **355.000 µm**, `PAD_EDGE_SPACING` **26** — all read in J2):

```
die_edge_min(N) = 762 + 75 * ceil(N/4)      [um]
```

**That constraint never refuses a design. It prices it in microns.** And it is a
LOWER BOUND, not the answer: a second geometric refusal quantises the die to the
minimum site width, so the first PLACEABLE die can sit a little above this one.
Which is why every die in this report is confirmed by running the flow's own
placer at it, and at one pad width below it. §4, §4a.

### And there is no die-area ceiling in anything this host holds (J4)

* the PDK's seal-ring PCell clamps the die **up** only —
  `minimum_width = 3*16 µm`, `self.w = max(minimum_width, self.w)`; no maximum
  anywhere in `libs.tech`.
* `grep -rniE "max_die|die_area_max|maximum die|reticle" programs/*.py flow/*.yaml`
  finds no PROCESS die-area ceiling in the plugin. **That pattern matches neither
  `die_area_budget_um` nor `_DEFAULT_DIE_MAX_UM`**, and I missed BOTH with it —
  the grep was right about what it asked and I read it as an answer to more.
  §4a is the first; the second is `_DEFAULT_DIE_MAX_UM = 2000`, a cap on how far
  the runner will grow a die BY ITSELF, whose own error text names the remedy —
  *"INCREASE `--die-um` MANUALLY or shrink the netlist"* — and which my own runs
  at 3300 / 3800 / 4200 µm walked straight past. Neither can refuse a design:
  one refuses only against a budget the DESIGN declares, the other refuses only
  to resize on its own. (J19, J27.)
* the only place the reticle is named, the plugin marks it **OPEN and foundry-owned**
  (`PENDING_FOUNDRY_reticle_steppers`) and lists it in `_OPERATOR_OWNED_ON_SHUTTLE`.

Buying a slot is exactly the transaction that makes the reticle somebody else's
problem. Give the slot up and the ceiling does not get bigger — **it becomes
unknown.** So "NOT FEASIBLE on die area" cannot be reached from a PROCESS ceiling
on this host, and where a design is merely large the answer is a number of mm².

**But re-verifying that grep for this report turned up a ceiling of a different
kind that the first pass missed:** `area_total_vs_budget_check.py` gates die area
against the design's **OWN declared budget**, and its only bound is arithmetic —
cell area cannot exceed die area, because that is what utilisation ≤ 1.0 means.
That gate is not a process ceiling and it is not a threshold anybody picked, and
it changes two of the six rows. §4a.

---

## 0b. ★ What each design DECLARES about itself — and the PDK two of them never asked for (J45)

Added on the sixth pass, because §2's and §3's reasons turned out to be inherited
from the verdicts under review rather than measured from the designs. Read from each
design's own input tree and nothing else:

```
chip                   own docs                  declared PDK   declared deliverable / scope
u_hawaii_adc           L1 + L5 + L9              (analog spec)  IOVDD 1.8 V + CORE 1.2 V, on-chip LDO
edge_llm_accel         L1..L9 (9 engineered)     nangate45      "tape-out simulation"; 無 pad ring; macro-level
caravel_user_project   L1..L9 (9 engineered)     SKY130A        user_project_wrapper GDS for the Caravel
                                                                harness; mpw_precheck-clean; die FIXED
opentitan_aes          10 upstream docs          NONE           "AES HWIP Technical Specification", --top earlgrey
ibex                   18 upstream .rst          NONE           upstream CPU-core project documentation
edge_llm_matmul_accel  1 plain-language request  NONE NAMED     "old, free, open ... boring and standard"
```

**Two of the six were adjudicated on a PDK they did not declare** — `edge_llm_accel`
declares `nangate45` (§3, J43) and `caravel_user_project` declares **SKY130A**. Both
rows now carry that caveat where the number is quoted.

**`caravel_user_project` says three more things §4 did not use.** Its die is **FIXED
by the harness** (`fixed_dont_change/` DEF), not chosen by it; it **relies on the
harness power ring**, so it has no power-pad budget of its own to compute; and **its
declared pre-check is `mpw_precheck`** — the harness's own, which is neither the
shuttle's nor `general_precheck`. The brief asks which pre-check applies; for the
thing this design says it is, its own documents name a third one. So *"does it
self-tape-out?"* is a question its own documents rule out — a wrapper whose die, pin
order and power ring all belong to a harness is not a die. **A better reason for the
same tier** than "637 ports, 0 die pins".

**Three of the six declare no PDK at all**, which is why no caveat belongs on them:
`opentitan_aes` is an HWIP block inside `--top earlgrey` by its own title line, `ibex`
is an upstream CPU-core project — `grep -rliE` over both docs trees returns **0 files**
naming any PDK, **0** stating a die or area target, **0** mentioning a pad ring, which
is exactly §4's finding arrived at from the designs' side. `edge_llm_matmul_accel`
names none but *describes* one, and gf180mcuD satisfies the description (§6, J44).

**No tier moves and no binding constraint moves.** The pattern across J42–J45 is one
error repeated: I measured the PDK, the geometry and the flow exhaustively and did not
open the designs' own input documents until the sixth pass. Every correction in this
group came from files that were in the tree the whole time.

---

## 0c. ★ The slot has an AREA, and it is the yardstick "52 pads" should have been (J48)

The source evidence publishes the slot's real geometry, quoted from the operator
tool's own output — a number neither the brief nor the first draft of this report used:

```
Check Slot Size   Layout size 3932.0 x 5122.0  ==  slot 1x1 3932.0 x 5122.0
```

**One 1x1 slot = 20.14 mm².** Every die measured in this report, in that unit:

```
row                      die mm    die mm²   slots   what the die is
caravel_user_project     12.912    166.72    8.28    standalone-die reading (*)
opentitan_aes            10.512    110.50    5.49    pad-perimeter die, 517 pads
ibex                      5.712     32.63    1.62    pad-perimeter die, 264 pads
edge_llm_matmul_accel     4.522     20.45    1.02    MEASURED floor: initial placement legalizes
edge_llm_matmul_accel     6.139     37.69    1.87    build-to, flow's own routing-headroom rule (J65)
edge_llm_matmul_accel     6.171     38.08    1.89    build-to, upper end of the same fixed point
                                                     (was 6.165/38.01 on four arms; the fifth
                                                      moved it +6.3 um under a registered rule, J76)
edge_llm_accel            3.087      9.53    0.47    pad-perimeter die (**)
u_hawaii_adc              2.052      4.21    0.21    core-forced die, holds 68 pads
```

**This is the comparison the originals should have made.** The brief asks for *"a die
of X mm² against a Y mm² ceiling"* and forbids *"a number against the shuttle's 52"*.
**52 was a pad inventory; 20.14 mm² is an area** — and area is what every one of these
designs is actually limited by. The originals reached for the number in the slot file
that was easiest to count, and it was the wrong one.

**The most useful row falls straight out of it:** `edge_llm_matmul_accel`'s measured
floor is **20.45 mm² = 1.02 slots** — almost exactly one whole slot's worth of silicon
before anything legalises — and **1.71–1.77 slots** to build with routing headroom.
That is what was true about it. "109 bits vs 52" measured a pad list that §6 shows fits
at 2.862 mm with room to spare.

**It is NOT a ceiling.** §0 measured that nothing here imposes a die-area ceiling on
this path; giving up the slot makes the limit unknown, not larger. This is a yardstick
— one purchasable unit of silicon — useful because it is concrete and externally
priced. And two rows carry caveats already established: **(*)** `caravel_user_project`
declares a FIXED harness die (§0b/J45), so 8.28 slots is what it would cost as a die it
never claims to be; **(**)** `edge_llm_accel` declares *"無 pad ring;macro-level"*
(§3/J43), so its pad-perimeter die is hypothetical and its real problem is 32.09 mm² of
logic against its own 5.76 mm² budget. The comparison is clean only for
`edge_llm_matmul_accel`, and indicative for `opentitan_aes` and `ibex`.

---

## 1. The six rows

| IC | verdict on the SELF-TAPE-OUT path | the constraint that binds THERE |
|---|---|---|
| `u_hawaii_adc` | **NOT FEASIBLE — UPHELD, one half only** | **needs a 1.2 V core device; the PDK ships 13 device flavors and the lowest is 3.3 V — 2.75× above it — and 0 corner libraries at any 1.2 V bracket (J31).** The "≥8 analog pins vs 6" half is **OVERTURNED by 8.5×** — its own core forces a die that holds **68 pads** and it asks for 24 (§2) |
| `edge_llm_accel` | **NOT FEASIBLE — UPHELD, DIFFERENT REASON, and a SECOND one the FLOW ITSELF refuses** | macro has **0 MASK-LEVEL views** (abstract + Liberty + behavioural, no GDS/OASIS) — unstreamable on *every* path, never a shuttle fact. And `area_total_vs_budget_check` **rc 1 `AREA_TOTAL_OVER_DECLARED_DIE`: 3.2086e+07 µm² vs its own declared 5.7600e+06 µm², 5.57×** (§3, §4a) |
| `caravel_user_project` | **NOT UPHELD — original reason OVERTURNED.** Tier: UNDETERMINED | **637 signal bits (645 with the 8 power pins) across 27 ports — 0 of them die pins** (J46) — a macro in somebody else's die, and its L1/L9 say so (J45). Pad-facing surface is **75 pads / 2.188 mm**. Area gate **PASSES at utilisation 0.0005** (§4, §4a) |
| `opentitan_aes` | **NOT UPHELD — original reason OVERTURNED.** Tier: UNDETERMINED | **512 of the 515 bits are one test wrapper's flattened register writes**; in silicon the key goes over a 32-bit bus. Ring **PLACES at 10.512 mm** (§4) |
| `ibex` | **NOT UPHELD — original reason OVERTURNED.** Tier: UNDETERMINED | **173 of the 262 bits are a bus to ON-DIE memory, 64 more are straps.** Ring **PLACES at 5.712 mm** (§4) |
| `edge_llm_matmul_accel` | **UNDETERMINED — original reason OVERTURNED, binding constraint MEASURED** | **CORE-limited, never pad-limited.** 111 pads want **2.862 mm**; at the flow's OWN `_AUTO_DIE_TARGET_UTIL = 0.25` its measured post-CTS+hold area wants a **5.387–5.413 mm** core → a **6.139–6.171 mm** die (37.7–38.1 mm²) = **2.145×–2.156×** the pad floor, **measured at FIVE dies, post-hold movable flat to 1.22 % across a core 173.4 % larger and NOT monotone in it (J37, J64, J76)**. *(That die is the FIXED POINT of the flow's rule. The **5.875–5.963 mm / 2.05×–2.08×** this row published earlier is the same rule's first iterates: the area it sizes from contains the tapcell lattice, 4.000 % of the core at all five dies and exactly `filltie`/2×`-distance` = 1.120/28.0 (J71), so every probe smaller than the answer under-reports it — J65.)* Initial placement alone legalizes at 4.522 mm = 1.58×, which is the floor — **and that floor now rests on FIVE dies whose verdict is monotone: FAILED at 4.022, OK at 4.522 / 4.922 / 5.875 / 6.155, with all-or-nothing recovery (0/409, 321/321, 242/242, 282/282, 341/341) and no partial anywhere (J73)**. "109 bits vs 52" measured a quantity that has nothing to do with what stops it (§6) |

**Not one of the six is refused by a pad budget on this path, and for three of them
the number that refused them was never a pad count at all.**

### The measurement (`meas/selftape_die_floor.py`, detail in J5)

Ports parsed by the flow's own `slot_pad_budget_check.parse_top_ports`; cell area
from `yosys stat -liberty` against the PDK's own `gf180mcu_fd_sc_mcu7t5v0` at
`tt_025C_5v00`; core-limited edge at 60 % utilisation plus the 350 µm ring depth
and the 26 µm offset on all four sides.

```
design                   sigbits   pads  /side  padDie_mm  cells_mm2 coreDie_mm   DIE_mm  DIE_mm2  limited-by
caravel_user_project         637    645    162     12.912     0.0055      0.848   12.912   166.72  PADS
edge_llm_accel               120    122     31      3.087    32.0855   (§3)     [11.417] 130.35  CORE+MACRO
edge_llm_matmul_accel        109    111     28      2.862     3.8619      3.289  [4.522]   20.45  CORE
ibex                         262    264     66      5.712     0.3730      1.540    5.712    32.63  PADS
opentitan_aes                515    517    130     10.512     0.8468      1.940   10.512   110.50  PADS
```

**Two DIE cells are bracketed because the script alone does not produce them.**
Re-running `meas/selftape_die_floor.py` today prints `edge_llm_accel 8.065` and
`edge_llm_matmul_accel 3.289` for that column, and both are superseded above:

* `edge_llm_accel` — yosys cannot price the macro at all (`Area for cell type
  \fakeram45_2048x39 is unknown!`), so the script sees only the logic. **11.417 mm**
  comes from `meas/edge_llm_accel_floor.py`, which adds the 390 PDK SRAM macros the
  design's 1 597 440 scratchpad bits require (§3). Re-run for this report; both
  scripts reproduce their published numbers exactly.
* `edge_llm_matmul_accel`'s DIE column is **bracketed because it was superseded**:
  3.289 mm was my own 60 %-utilisation estimate, and 60 % is denser than anything
  this design legalises at. The measured figure is **4.522 mm** (§6), and the row is
  kept beside it rather than quietly rewritten. **4.522 mm is the FLOOR** — the
smallest die at which *initial* placement legalises; the full flow measures 7.52 %
more area after CTS and hold, which at the flow's own sizing rule — solved rather
than probed — is **6.154 mm** (§6, J29, J65; the 5.875 mm this line first carried was
that rule's first iterate).

Every handed-down number reproduced from the design's own RTL by me:
`caravel_user_project` **637**, `opentitan_aes` **515**, `ibex` **262**,
`edge_llm_accel` **120**. `caravel_user_project`'s 0.0055 mm² is the staged
`user_proj_example` (a counter), which is what that wrapper actually contains.

Synthesis against the PDK's own cells COMPLETED for **all five digital designs**
(`u_hawaii_adc` is analog and has no logic to map). An earlier pass recorded
`edge_llm_accel` as a synthesis failure on a wrapper exit code of 125; the log
reaches `End of script` and both `edge_llm_accel_synth.v` (200 MB) and `area.txt`
were written, so that reading was wrong and the area it produced is in the table
above. `yosys stat -liberty` chip areas, verbatim:

```
caravel_user_project  \user_project_wrapper        5 518.7280 um^2
sha256 (control)      \chip_top                  284 895.2512
ibex                  \chip_top                  372 979.8464
opentitan_aes         \chip_top                  846 796.2048
edge_llm_matmul_accel \edge_llm_matmul_accel   3 861 894.6240
edge_llm_accel        \edge_llm_accel         32 085 504.1920   + 20 macros yosys cannot price
```

---

## 2. `u_hawaii_adc` — UPHELD, and only one half survives.

**Original:** *"IHP SG13G2 1.2 V analog; gf180mcuD has no 1.2 V device and none of
its corner libs; ≥8 analog pins vs 6 max."*

### The half that DIES — "≥8 analog pins vs 6 max": OVERTURNED, by 8.5×

`6` is `NUM_ANALOG_PADS` in the operator's slot file (its largest value; the `1x1`
slot has 2). Measured instead from the PDK's own IO LEF:

```
MACRO gf180mcu_fd_io__asig_5p0
  CLASS PAD INOUT ;
  SIZE 75.000 BY 350.000 ;
```

**The analog pad is 75.000 µm wide — the same width as every other pad in the
library.** An analog pad costs exactly what a digital pad costs in perimeter, so
there is no separate analog budget on this path to be short of.

Then the arithmetic, done from the right boundary. Its datasheet declares
**"Die (core, no seal ring) — 1300 × 1300 µm"**: that number is the CORE, so the
pad ring goes OUTSIDE it, not inside:

```
declared CORE                                        1300 um
+ ring depth 350 + edge 26, four sides   ->  DIE     2052 um   (4.211 mm2)
usable side width at that die                        1290 um -> 17 pads/side = 68 pads
its datasheet pin list                                 24 pads
HEADROOM                                               44 pads
```

Confirmed by the flow's own placer rather than by me, with the refusal kept
reachable:

```
24 pads @ 2052 um -> PASS
68 pads @ 2052 um -> PASS                  <- the die is full
69 pads @ 2052 um -> PAD_RING_DOES_NOT_FIT
```

**Its own core forces a die that holds 68 pads; it asks for 24.** The pads were
never close to binding, and the analog half of the refusal is out by **8.5×**
(68 available against the 8 it was said not to have room for).

*(An earlier draft of this section computed `die_edge_min(24) = 1212 µm` and
called the declared 1300 "its own die, with 88 µm to spare". That put the pad ring
INSIDE a number the datasheet labels as the core. 1212 µm is the perimeter floor
for 24 pads considered alone, and it is far BELOW the 2052 µm this design's own
core forces — which is why the headroom is 44 pads and not 2.)*

### The half that SURVIVES — the device and its corner libraries

Its own datasheet names the supply it needs: *"supplies `IOVDD` (1.8 V), **`CORE`
(1.2 V)**"*. Re-run for this report against what the PDK actually ships:

```
$ grep -rhoiE '^\.subckt\s+[np]fet[a-z0-9_]*' libs.tech/ngspice/ | sort -u
nfet_03v3  nfet_03v3_dss  nfet_05v0  nfet_06v0  nfet_06v0_dss  nfet_06v0_nvt  nfet_10v0_asym
pfet_03v3  pfet_03v3_dss  pfet_05v0  pfet_06v0  pfet_06v0_dss  pfet_10v0_asym      -> 13 flavors

$ ... | grep -oE '[0-9]{2}v[0-9]'      # every voltage token across all 13
03v3   05v0   06v0   10v0        -> the LOWEST device in the PDK is 3.3 V.  1.2 V: none.

$ for f in cornerMOShv.lib cornerMOSlv.lib cornerRES.lib cornerCAP.lib; do find <pdk> -name $f; done
  cornerMOShv.lib    ABSENT
  cornerMOSlv.lib    ABSENT
  cornerRES.lib      ABSENT
  cornerCAP.lib      ABSENT

$ grep -rlE '1v2|1p2v|_12v|1\.2 ?V' libs.tech/ngspice/ libs.ref/*/lib/
  (nothing)
```

> **Correction — mine (J31).** An earlier draft enumerated the device set with
> `grep '^\s*\.lib\s+[a-z]fet_...'` and reported **four classes**. That grep asks
> which flavors carry a *corner-library entry*, not which the PDK *ships*; it misses
> the `_dss` variants and `{n,p}fet_05v0`, which are real `.subckt` declarations
> (`sm141064.ngspice:46959`) with no independent corner entry. **7 of 13, reported as
> an inventory.** The verdict does not move — nothing is below 3.3 V on either
> count — and the corrected inventory states it harder.

And asked independently of the timing libraries rather than the device models:

```
$ find libs.ref -name "*.lib" | sed -E 's#.*__##; s#\.lib##' | grep -oE '[0-9]v[0-9]{2}' | sort -u
1v62 1v80 1v98 | 2v25 2v50 2v75 2v97 3v00 3v30 3v60 3v63 | 4v50 5v00 5v50
   -> nominal domains 1.8 / 2.5 / 3.3 / 5.0 V

$ find <pdk> -iname "*1v2*" -o -iname "*1v08*" -o -iname "*1v32*"     (nothing, anywhere)
```

The 1v62/1v80/1v98 corners are **not** a 1.8 V core device — all 44 of them belong to
`gf180mcu_{fd,ocd}_ip_sram` and the two 5v0 standard-cell libraries.

**VERDICT: NOT FEASIBLE, upheld — for the device-and-corner-library half only.**
### ★ The REQUIREMENT, re-measured from the design's own documents (J42)

J31 measured the PDK side of this hard. It never measured the DESIGN side — *"needs
1.2 V"* was quoted from the original NOT SUITABLE text, which is the thing under
review. The design ships its own docs and they say more than the verdict did:

```
L1_DATASHEET.md   | Supplies | IO/analog 1.8 V (IOVDD) · core 1.2 V |
L5_ANALOG_SPEC.md | Vdd (core) | 1.2 | 1.1-1.3 | V |      <- with a tolerance band
L5_ANALOG_SPEC.md | Vin        | 1.8 | 1.6-2.0 | V | IOVDD
L5_ANALOG_SPEC.md | Dropout <=0.5 V — headroom (1.8 IOVDD - 1.2 CORE = 0.6 V)
L9_CONSTRAINTS.md | IOVDD 1.8 V | CORE 1.2 V |
```

**Two rails below the PDK's device floor, not one** — the original named only the
1.2 V — and they are not independent: the on-chip LDO is specified by their
difference. Even at the top of the design's OWN tolerance band, 1.3 V, the gap to
3.3 V is **2.54×**.

**And the fact that looks like a counterexample, named and answered.** gf180mcuD
DOES ship 1.8 V artefacts — `find -iname "*1v8*"` returns **11 files** and the
corner brackets run `1v62 1v80 1v98 2v25 ... 5v50`. They are
`gf180mcu_fd_sc_mcu7t5v0__tt_025C_1v80.lib`, its 9-track sibling and the SRAM
macros: **characterisation corners of the 5 V-oxide libraries** (`nom_voltage: 1.8`),
not a 1.8 V device. For a DIGITAL block that is a real 1.8 V option. For an ADC
modulator and an LDO it is not — analog needs device models at the operating point,
and the lowest is `nfet_03v3`. 1.2 V has neither: no device, no lib, lowest corner
bracket `1v62`. *(I formed the hypothesis "both rails absent, verdict is stronger
than stated", measured it, and it was wrong. Recorded because anyone grepping this
PDK for `1v8` finds those 11 files, and §2 previously gave them nothing to check it
against.)*

A number against a number: **the design needs a 1.2 V core device; the PDK ships
13 device flavors and the lowest is 3.3 V — 2.75× above it — with zero corner
libraries at any 1.2 V bracket.** No pad assignment of ours changes either count — this is a statement about what the process contains,
not about where the signals leave the die. Re-specifying the core supply to a
class the PDK ships is a **design change**, not a path change.

**The original verdict's stated reason was half wrong, and the wrong half was the
half that came from the shuttle.**

---

## 3. `edge_llm_accel` — UPHELD, but the shuttle was never the reason

### ★ CORRECTION (J43) — I judged it against a bar its own documents say it does not claim to meet

Applying J42's test to this row too — *measure the requirement from the design, not
from the verdict under review* — found something worse than a missing measurement.
The design's own documents, in the tree I had:

```
L1:33  | 目標 PDK | `nangate45` (NanGate / FreePDK45 Open Cell Library, Si2) |
L1:45  abstract macro(無真實 GDS)。因此本 IC 的完成標準為
L1:46  「tape-out simulation」= synth -> PnR -> CTS -> detailed route -> GDS 輸出
L8:26  FakeRAM45 為 abstract macro(...標準 placeholder):無真實電晶體 GDS、
       無 memory-compiler 簽核 — 與 Kimi K3 Nangate45 demo 同一限制
L9:37  | Pin placement | 工具自選(無 pad ring;macro-level) |
```

**The missing mask-level view is DECLARED, not discovered.** Half one below measures
it correctly and that measurement stands — but the design states it itself, names it
a standard OpenROAD-flow-scripts placeholder, names the precedent it shares the
limitation with, and **draws the conclusion before I did**: its declared completion
criterion is **"tape-out simulation"**, with the SRAM as an abstract outline. So
*"cannot be streamed out on any path"* is right about the geometry and wrong about
the design — it reads as a defect I found, and it is a scope the design declared.

**The verdict does not move; its REASON does:**

> **NOT FEASIBLE for self-tape-out, UPHELD** — because its own declared completion
> criterion is **tape-out SIMULATION on nangate45** and it says so in writing. A
> design whose success condition is a routed GDS with an abstract SRAM outline is not
> a self-tape-out candidate, on this PDK or on its own. **Out of scope by
> declaration, not by defect.**

Two more of my own claims land on this:

* **§4a's `5.57×` compares a gf180mcuD synthesis against a nangate45 budget.** The
  `2400x2400` is the design's own and §4a says so — but it is a **45 nm** number,
  sized against a named 45 nm reference (L1:27). The `3.2086e+07` is a **180 nm**
  synthesis. The gate is arithmetically right that this PAIR cannot be placed; the
  pair is one nobody asked for. Quoted bare it reads as a design overrun and it is
  substantially a process substitution.
* **§4 prices a pad ring this design says it does not have** — `122 pads / 3087 µm`
  against L9:37's *"無 pad ring;macro-level"*. That is exactly the correction §4
  already applies to `caravel_user_project`, sitting uncorrected on another row of
  the same table.

What would be wrong to conclude is that the design is therefore fine. It cannot be
self-taped-out either way. What changes is that this is a statement about what it set
out to be, and this report presented it as a finding about what it failed at.

### Half one: a macro with no geometry — unstreamable on every path

Re-verified first-hand for this report against the tree the macro actually lives
in — `_gf180_priv/bdata/ic/edge_llm_accel/input/pdk_local/fakeram45/` (J32; an
earlier draft quoted a relative path that resolves nowhere in my own tree, and the
listing behind it was the shuttle arm's, which I did not say):

```
$ ls fakeram45_2048x39.*
fakeram45_2048x39.lef   fakeram45_2048x39.lib   fakeram45_2048x39.v

$ head -3 fakeram45_2048x39.lef
VERSION 5.7 ;
BUSBITCHARS "[]" ;
MACRO fakeram45_2048x39                      #  SIZE 206.910 BY 219.800 ;  CLASS BLOCK ;

$ grep -cE "^\s*(OBS|LAYER|RECT)" fakeram45_2048x39.lef            ->  587
$ find <design input tree> \( -iname "*.gds" -o -iname "*.oas" \) | wc -l   ->  0
```

> **Correction — mine (J32).** An earlier draft said the macro has **"no geometry
> in any view"**. It has 587 LAYER/RECT/OBS records — pin shapes and blockages —
> which is why it places and routes fine. What it has none of is **mask-level**
> layout.

Abstract + Liberty + behavioural model, and **0 mask-level layout views**. A die
containing it cannot be streamed out on *any* path — not because a placer would
refuse it, but because at stream-out there is nothing to merge. That is a property
of the design input; the slot never entered into it. `yosys` says the same thing from the
other side — it maps the design happily and then cannot price the block:

```
Area for cell type \fakeram45_2048x39 is unknown!
```

### Half two, which the first pass MISSED: the logic alone overruns its own die

The earlier pass counted only the memory and floored the die at 9.789 mm. That
understated it. Yosys could not price the macro, but it DID price everything
else, and the everything-else is **32.086 mm²** — against the design's own
declared target of **2400 × 2400 µm = 5.76 mm²**. Its logic alone is **5.6× the
die it declares for itself, before a single memory bit.** That is a
design-versus-its-own-datasheet mismatch and it has nothing to do with pads, with
52, or with a shuttle.

Re-targeting the memory to the PDK's own SRAM is a design change, and taken
(`meas/edge_llm_accel_floor.py`, every input read from the PDK's own LEF and the
design's own parameters):

```
logic, priced by yosys against the PDK's own cells      32.086 mm^2
   of which sequential                                   8.526 mm^2  (26.57 %)
scratchpad 20 x 79872 bits                            = 1,597,440 bits
the PDK's own sram512x8m8wm1  431.86 x 484.88 um = 209,400.3 um^2 for 4096 bits
macros needed  ceil(1,597,440/4096) = 390               81.666 mm^2
                                                       ---------
cells + macros                                         113.752 mm^2

   packing   core mm^2  core edge mm   + pad ring: DIE mm   DIE mm^2
      1.00       113.8        10.665               11.417      130.4  (impossible)
      0.80       142.2        11.924               12.676      160.7
      0.70       162.5        12.748               13.500      182.2
      0.60       189.6        13.769               14.521      210.9
```

On the shuttle this was **4.15× the largest slot's user area** — a ratio against a
purchase. Restated on this path it is a die edge of **at least 11.417 mm even at
an impossible 100 % packing**, ~13.5 mm at a realistic 70 %, against its own
declared 2.4 mm and against a pad-perimeter floor of only 3.087 mm. Per §0 there
is no ceiling on this host to compare those to, so the die size is stated as a
number and is not itself the refusal.

**And the second half is not my arithmetic — the flow's own gate says it (§4a):**

```
$ area_total_vs_budget_check meas/areagate/edge_llm_accel --die-area-um 2400x2400 --area-unit-um2
rc 1
[FAIL] AREA_TOTAL_OVER_DECLARED_DIE: synthesised cell area 3.2086e+07 um^2
  (phase2/stage2/synth/stats.json) exceeds the DECLARED die area 5.7600e+06 um^2
  (2400x2400 um, L19.die_area_budget_um) by 5.57x — the design cannot be placed
  on the declared die at any utilisation
```

`2400x2400` came out of the design's own L1 document and `3.2086e+07` out of the
flow's own producer run on the design's own synthesis log. I supplied neither.

**VERDICT: NOT FEASIBLE, upheld — on the unstreamable-macro half, which was never
a shuttle fact, and now on a second half the shuttle number also concealed and
which the flow REFUSES on its own authority: the design does not fit its own
declared die by 5.57× before its memory is counted. The absolute die size is not
a refusal here and is stated as a number.**

---

## 4. ★ The three whose number was never a pad count (J15)

The brief's correction is that "637 bits vs 52" is a true sentence about the
SHUTTLE and not an answer about the CHIP. Measured at the source it is worse than
that for three of the six: **the port list the number was counted from is not a
die boundary on any path.**

### `caravel_user_project` — 637 signal bits, 0 of them die pins

*(**637 or 645? Both — J46.** The brief says 637, the source evidence says 645, and
this report used each in a different place without reconciling them. Re-derived from
the RTL with `defines.v` resolved — `MPRJ_IO_PADS` = 38, `analog_io` = `[28:0]` —
**637 is the signal bits and 645 is every bit including the eight power pins**;
neither is wrong and neither document said which it was counting. It is also not a
PORT count: the wrapper has **27** ports. And re-deriving it with the flow's own
`parse_top_ports` but WITHOUT the `params` dict returns **498** — a silently wrong
answer, short by exactly `3x(38-1) + (29-1) = 139`, because every macro-width port
collapses to one bit. Using the real program is not the same as using it the way the
flow does. The row does not depend on which count: **0 of them are die pins** at all
three.)*

Its own documents: *"Top deliverable: `user_project_wrapper` **hardened GDS**,
ready for Caravel harness integration"* (L1:7); *"the wrapper relies on the
**harness power ring**"* (L9:16); `DIE_AREA = [0,0,2920,3520]` µm, **fixed**.

```
8 supply inouts (vdda1/2 vssa1/2 vccd1/2 vssd1/2) ...... harness supply nets
wb_clk_i, wb_rst_i, wbs_* .......................  106  bus to the management SoC
la_data_in/out/oenb [128] x3 ....................  384  logic-analyzer probes
io_in/io_out/io_oeb [38] x3 .....................  114  -> the HARNESS's GPIO pads
analog_io [29] ..................................   29
user_clock2, user_irq[3] .........................   4
                                                   637   = the handed-down figure
```

A macro has no pad ring, so **"how many pads?" answers zero**, and 637-against-52
compared a macro's port count to a die's pad budget.

### `opentitan_aes` — 512 of the 515 bits are one wrapper's convenience

`chip_top.sv`'s own header says `aes_wrap` *"drives the full TL-UL register
programming sequence (CTRL/AUX/KEY/IV/DATA) via an internal FSM, and exposes a
flat interface"*. `aes_input[128] + aes_key[256] + aes_output[128] = 512 of 515 =
99.4 %`. In silicon this IP is programmed **32 bits at a time over TL-UL**. A part
that brought its AES key out on 256 bond pads would be a security defect rather
than a floorplan.

### `ibex` — 173 of the 262 bits are a bus to on-die memory, 64 more are straps

```
instr_* ....  68     data_* .... 105     ->  memory bus 173  (66 %)
hart_id_i[32] + boot_addr_i[32] ......... 64   strapped, not pinned
everything else ......................... 25
                                          262
```

It is a **core**, shipped with an integration manual, whose instruction and data
buses terminate in on-die SRAM on every real part.

### Both readings answered — and the ring places under the harsher one

`meas/perimeter_probe.py` (J14) hands the flow's own inequality the question at
the die §0 predicts, and then at **one pad width (75 µm) less, which must refuse**:

*(Disclosure, added after checking rather than assumed — J41: `build()` writes the
`pad_assignment.json` these probes use; it does not call `pad_assignment_gen`. The
INEQUALITY is the flow's — `run()` drives `programs/pad_ring_gen.py` by subprocess —
but the INPUT was mine. Checked against what `pad_assignment_gen` actually produces
(77 pads → 20/19/19/19), the probe's round-robin gives the **identical split at every
pad count quoted here** — 24/75/77/111/122/264/517/645 — and the refusal depends only
on the max side load, `ceil(N/4)`, which is equal in both. So these dies are what this
repo's OWN assignment step yields, not an approximation of it. What the check does not
cover: pad ORDER within a side, immaterial here because every probe pad carries one
master.)*

```
design                    pads    die_um  AT THE PREDICTED DIE   ONE PAD SMALLER
caravel_user_project       645     12912  PASS                   PAD_RING_DOES_NOT_FIT
opentitan_aes              517     10512  PASS                   PAD_RING_DOES_NOT_FIT
ibex                       264      5712  PASS                   PAD_RING_DOES_NOT_FIT
edge_llm_matmul_accel      111      2862  PASS                   PAD_RING_DOES_NOT_FIT
edge_llm_accel             122      3087  PASS                   PAD_RING_DOES_NOT_FIT  (*)
u_hawaii_adc                24      1212  PASS                   PAD_RING_DOES_NOT_FIT
```

Six for six, tight to one pad width in both directions. **And every pad count here
reconciles to the source evidence exactly (J47):** `_gf180_priv/RESULT.md` counts
SIGNAL bits — 515 / 262 / 120 / 109, all four reproduced here to the bit — and this
table counts what a DIE needs, which is those plus **a clock pad and a reset pad**
(named by the flow's own `interface_budget`), plus whatever supply the design
declares (`caravel_user_project` +8, behind its own `` `ifdef USE_POWER_PINS ``).
The two documents were never in conflict; neither said which quantity it was
counting. **(*) `edge_llm_accel`'s row
is the same category error this table corrects for `caravel_user_project`: its L9
declares *"無 pad ring;macro-level"*, so its pad count is not defined either, and
3087 µm is what a ring WOULD cost if it were made a die (J43).** (`u_hawaii_adc`'s 1212 µm
is the perimeter floor for 24 pads considered ALONE. Its real die is larger and
set by its own core — 2052 µm, holding 68 pads against the 24 it asks for. §2.) `caravel_user_project` —
the 12.2× refusal — gets a real placed, **abutting** ring: 645 pads + 4 corners =
649 COMPONENTS in `padring.def`, `abuts: true`, sites resolved
`site_source=pdk_tool_config` (§8's capture; without it every row of this table
is `PAD_SITE_NOT_FOUND` and the question cannot be asked at all).

**VERDICT for the three: the original reason is NOT UPHELD on either reading.**
As the thing each one IS, its pad count is not defined, because it is not a die.
As a standalone die, its ring places and is priced in microns. The tier is
**UNDETERMINED** rather than PASS only because no finished layout exists to put
in front of the general pre-check — §7.

### And for `caravel_user_project`, most of those bits are not pads either (J17)

Of the bits that WOULD leave a standalone die, how many are actually pads? Asked
of the PDK's own bidirectional cell rather than of a fold heuristic:

```
MACRO gf180mcu_fd_io__bi_t   CLASS PAD INOUT ;   SIZE 75.000 BY 350.000 ;
  PIN A  CS  DVDD  DVSS  IE  OE  PAD  PD  PDRV0  PDRV1  PU  SL  VDD  VSS  Y
```

**A** (core→pad), **Y** (pad→core), **OE** (direction), and exactly **ONE `PAD`**.
`caravel_user_project` names its ports `io_in[38] / io_out[38] / io_oeb[38]` — it
has written down the tristate triple this cell implements, and `_oeb` IS the OE.
That is a structural fact about the cell, not a protocol guess:

```
io_{in,oeb,out}[38]   ->  114 core wires, 38 PADs;  76 bits are NOT pads

                                                        pads    die_um     mm^2
all 645 port bits as pads (standalone-die reading)       645     12912   166.72
pad-facing only: io[38] + analog_io[29] + 8 supply        75      2188     4.79
                                                            5.90x edge, 34.8x AREA
```

The flow's own `fold_candidates()` also offers `wbs_dat_i+wbs_dat_o` and
`la_data_in+la_data_out`, and for `ibex` it offers three pairs that are same-width
COINCIDENCES (`hart_id_i`+`instr_addr_o`). Its docstring refuses to decide those
and so do I — **none of them is taken.** Only the declared `_in/_out/_oeb` triple
is, and only `caravel_user_project` has one.

**A correction to my own formula, which the sweep found.** `die_edge_min(N)` is
the PERIMETER floor and nothing more. The flow carries a SECOND geometric refusal
— upstream's step 8, `PAD_CORNER_SPACING_NOT_SITE_MULTIPLE`: the corner-to-first-pad
gap must be a whole number of minimum site widths, *"because a ring that does not
abut carries no supply"*. At 75 pads the sides split 19/19/19/18 and the leftover
does not land on a site multiple, so the first PLACEABLE die is **2188.0, not
2187.0**:

```
75 pads @ 2112 um -> PAD_RING_DOES_NOT_FIT
75 pads @ 2187 um -> PAD_CORNER_SPACING_NOT_SITE_MULTIPLE
75 pads @ 2188 um -> PASS          <- smallest clean die, 4.787 mm^2
```

The six rows above all passed at exactly the formula's die; that was the
quantisation landing, not the formula being complete, and I would have reported
it as completeness had the sweep not been run.

### Power and ground pads price it too — measured, not assumed (`meas/power_pad_current.py`)

The brief names power/ground pad count as a constraint that binds here, and my
first table counted it as **0**. Measured from the PDK's own files:

```
gf180mcu_fd_io__dvdd   CLASS PAD POWER   SIZE 75.000 x 350.000 um
   PIN DVDD  Metal5  bond-pad opening 60.0 um  ->  90.0 mA
tech LEF, Metal5:  DCCURRENTDENSITY AVERAGE 1.5   (mA per um of width)
```

**One supply pad admits 90.0 mA DC, and it is 75.000 µm wide — the same width as
a signal pad.** So a supply pad enters the identical formula: it costs 75 µm of
perimeter, i.e. **18.75 µm of die edge, and buys 90 mA**. One amp of core current
costs 12 pads = **225 µm of die edge**. Like everything else on this path it
prices the die and cannot refuse it, because the perimeter grows with the die.
The PDK ships **no per-pad current limit in any liberty**; the 90 mA above is
derived from the pad's own conducting geometry and the PDK's own metal density,
and is stated as such.

And on the one design that reached a routed layout, the count is measured rather
than reasoned. Its own power report (which says of itself that it *"UNDERSTATES
the routed design"* — pre-PnR, no clock tree, no parasitics):

```
Group                  Internal  Switching    Leakage      Total
Total                  3.89e-02   2.40e-03   1.87e-06   4.13e-02      = 41.3 mW @ 5 V
                                                             -> 8.26 mA of core current
                                                             -> 1 supply pad, which covers it 10.9x

even at 10x that estimate   82.60 mA  ->  still 1 supply pad  =  18.8 um of die edge
```

**Ten times the understated figure still buys the whole die on one pad.** That is
what "power and ground price the die" means as a number rather than as a claim.

---

## 4a. ★ The flow's OWN die-area gate — and this is the first run that could use it (J19)

`area_total_vs_budget_check.py` gates the synthesised area against
`L19.fields.die_area_budget_um`. Its own docstring, measured over the published
corpus at `benchmark-data @ 146d665`:

```
L19*.json copies                                        177
  with die_area_budget_um set                             1   ('1300x1300')
published runs carrying a synth area figure (chip_area)   2
  of those, with an L19 die area budget                   0
```

**Not one published run could make this comparison.** Two of my six declare a die
in their own input documents, so two of them can. The one bound the gate applies
is arithmetic, in its own words: *"Standard-cell area cannot exceed die area ... A
design whose synthesised cell area already exceeds its DECLARED die cannot be
placed on that die at ANY utilisation. That bound is not a preference and not a
number anybody picked."* It explicitly refuses to apply a utilisation target.

### The unit was ESTABLISHED first, because the gate refuses to assume it

The gate treats an unestablished unit as its own refusal — *"a figure off by 1000x
reading as the same PASS as the true one"* — and `stats.json` deliberately
declines to name it. Established instead by two tools on ONE netlist:

```
flow's own stats.json   chip_area = 283975.4624   unit: "cell-library area unit"
openroad, same netlist  [INFO IFP-0103] Total instances area:  283975.462 um^2
                        [INFO IFP-0105] Number of instances:        10772
                        (logs/probe_fp_rerun.log — re-run for this report)
```

Identical to nine significant figures, and the second tool labels it `um^2`. That
is what `--area-unit-um2` requires a caller to have, and it is a measurement, not
an assumption.

**And the establishment transfers, because it is a fact about the LIBRARY, not
about that design.** All three synthesise against the same one:

```
proj/sha256           synth.log  ->  gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib
synth/edge_llm_accel  synth.ys   ->  ...same file, on dfflibmap, abc AND stat -liberty
synth/caravel_user_project        ->  ...same file
```

`yosys stat -liberty` sums that library's own `area` attribute. Establish its unit
once and every area quoted from it carries the same unit — which is why the gate
below can be given `--area-unit-um2` for designs whose own PnR never ran.

### Producer, then gate — both the flow's own, on the designs' real logs

`synth_area_stats_emit.py` on each real `synth.log` (no artefact hand-written),
then the gate with each ceiling taken from that design's OWN documents:

```
design                declared die   rc  verdict
edge_llm_accel        2400x2400       1  [FAIL]
caravel_user_project  2920x3520       0  [PASS]
ibex                  NONE            2  INCOMPLETE
opentitan_aes         NONE            2  INCOMPLETE
```

```
[FAIL] AREA_TOTAL_OVER_DECLARED_DIE: synthesised cell area 3.2086e+07 um^2
  exceeds the DECLARED die area 5.7600e+06 um^2 (2400x2400 um) by 5.57x —
  the design cannot be placed on the declared die at any utilisation

[PASS] cell area 5.5187e+03 um^2 against the DECLARED die area 1.0278e+07 um^2
  (2920x3520 um); utilization 0.0005, limit 1.0

INCOMPLETE: synthesised area was NOT compared against anything — missing
  authority: L19_CONSTRAINTS_PDK.json fields.die_area_budget_um
```

* **`edge_llm_accel`** — §3's second refusal is no longer my arithmetic. **The
  flow's own gate refuses it, rc 1.** `2400x2400` is the design's own L1 document;
  I supplied no number of my own.
* **`caravel_user_project`** — its core is **0.05 %** of the die it declares for
  itself. Whatever refuses this design, it is not area.
* **`ibex` / `opentitan_aes`** — INCOMPLETE is the CORRECT tier: they declare no
  die anywhere, and the gate refuses to invent one *"because a threshold nobody
  declared would turn an unanswered question into an answered one."* Two rc-2s
  beside one rc-1 and one rc-0 is also the positive control that this gate is not
  rubber-stamping.

---

## 5. The CONTROL — how far this path actually goes (`sha256`, not one of the six)

Not a verdict. The smallest design that drives the self-tape-out chain end to end,
so that "UNDETERMINED" is a measured distance rather than a shrug.

**0.5ic routes with no operator anywhere** (J23, re-read from the artefacts):
```
proj/sha256    route = SELF_TAPEOUT   operator_slot_files = []   answered 15/18
route_reason:  "no operator template, and the design declares deliverable=DIE:
                it is a die doing its own tape-out, so it takes the chip path"
$ ls proj/sha256/input/submission_template/  ->  SELF_TAPEOUT.txt  tapeout_declaration.json
```

**OUR pad assignment writes, from OUR own declaration** (probe project, 18/18
answered, 77 pads distributed 20/19/19/19 — a floorplan decision I authored, kept
out of `sha256`'s own declaration precisely so it cannot be mistaken for one):
```
$ pad_assignment_gen probe_padring    ->  rc 0    verdict: WROTE
all 13 variables provenance="declaration answer ..."; its own reason line:
"0 came from the operator's slot geometry and 13 from the design's own
 tape-out declaration"
```

**A real floorplan at our own die** (`logs/probe_fp_rerun.log`, re-run for this
report):
```
[INFO IFP-0100] Die BBox:  ( 0.000 0.000 ) ( 2300.000 2300.000 ) um
[INFO IFP-0101] Core BBox: ( 376.320 376.320 ) ( 1923.600 1920.800 ) um
[INFO IFP-0103] Total instances area:   283975.462 um^2
[INFO IFP-0104] Effective utilization:       0.119
[INFO IFP-0105] Number of instances:         10772
```
(against the flow's own `stats.json` chip_area 283975.4624 — the SAME netlist,
IDENTICAL to nine significant figures. An earlier draft of this line said "two
tools, 0.3 % apart" and compared against 284 895, which was MY standalone
synthesis script — a different netlist. §4a.) Utilisation 0.119, because the die
is set by the perimeter, exactly as §0 says.

**DFT, ATPG, and a detailed route that COMPLETES — but does not converge:**
```
[dft] step11_dft_scan_insertion  chain 1839 internal + 75 boundary; covers every flop=True
[dft] step11_dft_insertion       Fault ATPG measured stuck-at coverage = 95.05 %
[pnr] DRT-0198 Complete detail routing      <- the router's own completion line
[INFO DRT-0199]  Number of violations = 5.  <- and its own residual, which is not 0
```
"Complete detail routing" is the router saying it finished walking, not that the
geometry is clean. The two lines belong next to each other and the second one is
why the step's verdict below is FAIL.

OpenROAD was then killed by SIGSEGV inside `postroute_drv_repair`. The runner
caught it, refused to read the signal as a routing failure, and said so exactly:

> *"routing SUCCEEDED — the router printed its own completion line — and OpenROAD
> was then killed by SIGSEGV (signal 11) in postroute_drv_repair. This is a TOOL
> CRASH after a completed route, not a routing failure (rc=139 = 128+11). A Tcl
> `catch` cannot trap a signal ... Everything below the crashing line —
> `write_def routed.def` included — did NOT run."*

It then resumed from `routed_preantenna.def` with that one step omitted, and
`routed.def` was written (40 MB). Metal fill, extraction and multi-corner STA ran
after it. **That recovery is the flow at its best — a signal correctly refused as
a verdict — and it is worth saying plainly that it did not save the run.**

### And here is the honest limit — it does NOT finish, and the pre-check never runs

The run has since ENDED. Its verdict, and it is not a good one:

```
verdict: FAIL (steps: FAIL, completion audit: FAIL)
sign-off: 2 of 5 declared sign-off gate(s) PASSED; 3 FAILED: sta_signoff, sta_corner, sta_record
Steps: 69 total   PASS=0  FAIL=13  MISSING=11  SKIPPED=20  WAIVED-DEFERRED=1

FAIL pnr   ROUTE_NOT_CONVERGED: detailed route completed with N violations remaining
SKIP drc   GDS missing: phase3/stage3/pnr/chip_top.gds
SKIP lvs   upstream pnr step is FAIL — the final DEF / pin-label stages were never completed
FAIL canonicalize_artefacts  post-layout LEC FAILED (verdict=RUN_ERROR)
SKIP digital_hardmacro_gen   [REFUSED] no sign-off GDS under phase3/stage4/gds/
FAIL sta_signoff  STA_REAL_VIOLATION_FOUND
FAIL sta_corner   hold worst-slack -0.340 ns at the sign-off (min-RC) corner is VIOLATED
FAIL sta_record   SIGN-OFF corner 'FF' (role hold) VIOLATED: setup -62.240 ns
```

**No GDS. So the general pre-check the brief names never ran at all** — and that is
a comparison, not a single reading, because I kept the BEFORE:

```
BEFORE  verdict=NOT_DETERMINED  layouts_found=0  steps_with_evidence=0/11
AFTER   verdict=NOT_DETERMINED  layouts_found=0  steps_with_evidence=0/11
```

Timing, at the sign-off corners:

```
post-route SPEF STA, SS corner            wns -9.56   tns -328.34    VIOLATED
multi-corner OCV, SS 125C 4v50, derated   wns -12.52  tns -911.91    VIOLATED
                                          (early=0.95 late=1.05; STA_BASIS POST_ROUTE_SPEF)
[RSZ-0094] Found 55 endpoints with setup violations.
[RSZ-0062] Unable to repair all setup violations.
[RSZ-0033] No hold violations found.
[ANT-0001/0002] 0 pin violations, 0 net violations.     <- antenna IS clean
```

### Two things I had to check rather than repeat

**The routing violation count is 5, not the 3 the summary quotes.** The runner's
own line already disclaimed its number — *"route__drc_errors: 3 came from PARSING
THE LOG — the tool emitted no metric for it, so this value is a proxy for the
measurement, not the measurement. This step is NOT clean on this number."* Run the
flow's own reader over the FINISHED logs and it returns 5, twice over:

```
$ _signoff_drc_format.router_iter_last_count(openroad.log)         -> 5   (288 counts)
$ _signoff_drc_format.router_iter_last_count(openroad_resume.log)  -> 5   (145 counts)
[INFO DRT-0702] Post-route verification: 5 violation(s).
```

The parser is right; the READING was taken mid-run, when the log ended on an
earlier iteration. *(Provenance on that "5", asked because the other arm modified
`_signoff_drc_format.py` at 23:37 and two trees on this host carry it: compared
function by function via AST, `router_iter_last_count` and the only thing it calls,
`router_iter_counts`, are **byte-identical** in `origin/main` and their branch —
`0aa5f1224590` / `75a024c88efe` in both. The one function their commit changed,
`classify_text`, is not in the call path. So the number does not depend on which
copy ran. J40.)* The step verdict is FAIL either way, but the published proxy
UNDERSTATES the shipped geometry, which is the direction that matters.

**"Congestion-limited" is not what this design is.** The FAIL prose says so; the
run's own numbers do not:

```
[INFO IFP-0104] Effective utilization: 0.067        [INFO DPL-0009] Utilization: 12.1%
reports/route_congestion_trades.json:  congestion_aborted = false,  trades = []
```

At 6.7 % floorplan utilisation nothing is congested. The 5 residual violations sit
beside **3 620** `MIN_AREA_PATCH_UNPATCHABLE` lines of the form
`layer=Metal2 area=425600 need=577600` — minimum-area stubs the router cannot
patch, on a die whose size is set by its PAD PERIMETER and whose core is
consequently almost empty. That is a plausible reading and I am not asserting it
as the cause; what I can assert is that the stated cause does not match the run's
own utilisation figures.

### What the control therefore establishes

**The self-tape-out path carries a design from a declaration with no operator,
through our own pad assignment, our own floorplan, DFT, ATPG at 95.05 %, a
detailed route that completes, metal fill, extraction and multi-corner post-route
STA — and then stops, with no GDS and no pre-check.**

Two different things stop it, and only one of them is ours:

* **ours, chip-AGNOSTIC** — the pad ring (§7). Nothing in the flow instantiates
  the IO cells, so step 15.5ic cannot run for any design on any PDK.
* **this design's** — 5 unrepaired routing violations and −12.52 ns of setup at
  the SS corner against a 25.907 ns period the flow DERIVED from its documents.
  That would read the same on the shuttle.

So "UNDETERMINED" on the four rows is not a statement about those four designs.
**On this path today the smallest and simplest design in the set does not reach
the general pre-check either.** That is the measured distance, and it is the
honest reason those rows are not PASS.

---

## 6. `edge_llm_matmul_accel` — the only one where the CORE binds, and by how much

### ★ First, the question J43 forces: is THIS row measured on the wrong PDK too? (J44)

No — and the reason is in the design, not in my choice. Its entire input tree is:

```
src/edge_llm_matmul_accel/input/docs/00_user_request.md   (15 lines)
src/edge_llm_matmul_accel/rtl/edge_llm_matmul_accel.v
```

**A plain-language user request. No L1-L9, no declared PDK, no declared die** —
completely different provenance from the sibling's nine engineered documents. And it
says what process it wants: *"an old, free, **open manufacturing process** —
something **boring and standard**, not exotic."* **gf180mcuD is exactly that**, so
everything below is a valid instantiation of what was asked and carries none of §3's
caveat. Same measurement, same PDK, opposite answer on whether the PDK was right —
the difference is entirely in what each design declared.

**But the request states a size ask, and the die below does not meet it.** Three
times: *"a **small**, low-power chip"*, *"size and ambition **about like those
48-hour demo chips**"*, *"**small enough to be practical and cheap**"*. §6 measures
**34.5–35.6 mm²**. The demo it names is documented in this same benchmark set (the
sibling's L1:27) at **3.981 mm² on Nangate45**.

**That is deliberately not quoted as a ratio** — 3.981 is 45 nm and 34.5 is 180 nm,
and writing "8.7× too big" would repeat J43's error one finding later. The honest
form: **the request asks for the size of a 45 nm demo AND for an old, boring, open
process, and those two asks are in tension.** The measurement below is what makes the
tension precise. It does not move the tier (UNDETERMINED, J39) or the binding
constraint (core area, three dies) — it adds a second number-against-a-number that
comes from the DESIGN. The original "109 bits vs 52" measured a pad budget with
nothing to do with anything; this design's real size problem sat in its own request
document, and neither the original verdict nor my first pass read it.

Its 111 pads want a 2.862 mm die, and §4 shows the flow's own placer putting a
ring there (PASS at 2862, `PAD_RING_DOES_NOT_FIT` at 2787). **The pads were never
this design's problem.** Its own logic is, and the tool says so rather than me.

### The control — the runner's own PnR at a 3.300 mm die, quoted

```
[INFO IFP-0100] Die BBox:  ( 0 0 ) ( 3300.000 3300.000 ) um
[INFO IFP-0102] Core area:                     10 677 204.742 um^2
[INFO IFP-0103] Total instances area:           4 305 072.576 um^2   (191 615 insts)
[INFO IFP-0104] Effective utilization:                0.403
[INFO GPL-0018] Movable instances area:         4 834 234.484 um^2
[INFO GPL-0019] Utilization:                        47.163 %
[INFO GPL-0059] Movable instances area:         6 332 674.998 um^2  <- after timing-driven GP
...
diamond recovery: recovered 0/409 stuck cells.      (ten times)
INITIAL_DPL_LEGALIZE_FAILED
```

**The area that has to fit is not the synthesised one.** `yosys` gives
**3.862 mm²**; DFT insertion takes it to **4.305** (+18.86 %); and what the
detailed legalizer is then handed is **6.102 mm²** — `DPL-0007` movable
**5.675** plus `DPL-0008` fixed **0.427** — which is **57.1 %** of the
10.677 mm² core, and `DPL-0009` prints exactly that. There it saturates: ten
complete diamond recoveries, every one `recovered 0/409`.

> **Correction — mine, and it is about which OpenROAD line to read (J29).** An
> earlier draft of this paragraph quoted `GPL-0059` = **6.333 mm²** and called it
> "what the legalizer has to place", at 59.3 %. It is not. `GPL-0059` is the
> **routability-driven placer's own working area**, and it is die-dependent rather
> than a property of the netlist — **6.333 / 7.279 / 8.741 mm²** across the same
> three dies whose `DPL-0007` is flat at **5.675 / 5.684 / 5.634**. The placer
> inflates instances to relieve congestion (`GPL-0086 Inflated area: 170180.016
> um^2 (+2.86%)`) and the inflation is discarded before detailed placement. The
> verdict does not move — the sweep table below and the verdict number were always
> the `DPL` figures — but the sentence was arithmetic on the wrong quantity.

And `INITIAL_DPL_LEGALIZE_FAILED` is printed only after SIX escalating attempts —
default displacement, `-max_displacement` 5 / 20 / 100, full-die, then
`-use_diamond_legalizer`, then diamond at full-die. **All six.** That is not a
knob I neglected to turn.

**And it fails NARROWLY, which is worth saying because it bounds the answer.**
The full trace, not just its ends:

```
NegotiationLegalizer did not fully converge. Violations remain: 409   } x5, and
Padding check failed (409).                                           } 0/409 recovered
Detailed placement failed on the following 358 instances
Detailed placement failed on the following 7 instances                 } x3
Padding check failed (7).
detailed placement checks failed during check placement: 14 violation(s)
Detailed placement failed on the following 277 instances
```

So the negotiation phase is genuinely saturated (409, five times, zero recovered),
but the displacement/diamond escalation gets within **7 instances and 14
violations** of legal before oscillating back. And the instances it cannot place
are named: `load_slew62147`, `load_slew62205`, `place105944`, `wire6087` — every
one a **resizer-inserted repair buffer**, not design logic. The design is
marginally over at 3.300 mm, and what is over is the timing repair's own
footprint.

### The sweep — the runner's own script, die substituted and nothing else

`meas/matmul_diesweep/place_{3800,4200}.tcl` are `pnr.tcl` lines **1-143** and
**145-324** verbatim with `-die_area`/`-core_area` substituted. The single
omission is line 144, `write_def floorplan.def`, dropped so the sweep cannot write
into the live project — verified by grep that the only surviving references to it
are `read_verilog` and `read_sdc`. Same post-DFT netlist, same SDC, same
`global_placement -routability_driven -timing_driven -density 0.45`, same six-step
ladder, same marker.

```
die um   core um   IFP-0104   GPL-0019   legalizes?
  3300      3280      0.403    47.163 %  INITIAL_DPL_LEGALIZE_FAILED  (the runner's own run)
  3800      3780      0.303    35.460 %  INITIAL_DPL_LEGALIZE_OK disp=full-die
  4200      4180      0.248    28.981 %  INITIAL_DPL_LEGALIZE_OK disp=full-die
```

And at the point the NegotiationLegalizer gives up, from each run's own
`DPL-0006..0009` / `DPL-0701`:

```
die um   core mm^2   movable mm^2   fixed mm^2   DPL util   stuck cells
  3300      10.677         5.675        0.427      57.1 %      409
  3800      14.202         5.684        0.569      44.0 %      321
  4200      17.375         5.634        0.694      36.4 %      242
```

**The repair footprint is NOT what grows.** Movable instance area is
5.675 / 5.684 / 5.634 mm² across a die that grows 63 % in area — flat. So "timing
repair inflates until it does not fit" is wrong: the repair costs what it costs
(+64 % over synthesis) and then stops. The *fixed* area grows, 0.427 → 0.694 mm²,
because that is tapcells and PDN scaling with the die. **A fourth die has since
extended both readings: 5.656 mm² movable at die 5153, so the flatness is 0.87 %
across a core that grows 145.6 %, and fixed reaches 1.048 mm² — 2.45× — on the same
span (J54).**

**The stuck count is density-sensitive but does not visibly reach zero.**
409 → 321 → 242, monotone with utilisation, roughly 8 cells per point — and still
242 at 36.4 %. Extrapolated linearly that wants utilisation near 6 %, a die around
9 mm, which is not a credible answer for a 3.86 mm² design. So **the negotiation
legalizer alone does not decide this row**; the escalation ladder after it does,
and at 3300 that ladder took 409 down to 7 before oscillating. (Recorded before
the ladder returned, so the trend cannot be read backwards from its answer.)

> **★ CORRECTION — the fourth die measured this and the trend REVERSES (J54).**
> Dismissing the linear extrapolation as "not credible" was a judgement, not a
> measurement, and the judgement was right for the wrong reason. At die 5153
> (utilisation **25.6 %**) the stuck count is **282** — *higher* than the 242 at
> 36.4 %, on a die 51 % larger in area. The sequence is **409 → 321 → 242 → 282**
> and it turns near 36 %. So the extrapolation was not merely implausible, it was
> the wrong SHAPE, and "grow the die until initial placement legalises" is
> measurably not a convergent strategy on this design. The mechanism is in the same
> logs: initial cell count runs 346 888 / 379 342 / 405 619 / **487 266** (+40.5 %)
> because a larger die means longer nets and the resizer buffers them. **This
> strengthens rather than weakens the choice to size from the flow's own
> routing-headroom rule**, which is what §6 does, and it moves no verdict.
>
> **★ THAT MECHANISM IS REFUTED — J71.** `DPL-0393` counts everything in the rows,
> **tapcells included**. Subtract them, from each arm's own `TAP-0005`, and the
> DESIGN's own cell count is **249 591 / 249 797 / 247 441 / 248 524 / 249 329 — flat
> to 0.95 % across a core that grows 173.4 %**. The whole +48.5 % is the tapcell
> lattice tracking the core by construction; **the resizer adds essentially nothing**
> across this span. The reversal is still measured and now has a fifth point (341 at
> die 5434, J69), but the cause named here is gone.

Whichever core C legalizes, the SELF-TAPE-OUT die is `C + 2*(350 + 26)` — the
PDK's own pad-ring depth and `PAD_EDGE_SPACING` on four sides — and that number,
against 2.862 mm, is this row.

### ★ The number, from the flow's OWN sizing rule rather than from a die I chose (J27)

Following `_compute_resized_die` — the runner's own over-density remedy — turned
up the constant that settles this row:

```python
# GAP-E2E-4 FOLLOW-UP — the auto-die geometry target is a ROUTING-HEADROOM
# utilization ... A placement-dense target (0.40) sizes a die so tight that
# detailed route PLATEAUS; the empirically-clean campaign value is ~0.25
_AUTO_DIE_TARGET_UTIL = 0.25
```

**The flow's own campaign already measured that 0.40 is too tight and 0.25 is the
clean value** — and I drove this design at `--util 0.45`, landing at 57.1 / 44.0 /
36.4 %. Every one of my three sweep points is denser than the flow's own target and
the densest is 2.3× it. The 409 → 321 → 242 trend needs no explanation beyond that.

So the die is computed from the flow's constant and the MEASURED area, not from a
number I picked. `self-tapeout die = core + 2*(350 + 26)`:

```
area sized from                                          mm^2  core mm  DIE mm  DIE mm^2  vs pad
synthesis (the flow's own stats.json)                   3.875    3.937   4.689     21.99   1.64x
after DFT insertion (+18.86 %)                          4.305    4.150   4.902     24.03   1.71x
what INITIAL detailed placement is handed (DPL-0007)      5.684    4.768   5.520     30.47   1.93x
what the FINAL legalizer is handed, post-CTS + hold      6.561    5.123   5.875     34.51   2.05x
  ^ SUPERSEDED (J65): that rung is self-referential — its fixed point, not its
    first iterate, is                                     7.296    5.402   6.154     37.87   2.15x

pad-perimeter floor, 111 pads, confirmed by the flow's own placer   2.862 mm = 8.19 mm^2
the 3.300 mm die that FAILED had a 3.270 mm core = a 4.022 mm self-tapeout die
```

**Of these, the last rung is the one to quote for a die you intend to route — but at
its FIXED POINT, 6.154 mm, not the 5.875 mm first iterate this table originally
carried (J65)**, and the
last row is the one the live full-flow run added after this table was first written
(J29 — CTS and hold repair put 7.52 % on top of what initial placement was handed,
and the spare cells the ECO track requires are 0.098 mm² of it). The flow's
`--die-um auto` sizes from the SYNTHESIS area, which would give 4.689 mm; the
quantity **initial** placement has to place is 5.684 mm², measured, and measured
**flat** across a die that grows 63 % in area — **145.6 % once the fourth die is
included, with the flatness holding to 0.87 % (J54)** — so it is a property of this
design and not of the die I gave it. Sizing from either of the smaller numbers is what
already failed. The sweep below gives the other end — the smallest die at which
initial placement is merely LEGAL — and the two bound the row from either side.

### VERDICT — `edge_llm_matmul_accel`

**Tier: UNDETERMINED**, for the same reason as the three rows above and no other —
no finished layout exists, so the general pre-check never ran (§7, and §5 shows
that is true of the smallest design in the set too).

**But the constraint that binds ON THIS PATH is measured, and it is not the pads:**

> its own post-DFT, post-timing-repair core of **5.684 mm²** — measured, and
> measured flat across a die that grows 63 % in area. Two numbers bound it:
>
> * **the FLOOR, measured** — *initial* placement legalises at a 3.770 mm core and
>   refuses at 3.270 mm: a self-tape-out die of **4.522 mm (20.45 mm²) = 1.58×** its
>   2.862 mm pad floor, threshold bracketed between 4.022 and 4.522 mm. Both sweep
>   points stop at `PNR_STAGE: placement`, so this brackets placement and not the flow.
> * **the number to build to, now measured at THREE dies (J37)** — the full flow
>   costs **+7.52 / +7.51 / +7.26 %** more area to place after spare insertion, setup
>   repair, CTS and hold, at dies 3300 / 3800 / 4200, and the post-hold movable area
>   it produces is **flat to 0.98 %** across a core that grows **62.7 %** in area. At
>   the flow's own routing-headroom target `_AUTO_DIE_TARGET_UTIL = 0.25` each arm
>   sizes itself independently to a 5.123 / 5.185 / 5.211 mm core →
>   **5.875 / 5.937 / 5.963 mm = 2.05× / 2.07× / 2.08×** the pad floor.
>
> Both are core-driven; neither is anywhere near the pads. **The two more dies J29
> asked for have now been run** — they close the one-die caveat on the growth figure
> and they agree to 1.5 %. What they do NOT yet give is a full-flow *legalization*
> bracket: all three arms are still inside the `POST_HOLD_LEGALIZE` ladder with no
> verdict, and between the two arms whose counters are comparable that ladder's
> residual is flat with die (2340 vs 2296, −1.9 % for a core 22.3 % larger) where the
> initial one fell 321 → 242 — so the full-flow floor cannot be read off the
> initial-placement bracket, and it is not claimed here.

**The original reason is NOT UPHELD.** "109 bits vs 52 = 2.1×" measured a pad
budget; this design was never pad-limited — the flow's own placer puts a full ring
on it at 2.862 mm (§4) and refuses at 2.787 mm. What actually costs it a bigger
die is 64 % of area that synthesis does not show: DFT insertion and the timing
repair's own footprint. **A number against a number, and neither number is 52.**

### ★ And the sweep has now said where the legalizer turns over

`die 4200` finished, and it **legalizes**:

```
Using old diamond search for 242 remaining illegal cells.
[WARNING DPL-0701] NegotiationLegalizer did not fully converge. Violations remain: 242
[WARNING DPL-0011] Padding check failed (242).            } five times
INITIAL_DPL_LEGALIZE_OK disp=full-die 4200x4200
DIE_SWEEP_DONE 4200
```

The negotiation legalizer still gives up at 242 — as J26's trend predicted, that
phase does not converge at any die measured. What clears it is the ladder's
**full-die displacement** rung, `detailed_placement -max_displacement [4200 4200]`.
At a 3.270 mm core that same rung was tried and did not clear it; at a 4.170 mm
core it does.

**So the row has a measured bracket, not just a computed target:**

**Both sweeps have now finished, and both legalise — and two larger dies have since
been added, so the bracket is FIVE points and the verdict is monotone across all of
them (J61, J73):**

```
core 3.270 mm (die 3300)  INITIAL_DPL_LEGALIZE_FAILED             self-tapeout die 4.022 mm  INSUFFICIENT
core 3.770 mm (die 3800)  INITIAL_DPL_LEGALIZE_OK disp=full-die   self-tapeout die 4.522 mm  SUFFICIENT
core 4.170 mm (die 4200)  INITIAL_DPL_LEGALIZE_OK disp=full-die   self-tapeout die 4.922 mm  SUFFICIENT
core 5.123 mm (die 5153)  INITIAL_DPL_LEGALIZE_OK disp=full-die   self-tapeout die 5.875 mm  SUFFICIENT
core 5.403 mm (die 5434)  INITIAL_DPL_LEGALIZE_OK disp=full-die   self-tapeout die 6.155 mm  SUFFICIENT

recovery at each:  0/409 FAILED | 321/321 | 242/242 | 282/282 | 341/341
                   -> all-or-nothing at five dies, no partial anywhere
rung-5 cost:       5124.72 | 1076.56 | 848.15 | 2878.10 | 3299.09 s
                   -> not monotone in die, nor in the residual recovered (J61, J73)
```

*(Every core width above is `IFP-0101`'s BBox read from the arm's own log, not the
sweep's nominal — the last row was published as 5.404/6.156 for one draft and is
5.403/6.155 measured. And the arithmetic lands somewhere worth noting: arm5 was sized
to put its **core** on the fixed point, and its self-tape-out equivalent comes out at
**6.155 mm — inside the build-to band, which was 6.139–6.165 mm when this was written
and is 6.139–6.171 mm since the fifth arm answered (J76); 0.8 µm off the four-arm
6.154 mm centre and 2.5 µm off the five-arm 6.157 mm one.** That is by construction
rather than a second confirmation, but it does check the core→die geometry to the
micron.)*

**The threshold lies between 4.022 and 4.522 mm**, and the smallest die measured
to work is **4.522 mm = 20.45 mm² = 1.58×** the 2.862 mm pad floor. The flow's own
routing-headroom target puts it at 5.520 mm = 1.93× — larger, and it should be:
legalising is a weaker requirement than routing with headroom, and the flow's own
comment records that a placement-dense target *"sizes a die so tight that detailed
route PLATEAUS"*. (Both sweeps stop at initial placement; the next subsection
measures what the rest of the flow adds and moves 1.93× to 2.145×–2.154× (J65), and
to **2.145×–2.156×** once the fifth arm answered (J76).)
**Both numbers are core-driven and neither is near the pads.**

Note what did NOT change with the die: the negotiation legalizer failed at all
three (409 / 321 / 242), and at 3800 and 4200 alike it was the ladder's **full-die
displacement** rung that cleared it — the same rung that was tried and failed at
3300. So the die is what decides, and the rung that decides it is the same one
throughout.

### ★ And the bracket is an INITIAL-PLACEMENT bracket — the full flow needs more (J29)

The two sweep points that produced it reach `PNR_STAGE: placement` and stop. The
live chip-path run at 3.300 mm did **not** stop — `INITIAL_DPL_LEGALIZE_FAILED` is
printed by `pnr.tcl:324` and nothing exits on it, so that run went on through spare
insertion, setup repair, CTS and hold repair and is now inside the `POST_HOLD_LEGALIZE`
ladder, having written `placed.def` and `post_cts.def`. **That gives the one thing the
sweep could not: how much the thing being placed grows after placement.**

Every row below is OpenROAD's own `DPL-0006..0009` block at the same fixed
10.677 mm² core, and `grep DPL-0007` returns these five distinct values and no
others — the ladder is complete, not sampled. **Read at log line 6459 while the run
is still inside that ladder** (pid 423747, 3 h 43 m elapsed, on the full-die diamond
rung); `meas/matmul_fullflow/markers.log` is a read-only watcher polling it for the
`POST_HOLD_LEGALIZE_*` verdict and anything after, so the reading is pinned rather
than final:

```
stage that produced it                              movable   fixed    total   DPL util
initial DPL, after routability GP + repair_design    5.6748  0.4272   6.1020    57.1 %
after spare insertion begins                         5.7733  0.4272   6.2004    58.1 %
after SPARE_TIEOFF (7858 of 7858 conns, 3833 drv)    5.8069  0.4272   6.2341    58.4 %
after setup repair_timing (1003 up, 153 buf, 46 cl)  5.7617  0.5256   6.2873    58.9 %
after CTS (2657 clk buf, 1408 dummy) + hold (164)    6.0351  0.5256   6.5607    61.4 %
                                                     +6.35%  +23.04%  +7.52%
```

**+7.52 % more area to place, at the same die, costs 5.7× the stuck count**: the
initial ladder saturated at 409 and got within 7 of legal; the post-CTS one is at
2745 / 2346 / 2330 and still climbing its rungs. Two details that are not visible
from the ends — the growth on FIXED area is the **design-for-ECO spare cells**, which
are a flow requirement on this path and not optional, and which cost a bit-identical
**98 437.16 µm² at every die measured** *(the `+23.04 %` in the table is that same
absolute over a base of tapcells + PDN that itself scales with the die, so it reads
17.31 % at 3800 and 14.17 % at 4200 — **the percentage is a property of the die and
only the absolute is a property of the design**, J37)*; and the setup repair pass made
movable area go *down* while inserting 153 buffers and cloning 46 gates, and bought
nothing with it — `RSZ-0062 Unable to repair all setup violations`, 9795 violating
endpoints before and after.

Recomputing the flow's own `_AUTO_DIE_TARGET_UTIL = 0.25` sizing on the measured
post-hold area, `die = core + 2*(350 + 26)`:

```
area sized from                                  mm²   core mm   DIE mm   DIE mm²   vs 2.862 pad floor
initial-DPL movable (what §6 quoted above)     5.684     4.768    5.520     30.47      1.93x
post-CTS+hold movable                          6.035     4.913    5.665     32.10      1.98x
post-CTS+hold movable + fixed (the honest one) 6.561     5.123    5.875     34.51      2.05x
  ^ SUPERSEDED (J65) — that row's area carries a term proportional to the die
    (the tapcell lattice = 4.000 % of the core, five dies; J71 shows it is exactly
     1.120/28.0 and carries no PDN term), so it is a
    first iterate. Its FIXED POINT:                7.296     5.402    6.154     37.87      2.15x
```

**So 4.522 mm is a measured FLOOR, not the answer** — the smallest die at which
*initial placement* legalises. What the table above establishes on its own is a
direction and a magnitude at one die, not a full-flow bracket.

### ★ And the one-die caveat above is now DISCHARGED — three dies agree (J37)

Two more arms have reached the same point, so the paragraph above no longer rests
on a single die. `proj/matmul_d3800` (the full runner at 3800 — my own arm, J35)
and `meas/matmul_fullflow/fullflow_4200` are both past `PNR_STAGE: hold_repair` and
inside the `POST_HOLD_LEGALIZE` ladder. Blocks taken by STAGE and not by position —
the first `DPL-0007` after `PNR_STAGE: placement`, and the values after
`PNR_STAGE: hold_repair`, of which each arm has **exactly one** distinct:

```
 die mm  core mm²  init tot   ph tot  growth  mov init   mov ph  movgrow      fix Δ   ph util
  3.300    10.677    6.1020   6.5607   +7.52%   5.6748   6.0351   +6.35%   98437.16    61.4 %
  3.800    14.202    6.2523   6.7216   +7.51%   5.6835   6.0544   +6.53%   98437.16    47.3 %
  4.200    17.375    6.3289   6.7885   +7.26%   5.6345   5.9956   +6.41%   98437.16    39.1 %
```

**+7.52 / +7.51 / +7.26 %** — the number reproduces at two dies that were not used
to derive it. And post-hold movable area is **flat to 0.98 %** across a core that
grows **62.7 %** in area, exactly as the initial figure is flat to 0.87 %. *That* is
what makes this row core-limited rather than die-limited, and it is now established
at the post-hold stage and not only at initial placement.

Sizing the die from each arm's own post-hold `movable + fixed`, independently:

```
die 3300   6.5607 mm²  ->  core 5.123 mm  ->  DIE 5.875 mm (34.51 mm²)   2.05x
die 3800   6.7216 mm²  ->  core 5.185 mm  ->  DIE 5.937 mm (35.25 mm²)   2.07x
die 4200   6.7885 mm²  ->  core 5.211 mm  ->  DIE 5.963 mm (35.56 mm²)   2.08x
die 5153   7.1823 mm²  ->  core 5.360 mm  ->  DIE 6.112 mm (37.36 mm²)   2.14x   <- OUTSIDE
```

### ★ CORRECTION — that was a probe, not a fixed point (J65)

The three-row version of this block was published with the hedge *"the drift is
entirely the FIXED term … sizing a die from an area containing a die-dependent term
is **mildly self-referential and 1.5 % is the size of that effect**"*. The cause was
right; the bound was measured from three probes that were all clustered far below the
answer. **The fourth arm lands at 6.112 mm, outside the 5.875–5.963 mm range that
hedge produced** — and a range a new measurement steps outside is not a range. The
effect is **4.75 % in edge and 9.7 % in area**, and it does not need bounding because
it is solvable exactly.

Both die-dependent terms are linear in the core area, measured at four dies and not
fitted:

```
  die  core mm2  fix_init  f=fix/core    fix_ph  S=fix_ph-fix_init
 3300    10.677    427173    0.040008    525610           98437.16
 3800    14.202    568754    0.040048    667192           98437.16
 4200    17.375    694465    0.039969    792902           98437.16
 5153    26.227   1048173    0.039966   1146610           98437.16
```

`f` = **4.000 % of the core** — **the `tapcell -distance 14.0` lattice and NOTHING
else: `n_tapcells × 4.3904 µm²` reproduces `DPL-0008` to ±0.00 µm² at all FIVE dies,
and the "plus PDN" this line used to carry adds exactly zero, because PDN straps are
wiring and `DPL-0008` counts COMPONENTS (J71)**. It is also not a fitted constant:
taps at `-distance 14.0` sit 28.0 µm apart and `filltie` is 1.120 µm wide, so
**`f` = 1.120/28.0 = 4.0000 % exactly** — a PDK `SIZE` record over a flow constant,
predicting every arm's tapcell COUNT to **±0.12 %** with no fitted parameter. The
measured 0.206 % spread is the core's partial edge rows. `S` = **98 437.16 µm², identical to
the last digit at all four dies** — **the 3833 FIXED spare cells, counted in the arms'
own `post_cts.def` and priced from the PDK's own LEF to 0.00 µm² (J70)**. *(This line
used to read "the spare/`dont_touch` block", which is 34.2 % too big: the block is
7 666 instances / 132 093.96 µm², and its other half — the 3833 `spare_tielo_*_drv`
tie-low drivers — is `PLACED`, not `FIXED`, so it lands in `M` and not in `S`.)*
It is die-independent because the count it is 2 % of is: `_DEFAULT_SPARE_DENSITY =
0.02` applied to `IFP-0105 = 191 615`, identical at all five arms — **not** to the
post-resize cell count, which grows **+40.5 %** with die (J54). This report already
carried `S` in a column without using it. Together `f·core + S` reproduces every measured fixed area to
**0.11 %**.

With `A` the core area, `M` the flat post-hold movable area and `UTIL = 0.25`:

    A* = (M + f·A* + S) / UTIL      ⇒      A* = 4(M + S) / (1 − 4f)

```
FOUR arms (as published until the fifth answered):
  movable low   core 5386.9 um   DIE 6138.9 um (37.69 mm2)   2.145x
  movable mean  core 5402.2 um   DIE 6154.2 um (37.87 mm2)   2.150x
  movable high  core 5412.9 um   DIE 6164.9 um (38.01 mm2)   2.154x
```

Iterating the rule from the *smallest* probe converges there — 5872.8 → 6110.2 →
6147.2 → 6153.1 → 6154.0 → 6154.2 — which is the arithmetic saying the four figures
above are its first four steps.

> **★ CORRECTED BY THE FIFTH ARM, under a rule registered before it answered (J76).**
> Arm5's post-hold block landed at 14:34 and its movable area is **6 069 060.66 µm²**,
> **above** the 5 995 578.53–6 054 418.68 band the four arms defined — by
> **+14 642 µm², +0.24 %**. `meas/_j67/arm5_verdict.py`, written and run while the
> number did not exist, says of that branch: *"the fixed point moves UP and I correct
> the number in the direction that makes the chip harder."* So, re-solved on five arms
> with every input re-extracted from the raw logs (`meas/_j68/resolve_five.py`,
> `f` mean **0.039991**, `S` **98 437.16** — now identical to the last digit at
> **five** dies):
>
> ```
> FIVE arms:
>   movable low   core 5386.8 um   DIE 6138.8 um (37.685 mm2)   2.145x
>   movable mean  core 5405.5 um   DIE 6157.5 um (37.915 mm2)   2.151x
>   movable high  core 5419.2 um   DIE 6171.2 um (38.084 mm2)   2.156x
> ```
>
> **Build-to: 6.139–6.165 mm → 6.139–6.171 mm, 2.145×–2.154× → 2.145×–2.156×.** The
> top moves +6.3 µm (+0.10 %); the low end does not move.
>
> **But the predicate's stated REASON is not what five points show, and that has to be
> said.** The "above" branch was worded *"movable grows"*. It does not: ordered by
> core, post-hold movable runs **6.0351 → 6.0544 → 5.9956 → 6.0357 → 6.0691 mm²** —
> **not monotone**. The spread across five is **1.22 %** over a core growing 173.4 %,
> against 0.98 % across four. What actually happened is what a band estimated from
> four samples does when a fifth arrives. **Refuting the predicate does not license the
> mechanism the predicate named**, and the number is corrected because the registered
> rule says to, not because movable was shown to grow.
>
> **And the SHARPER of the two registered predictions HELD.** The fixed point also
> predicted the number OpenROAD would PRINT: `fix_ph` = **1 265 902.23** and
> `DPL-0009` = **24.9–25.1 %**, against 61.4 / 47.3 / 39.1 / 27.4 % at the four earlier
> dies. Measured: **1 264 887.41 (−0.080 %)** and **25.1 % — inside the band.** A curve
> fit has no reason to hit a printed number 12.4 points below the nearest arm.

**And the flow contains a SECOND reading, which its own source names.**
`phase3_one_shot_runner.py:12686` (`_auto_die_side_um`, the formula in its own
docstring, computed at `:12700`; called from `_resolve_auto_die_um` at `:13493`)
sizes the auto die as
`side = sqrt(cells × avg_cell / util)`, where `cells × avg_cell` is the **netlist's**
cells — no tapcell, no spare, no PDN, i.e. movable area alone. That gives
**5 649–5 673 µm = 1.97×–1.98×**. OpenROAD's own `DPL-0009 Utilization` is
`(movable+fixed)/core` (verified at all four arms: 7 182 294.88 / 26 226 686.62 =
27.385 % against a printed 27.4 %), and that is what the flow's resize loop
`_compute_resized_die`/`_compute_downsized_die` steers on — giving the fixed point.

**Which of the two this report quotes does not actually change**, and that is worth
being explicit about rather than hiding behind a bracket. §6's ladder above already
enumerates the rungs — synthesis 4.689 mm (1.64×), post-DFT 4.902 mm (1.71×), initial
DPL movable 5.520 mm (1.93×), post-CTS+hold `movable+fixed` 5.875 mm (2.05×) — and
already commits to the LAST one, because it is what the final legalizer is actually
handed. The movable-only reading (5.663 mm, 1.98 %) is simply one more intermediate
rung of that same ladder, sitting between the 1.93× and 2.05× rows; it is not a rival
headline. **The defect is not which rung was chosen — it is that the chosen rung was
evaluated at a probe instead of solved.** So the published figure moves along its own
rung:

```
  build-to die, post-CTS+hold movable+fixed at UTIL 0.25
    was  5.875–5.963 mm  (34.5–35.6 mm²)   2.05x–2.08x   <- first iterates
    was  6.139–6.165 mm  (37.7–38.0 mm²)   2.145x–2.154x <- fixed point on FOUR arms
    is   6.139–6.171 mm  (37.7–38.1 mm²)   2.145x–2.156x <- fixed point on FIVE (J76)
    pad floor 2.862 mm (8.19 mm²)
```

**The verdict does not move**: the row is core-limited under every rung of that
ladder, from 1.64× to 2.15×, and the pad ring refuses this chip under none of them.
**The floor does not move either** — 4.522 mm is a measured initial-placement bracket
with no sizing rule in it. What moves is one published number, by +4.75 % in edge and
+9.7 % in area, in the direction that makes the chip harder rather than easier.

The one extrapolation this makes, stated: the fixed point assumes movable area stays
flat out to a 29.2 mm² core, 11 % beyond the largest core measured. That quantity is
flat and *non-monotone* over the four dies (6.035 / 6.054 / 5.996 / 6.036 mm²), and
the low/high rows price its whole 0.98 % span at **0.42 %** of the answer. If it did
start growing, the fixed point moves UP, so the upper end is the one that would need
revisiting. Script: `meas/_fixedpoint/build_to_fixed_point.py`.

### ★ And the post-hold legalizer does NOT behave like the initial one

*(A first draft of this subsection put `2330 / 2340 / 2296` in one column and called
it flat. They are not the same counter — 2330 is a `DPL-0034`, the other two are
`DPL-0701`s — and chasing that down produced a better result than the table it
replaced. J37.)*

The three arms do not even fail the same WAY at post-hold, and the OpenROAD codes
each one emits say so:

```
post-hold region     DPL-0036    DPL-0011    DPL-0700   what actually happens
                     (dp THREW)  (chk ran)   (negot.)
die 3300                 4           0           0      detailed_placement ABORTS
die 3800                 0           4           5      it COMPLETES, leaves a residual
die 4200                 0           4           5      it COMPLETES, leaves a residual
```

**At 3.300 mm the post-hold `detailed_placement` throws on every rung** —
`check_placement` is never reached and the negotiation legalizer never engages. At
3.800 mm and above it completes and leaves a residual instead. *(The 3300 arm emits
both code sets in its INITIAL region, so this is a property of the post-hold state
and not of that arm's logging.)* So the 3300 point is not commensurable with the
other two, and the numeric comparison is between the two that are:

```
die   INITIAL ladder        POST_HOLD, DPL-0701 residual per rung
3300   409 -> 7 -> FAILED    (none exists — detailed_placement aborts, 4 rungs)
3800   321 -> OK full-die    2352, 2352, 2344, 2340       core 14.202 mm²
4200   242 -> OK full-die    2296, 2296, 2296, 2296       core 17.375 mm² (+22.3 %)
```

**The residual is flat: 2340 vs 2296, −1.9 %, for a core 22.3 % larger.** At initial
placement that same 500 µm of die bought 321 → 242, −25 %. And the escalation rungs
buy nothing — at 4200 the residual is *identical at all four completed rungs*
(the tcl's `detailed_placement` default, then `-max_displacement` 5 / 20 / 100 µm,
which OpenROAD reports as `DPL-0005` diamond spans of ±500 / ±8 / ±35 / ±178 sites
at this library's 0.56 µm site), where at initial placement the full-die rung is
precisely what CLEARED both arms. The fifth rung, full-die, is where all three arms
are now.

What the 3300 arm contributes is qualitative and only that: at that die the
post-hold placer **aborts** rather than returning a residual, and at 3800 it does
not — a threshold between 3300 and 3800 at the post-hold stage, in the same
direction as the initial-placement bracket.

**So the two ladders are limited by different things, and the initial-placement
bracket cannot be extrapolated to the full flow in either direction.** This is the
measurement that justifies sizing the build-to die from the flow's own
`_AUTO_DIE_TARGET_UTIL = 0.25` routing-headroom rule rather than by walking the
legalization bracket upward — a choice §6 made before the measurement existed.

### What is still open, stated as open

**No arm has printed `POST_HOLD_LEGALIZE_OK` or `_FAILED`.** All three are on a rung
as of **06:02**, and alive rather than assumed alive — sampled 20 s apart, each of
the three `openroad` pids gained exactly 20 s of CPU (`pid 423747` 35736 -> 35756,
`1933325` 17650 -> 17670, `2004621` 15800 -> 15820): one full core each, computing,
not hung. *(Host loadavg rose 6.1 -> 30.5 over those eight minutes on work that is
not mine, so my three are now competing. Nothing published here is affected —
`DPL` areas and pass/fail counts do not move with load — but any TIMING read on this
host from here needs the load quoted beside it.)* The ladder has four more rungs after full-die — `clkswap`,
`clkswap-full-die`, `diamond`, `diamond-full-die` (`pnr.tcl:8309-8364`) — so "stuck
at 2296" is **not** a verdict and is not reported as one.

**★ And on a later dispatch that item has a PREDICATE registered against it, written
while it was still unanswered (J79).** Five arms now, still 0 of 5 answered, still 0 of
5 past rung 5, and the wait re-priced against each arm's own initial rung 5 at
**0.8×–45.9×**. `meas/_j79/posthold_verdict_predicate.py`, registered **15:40:37**
(`NOT YET`, exit 2), predicts: **P1** no arm prints `POST_HOLD_LEGALIZE_OK
disp=full-die`; **P2** if any arm prints OK, its token is `clkswap` or later; **P3**
(weakest, and marked so) the clkswap rung's residual falls strictly below the
**2296–2418** band. The reason is the falsifiable part and it is measured, not guessed:
**rungs 1–4 grow the displacement bound 5 → 20 → 100 sites, a 20× growth, and the
residual moves by at most 12 in ~2350** — 3800 goes `2352 → 2352 → 2344 → 2340`, the
other three do not move at all — so displacement is nearly worthless while bounded, and
rung 5 is that same search unbounded. *(The registered file's next sentence — "there is
no legal site to displace to, at any radius" — is **REFUTED** by the die-4200 arm's own
rung-5 log: 255 of 2 296 recovered, 11.1 %, phase-2 illegal down to 2 035. The file
keeps the wrong sentence with a pointer, because a predicate rewritten after its subject
starts answering is not a predicate; the correction is J81 and P1/P2/P3 are untouched by
it, being claims about what the rung PRINTS.)* What binds is area, and J53 named whose: the 2 055 root-sized
clock buffers that rung 6 downsizes. **A plain `POST_HOLD_LEGALIZE_FAILED` refutes none
of the three** and is recorded as silent rather than counted as a pass.

**But the CONTROL has now printed one, which bounds what that silence means.**
`sha256` (§5 — not one of my six, used only as the control) reached
`POST_HOLD_LEGALIZE_OK disp=full` at a 2300 µm die, on **the same full-die rung** my
three are sitting on. So the ladder is not a construct that never terminates, and
the arms' silence is a statement about this design rather than about the ladder. The
distance is the point:

```
                    post-hold DPL utilisation    negotiation residual entering the rung
sha256   die 2300         12.1 – 13.1 %                        1
matmul   die 4200             39.1 %                        2296
matmul   die 3800             47.3 %                        2340
matmul   die 3300             61.4 %          (no residual — detailed_placement aborts)
```

**Even my loosest die is 3× the control's post-hold density, and its residual is
~2300× larger.** That is the same conclusion §6 reaches from area, arrived at from
the legalizer instead: this row is core-limited, and by a lot. Two further honesties:
the 3300 arm's post-hold state also inherits an ILLEGAL initial placement — a
*second* reason, independent of the counter difference above, why the residual
comparison rests on 3800 vs 4200 (its AREA figures are unaffected by either — area
is area whether or not cells overlap); and
`meas/matmul_fullflow/fullflow_3800` ended at 04:10 with **`rc=137`** — SIGKILL,
which is what the deliberate stop recorded in J35 produces and also what the
container's own 24 GB cap produces, and no kernel OOM record is readable to this
user to tell them apart. A host-level OOM is ruled out (84–102 GB free throughout),
and the die is covered by `proj/matmul_d3800` on a byte-identical netlist and the
same 14 201 741.03 µm² core, so nothing is lost — but "I stopped it" is a
recollection and `rc=137` is the measurement, and those are not the same claim.

### ★ And that silence is now PRICED rather than waited on (J49)

Re-measured **09:22** on a re-dispatch. All three arms are still on the same
full-die rung and all three are still alive — `getconf CLK_TCK` = 100, and over a
20 s sample each pid gained **+20.04 / +19.94 / +20.05 s** of CPU: one full core
each, computing (host loadavg 66.7 → 70.2 on 32 cores, on work that is not mine).
Each arm's last written line IS its entry into the rung, so the dwell reads straight
off the log:

```
die 3300  "Legalizing using diamond search."            02:36:43   dwell 6 h 45 m
die 3800  "old diamond search for 2340 remaining"       04:40:24   dwell 4 h 42 m
die 4200  "old diamond search for 2296 remaining"       04:52:08   dwell 4 h 30 m
```

**And the control priced the identical rung.** `sha256` at a 2300 µm die left it in
`DPL-0500 Runtime: 1.39s` and printed `POST_HOLD_LEGALIZE_OK disp=full-die`. What
differs is the load handed to it:

```
                  cells placed   stuck entering the rung   diamond span (sites x rows)
sha256  d2300          63 362              1                   ±4107 × ±586
matmul  d4200         418 033          2 296                   ±7500 × ±1071
matmul  d3800         391 980          2 340                   ±6785 × ±969
```

Scaling the control's own runtime by the two things that changed — span area
**3.34×**, stuck cells **2296×** — gives **7 663×**, i.e. `1.39 s × 7663` =
**2 h 57 m** expected at die 4200. That arm is **4 h 30 m** in, already **1.52×** the
estimate. Both simplifications in the estimate push the same way: `1.39 s` is the
control's whole `DPL-0500` call, negotiation included, so it OVERstates the control's
diamond; and linearity in 2 296 contended cells is optimistic. **So 7 663× is a lower
bound on the ratio.**

**The rung is not hung. It is being paid for, and the price is at least three orders
of magnitude above the control's.** That is §6's conclusion reached a third way —
from runtime, after area and after the residual — and it is still not a verdict: four
rungs follow full-die (`clkswap`, `clkswap-full-die`, `diamond`, `diamond-full-die`,
`pnr.tcl:8309-8364`), so even a `_FAILED` needs all five. **I neither stopped them nor
waited for them; the row never depended on either.**

### ★ And the whole row was re-derived from the raw logs, not from this report (J49)

Every published figure for this row, recomputed from the arms' own
`DPL-0006/0007/0008` lines with the pad floor from §0's
`die_edge_min(111) = 2862 µm` and the die built as `core + 2×376`
*(that argument is the PAD count; an earlier draft wrote `die_edge_min(109)`, the
SIGNAL-bit count. Both land on the same 2862 µm because `ceil(109/4)` and
`ceil(111/4)` are both 28 — the published number was never wrong, the argument
named beside it was. J52)*:

```
die   post-hold   initial     growth   util    core @ 0.25   self-tapeout die   / 2862
3300  6 560 682   6 101 991   +7.52 %  61.4 %    5 122.8 um       5 875 um      2.053×
3800  6 721 610   6 252 254   +7.51 %  47.3 %    5 185.2 um       5 937 um      2.074×
4200  6 788 480   6 328 922   +7.26 %  39.1 %    5 210.9 um       5 963 um      2.083×
5153  7 182 295   6 704 567   +7.13 %  27.4 %    5 360.0 um       6 112 um      2.136×   <- J64
```

*(The fourth row is this dispatch's, and it is the one that broke the "self-tapeout
die" column: the column is monotone in the probe because the area it sizes from
contains a term proportional to the die. Solved instead of probed, it converges to
**6 154 µm / 2.150×** — J65. The `+7.5 %` growth column, by contrast, extends cleanly:
+7.52 / +7.51 / +7.26 / +7.13 %.)*

All of it reproduces to the digit published — and so do the derived figures: movable
flat to **0.98 %** across a core that grows **62.7 %** *(and still 0.98 % at four dies
across **145.6 %** — the fourth point landed inside the band without widening it,
J64)*, residual **−1.9 %** against initial **−25 %**, floor **4.522 mm = 20.45 mm² =
1.580×** the pad floor. Both
constants the sizing rests on were re-read from the tree rather than quoted from
memory: `_AUTO_DIE_TARGET_UTIL = 0.25` (`phase3_one_shot_runner.py:12604`) and
`_DEFAULT_DIE_MAX_UM = 2000` (`:11828`). **Nothing changed. The point of doing it is
that it could have.**

**None of this moves the verdict.** The row is core-limited and not pad-limited
under every number measured, at four dies rather than one. The number to quote for
a die intended to go all the way through is the flow's own sizing rule on the
post-hold area, solved for self-consistency: **6.139–6.171 mm = 37.7–38.1 mm² =
2.145×–2.156×** the 2.862 mm pad floor *(J65 — the 5.875–5.963 mm this paragraph
originally published is that same rule's first iterates, not its fixed point; and J76
— the 6.139–6.165 / 2.145×–2.154× it then carried was the fixed point on FOUR arms,
moved up by the fifth under a rule registered before that arm answered)*.
**The row moves from 1.93× to 2.15× and stays core-driven; nothing here
is within an order of magnitude of a pad budget.**

### ★ And the residual now has a CAUSE, measured — it is CTS + hold repair, not density (J51)

The subsection above records that the post-hold residual is flat with die (2340 vs
2296) where the initial one is density-elastic (321 → 242), and leaves the
difference as an observation. Read across the CTS boundary, the two arms' own logs
answer it. Same run, same netlist, the reading immediately BEFORE `PNR_STAGE: cts`
against the reading after hold repair:

```
die 4200            cells      movable um^2    DPL util   DPL-0701 residual
before CTS        413 871      5 718 078.91      37.5 %          253
after CTS+hold    418 033      5 995 578.53      39.1 %         2296
                  +1.01 %          +4.85 %      +1.6 pts        x9.08

die 3800
before CTS        387 692      5 780 628.94      45.4 %          312
after CTS+hold    391 980      6 054 418.68      47.3 %         2352
                  +1.11 %          +4.74 %      +1.9 pts        x7.54
```

**A 1 % increase in cell count and a sub-5 % increase in area multiplied the
illegal-cell count by 7.5–9.1×.** The same runs measure density elasticity in the
opposite direction and an order of magnitude weaker: at initial placement **+22.3 %
of core bought −25 % of residual** (321 → 242). Two dies agree, independently.

So the post-hold residual is **not a density effect and cannot be read as one.** It
is a property of WHERE clock-tree synthesis and hold repair put their cells, not of
how much area they add. That is the missing half of the paragraph above: the initial
ladder and the post-hold ladder are limited by different things because they are
handed different KINDS of illegality — one a packing problem, one a placement-state
one.

### ★ A FOURTH die, and the prediction this section wrote down before it (J64)

The paragraph above was argued from two dies. The fourth arm reached
`PNR_STAGE: hold_repair` at **11:48:22** and answered it. Every column below is read
straight out of each arm's own `DPL-0006/7/8/9` lines at the post-hold stage:

```
 die   core mm2  movable mm2  fixed mm2  fix/core   util   entering  settled  mov-only util
3300     10.677        6.035      0.526     4.92%   61.4%      --       --        56.52%   (throws DPL-0036)
3800     14.202        6.054      0.667     4.70%   47.3%     3139     2352       42.63%
4200     17.375        5.996      0.793     4.56%   39.1%     2707     2296       34.51%
5153     26.227        6.036      1.147     4.37%   27.4%     2815     2418       23.01%
```

* **The prediction HELD.** It said "near **2 300**, not near **0**, at roughly
  **25 %**". Measured: **2 418 at 27.4 %** — the count +5.1 % off, the utilisation
  +2.4 points off, and the alternative it was posed against refuted by the whole
  2 418.
* **The residual is flat across a 1.73× utilisation span.** Over the three dies that
  return a residual at all, density falls 47.3 % → 27.4 % and the count moves
  2 352 → 2 296 → 2 418 — a **5.18 %** spread about a mean of 2 355, and not monotone.
* **Post-hold movable area is flat to 0.98 % at four dies**, and the fourth point did
  not widen the band by a digit: 6 035 684.84 µm² lands *inside* the 3800/4200 pair
  that already defined it. The core it is flat across now grows **+145.6 %**, against
  +62.7 % for the three-die version of this claim above.
* **Recovery is 0 at every rung that reaches one** — 0/2 418 twice at 5153, 0/2 352
  and 0/2 296 at 3800 and 4200. The diamond phase is not making slow progress on
  these cells; it is making none.
* **And the small-window rungs are measured no-ops.** At 5153, rung 2
  (`-max_displacement 5`, ±8×1 sites) took **5.85 s** and rung 3
  (`-max_displacement 20`, ±35×5) took **10.54 s**, and the residual was the same
  2 418 before and after both. Rung 5 — the whole-die search — is the only expensive
  rung on this ladder, which is the ladder's own explanation for why the three older
  arms have been sitting on it for 7–9 h.

One check the fourth die makes possible: 5153 was sized so its core would sit at the
flow's own `_AUTO_DIE_TARGET_UTIL = 0.25`, and it measures **23.01 %** counting
movable cells alone and **27.4 %** counting the tapcell/well fixed area the flow
inserts. **The target lands between the two measured numbers** — the closest a
single-number rule can come on a die whose own fixed overhead is 4.4 % of its core.
That is the 5875 µm build-to figure checked against the rule that produced it.

*(This subsection also corrected a sentence in this report's own header — J64. It had
said the build-to die was "confirmed to legalize by running it"; that is true of
INITIAL placement and this section's bracket says so in context, but the bare
sentence read as the whole flow, and at post-hold the same die does not legalize on
rungs 1–4.)*

Stated carefully, because it cuts both ways: **the post-hold residual is therefore
not evidence about die size.** All three arms sitting inside it does not argue this
design needs a die above the flow's own sizing rule — and it does not argue it needs
less. It argues the residual is answering a different question from the one this row
asks. The row's numbers are areas and a pad perimeter, and none of them comes from
the legalizer.

*(One number in an early draft of this paragraph was wrong and the check caught it:
I first read the boundary as `CTS-0018 Created 2 clock buffers` + `RSZ-0032 Inserted
184 hold buffers` = 186 cells, because `CTS-0018` is printed once PER CLOCK NET and
I read the first of two. The second is `Created 3171 clock buffers`, and the cell
counter settles it without arithmetic: 413 871 → 418 033. The conclusion did not
change; the number I would have published was 22× too small.)*

### ★ And the rung is now priced against the arm's OWN previous rung, not the control (J51)

J49 priced the full-die dwell by scaling the CONTROL's `1.39 s` across a different
design. These arms price it against themselves, and better — **each arm's INITIAL
ladder ran the identical full-die rung, and it TERMINATED**:

```
                initial full-die rung   stuck entering it   verdict
die 4200   ±7500 × ±1071    848.15 s           242          INITIAL_DPL_LEGALIZE_OK
die 3800   ±6785 ×  ±969   1076.56 s           321          INITIAL_DPL_LEGALIZE_OK
```

On THIS design, at THESE dies, the full-die rung is a rung that finishes — in 14.1
and 17.9 minutes. What changed at post-hold is the load handed to it, and the four
smaller rungs give that cost ratio directly, at identical window sizes:

```
window (sites × rows)     die 4200: initial -> post-hold    die 3800
  ±8    ×  ±1                  4.07 s ->     4.86 s  ×1.19    ×1.24
  ±35   ×  ±5                  4.46 s ->    13.22 s  ×2.96    ×5.81
  ±178  × ±25                  6.86 s ->    36.86 s  ×5.37    ×6.12
  ±500  × ±100                44.48 s ->   436.28 s  ×9.81    ×5.62
  full-die                   848.15 s ->  ≥ 5 h 24 m  ≥22.9×   ≥18.7×
```

At 4200 that ratio grows monotonically with window size — 1.19, 2.96, 5.37, 9.81 —
so scaling the arm's own 848.15 s by the largest COMPLETED ratio gives **2 h 19 m**,
and the arm is at **5 h 24 m**: **2.34×** the estimate. At 3800 the ratios do not
grow monotonically (1.24, 5.81, 6.12, 5.62), the same construction gives **1 h 41 m**,
and that arm is at **5 h 36 m**: **3.33×**. **Both estimates are exceeded, in the
same direction** — which is what J49 predicted when it called its own 7 663× a LOWER
bound, and it is now confirmed without borrowing a second design to say it.

### ★ And that comparison tightens to a CONTROLLED one — same die, same window, only the stuck count moved (J55)

The table above still varies two things at once (window size and stuck count). One
row of it does not, and it is the strongest measurement in this section. **An arm's
INITIAL full-die rung and its POST-HOLD full-die rung run at the identical window on
the identical die.** Between them the cell count moves +3.06 % and the stuck count
moves 9.49×. Nothing else changes.

```
die 4200   window 8 032 500 site-rows, both rungs
  initial full-die     242 stuck, 405 619 cells      848.15 s   -> converged
  post-hold full-die 2 296 stuck, 418 033 cells   >= 20 708 s   -> running (10:37)
                     stuck x9.4876, runtime >=24.4x  =>  exponent >= 1.420

die 3800   window 6 574 665 site-rows, both rungs
  initial full-die     321 stuck, 379 342 cells     1076.56 s   -> converged
  post-hold full-die 2 340 stuck, 391 980 cells   >= 21 413 s   -> running (10:37)
                     stuck x7.2897, runtime >=19.9x  =>  exponent >= 1.505
```

**Two independent arms put the cost of this rung at better than the 1.4th power of
the stuck-cell count, at a fixed window.** That is why the initial ladder's full-die
rung is a 14-minute step and the post-hold one is a multi-hour step, on the same die,
in the same run. **Both figures are LOWER bounds that RISE while the arms run** — an
hour from now they read higher, and the fact that they are still rising is itself the
statement that neither arm has converged.

> **★ And a third rung says do NOT read that exponent as a law (J57).** The die-3300
> arm's INITIAL full-die rung is in the same design's logs and it breaks any simple
> power law in (window, stuck):
>
> ```
> die   window        stuck   runtime      outcome
> 3300   4 955 172     409    5 124.72 s   INITIAL_DPL_LEGALIZE_FAILED
> 3800   6 574 665     321    1 076.56 s   INITIAL_DPL_LEGALIZE_OK
> 4200   8 032 500     242      848.15 s   INITIAL_DPL_LEGALIZE_OK
> ```
>
> **The 3300 rung has the SMALLEST window and the LONGEST runtime, by 6.0×.** Fitting
> `runtime ∝ stuck^b × window^a` to these three returns **b = −7.7**, i.e. no fit:
> the model is wrong across dies. What the exponents above are — and all they are —
> is a **same-die, same-window, only-the-stuck-count-moved** reading, which is exactly
> the pair they were computed from and is why they were computed that way. They price
> two specific rungs; they are not a law, and the third rung is here so nobody reads
> them as one. The variable the cross-die numbers actually track is free space
> (57.1 / 44.0 / 36.4 % utilisation), not window size and not stuck count.

*(The control agrees rather than being needed: `sha256`'s full-die rung ran a
2 406 702-site-row window over **1** stuck cell in `DPL-0500 Runtime: 1.39s` and
printed `POST_HOLD_LEGALIZE_OK disp=full-die 2300x2300`, verified from its log for
this section. Its window is only 3.34× smaller than die 4200's; the 1 vs 2 296 is
what the distance is made of.)*

One further reading from the same table, and it is the one that says the rung is
doing real work rather than spinning: at the ±178 window the post-hold negotiator
ran to completion in **36.86 s** and printed `diamond recovery: recovered 0/2296
stuck cells` — **twice**, once in each negotiation phase — before `DPL-0701` returned
the residual unchanged. The full-die rung is that same algorithm with the window
widened from 4 450 to 8 032 500 site-rows, **1 805×**, over the same 2 296 cells.
**A widened window is exactly the thing that cleared both arms at initial
placement**, so the outcome is genuinely not known in advance, and it is not
guessed here.

### ★ A FOURTH die is now running, at the number this report publishes (J51)

Everything above is a hypothesis with a consequence, so it is under test rather than
argued. `meas/matmul_fullflow/fullflow_5153.tcl` is built by the same
`build_fullflow.py` from the runner's own `pnr.tcl`, and `diff` against
`fullflow_4200.tcl` is **exactly three lines** — the header comment, the
`-die_area`/`-core_area` pair, and the done marker. Started **10:13:12** in its own
fresh container, `docker run … --skip` first and never `docker exec`, so it cannot
disturb the three live arms.

Die **5153 µm** is not a number I picked: it is chosen so the CORE is **5123 µm** —
the core the flow's own `_AUTO_DIE_TARGET_UTIL = 0.25` rule names for this design's
measured post-hold area, i.e. the core behind the **5875 µm** build-to figure this
report publishes (5123 + 2×376). It already reports `GPL-0019 Utilization:
19.200 %`, against 47.163 / 35.460 / 28.981 % at 3300 / 3800 / 4200.

**The prediction, written down before the answer exists** (a second, narrower one for
its *initial* rung is timestamped in J58 with the host load beside it, because load
rose 14 → 60 while it ran and a wall-clock test needs that said before the answer,
not after). If the post-hold residual
is created by CTS and hold repair rather than by density, this arm reaches post-hold
with a residual near **2 300**, not near **0**, at roughly **25 %** post-hold
utilisation — a fourth point across a span of 61.4 % → 25 %. If it instead collapses
toward zero, the two subsections above are wrong and the residual is density-driven
after all. **Either answer is publishable, and neither moves this row's verdict**,
which rests on measured area against a measured pad perimeter and takes nothing from
the legalizer.

### ★ And the residual's cause has a NAME and a cell count — 2 055 root-sized clock buffers (J53)

J51 gets the boundary right and stops one level too early. What CTS put across that
boundary is in the DEFs the runner arms wrote, and it is specific.
`clock_tree_synthesis` is invoked by the flow's own `pnr.tcl:8294` as

```tcl
clock_tree_synthesis -buf_list {gf180mcu_fd_sc_mcu7t5v0__clkbuf_4} \
                     -root_buf  gf180mcu_fd_sc_mcu7t5v0__clkbuf_16
```

Counting the clock-buffer masters instantiated in `placed.def` (before CTS) and
`post_cts.def` (after), read-only, on the two arms that write them:

```
                              clkbuf_16   clkbuf_4   others   (clkbuf_16 = the ROOT master)
edge_llm_matmul_accel d3800
  placed.def   (line 446)              2          0        0
  post_cts.def (line 8297)         2 055        707       49
edge_llm_matmul_accel d3300
  post_cts.def                     2 055      1 002       54
sha256 (the CONTROL)
  post_cts.def                          1        390        0
```

**The two DEFs are not adjacent and the attribution has to survive that.**
`placed.def` is written at `pnr.tcl:446` and `post_cts.def` at `:8297`; between them
sit the spare-cell block (**3 834 `place_inst` calls** — 958 `inv_1`, 767 `nand2_2`,
575 `nor2_2`, 575 `mux2_2`, 383 `dffq_2`, 383 `aoi21_2`, 192 `oai21_2`, 1 `tiel`,
**and no clock buffer of any kind**) and setup `repair_timing`, whose own log lines
show it inserting `buf_1`-class cells. So the `clkbuf_4` column above is CTS's plus
setup repair's and is NOT purely CTS's — which is why it moves with the die (707 vs
1 002) while the `clkbuf_16` column does not.

**The `clkbuf_16` column is attributable to CTS and only CTS, and that is checkable
rather than argued:** `grep -n clkbuf_16 pnr.tcl` returns **exactly one line in
8 500** — CTS's `-root_buf`. No other step in the flow is ever given that master.

**CTS instantiated the ROOT buffer master 2 055 times — the identical count at two
different dies — where the control, under the same invocation, instantiated it
once.** `clkbuf_16` is **28.000 µm** wide against `clkbuf_4`'s **7.840 µm**, both
3.920 µm tall (read from the PDK's own
`gf180mcu_fd_sc_mcu7t5v0.lef`): **3.57× the width**, 109.760 µm² each.

So the CTS+hold area increase J51 measured is not diffuse. It has a name:

```
2 053 clkbuf_16 that CTS added      225 337.28 um^2
CTS+hold movable increase @ d3800   273 789.74 um^2   ->  clkbuf_16 is 82.3 % of it
CTS+hold movable increase @ d4200   277 499.62 um^2   ->  clkbuf_16 is 81.2 % of it
```

**Four fifths of everything CTS and hold repair added to this design is one master,
instantiated 2 053 times, and the count does not move with the die.**

### ★ Which means the arms are NOT out of options — the flow's next rung is aimed exactly here

I expected the `clkswap` rung (rung 6 of the post-hold ladder, `pnr.tcl:8325-8352`)
to be toothless on this design, because CTS was already told to build from the
SMALLEST buffer — `-buf_list {clkbuf_4}`. **That expectation was wrong, and the DEF
says so.** The rung's own predicate is

```tcl
if {[string match {*__clkbuf_*} [$_rm_ph getName]] && [$_rm_ph getWidth] > $_rtw_ph} {
    $_rin_ph swapMaster $_rtgt_ph; incr _rn_ph      ;# _rtgt_ph = clkbuf_4
}
```

— every clock buffer WIDER than `clkbuf_4`, downsized to `clkbuf_4`. On this design
that predicate matches **2 089 instances at die 3800** (2 055 `clkbuf_16` +
31 `clkbuf_8` + 3 `clkbuf_12`; **2 097 at die 3300**, where the two small columns read
38 and 4 — the `clkbuf_16` column is the same 2 055 at both) and frees

```
2 055 x (28.000 - 7.840) x 3.920  =  162 400.90 um^2
   31 x (14.560 - 7.840) x 3.920  =       816.61
    3 x (21.280 - 7.840) x 3.920  =       158.05
                                     -----------
                                      163 375.56 um^2  =  59.7 % of the d3800 increase
```

**So the flow already contains the counter-move to the thing J51 measured, it is two
rungs ahead of where all three arms are sitting, and it is worth ~60 % of the area
CTS added.** That is not a prediction that they will clear — `swapMaster` frees width
but does not re-place anything, and `check_placement` must come back clean, which
means **zero** violations, not few. It is the reason the three arms' silence must not
be read as "out of moves". They are on rung 5 of 9.

*(How the OK verdict is decided, read from the same block rather than assumed:
`POST_HOLD_LEGALIZE_OK` is set only when `check_placement` does not throw. The
control reached it at the full-die rung, having entered that rung with a residual of
**1**. So the bar is zero, and 2 296 is not "nearly there".)*

**What I did NOT do, and will not:** change the `-root_buf` argument, downsize
anything by hand, or re-run CTS with a different buffer list to get a smaller number.
Whether TritonCTS should build 2 055 root-sized buffers for a 14 625-sink net is a
question about the tool and about this flow's invocation of it, and it belongs to the
flow owner. It is recorded here because it is measured, and because it is
chip-AGNOSTIC — the same invocation is in every `pnr.tcl` this flow writes — not
because this job acted on it.

### ★ The fourth arm's INITIAL ladder has already answered two things (J54)

`fullflow_5153` is still hours from post-hold, but its initial-placement ladder is
done and it settles two claims this report makes elsewhere — one by confirming it at
a fourth point, one by REFUTING a piece of reasoning the report used.

**Confirmed, and now across a 2.46× core range instead of 1.63×.** The quantity
initial detailed placement has to place is a property of the design and not of the
die I hand it:

```
die um   core um^2      movable um^2   fixed um^2   DPL util   initial residual
 3300    10 677 204.74   5 674 818.11    427 172.75   57.1 %        409
 3800    14 201 741.03   5 683 500.12    568 754.37   44.0 %        321
 4200    17 375 223.13   5 634 457.16    694 464.69   36.4 %        242
 5153    26 226 686.62   5 656 393.79  1 048 172.88   25.6 %        282
```

**Movable area is flat to 0.87 % across a core that grows 145.6 %.** Fixed area is
what tracks the die (tapcells and PDN), 2.45× across the same span — exactly as §6
said and now at four points.

The utilisation column is its own small result: die 5153 was chosen so the core would
be the one the flow's `_AUTO_DIE_TARGET_UTIL = 0.25` rule names, and the run lands at
**25.6 %**. The sizing rule's arithmetic is confirmed against a real floorplan, not
just against a spreadsheet.

**Refuted — and it is a piece of this report's own reasoning.** §6 records the
initial residual falling 409 → 321 → 242 with utilisation, dismisses the linear
extrapolation ("wants utilisation near 6 %, a die around 9 mm") as *"not a credible
answer for a 3.86 mm² design"*, and moves on. That dismissal was a judgement, not a
measurement. The fourth point measures it:

```
utilisation   57.1 %   44.0 %   36.4 %   25.6 %
residual        409      321      242      282     <- turns
```

**The trend reverses.** The residual bottoms somewhere near 36 % and is HIGHER at
25.6 % than at 36.4 %, on a die 51 % larger in area. So "keep growing the die until
initial placement legalizes" is not a strategy this design rewards, and the linear
extrapolation was not merely implausible — it was the wrong shape. The mechanism is
visible in the same logs: cell count at initial placement runs **346 888 / 379 342 /
405 619 / 487 266**, up **40.5 %** across the span, because a larger die means longer
nets and the resizer buffers them; the movable AREA stays flat because those extra
cells are small and the resizer downsizes elsewhere to pay for them.

**★ BOTH HALVES OF THAT SENTENCE ARE REFUTED (J71), and the second half was invented
to reconcile a tension that does not exist.** `DPL-0393` counts the tapcells too. Net
of them the design's own cell count is **flat to 0.95 % across a core that grows
173.4 %** — 249 591 / 249 797 / 247 441 / 248 524 / 249 329 at five dies. So there are
no "extra cells", nothing is being "downsized elsewhere to pay for them", and the
movable area is flat for the plain reason that **it is the same population**. The
+48.5 % is the `-distance 14.0` tapcell lattice tracking the core area, 97 297 →
265 682 taps against a core that grows +173.4 %. Count flatness and area flatness now
explain each other instead of needing a story to bridge them.

**None of this moves the row.** The verdict rests on movable area against a pad
perimeter, and the movable area is the column that did not move. What it changes is
the confidence in one sentence of §6's reasoning, which is now measured instead of
asserted — and it makes the case for sizing from the flow's own routing-headroom
rule STRONGER, because walking the legalization bracket upward is now measurably not
a thing that converges.

*(The post-hold prediction recorded above is unaffected and still open: this arm has
not reached CTS. Its initial residual of 282 is a DIFFERENT counter from the 2 296
the prediction is about — the J37 mistake, not repeated.)*

### ★ CORRECTION (J60) — the floor chain added the pad ring to a COORDINATE, not to a width

The bracket above labels each sweep point with `build_fullflow.py`'s
`core_hi = die - 20`, which is the core rectangle's **upper X coordinate**. The core
runs from `10` to `die - 20`, so its **width** is `die - 30`. Adding the pad ring to
the coordinate counts the low-edge margin twice, and every die in the floor chain was
**10.1 µm too large**. Read from each arm's own `IFP-0101 Core BBox` line
(`meas/_corebbox/core_width_vs_coord.py`), with `BBox width × height` reproducing each
log's own `DPL-0006 Core area` to the cent at all four dies:

```
  die  core_hi  BBox width  BBox height      area um^2 |   die@hi  die@width   delta
 3300     3280    3269.840     3265.360    10677204.74 |     4032    4021.84   10.16
 3800     3780    3769.920     3767.120    14201741.03 |     4532    4521.92   10.08
 4200     4180    4169.760     4166.960    17375223.13 |     4932    4921.76   10.24
 5153     5133    5122.880     5119.520    26226686.62 |     5885    5874.88   10.12
```

**The build-to chain never had this defect** — it sizes from measured AREA via
`sqrt(area / 0.25)`, which is a width by construction. So this report was carrying two
conventions for one quantity, each internally consistent, and the table above is the
first place they stood in the same column. The last row is the cross-check that
settles which is right: at die 5153, `core_hi + 752 = 5885` but
`width + 752 = 5874.88 → 5875`, and **5875 µm is the build-to die §6 has published
since J27**.

`376` is not affected and was checked rather than assumed: `probe_padring/fp.tcl`
*specifies* `-core_area {376 376 1924 1924}`, so 376 is an input — §1's **350 µm ring
depth + 26 µm `PAD_EDGE_SPACING`** — and the `376.320` in its output is that input
snapped to the 0.56 µm site grid, i.e. a sliver of unusable core rather than a deeper
ring.

```
floor die         4.532 mm  ->  4.522 mm      (-10.08 um, -0.22 %)
floor area        20.54 mm² ->  20.45 mm²     (-0.44 %)
floor / pad floor 1.583x    ->  1.580x        ("1.58x" as published: UNCHANGED)
floor in slots    1.02      ->  1.02          UNCHANGED
build-to trio     5.875 / 5.937 / 5.963 mm    UNCHANGED by J60
                  -> 6.139 - 6.165 mm          SUPERSEDED LATER by J65 (a different
                     defect: those three are the sizing rule's first iterates, not
                     its fixed point. J60 was a units bug in the FLOOR chain and did
                     not touch this one; both statements are true of their own sha)
tier, binding constraint                      UNCHANGED
```

Corrected in place throughout this report, 15 replacements each asserted to match
exactly once before any write; the pre-correction copy is kept at
`meas/_corebbox/RESULT.md.pre_j60`.

**The blast radius was then bounded by testing it, not by assuming it (J63).** Every
other die in this report comes from `meas/selftape_die_floor.py`, whose two die
functions are `FIXED + PAD_W*ceil(N/4)` and `sqrt(area/util) + 2*(RING_D + EDGE)` —
**neither takes a rectangle**, so a coordinate cannot stand in for a width there. The
coordinate entered through the sweep's `-core_area "10 10 core_hi core_hi"`, which
exists in exactly one place: this row's bracket. Re-run today, the script reproduces
§1's table cell-for-cell, including the two figures the report brackets as superseded
and the control. The sixth row, `u_hawaii_adc`'s 2052 µm, is not a script output — §2
builds it from the design's own datasheet line *"Die (core, no seal ring) —
1300 × 1300 µm"*, an explicit W × H, and it is confirmed by running the placer at it
in three states. The same re-run also **closes the last assumption J60 was carrying**:
it prints `ring_depth=350.0 um` and `edge_spacing=26.0 um` after reading them from the
`bi_t` master's LEF and the PDK's `config.tcl`, so `2*(350+26) = 752` is a PDK
measurement in both chains. **No verdict and no ratio moves at the precision
published.** It is worth recording anyway, because it is the failure mode this report
keeps naming in other people's numbers — a quantity *adjacent* to the one being
claimed, carried forward because it was the one in the variable. J49's re-derivation
did not catch it, and could not have: it re-derived the numbers the report
**published**, and the substitution happens one step earlier, in the label of the
input.

### ★ And the fourth arm has ANSWERED — the prediction's direction held, its numbers did not (J61)

`INITIAL_DPL_LEGALIZE_OK disp=full-die 5153x5153` at **11:17:47**, `DPL-0500 Runtime:
2878.10s`, `diamond recovery: recovered 282/282 stuck cells`. The rung began 10:29:49
and `10:29:49 + 2878.10 s = 11:17:47` — the runtime counter and the wall clock agree
without either being fitted to the other.

```
J58's linear estimate      1 487.6 s      actual / predicted = 1.935x   REFUTED
J58 with J55's exponent    1 586.3 s      actual / predicted = 1.814x   REFUTED
J58's DIRECTIONAL claim — "should complete, in tens of minutes rather than
  the 85 minutes the 57 %-dense 3300 arm took"  -> 47.97 min            HELD
```

**Both point estimates are refuted and the hedge is what survived.** J58 named the
tension correctly and could not call it: more free space pushes the runtime down, a
larger window pushes it up, and **the window won**. The full initial ladder at all
four dies, from the arms' own logs (`meas/_corebbox/initial_rung_runtimes.py`):

```
die   util    full-die window     span       stuck  recovered   runtime    verdict
3300  57.1%   +/-5892 x 841     4 955 172     409       0      5 124.72s  FAILED
3800  44.0%   +/-6785 x 969     6 574 665     321     321      1 076.56s  OK
4200  36.4%   +/-7500 x1071     8 032 500     242     242        848.15s  OK
5153  25.6%   +/-9201 x1314    12 090 114     282     282      2 878.10s  OK
```

* **Runtime is not monotone in die, span or stuck count** — 4200 is the cheapest of
  the four while sitting between 3800 and 5153 on every input. `t ∝ stuck × span`
  fitted to each successful rung gives a **1.93× spread** in the constant, so it is
  good to a factor of two and no better. This does not reach J49's pricing of the
  *post-hold* silence, which stands on a 10³ gap.
* **Recovery is all-or-nothing** — 0/409 where it fails, 100 % at all three dies where
  it passes. That is a better reason for calling the floor a bracket than the
  two-point argument originally given for it.
* **Failing costs more than succeeding** — the 3300 rung spent 5 124.72 s to recover
  nothing. A long silence on this ladder is not evidence of being close to an answer.

**And the bracket gains a fourth point, monotone in verdict where its residual is
not** (J54: 409 → 321 → 242 → 282):

```
core 3.270 mm (die 3300)  FAILED   self-tapeout die 4.022 mm  INSUFFICIENT
core 3.770 mm (die 3800)  OK       self-tapeout die 4.522 mm  SUFFICIENT   <- the FLOOR
core 4.170 mm (die 4200)  OK       self-tapeout die 4.922 mm  SUFFICIENT
core 5.123 mm (die 5153)  OK       self-tapeout die 5.875 mm  SUFFICIENT
```

The last row is **the die this report published as the build-to when that probe was
launched, and its INITIAL placement is now confirmed to legalize by running it rather
than by sizing it.** Two later corrections apply to it and neither touches this
bracket: the build-to figure itself has since moved to **6.139–6.165 mm** (J65 — the
old one was the sizing rule's first iterate) and then to **6.139–6.171 mm** (J76 — the
fifth arm landed above the four-arm band), and at the POST-HOLD stage this same die
does *not* legalize on rungs 1–4 (J64). The floor is still 4.522 mm — the smallest die
measured to work — and the tier, the verdict and the binding constraint are
unchanged.

### ★ The fixed point re-derived by a SECOND script, and a FIFTH arm at its own core (J67)

`meas/_j67/extract_dpl.py` re-extracts all four arms' DPL blocks from the raw
OpenROAD logs — blocks taken by `PNR_STAGE` marker, never by line position, with an
assert that each arm's post-hold triple is unique — and re-solves the fixed point
without reading a number out of this report. **It reproduces every published figure
to the digit it publishes:**

```
  die  core mm2     mov_ph      fix_ph   f=fix_i/core   S=fix_ph-fix_i   util_ph
 3300    10.6772  6035072.38   525609.91    0.040008        98437.16      61.4 %
 3800    14.2017  6054418.68   667191.53    0.040048        98437.16      47.3 %
 4200    17.3752  5995578.53   792901.85    0.039969        98437.16      39.1 %
 5153    26.2267  6035684.84  1146610.04    0.039966        98437.16      27.4 %

f  mean 0.039998, spread 0.206 % across cores differing by 145.6 %
S  spread 0.0000 um^2 — identical at all four
f*core + S reproduces every measured fixed area to 0.108 %
A* = (M+S)/(UTIL - f):  6138.9 / 6154.2 / 6164.9 um   =  2.145x / 2.150x / 2.154x
probe form iterated from the smallest arm: 5872.8 -> 6110.2 -> 6147.2 -> 6153.1
                                           -> 6154.0 -> 6154.2
```

The two inputs that are NOT measured here are the flow's, and both were read out of
its source: `_AUTO_DIE_TARGET_UTIL = 0.25` (`phase3_one_shot_runner.py:12604`, pinned
by `tests/test_auto_die_avg_cell_source_is_disclosed.py:71`) *(the line number this
line carried until J68 — 12021 in the same runner file — is a comment about
`catch`/`_NONFATAL:` markers and has nothing to do with the constant — the report cited the SAME constant at two
different lines and only one of them resolved)*, and the 376 µm ring
depth + offset of §0.

**And the one extrapolation J65 stated is now being MEASURED rather than assumed.**
J65 wrote down that the fixed point *"assumes movable area stays flat out to a
29.2 mm² core, 11 % beyond the largest core measured"*, and that if it did start
growing the answer moves UP. That is a testable sentence, so a **fifth arm** is
running at the die that lands the core on the fixed point's own core area:

```
  target A* (movable mean)          29 183 726 um2
  sweep die 5434 -> Core BBox       29 188 086.054 um2   (+0.015 %)
  same netlist as all four:  IFP-0105 191 615 instances, IFP-0103 4 305 072.576 um2
  started 12:56:14, loadavg 112.88 at launch, 85 GB free
```

The die is **5434** and not 6154 because a sweep arm is a BARE die — `core_hi =
die − 20` in `build_fullflow.py`, so its core is `die − 30` with no pad ring — while
the published build-to die is the core PLUS the 2×376 µm ring. Sizing 5434 from the
target core used a floorplan model (site 0.56 µm, row 3.92 µm, LL snapped to
10.08/11.76) that reproduces the die-3300 and die-5153 `IFP-0102` areas to **0.000
µm²** before it was used to pick anything. `fullflow_5434.tcl` differs from
`fullflow_5153.tcl` in **one line** — the `-die_area`/`-core_area` pair — at 8 372
lines each.

**Stated in advance, as J51's fourth-arm prediction was.** If post-hold movable area
at a 29.19 mm² core lands inside the 5.996–6.054 mm² band the four arms define, the
extrapolation is discharged by measurement and the build-to figure stands at
6.139–6.165 mm. If it lands **above** that band, the fixed point moves **UP** and I
correct the number in the direction that makes the chip harder. Either way **the
verdict does not move**: this row is core-limited at every rung of §6's ladder, and
the pad floor of 2.862 mm is in front of it at none of them.

> **★ ANSWERED 14:34, and it is a SPLIT verdict (J76).** Arm5's post-hold movable is
> **6 069 060.66 µm² — ABOVE the band, by +14 642 µm² (+0.24 %)**, so this prediction
> is **REFUTED** on the branch that costs me the number, and the build-to figure moves
> to **6.139–6.171 mm = 2.145×–2.156×** exactly as registered. The **second, sharper**
> prediction below **HELD**: `DPL-0009` printed **25.1 %**, inside the registered
> 24.9–25.1 %, with predicted `fix_ph` off by **−0.080 %**. And the verdict did not
> move, as both branches said it would not. *(The "above" branch was worded "movable
> grows". Five points are **not monotone** in core — 6.0351 / 6.0544 / 5.9956 / 6.0357
> / 6.0691 mm² — so the number moves because the registered rule says so, not because
> that mechanism was shown. See §6.)*

**And a SECOND, sharper prediction is registered with it.** The fixed point does not
only claim movable area is flat — it claims a number OpenROAD will PRINT. Arm5's core
is already on its log (`IFP-0102` = 29 188 086.054 µm²), so with the two constants
measured at four dies the post-hold block is predicted before it exists:

```
  predicted fix_ph  = f*core + S = 1 265 902.23 um2
  predicted DPL-0009 post-hold utilisation  =  24.9 .. 25.1 %
  what the four earlier dies printed        =  61.4 / 47.3 / 39.1 / 27.4 %
```

Landing inside 24.9–25.1 % tests the **whole solve** — both terms and the utilisation
target together — not just the flatness of one of them. A fixed point that is merely
a curve fit has no reason to hit a printed number 12.4 points below the nearest arm.

The predicate is not prose — it is `meas/_j67/arm5_verdict.py`, written and **run
while the arm was still in global placement**, where it printed `NOT YET — arm5 has
not reached its post-hold DPL block` and exited 2. So the rule that judges the
answer provably predates the answer, and the script's own ability to read the log was
established before there was anything in it to read.

---

## 7. ★ The wall the four UNDETERMINED rows actually hit — and it is OURS

I drove the self-tape-out pad-ring chain end to end rather than reasoning about
it (J10 has every command and every quote). After §8's capture the ring places on
a probe DEF (§4). On a REAL design it does not, and the step says why:

```
$ pad_ring_gen probe_padring                                ->  rc 1
PAD_INSTANCE_NOT_IN_BLOCK: 77 ordered pad instance(s) are not COMPONENTS of
phase3/stage3/pnr/floorplan.def ... this step does not create them
```

`pad_ring_gen` documents this about itself: *"The variables in `REQUIRED_VARS` are
upstream's, they name INSTANCES that must already exist in the netlist, and
NOTHING UPSTREAM OF THIS STEP IN THIS FLOW PRODUCES ANY OF THEM."* The flow's
synthesis emits a bare core; no step instantiates the PDK's IO cells and wires
them between the pads and that core.

**That is the constraint that actually binds on this path today. It is
chip-AGNOSTIC, it is a FLOW gap and not a design one, and it — not any property
of the four designs — is why their tier is UNDETERMINED rather than PASS.**

**★ And that wall was re-verified on TODAY'S main, not on the sha this section was
written against (J67).** Main has moved 214 commits since, and J66 established that
one of them closed `PAD_SITE_NOT_FOUND` — the gap this report filed — so the next
gap could plausibly have gone with it. It has not. On `origin/main` = `ae78abb28`
(v1.11.69), extracted with `git archive` and read directly, `PAD_INSTANCE_NOT_IN_BLOCK`
is still a live refusal in `pad_ring_gen.py:730` — **on MAIN's copy, which is 823
lines; my own worktree's is 662 and has no line 730 at all, so that coordinate is
only half an address until the tree is named (J68)** — and the step says the gap in
its own words rather than mine:

```
{n} ordered pad instance(s) are not COMPONENTS of <floorplan DEF>: [...] — the
side variables name instances the netlist must already carry, and THIS STEP DOES
NOT CREATE THEM
```

A grep of main's whole `programs/` tree for a step that instantiates IO cells into
the netlist finds none. **So the four UNDETERMINED rows are UNDETERMINED for the same
reason on today's main as on the sha measured earlier**, and the tier is not an
artefact of having looked at a stale tree.

### ★ FIRST — the brief's own named pre-check, run on all six (J39)

The brief names `general_precheck.py` as *"the pre-check that applies"* and requires
a verdict to say which pre-check and attach what it printed. **§7 used to rest on
J11, which quotes `general_precheck` on `proj/sha256` — the CONTROL, not one of my
six.** Every claim here that the six do not reach it was an INFERENCE from a
correctly-quoted command that answered about the wrong subject. Run on each of them
separately:

```
chip                     verdict         layouts required evidence undet decl_present excluded
u_hawaii_adc             NOT_DETERMINED        0       11        0    11        False        2
edge_llm_accel           NOT_DETERMINED        0       11        0    11        False        2
caravel_user_project     NOT_DETERMINED        0       11        0    11        False        2
opentitan_aes            NOT_DETERMINED        0       11        0    11        False        2
ibex                     NOT_DETERMINED        0       11        0    11        False        2
edge_llm_matmul_accel    NOT_DETERMINED        0       11        0    11        False        2
```

All six `rc 1`, and **each one's `reason` names its OWN project path**, so these are
six distinct runs rather than one result restated. Verbatim, identical in shape for
every chip — this is the "exactly what was missing" the UNDETERMINED tier requires,
in the program's own words rather than mine:

```
no finished layout found under the project (searched 4 layout location(s) below
<project>); nothing was examined, so nothing was determined
```

`edge_llm_matmul_accel` is the only one of the six I drove through the chip path, so
it was asked twice — and a tree six PnR stages deeper (synthesis, DFT, floorplan,
placement, CTS, hold) returns **the same verdict**, `layouts_found=0`,
`declaration_answered=0/18`, `emitted_by: general_precheck v1.11.68`. *(Confirmed I
did not disturb the live run in that directory: `find -printf '%f %s'` before and
after is identical.)*

**This moves no verdict. It moves the four UNDETERMINED rows from INFERRED to
MEASURED** — the brief's own pre-check now answers NOT_DETERMINED about each chip,
naming the missing input itself.

And it confirms this section from the other side. The two `operator_specific_excluded`
steps are the same two for every chip — `KLayout.CheckPadMask` and
`KLayout.GenerateID` — and the program's stated reason is this path's principle in
its own words: *"a mask of our own invention would be a rule we wrote pretending to
be theirs."* So the general pre-check is not the shuttle pre-check with checks
deleted; it declines exactly the two that belong to an absent operator and still
requires 11.

### ★ And the gap is NARROWER than the paragraph above makes it sound (re-measured 06:1x)

Re-run end to end on a COPY of `probe_padring` (re-running writes, and §8b records
me destroying the artefact I was verifying by not copying first):

```
step A  pad_assignment_gen  ->  rc 0, wrote pad_assignment.json (4717 bytes)
step B  pad_ring_gen        ->  PAD_INSTANCE_NOT_IN_BLOCK: 77 ordered pad
                                instance(s) are not COMPONENTS of floorplan.def
```

**The pin-out CHOICE is already made by a program that exits 0.** So the missing
piece is not the decision `_pad_ring` refuses to make on principle — *"a value this
program invented would be a pin-out nobody chose"* — that decision now has a writer
and it succeeds. What is missing is only **INSTANCE CREATION**: nothing puts the 77
cells the assignment already names into the netlist as COMPONENTS and wires them
between the pads and the core.

That distinction matters for whoever picks this up, because it changes what the work
IS. Inventing a pin-out would be the exact thing this brief forbids and the exact
thing `_pad_ring` refuses. **Instantiating the cells an existing, exit-0 assignment
already names is mechanical and forbidden by nothing.**

**★ AND THE MISSING INPUT IS NOW COUNTED, not described (J89).** *"Mechanical and
forbidden by nothing"* assumed the pieces such a step needs exist. Measured:
**0 of 77** signal pads carry a cell TYPE (the assignment fixes the pin-out and the
corner/filler masters only — so the step has two halves, not one); **every** master it
names is **PRESENT** in the PDK, whose IO library ships **15** masters covering input
(`in_c`/`in_s`), bidirectional (`bi_t`, three drives), analog and supply — **with no
output-only pad, so outputs must use a `bi_t` with its enable tied**, which is measured
rather than assumed; and **77 of 77** pad signals have a **declared** direction, the
port-bit count matching the pad count exactly (**44 in / 33 out**). So the missing input
is *a mapping from 77 declared directions onto 15 masters, plus the instantiation of 77
instances an exit-0 assignment already names* — **nothing invented, nothing absent.**
That is the strongest form this tier can take: not "we could not tell", but the missing
input counted with evidence that each of its inputs already exists.

**★ AND THE FLOOR EVERY ROW IS QUOTED AGAINST DOES NOT DEPEND ON THAT MISSING CHOICE
(J90).** `padring_die_floor.py` used ONE pad width, 75.0 µm, so the published floors could
have been conditional on the cell-type mapping J89 found missing. Measured from the PDK's
own LEFs: **every signal-carrying IO master is exactly 75.000 × 350.000 µm** — `in_c`,
`in_s`, `bi_t`, `bi_24t`, `asig_5p0`, `dvdd`, `dvss`, all identical; the variation is
entirely in fillers and breakers. **So no choice that step could make moves any published
pad floor by one micron**, and every direction each design needs is covered
(330/164/8, 384/131/0, 156/106/0, 73/36/0, 29/2/0 in/out/inout). **Two decisions are open
in this report and a verdict now measurably moves with neither**: J88 for the ladder
(core-limited at both ends, 2.145×–2.156× and 2.128×–2.139×) and J90 for the cell type.
*A verdict that moves with a decision nobody has taken is not a verdict* — that property
was asserted nowhere and is now measured on both.

**I did not build it, and that is deliberate.** It is a new flow step, not a bug
fix, and `pad_assignment_gen`'s own docstring states the rule for exactly this
situation: *"wiring it into the runner would change what a real run blocks on, which
is the flow owner's call and is recorded, not taken here."* Same reasoning, same
answer — recorded, not taken. It is also outside what this brief asked for, which
was to re-adjudicate six verdicts, and **UNDETERMINED with the missing input named
is one of the three verdicts the brief defines**, not a gap in the adjudication.

*(One method note: the shell above ends `rc=0` and that rc belongs to `grep`, not to
`pad_ring_gen` — the `wrapper-must-state-its-own-verdict` trap, hit twice in this
session. The verdict here is the refusal TEXT, which is what is quoted.)*

### ★ And a THIRD gap, which is the same boundary error in our own code (J28)

`--die-um` defaults to **`auto`**. What `auto` computes, with no chip-path branch
anywhere in the function:

```python
pin_side  = _pin_perimeter_die_side_um(pin_bits, _pin_pitch)   # n * pitch * 0.5
cell_side = _auto_die_side_um(cells, util_frac, avg_cell)      # sqrt(n*a/u)
side      = max(cell_side, pin_side)          # both max(60, min(side, 2000))
```

Its IO model is **DEF pins at the ROUTING pitch** — 0.56 µm on this PDK — not pads
at the pad pitch. A pad is **75.000 µm**, i.e. **134× wider than the pin this model
budgets for**:

```
design                    pads   pin-perimeter side   PAD-ring floor
caravel_user_project       645              181 um          12912 um     71x under
opentitan_aes              517              145 um          10512 um     72x under
ibex                       264               74 um           5712 um     77x under
edge_llm_accel             122               35 um           3087 um     88x under
edge_llm_matmul_accel      111               32 um           2862 um     89x under
u_hawaii_adc                24                7 um           1212 um    173x under
```

That model is not wrong — it is exactly right for the IP/macro path, where a "pin"
IS a wire end on a block boundary. **It is the wrong model for a DIE**, where every
signal needs a 75 µm pad CELL. Which makes it §4's error in our own code: the three
original verdicts counted a macro's ports against a die's pad budget; the flow's own
die sizer sizes a die as though it were a macro. Same confused boundary, opposite
direction.

And even pad-aware it would not reach: `die_edge_min(N)` crosses the
`_DEFAULT_DIE_MAX_UM = 2000` clamp at **65 pads** (64 → 1962 µm fits, 65 → 2037 does
not). **Five of my six exceed it**; only `u_hawaii_adc` does not. The upsize-retry
loop hits the same constant and returns *"resized die would exceed 2000x2000um cap
... INCREASE `--die-um` MANUALLY"*, and `grep add_argument.*die` finds exactly one
flag — no CLI option raises the cap.

**This is not a refusal of any design and I have not made it one.** The manual
override works: my own runs at 3300 / 3800 / 4200 µm all ran past the cap, which is
the remedy the program itself names. It is a third chip-AGNOSTIC gap on this path,
and it is the reason a DEFAULT `--die-um auto` invocation cannot self-tape-out any
real chip.

### ★ The cap re-verified BY EXECUTION — and two things reading it had missed (J67)

J28 above established the `_DEFAULT_DIE_MAX_UM = 2000` clamp by READING the source
and grepping for a flag. `meas/_j67/die_cap_probe.py` re-establishes it by **calling
the flow's own functions**, and the first control I wrote was wrong in a way worth
recording: I priced a die of 1900 µm as the positive control, and it returned `None`
too — because 1900 × the upsize factor 1.556 is *already* over the cap. A negative
whose control also fails proves nothing. With controls chosen so the GROWN die is
still under the cap, the refusals are the cap:

```
remedy      die 1000        1500        1900     2862     4522     6154
upsize    (1556,1556)      None        None     None     None     None
loosen    (1179,1179) (1768,1768)      None     None     None     None
downsize   (448,448)   (671,671)   (850,850) (1280..) (2023..) (2753,2753)
```

**First thing reading it missed: the LOOSEN ladder dies at the cap too.** J28 named
the upsize-retry loop. `_compute_loosened_die` is a *different* remedy — the flow's
congestion self-rescue, the one that matters for a design sized at 25 % utilisation
rather than one that overflowed — and it hits the same constant. Above 2000 µm the
flow has no way to grow a die for congestion either.

**Second: the cap is ASYMMETRIC.** Both remedies that GROW a die check the new
dimension against `die_max_um` and refuse; `_compute_downsized_die` has no such check
and still fires at every die above the cap. So above 2000 µm the flow's die machinery
can still make a die smaller and can never make one bigger. *(What that would do to a
real run is NOT established here: downsize triggers on UNDER-utilisation, and at its
build-to die this design sits at the target, so I drove the probe with a synthetic
5 % to reach the function at all. The asymmetry is the finding; a ratchet is not.)*

**And the ladder's rungs are worth pricing, because they all point the same way.**
`_loosen_ladder_util` continues past the authored `(0.25, 0.18, 0.12)` geometrically
at that list's own final ratio, up to `_ROUTE_LOOSEN_MAX_RUNGS = 6`. Walking it from
this report's build-to die with the flow's own `_compute_loosened_die` (cap lifted, to
show the shape — at the real cap every rung refuses with `die_cap_reached`):

```
rung 0  util 0.2500 -> 0.1800   die  7253 um   52.6 mm2
rung 1        0.1800 -> 0.1200        8884 um   78.9 mm2
rung 2        0.1200 -> 0.0800       10881 um  118.4 mm2
rung 3        0.0800 -> 0.0533       13327 um  177.6 mm2
rung 4        0.0533 -> 0.0356       16323 um  266.4 mm2
rung 5        0.0356 -> 0.0237       19992 um  399.7 mm2
```

**Every rung of the flow's own congestion self-rescue makes the die BIGGER.** So
6.154 mm is not a midpoint — it is the *tightest* die the flow's own machinery would
ever hand this design, and the pad floor of 2.862 mm is in front of it at none of the
six rungs. That is §6's verdict reached a fourth way. **What is NOT claimed: that this
design would descend the ladder at all.** No arm has reached global route, so nothing
here measures its routability; these are the dies the flow's own function computes
when asked, not a prediction that it will be asked.

The clamp itself, driven with the design's own floorplan numbers
(`IFP-0105` 191 615 instances, `IFP-0103` 4 305 072.576 µm², avg 22.467 µm²):

```
util 0.25  unclamped 4150 um -> _auto_die_side_um returns 2000  (2.08x)
util 0.18  unclamped 4891 um ->                        2000  (2.45x)
util 0.12  unclamped 5990 um ->                        2000  (3.00x)
```

and against what each design needs on this path — **every one of the five digital
designs is above the cap**, 2.26× to 6.46×, so a default `--die-um auto` cannot size
any of them.

**Which tree this is measured on, because that is a question the number can fail.**
The first run imported the file from the primary checkout — which is sitting on a
FEATURE branch (`fix/1464…` @ `886bb4a14`, dated 08-14), not on main, so on its own
it establishes nothing about what the flow ships. The four constants are byte-identical
at `a00f53f20` (the v1.11.66 main this branch was cut from), at both my branches, at
`886bb4a14`, **and at `origin/main` = `ae78abb28` (v1.11.69, landed today)** — and the
whole probe was then RE-RUN against main's own tree, extracted with `git archive
origin/main` so every sibling import is main's too. Every line above reproduces
identically there. The finding is about what main ships, not about a branch in flight. `u_hawaii_adc` at 1212 µm is the only one of the six that fits, and it
is refused by the PDK for a reason no die size touches (§2).

### What I did NOT run, said plainly — and the pre-check would not have stopped me (J24)

For `caravel_user_project`, `opentitan_aes` and `ibex` I ran synthesis and the
pad-ring geometry and stopped. **I did not run PnR on them, and that was a
choice, not a failure.** Their cores are 0.0055 / 0.847 / 0.373 mm² and would
place and route on their pad-set dies without difficulty.

And here is the part that makes the choice matter. The eleven ladder steps
`general_precheck` requires are:

```
 1 KLayout.ReadLayout    2 General.DatabaseUnit   3 KLayout.CheckTopLevel
 4 KLayout.CheckSize     5 General.SealRing       6 General.ForbiddenLayers
 7 Checker.KLayoutDensity  8 Checker.KLayoutZeroAreaPolygons
 9 Checker.KLayoutAntenna 10 Checker.MagicDRC    11 Checker.KLayoutDRC

operator_specific_excluded:  KLayout.CheckPadMask, KLayout.GenerateID
```

**Not one of the eleven looks for a pad ring.** The only pad-aware step is
`CheckPadMask`, and on this route it is excluded by construction — the pad mask
belongs to an operator this path does not have.

So I could have streamed three padless GDSs, run the general pre-check the brief
names, and written **PASS** in three rows with a pre-check report attached to
each — for dies that cannot be bonded or probed. That is exactly the *"pass
obtained that way is worth LESS than the failure it replaces"* case, and worse
than usual because the pre-check would have CO-SIGNED it. What stops a padless
die shipping is step 15.5ic, a FLOW requirement on the chip path. The rows stay
UNDETERMINED and the missing thing is named instead.

(`General.SealRing` IS step 5, so the two rings sit on opposite sides of that
line: the seal ring the pre-check checks, the pad ring only the flow does. The
shuttle arm has the matching evidence — an operator container refused a layout
this flow published at ladder step 3 of 16 for a missing seal ring.)

`general_precheck` says the same thing in its own voice, re-run for this report
(J21) and kept as `meas/general_precheck_before.json` so the control's AFTER is a
comparison rather than a single reading:
```
rc 1
NOT_DETERMINED: general_precheck (no operator) — layouts_found=0,
ladder_steps_required=11, steps_with_evidence=0, undetermined=11,
declaration_answered=15/18 — no finished layout found ...; nothing was examined,
so nothing was determined
```

`operator_specific_excluded` in the same report names the two steps this route
cannot run and why — `KLayout.CheckPadMask` (*"a mask of our own invention would
be a rule we wrote pretending to be theirs"*) and `KLayout.GenerateID`.

Both chip-path runs disclose `--allow-pdk-target-mismatch`, and the two strings
are not the same one: `proj/sha256` declares `pdk_target: 'sky130'` and
`proj/edge_llm_matmul_accel` declares `'sky130A'`. (An earlier draft said both
were `sky130A`.) A resolved PDK the design does not declare is a disclosure, not
a detail, either way.

---

## 8. What this job put back into the plugin

### ★ A THIRD finding, authored, verified and PUSHED (J85)

`next/placeability-bound-is-printed-and-never-consulted` @ **`4d1de0e2c`**, one commit
on `origin/main` = `ae78abb28`. **No version bump, nothing on main, nothing on a frozen
batch branch.**

**`PLACEABLE_WIDTH_BOUND` is measured, printed, and never consulted.** The width cap
measures the longest contiguous free-site run from the live tap grid and prints it; a
`git grep` for that marker finds it in the emitter and in its own tests and **nowhere
else**. `clk_buf_root` meanwhile is a PDK-registry value — or, when the registry is
silent, *"the LAST clkbuf in the Liberty"*, i.e. **the widest one** — fixed before any
floorplan exists. **Nothing joins the two.** All three designs printed
`PLACEABLE_WIDTH_BOUND: 56000 dbu = 50 site(s)` and all three named a **50-site** master
as `-root_buf`; the small one used it once and legalized, the large one used it 2 055
times and is the residual of §6.

**And the off-by-one I went hunting is REFUTED by the tree itself.** The cap's predicate
is `width > bound`, so a master exactly at the bound survives by exact equality — which
reads like a `>` that should be `>=`. It is not:
`test_a_master_exactly_at_the_bound_stays_legal` pins the strict form and its docstring
names the slip in advance — on the floorplan it was measured against, the **surviving**
masters sat exactly there, so `>=` would empty the pool. Recorded because a report that
only lists its successful hunts is not a record.

**What landed is REPORT-ONLY**: two lines that make the condition sayable at floorplan
time instead of discoverable ten hours into a legalizer
(`MASTERS_AT_PLACEABILITY_BOUND`, `CTS_MASTER_AT_PLACEABILITY_BOUND`). **Nothing is newly
excluded, no `-root_buf` is changed, and the strict `>` is untouched** — those are the
decision above, not a patch. Inert unless the caller supplies the names, so every other
caller's Tcl is byte-identical. **Three-state: 27/27 → 4 FAIL mutated → 27/27 restored**,
plus **490 passed / 1 skipped** across all 17 test files touching this emitter.

### ★ A DECISION, written out rather than taken (J84)

**It is not mine to settle, so it is stated with both sides and their measured costs.**

**The situation.** The post-hold ladder has nine rungs. Rung 5 is a full-die
displacement search — non-destructive, and **unbounded in time**. Rung 6 downsizes every
clock buffer wider than the CTS sink buffer — fast and effective, and **destructive**: it
weakens the clock tree the flow just built.

**Both are load-bearing, and that is the whole problem:**

* **Rung 5 saved the control.** `sha256` printed `POST_HOLD_LEGALIZE_OK **disp=full-die**
  2300x2300`. Rungs 1–4 recovered 0/1; rung 5 recovered 1/1. Put rung 6 first and that
  design's clock root gets downsized for nothing.
* **Rung 5 is where the arms are trapped.** Five of them, one to thirteen hours, and the
  one furthest in has bought **255 of 2 296 (11.1 %)** in over ten hours of one core.
  Rung 6, measured in their own post-hold state, takes **2 344 → 303 (−87.1 %) in
  16 min 35 s** (J83).

**Why the two designs differ, measured (J84).** Every structural ratio between them is
1.8×–6.5× — cells 6.2×, utilisation 3.9×, clock buffers 6.5×, tree depth 1.8×. Exactly
two ratios are not: **ROOT-master instances 1 vs 2 055**, and **residual 1 vs 2 344**.
`residual ≈ root_master_count + ~300` at both designs and all four measured dies, and
J83 is the causal half: removing exactly those instances' excess width leaves **303**
against a predicted 2 344 − 2 055 = **289**.

**The options, with what each costs by measurement and not by estimate:**

| option | cost to the control | cost to a matmul-shaped design | new parameter |
|---|---|---|---|
| **A. leave it** | none | unbounded — no verdict in 13 h and counting | none |
| **B. reorder: rung 6 before rung 5** | **1** instance swapped, 79.03 µm² — its clock ROOT weakened | 13 h → 16 min | none |
| **C. skip rung 5 when the residual entering it exceeds N** | none at N > 1 | 13 h → 16 min | **N**, and choosing it is the judgment |
| **D. bound rung 5 by time** | none | 13 h → bound + 16 min | a timeout, which OpenROAD's `detailed_placement` does not expose |

**★ AND A FIFTH OPTION, measured after the four above were written (J86).** A 79-second
probe settles the mechanism the first four were arguing around. `-root_buf` **does not
mean "the root"** — CTS instantiates whatever it names **~2 052 times**, at the root of
every subtree. Three variants on the arm's own `placed.def`, all printing `Created 2363
clock buffers` / `Max level 11`, so the tree is the same shape in each:

| variant | `-buf_list` | `-root_buf` | root-master instances |
|---|---|---|---|
| baseline (the arm's own) | `{clkbuf_4}` | `clkbuf_16` (50 sites) | **2 054** — reproduces the arm's 2 055 to 0.05 % |
| wide buf_list | `{1 2 4 8 12}` | `clkbuf_16` | **2 054 — unchanged, not by one instance** |
| narrow root | `{clkbuf_4}` | `clkbuf_8` (26 sites) | **2 052 × clkbuf_8; only 2 at the bound** |

| **E. name a `-root_buf` that fits the measured bound** | **none measured — skew 4.86 → 4.50 (−7.4 %), max network latency 7.61 → 6.92 (−9.1 %), same 2 363 buffers, same 11 levels** | **the 2 055 never exist; nothing at the bound to legalize** | **none** |

**★ AND OPTION E IS NOW MEASURED END TO END, NOT JUST AT CTS (J88).** Two full
post-hold probes from the same `placed.def`, differing in **one argument** (`diff` = three
lines, two of them comments):

| | `-root_buf clkbuf_16` (today) | `-root_buf clkbuf_8` |
|---|---|---|
| post-hold residual | **2 042** — `recovered 0 of 2 042` — in **13 m 28 s** | **8** in **2 m 35 s** (**5.2×** faster) |
| hold violations found | 2 595 | 1 522 (**−41 %**) |
| hold buffers inserted | 262 | 149 (**−43 %**) |
| post-hold movable | 5 957 992.32 µm² | 5 847 894.26 µm² (**−110 098.06**) |

**The residual five arms have been unable to clear for up to thirteen hours is created
by which master the flow names as `-root_buf`, not by the design.** The area delta lands
1.8 % from what the census predicted before either probe ran. *(The entry control
FAILED — `placed.def` predates spare insertion, so neither probe reproduces the arm's
absolute numbers — and the registration said in advance that the two are then compared
to each other, which is the controlled result. `rootfit` does NOT legalize outright
either: residual 8, `PROBE_PRESWAP_OK=0`, exactly as predicted. **Both probes have since
TERMINATED** — `rootbig` at 13 m 28 s with `recovered 0 of 2 042`, which is the
all-or-nothing shape J73 measured at five dies, with this one on the nothing side. The
sentence that used to read "still searching at 7 min" was a live read and is corrected
where it stood.)*

**This does NOT revise the published die.** 6.139–6.171 mm is what the flow **as it is**
would build and option E is not adopted; *if* it were, the same fixed point gives
**6.090–6.123 mm = 2.128×–2.139×**. That is a published M minus a delta measured on a
different base — a column beside the real number, never substituted for it.

**★ AND THE VERDICT SURVIVES THE DECISION EITHER WAY: 2.145×–2.156× as the flow stands,
2.128×–2.139× under option E — core-limited at both ends, pad-limited at neither.** The
adjudication does not hinge on an unresolved flow question, which is the property that
had to be checked.

**Option E is not merely cheaper than A–D; on this design it is better on every number
measured.** At 2 052 instances the clock net's load is mostly the buffers themselves, so
a 50-site buffer's own input capacitance costs more delay than its extra drive buys.
**It is still one design, one PDK and post-CTS skew rather than post-route**, which is
why it is a row in this table and not a patch.

**What I did NOT do.** Nothing was reordered, no `-root_buf` was changed, no cell was
downsized by hand, and no arm was stopped to make a point. **B costs the control a real
timing change** — one clock root, from 28.000 µm to 7.840 µm — and a legalizer cannot
see what that costs; **C is defensible and its only difficulty is that N is a number
somebody picks**, which is the shape this report refuses elsewhere; **D is the cleanest
and is not reachable from Tcl.** The evidence for all four rows is in `findings.md`
J53/J80/J81/J83/J84 and re-runnable from `meas/_j80` and `meas/_j83`.

**No verdict depends on this.** All six stand as published, and
`edge_llm_matmul_accel` is core-limited at 6.139–6.171 mm whichever rung eventually
answers.

### ★ And the adjudication itself is now published under a name (J82)

`next/six-shuttle-refusals-readjudicated-on-the-self-tapeout-path` @ **`450aba8fe`** —
20 files, +10 869: this report, the journal, the standing controls and the J80 probe
with its registered predictions, off `origin/main` = `ae78abb28`. **Not on main, no
version bump.** Scanned first with the repo's OWN file guard
(`source_chip_agnostic_check.py`): **PASS, 16 files, NDA panel 20 of 20** — and with a
positive control (`--extra-tokens` on a word known to be in the text) returning
**FAIL, 11 occurrences**, so the PASS is a measurement rather than a blind spot. Read
back from the remote by fetching the blob: `ALL SIX DECIDED` at line 3.
**The pushed copy is a SNAPSHOT** and this directory's is canonical; the decay ledger
now compares the two by hash and reports drift, because a stale number with a URL
outranks a current one without.

### ★ A SECOND finding, authored, verified, and PUSHED on this dispatch (J80)

**`fix(phase3): the clkbuf-downsize rung could fail in total silence — its `catch`
guard was inverted`** — `next/clkbuf-downsize-diagnostic-is-inverted` @
**`f99979a73`**, one commit on top of `origin/main` = `ae78abb28` (v1.11.69).
**No version bump, nothing pushed to main, nothing added to a frozen batch branch.**

`_build_escalating_legalize_tcl` emitted the downsize block as
`if {![catch { ...swapMaster... } _rec]} { puts "..._NONFATAL: $_rec" }`. Every other
`![catch ...]` in that emitter guards a body whose SUCCESS is the interesting case; this
one guards a body whose FAILURE is, and the polarity reverses with it. **Found by
EXECUTION, not by reading**: the J80 probe's own output is

```
POST_HOLD_CLKBUF_DOWNSIZE swapped=2089 -> gf180mcu_fd_sc_mcu7t5v0__clkbuf_4
POST_HOLD_CLKBUF_DOWNSIZE_NONFATAL:
```

— a `_NONFATAL:` line with **no message**, straight after the block **succeeded**. In
a plain `tclsh`, both branches: shipped shape prints `NONFATAL: ` on success and
**nothing** on failure; the corrected shape is silent on success and **names** the
failure. So if `findMaster` returns NULL for a PDK whose clock buffer is named
differently, or `swapMaster` refuses, **the flow says nothing and walks into
`detailed_placement` as though 2 089 cells had been downsized** — and on this run that
rung is worth an **87.3 %** drop in the illegal-cell count, so a silent failure there
presents as *"this design will not legalize"*, which is the sentence five arms are
currently sitting inside.

**Verified the way this report verifies things**, not by "the tests pass":

* Two BEHAVIOUR tests added to the file's existing `tclsh` + stubbed-odb harness — one
  asserting silence on the success path, one asserting the failure is NAMED.
* **Three-state**: fixed **8/8 PASS** → reverted to the shipped polarity **2 failed**
  (and the throwing case then emits only `POST_HOLD_LEGALIZE_FAILED`, with no
  diagnostic at all — the silent-failure proof) → restored by reverse edit **8/8 PASS**.
  `__pycache__` cleared before each state.
* **51 of 51** pass across all four test files that touch this emitter.
* **No test pinned either polarity before this**, so nothing would have caught it and
  nothing breaks by fixing it.
* Pushed with `core.hooksPath` pointed at **this branch's own tracked hook**, because
  the shared checkout's `pre-push` symlink is **293 lines against `origin/main`'s 440**
  — a stale hook missing its own abort-reporting trap. Never `--no-verify`.
* **Read back from the remote**: `git ls-remote` returns `f99979a73`, and the blob
  fetched back from that sha carries `if {[catch {` without the `!`.


> **★ SUPERSEDED — read this first (J66).** Everything below is true of the shas it
> names and none of it should be acted on. `origin/main` moved to **`a4caccefe`**
> (v1.11.69) and among the **214** commits it gained is **`741a87cc1`, authored
> 01:34:54 on 2026-08-22, which fixes the same defect by the same mechanism**
> (`PAD_FAKE_SITES` in `libs.tech/<flow>/<io library>/config.tcl`). I did not take the
> two commit subjects sounding alike as proof: I copied **my own patch's test file**
> into a detached worktree at `a4caccefe` and ran it in the pinned image. Round 1: 8
> failed, all on the NAME `discover_io_tool_configs` (main calls it
> `discover_io_site_declarations`). Round 3, with the assertions mapped onto main's
> `resolve_site()`: **9 of 9 passed.** Main additionally carries
> `PAD_SITE_DECLARATION_AMBIGUOUS`, which my patch does not — **a superset, not an
> alternative**. The branches stay on the remote as evidence of the finding; there is
> nothing left in them to land, and I have not rebased, deleted or re-filed anything.
>
> **★ AND THAT LAST SENTENCE HAS SINCE EXPIRED — J74.** Re-queried on this dispatch,
> `git ls-remote --heads origin` returns **67 heads, 0 of them `jself`**. I did not
> delete them; they are gone, and the claim "the branches stay on the remote" was true
> when measured and false by the time anyone read it. Preserved instead as a verified
> bundle + patches under `meas/_j68/bundles/`. Retained above unedited, for the same
> reason the "landable" language is.
> The "landable" language below is retained unedited because it was true when written
> and because rewriting it would hide that this is what a superseded claim looks like
> from the inside.

**TWO branches pushed, and the second one is the landable one (J50).** Both carry
the SAME patch — `git show` of the two diffs is **byte-identical, 0 lines of
difference** — and both are **version-less** (3 files, no `plugin.json`).
**Nothing on `main`. No version bumped.**

```
jself/pad-site-declared-in-pdk-tool-config              7a47263f1  on a00f53f20 (v1.11.66)
                                                                  descends from current main: NO
jself/pad-site-declared-in-pdk-tool-config-on-v1.11.68  f452ea45a  on 81cd5321b (v1.11.68)
                                                                  descends from current main: YES  <- land this one
```

The first is kept, unmoved and un-force-pushed, because **evidence attaches to a sha**:
every measurement in §8 was taken against `7a47263f1` and a force-push would have
unreferenced it. The second was pushed under a NEW name for the same reason.

**Re-verified at the second sha rather than recalled from J38** — same targeted
suite, same image, in the environment the flow actually runs in
(`PDK_ROOT=/foss/pdks`, `PDK=ihp-sg13g2` both SET): **`3 failed, 265 passed in
38.21s`**, the three failures the same three pre-existing ones by name. J38's
number reproduces at the rebased sha on current `main`.

### ★ Re-checked at 04:52 today, and the base has moved under it (J36)

`origin/main` is now `81cd5321b` (**v1.11.68**), **30 commits** ahead of
`a00f53f20`. So `git merge-base --is-ancestor origin/main HEAD` now answers **NO**.
It answered YES when this section was written; the sentence has been REPLACED
rather than left standing to be read as current, because it is exactly the kind of
claim that keeps its authority after it stops being true.

The branch is still landable, and the checks that say so are different ones:

```
git merge-base --is-ancestor a00f53f20 origin/main    YES   (base not rewritten)
git merge-tree --write-tree origin/main 7a47263f1     rc 0  (textually clean)
the 3 files my commit touches, over a00f53f20..origin/main:      0, 0, 0 commits
the 52 files those 30 commits DID touch, grepped on origin/main
   for _pad_ring / IoLibrary / PAD_SITE_NAME:                    0 hits
```

**A clean `merge-tree` on its own proves nothing about semantics**, so the
load-bearing line is the last one: what landed is DISJOINT from what this commit
changes, and there is no caller that could have drifted under it.

### ★ And the re-test that owed is now RUN, on the rebased tree (J38)

§8 used to end here saying the targeted suite had not been re-run on the rebased
tree and that this was the first thing to do if the branch were landed. It has been
run. `git worktree add --detach origin/main` + `git cherry-pick 7a47263f1` applies
**with an identical diff** — no textual adaptation — and the suite, compared BY ID
and never by count:

```
tree                                       PDK vars   result
main 81cd5321b + this commit  (6 files)      SET      3 failed, 265 passed
main 81cd5321b clean          (5 files)      SET      3 failed, 256 passed
main 81cd5321b + this commit  (6 files)     UNSET     267 passed, 1 skipped
main 81cd5321b clean          (5 files)     UNSET     258 passed, 1 skipped
```

**The same three tests fail in every arm that fails at all, by name, with this
commit present and absent.** This commit's contribution is **+9 passed and zero new
failures in both conditions** (265−256 = 9, 267−258 = 9), and the `267 passed, 1
skipped` above **reproduces exactly on the rebased tree at v1.11.68**. The branch is
landable on that evidence rather than on a clean `merge-tree`.

### ★ And chasing those three found a red that is green only OUTSIDE the flow's own environment

Not mine, not this branch, and it changes how the number above must be quoted.

```
PDK=ihp-sg13g2  (image default)    3 failed, 43 passed
PDK=gf180mcuD                      3 failed, 43 passed
PDK=sky130A                        3 failed, 43 passed
env -u PDK_ROOT -u PDK             46 passed
```

**Inside the shipped `vibeic-eda` image `PDK_ROOT=/foss/pdks` and `PDK=ihp-sg13g2`
are always set**, so those three are RED in the environment the flow actually runs
in and GREEN only outside it. Which is also the honest reading of my own earlier
figure: **`267 passed, 1 skipped` was taken in a shell where those two variables
were unset.** It was never wrong and it reproduces to the test — it was
*conditioned on an environment I did not state*. Both readings are published above
with the condition named, because either one alone is the misleading half.

**The WHY, after I got it wrong once (J38).** My first explanation quoted
`resolve_script`'s *"Existence is NOT checked here"* and concluded the path is
returned file-or-no-file so the marker can never be earned. The quote is real; the
causal claim is wrong. Existence **is** checked — at `if not runner.exists(script)`,
one branch later, exactly where that docstring's next sentence says it will be. What
actually decides it is the ORDER of the branches in `run()`:

```
1.  if not script:                    -> marker = not seal_required    (TRUE here)
2.  if gds_path is None or not file:  -> "no streamed GDS to seal"     (marker False)
3.  if runner is None:                -> ...
4.  if not runner.exists(script):     -> marker = not seal_required    (would be TRUE)
```

**Step 2 sits before step 4**, and these fixtures have no streamed GDS — so anything
that gets past step 1 lands on step 2 and the existence check at step 4 is never
reached. The answer turns purely on whether `script` is None, i.e. purely on whether
both variables are set, and **not at all on whether the PDK really ships a
generator.** The experiment that settles it:

```
PDK=ihp-sg13g2      sealring.py EXISTS (3830 bytes)   ->  marker False, "no streamed GDS"
PDK=sky130A         sealring.py ABSENT                ->  marker False, "no streamed GDS"
PDK=no_such_pdk_xyz the DIRECTORY does not exist      ->  marker False, "no streamed GDS"
PDK_ROOT+PDK unset  path never constructed            ->  marker TRUE,  "no generator declared"
```

**A PDK that does not exist behaves identically to one that ships a working
generator.** Not an existence check skipped — an existence check made unreachable.
*(Side facts: `gf180mcuD` ships a KLayout `sealring.py` too, only `sky130A` of the
three does not — which matches the program's own comment; and the unset-branch text
renders as* `"no seal-ring generator is declared for the this PDK PDK"`.*)*

**I did nothing about it.** It is pre-existing on `main` at both `a00f53f20` and
`81cd5321b`, fixing it means touching `die_finishing_gen.py` and landing on `main`,
and the brief forbids that. It is written down for whoever owns it — and I did not
quote only the `env -u` number to keep this section looking clean.

### For `jpadsite` on 8HD-3, who now owns `sha256`

The brief moving `sha256` to its own ledger row says the reason is our own
`PAD_SITE_NOT_FOUND`. **That refusal is what this branch removes**, so it is
probably the first thing that arm wants:

```
branch  jself/pad-site-declared-in-pdk-tool-config   (pushed; 1 commit on a00f53f20)
before  PAD_SITE_NOT_FOUND: PAD_SITE_NAME='GF_IO_Site' is not a SITE in the IO cell
        library this run resolved (0 site(s) from 16 LEF(s); PAD-class: [])
after   io_lib resolved=True  n_sites=2  pad_class_sites=['GF_COR_Site','GF_IO_Site']
        site_source={'GF_COR_Site':'pdk_tool_config','GF_IO_Site':'pdk_tool_config'}
then    PAD_INSTANCE_NOT_IN_BLOCK — the NEXT gap, which this does NOT close (§7)
```

Re-verified on this tree at 02:0x today, not quoted from earlier (J21). Every row
of §4's perimeter table depends on it; without it the question cannot be asked.

`PAD_SITE_NOT_FOUND` is not a one-PDK quirk. Measured on all three open PDKs
in the pinned image: **two of them declare no `SITE` in any IO LEF at all** and
supply it through the PDK's own tool config instead; the third declares it in LEF.
`_pad_ring.IoLibrary` read LEFs and nothing else, so step 15.5ic resolved 1 of 3.

The commit adds `discover_io_tool_configs()` + `parse_tool_config_sites()` and an
`IoLibrary(lefs, tool_configs=())` that consults the PDK's own config **only for a
site the LEF does not declare** — the LEF always wins, and every site carries its
`site_source` so *the PDK drew this* and *the PDK's tool config declared this* can
never be read as the same claim. A PDK declaring the site in neither place still
resolves nothing and the step still refuses.

**All four figures below were RE-RUN for this report, not carried over.** The
earlier record cited `test_tapeout_declaration*.py`, and **no file of that name
exists** — pytest errors on the literal and reports `no tests ran`, so the "132
passed" it was paired with could not have come from that command. The real
targeted set and its real number:

```
RED   separate worktree at unmodified a00f53f20, __pycache__ cleared,
      the new test file copied in and then removed again:      8 failed, 1 passed
      (the 1 that passes asserts the DEFECT, so it passes on both trees)
GREEN this tree, test_pad_ring.py + the new file:             84 passed, 1 skipped
      targeted regression — test_pad_ring, test_pad_ring_site_from_pdk_tool_config,
      test_pad_and_seal_ring_on_the_chip_path, test_general_precheck,
      test_tapeout_precheck_two_arms, test_submission_template_check:
                                                             267 passed, 1 skipped
      NOT the full suite — the brief forbids it.
```

`test_matrix_d3_outputs_produced.py` reports 6 failures. Baselined on unmodified
`origin/main` in a separate worktree, and compared by ID rather than by count:

```
my tree   step15 step17 step19 step20 step30 step32   6 failed, 52 passed, 61 skipped
baseline  step15 step17 step19 step20 step30 step32   6 failed, 52 passed, 61 skipped
```

**The same six, by name.** Pre-existing, not mine. `redwt` was left clean —
`git status --porcelain` empty after the copied test file was removed.

**Every number in §4's perimeter table depends on this capture.** Without it every
row is `PAD_SITE_NOT_FOUND` and the perimeter question cannot be asked at all.

### For whoever owns the flow's CTS invocation — recorded, not acted on (J53)

This job did not go looking for a CTS finding; it fell out of asking what created the
post-hold residual. It is chip-AGNOSTIC — the two flags are in every `pnr.tcl` this
flow writes — so it is left here in the shape someone else can act on.

```
where   pnr.tcl:8294
        clock_tree_synthesis -buf_list {..._clkbuf_4} -root_buf {..._clkbuf_16}

seen    edge_llm_matmul_accel, 14 625-sink clock net:
          post_cts.def carries 2 055 x clkbuf_16   (the ROOT master)
          identical count at die 3300 and die 3800 -> not a die effect
        sha256 (control), 1 839-sink clock net, SAME invocation:
          post_cts.def carries     1 x clkbuf_16

cost    clkbuf_16 = 28.000 x 3.920 um = 109.760 um^2, 3.57x clkbuf_4's width
        2 053 added instances = 225 337 um^2 = 82.3 % of everything CTS + hold
        repair added to movable area at die 3800

attrib  grep -n clkbuf_16 pnr.tcl -> exactly 1 hit in 8 500 lines, the line above.
        No other step is handed that master, so the count is CTS's and only CTS's.
```

**Which makes this a measurement rather than a discovery, and that is the honest
framing.** J53 did not find a hazard nobody knew about; it measured one the flow's
author had already built two recovery rungs for, on a design where it happens to be
large.

**What I am NOT claiming.** That this is a bug. TritonCTS may legitimately want the
root master across the upper levels of an H-tree over 14 625 sinks, and the flow may
legitimately want `clkbuf_16` named as the root. Two facts sit next to each other and
the reading between them belongs to whoever owns the invocation:

* the flow's own post-hold recovery ladder contains a rung (`clkswap`,
  `pnr.tcl:8325-8352`) whose entire job is downsizing clock buffers wider than
  `clkbuf_4` — **so the flow already treats oversized clock buffers as a known
  post-CTS hazard**, and on this design that rung has 2 089 targets worth
  163 376 um^2. **The flow says so structurally, not just by having the rung (J56):
  the INITIAL ladder has 7 rungs and the POST-HOLD one has 9, and the two extra are
  exactly `clkswap` and `clkswap-full-die`** — they appear after CTS and nowhere
  else, because before CTS there are no clock buffers to downsize;
* the same rung existing means nobody has to change the invocation to find out —
  the arms will reach it, and what it recovers is measurable rather than arguable.

**Nothing was changed to test this.** No `-root_buf`, no `-buf_list`, no instance
downsized by hand, no CTS re-run with different arguments. A pass obtained that way
would be worth less than the failure it replaces, and this is not even a failure yet.


---

## 8b. ★ Every quoted command in this report, re-run (J33)

*(Re-checked at 05:54 after this session enlarged the report: still **16**
`$`-prefixed commands, all of them the ones audited below. The material added since
— §6's three-die reproduction, §8's rebase re-test — was measured in this session,
not carried over, and its own numbers are audited in J37/J38. **Re-counted again
after this dispatch added §6's J51–J54 and §8's CTS handoff: still 16.** That
material quotes no new shell command — it is `DPL-`/`CTS-`/`RSZ-` lines lifted from
logs the arms wrote, two DEF histograms, `SIZE` records from the PDK's own LEF, and
`pnr.tcl` line numbers, each cited where it is used and each re-derived in this
session rather than carried over. One further audit,
which is arithmetic rather than a command: **§0's die formula
`762 + 75*ceil(N/4)` reproduces all six quoted dies exactly** — 12912 / 10512 /
5712 / 2862 / 3087 / 1212 µm for 645 / 517 / 264 / 111 / 122 / 24 pads. The single
place a quoted die is one micron above the formula, `caravel_user_project`'s
75-pad reading at 2188, is the site-multiple quantisation and it is MEASURED rather
than rounded: 2187 returns `PAD_CORNER_SPACING_NOT_SITE_MULTIPLE` and 2188 returns
PASS. So no number in either summary table is a number I computed and did not
also run.)*


Two rows turned up defects in evidence I had presented as measured (§2's device
inventory was 7 of 13 flavors; §3's macro quote was the other arm's, not verbatim,
and "no geometry" overstated it). Two is a pattern, so I re-ran **all 16** `$`-prefixed
commands in this file rather than spot-checking.

**16 of 16 reproduce.** Two substantive corrections, both already folded in above;
**no verdict reversed**. Three of the sixteen only reproduced after I fixed my own
harness, and all three failures printed something plausible rather than failing loudly:

* **The image's default PDK is not the one under test.** `pad_ring_gen` in a fresh
  container refused with `PAD_SITE_NOT_FOUND ... ['sg13g2_cornerSite', 'sg13g2_ioSite']`
  — a different open PDK. The image ships seven (`asap7 ciel gf180mcuD ihp-sg13cmos5l
  ihp-sg13g2 nangate45 sky130A`) and defaults to `PDK=ihp-sg13g2`; **mounting a PDK
  does not select it**, and `jself-eda`, where the live run sits, has the same default.
  With `-e PDK=gf180mcuD` the same command returns §7's `PAD_INSTANCE_NOT_IN_BLOCK:
  77 ordered pad instance(s)`, rc 1, verbatim. Nothing in the refusal names the PDK
  it resolved except the site prefixes.
* **I destroyed the artefact I was verifying.** `pad_ring_gen` writes;
  re-running it to check §7 overwrote `probe_padring/reports/phase3/padring.json`
  with a wrong-PDK run. My check for that used `find -newermt "-20 minutes"`, which
  does not take a relative time that way — the guard silently inverted and reported
  nothing touched. `ls --time-style=full-iso` showed both files rewritten. Regenerated
  under the correct PDK; `probe_padring.bak_0405` is a full pre-write copy.
* **A reader that takes text, handed a path.** `router_iter_last_count` returned
  `None` on both sha256 logs — its own docstring says None means *"could not read
  this report"*, never 0, precisely to avoid the false PASS. Both arms failing
  identically was the signature of my harness, not the claim; with the file contents
  it returns `5 (288 counts)` / `5 (145 counts)` as published.

Detail and the full 16-row table: **J33**.

---

## 9. Rules I held to

No GDS hand-edited, no geometry deleted, no pin moved, no rule deck relaxed, no
`--write-baseline`, nothing pushed to `main`, no version bumped, the full
`programs/tests` suite not run, no `docker exec` into another identity's
container. `--force-step` was available and I did not reach for it — its own help
says it bypasses freshness only, and the input contract it would not have relaxed
is the one I am reporting. The DEFs in `meas/_probe_*` are labelled GEOMETRY
PROBES in the source that writes them; they exist to make the flow's own
side-width inequality the thing that decides, and none of them is a shipped
artefact. The seal-ring requirement has a general-path equivalent
(`General.SealRing` → `die_finishing_check` → the PDK's own `sealring.py`, J6) and
would be met by running 26.5ic's producer, never by drawing a ring.

Two more disclosures, because a reader should not have to find them:

* **Re-running `edge_llm_matmul_accel` at a larger die is not manufacturing a
  PASS.** The first run saturated at 3.300 mm; the sweeps give the design the die
  its own post-repair area demands and let the legalizer decide. Had they saturated
  too, that would have been the answer and it would have gone into §6 as the answer
  — the bracket is reported the way it came out, in both directions (3.300 mm
  refuses, 3.800 and 4.200 mm do not). **I did not touch a utilisation knob, a rule
  or a constraint to make any run come out**, and the sweep scripts are the runner's
  own `pnr.tcl` — lines 1-143 and 145-324 for the placement sweeps, lines 1-8364
  for the full-flow ones (J30) — with only `-die_area`/`-core_area` substituted and
  the write_defs into the live project dropped.
* Both chip-path runs also carry `--allow-oss-pdk-fallback`, alongside the
  `--allow-pdk-target-mismatch` already disclosed in §7.
* **Both placement sweeps have finished and both legalise** (§6). §6's verdict was
  written from the flow's own `_AUTO_DIE_TARGET_UTIL` and a measured, die-invariant
  cell area BEFORE either returned, and they corroborate it rather than supply it —
  which is the only reason it was safe to write early.
* **The 3.300 mm run I called "burning a core it should not be" turned out to be the
  most informative arm in the set.** An earlier draft said I had tried twice to stop
  it and the sandbox refused, so I left it. It did not stop at
  `INITIAL_DPL_LEGALIZE_FAILED` — nothing exits on that marker — and it carried on
  through spare insertion, setup repair, CTS and hold repair. That is the entire
  basis of J29, and it is one of the four arms the build-to figure now quoted for this
  row is measured on (J37, J64, J65). **The correction runs the opposite way from the usual
  one: I wrote a run off as waste and it was the measurement.**
* **A third arm is the full `phase3_one_shot_runner` on `proj/matmul_d3800` at
  3.800 mm**, and an earlier draft had it "still in ATPG". It is past that and in
  PnR, on a netlist byte-identical to the sweeps' (`md5 36f9575…`) at a core area
  identical to J26's 3800 point (`IFP-0102 14 201 741.030 um²`). That made my own
  extracted `fullflow_3800` redundant, **so I stopped it**, keeping the authoritative
  arm and the unique 4200 one. It cannot change the row, only sharpen which die to
  build — and it has: it is the 3800 point of the three-die reproduction in §6/J37.
  One honesty about that stop: the log records `rc=137`, which is SIGKILL, and a
  deliberate `docker kill` and the container's own 24 GB cap both produce it. No
  kernel OOM record is readable to this user, so I cannot prove which from evidence;
  a host-level OOM is ruled out (84–102 GB free throughout). "I stopped it" is a
  recollection, `rc=137` is the measurement, and they are not the same claim.
* **For about an hour I attributed that third arm to a co-tenant agent** and sized my
  own CPU share around it. It was mine. Worth recording because it is the same shape
  as the error this whole job corrects — a number read against the wrong owner.

**A chip that does not fit is allowed not to fit. Two of the six still do not, and
I said which half of each verdict survived. For three more the refusing number was
never a pad count, and I did not replace it with a different refusal I could not
measure. The sixth is core-limited and the tool, not I, is saying so.**
