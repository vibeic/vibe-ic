# u_hawaii_adc `delta_sigma`: lane state, for whoever picks this up

**Status:** blocked on an owner decision. Six defects were found by
measurement; five are fixed and landed, the sixth cannot be fixed without
choosing which of three declarations gives way.

**This document makes no recommendation.** The three paths and their costs are
in
[`2026-09-03-u-hawaii-adc-delta-sigma-three-way-constraint-conflict.md`](./2026-09-03-u-hawaii-adc-delta-sigma-three-way-constraint-conflict.md).

**Tree:** `v1.16.81` / `eebbc8fd0c33`. PDK `ihp-sg13g2`, image
`ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…d0d01ff`, host 8HD-8.

---

## 1. Fixed and landed

| # | Defect | Landed |
|---|---|---|
| 1 | The quantiser cited a StrongARM and emitted two of its four latch devices — no cross-coupled NMOS pair, input pair draining onto the regenerative nodes. Output separation was **linear in the input** (0.0025 V at 2 mV), i.e. a ~1.3 V/V amplifier, not a comparator. | **v1.16.18** |
| 2 | The transient started with `.tran … uic`, so the latch resolved on **unsolved** node voltages and the SR latch held that decision for the whole window. At −40 mV the `uic` deck decided POSITIVE (wrong) and the same deck without it decided NEGATIVE. | **v1.16.22** |
| 3 | The latch was strobed by the same edge the sampling and DAC switches fire on. A StrongARM commits ~1.5 ns after its tail turns on, and at that instant it was handed a clock-injection transient **3–5× the signal and identical at every input** (+0.098…+0.153 V, sign 63/63). | **v1.16.41** |
| 4 | The common-mode reference tracked the input **six times harder than the signal did** — `vcm` moved 0.1196 V across the input range against a signal variation of 0.004–0.024 V. Decoupling alone stalled at 3.3× (0.1196 → 0.0367 V) and was closed by extrapolation (a tenth of the signal needs ~734 unit caps ≈ 0.10 mm²); a unity-gain buffer followed. | **v1.16.44**, **v1.16.50** |
| 5 | The all-ones decode is a combinational AND over an **asynchronous ripple counter**, glitching 5–6 times per window at ~0.6 ns, wired straight to the integrator shorts and the auto-zero clamp. Round 20 fixed this in a hand-edited netlist and it **never reached the producer**; round 29 found `nallc` appearing 0 times in both the emitted netlist and the emitter. | **v1.16.72** |

Two process defects were fixed alongside them, and both are the same shape as
#5 — a fix that does not reach the emitter reaches nobody:

| Defect | Landed |
|---|---|
| The A1–A3 producers ran only on the gate's rc 2 (artefact missing). With a **stale** artefact the gate returned rc 0, the step reported PASS, and the producer never ran — so a lane that had just fixed the topology library simulated the old netlist and the run looked identical to a successful one. Producers now stamp a digest of their own source; the runner compares it before skipping. | **v1.16.29** |
| Choosing 512/32 µm for the buffer output stage met the derived 360 Ω but drew **1.037 mA against the design's own 1.0 mA maximum**. 512/28 (0.947 mA, 388 Ω) was taken instead, and *which declaration outranks which* is stated in the source: the design's ceiling beats a target this analysis derived. | **v1.16.67** |

---

## 2. The sixth defect, and why it is stuck

The loop filter does not integrate. `vsum2` and `vint` swing **together with
their difference fixed at 0.011 V**, so the integrating capacitor never changes
charge — the virtual ground is not a virtual ground, and the charge `cf2`
commutates each clock lands on the summing node's own capacitance instead of on
`ci`. Over eight consecutive clocks `vint` covers 0.4571–0.7427 V, and within
any *one* clock it covers 0.4571–0.7427 V too: 0.285 V per clock, accumulating
nothing.

| quantity | value |
|---|---|
| `gm` (mn_in2 / mn_ref2) | 692 / 697 µS |
| `ci2` | 9.49 pF |
| τ = ci/gm | **13.6 ns** |
| usable settling time (¼ of the 100 ns clock the TB runs) | **25 ns** |
| time constants available | **1.8** |
| needed for the declared resolution | **≈ 7** |

Closing it needs gm ×5.3 → tail current ×5.3 → **≈ 1.79 mA** against a declared
maximum of 1.0 mA that the block is **already at 95 % of**. That is the
three-way conflict:

```
incremental coefficient derivation  →  demands a large ci  (grew it ~90×)
  large ci                          →  demands a large gm to settle in a phase
    large gm                        →  demands current
      current                       →  ceiling already at 95 %
```

The bound that refuses this declaration (`settling_time_constants`, floor 7,
reading **1.3** at the clock the circuit runs at) is written and tested but
**deliberately not landed** — it sits on branch `uhadc31-settling`. Landing it
turns 12 tests that assert this entry emits red, for the same honest reason
round 20's coefficient derivation did: the entry would then say this cannot be
built this way.

---

## 3. Still NOT_MEASURED

Nothing below has ever been measured on this design. None of it should be
quoted as a number.

* **All five sweep points.** Latest run (v1.16.72, OSR 64, `tstep` 0.5n,
  window 6528–12800 ns): every one of vin 0.30 / 0.40 / 0.50 / 0.60 / 0.70 is
  **NOT_MEASURED** — `dac_edges` 0 at all five. Density is withheld, not
  reported as 0.
