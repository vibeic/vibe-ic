# u_hawaii_adc `delta_sigma`: what blocks it is none of the three declarations

**Status: CORRECTED 2026-09-05.** The original version of this document — kept
below from section 1 onward, with two of its own sections corrected in place —
argued that three declarations (OSR/order, clock, current) cannot all hold, and
laid out three ways to relax one of them. **That framing is wrong, and acting on
it would have cost a design iteration.** None of the three needs to be relaxed.
The block does not convert for a reason none of the three describes, and the
measurements that settle it are in section 0.

**Correcting measurement:** host 8HD-6. Transient measurements were re-run alone
at host load 3.4–4.2 and the load is stated with each; the `.ac` and `.op`
measurements are sub-2-second and load-insensitive. Image `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…d0d01ff` (local image id
`sha256:b8b65ea3af6e…`), ngspice-47, PDK `ihp-sg13g2`. Netlist under test is
`phase3/analog/delta_sigma/delta_sigma.sp` as emitted, with only its `.lib`
paths repointed at the project's own PDK copy. Testbench conditions are the ones
the design's own emitter states in the header of its `co_1.00.sp`: vdd 1.2 V,
vrefp/vrefn 1.1/0.1 V, clk 100 ns (`fclk_max` = 10 MHz, the binding settling
corner), `uic`.

---

## 0. What is actually measured

### 0.1 The four declarations

| declaration | state | evidence |
|---|---|---|
| `fclk` 1.0 MHz (range 0.1–10) | **not adjudicated here** | the deck runs at 10 MHz = `fclk_max`, and its bias leg is `r_ib l=33.427u`, which matches NEITHER of the two lengths §2.3's own table derives (15.089 µm at 1 MHz, 1.509 µm at 10 MHz). I therefore do not repeat the claim that "the circuit is biased for 1 MHz": on this deck it is biased for neither. The clock mismatch itself is real and is recorded in `analog_a2_topology_emit.py`, not here |
| `Iout` ≤ 1.0 mA | **MET on this deck** — 0.4368 mA | see §0.4. Not inherited from any earlier number |
| `OSR` 256 | see §0.5 | a two-window OSR-256 transient costs minutes, not the ~7 h this document previously assumed; measured wall time in section 5 |
| `ENOB` ≥ 14 | see §0.5 | |

### 0.2 The integrator's amplifier is not the blocker

`swing(vout)/spread(vout − vsum)` — the bound this lane inherited as evidence of
"integrator gain ≈ 13" — is **not a measurement of amplifier gain**. (The
specific values 12.5 / 16.1 that were circulating as that evidence have no
backing measurement anywhere in the tree or on the fleet; the baseline used in
every comparison here is therefore this lane's own measurement on the frozen-base
deck, not those figures.) It conflates
finite DC gain, incomplete settling, and every reset and charge-injection event
inside the window. Measured directly instead, by `.ac` on one integrator OTA at
its in-circuit operating point (DC unity-gain feedback through a 1 TH inductor,
AC injected through a 1 TF capacitor, non-inverting input at the measured
vcm 0.6125 V, 9.5 pF load):

| OTA | open-loop DC gain | GBW | signal-path current |
|---|---|---|---|
| as emitted (2-stage Miller, 5T first stage) | **50.3 dB / 327 V/V** | 18.7 MHz | reference |
| telescopic-cascode first stage (`ota_tel_l1`) | **71.1 dB / 3600 V/V** | 18.8 MHz | UNCHANGED mirror ratios |

The emitted amplifier's DC gain is **327, not 13** — 25× above the bound that was
being read as its gain.

The replacement buys its 20.8 dB from cascoding and device geometry only: the
tail (8u/1u) and the second-stage sink (8u/1u) keep the emitted mirror ratios
against the same 4u/1u reference leg, so signal-path current is untouched, and
cascoding raises the first stage without touching `gm_in`, so GBW is preserved.

Substituting it into both arms of the full modulator and re-measuring the SAME
bound over the SAME settled window:

| netlist | OTA open-loop gain | A_arm_A | A_arm_B | Ivdd mean | density |
|---|---|---|---|---|---|
| as emitted | 50.3 dB | 10.75 | 13.01 | 0.4368 mA | 0.0000 |
| telescopic | 71.1 dB | 15.04 | **8.99** | 0.5394 mA | 1.0000 |

