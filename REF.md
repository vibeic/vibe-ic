# REF — si_mcf_sta folds every coupling cap twice; the gate cannot see it

**Class:** chip-AGNOSTIC plugin defect (flow-level: a Phase-3 sign-off gate every
design passes through).
**Found on:** plugin v1.14.22 (current main), host 192.168.1.121.
**Subject:** `/home/reyerchu/vibeic-designs/subservient_gf180mcuD_20260831_e1`,
`reports/phase3/si_mcf_sta.json` verdict **FAIL**,
`reports/phase3/si_mcf_sta_check.json` verdict **PASS**.
**Defect site:** `programs/si_signoff_timing_aware.py` :: `parse_spef()`, pass 2
(lines 311-317 at v1.14.22).
**Blast radius:** `programs/si_mcf_sta.py`, `programs/si_mcf_sta_check.py`, and
every consumer of `sp["cc"]` / `sp["pair_cc"]` in `si_signoff_timing_aware.py`
(lines 523, 551, 617, 655, 732, 757, 841).

## What is wrong

IEEE-1481 permits — and OpenROAD emits — the *same physical* coupling cap twice:
once in each of the two coupled nets' `*CAP` sections (the reciprocal listing).
`parse_spef()` appends every 2-node `*CAP` line to `raw_pairs` and then, in pass
2, accumulates all of them:

```python
for na, nb, val in raw_pairs:
    ra, rb = _resolve(na), _resolve(nb)
    cc[ra] = cc.get(ra, 0.0) + val
    cc[rb] = cc.get(rb, 0.0) + val
    if ra != rb:
        pair_cc[frozenset((ra, rb))] = pair_cc.get(...) + val
```

There is no de-duplication of the reciprocal listing anywhere in the parse. So
`pair_cc[(A,B)] = 2 * Cc_physical(A,B)` and `cc[net] = 2 * Cc_physical(net)`.

`si_mcf_sta.victim_folded_caps()` then correctly credits `cc * MCF` to **both**
nets of each pair (reciprocity) — which is right *only if* `cc` is the single
physical value. Because it is already doubled, every victim is folded at **2×**.

Measured on subservient (`subservient.spef`, OpenROAD 26Q3-1921-g4de296ee89):

| | measured |
|---|---|
| coupling `*CAP` lines | 29410 |
| distinct physical caps | 14705 — **every one listed exactly twice, in two different `*D_NET` blocks, identical value** |
| `sum(pair_cc)` as parsed | 14.302661 pF |
| physical coupling | 7.151330 pF |
| setup fold applied (MCF=2) | 55.788 pF |
| setup fold that MCF=2 calls for | 27.894 pF |

## What it costs

The design is timing-clean nominally (worst setup **+1.9578 ns**). Under the
inflated fold OpenSTA reports **−4.6706 ns** and the gate FAILs. Re-running the
plugin's *own* STA tcl against a correctly de-duplicated fold, changing nothing
else:

| corner | nominal | as-shipped (2×) | corrected (1×) |
|---|---:|---:|---:|
| worst slack max | +1.9578 | **−4.6706** | **+0.6440** |
| worst slack min | +1.9319 | +2.0048 | +1.9605 |

**The entire −4.6706 ns is manufactured by the double-count.** There is no SI/MCF
timing violation on this design and nothing in the design to fix.

## Why the gate confirmed it

`si_mcf_sta.independent_recount()` advertises that "an OVER-applied (inflated)
fold is caught too" (si_mcf_sta.py:550). It cannot be. It calls the *same*
`coupling_pairs()` (si_mcf_sta.py:554) and derives its over-application ceiling
from the *same* doubled `raw_cc` (si_mcf_sta.py:583). The recount is independent
of the **emitter's arithmetic** but not of the **parse**, so it reproduces the
identical doubling and certifies it. That is the whole reason a run can show
`si_mcf_sta=FAIL` beside `si_mcf_sta_check=PASS, vacuous=false, errors_count=0`.

## Corpus sweep — this is not one design

All 27 SPEFs under `/home/reyerchu/vibeic-designs/*/phase3/stage3/extracted/`
(spm, sha256, subservient; gf180mcuD and sky130A):

