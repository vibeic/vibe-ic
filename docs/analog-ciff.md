# Incremental CIFF in the A2/A3 producers

The ordinary `delta_sigma` block selects CIFF with the numeric A1 spec row
`ciff=1`. An absent row or `ciff=0` keeps the existing CIFB producer.
Rows originate in `L5_ADI_SPEC.json:analog_blocks[].spec.specs[]`; A1 binds
them to `phase3/analog/<block>/spec.json`. Each row has `name`, numeric
`target`, and `unit`. CIFF configuration rows are dimensionless, except
`ciff_summer_cap_ff`, whose unit is `fF`.

| Row | Meaning |
| --- | --- |
| `order` | Integrator count, 1 through 3 |
| `ntf_hinf` | Required peak NTF gain, strictly between 1 and `2**order` |
| `feedback_delay` | D=0 or D=1; default 0 |
| `a1` … `aL` | Positive integrator gains Cs/Ci; absent gains use unit normalization |
| `c0` | Input feed-forward weight; default 1 |
| `c1` … `cL` | Optional complete explicit feed-forward vector, checked against the synthesized NTF |
| `k0` | Optional explicit compensation weight, checked against the synthesis |
| `ntf_optimize_zeros` | 0: DC zeros; 1: in-band Legendre zeros; default 0 |
| `ntf_zero1_real/imag` … `ntf_zeroL_real/imag` | Optional complete explicit zero set; imaginary parts default to zero |
| `ntf_pole1_real/imag` … `ntf_poleL_real/imag` | Optional complete explicit pole set, stable and within the peak-gain bound |
| `ciff_summer_cap_ff` | Positive summer capacitor unit; otherwise the noise-budget sampling capacitance |
| `ciff_dac_ratio` | DAC full scale / reference scale; default 1; equals Cf1/Cs1 for synthesized CIFF |
| `designed_coefficients` | 1: accept complete, explicit a/b/c vectors instead of NTF synthesis; default 0 |
| `b1` … `bL` | Designed DAC injection gains; zero removes that stage's DAC; CIFF requires b2…bL=0 |
| `quantizer_levels` | 2 (one bit); other levels are refused |
| `startup_reset` | 1: RC + Schmitt startup reset of the counter and all integrators; default 0 |
| `startup_reset_tau_ns` | Optional RC time constant; default two declared clock periods |
| `startup_reset_cap_ff` | Optional RC capacitance; otherwise 40 noise-budget sampling capacitors |

For `designed_coefficients=1`, `ciff=0` selects designed CIFB and `ciff=1`
selects designed CIFF. Supply all a/b/c entries, including zeros. Signed
nonzero a values and signed b/c values are supported by switched-plate
orientation and reference selection. These coefficients are authoritative;
NTF synthesis rows do not replace or rescale them. Linear closed-loop poles
are reported without claiming nonlinear stability. A nonzero k0 requires D=1.
The physical ratio in a designed loop is Cf_i/Ci_i = abs(b_i) times
`ciff_dac_ratio`; the k0 capacitor uses the same reference-scale conversion.

The existing supply, reference, clock/range, OSR, resolution and measured
PDK prerequisites still apply. The conversion counter rounds OSR up to a
power of two and resets all integrators every window. State scaling is a
sizing input: an NTF alone does not uniquely determine `a_i`. A2 computes
`c_i` for those gains; it does not perform native swing optimization.

Synthesis solves the Butterworth high-pass cutoff for the requested
out-of-band gain and checks the full unit-circle peak. Optional optimized
zeros use the Legendre solution for integrated in-band noise. Realization
matches `1/NTF-1` in a controllable integrator basis. Its recurrence is:

```
x[n+1] = A*x[n] + b*(u[n] - v[n-D])
y[n]   = c0*u[n] + c*x[n] - k0*v[n-1]
```

With DC zeros, A is the integrator chain and `k_i=c_i*prod(a1…ai)`.
Non-DC zeros add signed SC state-feedback capacitors into stage 1.
These use the same OTA, capacitor and CMOS switch roles as the existing
library. Only stage 1 samples the one-bit DAC. The passive summer feeds the
existing comparator. D=0 samples the settled states and resets AZ during
integration (phi2), then returns the summer bottom plates to VCM in phi1.
The comparator inputs are exchanged to cancel that summer inversion. Its
two-inverter strobe source is `clk`, the native rephased arrangement: the
declared latch event is integration end, before the next sampling phase;
the latched decision drives DAC acquisition in phi1 and transfer in phi2.
D=1 retains the native `nclkb` strobe and normal comparator polarity, holds
the sum for the transfer-phase decision, adds the k0 reference branch, and
delays summer reset until after the comparator strobe. Its hold capacitor
is reset each cycle to prevent previous-sample charge from contaminating
the sum.

