---
name: hls-c2rtl
description: Translate C / C++ / SystemC algorithmic descriptions into synthesizable RTL via High-Level Synthesis. Use when the user says "HLS", "C to RTL", "C++ to Verilog", "Vitis HLS", "Catapult", "XLS", "algorithmic design", or provides a reference implementation in software and asks for hardware.
---

# HLS (C/C++ → RTL)

High-Level Synthesis is the entry point for DSP / AI accelerator / image-processing blocks where the algorithm is already written in C/C++. This skill guides the lowering from algorithm to RTL with pragmas / directives and hands off to `/rtl-review`.

## When to use

- Algorithmic block (filter, matrix multiply, feature extractor) exists in C/C++/SystemC
- Dataflow-heavy pipeline where manual RTL would be error-prone
- Design-space exploration across latency vs throughput vs area
- Target flow: Vitis HLS, Catapult HLS, Stratus HLS, XLS (open source, Google)

## Inputs

1. Source file(s) — C/C++/SystemC
2. Test vectors (golden I/O pairs)
3. Target: FPGA (bitstream) vs ASIC (Verilog netlist)
4. Constraints: target clock period, latency budget, throughput, resource limits
5. Tool choice

## Workflow

1. **Clean the source**: remove pointer chasing, dynamic allocation, recursion — HLS only digests statically-bounded C
2. **Interface synthesis**: decide on AXI-Stream, AXI-Lite, memory-mapped BRAM, or wire handshake for each argument
3. **Apply pragmas / directives**:
   - `#pragma HLS PIPELINE II=1` for loops
   - `#pragma HLS UNROLL factor=N`
   - `#pragma HLS DATAFLOW` for stream pipelines
   - `#pragma HLS ARRAY_PARTITION` for memory banks
4. **Co-simulate** C vs generated RTL using the test vectors
5. **Emit RTL** and hand off to `/rtl-review` and `/testbench-gen`
6. **Report PPA** — estimated from HLS tool's synthesis report

## Output format

- `hls/<module>.cpp` — cleaned, annotated source
- `hls/<module>.tcl` — HLS tool run script
- `hls/<module>_rpt.md` — directive log + PPA estimate + handoff notes

## Tool prerequisites

Open source: XLS (https://github.com/google/xls). Commercial: Vitis HLS, Catapult, Stratus.

## Technical basis

HLS is a mature commercial flow. XLS is Google's open-source DSL-based HLS. Key principle: the algorithm must be rewritten with hardware-friendly idioms (bounded loops, no dynamic memory, explicit streaming) before HLS can produce good QoR.

## Handoff

- Generated RTL → `/rtl-review` then `/testbench-gen`
- Golden C model → reuse as reference in `/testbench-gen`
- PPA → `/ppa-predict` for cross-check

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/hls-c2rtl/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
