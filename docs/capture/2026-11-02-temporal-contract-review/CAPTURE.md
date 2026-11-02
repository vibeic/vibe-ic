# Source-bound temporal interpretation before executable review

## Result

**STATUS**: Documentation-only Bucket-B candidate, uncommitted. This captures prevention of a review error: an executable timing challenge can silently choose whether a timestamped row gives values before a clock edge or drives after it, shifting acceptance and completion by one cycle. The originating symptom comes from the parent agent's completed-review handoff and permitted completed diagnosis; this packet does not independently replay or qualify that design.

Exact base and detached HEAD: `6d546b094fe6f4069a02d2bba9fb5c30dec630c6`, released plugin `1.35.34`. Isolated checkout: `/home/reyerchu/codex_tasks/work/ve-human-temporal-review1102`. External packet: `/home/reyerchu/codex_tasks/out/ve-human-parallel-continue-20261102T0134Z/temporal-capture`.

Permitted source-context report: `/home/reyerchu/codex_tasks/out/ve-human-ic-expert-148/postscore-packet154/REPORT.md`, SHA256 `c1fd38721dc35a43c43f36437fbe0e67eb414cd5a6dc9e43f26a0e9421721826`. It reports a visible-source conditional trace, unresolved input phase, no prompt-proven rejection and native execution `NOT_RUN`. Only that completed report was read; none of its linked prompt, RTL or binding files was opened. Its score mention supplies no authority for the skill or capture.

Only `skills/testbench-gen/SKILL.md` and this capture pair change. The existing `phase2.sim.multi_output_waveform` entry in `benchmark/CAPTURE_ROUTING.json` routes Bucket B to that skill and Bucket A to `programs/waveform_table_conformance_check.py`. Reusing the mapping introduces no flow row, schema, checker, generator or acceptance rule.

## Program First and judgment boundary

The existing `professional_tb_gen.py` producer remains required; its reference-model tiers, normal execution consumers and proof requirements continue to apply. The addition asks an independent IC expert to derive the drive phase, capture edge, settled sample point, output-valid interval, overlap, reset and condition-specific don't-care from the complete visible contract before relying on an executable challenge. It asks the reviewer to explain competing schedules, then select the best source-bound interpretation. A hidden oracle, score or DUT trace cannot choose the convention.

**why_not_bucket_a**: The exact input is visible prose, diagrams and timestamped signal rows that may omit whether a row is a pre-edge value or a post-edge drive. No closed regex or structural rule selects the normative phase for every such contract. Whole-contract engineering adjudication is the residual judgment; existing programs still generate and execute the selected test. This is neither a request to add a checker for missing prose nor a universal one-cycle correction.

Program output is frozen before independent review. A claimed defect still needs an input-derived executable test that fails that exact output, followed by repair passing the same unchanged test, normal gates and fresh review. If adjudication leaves competing interpretations equally supported, retain both and mark the affected timing claim `NOT_MEASURED` with the missing convention. Other source-determined obligations remain in scope. The neutral worked example illustrates alternatives without providing a benchmark solution.

## Validation and evidence bounds

`enhancement_emit.py` consumes `recoveries.json` without bypassing the Program-First gate and emits one Bucket-B section routed to `skills/testbench-gen/SKILL.md`. The existing capture and testbench skill compliance checks inspect this report's structure only. JSON parsing, an exact emitted-section comparison and `git diff --check` inspect the authored documentation. External logs, patch and identity manifest retain the exact results.

These checks do not demonstrate improved review behavior, a functional recovery, native simulation, score change, fresh blind measurement, whole-flow qualification or convergence; all remain `NOT_MEASURED` or `NOT_RUN` in this bounded packet. No dataset, scorer, hidden oracle or author candidate file was read. No installed cache, generated testbench, benchmark score, version or runtime state was changed. No new test is justified by this reversible prose change, and no compliance contract changed.

## Next steps

Proceed to independent review of the exact three-file patch and emitted record. The parent agent owns any later publication; this packet grants no automatic PASS and includes no commit or push.
