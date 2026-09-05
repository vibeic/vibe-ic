---
name: spec-to-rtl
description: "MANDATORY entry point when `design_one_shot_runner.step_rtl_gen` WAIVES with `fallback_skill='spec-to-rtl'`. This is invoked for every IC class with `rtl_gen=null` in `ic_class_registry.json`, which is the SOURCE OF TRUTH for that set and the thing the runner actually routes from -- at the time of writing the 11 such classes are bare_fpga, bus_interconnect_protocol, bus_peripheral, crypto_accelerator, data_converter, digital_arithmetic_primitive, digital_cmd_driven, processor_cpu, pure_analog, serial_peripheral_protocol, unknown_protocol_class. The runner has already (1) ingested the prompt into L1-L27, (2) detected the IC class, (3) set the expected RTL path. This skill authors synthesizable RTL into the runner's expected path so the runner's downstream gates (chip_top auto-emit, rtl_hygiene_lint --fix, eda_lint, eda_synth, rtl_repair_retry, spec_conformance_check, full_stack_tb_gen) can fire on it. Triggered automatically by the runner's WAIVE message; also fires on phrases like 'AI invokes spec-to-rtl', 'runner WAIVED rtl_gen', 'spec-to-rtl handoff'. THIS IS THE RUNNER'S INTENDED PATH — NOT BYPASS. Bypass means authoring with MCP outside the runner's pipeline (what the 2026-05-28 wrong-shape RTLLM 37/50 did)."
---

# spec-to-rtl — the runner-orchestrated AI authoring step

## What this skill IS

The deterministic authoring path for IC classes WITHOUT a registered `rtl_gen`
generator. Spec → RTL fundamentally requires a language model (open-benchmark-
methodology skill § 1); this skill is **how the runner delegates that step to
the AI inside its own pipeline**, so the surrounding gates still fire.

## Invocation contract

