---
name: formal-verify
description: Run formal property verification (FPV) on RTL by driving model-checkers such as SymbiYosys, Jasper, or VC Formal. Use when the user says "prove this", "formal verify", "model check", "run sby", or has SVA properties from assertion-gen that need to be proven or bounded.
---

# Formal Verify

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt.
> Programs first; AI is the backstop on cex narrative.

`formal_harness_gen.py` authors the construction-safe floor and writes
`property_contract.json`. This skill owns BOTH the expert property-authoring
fallback for unresolved L3/L6/L8 obligation IDs and the independent review of
model-checker evidence. Without a runner, SVA files are documentation; without
denominator closure, a passing subset is INCOMPLETE rather than Step 5.

## Mandatory Deterministic Preflight

```bash
# MCP tool call — drives SymbiYosys / Jasper / VC Formal:
eda_formal({
  rtl_files: ["<dut>.v"],
  sva_files: ["<assertions>.sva"],
  top_module: "<top>",
  mode: "prove",       // or "bmc" with --bmc-depth N
})
```

The tool returns `property_count`, `proven`, `failed`, plus
`counterexample_paths[]` when failures appear. **Treat the JSON output
as ground truth.** When a property is FAILED, narrate the CEX trace;
when UNDETERMINED at the bound, recommend deeper BMC. Never claim a
property "obviously holds" without the tool's PROVEN verdict.

## The Step-5 in-flow path (`formal_property_run`) — author the harness, the program proves

The canonical flow Step 5 starts with PROGRAM `formal_harness_gen.py`. When it
writes `formal_authoring_request.json`, invocation of this skill is mandatory:

1. Read `property_contract.json` and the request. Preserve every obligation ID.
2. Bind each unresolved L3/L6/L8 declaration to visible RTL signals. Never guess
   a signal mapping or transcribe an uncheckable prose promise into an assertion.
3. Author properties in `phase2/stage1/formal/formal_<top>.sv`; update each
   covered obligation with its exact property name and remove it from
   `unresolved_obligations` only when the assertion exists.
4. Write `formal_expert_review.json` with `invocation_status: INVOKED`,
   `fallback_skill: formal-verify`, and a `dispositions` list with one
   `AUTHORED`, `DECLARATION_MISSING`, or `UNANSWERABLE` row for every request
   ID. Every `AUTHORED` row names the exact `property`; `UNANSWERABLE` keeps
   the row INCOMPLETE and names what declaration/property is missing.
5. Run `formal_property_run.py`, then `formal_proof_evidence_check.py`.

The PROGRAM `formal_property_run.py` emits the `.sby`, runs `sby` in the
container, parses the transcript, and writes `formal/results.json` plus the
report that `formal_proof_evidence_check` verifies (`all_proved:true` ONLY when
every task shows `DONE (PASS)`). A completed result must cite the elaborated
`.sby`, proof transcript, positive property denominator, and bounded/unbounded
scope. Without a sound harness the request remains INCOMPLETE; it is never a
skip.

