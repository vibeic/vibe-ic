# Benchmark enhancement capture — runtime evidence consumers

## Recovered failing cases

The fresh u_hawaii_adc v1.15.25 acceptance produced two new false failures after its real producer work had completed:

- A completed, equivalent LEC invocation wrote telemetry whose `pidfile` field names the watchdog marker used during supervision. The marker was correctly removed at child exit, but the delivery-path gate interpreted its absence as lost project output.
- The professional cocotb test ran and passed its six-channel/24-slot scoreboard, but the generic testbench gate omitted all Python TBs and counted only seven Verilog markers.

These are consumer failures. Neither changes the design, the producer output, nor the acceptance threshold.

The same full-suite pre-fix run exposed a third consumer failure: A9's documented headless close was converted to FAIL because HIL-only advisory checks ran with no bench campaign and published an untyped absence. It also exposed two repository self-consistency drifts introduced by earlier reason-taxonomy and flow-census changes.

## AI judgment distilled into deterministic rules

1. A path is runtime process metadata only when it exactly matches the watchdog-owned `/tmp/.vibeic-job-<safe-id>.pid` namespace. It is disclosed and excluded from deliverable accounting. No extension-wide or JSON-wide exemption is allowed.
2. A Python source is canonical cocotb testbench evidence only when its basename matches `tb_*.py`. Structural review uses cocotb semantics (`@cocotb.test`, `async def`, and awaited simulation triggers), and the check denominator counts executable test decorators and independent assertion lines.
3. Existing thresholds stay unchanged. A newly recognised testbench contributes evidence; it does not lower `--min-tests`.
4. A missing hardware campaign is a legitimate `EXTERNAL` non-verdict only while no block carries `hw_measurements.json`. HIL discipline gates must not execute in that arm. Once bench evidence exists, they execute normally and can refuse missing or malformed HIL artefacts.
5. rc 2 is only a non-verdict candidate. Untyped rc 2 remains `EXECUTION_ERROR`/`INCOMPLETE`; tests may not pin the superseded unconditional VACUOUS_PASS convention. Published census numbers must be derived from the canonical flow parser.

## Positive and negative controls

- Positive pid control: completed LEC telemetry with an absent watchdog pidfile must return rc=0 and print `ephemeral process-marker`.
- Negative delivery control: a live external GDS must remain rc=1.
- Positive TB control: five Verilog checks plus one canonical cocotb test containing four assertions must reach exactly ten and PASS.
- Negative TB control: nine Verilog checks with no cocotb evidence must remain rc=1.
- Real artefact: the v1.15.25 u_hawaii_adc project changes from both consumer failures to both direct gates rc=0; professional simulation itself remains 1/1 PASS rather than being inferred from source syntax.

## Generality and blast radius

No chip name, port name, clock name, PDK name, or benchmark path appears in production code. A 34-project cocotb sweep found 0 green-to-red transitions; a four-project watchdog-telemetry sweep found the same intended correction. The general external-artifact and under-coverage controls remain blocking.

## Disclosure boundary

This capture removes only false consumer failures. It does not alter the official origin/main acceptance verdict, promote Analog WAIVED/BLOCKED/VACUOUS states, fabricate missing backend evidence, or treat the local candidate as released code.
