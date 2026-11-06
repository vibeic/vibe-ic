---
name: catalog-glue-author
description: When design_one_shot_runner.step_rtl_gen WAIVES rtl_gen and ip_catalog_query has emitted matches, this skill pulls the matched open-source IP RTL into the project's canonical phase2/stage1/rtl/ directory and authors only the integration wrapper / chip-top + OpenLane config glue from L1-L27 spec. Replaces full-from-scratch spec-to-rtl authoring for SoC-class designs where pre-validated open-source IPs exist in the catalog. Triggers automatically when phase2 WAIVES with `fallback_skill=catalog-glue-author`.
---

# Author catalog integration glue

Use the existing `ip_catalog_query.py` results and the source documents to
select an IP implementation. Read its public interface and licensing terms.
Stage only its required RTL dependencies in the project's canonical RTL input
set, using an available local mirror or the explicitly selected public source.
Do not access benchmark oracles or grading harnesses.

Implement the wrapper from the actual port, clock, reset, parameter and bus
contracts. Preserve widths, signedness, reset polarity, struct/array ordering,
endian conversion and protocol timing. Tie off only inputs whose required
inactive behavior is documented. Keep internal housekeeping signals out of the
external chip pin contract unless the input requires them.

Run the selected native elaboration, lint, simulation and synthesis window.
Read diagnostics for unresolved modules, black boxes, truncated buses, unused
clocks and parameter mismatches. Verify any semantic rename or adaptation with
a source-derived executable test. Review reused IP and authored glue
independently. Record source paths and license obligations as useful project
information, without a hash or manifest admission gate.

Read the selected rows in `<project>/reports/flow_engine.json` and open their
native `reports`. `flow/steps.json` names each current tool and
`flow/native_limits.json` retains its original limits. Review `tool_ran`,
`native_steps`, `native_metrics`, and each metric's value, operator and limit.
A missing native measurement is `NOT_MEASURED`. AI reviews the engineering
meaning of every result and fixes problems in the design, tool or plugin.

```bash
python3 programs/flow_engine.py report --project <project>
```

## AI authoring contract (Step 5)

When AI authors the chip-top wrapper, it MUST:

1. Read ONLY:
   - `<project>/input/docs/L*.md` (the spec)
   - `<project>/phase2/stage1/rtl/` (the pulled IPs — to see their port interfaces)
   - The Plugin's catalog manifest for each pulled IP (for parameter defaults + integration_notes)

2. AI MUST NOT:
   - Read original reference repos (oracle path)
   - Look at any existing chip-top wrapper from the open-source repo
   - The integration_guide.md serves as documentation; AI is allowed to read it

3. AI MUST author files with explicit attribution comments:
   ```verilog
   // SPDX-License-Identifier: <user's choice>
   // Author: Vibe-IC Plugin catalog-glue-author skill
   //
   // This module is the integration wrapper. It instantiates the
   // following open-source IPs (license: see source repos):
   //   - serv          (ISC,    github.com/olofk/serv@1.4.0)
   //   - shared_sram_rf (Apache-2.0, github.com/olofk/subservient@0.2.2)
   //
   // The instantiations and port wiring below are AI-authored from
   // input/docs/L3 + L8 spec. Sub-module RTL is unmodified from
   // its open-source upstream and is governed by its respective
   // license.
   module <name_from_L1.product_name>(...);
       // ... AI-authored instantiations
   endmodule
   ```

4. Verify the authored wrapper through native elaboration, lint and the
   source-derived behavioral tests. Keep the actual selected RTL/header set
   available to both synthesis and simulation.

### Synchronous reset at an external memory interface

Read the complete input's memory retention and sampling obligations before
choosing the external memory protocol. Synchronous internal reset alone does
not authorize a pending write at the first edge that samples reset. If the
input requires all memory contents to retain throughout reset assertion, the
chosen protocol must suppress writes at that first edge and throughout held
reset. A declaration cannot introduce a first-edge exception to that input.
If the input explicitly permits a preceding transaction to commit at that
edge, declare that boundary and test the permitted behavior separately.

Preserve the complete registered transaction: write-enable launch, address and
data must stay aligned. For a memory that consumes writes only at the declared
clock edge, an external reset admission qualifier over the registered launch
can satisfy whole-memory retention without asynchronously resetting core
state. Check the actual sampling rule and all reset-edge transactions before
using this design. A memory that writes on a write-enable transition or during
an active level needs its own protocol analysis; this guidance does not make
raw reset qualification safe for those interfaces. Follow any separately
specified asynchronous safety behavior and any required port-waveform rule.