**An 11× increase in amplifier gain moved one arm's bound by 1.40× and the other
arm's the wrong way, by 0.69×.** The bound does not track gain. Whatever it is
measuring, it is not the amplifier, and no amplifier will fix it.

### 0.3 Where the charge goes, and what actually stops the conversion

The integrator does not accumulate. Measured as the sampled-data state — `vint`
sampled 2 ns before each rising clock edge, clocks 60–199 (see the correction to
§4.1 below on why fixed-phase sampling is the right instrument for a
switched-capacitor circuit, not an "alias"):

| quantity | value |
|---|---|
| drift of `vint` at one fixed clock phase | **−20.3 µV/clock** |
| step the capacitor ratio demands, `cs/ci · (vin − vcm)` | **+1932 µV/clock** |
| step the 1-bit DAC alone demands, `cf/ci · (vrefp − vcm)` | **+10 771 µV/clock** |
| `bit_out` at that same fixed phase, all 140 samples | 0 V — the quantiser never fires |

About **1 % of the signal charge and 0.2 % of the feedback charge** reaches the
integrating capacitor, and with the wrong sign. That is the defect, stated as a
number, for the first time in this document's history.

**What it is NOT.** It is not amplifier gain (§0.2: 327 V/V measured, and 3600
V/V changes nothing). It is not the window reset (control experiment below). It
is not a conflict between the declarations of §1.

**What is confirmed about the window reset.** `nall` gates both integrator reset
switches (`xmn_rsti1`, `xmn_rsti2`) and the quantiser auto-zero (`xmn_azq`).
Every assertion in a 200-clock run, classified by width:

| kind | count | width | interval |
|---|---|---|---|
| sustained terminal count | **4** | 97.9–98.4 ns | exactly 6400 ns = **64 clocks**, as designed |
| decode glitches | **18** | **0.02–0.58 ns** | at 2, 4, 8, 16 and 32 clocks into every window |

So the counter itself is **correct**: it is a 6-stage ripple divider, its
terminal count `q1·q2·q3·q4·q5·q6` fires once per 64 clocks, and it does exactly
that. What is defective is that the AND decode is **unregistered**, so it also
glitches at every power-of-two ripple boundary, where the asynchronous stages
transiently read all-ones.

**The glitches are NOT the blocker — control experiment, run.** Those glitches
are sub-nanosecond; against a `w=4u l=0.15u` reset switch into `ci = 9.49 pF`
(RC of order 28 ns) they can dump only a few percent of the stored charge. So
rather than assert them as the cause — which would repeat exactly the error this
correction exists to undo — the reset switches were driven from an **ideal,
glitch-free 64-clock reset** with everything else identical (`ds_idealrst`, the
counter left in place, only its fan-out to the reset switches cut). Result:
density **0.0000 at every input**, `bit_out` transitions **0**, `vint` drift
1.6–1.8 µV/clock. **A perfect reset changes nothing.** The unregistered decode is
a real defect and should be fixed on its own merits; it is not what blocks the
conversion.

**What DOES block it: three defects in series, all measured.**

**(1) The switched-capacitor integrators are missing their transfer-phase
switches.** `vsum1` connects to exactly five things — the OTA input gate, `cs1`,
`ci1`, `cf1`, and the reset switch. **There is no switch between the sampling
capacitors and the summing node.** Only the bottom plates are switched
(`vin↔vcm`, `ndac↔vcm`), so each capacitor delivers `+C·(V−vcm)` on one clock
edge and takes it straight back on the next: **net zero charge per clock
period**, up to second-order asymmetry. A parasitic-insensitive SC integrator
switches *both* plates; the summing-node plate must sit at `vcm` while the
capacitor samples and reach the virtual ground only during the transfer phase.

Giving the four capacitors the switches they lack (`ds_fix`, +16 devices in the
same transmission-gate style and geometry the netlist already uses for its
bottom-plate muxes, nothing else changed):

| deck | `vint` drift at one fixed clock phase | vs the +1932 µV/clock the ratio demands |
|---|---|---|
| as emitted | **−20.3 µV/clock** | 1 %, **wrong sign** |
| `ds_fix` | **+247.8 µV/clock** | 12.8 %, **correct sign** |