When `design_one_shot_runner.step_rtl_gen` WAIVES with the message:

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

   **— and CONSULT THE CAPTURED-LESSON DIGEST (MANDATORY) —**
   The runner's WAIVE step deterministically writes
   `<project>/phase2/stage1/lessons.md` (and sets `lessons_digest` +
   `lessons_count` in its handoff `extras`): a chip-AGNOSTIC digest of every
   `### Skill:` genre/topology convention captured from prior recoveries.
   BEFORE you author, OPEN it, keyword-match THIS design's genre against each
   section's `**When to apply**` line, and APPLY every match. These are general
   patterns (frequency/clock-divider dual-edge-OR LEVEL topology,
   shifter logical-vs-rotate default, FIFO Gray-pointer, restoring-divider
   remainder width, overlapping-sequence FSM re-seed, valid/ready handshake
   inference, …), **NOT per-problem answers** — applying them is REQUIRED, not
   optional. A runner-driven author that skipped this re-invented a
   genre-determined topology from the prompt's loose wording and failed; this is
   the SAME digest Shape-C blind authors already MUST read.

   **— and LIST THE OTHER ARTIFACTS THE SPEC MAKES MANDATORY (MANDATORY) —**
   The WAIVE handoff tells you two things: write the RTL here, and read
   `lessons.md`. It says nothing about the OTHER artifacts the same spec makes
   mandatory and that you are the only one who can produce. Those clauses are
   already extractable from the SAME input docs you have just read, so run the
   preflight BEFORE you author:

   ```bash
   python3 plugins/vibe-ic/programs/spec_required_artifact_check.py \
       <project> --preflight
   ```

   It prints every still-OUTSTANDING spec-declared artifact with the input doc
   and the clause that demands it, and **always exits 0** — at handoff those
   files are legitimately absent, so it can never block a correct run. Author
   each one alongside the RTL. Skipping this does not make the requirement go
   away: the same extraction runs as a BLOCKING assertion at `final_audit`, so
   a missing declaration costs an entire Phase 2 (hygiene, lint, synth, DFT, a
   multi-minute LEC) to discover a file that took seconds to write.

   **— and DECIDE + RECORD YOUR FREE CHOICES *BEFORE* YOU AUTHOR (MANDATORY) —**
   The preflight above tells you WHICH files the spec demands. When one of them
   is a DECLARATION — a "MUST declare `<path>`" clause followed by a field table
   — the file is not paperwork you can write afterwards. Its fields are FREE
   CHOICES: decisions no downstream tool can recover by inference (serial bit
   order, reset-release latency, integer encoding, reset polarity, the parameter
   this build ran at, which optional feature axis you selected). Two correct
   designs disagree on all of them, so the comparison procedure cannot pair its
   reference output unless you tell it.

   The runner already staged the contract for you at
   `<project>/phase2/stage1/declaration_contract.json` (extras key
   `declaration_contract`). Read it, DECIDE each field, and record them:

   ```bash
   python3 plugins/vibe-ic/programs/spec_declaration_emit.py <project> --contract
   python3 plugins/vibe-ic/programs/spec_declaration_emit.py <project> \
       --set <field>=<value> --set <field>=<value> ...
   ```

   Then author RTL that CONFORMS to what you declared — not the other way round.

   Rules that are easy to get wrong:
   - The emitter **refuses** (rc=1, naming the field) while any REQUIRED choice
     is undetermined, and writes nothing. That refusal is correct: a
     default-filled declaration would turn the required-artifact gate green
     against a value nobody chose.
   - **Do not copy the spec's example value** into the declaration. The example
     column records what a reference implementation happened to pick; copying it
     makes the document author the designer.
   - An informational field you did not decide is **omitted**, never
     placeholder-filled.
   - `--from-rtl-declaration` exists ONLY for a legacy design whose RTL was
     written before the declaration; it promotes an existing
     `key = value` header block and stamps every field it takes as
     `recovered_from_prose` in the provenance sidecar. Do not use it as the
     normal path — a free choice recorded only in an RTL comment is a free
     choice a downstream tool has to guess.
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
6. **Self-verify with the HARNESS-EXACT toolchain BEFORE emit (MANDATORY —
   ORGANIC #688)**. A host-only / RTL+TB-together self-check passes code the
   scorer rejects, because the scorer (a) pins a specific tool version, (b)
   compiles the RTL **alone** under the harness top flag `-s <module>` (full
   codegen, not a `-t null` elaborate), and (c) runs a lint gate. Run the
   deterministic gate program — it is the gate, not a suggestion:

   ```bash
   python3 plugins/vibe-ic/programs/harness_exact_selfverify.py \
       --rtl <project>/phase2/stage1/rtl/<module_name>.v \
       --top <module_name> \
       --tb  <your_functional_tb.sv>   \  # optional gate C (see below)
       --report harness_exact_selfverify.json
   ```

   The program runs THREE gates and exits 0 only when every enforced gate
   passes:
   - **Gate A (deterministic)** — `iverilog -g2012 -o sim.vvp -s <top> rtl`
     standalone full codegen (catches ELAB-only + standalone-top fail
     classes). This is the harness-exact flag, NOT a `-t null` elaborate.
   - **Gate B (deterministic)** — `verilator --lint-only -Wall` clean.
   - **Gate C (you author, the program RUNS)** — a functional TB whose golden
     vectors are the **prompt's OWN worked examples / tables** (+ random +
     boundary). Extracting those examples is YOUR judgment; pass the TB via
     `--tb` and the program compiles+runs it and parses the verdict. No `--tb`
     → gate C is reported `skipped`, never silently passed.

   The program DISCLOSES any host/scorer tool-version skew and does NOT claim
   to catch spec-INTERPRETATION mismatches (it cannot — that residual stays an
   authoring judgment). When a tool is absent it discloses and skips (or, under
   `--require-tools`, hard-refuses) — it never fakes a pass.