* **Monotonicity.** Fewer than two LIVE points, so the falsifier cannot fire.
  A falsifier that cannot fire is not a result.
* **Gain, offset, INL, DNL, ENOB.** These have no object until a transfer
  exists. ENOB in particular is declared ≥ 14 bit and has never been measured.
* **Anything at the declared OSR 256.** Every measurement in this lane since
  round 24 was taken at **OSR 64** — the low end of the same declared range —
  purely for cost (a full two-window transient is ~7 h/point at OSR 256 versus
  ~25 min at OSR 64). No number here is a claim about OSR 256.
* **`tstep` was never relaxed** (still 0.5n). If a future round moves to 2n to
  buy speed, two earlier measurements become unmeasurable: round 20's
  0.1–0.7 ns decode glitches, and round 21's 1.13–1.47 ns latch regeneration
  time. Say so if you do it.
* **The 512 µm buffer pull-up** must be drawn multi-finger. That is A5's `m`,
  not A2's, and it has not been laid out.
* **A6** was last measured at 68 violations of 628 rules on the narrow-keeper
  layout (0 of 560 on geometry without it). Not revisited since.

---

## 4. Two instrument lessons

These cost this lane the most time and will cost the next reader the same.

### 4.1 Sampling alias

Round 30 reported the loop filter "stuck at 0.7401 V", citing four samples
900 ns apart that agreed to the fourth decimal. **Those samples sat on
multiples of the 100 ns clock period**, so every one landed on the same phase.
Corrected: `vint` moves 0.285 V within every clock and returns to the same
range. Not stuck — swinging and accumulating nothing, which is a different
defect with a different cause.

**Sample against the strobe, not against the wall clock.**

### 4.2 `.op` is the wrong instrument for this circuit

A DC operating point opens every capacitor, and both questions asked here go
through capacitors:

* **Switch conduction cannot be read from the drain current.** Once a switch's
  terminals equalise there is no steady-state current, so an *open* switch and
  a *closed, settled* one both report ~0 A. Measured: `mp_smp2` at
  `Vds = 0.0000` with `ids = 2.6e-11 A` is conducting, not off.
* **The integrator is necessarily saturated.** With `ci` open there is no
  feedback path, so `.op` puts both integrator outputs at 1.065 V regardless of
  what the transient does (the transient shows 0.59 V). That is the analysis,
  not the circuit.

Recorded with it, because it was my own error: device region was first judged
with `|Vgs| − |Vth|` for **both** types. That is the PMOS convention; for an
NMOS the overdrive is `Vgs − Vth`, and using the absolute value reported
cut-off devices as saturated.

**The transient is the valid instrument here.**

---

## 5. `slew_margin` is a constant, and the real clock mismatch is elsewhere

`slew_margin` reads 2.0000 at fclk 0.1, 1.0 and 10.0 MHz alike — it is
identically `slew_design_margin` for **every** declaration:

| fclk (MHz) | r_ib_l_um | I_tail | C_load | slew_margin |
|---|---|---|---|---|
| 0.1 | 150.889 | 9.81 µA | 12.267 pF | 2.0000 |
| 1.0 | 15.089 | 98.14 µA | 12.267 pF | 2.0000 |
| 10.0 | 1.509 | 981.37 µA | 12.267 pF | 2.0000 |

`fclk` appears once in the time available and once inside the bias length this
entry derives *from* the slew requirement (v1.16.10), so `I_tail ∝ fclk`
cancels it. The load cancels the same way — it appears twice, and scaling both
gives 2.0 → 2.0. **Reading that 2.0 as "this block has twice the slew it needs"
is reading a constant.** It is retained as a *consistency* check: it moves only
when `_LOAD_F_EXPR` and `_R_IB_L_UM_EXPR` are edited apart.

**The real mismatch is in `bias_resistor_l_um`.** This entry binds `fclk_max`
in `requires_bound`, builds every testbench time from `fclk_max` —

```
tper_ns  = 1000 / fclk_max          tmeas_ns = window_clocks * 1000 / fclk_max * 1.02
thigh_ns = 1000 / fclk_max / 2 - 1  tstop_ns = window_clocks * 2000 / fclk_max
```

— and then sizes the **circuit** from `fclk`: `_TAIL_I_EXPR`,
`_R_IB_L_UM_EXPR`, and the `r_ib` device length. On the declaration in hand
that is a bias built for 1.0 MHz and simulated at 10 MHz: **98 µA where
`fclk_max` would ask for 981 µA.**

It is **not fixed**, on purpose. Deriving the bias at `fclk_max` multiplies the
integrator tail current by ten and lands squarely on the current ceiling that is
the open decision. Fixing it would pre-empt that decision, which is not this
lane's to take.

---

## 6. Where things are

| | |
|---|---|
| Refusing settling bound, written and tested, **unlanded** | branch `uhadc31-settling` |
| Three-way conflict, with each path's cost | `docs/research/2026-09-03-u-hawaii-adc-delta-sigma-three-way-constraint-conflict.md` (landed v1.16.75) |
| Per-round verdicts, every number with its tree and host load | `~/_icverdicts/uhadc_*.txt` on 8HD-8 |
| Measurement trees, raw files kept | `~/_uhadc_r2*/`, `~/_uhadc_r3*/` on 8HD-8 |