A2 emits a flat topology IR and the complete synthesis record under `ciff`.
A3 uses its existing flat renderer and PDK geometry checks; it has no
independent per-converter template. Unrealisable capacitor dimensions are
reported as gaps, including very small optimized-zero correction caps.

The optional POR uses physical resistor/capacitor roles and a six-transistor
Schmitt inverter. It presets both storage nodes of each counter bit and ORs
startup reset with the existing per-window integrator reset. A latch permits
counter-clock release only during the source clock's low phase. Disabled,
the option introduces no devices. Reset timing still needs validation under
the target PDK's supply ramps and thresholds.

The consumer contract is `topology.json.loop_declaration` (schema 1), for
legacy CIFB as well as the new families:

- `family`, `order`, `a`, `b`, `c`, `c0`, `D`, `k0`;
- `A`, `input_vector`, `feedback_vector`, `state_nets` describe
  `x[n+1] = A*x[n] + input_vector*u[n] + feedback_vector*v[n-D]`;
- `dac_stages` lists one-based stage numbers; `quantizer_levels` is 2;
- `paths` names each input, cascade, DAC, feed-forward and zero-shaping path,
  its signed gain and capacitor base name; DAC paths include
  `destination_stage` and `delay_clocks`;
- `k0_path` is null or the explicit latch-to-summer path with
  `delay_clocks=1`; `quantizer_input_net` and `quantizer_strobe_device`
  identify the comparator boundary;
- `normalization` defines the input/state voltage scale and DAC output levels.
- `timing` is derived from D and the declared `loop_timing` template table:
  `latch_event`, `strobe_source`, `comparator_polarity`, summer sample/reset/
  return phases, DAC sample/transfer phases, `nonoverlap_parameters` and
  `latch_delay_cap_ff`.

Capacitor base names resolve through the existing
`_provenance.layout_maxima.capacitor_arrays` if the PDK requires unit arrays.
`startup_reset` separately records POR/reset/clock/release nets, RC time
constant, reset counter state and the circuits it clears. Net names follow
the ordinary interface port renaming. `ciff` retains the full NTF synthesis
record for CIFF; consumers should use `loop_declaration` for either family.

Scope: this implements single-bit CIFF A2/A3 production. The existing
distributed-feedback incremental decoder and loop probe are still CIFB;
CIFF needs a separate matched decoder for conversion/ENOB grading. The
generated transistor circuit has no native timing, swing, offset, noise or
PVT certification from these coefficient/structural tests. Orders above 3
and multi-bit quantizers are outside this family.

