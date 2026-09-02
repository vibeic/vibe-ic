# u_hawaii_adc `delta_sigma`: three declarations that cannot all hold

**Status:** open design decision. Nothing here proposes which constraint should
give way. This document exists so that whoever decides has the three numbers in
front of them.

**Measured at:** `v1.16.72` / `ded6aa231a68`, PDK `ihp-sg13g2`, image
`ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…d0d01ff`, host 8HD-8, load 10–20.
The refusing check is on branch `uhadc31-settling` (`d4a1cc6c7`), **not landed**.

---

## 1. The three declarations, quoted

All three come from the same file the flow ingests,
`phase1/input_doc/L5_ANALOG_SPEC.txt`, and reach the emitter through
`phase1/generated_docs/L5_ADI_SPEC.json` (`block.spec.source: L5_ANALOG_SPEC.md`).

### (a) The converter is incremental, order 2, OSR 256

`L5_ANALOG_SPEC.txt:25,28–31`, Block A — `delta_sigma` (×6 copies):

```
| converter_type | incremental delta-sigma | — | — | resets/accumulates per conversion window |
| Order | 2 | 1–3 | — | loop-filter order (est) |
| OSR | 256 | 64–512 | — | oversampling ratio (est) |
| ENOB | ≥ 14 | ≥ 10 | bit | target effective resolution (est) |
```

> Note on OSR in the measurements below: the campaign re-declared OSR to **64**
> — the low end of this same declared range — purely to make one measurement
> affordable (a full two-window transient at OSR 256 costs ~7 h/point on this
> host; at OSR 64 it is ~25 min). **No number in this document is a claim about
> the declared OSR 256.**

### (b) The clock is 1.0 MHz, range 0.1–10 MHz

`L5_ANALOG_SPEC.txt:35`:

```
| fclk | 1.0 | 0.1–10 | MHz | modulator clock (CK4/5/6) (est) |
```

The testbench this design's own emitter produces runs the modulator at the
**fastest rate the declaration admits** (100 ns period = 10 MHz), and says so
in its own header comment.

### (c) The current budget is 0.5 mA target / 1.0 mA maximum

`L5_ANALOG_SPEC.txt:44` — and this line is **in Block B, the `ldo`**, not in
Block A:

```
## Block B — `ldo` : low-dropout regulator (×1, supplies one modulator core)
| Iout | 0.5 | 0.1–1.0 | mA | modulator quiescent + dynamic budget (est) |
| Dropout | ≤ 0.5 | — | V | headroom (1.8 IOVDD − 1.2 CORE = 0.6 V available) |
```

So the ceiling is **the LDO's output-current rating for one modulator core**,
not a package, battery or thermal limit. `L19_CONSTRAINTS_PDK.json` carries
`power_budget_uw: null`; `L25_RELIABILITY_MISSION_PROFILE.json` has
`mission_profile`, `temp_range`, `qual_standard`, `em_budget` and
`aging_margin` all `null`. There is no upstream source for it in the tree.

**Every one of the three is tagged `(est)` in the source document.** So is
ENOB. `converter_type` is the only row in Block A that is not.

`L5_ANALOG_SPEC.txt:38` also says, of Block A:

```
R3: SC or CT, single-loop or otherwise — designer's choice, as long as
ENOB/OSR/range met.
```

---

## 2. The numbers

### 2.1 The incremental coefficient grows `ci` about 90×

The topology library used to carry a fixed table, `{"2": [0.5, 0.5]}`, cited to
the **free-running** second-order set (Boser & Wooley, JSSC 23(6), 1988). It was
replaced (v1.16.10) by a derivation for the regime this converter is actually
in — reset every window, accumulating from zero for `osr` clocks:

```
prod(a_i) · vref · N^L / L!  ≤  usable_swing
a = ( usable_swing · L! / (vref · N^L) )^(1/L)
```
(Márkus, Silva & Temes, IEEE TCAS-I 51(4), 2004.)

