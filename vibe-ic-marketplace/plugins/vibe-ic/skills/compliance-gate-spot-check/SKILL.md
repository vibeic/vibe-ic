---
name: compliance-gate-spot-check
description: "AI review of actual native tool evidence against original engineering limits, with explicit failures and unmeasured obligations."
tier: verification
paired_program: flow_engine.py
---

# Review native evidence

Read `<project>/reports/flow_engine.json` from the normal public runner. Use
the selected rows' current position and `name` from `flow/steps.json`. The
Router-selected window executes through the sole engine path; this review
adds no gate, alternate runner, receipt, qualification or approval layer.

## Review each native result

1. For each selected row, read `tool_ran`, `native_steps`, `native_metrics`, `metrics`, and the native paths in `reports`. Confirm the tool actually consumed the intended design and corner.
2. Open the underlying tool report. Compare its measurement and operator with the unchanged original spec, PDK or owner limit. Check that a summary did not hide a failed corner, missing input or unexecuted measurement.
3. AI review the result's engineering meaning and physical plausibility. A token, file, stub field or printed PASS is not proof that the intended behavior was exercised.
4. Match simulation transcripts and waveforms to the actual stimulus and observed response. Check that a testbench can distinguish the required behavior rather than printing PASS unconditionally.
5. Follow source facts to the actual consumer. Confirm that citations refer to real source meaning, assertions express the applicable requirement, and bit captures came from the measured simulation or hardware.
6. Compare related native reports for inconsistent inputs, design revisions, corners or numbers. Investigate substantive disagreements through the responsible producer or tool.

Keep failures as failures. A missing native value, missing original limit or
unexecuted selected tool is `NOT_MEASURED`, never an inferred PASS. Describe
what remains unmeasured and why. Preserve analog, mixed-signal and FPGA evidence
where applicable, and preserve all original numeric engineering limits.

Review a proposed exception against the real defect, mitigation and residual
risk. Its text or metadata cannot erase an engineering failure or convert
deferred work into an executed PASS. Follow the owner's current instructions
for handling that remaining work.

## Resolve and record

Trace each finding to the first incorrect producer or consumer. Fix the
design, local native-tool fork or plugin as the current task permits, then
rerun the actual affected tool and review its native result. Do not add another
per-step checker or qualify the tool during an ordinary design run.

Keep the existing per-row AI review and measured duration with the result.
Append any useful narrative to `<project>/reports/compliance_spot_check.md`,
identifying the current table position/name, native report, actual value,
original limit, finding and remaining `FAIL` or `NOT_MEASURED` obligation. Keep
run evidence outside the plugin repository. Use only current authorization
for publishing a report, messaging others, creating an issue or landing a fix.
