---
name: spec-to-rtl
description: "MANDATORY entry point when `phase2_one_shot_runner.step_rtl_gen` WAIVES with `fallback_skill='spec-to-rtl'`. This is invoked for every IC class with `rtl_gen=null` in `ic_class_registry.json` (currently: digital_arithmetic_primitive, digital_cmd_driven, bare_fpga, processor_cpu, unknown_protocol_class). The runner has already (1) ingested the prompt into L1-L23, (2) detected the IC class, (3) set the expected RTL path. This skill authors synthesizable RTL into the runner's expected path so the runner's downstream gates (chip_top auto-emit, rtl_hygiene_lint --fix, eda_lint, eda_synth, eco_loop, spec_conformance_check, full_stack_tb_gen) can fire on it. Triggered automatically by the runner's WAIVE message; also fires on phrases like 'AI invokes spec-to-rtl', 'runner WAIVED rtl_gen', 'spec-to-rtl handoff'. THIS IS THE RUNNER'S INTENDED PATH — NOT BYPASS. Bypass means authoring with MCP outside the runner's pipeline (what the 2026-05-28 wrong-shape RTLLM 37/50 did)."
---

# spec-to-rtl — the runner-orchestrated AI authoring step

## What this skill IS

The deterministic authoring path for IC classes WITHOUT a registered `rtl_gen`
generator. Spec → RTL fundamentally requires a language model (open-benchmark-
methodology skill § 1); this skill is **how the runner delegates that step to
the AI inside its own pipeline**, so the surrounding gates still fire.

## Invocation contract

When `phase2_one_shot_runner.step_rtl_gen` WAIVES with the message:

> *IC class 'XXX' registered but rtl_gen=null. Recommended action: AI invokes
> skill `spec-to-rtl`.*

…the AI MUST:

1. **Read the L docs the runner just emitted**:
   - `<project>/phase1/generated_docs/L1_*.json` (product metadata, IC name, target clock)
   - `<project>/phase1/generated_docs/L2_*.json` (functional spec)
   - `<project>/phase1/generated_docs/L3_*.json` (external interface — ports)
   - `<project>/phase1/generated_docs/L7_*.json` (verification plan / truth-tables)
   - `<project>/phase1/generated_docs/L9_*.json` (constraints, top_module name, top_ports)
   - For Path-A (NL prompt) projects, ALSO read the original prompt at
     `<project>/input/phase1_prompt.md` or `<project>/input/docs/*.md`. The
     prompt typically has clearer port-name and behavioral details than the
     auto-extracted L docs.
2. **Respect the blind rule**: read ONLY the L docs + original prompt. NEVER
   read `testbench.v`, `verified_*.v`, hidden cocotb harness, or any reference
   RTL the upstream benchmark ships. This is enforced by the open-benchmark-
   methodology skill's absolute-blindness rule and applies inside this skill.
3. **Determine the module name**:
   - If `L9_INTEGRATION_SPEC.json` declares `top_module` (e.g. `"chip_top"`)
     AND that matches the description's stated module name, use that.
   - Otherwise (common for RTLLM-class designs): use the **exact name the
     prompt/description states** ("Module name: <name>"). The hidden TB
     instantiates by that name. The runner's chip_top auto-emit (v0.1.32+)
     will wrap your module if L9.top_module differs.
4. **Author synthesizable RTL** at the runner's expected path:
   ```
   <project>/phase2/stage1/rtl/<module_name>.v   (or .sv)
   ```
   - Verilog-2001 or SystemVerilog; synthesizable for yosys + gf180/sky130
   - EXACT port list per L3 / L9: names, directions, widths (`[3:0]` ⇒ 4 bits)
   - Implement the behavior the description states. Algorithm choices the
     description doesn't pin down are R3-permitted design freedom.
5. **Apply known hygiene proactively** (so the runner's gates don't have to
   work around them):
   - Combinational `always @(*)` blocks: every branch assigns every output
     OR a `default` covers them (no inferred latches).
   - Reset-less registered outputs: add `initial <reg> = 0;` in a SEPARATE
     `initial` block (NOT inline on `output reg q = 0;`) so the runner's
     `rtl_hygiene_lint --fix` doesn't have to repair PROCASSINIT.
   - `case`: include `default`; rewrite overlapping `casez` priority encoders
     as `if/else-if`.
6. **Self-check with MCP** (encouraged, not strictly required — the runner
   will re-run these):
   - `eda_lint`: 0 errors.
   - `eda_synth` (gf180): clean, no inferred latches except intended
     `always_latch` transparent latches.
7. **Tell the orchestrator you're done**. The caller will re-invoke
   `vibe_ic_one_shot_runner.py` so the runner detects the RTL at the
   expected path, skips `step_rtl_gen`, and continues with: chip_top
   wrapper auto-emit (v0.1.32+), `rtl_hygiene_lint --fix`, `eda_lint`,
   `eda_synth`, `spec_conformance_check`, `eco_loop` (up to 3 retries
   on `reference_tb` FAIL), `full_stack_tb_gen`, `final_audit`.

## What this skill IS NOT

- **NOT a fully-deterministic program**. Spec→Verilog needs an LLM; this
  skill is *the AI's role inside the runner pipeline*, with all the
  structural gates wrapping it.
- **NOT a bypass of the runner**. Bypass = authoring with MCP outside the
  runner's pipeline (no phase1 L doc context, no chip_top auto-emit, no
  hygiene `--fix`, no eco_loop, no conformance, no audit). The wrong-shape
  RTLLM 37/50 baseline was bypass. Shape B done correctly invokes THIS
  skill.
