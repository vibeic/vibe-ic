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

The plugin's EDA tools run **inside a Docker container named `vibeic-eda`** (the name the
MCP server expects via `EDA_CONTAINER`). Provide it either way:

**Recommended — the enhanced `vibeic-eda` toolchain** (forked OpenROAD / yosys / ngspice /
magic / netgen / iverilog / klayout with gatekeeper-verified FAIL→PASS fixes; scoreboard in
`tools/vibeic-eda/FIX_STATUS.md`). Build the reproducible image once, then run it:

First point `VIBEIC_DESIGNS` at **your own** designs / projects directory — the folder where
your IC projects already live. It **must already exist**: installing the plugin adds nothing
to your home directory, and `docker run -v <src>:<dst>` would otherwise create a missing
source directory *as root* — the phantom-directory bug. Do NOT default it to a plugin-named
workspace; use a directory you already have (e.g. your project folder).

```bash
export VIBEIC_DESIGNS="/path/to/your/designs"         # ← your project / designs folder (must already exist)
[ -d "$VIBEIC_DESIGNS" ] || { echo "VIBEIC_DESIGNS must point at an existing directory"; exit 1; }

docker pull ghcr.io/vibeic/vibeic-eda:0.2.99          # canonical image; to build from source: git clone https://github.com/vibeic/vibeic-eda
docker rm -f vibeic-eda 2>/dev/null || true           # "name already in use" = an old container exists; drop it first
docker run -d --name vibeic-eda \
  -v "$VIBEIC_DESIGNS:$VIBEIC_DESIGNS:rw" \
  -v "$VIBEIC_DESIGNS:/foss/designs:rw" \
  ghcr.io/vibeic/vibeic-eda:0.2.99 --skip sleep infinity
docker exec vibeic-eda yosys --version                # sanity check → prints a version (bare exec resolves since 0.2.12)
```

**Or — the stock base** (standard tools, no fork enhancements): pull IIC-OSIC-TOOLS and give
the container the same name (same `$VIBEIC_DESIGNS` mounts):

```bash
[ -d "$VIBEIC_DESIGNS" ] || { echo "set VIBEIC_DESIGNS to an existing directory first"; exit 1; }
docker pull hpretl/iic-osic-tools           # or the pinned tag in mcp-eda/INSTALL_GUIDE.md
docker run -d --name vibeic-eda \
  -v "$VIBEIC_DESIGNS:$VIBEIC_DESIGNS:rw" \
  -v "$VIBEIC_DESIGNS:/foss/designs:rw" \
  hpretl/iic-osic-tools --skip sleep infinity
```

> **The bind-mounts are REQUIRED, not optional — a clean install with a bare `sleep
> infinity` container will fail Phase 3.** The MCP-EDA tools address designs under
> `/foss/designs` (second mount), but Phase 3's backend and the RTLLM Verilator-escalation
> scorer also run in-container commands like `cd {host_path}` using the *host absolute*
> path — that resolves ONLY if the SAME path exists inside the container, which is what the
> first **identity mount** (`$VIBEIC_DESIGNS` → same path) provides. Without it the
> in-container `cd` reports `No such file or directory` and Phase 3 aborts. `phase3_one_shot_runner`
> auto-detects the mount table (`docker inspect … .Mounts`) and translates host→container
> paths, so an unmounted container leaves it nothing to translate to. Keep your design tree
> under `$VIBEIC_DESIGNS` (the directory you chose above) — the plugin never invents a
> workspace under your `$HOME`.

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
    "env": { "EDA_CONTAINER": "vibeic-eda" } } } }
```

Claude Code starts the `eda-tools` MCP server, which drives the `vibeic-eda` container.
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
