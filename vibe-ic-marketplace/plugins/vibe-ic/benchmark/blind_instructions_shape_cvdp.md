# Blind authoring instructions — CVDP copilot (nonagentic) shape

You are authoring completions for CVDP copilot problems exported by the
official `local_export` flow. These rules are BINDING (they implement the
clean-room blindness doctrine + GATE-AS-SOLE-EMIT-PATH, ORGANIC #528/#529).

## What you MAY read

* The exported prompt records given to you. A record is `{id, prompt}` and, for
  a "modify / lint / optimize / complete an existing RTL" problem, **also
  `context`** — a map `{"rtl/<name>.sv": "<original source>"}` of the ORIGINAL
  RTL the task asks you to work on. This `context` is **GIVEN INPUT, not oracle
  data**: the prompt literally says "modify this design", the official scorer
  drops these exact files into `/code/rtl/` and compiles your top against them.
  You **MUST read your own record's `context` and honor it** — keep the exact
  module name(s), port names/directions/widths, and parameters of the given RTL;
  do the SPECIFIC change the prompt asks, not a from-scratch rewrite. The hidden
  TOPLEVEL is normally the top module declared in that context (`rtl/<X>.sv` →
  module `<X>`); name your top + file EXACTLY that. Ignoring the given context and
  re-inventing the interface is the #1 cause of ELAB_ERROR / functional-mismatch
  fails. Use **`cvdp_prompt_export.py`** to produce these context-complete records
  — it is the input-side sole-source (a hand-rolled `{id, prompt}`-only export
  silently strips `input.context`, which prose alone never prevents).

* **Extend, don't replace, given files (issue #139 class).** When a
  functional-modification completion adds a NEW module whose deliverable file
  IS one of the given `context` files, the completion for that file must carry
  BOTH the (unchanged, except requested edits) original context module AND the
  new top — the new top instantiates the original, so a file holding only the
  new module deletes the definition it depends on and nothing elaborates.
  Deterministic backstop before drafting the JSONL:
  `programs/file_extend_preserve_check.py --before <context_dir> --after
  <delivery_dir>` (exit 1 = self-breaking clobber). The judgment half lives in
  the IC Expert DB (`functional-modification-delivery`).

## What you MUST NOT do

* MUST NOT read the dataset's raw JSONL, golden/reference solutions
  (`output.response` / `output.context`), harness/testbench files, or ANY OTHER
  problem's materials. (Your OWN problem's `input.context` is allowed — see above;
  it is the given starting material, distinct from the forbidden golden output and
  other problems' context.)
* MUST NOT run `run_benchmark.py`, any scorer, or any verdict-level oracle.
  Scoring is the HOST's post-generation step. Your self-verification means
  your OWN mini-testbench only.
* MUST NOT write the responses JSONL yourself.

## The ONLY emit path (gate-as-sole-emit-path)

Write your per-problem draft completions to a drafts JSONL
(`{"id": ..., "completion": ...}` per line), then run:

```bash
python3 <plugin>/benchmark/cvdp_gate.py \
    --batch <your_drafts.jsonl> --out responses/<batch>.jsonl \
    --report reports/cvdp_gate_<batch>.json
```

The gate (a) extracts your Verilog payload, (b) ENFORCES
`rtl_hygiene_lint --fix`, (c) runs the `iverilog -g2012 -t null`
parse/elaboration gate (unknown CONTEXT modules are tolerated; syntax
errors and icarus-unsupported constructs — fatal on the official
icarus-13 scorer too — are BLOCKED), and (d) writes the responses JSONL
**itself**. A draft that does not pass the gate does not exist on disk;
fix it and re-run the gate. Exit 0 = all gated in; exit 1 = the stderr
lists each BLOCKED id with the offending line — fix those drafts and
re-run.

Disk truth: progress is counted from the gate-written responses JSONL,
never from your own tallies.

## Model selection for blind authoring (cost policy)

**DEFAULT to a cheaper model with LOW reasoning effort for the blind
authoring pass; reserve Opus for hard triage only.**

Rationale (run_v1239_converge cost lesson): the blind authoring pass is a
large fan-out over many small, well-scoped, single-module problems whose
spec is fully given in the prompt (+ `input.context`). The bulk of these
are routine RTL the GATE verifies deterministically anyway (it ENFORCES
`rtl_hygiene_lint --fix` + the icarus-13 parse/elaboration gate as the sole
emit path), so the marginal pass@1 from spending a frontier model on every
problem is small while the token cost is large. Spending Opus on the whole
fan-out is the dominant, avoidable cost.

Policy:

* **Blind authoring fan-out → a CHEAPER model + LOW reasoning effort.**
  Prefer **Haiku** (`claude-haiku-4-5-20251001`) for the routine bulk; step
  up to **Sonnet** (`claude-sonnet-4-6`) for a problem the cheaper model
  visibly struggles with (its own mini-TB fails, or the spec is dense).
* **Reserve Opus** (`claude-opus-4-8`) for the **hard triage / close-loop**
  step ONLY — the residual fails that need careful spec re-reading, FLOOR
  proofs (§4.1), or §4.2 independent blind re-solves — not for the
  first-pass author of every problem.
* This is a **cost** policy, not a quality shortcut: the deterministic gate
  is the same regardless of authoring model, so a cheaper author that
  passes the gate emits an equally-valid scoring artifact. If a cheaper
  model measurably depresses pass@1 on a given problem class, step that
  class up — but the DEFAULT is cheap + low-effort.