|                          | coefficient | ci/cs | ci drawn length |
|--------------------------|-------------|-------|-----------------|
| tabulated free-running   | 1/2         | 2.0   | 6.949 µm        |
| derived, OSR 256         | 1/181.1     | 181.1 | 629.08 µm       |
| derived, OSR 64          | 1/45.3      | 45.3  | 629.08 µm       |

**Where "about 90×" comes from:** 629.08 / 6.949 = **90.5×** in drawn length,
comparing the derived OSR-256 value against the tabulated one it replaced.
At OSR 64 the same derivation gives the *same drawn length* (cs grows 4× as
osr falls 4×, and a grows 4× with it, so ci = cs/a is unchanged — a
cancellation pinned by test); against the OSR-64 tabulated value of 27.80 µm
the ratio is **22.6×**. The two ratios describe the same change measured
against different baselines; neither is wrong, and quoting one for the other
is.

Measured on the emitted netlist at OSR 64: `xci2 = 9.487 pF`.

### 2.2 Settling needs ~7 time constants and has 1.8

Measured at the operating point of the emitted netlist (OSR 64):

| quantity | value | source |
|---|---|---|
| `gm` (mn_in2 / mn_ref2) | 692 / 697 µS | `.op`, `ids` 43 µA per side |
| `ci2` | 9.49 pF | `.op` |
| τ = ci/gm | **13.6 ns** | derived from the two above |
| usable settling time | **25 ns** | ¼ of the 100 ns clock the TB runs |
| time constants available | **1.8** | 25 / 13.6 |
| needed for the declared resolution | **≈ 7** | 0.1 % settling |

The transient agrees with what that predicts. `vsum2` and `vint` swing
**together with their difference fixed at 0.011 V**, so the integrating
capacitor never changes charge: the virtual ground is not a virtual ground, and
the charge `cf2` commutates each clock lands on the summing node's own
capacitance instead of on `ci`. Over eight consecutive clocks `vint` covers
0.4571–0.7427 V — and within any *one* clock it covers 0.4571–0.7427 V too.
It moves 0.285 V per clock and accumulates nothing.

### 2.3 Closing it costs 1.8× the ceiling

| step | value |
|---|---|
| time constants needed / available | 7 / 1.333 = **5.3×** |
| gm must rise by | 5.3× |
| gm ∝ I, so tail current must rise by | 5.3× |
| integrator pair's share of the block current | ≈ 196 µA of 947 µA |
| block current after scaling that share | ≈ **1.79 mA** |
| declared maximum | **1.0 mA** |
| result | **1.8× the ceiling** |

The block already measures **0.947 mA — 95 % of the ceiling** (round 29, whole
block, `i(v_vdd)`), after the common-mode buffer's output stage was chosen at
512/28 µm *specifically* to stay inside it.

So:

```
incremental coefficient derivation  →  demands a large ci
  large ci                          →  demands a large gm to settle in a phase
    large gm                        →  demands current
      current                       →  ceiling already at 95 %
```

---

## 3. The three ways out, and what each costs

**No recommendation is made here.** Each path is listed with its number, or with
an explicit "not measured".

### 3.1 Relax the incremental coefficient (smaller `ci`)

- Direct effect: τ falls in proportion. Getting to 7 τ by this route alone needs
  ci ÷5.3, i.e. ci/cs from 45.3 to 8.5 at OSR 64.
- **What it costs: NOT MEASURED.** The derivation's stated purpose is bounding
  integrator overflow, and its own docstring already records that it **bounds
  overflow and does not set the gain** — measured, 1/8 gave a mid-scale density
  of 0.1288 and 1/181 gave 0.0325, both against an ideal 0.5. Whether a
  coefficient 5.3× larger than the derived one overflows the window has not been
  measured on this design; the derivation says it would.
- Precedent in the tree: the tabulated 1/2 that this replaced **did** overflow —
  the first integrator saturated in two clocks of a 256-clock window.

### 3.2 Relax the current ceiling

- Overshoot: **1.79 mA against 1.0 mA = 1.8×**, i.e. +0.79 mA.
- Where the ceiling comes from: it is **the LDO block's `Iout` rating**
  (`L5_ANALOG_SPEC.txt:44`), tagged `(est)`, for a regulator declared as
  "×1, supplies one modulator core". It is **not** a package, battery or
  thermal limit — those fields are `null` throughout `L19` and `L25`.