Method references: [SciPy Butterworth design](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html),
[Schreier toolbox Python realization](https://docs.python-deltasigma.io/en/latest/_modules/deltasigma/_realizeNTF.html).

## Declared OTA1 options (no sizing)

`ota1_folded_cascode=1` replaces only OTA1 with the existing folded-current
cell graph, removes its single-ended second stage, and exposes the folded
high-gain node. Its input pair is interchanged to preserve negative gain at
the SC summing node. Cc1 remains parameterized and becomes output-to-VCM
compensation. The new devices require explicit `w`/`l` entries in
`sizing_inputs.json.device_parameters`; their names have the `ota1_` prefix
on the existing folded cell's names. Missing geometry produces a gap, never
an automatically sized transistor. OTA2/OTA3 retain their existing cells.

`ota1_chopper=1` enables input-gate chopping and differential-current
demodulation inside OTA1. The folded cell demodulates at the folding cascode
sources. The two-stage cell retains its single-ended second stage and uses
common-gate current conveyors, before its existing PMOS mirror, to provide
low-impedance demodulation nodes. Conveyor geometry starts from the input
pair's reference geometry; the real bias divider resistors
`r_ota1_ch_top` / `r_ota1_ch_bottom` require explicit geometry input.
No differential output or additional common-mode feedback is introduced.

Chopping requires these numeric A1 rows:

- `ota1_chop_ratio`: a power of two from 2 through 65536;
- `ota1_chop_sc_phase`: 1 (sampling phase) or 2 (transfer phase);
- `ota1_chop_polarity`: 0 or 1, optional, default 0;
- `ota1_chop_nmos_w_um`, `ota1_chop_pmos_w_um`, `ota1_chop_l_um`: explicit
  switch dimensions, with no synthesized defaults.

The divider reuses the existing static TG counter cells, driven from the
selected non-overlap SC phase. Input and current demodulators share the
resulting non-overlap positive/negative phases. `ota1_cc_ff` optionally binds
Cc1; all other Cs/Cf/Ci/summer/Cc expressions are retained. Both topology
selectors default to zero; with fixed provenance, the default A3 circuit
deck is byte-identical. Native chopper noise, clock feedthrough, headroom,
GBW/SR and folding bias remain unqualified. CDS is not added in this change.

`topology.json.ota1_options` records the selected cell, compensation,
explicit geometry devices, and (when enabled) `chopper.{ratio,source_phase,
polarity,clock_net,positive_phase,negative_phase,switch_geometry_um,
input_nodes,demodulation_nodes,location,output_interface,second_stage_retained}`.

Non-overlap gate parameters remain selectable through
`sc_nonoverlap_nmos_w_um`, `sc_nonoverlap_pmos_w_um`, `sc_nonoverlap_l_um`.
`quantizer_latch_delay_cap_ff` optionally binds the physical strobe-delay
capacitor. Absent these rows, existing reference geometry/capacitance is
retained. No ns delay, slack, GBW or slew target is tuned or inferred by the
template. The phase/polarity contract follows the native rephased bench;
complete closed-loop native qualification remains separate.

## Shared stage-1 input/DAC and three-location chopping

`shared_input_dac=1` selects shared charge transfer for positive stage-1
CIFF with D=0. In phi1, Cs1 samples Vin. In phi2, its bottom plate connects
to `ndacb`: decision one selects Vref+, decision zero selects Vref-.
The DAC-only Cf1 samples the opposite reference at `ndac` in phi1 and
returns to VCM in phi2. Thus the total feedback capacitance is Cs1+Cf1.
The existing `ciff_dac_ratio` remains the total DAC/input scale: Cf1 becomes
`(total_ratio-1)*Cs1`. Total ratio one omits the unnecessary Cf1 branch.
The normalized a/b/c coefficients and decoder scale remain unchanged.
The option defaults to zero; D=1 sharing is refused because its reference
would need an additional hold path. The separate-DAC alternative remains
available with the existing parameters.

`loop_declaration.sharing` declares enabled/stage/input_capacitor/
dac_only_capacitor/total_dac_over_input_cap/dac_only_over_input_cap/
shared_reference_net/dac_only_reference_net/input_sample_phase/
reference_transfer_phase/decision_one_reference/decision_zero_reference/
shared_feedback_gain/dac_only_feedback_gain. `paths` splits the logical
DAC contribution into `dac_shared` (Cs1) and `dac` (Cf1); their signed gains
sum to the existing feedback vector. `dac_stages` still lists only stage 1.

Absolute capacitor inputs are `cs1_ff`..`csL_ff`, `ci1_ff`..`ciL_ff`,
`cf1_ff`..`cfL_ff`, `cc1_ff`..`ccL_ff`, `cff0_ff`..`cffL_ff`, `cffk0_ff`.
Binding Cs scales its Ci/Cf/Cc partners from the declared coefficients.
Binding a complete inconsistent set fails instead of changing the loop.
Individual summer values must agree with a common unit and c0/c_i/k0.
Stages without explicit inputs retain their existing expressions.

For the folded cell, `ota1_chop_stages=3` is the default when chopping is
enabled: CH1 interchanges the input pair; CH2 commutates currents at the
folding cascode sources; CH3 interchanges the physical NMOS mirror devices
at the load-cascode sources. The three-location option requires ratio=2
and SC phase=1 (also its declared defaults). It presets the divider on
every conversion reset, updates at the start of phi1 and holds throughout
phi2. Its master uses phi2 and its slave uses gated phi1, with the existing
SC non-overlap preventing a transparent path through both latches. The
chop phase generator's internal nodes are isolated from the SC generator.
`ota1_chop_polarity` selects the repeatable first valid chop phase.
Legacy two-location chopping is selectable with `ota1_chop_stages=2`.

`ota1_folded_remove_cc=1` removes OTA1's obsolete Miller Cc/RZ from the
single-stage cell. It defaults to zero to retain the earlier optional
output-compensation connection; no capacitor or transistor is sized here.
`ota1_options.chopper` adds `switch_locations` (CH1/CH2/CH3), `stages`,
`update_event`, `static_phase`, `reset_net`, `divider_clock_net` and
`conversion_start_phase`. Generic-MOS transient tests cover the control
clock frequency and reset phase; the consumer must validate the complete
analog graph and reference settling with native process models.