```
ratio histogram (old_sum / new_sum) = {2.0: 27}    27 of 27
listed == 2 * physical                             27 of 27
  sha256.spef      242666 listed -> 121333 physical   169.648 pF -> 84.824 pF
  subservient.spef  29410 listed ->  14705 physical    14.303 pF ->  7.151 pF
  spm.spef           8132 listed ->   4066 physical     3.024 pF ->  1.512 pF
```

Every `si_mcf_sta` and `si_signoff_timing_aware` number ever published from this
corpus was computed on a 2× coupling.

## Fix

De-duplicate by the **unordered physical node pair** before accumulating, and
return `coupling_caps_listed` / `coupling_caps_physical` so the doubling can
never again be invisible. See `candidate.patch`.

Do **not** fix this by halving in `si_mcf_sta.py`: an extractor that lists each
Cc only once would then be halved wrongly. De-dup on the node pair is correct
under both conventions — a single-listing SPEF has nothing to collapse and comes
out bit-identical. `test_single_listing_spef_is_not_halved` is that guard.

---

## UPDATE — re-measured at v1.14.24 (current main)

v1.14.24 landed `unescape_spef_name()` in `si_mcf_sta.py`, fixing a **different**
defect in the same gate: the SPEF spells pins with IEEE-1481 escapes while the
timing report spells them plainly, the driver-pin lookup failed, and an unknown
window conservatively assumes overlap — so unmatched nets were promoted to
worst-case MCF. Window resolution goes **465 → 1530 of 1558 nets (98.2%)**.

`si_signoff_timing_aware.py` is **byte-unchanged** 1.14.22 → 1.14.24, so the
double-count reported here **is still open at current main**, and
`candidate.patch` still applies cleanly (`git apply --check` clean against
`9167b162e`).

Re-measured on a pinned snapshot (`subservient.spef` md5 `7dd44470c357`,
`si_mcf_windows.json` md5 `48d7e58cfece`):

| arm | setup worst slack | hold worst slack |
|---|---:|---:|
| v1.14.24 as-shipped | **−4.0588 FAIL** | +1.9347 |
| v1.14.24 + reciprocal de-dup | **+1.1813 PASS** | +1.9200 |

**v1.14.24 does not close this red.** It moves it −4.6706 → −4.0588; the
remaining −4.06 ns is the double-count. With the de-dup the gate passes with
**+1.1813 ns** — *more* margin than the +0.6440 measured at 1.14.22, because the
1.14.24 window fix correctly de-rates aggressors that provably do not overlap.
The two fixes are independent and compound; **neither alone closes the red.**

(Setup fold: 47.918 pF as-shipped → 23.959 pF de-duped. Hold fold *rose*
1.423 → 9.293 pF versus 1.14.22, because correctly-resolved non-overlapping
aggressors now take MCF=1 rather than MCF=0 — that is the right direction.)

---

## SECOND red closed by the same patch — `si_mcf_sta_check` hold monotonicity

On `subservient_keeper_1.14.26` (v1.14.26, fresh PnR) `si_mcf_sta_check` also
FAILs, with an ERROR that was silent at 1.14.22:

```
SLACK_BETTER_THAN_BOUND — hold: reported SI-bounded slack 1.9261 ns is BETTER
than the nominal grounded 1.913 ns — a conservative MCF bound can only DEGRADE it
```

A node-id path diff (`report_checks -path_delay min`, keyed on start/end) shows
this is **not** a min-over-changing-set artefact. The worst path does change
identity, but the identity-matched path is itself better under the bound:

| path | nominal | bounded | delta |
|---|---:|---:|---:|
| `__uuf__._1764_ -> __uuf__._1765_` | 1.9130 | 1.9263 | **+0.0133** |

Cause: for hold, MORE cap means later arrival and BETTER slack. At MCF=1 (an
aggressor proved non-overlapping) the fold must equal Cc exactly and reproduce
the nominal grounded cap. Doubled, it applies 2*Cc — more cap than nominal — and
hold slack improves. v1.14.24's window fix made this visible by moving most
aggressors from MCF=0 to MCF=1 (hold fold 1.42 -> 7.92 pF); at 1.14.22 the corner
was mostly MCF=0 and the inflation was masked.

Confirmed by the Step-7 arms: as-shipped hold 1.9347 vs nominal 1.9319 (+2.8 ps,
violates); with the de-dup 1.9200 vs 1.9319 (-11.9 ps, monotonic).

**One patch closes both reds.** Neither is a design fact.
