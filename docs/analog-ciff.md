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
existing comparator through a sampling/holding transmission gate; its
common positive attenuation does not change the ideal one-bit decision.
D=0 strobes in the sampling phase. D=1 holds the sum for the transfer-phase
decision, adds the k0 reference branch, and delays summer reset until after
the comparator strobe. The hold capacitor is reset each cycle to prevent
previous-sample charge from contaminating the sum.

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
