# Vibe-IC

**AI-native IC design with Claude — from natural-language intent to verified silicon.**

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Awesome](https://awesome.re/badge.svg)](https://github.com/vibeic/awesome-open-ic)
[![Plugin v1.16.41](https://img.shields.io/badge/plugin-v1.16.41-brightgreen.svg)](vibe-ic-marketplace/README.md)
[![MCP-EDA v1.0.0](https://img.shields.io/badge/mcp--eda-v1.0.0-brightgreen.svg)](vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/README.md)

> **Status: v1.16 — mature, benchmark-hardened.** The `vibe-ic` plugin is the
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
├── benchmark-data/             design INPUT only (542 files) — results moved to vibeic/benchmark-data
│   ├── ic/                      9 canonical benchmark ICs driven doc → RTL → GDS
│   └── evaluation/              7 open-benchmark / parity evaluation sets
├── benchmark_external/         external-benchmark harness notes (CVDP legal-input definition)
├── tools/                      repo dev / CI utilities (second pytest tree)
├── docs/                       repo-level guides — INSTALL.md · governance runbook
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
export VIBEIC_DESIGNS="/path/to/your/designs"  # ← your project / designs folder (must already exist)
[ -d "$VIBEIC_DESIGNS" ] || { echo "VIBEIC_DESIGNS must point at an existing directory"; exit 1; }
docker pull ghcr.io/vibeic/vibeic-eda:latest   # canonical image; to build from source: git clone https://github.com/vibeic/vibeic-eda
docker rm -f vibeic-eda 2>/dev/null || true    # "name already in use"? drop the old container first
docker run -d --name vibeic-eda --memory 48g --memory-swap 48g \
  -v "$VIBEIC_DESIGNS:$VIBEIC_DESIGNS:rw" \
  -v "$VIBEIC_DESIGNS:/foss/designs:rw" \
  ghcr.io/vibeic/vibeic-eda:latest --skip sleep infinity
docker exec vibeic-eda yosys --version         # sanity check — should print a version
```

Stock fallback: `docker pull hpretl/iic-osic-tools:latest` (run it named `vibeic-eda`).
Already running an older tag? Swap without retyping mounts:
`tools/vibeic-eda/restart-eda.sh` (no argument = the newest vibeic-eda image this
host holds, pinned to its digest), or pass a tag explicitly.
See **[docs/INSTALL.md](docs/INSTALL.md)** for the required bind-mounts (Phase 3 needs the identity mount).

**This repo does not record which vibeic-eda version you should run.** It used to:
a one-line `tools/vibeic-eda/VERSION` held the number, every install doc had to
match it, and every vibeic-eda release therefore opened a PR here. That file is
gone. `docker pull …:latest` above gets the current image, and anything in the
plugin that needs to name an image asks `_eda_image.judged_image()`, which asks
the image two questions and stores neither: its **digest**
(`ghcr.io/vibeic/vibeic-eda@sha256:…`, what you replay with) and its own standard
`org.opencontainers.image.version` **label** (what a human reads). Gates that
report a verdict *about* the image write both into their `--json` report, so any
finding can be replayed with `--image …@sha256:…` and any red is attributable to
specific bytes rather than to a tag whose meaning moved. An image that will not
say which release it is, or that this host cannot identify, is `NOT_MEASURED` —
the gate exits 2 rather than reporting a clean PDK it never opened.

**PDKs.** The flow resolves PDKs through
`plugins/vibe-ic/programs/pdk_registry.json`:

| PDK | What it is |
|---|---|
| `sky130A` · `gf180mcuD` · `ihp-sg13g2` | open foundry PDKs — the real sign-off targets |
| `nangate45` · `asap7` | **generic / predictive research-and-education enablements** — full LEF + Liberty + GDS so synth / PnR / CTS / STA and area-timing comparison run, but each is marked `tapeout_capable=false` in the registry: no real foundry, no manufacturable layer stack, and the shipped DRC decks are educational rule-checks, **not** sign-off |
| `custom_auto_detect` | a PDK you stage yourself, auto-detected from its on-disk layout |

A **commercial PDK** is supported as a *mechanism* only: the resolver reads a
`VIBEIC_COMMERCIAL_PDK_ID` env var (or a private, gitignored user config) and
never carries a vendor identifier in this repo — see
`plugins/vibe-ic/programs/_commercial_pdk.py`. No PDK is bundled with the plugin.

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

### 3. Design something

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
number we publish measures **what the canonical benchmark entry and its
deterministic gate/runner chain can produce**, not what a raw LLM can do in
isolation. Every run discloses any open↔commercial tool substitution and follows the
[open-benchmark methodology](vibe-ic-marketplace/plugins/vibe-ic/skills/open-benchmark-methodology/SKILL.md).

**Every row names the authoring model and the plugin version that produced it —
not today's plugin version.** The newest attributable campaign is GPT-5.6-Sol on
plugin **v1.10.45** (2026-08-16). The Claude reference runs use Fable 5 on
**v1.4.81** for VerilogEval and **v1.3.88** for RTLLM. These are therefore
published **model + plugin** datapoints, not a controlled model-only experiment.
Single-shot and one blind close-loop score are kept in separate columns.

| Benchmark | Model · plugin | Clean single-shot | After one blind close-loop | Notes |
|---|---|---:|---:|---|
| **NVIDIA CVDP** (nonagentic code-generation, no-commercial) | Opus 4.8 · v1.2.63 | **243/302 = 80.46%** | — | Official-compliant prompt+context-only blind pass@1. The hidden harness and golden are off-limits, enforced by a byte-identity regression guard; scored by official `run_benchmark.py`. |
| **RTLLM v2.0** | Claude Fable 5 · v1.3.88 | **47/50 = 94.0%** | **49/50 = 98.0%** | Runner-driven Shape B; one proven upstream defect in the final scorer record. |
| **RTLLM v2.0** | [GPT-5.6-Sol · v1.10.45](https://github.com/vibeic/benchmark-data/tree/main/evaluation/rtllm/v1.10.45_gpt_5.6_sol) | **48/50 = 96.0%** | **49/50 = 98.0%** | Runner-driven Shape B. The sole official residual is an Icarus language-dialect scoring gap; the immutable official score remains 49/50. |
| **VerilogEval-v2** | Claude Fable 5 · v1.4.81 | **153/156 = 98.08%** | — | Shape C, official Icarus harness; no scored recovery round. |
| **VerilogEval-v2** | [GPT-5.6-Sol · v1.10.45](https://github.com/vibeic/benchmark-data/tree/main/evaluation/verilogeval_v2/v1.10.45_gpt_5.6_sol) | **153/156 = 98.08%** | — | Shape C; all 156 samples gate-emitted. Residual RCA did not patch or rescore a sample. |
| **VerilogEval-Human** | Claude Fable 5 · v1.4.81 | **154/156 = 98.72%** | — | Shape C, official Icarus harness; no scored recovery round. |
| **VerilogEval-Human** | [GPT-5.6-Sol · v1.10.45](https://github.com/vibeic/benchmark-data/tree/main/evaluation/verilogeval_human/v1.10.45_gpt_5.6_sol) | **153/156 = 98.08%** | **154/156 = 98.72%** | Shape C; one prompt-only recovery was emitted through the same gate before rescoring. |

*Historical note:* VerilogEval-Human was 153/156 on the earlier Fable 5 / v1.3.88
run and rose to 154/156 on the v1.4.81 clean-room re-run. The GPT rows are
separate model+plugin measurements; they do not supersede the Claude rows.

> **Honesty over score.** Compliance is a structural invariant of the plugin,
> not a runtime convenience — no benchmark run reads the hidden harness or the
> golden reference to inflate a number. Published artifacts, identity
> attestations, and exact scorer commands make each figure independently
> reopenable and rerunnable. Tool substitutions (Synopsys VCS → Icarus, Design
> Compiler → Yosys+OpenROAD, …) are disclosed in every `RESULT.md`.

---

## The benchmark corpus — `benchmark-data/`

Every number above is backed by published files. **The results live in a separate
repository — [vibeic/benchmark-data](https://github.com/vibeic/benchmark-data)** —
because they were 78% of this repo's files and 85% of its bytes, and every clone,
every hygiene sweep and every landing gate paid for carrying them.

| Where | What it holds |
|---|---|
| [vibeic/benchmark-data](https://github.com/vibeic/benchmark-data) `ic/` | the canonical benchmark ICs, driven end-to-end (documents → RTL → GDS) |
| [vibeic/benchmark-data](https://github.com/vibeic/benchmark-data) `evaluation/` | open-benchmark runs — VerilogEval, RTLLM, CVDP — plus the Phase-1 parity sweep |
| `benchmark-data/**/input/` **here** | the 542 design-input files. They are INPUT, not output: the flow reads them directly, so they stay with the flow rather than with the results. |

The results repository is a **snapshot without history** — its commit SHAs do not
correspond to anything here. To read how a result came to be, use this repo's history
for the same path; the files were removed, not the record of them.

A local working tree still grows far larger than either (re-run outputs, `clean_run_*/`
and other generated directories are gitignored, not committed). The upstream CVDP
problem sets are **not** vendored — `benchmark-data/datasets/` is gitignored as "not
ours to redistribute"; fetch them from NVIDIA's `cvdp-benchmark-dataset` at the version
each `RESULT.md` pins.

Two audiences, two entry points. If you are **checking a published claim**, read
the `RESULT.md` / `BENCHMARK_VERIFICATION_REPORT.md` at the top of the relevant
directory — each row names the artifact that evidences it, so a claim can be
traced to a file rather than taken on trust. If you are **re-running**, take only
the `input/` sub-tree; everything else is output and is regenerated.

### `ic/` — the 9 canonical benchmark ICs

The ICs we push through the *whole* flow under the corrected protocol in
[`ic/METHODOLOGY.md`](benchmark-data/ic/METHODOLOGY.md), whose hard rule is that
the input is **curated design documents only** — no RTL, no reference netlist —
so a run cannot quietly copy the answer it is being scored against.

| IC | What it is |
|---|---|
| `spm` | configurable N-bit serial-parallel integer multiplier |
| `sha256` | SHA-256 hash core |
| `subservient` | bit-serial RISC-V core |
| `ibex` | 32-bit RISC-V CPU core |
| `opentitan_aes` | AES block from the OpenTitan family |
| `caravel_user_project` | user-project harness for the Caravel SoC frame |
| `u_hawaii_adc` | **the analog / mixed-signal one** — runs the Analog A1-A9 track (spec → topology → sizing → corner sweep → layout → post-layout resim → hardmacro) rather than the digital Phase-3 track |
| `edge_llm_accel` | 64×64 weight-stationary INT4 systolic GEMM core, driven doc → GDS on the `nangate45` enablement |
| `edge_llm_matmul_accel` | one INT4 matmul tile — the plain-language-dialogue → IC sample (front door, blind), on `sky130` |

A typical IC directory:

```
ic/<name>/
├── input/docs/          the ONLY legal input — curated design documents
├── phase1/generated_docs/L*.json    the L1-L27 handoff Phase 2 requires
├── phase2/              generated RTL, lint, simulation
├── phase3/              synth · PnR · DRC/LVS · GDS  (analog/ for the AMS track)
├── reports/             per-gate JSON + coverage + the phase audits
├── sim/                 simulation artifacts
├── RESULT.md            the verdict, per-phase, with the evidence path per row
├── SOURCE_MANIFEST.md   provenance of anything reused
└── clean_run_*/         one self-contained dir per clean-room re-run
```

`clean_run_*/` is why the tree is large and is deliberate: a new run never
overwrites an older verdict, so a regression stays visible instead of being
silently replaced.

Where the six-pillar
[`/benchmark-verify`](vibe-ic-marketplace/plugins/vibe-ic/skills/benchmark-verify/SKILL.md)
gate (functional coverage · 56-step comparison vs the open-source reference ·
code coverage · FPGA verification · analog closed-loop · design-for-ECO
readiness) has been driven to completion, the IC also carries a
`BENCHMARK_VERIFICATION_REPORT.md` — present today for `spm`, `sha256`,
`subservient`, and `u_hawaii_adc`.

### `evaluation/` — the 7 evaluation sets

Results from public benchmarks and from our own parity sweeps. Each set keeps
its version/model cells plus a `RESULT.md` and `RUN_MANIFEST.json` naming the
plugin version, authoring model, scorer evidence, and exact toolchain identity
that produced the number.

| Set | Tracked size | What it is |
|---|---|---|
| `phase1_parity` | 139 MB | the **87-protocol Phase-1 parity sweep** — does the deterministic Phase-1 engine extract the same protocol facts as the AI reference? One directory per protocol, each holding the engine's `phase1/generated_docs/L*.json` and the extraction-coverage / parity reports under `reports/` |
| `cvdp` | 7.6 MB | NVIDIA CVDP campaign — the compliance-hardened re-runs behind the 243/302 figure |
| `verilogeval_v2` | 2.5 MB | VerilogEval-v2 spec-to-RTL runs |
| `verilogeval_human` | 1.3 MB | VerilogEval-Human code-completion runs |
| `rtllm` | 286 KB | RTLLM v2.0 spec-to-RTL runs |
| `verilogeval_machine` | 275 KB | VerilogEval-Machine runs (earlier campaigns) |
| `interconnect` | 12 KB | chip-to-chip interconnect benchmark **anchors** — manifests with pinned upstream commits + licenses; the upstream RTL is fetched on demand, not vendored (see its [`README.md`](benchmark-data/evaluation/interconnect/README.md)) |

Sitting alongside them are the cross-cutting ledgers — `FAIL_CASE_LEDGER.md`,
`RESIDUAL_DEFECTS.md`, and the per-campaign `RESULT_*.md` — which record the
failures and the known dataset defects rather than only the wins.

### Upstream datasets — fetched, not vendored

The CVDP problem sets (`cvdp-benchmark-dataset`: one `.jsonl` per dataset version
and split — agentic / nonagentic × code-generation / code-comprehension ×
commercial / no-commercial) are **input we did not author** and are **not** kept
in this repo: `benchmark-data/datasets/` is gitignored as large and not ours to
redistribute. Each `RESULT.md` pins the dataset version and split it was measured
on, so a published score can be reproduced by fetching exactly that split from
upstream.

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
- **Benchmark-IC protocol** (what counts as a legal input) — `benchmark-data/ic/METHODOLOGY.md`
- **Six-pillar IC verification** — `vibe-ic-marketplace/plugins/vibe-ic/skills/benchmark-verify/SKILL.md`
- **EDA fork scoreboard & image build** — `tools/vibeic-eda/README.md` and `tools/vibeic-eda/FIX_STATUS.md`
- **Agent roles & governance** — `vibe-ic-marketplace/AGENT_USAGE_GUIDE.md`
- **Contributing a new IC class / PDK / gate / skill / device** —
  `vibe-ic-marketplace/docs/CONTRIBUTING_*.md`

---

## Related repos (the `vibeic` org)

Vibe-IC is deliberately split into purpose-scoped repos under
[github.com/vibeic](https://github.com/vibeic), wired together by explicit
version contracts (this plugin resolves the `vibeic-eda` image by digest; `vibeic-eda`
pins each fork's SHA). This repo — the **plugin** — is the one you install.

```
12 forked EDA tools ──▶ vibeic-eda ──▶ vibe-ic ──▶ you
(OpenROAD·yosys·        (Docker image)  (this repo:   (Claude Code)
 ngspice·magic·netgen·                   the plugin)
 iverilog·klayout·                          │
 verilator·cocotb·                          ▼
 cocotb-coverage·pyuvm·                 vibe-ic-studio
 sby — each a real fork,               (web control surface)
 upstream-tracked)
```

- **[vibeic-eda](https://github.com/vibeic/vibeic-eda)** — the forked +
  bug-fixed open-source EDA toolchain, shipped as a Docker image. Rebuilds when
  a fork changes, not when this plugin changes.
- **The EDA forks** — the **12** the image builds from source, each pinned to a
  commit SHA in the canonical `vibeic/vibeic-eda` repo's `Dockerfile`: OpenROAD, Yosys, ngspice, Magic,
  Netgen, Icarus Verilog, KLayout, Verilator, cocotb, cocotb-coverage, pyuvm, and
  SymbiYosys. Verilator's pinned commit is also present upstream, so the shipped
  build carries no fork-only delta. A 13th fork, **OpenSTA**, reaches the image
  as OpenROAD's `src/sta` rather than as its own build stage. The
  [`vibeic` org](https://github.com/vibeic) carries **15** forks in total — the
  13 above plus `ALIGN-public` and `ALIGN-pdk-sky130`, the analog auto-layout
  line tracked as Bucket-T and not built into the EDA image. Each stays its
  **own** repo so upstream fixes can be pulled and our fixes contributed back;
  they are never vendored into this plugin. Per-fork scoreboard:
  [`tools/vibeic-eda/FIX_STATUS.md`](tools/vibeic-eda/FIX_STATUS.md).
- **[vibe-ic-studio](https://github.com/vibeic/vibe-ic-studio)** — the web
  control surface (Platform + Project layers), deployed independently.
- **[Awesome Open IC](https://github.com/vibeic/awesome-open-ic)** — a curated,
  MCP-aware map of every open-source IC tool, IP core, PDK, benchmark, and
  standard we have evaluated (notes whether MCP-EDA already wraps each).

---

## Contributing

We welcome contributions of every size: bug reports, doc fixes, new
skills, new EDA tool wrappers, new device drivers, new benchmark
fixtures. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md) before opening a PR.

For security vulnerabilities, see [SECURITY.md](SECURITY.md) — please
do **not** open a public issue.

### Install the git hooks (one line)

```bash
tools/install-git-hooks.sh
```

`.git/hooks/` is not tracked, so the repo's hooks do nothing until installed.
The installer symlinks the two tracked hooks, so a later `git pull` that improves
a hook takes effect with no re-install; re-running is idempotent, and it refuses
to clobber a pre-existing hook of the same name unless you pass `--force`.

Both hooks block a proprietary-PDK foundry / SKU / process name from reaching a
commit **message** — `commit-msg` as the commit is created, `pre-push` across
every message in the range being pushed. That is a surface the source-file guard
(`source_chip_agnostic_check.py`, which scans source files only) cannot see, so
the two are complementary and you want both. See
[tools/git-hooks/README.md](tools/git-hooks/README.md).

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
