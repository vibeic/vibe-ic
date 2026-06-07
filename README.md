# Vibe-IC

**AI-native IC design with Claude — from natural-language intent to verified silicon.**

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Awesome](https://awesome.re/badge.svg)](https://github.com/vibeic/awesome-open-ic)
[![Plugin v0.1.25](https://img.shields.io/badge/plugin-v0.1.25-brightgreen.svg)](vibe-ic-marketplace/plugins/vibe-ic/CHANGELOG.md)
[![MCP Server v0.1.13](https://img.shields.io/badge/mcp--eda--server-v0.1.13-brightgreen.svg)](mcp-eda-server/CHANGELOG.md)

> **Status: v0.1 initial public release.** Expect rough edges. API and
> skill catalogues will stabilise across the 0.x line.

Vibe-IC is a Claude Code plugin + Model Context Protocol (MCP) server
that bridges large language models to real open-source EDA tools so that
designers can drive an entire IC flow — from a one-paragraph intent
through L1-L13 design documents, RTL, FPGA verification, and tape-out
sign-off — in natural language, with every step gated by deterministic
checkers (no fabrication, no hallucinated PASS).

---

## What's in this repo

```
.
├── mcp-eda-server/          MCP server (Node.js) — 24 EDA tool wrappers
│                             + a manifest-driven device framework.
├── vibe-ic-marketplace/     Claude Code plugin marketplace.
│   └── plugins/vibe-ic/      57 skills + 429 deterministic programs.
├── tools/                   CLI utilities (phase1 engine, regression).
├── docs/                    Architecture, design, and tutorial notes.
├── LICENSE                  Apache-2.0
├── NOTICE                   Third-party attributions
├── CONTRIBUTING.md          How to contribute
├── CODE_OF_CONDUCT.md       Contributor Covenant v2.1
└── SECURITY.md              Vulnerability reporting
```

---

## Quick Start

### 1. EDA toolchain (Docker)

All open-source EDA tools (Yosys, OpenROAD, KLayout, Magic, ngspice, …)
run inside the `hpretl/iic-osic-tools` image:

```bash
docker pull hpretl/iic-osic-tools:latest
```

### 2. MCP server

```bash
cd mcp-eda-server
npm install
claude mcp add eda-tools node "$PWD/src/index.js"
```

### 3. Claude Code plugin

Add this repo as a marketplace and install the `vibe-ic` plugin:

```bash
claude plugin marketplace add vibeic/vibe-ic
claude plugin install vibe-ic
```

> Inside an interactive Claude Code session the same two commands are
> `/plugin marketplace add vibeic/vibe-ic` and
> `/plugin install vibe-ic@vibe-ic-marketplace`.

### 4. Design something

```bash
claude "Design a temperature sensor IC: I2C interface, 12-bit, alert
output, SOIC-8 package."
```

Claude will dispatch the appropriate skills, invoke MCP-EDA tools, and
emit L1-L13 design docs + RTL + a verified bitstream.

Optional for full lab integration:

- **Intel Quartus Prime Lite** (free) — FPGA synthesis / bitstream burn
- A Cyclone-/MAX10-family FPGA board (we test on Terasic DE10-Lite)
- A USB scope (we test on Keysight DSO-X 3014T)
- A custom protocol tester or any HID-class USB device (driver template
  in `mcp-eda-server/src/devices/tester/`)

---

## Design flow at a glance

```
              Natural-language intent
                       │
                       ▼
     ┌────────────────────────────────────┐
     │   Phase 1  (doc / spec extraction) │
     │   L1-L13 JSON design documents     │
     └─────────────────┬──────────────────┘
                       ▼
     ┌────────────────────────────────────┐
     │   Phase 2a  (RTL + verification)   │
     │   Yosys lint → Icarus sim →        │
     │   SymbiYosys formal → coverage     │
     └─────────────────┬──────────────────┘
                       ▼
     ┌────────────────────────────────────┐
     │   Phase 2b  (FPGA prototype)       │
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

Throughout, a **canonical-flow compliance gate** verifies that every
required step actually ran (no skipped phases, no waived sign-off), and
a **chip-AGNOSTIC source guard** keeps proprietary IC names out of the
public source tree.

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

- **Architecture overview** — `docs/architecture/`
- **Design rationale** — `docs/design/`
- **Tutorials** — `docs/tutorials/`
- **MCP server install** — `mcp-eda-server/INSTALL_GUIDE.md`
- **Plugin install** — `vibe-ic-marketplace/plugins/vibe-ic/README.md`

---

## Companion project

**[Awesome Open IC](https://github.com/vibeic/awesome-open-ic)** — a
curated, MCP-aware map of every open-source IC design tool, IP core,
PDK, benchmark, standard, and community we have evaluated. Each entry
notes whether `mcp-eda-server` already wraps it.

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
