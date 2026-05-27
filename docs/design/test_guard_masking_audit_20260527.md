# Test-guard masking audit — both test trees (2026-05-27)

Audit goal: confirm no compliance/quality guard in either test tree is **masked**
(by `xfail`, `skip`, or a vacuous early-return / no-assert body) such that a real
gap could pass CI undetected. Triggered while verifying the v0.1.6–v0.1.9
deterministic Phase-2 generators + dispatcher had compliance coverage.

## Scope
- **plugin tree**: `vibe-ic-marketplace/plugins/vibe-ic/{tests,programs/tests}`
- **mcp-eda tree**: `mcp-eda-server/test/`

## Findings

### 1. One real masked guard — FOUND & FIXED
`mcp-eda-server/test/test_mcp_tool_coverage_inventory.py::test_inventory_completeness`
(every registered MCP tool must be in `TESTED_TOOLS` or `DEFERRED_TOOLS`) was
masked by a stale `@pytest.mark.xfail(reason="regression-from-v2-rename …")`. It
hid **11 unclassified tools**, including all six added this session
(`eda_spec_lint`, `eda_fsm_table_gen`, `eda_truth_table_gen`,
`eda_gate_netlist_gen`, `eda_vector_op_gen`, `eda_rtl_dispatch`).

Fix (committed): classified all 11 in `DEFERRED_TOOLS` with honest rationales
(wrapped pure-Python programs point at their plugin-tree test; the two FPGA tools
cite their Quartus/lab dependency) and **removed the xfail** so the gate is
load-bearing again. vibe-ic `6b30f7b`; AID `aed4d5fe0`.

### 2. No other masking — verified clean
| Check | plugin tree | mcp-eda tree |
|---|---|---|
| `@pytest.mark.xfail` markers | 0 (all 81 cleared earlier) | 0 (the 1 above removed) |
| Actual `skipped` at runtime | **0** | **0** |
| `skipif` markers | 13 — all legit env/deny-list conditionals; do not trigger here (iverilog present; `CHIP_NAME=AS3616`, `TESTER_NAME=MD-905` populated from `chip_deny_list.txt`) | 3 — legit (`node`, `yosys`); do not trigger here |
| `pytest.skip()` calls | 7 — env/deny-list conditional; do not trigger here | — |
| Vacuous bodies (no-op / `assert True` / no-assert) | none real — the one early-return is *after* a real `assert`; `pass` lines are inside embedded fixture code-strings; the one no-assert test (`test_preset_self_check_on_empty_and_known_inputs`) delegates its assertion to `cvg.self_check()` which raises on divergence | none |

### 3. Deeper recheck — expanded masking-pattern sweep (also clean)
A second pass widened the search beyond xfail-marker / skip / early-return to the
subtler masking patterns, across both trees:

| Pattern | Result |
|---|---|
| runtime `pytest.xfail(...)` (not a marker) | 0 |
| unconditional `@pytest.mark.skip(...)` | 0 |
| `assert` swallowed by a `try/except: pass|continue|return` (AST-checked) | 0 |
| tautological asserts (`assert True` / `assert 1` / `... or True`) | 0 |
| test functions with no effective assertion (AST-checked, both trees) | 0 |
| commented-out asserts / `if False:` / empty-iterable dead guards | 0 |
| `pytest.skip()` / `skipif` that skip on *failure* (vs resource-absent) | 0 — all 20 are resource/env conditionals (`iverilog`, `node`, `yosys`, generator/tool/deny-list-token presence) |

### 4. Source/program GATE vacuous-pass audit (the most important class)
Beyond the test trees, the checker/gate PROGRAMS themselves (364 emit a PASS/FAIL
verdict) were audited for **vacuous-pass**: returning a clean PASS when the gate
could not actually run (input/path/doc absent), thereby shipping a false "OK".

Method: AST scan for `if <input absent> → PASS-verdict` branches, progressively
refined to exclude the legitimate "no findings → PASS" pattern, helper functions
that return a 0 count/score, and N/A branches that carry a documented reason.

- Start 231 → (drop "no findings/failures/offenders → PASS") 36 → (gate-verdict
  path only, drop helper `return 0`/`0.0`, drop reasoned N/A) **3** → all 3 are
  string-literal false positives (`"pass --list-structural-gates"` usage text;
  `"…PASS…"` inside a `failures.append(...)` message; `"PASS"` near power-report
  generation). **0 genuine vacuous-pass gate bugs remain.**
- The two real vacuous-pass bugs that DID exist were found + fixed earlier this
  session: `tools/phase1_engine/gap_detect.py` (dead `vibe-ic-core` KB path made
  the phase1 required-fields hard-gate vacuous-pass) and
  `self_audit_doc_claim_consistency_check.py` (hard-coded `_BENCH_ROOT` never
  matched → scan vacuous-passed). Both now repointed/discovery-based.
- Remaining "absent → PASS" branches are legitimate: gate N/A passes WITH
  documented reasoning (e.g. hw_acceptance "gate not yet applicable" backstopped
  by flow_compliance; single_bus_driver "not half-duplex / no rtl yet";
  no_protocol "applies: False"; optional L10–L12 layers) or helper count/score
  returns on malformed input. The framework also has an explicit VACUOUS_PASS
  verdict tier (flow_compliance_check rc=2) for genuinely-vacuous runs.

## Final state (full-suite, no masking)
| Tree | Result |
|---|---|
| plugin | **4022 passed**, 0 failed / 0 skipped / 0 xfailed / 0 xpassed |
| mcp-eda | **120 passed**, 0 failed / 0 skipped / 0 xfailed / 0 xpassed |

Both trees are genuinely all-green with **no masked or vacuous guards**. The only
actionable item (the coverage-inventory xfail) was fixed; this audit found nothing
further to repair.
