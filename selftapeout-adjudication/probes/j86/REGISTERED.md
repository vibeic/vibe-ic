# J86 — predictions registered BEFORE the CTS buf_list probe ran

## The question

J84 measured that `clock_tree_synthesis -buf_list {clkbuf_4} -root_buf {clkbuf_16}`
instantiated the ROOT master **2 055 times** on one design and **once** on another, and
that those 2 055 fifty-site cells are the entire post-hold residual. J85 established
that nothing in the flow checks the CTS masters against the placeability bound. Neither
answers WHY CTS used the root master 2 055 times.

Two candidate mechanisms, and they have different fixes:

* **H1 — buf_list poverty.** `-buf_list` names exactly ONE cell. When a subtree needs
  more drive than `clkbuf_4` provides, CTS has nothing between it and the root master,
  so it reaches for the root master. FIX: widen `-buf_list`.
* **H2 — root_buf is used per sub-tree, not per tree.** CTS uses `-root_buf` at the root
  of every level/subtree it creates, so the count tracks the tree's shape and not the
  drive ladder. FIX: name a narrower `-root_buf`.

## Subject and its ENTRY CONTROL

`proj/matmul_d3800/phase3/stage3/pnr/placed.def` -- the pre-CTS state, written by the
runner at 04:14. It lacks the 3 833 spare cells (they are inserted after it), so it is
NOT byte-identical to what the arm handed CTS.

**E HOLDS if** the BASELINE invocation -- the arm's own
`-buf_list {clkbuf_4} -root_buf {clkbuf_16}` -- reproduces a ROOT-master count within
**+/-10 %** of 2 055 (i.e. 1 850-2 261). That bound is far smaller than the effect being
tested (2 055 vs an expected handful), so unlike J83's first entry control it CANNOT be
passed by a no-op.
**E FAILS ⇒ the variants are still reported, and reported as answered on a state that
is not the arm's.**

## Predictions

**P7 (H1).** With `-buf_list {clkbuf_1 clkbuf_2 clkbuf_4 clkbuf_8 clkbuf_12}` and the
same `-root_buf {clkbuf_16}`, the ROOT-master count falls **below 100** -- i.e. by more
than 20x. FALSIFIER: >= 100.

**P8 (H2).** With the arm's own `-buf_list {clkbuf_4}` but `-root_buf {clkbuf_8}`
(14.560 um = 26 sites, comfortably inside the 48-site inter-tap run), the count of the
NAMED ROOT MASTER stays **above 1 000** -- i.e. the flow keeps using whatever is named
as root, in quantity. FALSIFIER: below 1 000.

P7 and P8 are not exclusive: both can hold, and if they do the mechanism is "CTS uses
the named root master wherever its one-cell buf_list cannot reach", which has BOTH
fixes available and would make the choice a cost question rather than a mechanism one.

**P9 (the one that matters for the chip).** In the P8 arm, the widest clock-buffer
master present after CTS is **at most 38 sites** (clkbuf_12), i.e. **no master at or
above the 50-site placeability bound is instantiated at all**. FALSIFIER: any instance
of a >= 50-site master.

## Rules

Probe only. Nothing here changes the flow, and no result of it is applied to any
running arm. `docker run` in a fresh container with `--skip` first, never `docker exec`.
It STOPS after CTS and the census -- no legalizer, no full-die rung. No geometry edited,
no rule relaxed, no `--write-baseline`.

---

# AMENDMENT — P7 REFUTED, P8 and P9 HELD, so the remaining question is COST

Measured (each probe 79 s, all three printing `Created 2363 clock buffers` and
`Max level of the clock tree: 11` -- the tree is the SAME SHAPE in all three):

```
baseline      -buf_list {clkbuf_4}        -root_buf clkbuf_16   2054 x clkbuf_16 (50 sites)
wide_buflist  -buf_list {1 2 4 8 12}      -root_buf clkbuf_16   2054 x clkbuf_16  UNCHANGED
narrow_root   -buf_list {clkbuf_4}        -root_buf clkbuf_8    2052 x clkbuf_8  (26 sites)
                                                                   2 x clkbuf_16
```

E HOLDS: the baseline reproduces the arm's 2 055 as **2 054** (0.05 % apart).
P7 REFUTED: widening `-buf_list` did not move the root-master count by one instance.
P8 HELD: CTS instantiates whatever `-root_buf` NAMES, ~2 052 times.
P9 HELD: with a 26-site root buffer, only **2** instances at the placeability bound.

So the mechanism is not drive-ladder poverty. `-root_buf` is used at the root of every
subtree, and the flow names a master that is exactly at the placeability bound.

## P10 — the cost, registered before it is measured

Swapping the root buffer halves its drive (clkbuf_16 -> clkbuf_8). The tree is already
measured to be the same shape, the same 2 363 buffers and the same 11 levels, so the
question is TIMING.

**P10: the narrow-root tree's global clock skew is within 2x of the baseline's.**
FALSIFIER: worse than 2x. If P10 is refuted the swap is not cheap and the decision in
the report's §8 keeps all four of its original options.

Reported either way, and the change is NOT authored on the basis of this probe alone:
skew after CTS is not skew after routing, and one design is not a rule.
