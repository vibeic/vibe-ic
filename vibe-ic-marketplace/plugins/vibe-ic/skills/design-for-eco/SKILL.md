---
name: design-for-eco
description: "Design-for-ECO methodology — pre-place a distributed pool of tied-off spare standard cells/gates and reserve spare ECO pads so that a late-stage bug can be fixed with a cheap metal-only ECO instead of a full base-layer respin. Covers WHY (metal-only vs base-layer respin cost), WHAT to insert (inverter/nand2/nor2/dff/mux2/aoi/oai mix, ~1-5% density, tie-offs, even spatial distribution, reserved ECO pads), WHERE in the flow (after placement, before CTS), ECO-aware metal fill, and the HARD preservation rule that every downstream optimization must obey. Use when: 'design for eco', 'spare cells', 'ECO prep', 'metal-only ECO readiness', 'reserve spare gates', 'spare pad planning', or before CTS on any digital place-and-route flow."
---

# Design-for-ECO — spare-cell / spare-gate / spare-pad readiness

A taped-out chip will, sooner or later, need a fix: a missed timing path, a
logic bug found in bring-up, a metal-mask trim. The cheapest possible fix is a
**metal-only ECO** — reusing already-placed transistors and only re-spinning a
few metal/via masks. The most expensive is a **base-layer respin** — new
diffusion/poly masks, a full mask set, weeks of fab time. Design-for-ECO is the
discipline of *pre-investing* a small amount of silicon area, BEFORE tape-out,
so that future fixes stay in the cheap (metal-only) regime.

This skill is **chip-AGNOSTIC**: it describes the methodology and the hard
preservation rule; the deterministic insertion + verification is owned by the
phase3 stage3 Design-for-ECO step and its two checkers (see *Flow integration*).

## Why pre-place spare cells/gates + reserve spare pads

| Fix vehicle | Masks touched | Relative cost / turn time | Needs spares? |
|---|---|---|---|
| Metal-only ECO | a few metal + via | low — days, partial mask set | **yes** — must reuse existing transistors |
| Base-layer ECO | poly/diffusion + all above | high — weeks, full mask set | no (but expensive) |
| Full respin | entire mask set + re-PnR | highest | no |

A metal-only ECO can only add/replace logic if the transistors it needs are
**already on the die** (placed, powered, tied off) and only need re-wiring.
If no spare cells exist near the bug, even a one-gate fix forces a base-layer
respin. The same logic applies at the chip boundary: a missing test/trim/config
signal after tape-out needs a **reserved spare pad** (and its ESD + bond
option) already present — you cannot add a pad in metal only.

So Design-for-ECO trades ~1-5% area + a handful of pads now for the option to
do almost any late fix as a metal-only spin later. On most projects that option
is exercised at least once and pays for itself many times over.

## What to insert

### Spare standard cells / gates (the ECO pool)
Insert a *mix* of cell types so an arbitrary future fix can be assembled from
nearby spares without re-placing:

- **Inverter** (`inv`) — buffering, polarity, hold padding.
- **NAND2 / NOR2** — universal 2-input logic; any combinational function is
  reachable by composing these.
- **AOI / OAI** (and-or-invert / or-and-invert) — compact compound gates for
  denser logic fixes.
- **MUX2** — select/bypass/observe insertion.
- **DFF** — sequential fixes (re-time, add a pipeline stage, sample a signal).

Guidance:
- **Density target ~1-5%** of placed std-cell area (start ~2-3%; raise to 5% for
  risky/first-silicon designs, lower toward 1% for mature, low-risk blocks).
- **Type ratio** roughly: many inverters + NAND2/NOR2 (the workhorses), a useful
  count of MUX2 and DFF, a smaller set of AOI/OAI. The pool must be able to
  build both combinational and sequential fixes.
- **Tie-offs (mandatory):** every spare input is tied to a defined level
  (VSS via tie-low / VDD via tie-high, or a tie cell), every spare output is
  left floating-safe (unconnected or tied per PDK rule). An *untied* spare
  input floats → leakage, latch-up risk, and an LVS/ERC failure. A spare that
  is not properly tied off is **not** a usable spare.
- **dont_touch / keep:** every spare cell/gate is marked `dont_touch` (a.k.a.
  `keep`) so synthesis/PnR optimization will not delete, resize, absorb, or
  re-purpose it. This attribute is the contract that the rest of the flow obeys
  (see *The HARD preservation rule*).

