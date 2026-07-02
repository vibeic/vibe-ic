# CVDP hard-94 CLEAN-ROOM blind authoring — BINDING per-batch instructions (plugin v1.2.93)

## Inputs you MAY read
* ONLY your assigned `batches/batchNN.jsonl`. Each line = {id, prompt, [context]}.
  `context` (when present) = {"rtl/<name>.sv": "<original source>"} — GIVEN INPUT (input.context), not oracle.
* The Vibe-IC plugin's design-craft knowledge: the `ic-expert-agent` skill lessons AND
  `python3 programs/ic_expert_db_query.py "<the prompt text>"` (the IC Expert DB — general,
  blindness-clean design-class craft). This is the plugin capability being measured — USE it.

## MUST NOT (clean-room blindness — BINDING)
* MUST NOT read: the dataset raw JSONL, golden/reference (output.*), harness/testbench,
  ANY other problem's materials (sibling prompts/TB/Makefile), ANY other batch file,
  prior run samples, this run's responses/reports, any scorer output, agent memory.
* MUST NOT run run_benchmark.py / any scorer / any verdict-level oracle.
* MUST NOT write the responses JSONL yourself — the GATE writes it.

## Authoring (per problem)
1. Extract EVERY testable fact from the prompt: exact module name, every port (name/dir/width),
   reset value+polarity+sync/async, latency/timing, every table row + worked example, every
   enumerated set + its outside-the-set/default, signedness, byte order, overflow/sat/rounding,
   handshake timing. For a context (bug-fix/modify) problem: keep the EXACT module name(s),
   ports, params of the given RTL; do ONLY the change the prompt asks; do NOT rewrite from scratch.
2. Author SYNTHESIZABLE Verilog/SystemVerilog. Module name MUST match the context module (or the
   name the prompt says to save, rtl/<name>.sv -> module <name>). The hidden TOPLEVEL is derived
   from the file layout — a name mismatch ELAB-errors.
3. Write the completion to `drafts/batchNN/<id>.sv` — FILE CONTENT = raw Verilog (gate assembles JSON).
4. Self-verify with your OWN reasoning / your OWN mini-TB (host iverilog syntax check ok). NEVER the harness.

## The ONLY emit path (run from the plugin dir)
```
cd /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic
python3 benchmark/cvdp_gate.py --batch-dir <RUN>/drafts/batchNN --out <RUN>/responses/batchNN.jsonl \
    --report <RUN>/reports/cvdp_gate_batchNN.json --prompts <RUN>/batches/batchNN.jsonl \
    --dataset /home/reyerchu/AI_IC_design/_extbench/cvdp_open_v110/cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl
```
