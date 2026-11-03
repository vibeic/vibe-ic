# Step 49 Analog characterized views — 2026-11-04

LDO: 405/405 native no-load operating points and 405/405 OpenSTA power
comparisons completed. DSM: three historical r9 timing models from existing
extracted EM waveforms; the new 135-point matrix is incomplete and on hold.
The leader reported pre-layout DSM ENOB 9.09 against 14, with the cause open and
the netlist subject to change. No new long DSM simulations are authorized until
the leader clears that hold. These DSM models are historical data, not the
approved timing views of a replacement netlist.

This directory delivers measured data and thin reproduction scripts. It does
not change the automatic hardmacro producer, whose loaded LDO input power was
rejected as leakage. The producer still needs that semantic correction. The
measured LDO libraries here use the owner's explicit no-load condition.

## LDO delivery

`ldo/ldo.{lib,lef,v,gds}` is the nominal physical kit, with the corrected
TT/27 °C/1.8 V/VREF=1.0 V no-load Liberty. GDS is
`d6c3da76e759dc2b567ba5603a6e480325892e2a608a8558354921255292d1c9`,
the main rebuild previously compared XOR 0 with the accepted re-freeze.
The signed R5h addendum is
`63839f42ff128a7566f71a9a6254bc246cfbdb6774e3f010b6860654143ab9d2`.

`ldo/measurements.csv` contains all 405 measured scalars. Coverage is five
existing RC styles × TT/SS/FF × −40/27/125 °C × VIN 1.6/1.8/2.0 V ×
VREF 0.99/1.0/1.01 V. Each point has no external vout load; the extracted
divider, bias network and parasitics remain. ngspice directly prints
`iq_a=-i(VDD)` and `power_w=v(vdd)*iq_a`. No 0.5 mA loaded input power is used.

| Native quantity | Measured range | Original limit |
| --- | --- | --- |
| Iq | 30.75744–47.53473 µA | ≤50 µA |
| Vout | 1.187202–1.216568 V | 1.1–1.3 V |
| No-load input power | 49.21190–95.06947 µW | measured leakage model |

Nominal Iq is 38.99316 µA, power 70.18769 µW and Vout 1.200338 V.
`leakage_power_unit` is library-level `1uW`. OpenSTA actually reads each
library, links one LDO instance and reports the same macro leakage within its
printing precision. The nominal native report is `ldo/sta-nominal.log`.

`ldo/selected.csv` maps 135 RC/process/temperature/VIN combinations to
`ldo/selected/*/ldo.lib`. Each is an unchanged copy of the measured library
with the largest power among that combination's three VREF points; all 135
selected VREF values happen to be 1.01 V. This selection does not replace the
405 measurements.

`ldo/native-no-load.tar.gz` contains all 405 original decks, ngspice logs,
Liberty files, result records and OpenSTA logs, plus warning probes and the
original power comparison. Its aggregate `results.json` uses relative paths
for portable OpenSTA reads. Per-corner original records retain their original
paths. PDK model files and extracted device netlists are not bundled.
Three resistor-model warnings occurred during Newton/gmin iterations; final
mapped-node probes reproduced the same operating points without a final
model-range violation. The archive retains those logs and the detailed report.

## Historical DSM models

`dsm-prior-r9/{tt27,ff125,ffm40}` contains the three measured Liberty models,
threshold samples and native OpenSTA timing reports. `measurements.json`
retains the measured crossings. The underlying r9 GDS is
`2344ffd831d8a400d6df8232e698c9255f299c6547954c611529f501be2ed27f`.
These waveforms used the older unsimplified extracted network, not the five
RC netlists intended for the new matrix.

| Historical corner | clk→bit_out rise | clk→bit_out fall |
| --- | ---: | ---: |
| TT / 27 °C / 1.2 V | 12.72679523 ns | 11.87750268 ns |
| FF / 125 °C / 1.3 V | 12.70434896 ns | 11.78807828 ns |
| FF / −40 °C / 1.3 V | 8.40156932 ns | 7.87929738 ns |

Both output polarities follow the rising clock edge. Each delay is an actual
output 50% crossing minus the preceding measured clock 50% rising crossing.
The scalar model uses the largest of five samples per polarity at that corner.
OpenSTA reports the measured rising-edge clk→bit_out arc. No declared timing
contract supplies a delay.

Conditions are 1 MHz clock, 1 ns source edge (0.6 ns at 20–80%), 6–16 µs
measurement window and zero external output load. Extracted internal fanout
remains. These scalar points do not characterize other slew/load conditions
or the unmeasured corners. DSM leakage and input capacitance are not invented.

## Reproduction

Use the pinned image
`ghcr.io/vibeic/vibeic-eda@sha256:d3159f09be84ee94a315f83523952afe55e93f48d8eec638e48ec265ed3f2508`
with `--rm --network none`, `PDK=ihp-sg13g2`, and mounts preserving the case's
model paths. It contains ngspice 47 and OpenSTA 3.1.0. Keep total lane usage
within eight CPUs and 32 GiB. The scripts default to two native processes. The LDO runner copies the PDK
`.spiceinit` into its own output working directory to load the native OSDI
models; `--spiceinit` can supply that file explicitly. It does not modify the
case or the user's home directory.
Run the following inside that image, with this directory as the working
directory and an empty writable output directory under `/mnt/ssd2/tmp`.

To read the existing 405 libraries again, without rerunning analog simulation:

```bash
mkdir -p /mnt/ssd2/tmp/a4-ldo-read
tar -xzf ldo/native-no-load.tar.gz -C /mnt/ssd2/tmp/a4-ldo-read
python3 read_ldo_liberties.py \
  --results /mnt/ssd2/tmp/a4-ldo-read/results.json \
  --out /mnt/ssd2/tmp/a4-ldo-read/sta --workers 2
```

To reproduce the native LDO OP matrix using the existing five extracted
netlists, supply the case containing `input/pdk/models`, the signed four-port
`phase3/analog/ldo/ldo.sp`, and
`phase3/librelane/analog/ldo/native_analog/pex_*.bound.spice`:

```bash
python3 ldo_no_load.py --case /path/to/ldo-case \
  --out /mnt/ssd2/tmp/a4-ldo-new --workers 2
```

`--nominal` runs one point. Existing completed records are collected instead
of rerun; `--collect-only` requires them to exist. The script uses the plugin's
existing one-to-one extracted-port wrapper from this repository. It preserves
the previously authorized `.nodeset v(vout)=1.2` initial guess and native
solver settings. This is a bounded runner for these signed LDO ports.

To regenerate and read only the three already measured DSM models, without
launching ngspice:

```bash
python3 emit_dsm_liberty.py --results dsm-prior-r9/measurements.json \
  --out /mnt/ssd2/tmp/a4-dsm-prior-read --check-sta
```

Original local evidence and unfinished pilots remain under
`/mnt/ssd2/codex_tasks/out/a4pilot/cx-a4/`. They are not counted as completed
new DSM matrix points. Full lane status is in
`/mnt/ssd2/codex_tasks/out/a4pilot/RESULT.md`.

`validation.json` records checks on this packaged copy: 405 native portable
STA reads with matching power, three regenerated historical DSM models with
matching native STA delays and unchanged Liberty bytes, and a native nominal
run of the parameterized LDO script with exactly the original values and
Liberty bytes. The first nominal reproduction lacked the PDK OSDI startup
file and failed; its logs remain in the local evidence. Loading the PDK
startup file in the private output directory fixed that reproduction.
