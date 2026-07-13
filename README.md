# Vibe-IC

**AI-native IC design with Claude — from natural-language intent to verified silicon.**

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Awesome](https://awesome.re/badge.svg)](https://github.com/vibeic/awesome-open-ic)
[![Plugin v1.2.96](https://img.shields.io/badge/plugin-v1.2.96-brightgreen.svg)](vibe-ic-marketplace/README.md)
[![MCP-EDA v1.0.0](https://img.shields.io/badge/mcp--eda-v1.0.0-brightgreen.svg)](vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/README.md)

> **Status: v1.3 — mature, benchmark-hardened.** The `vibe-ic` plugin is the
> product: one install bundles and auto-registers the MCP server, the IP
> catalog, and the benchmark harness. Install once, design in natural language.
> Every capability is gated by a deterministic checker and continuously
> hardened against open IC-design benchmarks (see **Benchmark results** below).

Vibe-IC is a Claude Code plugin + Model Context Protocol (MCP) server
that bridges large language models to real open-source EDA tools so that
designers can drive an entire IC flow — from a one-paragraph intent
through L1-L27 design documents, RTL, FPGA verification, and tape-out
sign-off — in natural language, with every step gated by deterministic
checkers (no fabrication, no hallucinated PASS).

---

## What's in this repo

```
.
├── vibe-ic-marketplace/        Claude Code plugin marketplace (+ partner plugins)
│   └── plugins/vibe-ic/         ★ the vibe-ic plugin — one install = everything:
│       ├── skills/  programs/    skills + deterministic programs
│       ├── agents/  commands/  hooks/
│       ├── mcp-eda/                  bundled MCP-EDA server — open-source EDA tools
│       │                          + lab-device wrappers, auto-registered via .mcp.json
│       ├── ip-catalog/           open-source IP catalog (manifests)
│       └── benchmark/            benchmark harness + registry
├── IP/                         open-core git submodules (serv · ibex · sha256 · opentitan)
├── benchmark-data/             benchmark inputs + results (ic/<6 ICs> + evaluation/)
├── tools/                      repo dev / CI utilities
├── LICENSE                     Apache-2.0
├── NOTICE                      Third-party attributions
├── CONTRIBUTING.md             How to contribute
├── CODE_OF_CONDUCT.md          Contributor Covenant v2.1
└── SECURITY.md                 Vulnerability reporting
```

---

## Quick Start

### 1. EDA toolchain (Docker)

All open-source EDA tools (Yosys, OpenROAD, KLayout, Magic, ngspice, …) run
inside a Docker container named `vibeic-eda` (the name the MCP server expects
via `EDA_CONTAINER`). **Recommended — the enhanced fork image** (patched
OpenROAD / yosys / ngspice / magic / netgen / iverilog / klayout with
gatekeeper-verified FAIL→PASS fixes; scoreboard in `tools/vibeic-eda/FIX_STATUS.md`):

```bash
docker pull ghcr.io/vibeic/vibeic-eda:0.2.16   # or build: docker build -t vibeic-eda:0.2.16 tools/vibeic-eda
docker rm -f vibeic-eda 2>/dev/null || true    # "name already in use"? drop the old container first
docker run -d --name vibeic-eda \
  -v "$HOME/AI_IC_design:$HOME/AI_IC_design:rw" \
  -v "$HOME/AI_IC_design:/foss/designs:rw" \
  ghcr.io/vibeic/vibeic-eda:0.2.16 --skip sleep infinity
docker exec vibeic-eda yosys --version         # sanity check — should print a version
```

Stock fallback: `docker pull hpretl/iic-osic-tools:latest` (run it named `vibeic-eda`).
Already running an older tag? Swap without retyping mounts: `tools/vibeic-eda/restart-eda.sh 0.2.12`.
See **[docs/INSTALL.md](docs/INSTALL.md)** for the required bind-mounts (Phase 3 needs the identity mount).

### 2. Install the `vibe-ic` plugin (one step)

Add this repo as a marketplace and install the plugin. This **also bundles
and auto-registers the MCP-EDA server** — no separate `claude mcp add` needed:

```bash
claude plugin marketplace add vibeic/vibe-ic
claude plugin install vibe-ic
```

> The bundled MCP-EDA server is declared in the plugin's `.mcp.json` and
> auto-registers on install; its npm dependencies install on first run via
> the plugin's `post_install` hook.

> Inside an interactive Claude Code session the same two commands are
> `/plugin marketplace add vibeic/vibe-ic` and
> `/plugin install vibe-ic@vibe-ic-marketplace`.

### 4. Design something

```bash
claude "Design a temperature sensor IC: I2C interface, 12-bit, alert
output, SOIC-8 package."
```

Claude will dispatch the appropriate skills, invoke MCP-EDA tools, and
emit L1-L27 design docs + RTL + a verified bitstream.

Optional for full lab integration:

- **Intel Quartus Prime Lite** (free) — FPGA synthesis / bitstream burn
- A Cyclone-/MAX10-family FPGA board (we test on Terasic DE10-Lite)
- A USB scope (we test on Keysight DSO-X 3014T)
- A custom protocol tester or any HID-class USB device (driver template
  in `vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/devices/tester/`)

---

## Design flow at a glance

```
              Natural-language intent
                       │
                       ▼
     ┌────────────────────────────────────┐
     │   Phase 1  (doc / spec extraction) │
     │   L1-L27 JSON design documents     │
     └─────────────────┬──────────────────┘
                       ▼
     ┌────────────────────────────────────┐
     │   Phase 2  (RTL + verification +   │
     │            FPGA prototype)         │
     │   Yosys lint → Icarus sim →        │
     │   SymbiYosys formal → coverage →   │
     │   Quartus synth → SOF → on-board   │
     │   protocol verification            │
     └─────────────────┬──────────────────┘
                       ▼
     ┌────────────────────────────────────┐
     │   Phase 3   (sign-off + tape-out)  │
     │   OpenSTA → DFT → OpenROAD PnR →   │
     │   KLayout DRC → Netgen LVS → GDS   │
     └────────────────────────────────────┘
```

**Every project enters at Phase 1.** Both entry paths — Path A (existing
design docs) and Path B (a natural-language prompt / dialogue) — converge on
the same universal handoff, the **L1-L27 JSON** design-document set. Phase 2
cannot start without it: the canonical-flow gate hard-requires Phase 1's
`generated_docs/L*.json` before any RTL is authored. There is no "skip to
Phase 2" entry — the L1-L27 handoff is what makes the downstream flow uniform
regardless of how the design was specified.

For **analog and mixed-signal** designs, two extra stage tracks
interleave with the digital phases:

- **Analog track — A1-A9.** A1 spec extract (Phase 1) → A2 topology
  select → A3 netlist + sizing → A4 corner sweep (Phase 2) → A5 layout →
  A6 per-block physical verification → A7 post-layout resim → A8 hardmacro
  generation → A9 silicon / hardware verify (Phase 3).
- **Mixed-signal track — M1-M4** (Phase 3). M1 analog+digital GDS merge +
  macro placement → M2 power-domain / level-shifter / isolation check →
  M3 AMS co-sim + interface signal-integrity → M4 top-level PV sign-off.

Throughout, a **canonical-flow compliance gate** verifies that every
required step actually ran (no skipped phases, no waived sign-off), and
a **chip-AGNOSTIC source guard** keeps proprietary IC names out of the
public source tree.

---

## Benchmark results

Vibe-IC is continuously hardened against open IC-design benchmarks. The
number we publish measures **what the deterministic runner chain can do**
(program-first — `vibe_ic_one_shot_runner.py` → phase1/2/3 + plugin programs
+ MCP-EDA), not what a raw LLM can do with the same tools. Every run
discloses any open↔commercial tool substitution and follows the
[open-benchmark methodology](vibe-ic-marketplace/plugins/vibe-ic/skills/open-benchmark-methodology/SKILL.md).

Latest clean-room runs (2026-07-12): **Claude Fable 5** driving plugin
**v1.3.88** + forked `vibeic-eda:0.2.16`. The CVDP figure is from an earlier
campaign with Claude Opus 4.8 (v1.2.96); each score names its model.

| Benchmark | Result | Notes |
|---|---|---|
| **NVIDIA CVDP** (nonagentic code-generation, no-commercial) | **243/302 = 80.46%** official-compliant blind pass@1 *(Opus 4.8, v1.2.96)* | **prompt+context-only** — the deterministic solver reads ONLY `input.prompt` + `input.context`; the hidden test harness (`.env`, cocotb testbench) and the golden solution are OFF-LIMITS oracle, enforced by a regression guard that proves the emit is byte-identical with vs without them. Scored on the official `run_benchmark.py` in the pinned `cvdp-sim` image. |
| **RTLLM v2.0** | **49/50 = 98%** blind pass@1 (**49/49 = 100%** excluding the 1 proven upstream dataset defect) *(Fable 5, v1.3.88)* | spec-to-RTL, runner-driven (Shape B), §4.05-blind, iverilog-scored; single-shot 47/50 = 94%, converged after ONE blind close-loop round. The sole residual (`ring_counter`) is a golden that fails its own testbench — a per-design RESULT entry, not a silent drop. |
| **VerilogEval-v2** | **153/156 = 98.08%** blind pass@1, **single-shot** *(Fable 5, v1.3.88)* | spec-to-RTL, §4.05-blind, iverilog-scored; 130/156 problems emitted by deterministic solvers. All 3 residuals are documented dataset defects / spec ambiguities — the score sits at the defect floor with no close-loop round. |
| **VerilogEval-Human** | **153/156 = 98.08%** blind pass@1, **single-shot** *(Fable 5, v1.3.88)* | code-complete (iccad2023), §4.05-blind, iverilog-scored; 129/156 deterministic emits. |

> **Honesty over score.** Compliance is a structural invariant of the plugin,
> not a runtime convenience — no benchmark run reads the hidden harness or the
> golden reference to inflate a number, and a fresh clean-room re-run reproduces
> the published figure. Tool substitutions (Synopsys VCS → Icarus, Design
> Compiler → Yosys+OpenROAD, …) are disclosed in every `RESULT.md`.

---

## Agent roles & check-in governance

Vibe-IC has **two contribution layers** — keep them distinct:

- **Layer 1 — the public contribution model (what external contributors follow).**
  If you find a bug you either **file a backlog** (a report, no code) **or open a
  PR** (a proposed fix, with code). Both paths are valid and serve different cases
  (report-only vs report-with-fix); one did not replace the other. The
  **repo-gatekeeper** — the single maintainer identity — triages backlogs and
  reviews + **lands PRs into the next version**. External contributors do **not**
  hold the maintainer role and do **not** push to `main`; see
  [CONTRIBUTING.md](CONTRIBUTING.md).
- **Layer 2 — the maintainer-internal improvement-phase shortcut.** While the
  maintainer builds the plugin out, it direct-fixes and **direct-pushes** to
  `main` with every quality **gate retained** (`gatekeeper_review` MERGE_OK +
  adversarial §4.05 no-leak review + a monotonic version bump); only the PR
  *ceremony* is dropped. This is an internal convergence shortcut, **not** the
  public model.

Roles are separated by scenario and — most importantly — by **what each may check
in (git commit)**. The governing rule: **only the maintainer role (the
repo-gatekeeper) edits the plugin or the MCP server.** Any other role that finds a
problem hands it upstream — a **backlog** report, or a **version-less PR** carrying
a fix — and the gatekeeper resolves it into the plugin/MCP. The **repo-gatekeeper**
both authors deterministic chip-AGNOSTIC fixes and gates every change; quality is
guaranteed by the **gates**, not by an author≠approver split.

| Agent | Scenario | May check in to | Plugin | MCP | On finding a problem |
|---|---|---|---|---|---|
| **Field Agent** | General usage / audit | `community/backlogs/` only | ❌ | ❌ | → backlog → gatekeeper lands |
| **Benchmark Agent** | Maintainer official runs + end-user local runs | `benchmark-data/` (plugin/MCP fixes via version-less PR, NO-MIX) | ❌ | ❌ | → version-less PR → gatekeeper lands |
| **Core Agent** (= repo-gatekeeper) | Maintainer | everything (owns plugin + MCP) | ✅ only role | ✅ only role | resolves backlog + lands PRs → fixes plugin/MCP |
| **IC Expert Agent** | Phase 1 — technical review | design-time, no repo check-in | — | — | — |

- The **MCP server lives under the plugin tree** (`plugins/vibe-ic/mcp-eda/`),
  so "cannot touch the plugin" already covers "cannot touch the MCP".
- The **Benchmark Agent** runs *Benchmark Evaluation* (open benchmarks via
  `/vibe-ic-benchmark`) and *Benchmark IC* (the canonical ICs via `/vibe-ic-all`
  → `/benchmark-verify`), and owns `benchmark-data/`.
- The **Field Agent** checks in nothing but the ORGANIC backlog mirror.
- This boundary is **enforced by a deterministic gate**, not by trust —
  `programs/agent_checkin_scope_guard.py --role <role> --staged` (exit 1 lists
  any path outside the role's scope). Each role's charter lives in
  `plugins/vibe-ic/agents/<role>.md`; the full matrix + Capture-Enhancement loop
  is in [`AGENT_USAGE_GUIDE.md`](vibe-ic-marketplace/AGENT_USAGE_GUIDE.md).

---

## Key design principles

1. **Single-agent RTL generation** — multi-agent approaches drift on
   port naming across submodules.
2. **L9 Integration Spec before any RTL** — submodule ports are
   defined once, in one canonical place.
3. **No stub modules** — the top-level instantiates everything.
4. **Real-benchmark fixtures** — every walker / regex / merge patch
   must ship with a real-world doc-shape fixture under
   `tests/fixtures/real_benchmark/`, not just a minimal synthetic case.
5. **Determinism over heuristics** — every check is a Python program
   with a fixed verdict tier (PASS / PASS\_WITH\_WAIVERS / FAIL),
   never an LLM-judged "looks fine".

---

## Documentation

- **Plugin overview & changelog** — `vibe-ic-marketplace/README.md`
- **Plugin install & skills** — `vibe-ic-marketplace/plugins/vibe-ic/README.md`
- **MCP-EDA server & EDA tools** — `vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/README.md`
  and `.../mcp-eda/INSTALL_GUIDE.md`
- **Benchmark methodology** — `vibe-ic-marketplace/plugins/vibe-ic/skills/open-benchmark-methodology/SKILL.md`
- **Agent roles & governance** — `vibe-ic-marketplace/AGENT_USAGE_GUIDE.md`
- **Contributing a new IC class / PDK / gate / skill / device** —
  `vibe-ic-marketplace/docs/CONTRIBUTING_*.md`

---

## Companion project

**[Awesome Open IC](https://github.com/vibeic/awesome-open-ic)** — a
curated, MCP-aware map of every open-source IC design tool, IP core,
PDK, benchmark, standard, and community we have evaluated. Each entry
notes whether the bundled MCP-EDA server already wraps it.

---

## Contributing

We welcome contributions of every size: bug reports, doc fixes, new
skills, new EDA tool wrappers, new device drivers, new benchmark
fixtures. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md) before opening a PR.

For security vulnerabilities, see [SECURITY.md](SECURITY.md) — please
do **not** open a public issue.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

This license is compatible with bundling Vibe-IC alongside open-source
PDKs (SkyWater, GF180MCU, IHP — all Apache-2.0) and open-source EDA
tools (Yosys — ISC; OpenROAD — BSD-3-Clause; KLayout — GPL-3.0 invoked
as a separate program; Magic / netgen — MIT-style). Patent grant is
explicit (Apache-2.0 §3).

## IP ownership & commercial-tool firewall

**Tool vs design.** Vibe-IC is a *tool*, not a *design*. Designs you
produce with it (RTL, netlists, GDS, constraints, test vectors) are
**yours**: Apache-2.0 places no claim and no copyleft on tool outputs —
they are not derivative works of the flow, exactly as a binary compiled
by GCC is not a derivative work of GCC.

**AI-generated RTL.** Where a flow step is AI-authored (spec-to-RTL,
oracle testbenches), the resulting code is held by **you, the user**,
as your work product. Note the current US posture: an AI cannot be
named *inventor* (Thaler v. Vidal, Fed. Cir. 2022), but AI-assisted
output with significant human contribution is ordinary, ownable IP.
Generated flow artifacts carry a provenance header stating exactly
this.

**Manufacturing responsibility.** Foundry sign-off, fabrication
qualification, and product certification are the user's responsibility
— Vibe-IC's sign-off gates are open-source equivalents and named
honest disclosures, not a foundry guarantee.

**Commercial-tool firewall.** The entire 1–44 flow runs on open-source
tools only; Vibe-IC neither bundles nor requires any commercial EDA.
If you substitute a commercial tool for a step (e.g. PrimeTime in
place of OpenSTA), that tool's **outputs are governed by its EULA**,
are your responsibility, and must **not** be contributed back into
this repository. Open↔commercial substitutions are disclosed via
`programs/tool_substitution_disclose.py`.

**Contributions.** Inbound contributions follow Apache-2.0 §5 with an
explicit DCO + patent non-assertion pledge — see
[CONTRIBUTING.md](CONTRIBUTING.md).

---

## Acknowledgements

Vibe-IC stands on the shoulders of an enormous open-source EDA
community. See [NOTICE](NOTICE) for the third-party tools we wrap and
the open standards we implement against.

In particular:

- The **OpenROAD**, **Yosys**, **KLayout**, **Magic**, **ngspice**, and
  **cocotb** projects, whose decades of work make this kind of
  AI-driven IC flow possible at all.
- **IIC OSIC Tools** for the curated Docker image.
- **FOSSi Foundation**, **libre-silicon**, and **RISC-V International**
  for the community + standards.
- **Tiny Tapeout** and **eFabless Caravel** for proving that hobbyist
  tape-out is real.