and the drift becomes input-dependent (222 / 116 / 522 µV/clock at vin
0.20 / 0.6125 / 1.00) where as emitted it is 0.7 / 0.7 / 0.4 µV/clock — flat and
input-blind. The quantiser's input also gets 10× quieter (crossings per 120
clocks fall from ~980 to ~100). **The integrator starts integrating.**

**(2) The comparator's input is a floating node refreshed once per 64 clocks.**
`nqz` reaches the quantiser only through `caz` and has no DC path except the
auto-zero switches, which close only on the terminal count. Measured over
8–20 µs on `ds_fix` at vin 1.00: `nqz − vcm` has **mean +0.216 V**, range −0.142
to +0.551 V. The offset is roughly four times the full-scale signal the loop is
trying to resolve, so the decision is made by the drift, not by the input.

**(3) The quantiser therefore resolves one-sided and the output latch never
changes state.** Over the same interval: `nqstb` (the strobe) toggles 240 times,
`nqtail` 266, and `nq_n` 240 — the front end is being clocked and one side does
resolve every clock. But **`nq_p` never toggles** (min 0.887, max 1.302, mean
1.2000), so the SR latch input `nsrqb` is pinned at 0.0000 V and `bit_out` sits
at 1.2000 V with **0 transitions**. That is why the transfer is flat (§0.5).

None of the three is an amplifier problem, and none of the three is a conflict
between the declarations of §1.

**Also measured, and material:** the netlist's own conversion window is **64
clocks (6400 ns)**, not the 256 the deck header of `co_1.00.sp` assumes
(25 600 ns). The two are different builds; see §0.4.

### 0.4 Supply current, measured on this deck and not inherited

Conditions in full: netlist as emitted with only its `.lib` paths repointed;
`cornerMOSlv.lib mos_tt`, `cornerCAP.lib cap_typ`, `cornerRES.lib res_typ`;
vdd 1.2 V; vrefp/vrefn 1.1/0.1 V; **clk 100 ns = 10 MHz, `fclk_max`**; vin 0.7 V;
`tran 0.2n`, `uic`; window 16 000–20 000 ns = exactly 40 clock periods, after vcm
has settled. `i(v_vdd)` is trapezoidal-time-weighted over the non-uniform
`wrdata` timesteps (which span a 12× range here); a naive sample mean reads ~1.5 %
high and is not used.

| deck | Ivdd time-weighted | RMS | peak | vs 1.0 mA |
|---|---|---|---|---|
| as emitted | **0.4368 mA** | 0.4427 mA | 1.0929 mA | mean within, peak above |
| telescopic | **0.5394 mA** | 0.5442 mA | 1.1732 mA | mean within, peak above |

Two earlier lanes measured **1.69158 mA** on the deck they had, and §2.3 below
projects 1.78–1.79 mA from it. **Neither is reproduced here, and the decks are
not the same deck.** The bias leg measured here is
`xr_ib vdd nbias vss rppd w=0.5u l=33.427u`, whereas §2.3's own table gives
`r_ib_l_um` 15.089 at fclk 1 MHz and 1.509 at 10 MHz. A longer bias resistor is
a smaller reference current and so a smaller block current: the direction is
predicted and is the direction observed. Any current number for this block is
meaningless without the `r_ib` length beside it, and that is the substance of
the `bias_resistor_l_um` warning.

### 0.5 ENOB and OSR

**ENOB: NOT_MEASURED — and for the first time the transfer curve behind that
word has actually been run.** Three inputs spanning the declared reference, on
the emitted deck, density accumulated per real 64-clock conversion window:

| vin | normalised input | density, window 1 / 2 / 3 |
|---|---|---|
| 0.20 V | 0.1000 | 0.0100 / 0.0000 / 0.0000 |
| 0.6125 V | 0.5125 | 0.0097 / 0.0000 / 0.0000 |
| 1.00 V | 0.9000 | 0.0095 / 0.0000 / 0.0000 |

**The transfer is flat.** Density moves by 0.0005 across a 0.80 change of
normalised input, and in the wrong direction. There is no monotonic transfer to
fit, so there is no ENOB to report — not a low ENOB, no ENOB. It is not reported
as a default, an estimate, or a value inherited from a datasheet.