**When the engine cannot be REACHED (#216).** "The proof engine was never
reached" and "the proof ran and was inconclusive" are different facts and are
reported differently. If `sby` is unreachable (container not running, Docker
down, `sby` not on PATH) the program writes
`phase2/stage1/formal/formal_env_unavailable.json` + `.md` with
`verdict: ENV_UNAVAILABLE` and an `env_gap` block naming **what** capability is
missing, **where** the flow looked for it, and **what to install or stage** —
and it writes NO `results.json`, so nothing that looks like a proof enters the
record. It never reports `INCONCLUSIVE`, which is a claim about solver
convergence that a run with no transcript cannot support.

Before waiving Step 5, CHECK THE CLAIM: our SymbiYosys fork ships inside the
`vibeic-eda` image at `/usr/local/bin/sby`, so on a provisioned host there is
usually nothing to waive — verify with
`docker exec <container> command -v sby`. Passing the wrong `--container` name
is a DISCOVERY bug, not an environment gap, and the fix is to point at a
running container (`docker ps`), not to file a waiver.

A genuine gap is waived through `waivers.json` with
`step: "formal"`, `verdict_tier: "ENV_UNAVAILABLE"`, a `ticket`,
`review_required: true`, non-empty `evidence`, and a `rationale` that names the
capability, the search location and the remedy. An entry missing any of those,
or naming an unknown step role, is REJECTED and reported as an advisory in the
compliance output — it is never silently dropped, and the step stays unwaived.
A waiver is open work: it never counts as a pass, and it defers only the steps
that genuinely declare a `blocks_on` dependency on formal results.

**Engine recipe (no external SMT solver needed).** The container ships NO
z3/yices/boolector — do NOT dead-end on that: SBY's built-in **ABC engines**
need none (`aigsmt none`): `abc pdr` proves safety properties UNBOUNDED;
`abc bmc3` runs functional BMC to a DISCLOSED depth. Split the harness into a
`[safety]` prove task and a `[bmc]` task so each engine does what it is good at.

**Harness-authoring craft (blind, §4.05-clean) — distilled from the spm proof:**
- Golden reference = the OPERATOR SEMANTICS (`assert (p_acc == x * y_low)`),
  never a TB/oracle/harness read. Universally quantify inputs with
  `(* anyseq *)` wires; pin the contract's stability assumptions explicitly
  (e.g. `assume (x == $past(x))` when the datasheet says x is held).
- Model reset honestly: a one-shot init assumption (`assume (rst)` at t0,
  `assume (!rst)` after) beats leaving reset free — a free-running reset makes
  every property vacuously provable or spuriously refutable.
- Disclose bounded-vs-unbounded in the result: a wide datapath's full-latency
  functional proof may be solver-hard (SAT size grows exponentially with
  frame count); the achievable HONEST tier is safety-UNBOUNDED +
  functional-BMC-to-depth-k with k stated. Corroborate the miter at reduced
  widths (e.g. full-latency proof at size=8/16) — same properties, full
  coverage where the solver can reach.

## When to use

- Control-dominated logic (arbiters, FIFOs, protocol adapters, CDC samplers)
- When the program-first request names unresolved L3/L6/L8 obligations
- Regression: re-prove after any RTL change to a formally-verified block
- Safety-critical paths where simulation coverage is insufficient

## Verification Modes

| Mode | What it proves | When to use | Limitation |
|------|---------------|-------------|-----------|
| **k-induction** (`mode prove`) | Property holds for ALL reachable states | Small modules (<100 FFs, no deep counters) | Fails on large state spaces |
| **BMC** (`mode bmc`) | No bug exists within N cycles | Large/complex modules | Not a complete proof |
| **cover** (`mode cover`) | A given state IS reachable | Checking liveness, debug | — |

## Why Large Modules Fail k-induction

k-induction requires depth ≥ longest counter/timer path; deep counters, large
memory arrays, and many-FF state spaces all defeat unbounded proof — the
**state explosion problem**, fundamental to model checking.

**Do not eyeball the module to decide prove-vs-bmc.** The per-module
feasibility decision (FF count, deepest counter/timer terminal, memory-array
bit width, FSM state count → `recommended_mode` + `min_k_bound` +
`infeasible_reason`) is **enforced by `programs/formal_complexity_classify.py`**.
Run it and treat its verdict as ground truth:

```bash
python3 programs/formal_complexity_classify.py <rtl_dir> --json
```

- `recommended_mode: "prove"` → k-induction feasible; use it at `min_k_bound`.
- `recommended_mode: "bmc"`  → exceeds the prove envelope; run `mode bmc
  depth>=min_k_bound` and apply Solutions B-F below to chase a complete proof.
- exit 2 (NO_MODULE / NO_RTL) → honest missing-data; do **not** claim proven.

The classifier reproduces the worked benchmark table (timer_block / crc8_engine
prove-feasible at k=20; aid_transceiver k≥135; otp_controller 376 mem-bits +
k≥1650; cmd_processor 336-bit memory) directly from the RTL — no hand table.

## Solutions for Complex Modules

### Solution A: BMC-Only (Immediate)

Don't pursue complete proof. BMC to depth 50-200 catches most bugs:

```
[options]
mode bmc
depth 50
```

**<benchmark> result**: All 4 complex modules pass BMC at depth 50.

### Solution B: Abstract Timers (`ifdef FORMAL`)

Replace long counters with short ones for formal:

```systemverilog
`ifdef FORMAL
  localparam logic [11:0] EPROG_CYCLES = 4;  // formal: 4 cycles
`else
  localparam logic [11:0] EPROG_CYCLES = 1650;  // real: 1650 cycles
`endif
```

Logic structure unchanged, but solver finishes in seconds.

Reference: [Tom Verbeure — Under the Hood of Formal Verification](https://tomverbeure.github.io/rtl/2019/01/04/Under-the-Hood-of-Formal-Verification.html)

### Solution C: Assume-Constrain Decomposition

Use `assume()` to restrict inputs to legal behavior:

```systemverilog
// cmd_processor: break only in valid states
always @(posedge clk)
  assume (!break_detected || state_r == IDLE || state_r == COMM_ERROR);

// byte_rx_valid never two consecutive cycles
always @(posedge clk)
  if (!init) assume (!byte_rx_valid || !$past(byte_rx_valid));
```

Massively reduces state space — solver ignores unreachable scenarios.

Reference: [ZipCPU — Swapping Assumptions and Assertions](https://zipcpu.com/formal/2018/12/18/skynet.html)

### Solution D: Helper Invariants

Help solver know which state combinations are impossible:

```systemverilog
// otp_controller: prog_timer nonzero only in PROG states
always @(posedge clk)
  if (!init && rst_n)
    assert (prog_timer_r != 0 |-> 
      (prog_state_r == PROG_ACTIVE || prog_state_r == PROG_WAIT));
```

Reference: [ZipCPU — An Exercise in Formal Induction](https://zipcpu.com/blog/2018/03/10/induction-exercise.html)

### Solution E: Per-Command Task Splitting

For `cmd_processor` with 8 commands — split into 8 formal tasks:

```
[tasks]
verify_cmd_id
verify_cmd_set_state
verify_cmd_get_state
...

[options]
verify_cmd_id: mode bmc
verify_cmd_id: depth 30
```

Each task assumes `cmd_byte_r` is one specific value. 8 small problems >> 1 huge problem.

Reference: [SymbiYosys Tasks](https://symbiyosys.readthedocs.io/en/latest/reference.html)

### Solution F: Memory Abstraction

For `otp_controller`'s 47-byte array:
- **Memory slicing**: only verify 3-4 representative bytes
- **Array theory**: SMT solver uses `(Array (_ BitVec 6) (_ BitVec 8))` — more efficient than 47×8 bits

## Inputs to gather

1. RTL module under verification
2. SVA properties (from the deterministic floor or expert-authored here)
3. Target engine: SymbiYosys (open), Jasper (Cadence), VC Formal (Synopsys)
4. Bound (for BMC) or depth (for k-induction)
5. Constraints / assumptions (`assume` properties)

## Workflow

1. **Classify module complexity** — run `programs/formal_complexity_classify.py`
   to choose k-induction (prove) vs BMC per module (do not eyeball it)
2. **Generate assertions** — deterministic floor first, then this skill for the
   exact unresolved obligation IDs
3. **Write `.sby` config** with appropriate mode and depth
4. **Run engine** — `sby -f module.sby`
5. **Triage results**:
   - PASS: record bound/depth
   - FAIL: capture CEX trace, map to RTL line, propose fix → `/rtl-repair`
   - TIMEOUT: apply solutions B-F above
6. **Regression harness**: re-run after any RTL change

## Output format

- `formal/<module>.sby`
- `formal/<module>_formal.sv` — assertions
- `formal/<module>_report.md` with per-property status table
- Counterexample VCDs (if FAIL)

## Technical basis

SymbiYosys is the canonical open-source FPV driver on top of Yosys. K-induction and IC3/PDR are the dominant engines. SMT solvers (Yices, Z3) handle the underlying satisfiability.

References:
- [SymbiYosys Documentation](https://symbiyosys.readthedocs.io/)
- [ZipCPU Formal Verification Blog Series](https://zipcpu.com/formal/formal.html)
- [Model Checking and State Explosion (Clarke et al.)](https://link.springer.com/chapter/10.1007/978-3-642-35746-6_1)
- [Formal Verification with SymbiYosys (Clifford Wolf)](https://slideplayer.com/slide/11950984/)
- [HIVE: Scalable HW-FW Co-Verification via Decomposition](https://arxiv.org/html/2309.08002v2)

## Handoff

- CEX → `/rtl-repair`
- Uncovered states → `/coverage-closure`
- New SVA needed → `/assertion-gen`

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/formal-verify/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
