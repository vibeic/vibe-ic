# L2 FRS

> Converged L-doc (program-track + IC-Expert AI-track). doc_class: `frs` | ic_name: `edge_llm_matmul_accel`

- **doc_class:** frs
- **fmax_mhz:** 50
- **functional_requirements:**
  - **FR1**
    - **id:** FR1
    - **text:** Compute C = A x B for INT4 signed operands, tiled 16x16, arbitrary M,K,N via software tiling.
  - **FR2**
    - **id:** FR2
    - **text:** Accumulate products in a 32-bit signed accumulator (no overflow for K up to ~1e3+).
  - **FR3**
    - **id:** FR3
    - **text:** Apply one per-output-channel scale factor (dequant/requant) -> 8-bit signed output.
  - **FR4**
    - **id:** FR4
    - **text:** Host loads weights+activations into on-chip SRAM over a memory-mapped bus, writes START, reads DONE, reads results.
  - **FR5**
    - **id:** FR5
    - **text:** Softmax / normalization are OUT of scope (host CPU).
  - **FR6**
    - **id:** FR6
    - **text:** Hard-wired datapath; only tile dimensions M/K/N, scale, start/status are register-configurable.
  - **FR7**
    - **id:** FR7
    - **text:** Expose ready/done status pins + done interrupt.
- **non_functional:**
  - **NFR1**
    - **id:** NFR1
    - **text:** Active power < 0.5 W; far more efficient per-MAC than host CPU.
  - **NFR2**
    - **id:** NFR2
    - **text:** Open free PDK (sky130), chipIgnite-class die, per-chip cost low hundreds USD.
  - **NFR3**
    - **id:** NFR3
    - **text:** Clock 50 MHz; latency 'sub-second for common ops' via 256-wide parallelism.
- **protocol_overview:**
  - **bus:** Wishbone B4 slave
  - **half_duplex:** False
- **ic_name:** edge_llm_matmul_accel
- **frs_sections:**
  - **[0]**
    - **section:** h2
    - **title:** The Problem
    - **content:** I run language models on a little box sitting on my desk—just a regular machine, nothing fancy. The models work, but the heavy math part (all those big multiply operations when the model is doing its thinking) is slow and it drains a lot of power. It's fast enough to be usable, but not fast enough, and the power draw is annoying.

I've heard about those 48-hour chip demos that people built on an open manufacturing process, and I thought—why not a small custom chip that just handles that one part really well? Just the multiply math. I don't need it to do everything, just to be really good at that one thing so my local machine can stay snappy and not cook itself.
    - **evidence:** input/docs/00_user_request.md
    - **heading_shape:** md_atx
  - **[1]**
    - **section:** h2
    - **title:** What I Want
    - **content:** A small, low-power chip that lives next to my CPU as a helper. It should work with tiny 4-bit numbers (I know that saves memory and power and we don't really need huge precision for this kind of work). It should be built on an old, free, open manufacturing process—something boring and standard, not exotic. The size and ambition should be about like those 48-hour demo chips I read about. Not crazy high speed, just practical.

The workflow I imagine is simple: load the model's weights and input numbers into the chip's on-chip memory, tell it "go", it crunches the numbers, I read the results back into my machine. Done.

That's it. Speed up the multiply math, low power, open process, small enough to be practical and cheap.
    - **evidence:** input/docs/00_user_request.md
    - **heading_shape:** md_atx
- **no_frs_sections_in_input:** False
- **no_protocol_overview_in_input:** True
- **no_fmax_mhz_in_input:** True
- **extraction_evidence:**
  - **input/docs/00_user_request.md:**
    - **[0]**
      - **literal:** h2 The Problem
      - **label:** FRS section
    - **[1]**
      - **literal:** h2 What I Want
      - **label:** FRS section
