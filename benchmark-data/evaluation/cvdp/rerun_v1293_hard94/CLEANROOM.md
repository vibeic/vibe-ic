# CVDP hard-94 CLEAN-ROOM re-run (plugin v1.2.93)

- Subset: the 94-case hard set (fair94/blind94 membership; id-list only, no prior solutions read).
- BLIND: each prompt = input.prompt + input.context ONLY. output.* and harness NEVER read.
- Fresh dir, empty drafts/responses. No prior samples/memory/storage/oracle.
- Emit path: cvdp_gate.py (sole-emit). Scorer: official run_benchmark.py in cvdp-sim-pinned:latest.
- Baseline for comparison: v1.2.63 compliant 243/302 (hard-94 recovery measured here on v1.2.93).
