# Container native-tool command resolution

## Result

**STATUS**: Bounded source recovery measured; installed Codex/Claude qualification PENDING_ROOT_INSTALL. Source base: 3cd7222ddf65f290a3be07ad23b856da71795fbc, released plugin 1.35.35. The source probe changed doctor from 8/17 to 17/17 and the real KLayout consumer from unavailable to 10 fixture GDS cells. These results qualify the bounded source repair only.

Fresh Codex and Claude MCP clients each connected, exposed 56 tools and returned alive health. Both full eda_doctor calls returned success=false, with 8/17 checks passed. All nine native tool checks failed: yosys, OpenROAD, KLayout, Icarus, Verilator, Magic, Netgen, ngspice and Fault. The returned failures selected unavailable built-in /foss paths. Magic and Fault remained soft failures in the existing doctor contract.

The root investigator's NATIVE_PATH_READBACK.json records command -v success for all nine binaries on the selected container PATH (rc=0). The held image is ghcr.io/vibeic/vibeic-eda@sha256:d3159f09be84ee94a315f83523952afe55e93f48d8eec638e48ec265ed3f2508 (release 0.4.67); its config ID is sha256:8434ad1a10e5c296913add246e4b2ab963d0a249739460558dec4a691cd3466a and container ID is ddb4d23683dabee85939b929ce34d6b44a28c28581eed63965df7f07b9c771c5. This is availability readback, not functional tool qualification. The defect is in the adapter's path selection. No forked tool produced an incorrect output, so Bucket T is inapplicable. This capture author did not run native queries.

## PR rework scope

The PR rework restores the existing deterministic Magic and Fault commands and
all original doctor assertions, including the bare-PATH Fault prohibition.
Container PATH resolution remains for the other tools. Historical 17/17 doctor
and source-patch identities below describe the earlier component experiment;
they do not qualify this reworked tree. New JavaScript controls require Node
and report `MCP_NODE_NOT_MEASURED` when that prerequisite is absent.

## Program First

Bucket A, AUGMENT-EXISTING. The existing mcp-eda/src/index.js owns registered MCP consumers. The source author added a shared deterministic resolver in mcp-eda/src/lib/tool_path.mjs: retain a built-in legacy default when executable inside the selected container, otherwise discover its command on that container's PATH. Preserve an explicit operator command unchanged, including failure when that command is unavailable. A genuinely missing default must also remain a failure. The actual DFT consumer preserves shell quotes in its assembled script and propagates dependency or Fault failures before a success marker or PASS manifest can be emitted.

This uses command origin, executable presence and command discovery. It needs no contextual design judgment, forked-tool patch, per-tool environment framework, new flow row or acceptance gate. The routing subtype mcp_eda.tool_resolution is metadata only and targets the existing MCP index owner. Existing routes, including benchmark.spec_adjudication, are preserved.

## Evidence and limits

The immutable before receipts are under /home/reyerchu/codex_tasks/out/ve-human-parallel-continue-20261102T0134Z:

| Receipt | SHA256 | Returned result |
|---|---|---|
| upgrade/codex-fresh-mcp.json | d10ce85f4d27e6939c161be82c046bc95dcdb6514027289766845f162ac0e8af | CONNECTED, 56 tools, alive, doctor 8/17 |
| upgrade/claude-fresh-mcp.json | 378f65c6c3d6c710b511eca94abef540c39a7cf45ecefda25ad122e32deed5e0 | CONNECTED, 56 tools, alive, doctor 8/17 |
| upgrade/NATIVE_PATH_READBACK.json | c72277453ff165b4907e2a0a6a88ba0440aa325e0cd40f303602cd87b74282a7 | Same container/image, nine commands, rc=0; availability only |

Each receipt binds the released source readback and image digest. The MCP index readback SHA256 is 321b303e3b05366e78e0ff14020f52cc48d691bd9e65bd1bdc87aa1b8c38537d. Connection and tool listing do not qualify the failed doctor checks.

## Source proof and controls

The author's exact four-file patch SHA256 is e9c10b32e819df1f41ee734d3be3b1f44129801af4a3bdee9aee81d1bc12599b. SOURCE_IDENTITY.json binds mcp-eda/src/index.js (7803c5cd369a7be3f6c0bb42a7dd9fc66b44ad918c2b07e7cc5e4071d7f444b7), mcp-eda/src/lib/tool_path.mjs (34b3082875c8a700c3d89a7b88789f6c0624ff8419b9a20a63a285d58df7d942), test_eda_doctor.py and test_mcp_tool_honesty.py. Both native receipts bind the actual loaded source; the candidate also binds its helper hash.