### Reserved spare pads
Reserve a small number of **spare I/O pads** (with ESD cells, optional bond
finger, and a tie-off / weak pull) at the chip boundary, marked
`dont_touch`/`keep`. These enable post-tape-out access to a new test/trim/
config signal as a metal-only + bond-option change rather than a respin.

### Distribution (not a corner dump)
Spares must be **spatially distributed** across the placeable area — a roughly
uniform grid / per-region quota — so that every region of the die has spares
within ECO routing reach. A bug in a far corner cannot be fixed metal-only by a
spare that sits 500µm away. The coverage checker verifies per-region density
and distribution, not just a global count.

## Where in the flow

```
placement (legalized)  ─▶  ★ Step 18: Design-for-ECO insertion ★  ─▶  CTS  ─▶  route  ─▶  fill  ─▶  signoff
                            (distributed spare pool +
                             tie-offs + reserved pads,
                             all dont_touch/keep)
```

In the canonical 56-step flow this is **Step 18** (between placement, Step 17, and
CTS, Step 19); all later numeric steps shift +1 relative to the old 55-step flow.

- **After placement, before CTS.** Spares need legal placement sites and must be
  in the database before CTS/route so the clock tree and routing account for
  them. Inserting earlier risks them being optimized away by placement opt;
  inserting after route defeats the "already placed/powered" purpose.
- **ECO-aware metal fill.** When metal fill is added at signoff, it must be
  *ECO-aware*: do not lock fill over the metal tracks above spare cells and
  reserved pads, or use slottable/removable fill there, so a future metal-only
  ECO can route to the spares without ripping up locked fill. Treat the spare
  pool's routing channels as reserved.

## The HARD preservation rule

> ⛔ **ECO spare-cell preservation (chip-AGNOSTIC, non-negotiable):**
> Any instance carrying the `dont_touch` / `keep` attribute, or otherwise tagged
> as a spare/ECO cell, gate, or pad, is **RESERVED for a future metal-only ECO**.
> No flow step — synthesis, PnR optimization, area recovery, timing repair,
> hold fix, DRC fix, ECO, or any cleanup — may **delete, resize, re-purpose, or
> optimize it away**. Specifically: no `opt_clean` / `clean -purge` /
> `remove_buffers` / area-recovery acting on keep-marked instances. After ANY
> optimization, `spare_cell_preservation_check.py` MUST still PASS (the spare
> set is intact and all keep attributes are preserved, 0 removed). If a change
> drops a spare, that is a **regression** — restore the spare and re-run the
> checker before proceeding.

Every optimization skill (`synth-doctor`, `rtl-repair`, `hold-fix`, `eco-plan`,
`ppa-predict`, `drc-fix`) carries a tailored copy of this block.

## Flow integration

The deterministic mechanics are owned by the phase3 **stage3 Design-for-ECO**
step (in the flow runner), not by this skill:

- The stage3 step **inserts** the distributed, tied-off spare std-cell pool
  (inverter / nand2 / nor2 / dff / mux2 / aoi / oai) + reserved ECO pads, all
  marked `dont_touch`/`keep`, and emits:
  - `phase3/stage3/pnr/spare_cells.json` — the inserted spare inventory.
  - `reports/spare_cell_coverage.json` — density / distribution / tie-off
    readiness summary.
- `spare_cell_coverage_check.py` (**readiness**) verifies the pool meets the
  density / distribution / tie-off targets → coverage PASS.
- `spare_cell_preservation_check.py` (**preservation**) verifies that NO spare/
  ECO cell/gate/pad was optimized away by any later step, and that all keep
  attributes are intact → emits `reports/spare_preservation.json`
  (`all_keep_attr_intact`, `removed` count).

## Acceptance (Design-for-ECO readiness gate)

A digital place-and-route IC is Design-for-ECO-ready iff:
- `reports/spare_cell_coverage.json` → readiness **PASS** (density in ~1-5%
  band, distributed, all spares tied off), **and**
- `reports/spare_preservation.json` → `all_keep_attr_intact == true` **and**
  `removed == 0`.

`benchmark-verify` reports this as its sixth pillar ("Design-for-ECO readiness").
It is **N/A** only for an IC that genuinely has no place-and-route (analog-only,
no DEF/GDS). A missing spare report is **PENDING**, never a silent PASS.

## Do not
- Do not dump all spares in one corner — distribution is the point.
- Do not leave spare inputs floating — untied spares fail ERC/LVS and are unusable.
- Do not let metal fill lock the tracks over spares/pads — keep ECO routing reachable.
- Do not allow any downstream optimization to remove a keep-marked spare.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/design-for-eco/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
