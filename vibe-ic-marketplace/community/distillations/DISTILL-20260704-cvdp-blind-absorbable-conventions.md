# Distillation — CVDP converged conventions → blind-absorbable plugin knowledge

**Filed by:** benchmark-agent · **Source run:** `benchmark_external/cvdp/run_hard94_unified_20260703`
**Plugin at distill time:** v1.3.8 · **Method:** zero-oracle two-arm A/B blind re-author, official docker scorer
**Companion:** backlog `ORGANIC-20260704-ic-expert-canonical-convention-floor-crosscheck.yaml` (#104)

## What this is

The 10 canonical conventions that recovered prior "floors" **with oracle-in-the-loop** were each re-tested **BLIND** (zero oracle, single shot) with the convention injected as an `ic-expert-agent` lesson. Controlled result:

| arm | convention in skill | blind pass@1 |
|---|---|---|
| A (baseline v1.3.8) | no | **0/10** |
| B (convention injected) | yes | **3/10** |

This file distills each into **absorption-ready** form and labels it by the **verified** litmus:
a convention is **BLIND-ABSORBABLE** iff a blind author, given only prompt+context+the rule, passes the official oracle in one shot (proven at `blind_B/score` vs `blind_A/score`).

---

## Tier 1 — BLIND-ABSORBABLE (verified: Arm B PASS, Arm A FAIL). Land these first.

These lift blind pass@1 immediately and generalize to their whole family. Program-first where a
deterministic template exists; skill-lesson otherwise.

### 1. Tree-PLRU victim policy  → `agents/ic-expert-agent.md` (+ program: `rtl_dispatch` PLRU template)
> **### Skill: tree-PLRU victim decode (complement walk).** In a textbook tree-PLRU, each
> internal-node recency bit records the branch toward the MOST-recently-used child; the victim
> way is decoded by walking the COMPLEMENT of each stored bit from root to leaf. All-zeros reset
> therefore selects way `NWAYS-1` as the first victim. (Do not read the bit as "points at victim".)

### 2. Rectangular zero-pad embedding  → `agents/ic-expert-agent.md`
> **### Skill: block zero-pad embedding.** Embedding an m×n array into an N×N square is the
> textbook block form `[[A,0],[0,0]]`: data stays at the top-left origin; zeros fill the trailing
> rows/columns (numpy/DSP trailing pad). A "no-rotation / pass-through" mode must reproduce this
> exact placement, not a centered or bottom-right placement.

### 3. One-hot SOP area rewrite  → `agents/ic-expert-agent.md` (+ program: synth-area helper)
> **### Skill: one-hot sum-of-products area rewrite.** A set of mutually-exclusive equality
> decodes (each an N-bit compare to a distinct constant) is one-hot, so a deep priority-mux
> payload network legally flattens to a one-hot AND-OR (SOP) net — with a thermometer mask for
> run/terminate families and shared comparator products. Functionally identical, far fewer
> logic levels/cells; use it when an area/cell threshold must be met.

---

## Tier 2 — CONVERGE-AID (necessary but NOT single-shot-blind-sufficient on this set).

Each of these recovered its problem **only** in combination with a second fact the rule alone
does not supply (exact port name / cycle-exact timing / multi-parameter default), so injecting the
rule blind did **not** reproduce the pass in one shot. Still worth landing as lessons — they cut
close-loop iterations and may combine to lift blind on other problems — but label them honestly as
converge-aids, not blind-lifts.

- **Packed-array LSB packing** (`config_lpf_0004`): slot i = bits `[i*W +: W]`, slot 0 at LSB.
  → also a candidate deterministic packing helper. *Blind gap: needs the exact slot→source map.*
- **cocotb top-scope observability** (`config_lpf_0011`): `dut.<name>` resolves any top-scope
  reg, not only ports; expose an existing state reg under the `_in/_out` suffix convention.
  *Blind gap: which internal signal is the intended observable.*
- **AMBA default width** (`fifo_async_0001`): unstated bus width ⇒ 32; a 0xDEADBEEF-class sentinel
  in the prompt pins 32. *Blind gap: combined with reset/flag timing.*
- **Microcode cadence inheritance** (`perceptron_0006`): a unit extending a microcode ROM inherits
  the base sequencer's rate (1 µinstr / 2 clk with a double-registered address path).
  *Blind gap: per-vector micro-step count.*
- **Fausett stop criterion** (`perceptron_0013`): stop iff weight-update deltas are ZERO (not
  "two consecutive EQUAL deltas"). *Blind gap: surrounding training-FSM structure.*
- **Moore-FSM timing derivation** (`interrupt_ctrl_0017`): output asserts on state ENTRY (fixed
  FSM-depth latency), level-held to ack, deasserts registered with ≥1 dwell before re-arm.
  *Blind gap: exact per-state cycle counts.*
- **Ring-counter SIPO rewrite** (`sync_serial_0052`): replace random-access indexed bit write with
  a one-hot ring-counter write pointer + lap counter. → candidate `rtl_dispatch` template.
  *Blind gap: exact mod-N drop/done semantics.*

---

## Tier 3 — NOT DISTILLABLE (would be memorization = cheating; keep as FLOOR).

Excluded on purpose — no general rule; the pass would require encoding this problem's hidden-TB
value, which overfits and pollutes the DB:
- `hebbian_0012` — TB pins internal `w1/w2/bias` that contradict the GIVEN `gate_target`.
- `rounding_0001` — expected output oscillates 0↔255 between two contradictory worked examples.
- `axi_tap_0009` — prompt explicitly mandates a single named threshold; no convention to infer.

---

## Absorption plan (core-agent / gatekeeper owns landing + versioning)

1. Land Tier 1 (3 lessons) into `agents/ic-expert-agent.md`; add the 2 program templates
   (PLRU decode, one-hot SOP) where a deterministic form is stable — **measure blind pass@1
   lift on a fresh full run** to confirm compounding.
2. Land Tier 2 (7 lessons) with the honest "converge-aid" label; do NOT claim blind lift.
3. Tier 3 stays FLOOR — do not absorb.

**Verification obligation:** after landing, a fresh BLIND full-302 run must show the blind number
rise (not just the converged number) — that is the only proof the knowledge compounded. The
benchmark-agent will re-measure at the oracle once landed.
