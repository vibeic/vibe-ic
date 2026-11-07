# PWM4 design input

`design_description.md` defines the chip interface and PWM behaviour. `L7_TEST_DEBUG.md` supplies the verification scenarios and `L9_PHYSICAL_DESIGN.md` declares the external input transition in the existing constraint syntax. `rtl/chip_top.sv` implements the synchronous SPI receiver. `verification/expert_reference_tb.py` checks top-level behaviour against the documents.

Stage the documents under a project's `input/docs/` and copy `design_description.md` to `input/phase1_prompt.md`. Put the RTL under `phase2/stage1/rtl/` and the reference bench at `phase2/stage1/sim_professional/chip_top/expert_reference_tb.py`. Preserve the owner's DIE route declaration in `input/step_0_5ic_answers.json`.

Run the normal entry with the stock `ghcr.io/vibeic/vibeic-eda:0.4.73` image:

```sh
python3 programs/vibe_ic_one_shot_runner.py "$project" --route ic --pdk gf180mcuD --from requirements_and_delivery_route
```

This regenerates Phase 1 from the design documents and reuses the authored RTL and reference bench. Native reports determine each result against its existing limit. Full-chain results belong in the project reports, outside this source tree.
