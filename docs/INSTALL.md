# vibe-ic — Install & First Run (single source of truth)

> Fresh-platform path: install the EDA Docker → install the plugin → the MCP
> auto-wires them → Claude Opus 4.8 becomes the IC Expert Agent. Detailed EDA-server
> guide: `vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/INSTALL_GUIDE.md`.

## Prerequisites

| Tool | Version | Check |
|---|---|---|
| Docker | 20.10+ | `docker --version` |
| Node.js | 18+ | `node --version` |
| Python | 3.10+ | `python3 --version` |
| Icarus Verilog | 12+ | `iverilog -V` (functional pass@1) |
| Claude Code | latest | `claude --version` |

## Step 1 — EDA open-source Docker (prerequisite)

The plugin's EDA tools run **inside the IIC-OSIC-TOOLS container** (OpenROAD, yosys,
klayout, ngspice, iverilog, …). Pull/start it and name it `iic-eda` (the name the MCP
server expects via `EDA_CONTAINER`):

```bash
docker pull hpretl/iic-osic-tools           # or the pinned tag in mcp-eda/INSTALL_GUIDE.md
docker run -d --name iic-eda hpretl/iic-osic-tools sleep infinity
```

## Step 2 — Install the plugin

Add the marketplace and install `vibe-ic` (Claude Code plugin manager). Then in the
plugin's MCP server dir:

```bash
cd vibe-ic-marketplace/plugins/vibe-ic/mcp-eda && npm install
```

## Step 3 — MCP auto-wire (Docker ↔ plugin)

No manual wiring. The plugin ships `.mcp.json`:

```json
{ "mcpServers": { "eda-tools": {
    "type": "stdio", "command": "node",
    "args": ["${CLAUDE_PLUGIN_ROOT}/mcp-eda/src/bootstrap.mjs"],
    "env": { "EDA_CONTAINER": "iic-eda" } } } }
```

Claude Code starts the `eda-tools` MCP server, which drives the `iic-eda` container.
Every `eda_*` tool (`eda_synth`, `eda_pnr`, `eda_drc_klayout`, `eda_lvs`, …) then runs
inside the container. Health-check: ask the agent to run `eda_doctor` /
`mcp_server_health_check`.

## Step 4 — Use it (two input modes → Phase 1 → 2 → 3)

**Mode A — input folder:**
```bash
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py <project> --pdk sky130A
# → reports/orchestrator/vibe_ic_one_shot.json
```

**Mode B — dialogue:** open Claude with the plugin and describe your chip in plain
language. Claude (as IC Expert Agent) elicits the spec, fills gaps, and runs the flow.

See `docs/GUIDE_MAP.md` for all entry paths, convergence loops, and expected results.

## Step 5 — Verify the install reproduces our numbers

```bash
RTLLM_DATASET=/path/to/RTLLM \
VEV2_DATASET=/path/to/verilog-eval/dataset_spec-to-rtl \
VEHUMAN_DATASET=/path/to/verilog-eval/dataset_code-complete-iccad2023 \
tools/release/verify_clean_platform.sh          # expect: VERDICT: READY
```

It checks host tools → plugin structure → plugin self-checks (flow map, expert-DB
consistency, chip-agnostic, MCP import) → benchmark reproduce (RTLLM 44/50, VE-v2
153/156, VE-Human 153/156). Datasets are external; omit an env var to SKIP that
benchmark (still READY).
