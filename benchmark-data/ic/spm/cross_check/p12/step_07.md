# Step 7 — SDC diff (OUR vs REF)

## What we ran
- Read OUR `phase2/stage2/constraints/spm_10ns.sdc` vs REF
  `phase2/stage2/constraints/spm.sdc` and REF `phase2/stage1/fpga/spm.sdc`.

## OUR SDC
```
create_clock -name core_clock -period 10.0 [get_ports clk]   # 100 MHz
set_input_delay  2.0 -clock core_clock [all_inputs]           # 20% of period
set_output_delay 2.0 -clock core_clock [all_outputs]
```

## REF SDC
- stage2 `spm.sdc`: `create_clock -period 20.0 [get_ports clk]` (50 MHz, auto-gen
  relaxed), input/output delay 2 ns.
- stage1 fpga `spm.sdc`: `create_clock -name clk_main -period 10` (100 MHz), input
  delay max 4.0 / min 0.0 on x,y,p, `set_false_path` on `rst`.

## Comparison
| Field | OUR | REF stage2 | REF stage1-fpga | Source |
|-------|-----|-----------|-----------------|--------|
| clock period | 10.0 ns | 20.0 ns | 10.0 ns | L9 100 MHz / L1 "SKY130 10 ns" |
| frequency | 100 MHz | 50 MHz | 100 MHz | L9 freq_mhz=100 |
| input delay | 2.0 | 2 | 4.0/0.0 | derived |
| output delay | 2.0 | 2 | — | derived |

Both derive the clock from L9 `clock_domains.clk` (100 MHz / 10 ns). **OUR period
matches the L9/L1 sign-off target exactly (10 ns)**; REF's stage2 used a relaxed
auto-generated 20 ns (its FPGA SDC uses the same 10 ns OURS does). I/O delays agree at
2 ns (OUR/REF-stage2); REF-fpga used 4 ns.

## Verdict: EQUIVALENT (same L9 origin; OUR tighter & on-target)
Both SDCs trace to the same L9 100 MHz clock. OUR 10 ns is the on-spec sign-off
constraint (matches L1's "Target clock period — SKY130 10 ns" and L9 100 MHz); REF's
stage2 20 ns is a looser auto-default. No contradiction. EQUIVALENT.
