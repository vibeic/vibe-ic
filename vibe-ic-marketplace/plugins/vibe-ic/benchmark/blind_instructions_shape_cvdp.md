# Blind authoring instructions — CVDP copilot (nonagentic) shape

You are authoring completions for CVDP copilot problems exported by the
official `local_export` flow. These rules are BINDING (they implement the
clean-room blindness doctrine + GATE-AS-SOLE-EMIT-PATH, ORGANIC #528/#529).

## What you MAY read

* The exported prompt records given to you (id + prompt text), and nothing
  else of the dataset.

## What you MUST NOT do

* MUST NOT read the dataset's raw JSONL, golden/reference solutions,
  harness/testbench files, or ANY other problem's materials.
* MUST NOT run `run_benchmark.py`, any scorer, or any verdict-level oracle.
  Scoring is the HOST's post-generation step. Your self-verification means
  your OWN mini-testbench only.
* MUST NOT write the responses JSONL yourself.

## The ONLY emit path (gate-as-sole-emit-path)

Write your per-problem draft completions to a drafts JSONL
(`{"id": ..., "completion": ...}` per line), then run:

```bash
python3 <plugin>/benchmark-harness/cvdp_gate.py \
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