- **What relaxing it costs: NOT MEASURED here.** It is a question about the LDO
  block, not this one: whether that regulator can source 1.79 mA within its
  declared dropout (≤ 0.5 V against 0.6 V of available headroom) has not been
  simulated. Note also `L5_ANALOG_SPEC.txt:25` declares the modulator as
  **×6 copies** while the LDO is **×1 supplying one core**, so the system-level
  reading of this number is itself worth confirming before it is moved.

### 3.3 Relax the clock or the OSR

- Clock: the settling margin is evaluated at `fclk_max` = 10 MHz, the rate the
  emitted testbench actually uses. At the **declared target of 1.0 MHz** the
  same expression gives **13.3 time constants and passes**. Dropping the clock
  10× therefore closes the settling constraint outright, with no current cost.
- **What it costs: NOT MEASURED.** Conversion time scales with 1/fclk: one
  window is OSR clocks, so at 1 MHz and OSR 256 a conversion takes 256 µs
  against 25.6 µs at 10 MHz. Whether the application tolerates that is not
  stated anywhere in the tree.
- OSR: lowering OSR shortens the window and lowers the coefficient's demand on
  ci, but ENOB is declared **≥ 14 bit** and SQNR for a second-order incremental
  falls steeply with OSR. **The ENOB-vs-OSR trade has not been measured on this
  design** — no ENOB has ever been measured on it, because the loop has never
  produced a transfer.

`L5_ANALOG_SPEC.txt:38` explicitly leaves the topology open —
*"SC or CT, single-loop or otherwise — designer's choice, as long as ENOB/OSR/
range met"* — so a fourth path (a different amplifier, e.g. one whose output
impedance is not paid for in static current) is permitted by the declaration.
Its cost is likewise **not measured**.

---

## 4. Two corrections worth carrying forward

### 4.1 "vint is stuck at 0.740 V" was a sampling alias

Round 30 reported the loop filter stuck at 0.7401 V, citing four samples 900 ns
apart that agreed to the fourth decimal. **Those samples were taken at multiples
of the 100 ns clock period**, so every one of them landed on the same clock
phase. Corrected: `vint` moves **0.285 V within every clock** and returns to the
same range each time. It is not stuck — it swings and accumulates nothing, which
is a different defect with a different cause.

### 4.2 `.op` is the wrong instrument for this circuit

A DC operating-point analysis opens every capacitor, and both of the questions
being asked here go through capacitors:

- **Switch conduction cannot be read from `ids`.** Once a switch's two terminals
  equalise there is no steady-state current through it, so an *open* switch and a
  *closed, settled* one both report ~0 A. Measured: `mp_smp2` at `Vds = 0.0000`
  with `ids = 2.6e-11 A` is conducting, not off.
- **The integrator is necessarily saturated.** With `ci` open there is no
  feedback path, so `.op` puts both integrator outputs at 1.065 V regardless of
  what the transient does (where the transient shows 0.59 V). That is the
  analysis, not the circuit.

Also recorded because it was my own error: region was first judged with
`|Vgs| − |Vth|` for **both** device types. That is the PMOS convention; for an
NMOS the overdrive is `Vgs − Vth` and using the absolute value reported
cut-off devices as saturated. Corrected.

**The transient is the valid instrument here.**

### 4.3 `slew_margin` passes at 2.0 and says nothing about settling

This is why the defect survived so long. The entry has bounded the
**large-signal** question since v1.16.10 — *can the bias move a full reference
step in the time available* — and it passes here at **2.0**, comfortably. It has
never bounded whether the loop then **settles**, which is a different question
with a different answer: **1.3** at the clock the circuit runs at. A block can
slew to the answer and never settle on it, and only one of those two was being
checked.

The companion bound is on `uhadc31-settling` and is deliberately **not landed**:
it refuses this declaration, and which of the three constraints gives way is the
decision this document exists to inform.