- **NOT a free pass to ignore the blind rule**. The original benchmark's
  testbench / golden RTL are STILL HIDDEN during this authoring step. Only
  the host scorer (after all gates run) touches them.

## Quality bar

A "good" spec-to-rtl emission means:
- The RTL `iverilog -g2012`-compiles standalone (no missing dependencies).
- `eda_lint` returns 0 errors.
- `eda_synth` gf180 emits ≥1 cell (not pure-passthrough; not optimised to nothing).
- The module name + port list match the description verbatim.
- No latches inferred (or, if a latch IS intended per the description,
  declared `always_latch`).
- Reset-less registered outputs have an `initial = 0` block.

If you cannot satisfy this from the description blindly (e.g. the description
genuinely under-specifies a parameter the TB will instantiate by name), emit
your best honest reading and let the runner's downstream gates report the
mismatch. Per the open-benchmark-methodology skill § 4 Cat B, that's
documented as benchmark under-specification, not a skill failure.

## Honest history

This skill was filed at v0.1.31 as fix (A) of three suggestions for
`ORGANIC-20260528-null-rtl-gen-classes-need-bridge`. Before v0.1.32, the
runner's WAIVE message referenced `spec-to-rtl` skill but no skill file
existed — leading 5 disciplined RTLLM Shape B agents to interpret the
absence as "no path forward" and emit 0/50 in the first attempt. v0.1.32
ships this skill so the WAIVE → handoff is unambiguous + reproducible.

## Error-flag behavior — classify recoverable vs fatal from L3/L5 (#468)

When you author RTL that raises an error flag on an undefined-access /
illegal-command / out-of-range path, decide from the **L3/L5 protocol prose**
(not from convenience) whether the FSM should **recover** or **halt**, and encode
that decision so the downstream `fsm_error_invariant` gate and `/rtl-review` can
audit it:

- **recoverable** — if L3 (transaction protocol) / L5 (error-handling spec) says the
  block sets the error flag and **continues serving the next transaction** (returns to
  IDLE/ready), implement exactly that: raise the flag, then transition back to the
  serving state. Add a `// fsm_error: recoverable` annotation at the error-assign site
  so the reviewer can confirm without re-deriving the semantics.
- **fatal** — if L3/L5 binds the error to a **halt/lockup state** or says it
  **requires a reset (or explicit clear) to clear**, implement the halt and do NOT add
  the recoverable annotation; the FSM stays in the error state until reset.

**FORBIDDEN:** annotating a site `// fsm_error: recoverable` (or, in review, silencing
the gate) **without** the L3/L5 sentence(s) that establish the halt-vs-continue
behavior. The annotation is a claim about the spec and must be backed by spec text.

**why_not_bucket_a:** the gate program already does its half — it flags the
error-flag sites structurally. The recoverable-vs-fatal call is a semantic judgment
that lives in protocol prose (L3/L5), not in RTL structure; the identical
`error <= 1'b1` line means "keep going" in one protocol and "lock until reset" in
another, so no deterministic rule over the RTL can decide it. This is the residual LLM
authoring judgment, cross-referenced with `/rtl-review`'s matching classification
section.

## Output timing — same-cycle (Moore-combinational) vs registered pulse (#560)

A recurring functional miss (CVDP FUNC_ALL family): a status / event / strobe
output is implemented as a **registered** pulse (`out <= <event>;` under a
clock), which makes it appear **one cycle late**, but the spec / testbench
expects the output to be visible **in the same cycle as the event**. cocotb
checks that sample the output **on the same edge the event occurs** then read 0
and FAIL, even though the logic is otherwise correct.

**Decide the output's timing from the prose, then encode it:**

- **same-cycle (Moore-combinational decode)** — when the spec describes the
  output and its triggering event in the **same breath** ("asserts `done` *when*
  the count reaches N", "drives `error` *on* an invalid command", "`valid` is
  high *while* in state S"), OR the testbench style is a same-edge check, derive
  the output **combinationally from state / inputs** and do NOT register it:

  ```verilog
  // Moore decode — same-cycle, no register delay
  assign done = (state == DONE);
  always @(*) error = (cmd_valid && !cmd_legal);
  ```

  This is the right default for FSM status outputs, single-cycle strobes whose
  event is a combinational condition, and "output follows state" descriptions.

- **registered / next-cycle** — ONLY when the prose explicitly says the output
  is **registered**, appears **one cycle after** the event, is **pipelined**, or
  must be **glitch-free** for an external interface. Then use the NBA form:

  ```verilog
  always @(posedge clk) out <= <event>;   // intentional 1-cycle latency
  ```

**Worked examples (round-5 CVDP recoveries):** a vending-machine `error`+`return`
asserted the same cycle as the bad coin; an FSM output that follows the state
transition in the same cycle; a simple-SPI output that tracks the transition
when it happens. All three FAILed as registered pulses and PASSed once decoded
combinationally from state.

**why_not_bucket_a:** same-cycle vs registered is a reading of the spec prose
("when"/"on"/"while" vs "registered"/"one cycle later"/"pipelined") and of the
testbench's sampling convention. The identical event→output mapping is correct
as combinational in one problem and as registered in another; no regex over the
RTL or the prompt reliably separates the two, so this stays an LLM authoring
judgment.


## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/SKILL_NAME/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in this skill directory enumerates every required
element of your output: section headers, handoff lines, summary blocks.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