The blocking cause, named: **the 1-bit output never changes state.** Zero
transitions of `bit_out` over 120 clock periods at every one of the three inputs
— while over the same interval the quantiser's own input crosses its own
reference (`nqz − vcm`) about **980 times**. The comparator input swings across
the decision point continuously and the latch never resolves. So the loop is
open at the quantiser as well as leaky at the integrator, and no amplifier
change reaches either.

**OSR 256: NOT_MEASURED. The cost that stops it is not simulation time.** The
netlist on disk is the **OSR-64 build**: its sampling capacitors are
`l=13.8981 µm` against `ci = 629.081 µm`, i.e. `ci/cs = 45.26`, which is exactly
§2.1's OSR-64 coefficient (the OSR-256 coefficient is 181.1, which would need
`cs = 3.4737 µm`). Its window counter is a 6-stage ripple divider and measurably
divides by **64**. Producing OSR 256 therefore needs the sampling capacitors
re-derived AND two more counter stages — an A2/A3 re-emission, not a testbench
change. Running a 256-clock window against OSR-64 coefficients would not be
OSR 256 and is not reported here as such. What it costs is a re-emission of the
design; what it does NOT cost is hours of simulation (§1's note, corrected).

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
>
> **CORRECTED 2026-09-05:** the cost figure is wrong by roughly two orders of
> magnitude, and it is the reason the declared OSR went unmeasured. Measured on
> 8HD-6 with ngspice-47 (KLU solver, ~8 threads per run): a 20 000 ns transient
> of this netlist at `tran 0.2n` completes in **1 min 48 s** at host load 3.5.
> The declared-OSR run is 51 200 ns at the coarser `tran 0.5n`; the measured
> wall time for one such point at low load is given in section 5. It is
> minutes, not hours. OSR 256 did not have to be re-declared to 64 to be
> measured.

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

> **CORRECTED 2026-09-05 — the remedy this section prices does not buy what it
> is priced for.** The chain above assumes gm can be bought with tail current and
> that nothing else moves. Measured on the emitted amplifier, `.ac` at its
> in-circuit operating point, scaling the tail and the second-stage sink by their
> mirror ratios with device widths scaled alongside them (the charitable form of
> the change — the actual `r_ib` knob scales current WITHOUT widths and is worse):
>
> | tail scale | DC gain | GBW | mirror-side input device `Vds` |
> |---|---|---|---|
> | ×1 (as emitted) | **50.3 dB** | 18.7 MHz | 0.289 V — saturated |
> | ×2 | 40.1 dB | 35.0 MHz | |
> | ×5 (the 5.3× this section asks for) | **22.4 dB** | 30.9 MHz | **0.024 V — triode** |
> | ×10 | **19.3 dB** | 54.8 MHz | **0.014 V — triode** |
>
> Current buys bandwidth and **destroys gain**: 31 dB of it by ×10. The mechanism
> is visible in the operating point — `nd2` falls 0.555 → 0.201 → 0.135 V while
> `ntail` falls 0.267 → 0.176 → 0.121 V, so the mirror-side input device leaves
> saturation. So "gm must rise 5.3×, therefore current must rise 5.3×, therefore
> 1.79 mA" prices a change that, applied to this amplifier as drawn, arrives at an
> amplifier with **one eighth** the gain it started with. It is not a repair, and
> the 1.8×-the-ceiling figure is the price of something that does not work rather
> than the price of closing the constraint. Re-centring the operating point at the
> higher current is real sizing work and nobody has done it.
>
> Worth noting for whoever chases the provenance of the "integrator gain ≈ 13"
> figures: **×5 measures 22.4 dB = 13.2 V/V.** That is a *hypothesis* about where
> an unsourced number may have come from, not a finding — but a deck biased toward
> `fclk_max` is exactly the deck that would produce it, and it is the reason the
> `bias_resistor_l_um` reading matters.

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

> **CORRECTED 2026-09-05 — this correction was half right and its remedy was
> wrong.** Two separate things were conflated.
>
> **(a) Sampling at one fixed clock phase is the CORRECT instrument here, not an
> alias.** This is a switched-capacitor circuit: its state is by definition the
> value at one phase of the clock, and the within-phase excursion is the
> settling transient, not the state. Rejecting fixed-phase sampling as "an
> alias" threw away the only instrument that measures whether the integrator
> accumulates, and every round after it measured within-clock swing instead —
> which is why the non-accumulation was attributed first to settling and then to
> gain. Applied properly (`vint` sampled 2 ns before each rising edge, clocks
> 60–199) it gives the number in §0.3: **−20.3 µV/clock against the +1932 µV/clock
> the capacitor ratio demands**.
>
> **(b) Round 30's four samples really were aliased — but with the RESET, not
> with the clock.** They were 900 ns = 9 clock periods apart, and `nall` resets
> the integrator every **9.8 clock periods** on average (§0.3). Four samples
> spaced at very nearly the reset interval land at very nearly the same point
> after each reset, which is exactly why they agreed to the fourth decimal. The
> agreement was real evidence of a defect; it was evidence of the reset rate, and
> it was discarded.

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

---

## 5. Run record for the corrections above

Host 8HD-6 (192.168.1.108), 32 cores. Image
`ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…d0d01ff`, local image id
`sha256:b8b65ea3af6e…`, ngspice-47 (KLU), PDK `ihp-sg13g2`, all runs
`docker run --rm --network=none … --skip bash -c …`, never `docker exec`.

Model sections for every run: `cornerMOSlv.lib mos_tt`, `cornerCAP.lib cap_typ`,
`cornerRES.lib res_typ`. TT only — **the nine PVT corners are NOT_MEASURED**,
because the nominal corner does not converge and cornering a design that does not
convert would report nine copies of the same non-result.

### 5.1 Decks

| deck | what it is | devices |
|---|---|---|
| `ds_base` | `delta_sigma.sp` as emitted, `.lib` paths repointed, otherwise byte-identical | 222 |
| `ds_tel` | `ds_base` + telescopic-cascode first stage in both arms + shared cascode bias generator | 237 |
| `ds_idealrst` | `ds_base` with the five reset consumers driven from an ideal 64-clock reset; counter left in place | 222 |
| `ds_fix` | `ds_base` + the missing summing-node switches on `cs1`/`cf1`/`cs2`/`cf2` | 238 |

`ds_fix` differs from `ds_base` by exactly 4 changed capacitor lines and 16 added
switches; nothing else in the file differs.

### 5.2 Wall time — the figure §1's note got wrong

| run | step | wall time | host load |
|---|---|---|---|
| 20 000 ns transient | `tran 0.2n` | **1 min 48 s** | 3.5 |
| 20 000 ns transient | `tran 0.5n` | **63 s** | ~20 |
| one `.ac` + `.op` on one OTA | — | < 2 s | any |

A two-window run at the declared OSR is minutes, not the ~7 h §1 assumed. What
actually blocks OSR 256 is that the design on disk is the OSR-64 build (§0.5),
not the cost of simulating it.

### 5.3 Transfer, three decks, density per real 64-clock window

| deck | vin 0.20 | vin 0.6125 | vin 1.00 | `bit_out` transitions / 120 clocks |
|---|---|---|---|---|
| as emitted | 0.0100 / 0 / 0 | 0.0097 / 0 / 0 | 0.0095 / 0 / 0 | **0** |
| ideal reset | 0.0000 / 0 | 0.0000 / 0 | 0.0000 / 0 | **0** |
| `ds_fix` | 1.0000 ×3 | 1.0000 ×3 | 1.0000 ×3 | **0** |

Flat on all three. The output carries no information about the input on any of
them, which is the measured basis for the NOT_MEASURED in §0.5.

### 5.4 What this lane did NOT do

No push to main, no version bump, no PR, no landing. No gate baseline rewritten,
no assertion weakened, no threshold loosened, no exemption added. No layout,
GDS, or spare cell touched. No oracle, harness or golden output read — only the
design input (`L5_ANALOG_SPEC.txt` declarations, quoted in §1) and the design's
own emitted output. `ds_tel`, `ds_fix` and `ds_idealrst` are diagnostic decks
held outside the repository; **no netlist in the tree was modified**, because
authoring A3 output by hand would break its provenance to the emitter. What they
establish is where the emitter's output is wrong, which is the A2/A3 owner's
repair to make.
