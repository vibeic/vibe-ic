# L1 — Product Metadata

- **Project name:** caravel_user_project (user_proj_example)
- **Class:** SoC user-project integration for the eFabless/ChipFoundry Caravel harness
- **Target PDK:** SKY130A (open-source sky130 130 nm)
- **Shuttle:** ChipFoundry / eFabless chipignite open MPW shuttle
- **Top deliverable:** `user_project_wrapper` hardened GDS, mpw_precheck-clean, ready for Caravel harness integration
- **Source:** https://github.com/chipfoundry/caravel_user_project (Apache-2.0)
- **Function:** A trivially simple example user project — a programmable up-counter, controllable and observable from the Caravel management SoC (RISC-V) over the Wishbone bus, the 128-bit logic-analyzer probe bus, and the user GPIO pads.
- **Power domains:** vccd1/vssd1 (user area 1, 1.8 V digital).
- **License:** Apache-2.0.

The counter is the *design under test*; the wrapper integration onto the Caravel
harness (fixed die area, power straps, pin order) is the SoC-grade portion of the
flow that the benchmark exercises end-to-end (RTL → OpenLane PnR → GDS → precheck).
