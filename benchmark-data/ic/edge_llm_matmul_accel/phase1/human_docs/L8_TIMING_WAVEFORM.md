# L8 TIMING WAVEFORM

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `timing_waveform` | ic_name: `edge_llm_matmul_accel`

- **doc_class:** timing_waveform
- **timing_constants:**
  - **clk_period_ns**
    - **name:** clk_period_ns
    - **value:** 20
    - **note:** 50 MHz
  - **tile_latency_cycles**
    - **name:** tile_latency_cycles
    - **value:** K + ARRAY_ROWS + ARRAY_COLS (systolic fill+drain)
  - **requant_cycles**
    - **name:** requant_cycles
    - **value:** 1
- **waveforms:**
  - **[0]**
    - **seq:** START -> BUSY -> (K+~32 cyc) -> DONE + irq_o pulse
- **ic_name:** edge_llm_matmul_accel
- **extraction_evidence:** _(empty)_
