# vibe-ic — Claude Code plugin

**AI-native IC design plugin for Claude Code. Natural-language intent →
L1-L13 design documents → RTL → FPGA SOF → ASIC GDS.**

Version: **0.1.0** · License: Apache-2.0

## What it provides

| Asset | Count | Purpose |
|-------|-------|---------|
| **Skills** | ~85 | Phase 1 doc extraction, Phase 2a RTL + verification, Phase 2b FPGA prototype, Phase 3 sign-off + tape-out, Analog A1-A9, Mixed-signal M1-M4 |
| **Deterministic programs** | ~220 | Canonical-flow compliance checks, structural-RTL gates, anti-fabrication audit suite, IP catalog reproducible pull |
| **Slash commands** | 3 | `/vibe-ic-phase1`, `/vibe-ic-phase2`, `/vibe-ic-phase3` |
| **Guard tests** | externalised | `tests/chip_deny_list.txt` + `tests/test_chip_agnostic_guard.py` keep private IC names out of source |

## Install

```bash
# Add the parent marketplace (one-time)
claude plugin marketplace add <path-or-url>/vibe-ic-marketplace

# Install the plugin
claude plugin install vibe-ic
```

Then in any Claude Code session:

```
/vibe-ic-phase1  Design a temperature sensor IC: I2C, 12-bit, alert, SOIC-8
```

## Dependencies

The plugin invokes the [mcp-eda-server](../../../mcp-eda-server/) MCP
server for real EDA tool execution. Install both — the plugin alone can
draft documents but cannot run synthesis / sim / sign-off.

## Repository layout

```
plugins/vibe-ic/
├── .claude-plugin/plugin.json   Plugin manifest
├── agents/                       PM Agent + IC Expert Agent + lessons
├── commands/                     Slash command definitions
├── flow/                         Canonical Phase 1 / 2 / 3 flow YAML
├── hooks/                        Pre/post hook scripts
├── ip_catalog/                   Open-source IP catalogue (CPU, crypto, periph, …)
├── programs/                     ~220 deterministic gate / check / generator programs
├── skills/                       ~85 skill definitions (SKILL.md per skill)
├── tests/                         Unit + integration tests (incl. chip-AGNOSTIC guard)
├── tools/                        Plugin-side utilities
└── README.md                     This file
```

## Design philosophy

1. **Single-agent RTL generation.** Multi-agent approaches drift on port
   naming across submodules.
2. **L9 Integration Spec before any RTL.** Submodule ports are defined
   once, in one canonical place.
3. **No stub modules.** The top-level instantiates everything end-to-end.
4. **Real-benchmark fixtures.** Every walker / regex / merge patch ships
   with a real-world doc-shape fixture under
   `tests/fixtures/real_benchmark/`, not just a minimal synthetic case.
5. **Determinism over heuristics.** Every check is a Python program
   with a fixed verdict tier (PASS / PASS_WITH_WAIVERS / FAIL), never
   an LLM-judged "looks fine".

## Acceptance criterion

Any "Phase 2+3 complete" claim **must** be self-audited by:

```bash
python3 plugins/vibe-ic/programs/flow_compliance_check.py <project_dir> --strict
```

Verdict tiers:

- `Overall: PASS` — every canonical step executed and verified. Tape-out-ready.
- `Overall: PASS_WITH_WAIVERS` — structurally complete, N steps deferred via
  `waivers.json`. Engineering-complete but **not** tape-out-ready.
- `Overall: FAIL` — incomplete. Keep working.

Individual gate PASSes (e.g. `tapeout_signoff_check 4/4`) are necessary
but **not** sufficient — only the orchestrator verdict counts.

## License

Apache License 2.0 — see [LICENSE](../../../LICENSE) at the repo root.

## Contributing

See [CONTRIBUTING.md](../../../CONTRIBUTING.md) at the repo root.