Distinguish an unsampled port waveform from a consumed memory transaction.
When the input allows a clock-sampled protocol and does not require a constant
between-edge write-enable waveform, record that waveform change diagnostically
and compare actual memory contents, firmware results and cycle counts with the
unpulsed baseline. Keep address/data alignment and observed core-state checks;
a reset pulse wholly between sampling edges must not change the sampled
execution. Require an observed active injection point before crediting reset
retention, and check every memory byte through the first edge and held reset.

Preserve the original native behavior checks and their results. If an earlier test enforced an extra
port-waveform condition from a prior protocol choice, freeze it and author a
new, separately identified protocol test; retain its input-derived memory,
firmware and reset assertions and known-bad value controls. Declare required
free choices through `spec_declaration_emit.py --set`, preserve imported IP
pins, and attribute the authored-glue correction separately. Do not waive an
input retention failure or alter a reported result to admit a repair.

### Skill: Defined idle values at a registered external memory boundary

**Pattern**: Reused minimally reset IP can expose undefined scratch address or write data while its client admission is known inactive, and registering that payload can leak X/Z onto the public memory interface.

**When to apply**: An authored integration wrapper publishes a continuously available memory address or observable write-data output around reused IP with minimally reset internal datapaths.

**What to do**: Trace the real internal read and write admissions and the external sampling contract. Where the input leaves idle payloads free, retain or select a legal defined idle address and choose a defined idle write-data value. Preserve every active transaction address/data and its registered write-enable alignment, read latency, first reset edge and whole-memory retention. Use ordinary conditional four-state merging for uncertain admission; never treat X/Z as inactive. A cycle indication is not automatically a read-enable. Keep the normal reset and CPU tests unchanged and rerun them through both the core and generated pad top; include a reverse control and a reset-write mutant.

**Worked pattern** (anonymized): A shared byte memory had correct computed store/load results but an undefined idle address and idle write data after reset release. Selecting known idle payloads only when the corresponding admissions were inactive cleared both native failures; reversing the wrapper change restored both, while a reset-write mutant still corrupted memory.

**Why this is GENERAL**: This is integration and protocol craft for reused minimally reset IP and external memories. It adds no register reset, signal-name heuristic, checker exemption or alternate simulator model.

_Captured by benchmark-enhancement-capture 2026-10-19._

### Do NOT declare a port you cannot drive (HARD)

`tie_offs` means "the chip-top wires this L9 interface to a constant or an
internal net **instead of** a pad". It does **not** mean "this port does not
exist". Vendor docs frequently describe a **newer / superset integration
wrapper** than the revision staged in `input/vendor_rtl/` — an outer top that
adds redundancy, integrity or scrambling interfaces the staged sources simply
do not contain. Listing those under `tie_offs` asserts the delivered IC has a
safety surface it does not have, and buys a PASS by lying. Never do it.

Compare the actual declared ports of the instantiated IP revision with the
wrapper and source integration contract. A reference document may describe a
newer or superset variant. Disclose that difference; do not invent a port,
claim a safety feature that is absent, or silently drop an actual required IP
port. Verify each real adaptation through native elaboration and behavioral
checks. An interface manifest does not substitute for those measurements.

## Synthesis-safe parameters (`synth_safe_params`)

When the catalog manifest for a pulled IP declares a `synth_safe_params`
list, AI MUST apply each `param → synth_safe_value` **by default** on
every SYNTHESIS instantiation of that IP, overriding the manifest's
`interface.parameters[].default`. The canonical case is a simulation-only
`generate` block gated by a `sim` / `debug` parameter that uses PLI or
system tasks (`$value$plusargs`, `$fopen`, `$display`, `$readmemh`):
yosys cannot elaborate those tasks, so instantiating with the sim value
(e.g. `sim = 1`) aborts synthesis, while the synth-safe value (e.g.
`sim = 0`) synthesises cleanly and the functional oracle still passes.
Read each pulled IP's `manifest.yaml.synth_safe_params`; for SERV this
pins `.sim(1'b0)`. The reference TB / functional oracle may still drive
the sim value during simulation — only the synthesis instantiation is
pinned to the synth-safe value. Document the applied pins in
`declaration.json` (e.g. `synth_safe_params_applied`).

## SystemVerilog inputs

Stage the IP's complete SystemVerilog sources, packages, and include headers.
The public runner passes those sources to native LibreLane/Yosys synthesis.
Keep the original files so the simulation and synthesis tools can each apply
their intended language and macro settings. Read the native compiler report
for unresolved modules, includes, and unsupported syntax, then fix the source
selection or the local tool fork.

## License review

Read each selected IP's actual license and preserve its attribution and
redistribution obligations. Confirm compatibility with the project before
including the IP. The removed pull program supplies no license verdict.