The terminal predecessor/candidate native probes used the same pristine sandbox container a25a540eb001a531f76bc86dbce555084c6ce5f1b33391be21bdd481be41c9e0 and the same held image/config identity. That sandbox had 2 GiB memory, no swap allowance beyond its memory ceiling, network none and a read-only root filesystem. The legacy tree was absent before and after. The predecessor returned doctor 8/17 and gds_parse_unavailable; the candidate returned doctor 17/17 and the real native KLayout PDK-lint consumer measured 10 GDS cells (0 errors, 2 retained fixture warnings). Earlier held-compatibility-state diagnostics are excluded from the terminal evidence.

The candidate component run reports 53 PASS, 0 FAIL, 0 ERROR and 1 existing layout-dependent Dockerfile SKIP. The 13 matched case IDs have predecessor 9 FAIL / 4 PASS and candidate 13 PASS. Existing executable legacy priority, a failing executable legacy tool with no fallback, absent legacy plus absent native tool, and explicit missing operator path are all PASS in both arms. This preserves legacy support and missing-tool refusal. The control-substance classifier credits 8 observed-value failures, 1 undecided None-sentinel failure and 0 presence-only failures; it does not credit all nine as substantive.

DFT controls execute the actual registered handler's assembled script with neutral tool fixtures. The candidate positive observes the fixtures' known scan length 3, coverage value 91 and vector count 5, and emits its expected manifest. Missing Fault, failing ATPG, missing Icarus and missing Yosys each return success=false and emit no PASS manifest. Additional matched component controls cover failing chain, cut and tap operations. The predecessor's missing-command cases spuriously returned success/PASS. Reverting only the quote handling makes the same positive test fail (1 FAIL); the saved mutation records success=false and no manifest. These controls qualify adapter quoting and failure propagation; the fixture's coverage number is not native ATPG coverage. Full native ATPG is NOT_RUN. No retracted diagnostic-order concern is asserted as a defect.

All following receipts are under the same run root's native-tool-fix directory:

| Receipt | SHA256 |
|---|---|
| SOURCE_IDENTITY.json | e750290da893f1fb4b42b2dfca37d2635314d2d5c85f4f11faa8d0fa077be42d |
| TERMINAL_PACKET.json | e87583ac495d3b39edb4961ff311fc8266403aaa52a5792b12e0e073c4764868 |
| candidate.patch | e9c10b32e819df1f41ee734d3be3b1f44129801af4a3bdee9aee81d1bc12599b |
| predecessor-native.json | 6f17cba3850a1046c73e6c0fd7a341899d416cb2a9e1512dd35a1cab788660cf |
| candidate-native.json | 1ef1e5ccc7b5be70c1841893df3bd6a41063a880b9a1019787a3dd6e9bc762c0 |
| component-predecessor.xml | 8667a156fdde3640a37b7d96cd74c13967d7916e3ed5e789835bee662f87aa93 |
| component-candidate.xml | 3d900f266c25b8b935283a277bfdc77276359cd2417afe1cba2e7383873b1af0 |
| component-quote-control.xml | 9d466aa75b8e242162ea303ac9e2a171fa21364eb1497db836fad14dec4a968b |
| matched-controls.json | 0cb9a8b46775f6971687f0709b79402dc1fa47af0ffe9fea1ea58c96ca912398 |
| control-substance.json | e060be41757fcea459e5c8c6b6c36ad17f04acbb0c17519604482a4741b46c90 |
| dft-controls.json | eb6d95985929e3f91c37361978ac5b842399c216fc72c7fd345440465f4c7888 |

Root owns independent review closure, composition, local install and final fresh Codex/Claude MCP qualification. The initial installed clients' 8/17 remains the last measured installed-client result in this capture; the source probe does not replace it. This capture author read saved receipts and ran only metadata emission and document compliance. No benchmark oracle, dataset, scorer, hidden test or official score supplies evidence here.

## Contribution scope

Versionless and uncommitted. Owned source paths are only docs/capture/2026-11-02-mcp-native-tools/CAPTURE.md, docs/capture/2026-11-02-mcp-native-tools/recoveries.json, and vibe-ic-marketplace/plugins/vibe-ic/benchmark/CAPTURE_ROUTING.json. Other local patches and all existing routes retain their contents. Installed caches are outside this task.

Next: /home/reyerchu/codex_tasks/out/ve-human-parallel-continue-20261102T0134Z/native-tool-capture — root reviews the source-bound packet, composes the accepted patch, installs locally and produces final fresh-MCP proof. Capture emission and compliance receipts accompany this handoff.