6b. **Prompt→interface conformance pre-emit check (ORGANIC #695)**. Before
   handing back, run the deterministic interface gate — it reads ONLY the
   prompt + your RTL (BLIND; never the oracle/hidden TB) and flags the three
   PROMPT-DERIVABLE interface misses the hidden cocotb harness gets you on:

   ```bash
   python3 plugins/vibe-ic/programs/iface_conformance_v2.py \
       --id <problem_id> \
       --prompt <prompt.txt> \
       --rtl <project>/phase2/stage1/rtl/<module_name>.v
   ```

   It checks (1) MODULE-NAME-CASE — the RTL module name must match the
   canonical id stem the harness uses as TOPLEVEL CASE-EXACTLY (`-s
   findfasterclock` won't find `FindFasterClock`); (2) MISSING-PORT — every
   interface signal the prompt NAMES (table rows, backtick signal names with a
   nearby direction, a given-code module header, wavedrom `name` entries) must
   appear in your port list (AXI master must keep `ar*`/`aw*`, `s_ready`, etc.);
   (3) PORT-DIRECTION — a port's direction must match the prompt's signal table
   (don't declare `output sram_valid` when the harness drives it as an input).
   ADVISORY by default (prompt extraction is heuristic — an internal signal
   mentioned in prose is NOT a port and must not block); add `--strict` to make
   any finding exit 1 once you've confirmed the named signals really are ports.
   FIX every confirmed finding before emit — these are deterministic
   elaboration/bind failures the scorer would hit, not authoring judgment.
6c. **Spec-first coverage attribution pre-emit gate (ORGANIC #697)**. The
   hidden scorer is built from the SAME spec you read — where "spec" is the
   WHOLE input chain (prompt → fact graph → the L1-L27 the runner just emitted).
   So your self-TB must cover every spec-derived requirement, or the hidden TB
   will catch a bug yours never exercised. Run the deterministic gate — it reads
   ONLY the chain + your RTL + your TB (BLIND; never the oracle):

   ```bash
   python3 plugins/vibe-ic/programs/spec_coverage_check.py \
       --prompt <prompt.txt> --ldocs <project>/generated_docs/ \
       [--fact-graph <fact_graph.json>] \
       --rtl <project>/phase2/stage1/rtl/<module_name>.v \
       --tb  <your_functional_tb.sv> --strict
   ```

   It extracts a DETERMINISTIC checklist (ports/widths/directions, reset
   value+polarity+sync/async, stated latency, every table row, every worked
   example, **every ENUMERATED SET + its outside-the-set/default boundary** —
   the most-missed #697 pattern — signed-ness, byte order, overflow, handshake)
   from EVERY chain station and reports any item your TB leaves UNCOVERED
   (`--strict` BLOCKs on a coverage gap). FIX the gap by adding the missing
   directed stimulus/assertion (especially an OUTSIDE-the-set value for any
   enumerated set). On a downstream FAIL, re-run with `--failure "<behavior>"`:
   a `coverage-gap` ⇒ enhance your TB; an `extraction-gap` ⇒ the program names
   the `route_to:` station (ic-expert-agent / spec-to-rtl) that
   dropped the requirement (community-backlog it); only a cited `spec-absent` is
   a genuine floor. The structural extraction + routing is deterministic;
   deciding whether a prose sentence is a distinct *testable* requirement (so
   you can author its stimulus) is your LLM judgment.
7. **Tell the orchestrator you're done**. The caller will re-invoke
   `vibe_ic_one_shot_runner.py` so the runner detects the RTL at the
   expected path, skips `step_rtl_gen`, and continues with: chip_top
   wrapper auto-emit (v0.1.32+), `rtl_hygiene_lint --fix`, `eda_lint`,
   `eda_synth`, `spec_conformance_check`, `rtl_repair_retry` (up to 3 retries
   on `reference_tb` FAIL), `full_stack_tb_gen`, `final_audit`.

## What this skill IS NOT

- **NOT a fully-deterministic program**. Spec→Verilog needs an LLM; this
  skill is *the AI's role inside the runner pipeline*, with all the
  structural gates wrapping it.
- **NOT a bypass of the runner**. Bypass = authoring with MCP outside the
  runner's pipeline (no phase1 L doc context, no chip_top auto-emit, no
  hygiene `--fix`, no rtl_repair_retry, no conformance, no audit). The wrong-shape
  RTLLM 37/50 baseline was bypass. Shape B done correctly invokes THIS
  skill.
- **NOT a free pass to ignore the blind rule**. The original benchmark's
  testbench / golden RTL are STILL HIDDEN during this authoring step. Only
  the host scorer (after all gates run) touches them.

## Quality bar

A "good" spec-to-rtl emission means:
- `harness_exact_selfverify.py` exits 0 (gate A standalone `-s <top>` codegen
  + gate B verilator lint both pass — see step 6; this subsumes "compiles
  standalone" and "lint clean" with the SCORER's exact flags, so the host-only
  accept-set cannot diverge).
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


## Independent differential self-verification (N-version) — break the single-self-TB circularity (#700)

If you author BOTH the RTL **and** its self-testbench from ONE reading of the
spec, the self-verification is **circular**: a misread baked into that one
reading lands in BOTH surfaces, so the TB happily confirms the wrong behaviour.
Empirically this passed a real oversight (an hmac write-data **live-read vs
latched-read**: 3471 diffs once an independent check was added → fixed to 0).

**Break the circularity with a SECOND, INDEPENDENT derivation** and
cross-check it against the RTL every cycle with `diff_verify_harness.py`:

1. **Derive a reference model INDEPENDENTLY** — fresh reasoning, **without
   reusing your RTL derivation**. Author a Python module exposing `ref(seq)`
   (input-sequence → expected-output-sequence). It must be a behavioural
   transfer function, not a copy of the RTL's structure.

2. **EXPLICITLY enumerate every ambiguous quantity and PIN each via the spec's
   worked examples** before writing `ref`:
   - **latency** (count the pipeline stages → the leading-prefix length, e.g.
     `[0,0]+seq[:-2]` for an exactly-2-cycle delay);
   - **registered-vs-comb** output;
   - **off-by-one** (pulse offset / first-vs-last / wrap / inclusive-exclusive);
   - **bit/byte packing** and **encoding** (MSB/LSB-first, sub-byte width).
   Pin each to a concrete spec worked example so the reference is grounded, not
   guessed.

3. **Run the differential harness** — it generates and runs a cycle-accurate
   differential testbench (directed + random + boundary vectors), driving the
   RTL and comparing every cycle to your independent `ref`:

   ```bash
   python3 plugins/vibe-ic/programs/diff_verify_harness.py \
       --rtl <your_rtl.sv> --ref <your_ref.py> --top <module> \
       --vectors directed+random+boundary
   ```

   `AGREE` (rc 0) = the two independent derivations match every cycle.
   A first-mismatch line (rc 1, `cycle`/`signal`) = a **designer-vs-reference
   DIFF**: one derivation noticed a clause the other missed.

4. **Adjudicate every mismatch by RE-READING the spec** — decide which
   derivation is correct, fix the wrong one, re-run. **Emit only after RTL and
   the independent reference AGREE.**

**Honest SCOPE (this is a COMPLEMENT, not a silver bullet):** it catches
**OVERSIGHT misreads** (one derivation noticed a clause the other missed). It
does **NOT** catch **genuine ambiguity** where the spec wording biases ALL
independent blind readings the **same** way (an exact-latency phrase both you
and the reference read identically-but-wrong), nor benchmark spec↔TB
contradictions — those are **FLOOR** (on the hardest CVDP ambiguity residual it
recovered 0/8 per #697). Its value is on FRESH runs preventing oversight bugs
**before** the scorer. It is the differential complement to the deterministic
**#697 `spec_coverage_check`** (force the self-TB to COVER each dimension) and
the **#699** timing/encoding reading disciplines — not a replacement for either.

**why_not_bucket_a:** authoring the independent reference and adjudicating a
designer-vs-reference mismatch require reading and interpreting the spec; no
regex derives the reference. The DETERMINISTIC half — generating and running
the differential harness over directed/random/boundary vectors and reporting
per-cycle mismatches — IS the program (`diff_verify_harness`); this step records
the judgment residual (deriving the reference + adjudicating).


## Latency/timing conformance — the PROGRAM measures, not your self-TB (#705)

When the spec states an **EXACT** latency — "output asserts **N cycles** after
the start event", "**WIDTH+2**-cycle delay", "**1 cycle overhead** when
transitioning IDLE→BUSY registering inputs" — **DO NOT trust your self-TB's
measurement.** Empirically, across four blind authoring strategies agents scored
**0/8** on off-by-one latency failures: each improvised a counting convention
that happened to match its OWN (wrong) RTL, so the self-TB confirmed the wrong
behaviour. There is no independent yard-stick in a single-self-TB flow.

`latency_conformance_check.py` IS that yard-stick. It generates its OWN canonical
measurement testbench, **counts the way a hidden scorer counts** (pulse the event
HIGH for exactly one clock = one latch edge, then count posedges until the output
first asserts), resolves the spec literal against the module's real parameters,
and **BLOCKS on any mismatch**. Run it and fix the RTL until it prints
`latency-conformance ok`:

```bash
python3 plugins/vibe-ic/programs/latency_conformance_check.py \
    --rtl <your_rtl.sv> --top <module> \
    --event <start_port> --output <valid_port> --expect "<expr>"
```

- `--expect` is the spec latency literal as arithmetic over the module's
  parameters (`WIDTH+2`, `N+1`, `8`); resolved against the `#(...)` defaults (or
  a `--param NAME=VAL` override). It is evaluated by a tiny SAFE evaluator
  (digits, param names, `+ - * // ( )` only — never `eval`).
- `LATENCY-MISMATCH: measured=<m> but spec <expr>=<e>` (rc 1) = your RTL's real
  latency is `<m>`, the spec demands `<e>` — an off-by-one. Fix the RTL (one
  iteration / one register stage off) and re-run.
- `latency-conformance ok: measured=<m> == spec <expr>` (rc 0) = the measured
  latency matches the spec literal — emit.
- iverilog absent → a distinct `SKIP` (rc 0), **never** a fabricated PASS; the
  output never asserting → `LATENCY-TIMEOUT` (rc 1).

**why_not_bucket_a:** the canonical MEASUREMENT (build the TB, pulse the event,
count posedges to the output assertion) + the comparison against the resolved
literal IS the deterministic program. The LLM residual is reading the spec to
decide **WHICH** port is the event, **WHICH** is the output, and **WHICH**
expected expression the prose names (`WIDTH+2` vs `N+1` vs a constant). This is
the timing complement to **#697** (coverage attribution — force the self-TB to
COVER each dimension) and **#700** (independent differential verify — cross-check
a second derivation): #705 supplies the absolute latency yard-stick those two do
not.


## "Read the simulation waveform" tables — the PROGRAM replays the published table (#716)

When the prompt embeds a **literal simulation table** — rows of
`time [clk] <input...> [internal...] <output>` under a "**Read the simulation
waveforms to determine what the circuit does, then implement it**" instruction
(the VerilogEval `circuitN` family) — the table **IS** a directed test vector you
must reproduce **exactly**. The trap that fails the hidden scorer is
**MIS-COUNTING PIPELINE STAGES**: the early rows where the output reads `x` are
the **input-sampling NBA race** (`@(posedge) a<=val` leaves the input `x` on the
first edge), **NOT** an extra register stage. An agent who reads that X-window as
a second stage authors a TWO-stage `q1<=~a; q<=q1` pipeline when the spec is the
ONE-stage `q<=~a`; its self-TB still "passes" but it scores ~58/123 mismatches on
the hidden TB (Prob098_circuit7, the round-18 FAIL). The X-window is consumed by
the X-match convention — it does **not** license an added latency stage. Count
stages from the **first DEFINED output transition**, not from the first `x`.

`waveform_table_conformance_check.py` is the independent yard-stick. It parses the
table, replays it the way the scorer compares (X in the table matches anything;
X in the DUT only matches a table X), and **BLOCKS on any mismatch**:

```bash
python3 plugins/vibe-ic/programs/waveform_table_conformance_check.py \
    --prompt <prompt.txt> --rtl <your_rtl.sv> --top <module>
```

- `WTC_PASS` (rc 0) — the RTL reproduces the published table; emit.
- `WTC_FAIL mismatches=<n>` + per-row `WTC_MISMATCH t=.. expected=.. got=..`
  (rc 1) — your RTL diverges from the table (the stage-count / inversion /
  function is wrong). Fix and re-run.
- `WTC_SKIP_<reason>` / `WTC_NO_TABLE` (rc 0) — the prompt has no table, OR the
  design is **outside the proven-faithful envelope** (a negedge / level-sensitive
  **transparent latch**, a **multi-bit/hex** output column, a Moore FSM exposing
  **multiple observable outputs**, or non-binary table values). The gate
  **refuses to block** these — its replay timing is only proven faithful for
  combinational truth-tables and single-bit single-clock **posedge-registered**
  outputs, so for everything else it advises rather than blocks (NO false-block).
- iverilog absent → `WTC_SKIP_no_tools` (rc 0), never a fabricated PASS.

**why_not_bucket_a:** parsing the table, building the directed replay TB, running
it under the scorer's X-match, and comparing every row IS the deterministic
program. The LLM residual is reading the prose to confirm it is a
"read-the-waveform" problem and, on a `WTC_FAIL`, deciding WHICH clause of the
RTL (stage count, polarity, function) the mismatch implicates. This is the
DIRECTED-VECTOR complement to **#700** (a random differential cross-check, which
is circular here because a stage-count misread biases BOTH the RTL and a
hand-derived `ref`) and **#705** (which needs a prose latency literal a
waveform-only prompt does not supply).


## Behavioral-prose Moore FSM — extract the table, let the PROGRAM emit (2026-06-23)

Most FSMs whose states + transitions are stated in NARRATIVE PROSE (Lemmings with
dig/splat/counter precedence; a PS/2 byte-boundary search; a sliding-window counter;
a multi-phase controller) still need a language model to read prose into structure.
One strict basic carve-out is already program-solved: when a directional bump+fall
walker explicitly states both direction mappings, both-side behavior, fall/resume
memory, all three bump/fall boundary priorities, Moore outputs, reset, and clock
edge, `behavioral_fsm_synth.py` parses those facts into a complete four-state table
and the registry emits it. Missing any fact or adding dig/splat/timer behavior is a
safe SKIP. For every remaining narrative shape, once the AI extracts a COMPLETE
enumerated table, emitting correct RTL is a pure formula. So DO NOT hand-author the
always-blocks — split the work:

1. **You (AI) extract the COMPLETE canonical Moore-FSM table from the prose** — every
   state, every Moore output per state, the reset (state + sync/async + level), and
   EVERY transition (one row per state × every input combination; UNROLL a counter
   like "falls for >20 cycles" into explicit states — the internal encoding is FREE
   because the TB observes only the Moore outputs). Inputs may be a 1-bit port or a
   bus bit-select (`in[3]`). The format is the docstring of
   `programs/moore_fsm_table_emit.py`.
2. **The PROGRAM emits + gates**: `python3 programs/moore_fsm_table_emit.py --prompt
   <prompt> --table <your.tbl> --top <TopModule>`. It VALIDATES the table is complete
   and matches the declared interface (rejects a hallucinated port, a missing input
   combo, an unknown next-state, a missing output) and emits the RTL, or SKIPs
   (exit 1). The emitted RTL is then your authored sample.

This is the §4.2 **AI-step-gated-by-program** pattern, not free-text authoring: the
program guarantees the RTL is a pure function of a table it proved complete, so a
mis-extraction becomes a SKIP, never a wrong-but-plausible machine. Proven
0-mismatch on the full Lemmings family (1–4, incl. the 47-state >20-cycle splatter
counter), PS/2 (`in[3]`), the 3-cycle window counter, and the multi-phase motor
controller. If your first table mismatches its self-TB, RE-READ THE PROMPT (never
the hidden reference) to fix the offending transition/output.


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
