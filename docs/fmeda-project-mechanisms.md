# Project-local FMEDA mechanism declaration

Status: pre-implementation contract, 2026-10-20. Owner: `fmeda_fault_injection_coverage.py`; ordinary consumer: `fmeda_coverage_check.py`. This is an author engineering declaration of implementation choices, not a requirement, safety verdict, correction capability, or full FMEDA claim.

The optional input is `phase2/stage1/fmeda_mechanisms.json`. Absence preserves existing auto-detection and classification. A present invalid declaration refuses; it never falls back to auto-detection. A previously declared report cannot be consumed after declaration removal.

```json
{
  "schema": "vibeic.fmeda-mechanisms.v1",
  "authority": "AUTHOR_ENGINEERING_DECLARATION",
  "top_module": "component",
  "rtl_files": [{"path": "phase2/stage1/rtl/component.sv", "sha256": "<64 lowercase hex>"}],
  "mechanisms": [{
    "id": "payload_integrity", "kind": "parity",
    "encoder": {"module": "payload_encode", "instance": "component.checker.encoder", "input": "data_i", "output": "code_o"},
    "checker": {"module": "payload_check", "instance": "component.checker", "input": "code_i", "detect": "err_o", "corrected_output": null},
    "data_width": 3, "code_width": 4
  }]
}
```

The exact current authored RTL/header inventory is collected by `_specrtl_common.rtl_source_files`; declaration order is recorded, and `testbench_gen.package_first_order` supplies only the native compilation order. No excluded or unlisted file, duplicate key/ID/path, symlink, path escape, unsupported port, invalid integer, or missing source is admissible. Top must equal `p0_tool_frontend_check._top(project)`, the existing L9 reader also used by `_cdc_netlist.source_binding`; the declaration cannot choose an alternate root. L9 bytes are part of the input identity.

The L9 identity binds the selected top and current document bytes. Top-level L9 port conformance remains owned by the existing P0/spec-conformance checks; this capability measures the declared mechanism leaf ports. The encoder may be the checker's internal expected-tag recomputation. Its reachable identity calibrates a standalone codeword model, not a claim that its output is the received-codeword wire or that the campaign injected an in-place whole-DUT instance.

A fresh bounded Yosys `read_slang --keep-hierarchy --single-unit --top <selected>; hierarchy -check -top <selected>; proc; write_json` run, without flatten/ABC/mapping, must establish each declared instance is reachable from that top and has the declared module and literal measured port directions/widths. All input ports of the standalone combinational mechanism must be accounted for; unsupported shapes refuse. The native artifact, command, return code, tool identity, source population, top, and declaration hashes are retained. The ordinary consumer rechecks current identity and validates the bound native hierarchy. It does not trust regex success, a self-reported width, or a PASS label.

Parameterized encoder/checker modules and their reachable module dependencies are currently unsupported, including a parameter whose override preserves all port widths. Slang's lowered JSON omits effective parameter values while standalone FI would instantiate defaults. A bounded source-declaration check therefore refuses such selected subtrees in both producer and consumer, including declarations containing macro/directive tokens that could expand into parameters; it never treats an absent regex match as native elaboration proof and does not implement macro expansion. Unrelated parameterized implementation modules remain permitted. Supporting effective specialization requires a separate explicit tool-derived parameter binding, not guessed defaults.

Each mechanism runs the existing real Icarus single-bit engine independently. Every selected stimulus requires one known fault-free encoding and DETECT=0. Detection-only mode requires `corrected_output:null` plus an explicit detect port: MATCH is typed `NA`, never invented 1; each fault is covered only when DETECT=1. Correction-capable mode retains the old DETECT OR MATCH rule. Explicit complete CLI wiring may also establish detection-only mode; incomplete/auto-guessed missing correction does not.

The expected census is the Cartesian product of the deterministic stimulus list and every bit `[0,code_width)`. Full baseline and fault rows plus raw transcript are retained without the legacy 512-row preview cap. The consumer recomputes census uniqueness/completeness, known baseline, row coverage, DC, and ASIL floor for every mechanism separately. No weighted average can mask a failing mechanism. It replays the retained raw transcript and compares all rows/counts; missing rows, invented match, baseline false alarm, altered source/ports/instance/top/declaration/native artifact, or stale evidence refuse.

Required controls: two reachable neutral mechanisms; native width/type/direction/unreachable and source/hash changes; duplicate keys/IDs; declaration removed; baseline false alarm; disabled detector for each mechanism; >512 faults with a row removed; per-mechanism floor masking; byte restoration; correction-mode compatibility; unchanged absent-declaration classification. No global gate, policy/threshold, version, or auto-pairing repair is included. Scope is the measured codeword boundary and current reachable implementation modules, not whole-chip safety qualification or FIT/SPFM/LFM/PMHF.
