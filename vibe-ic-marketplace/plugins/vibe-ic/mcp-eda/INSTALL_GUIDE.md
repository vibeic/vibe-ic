# MCP EDA Server — Complete Installation Guide

> **Vibe Coding for ASIC**: From natural language to GDS to physical chip.
>
> This guide enables you to reproduce our exact results by installing the
> full open-source EDA toolchain, the MCP EDA Server, and the vibe-ic-d
> deterministic plugin.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Install IIC-OSIC-Tools Docker Image](#step-1-install-iic-osic-tools-docker-image)
3. [Step 2: Start the EDA Container](#step-2-start-the-eda-container)
4. [Step 3: Install MCP EDA Server](#step-3-install-mcp-eda)
5. [Step 4: Install vibe-ic-d Plugin](#step-4-install-vibe-ic-d-plugin)
6. [Step 5: (Optional) Install Quartus Lite for FPGA](#step-5-optional-install-quartus-lite-for-fpga)
7. [Step 6: (Optional) Custom PDK Setup](#step-6-optional-custom-pdk-setup)
8. [Verification: Full Pipeline Test](#verification-full-pipeline-test)
9. [Architecture Diagram](#architecture-diagram)
10. [Troubleshooting](#troubleshooting)

---

## Prerequisites

Before starting, ensure you have the following installed on your host machine:

| Requirement | Version | Check Command |
|-------------|---------|---------------|
| **Linux** | Ubuntu 22.04 or 24.04 recommended | `lsb_release -a` |
| **Docker** | 20.10+ | `docker --version` |
| **Node.js** | 18+ (for MCP server) | `node --version` |
| **npm** | 9+ | `npm --version` |
| **Python** | 3.10+ (for vibe-ic-d programs) | `python3 --version` |
| **Claude Code CLI** | Latest (for plugin execution) | `claude --version` |
| **Disk space** | 25+ GB free (Docker image ~22GB) | `df -h` |

### Install Docker (if not already installed)

```bash
# Ubuntu 22.04/24.04
sudo apt update
sudo apt install -y docker.io
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect
newgrp docker
```

### Install Node.js 18+ (if not already installed)

```bash
# Using NodeSource
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
```

### Install Claude Code CLI

```bash
npm install -g @anthropic-ai/claude-code
```

---

## Step 1: Install the EDA Docker Image

Every EDA tool runs inside one Docker container (the full RTL-to-GDS toolchain — no
individual tool installs). There are two image options; **the plugin looks for a container
named `vibeic-eda` either way** (`EDA_CONTAINER`).

### Option A (recommended): the enhanced `vibeic-eda` image

A forked + enhanced toolchain (OpenROAD / yosys / ngspice / magic / netgen / iverilog /
klayout) carrying **gatekeeper-verified FAIL→PASS fixes** over the stock base — e.g. yosys
uplifted to 0.66 + slang SV frontend, ngspice `-b` batch-honesty nonzero-rc, netgen
property-error LVS verdict (kills silent false-pass), klayout MANUFACTURINGGRID streamout
snap. Full scoreboard: `tools/vibeic-eda/FIX_STATUS.md`. Get the enhanced image — pull the
published one, or build from the canonical source:

```bash
docker pull ghcr.io/vibeic/vibeic-eda:latest                 # published image (all fork fixes baked in)
# — or build from source (advanced): the Dockerfile lives in the canonical repo, not this tree
git clone https://github.com/vibeic/vibeic-eda && docker build -t vibeic-eda:latest vibeic-eda/
```

### Option B: the stock IIC-OSIC-Tools base

The upstream image (~22 GB) with the standard tool versions listed below (no fork fixes):

```bash
docker pull hpretl/iic-osic-tools:latest
```

This may take 10-30 minutes depending on your internet connection. The table below lists the
**stock** baseline versions; Option A uplifts several (yosys → 0.66-fork, etc.).

### Tools Included in the Image

| Tool | Version | Purpose |
|------|---------|---------|
| **Yosys** | 0.62 | RTL synthesis (Verilog/SystemVerilog to gate-level netlist) |
| **OpenROAD** | 26Q1 | Place & Route (floorplan, placement, CTS, routing) |
| **OpenSTA** | 2.7.0 | Static Timing Analysis (setup/hold, multi-corner) |
| **Verilator** | 5.044 | RTL lint, SystemVerilog simulation |
| **Icarus Verilog** | 13.0 | Verilog simulation (iverilog + vvp) |
| **KLayout** | 0.30.6 | GDS generation from DEF, DRC with foundry rule decks |
| **Magic** | 8.3.603 | DRC, LVS, parasitic extraction |
| **Netgen** | 1.5.316 | LVS (Layout vs Schematic comparison) |
| **ngspice** | latest | SPICE simulation (analog/mixed-signal) |
| **Xyce** | 7.10 | Advanced parallel SPICE simulation |
| **cocotb** | 2.0.1 | Python-based testbench framework |
| **cocotb-coverage** | 2.0 | Functional coverage + constrained-random (`pip install cocotb-coverage`) — required by the `eda_professional_tb` generated testbenches |
| **pyuvm** | 4.0.1 | Python UVM (structure without a commercial simulator) |
| **SymbiYosys** | latest | Formal verification (with Yices solver) |
| **GTKWave** | latest | Waveform viewer |
| **Xschem** | latest | Schematic editor |
| **Fault** | latest | DFT scan chain insertion, ATPG |

### Built-in PDKs

| PDK | Process Node | Use Case |
|-----|-------------|----------|
| **GF180MCU** | 180nm | Mixed-signal ICs, 5V I/O, low-speed protocols |
| **SKY130** | 130nm | Digital ICs, RISC-V cores, 1.8V |

Both PDKs are pre-installed at `/foss/pdks/` inside the container:
- GF180MCU: `/foss/pdks/gf180mcuD/`
- SKY130: `/foss/pdks/sky130A/`

---

## Step 2: Start the EDA Container

Launch the container with your designs directory mounted.

**Point this at a directory you ALREADY have** — normally your project directory,
or the parent directory holding your projects. Letting the container see the
files you are working on is the mount's only job.

```bash
export VIBEIC_DESIGNS="/path/to/your/projects"   # ← an EXISTING directory of yours
```

There is no default location, nothing picks one for you, and installing the
plugin adds nothing to your home directory. `docker run` silently creates a
missing bind-mount source as `root`, so the recipe below refuses to start when
`$VIBEIC_DESIGNS` does not exist rather than leaving you a phantom directory. If
you want a dedicated workspace instead of reusing an existing tree, create it
yourself first and point at that.

```bash
# Option A image: vibeic-eda:0.3.16   |   Option B image: hpretl/iic-osic-tools:latest
docker rm -f vibeic-eda 2>/dev/null || true   # "name already in use" = an old container exists; drop it first
[ -d "$VIBEIC_DESIGNS" ] || { echo "set VIBEIC_DESIGNS to an existing directory first"; exit 1; }
docker run -d --name vibeic-eda \
  -v "$VIBEIC_DESIGNS:$VIBEIC_DESIGNS:rw" \
  -v "$VIBEIC_DESIGNS:/foss/designs:rw" \
  -p 8888:80 \
  -p 5901:5901 \
  vibeic-eda:0.3.16 --skip sleep infinity
# Tip: to swap an already-running container to a new tag WITHOUT retyping the mounts/ports,
# use the config-preserving helper:  tools/vibeic-eda/restart-eda.sh 0.2.12
```

### Mount Point Explanation

| Host Path | Container Path | Purpose |
|-----------|---------------|---------|
| `$VIBEIC_DESIGNS` | `$VIBEIC_DESIGNS` | Identity mount — host absolute paths resolve unchanged in-container (Phase 3 needs this) |
| `$VIBEIC_DESIGNS` | `/foss/designs` | Your design workspace (RTL, netlists, GDS) |

`$VIBEIC_DESIGNS` is whatever directory **you** chose above — the plugin ships no
default and never creates it.

You do not normally need to configure anything further: when a runner or scorer
is invoked with a project directory it derives the designs root from that project
plus the container's own mount table. `VIBEIC_DESIGNS_HOST_ROOT` is an optional
explicit override for CI and non-standard layouts. When a tool can resolve
neither, it returns a `DESIGNS_ROOT_UNRESOLVED` status listing both routes — it
never guesses a path and never creates one.

The MCP EDA Server executes all EDA tools inside this container via
`docker exec`, so file paths in MCP tool calls use container paths
(e.g., `/foss/designs/my_project/top.v`).

### Verify the Container is Running

```bash
docker ps --filter name=vibeic-eda
```

You should see the container in `Up` status.

---

## Step 3: Install MCP EDA Server

### 3a. Clone and Install

```bash
cd "$VIBEIC_DESIGNS"
git clone <your-repo-url>/mcp-eda.git
cd mcp-eda
npm install
```

### 3b. Configure Claude Code to Use the MCP Server

**Option A: CLI command (recommended)**

```bash
claude mcp add eda-tools node "$VIBEIC_DESIGNS/mcp-eda/src/index.js"
```

**Option B: Manual configuration**

Copy the example and edit your username:

```bash
cp mcp-eda/.mcp.json.example ~/.claude/.mcp.json
# Edit ~/.claude/.mcp.json — replace <your-user> with your actual username
```

The file should contain:

```json
{
  "mcpServers": {
    "eda-tools": {
      "type": "stdio",
      "command": "node",
      "args": ["/home/<your-user>/vibe-ic-designs/mcp-eda/src/index.js"],
      "env": {
        "EDA_CONTAINER": "vibeic-eda"
      }
    }
  }
}
```

Replace `<your-user>` with your actual username.

### 3c. Available MCP Tools (20 tools)

After configuration, Claude Code gains access to these EDA tools:

| MCP Tool | Backend EDA | Purpose |
|----------|------------|---------|
| `eda_lint` | Verilator | RTL quality check (lint errors/warnings) |
| `eda_synth` | Yosys | RTL to gate-level netlist synthesis |
| `eda_simulate` | Icarus Verilog | Functional simulation |
| `eda_cocotb` | cocotb + Verilator/Icarus | Python testbench execution |
| `eda_formal` | SymbiYosys + Yices | Formal verification (bounded model checking) |
| `eda_pnr` | OpenROAD | Place & Route (floorplan to routed DEF) |
| `eda_sta` | OpenSTA | Static Timing Analysis |
| `eda_sta_mcorner` | OpenSTA | Multi-corner STA (SS/TT/FF) |
| `eda_gds` | KLayout | GDS generation from DEF + cell GDS |
| `eda_drc_klayout` | KLayout | Foundry DRC with rule decks |
| `eda_lvs` | Netgen | Layout vs Schematic comparison |
| `eda_dft` | Fault | Scan chain insertion + ATPG + JTAG TAP |
| `eda_spice` | ngspice | SPICE simulation |
| `eda_ir_drop` | OpenROAD PSM | Power grid IR-drop analysis |
| `eda_equiv` | Yosys LEC + Netgen | Equivalence checking (RTL vs netlist) |
| `eda_extraction` | Magic | Parasitic extraction |
| `eda_rtl_audit` | vibe-ic-d programs | Deterministic RTL audit (runs on host) |
| `eda_fpga_compile` | Quartus/Vivado | FPGA synthesis (runs on host) |
| `eda_fpga_program` | Quartus/Vivado | FPGA programming (runs on host) |
| `eda_ic_search` | PostgreSQL + pgvector | IC knowledge base search |

Every tool writes a result manifest (`latest_results.jsonl` +
`latest_results.yml`) with timestamp, status, and key metrics after each
PASS, so reviewers never pick up stale logs.

### 3d. PDK Selection

The MCP server supports three PDK modes:

| PDK Value | Process | Default VDD/VSS | Site Name |
|-----------|---------|-----------------|-----------|
| `gf180` | GF180MCU 180nm | VDD / VSS | GF018hv5v_mcu_sc7 |
| `sky130` | SKY130 130nm | VPWR / VGND | unithd |
| `custom` | User-provided | Configurable | Configurable |

---

## Step 4: Install vibe-ic-d Plugin

The vibe-ic-d plugin (Deterministic Edition, v0.36) ensures that AI
agents produce consistent, complete outputs when executing IC design
skills. It includes 56 compliance-checked skills and 11 deterministic
programs.

### 4a. Clone and Install

```bash
cd "$VIBEIC_DESIGNS"
git clone <your-repo-url>/vibe-ic-marketplace.git
cd vibe-ic-marketplace/plugins/vibe-ic-d
pip install pytest   # for running compliance tests
```

### 4b. Run the Test Suite

```bash
./run_tests.sh
```

Expected result: **226+ tests passed** across 4 tiers.

### 4c. Test Suite Structure (4 Tiers)

| Tier | Directory | Tests | What It Checks |
|------|-----------|-------|----------------|
| 1 | `tests/test_driver_core.py` | 33 | YAML parser, Requirement class, cross-check rules, CLI |
| 2 | `tests/test_tools_and_integration.py` | 15 | Bootstrap, gate tools, all-skills smoke test |
| 3 | `programs/tests/` | 70 | CRC generator, RTL lint, FSM audit, SVA generators |
| 4 | `skills/*/tests/` | 110+ | Per-skill compliance regression (55 skills x 2) |

### 4d. Included Deterministic Programs

| Program | Purpose |
|---------|---------|
| `crc_vector_gen.py` | Parametric CRC RTL + reference + test vectors |
| `rtl_hygiene_lint.py` | General RTL hygiene checker (undriven wires, missing defaults) |
| `fsm_error_invariant.py` | Error-signal context auditor for FSMs |
| `tristate_bus_check.py` | Bus-arbitration SVA generator |
| `protocol_gap_check.py` | Inter-unit-gap SVA generator |
| `rx_tolerance_sweep.py` | Pulse-width decode coverage analyzer |
| `phy_counter_audit.py` | Bus-sampling vs time-based TX counter detector |
| `interface_encoding_audit.py` | Gray-code/binary mismatch detector |
| `crc_bitorder_check.py` | CRC bit-reversal verification for TX loading |
| `oe_pattern_check.py` | Output-enable timing pattern analyzer |
| `corner_coverage_audit.py` | Multi-corner/PVT coverage auditor |

### 4e. Included Skills (56 total)

**Frontend (18):** spec-to-rtl, rtl-review, rtl-repair, assertion-gen,
testbench-gen, ppa-predict, cdc-check, rdc-check, formal-verify,
equivalence-check, coverage-closure, hls-c2rtl, prompt-intake,
spec-review, spec-validator, synth-wrapper-gen, synth-doctor,
constraint-gen

**Backend (16):** placement-optimize, drc-fix, eco-plan, cts-plan,
sta-review, ir-drop-triage, tapeout-checklist, upf-author, lvs-triage,
hold-fix, sdc-validator, em-check, power-analysis, perc-check,
schematic-gen, architecture-explore

**Document Stack (8):** datasheet-gen, frs-gen, cmd-protocol-gen,
regmap-gen, adi-spec-gen, control-logic-gen, test-debug-gen,
timing-waveform-gen

**Methodology (5):** flow-orchestrate, regression-manage,
doc-consistency-check, checkpoint-gate, dft-insert

**Silicon/Analog (5):** analog-sizing, analog-layout, ams-sim, atpg,
bringup-plan, yield-diagnostic

**FPGA (4):** fpga-test-harness, fpga-signaltap, fpga-hps-bridge

### 4f. Usage: Compliance Checking

After any agent produces skill output, verify completeness:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/<skill>/compliance.yaml \
    <agent_output_file>
```

Exit codes:
- **0** = PASS (all required elements present)
- **1** = FAIL (stdout lists missing elements with regex patterns)
- **2** = ERROR (file not found)

---

## Step 5: (Optional) Install Quartus Lite for FPGA

For Intel FPGA verification (e.g., DE10-Lite with MAX10 10M50DAF484C7G):

### 5a. Download

1. Visit: https://www.intel.com/content/www/us/en/products/details/fpga/development-tools/quartus-prime/resource.html
2. Select **Quartus Prime Lite Edition** (free, no license required)
3. Download for Linux (~5 GB)

### 5b. Install

```bash
chmod +x QuartusLiteSetup-*.run
./QuartusLiteSetup-*.run
# Default install path: ~/intelFPGA_lite/
```

### 5c. Add to PATH

```bash
echo 'export PATH=$PATH:~/intelFPGA_lite/24.1/quartus/bin' >> ~/.bashrc
source ~/.bashrc
```

### 5d. What It Enables

| MCP Tool | Purpose |
|----------|---------|
| `eda_fpga_compile` | Quartus synthesis + fitting + timing for Intel FPGAs |
| `eda_fpga_program` | Program SOF/POF to connected FPGA board via USB-Blaster |

These tools run on the **host** (not inside Docker), since Quartus
requires native installation and USB access for the programmer.

### 5e. Supported FPGA Boards

| Board | FPGA | Device String |
|-------|------|---------------|
| DE10-Lite | MAX10 10M50DAF484C7G | `10M50DAF484C7G` |
| DE0-Nano | Cyclone IV EP4CE22F17C6 | `EP4CE22F17C6` |

---

## Step 6: (Optional) Custom PDK Setup

For commercial or custom PDKs (e.g., proprietary 180nm libraries):

### 6a. Prepare PDK Files

```bash
mkdir -p "$VIBEIC_DESIGNS/pdk/my_custom_pdk"
```

Place the following files:

| File Type | Example Path | Purpose |
|-----------|-------------|---------|
| Liberty (.lib) | `pdk/my_pdk_typ.lib` | Timing/power (typical corner) |
| Liberty (.lib) | `pdk/my_pdk_wci.lib` | Worst-case industrial corner |
| Liberty (.lib) | `pdk/my_pdk_bci.lib` | Best-case industrial corner |
| Tech LEF | `pdk/tech.lef` | Metal layer definitions |
| Cell LEF | `pdk/cells.lef` | Cell abstracts (pins, obstructions) |
| Cell GDS | `pdk/cells.gds` | Cell layouts for GDS merge |
| Cell Verilog | `pdk/cells.v` | Behavioral models for simulation |

### 6b. Use Custom PDK in MCP Tools

When calling MCP tools, set `pdk: "custom"` and provide the paths:

```
pdk: "custom"
custom_lib: "/foss/designs/pdk/my_pdk_typ.lib"
custom_techlef: "/foss/designs/pdk/tech.lef"
custom_celllef: "/foss/designs/pdk/cells.lef"
custom_cellgds: "/foss/designs/pdk/cells.gds"
custom_site: "core_site_name"
custom_vdd: "VDD"
custom_vss: "VSS"
```

**Note:** All paths must be container paths (under `/foss/designs/`), not
host paths, since tools run inside Docker.

---

## Verification: Full Pipeline Test

After completing Steps 1-4, run this smoke test to verify all tools are
accessible:

```bash
echo "=== Verifying EDA Tools in Docker Container ==="

echo -n "Yosys:         "; docker exec vibeic-eda yosys --version 2>&1 | head -1
echo -n "OpenROAD:      "; docker exec vibeic-eda openroad -version 2>&1 | head -1
echo -n "OpenSTA:       "; docker exec vibeic-eda sta -version 2>&1 | head -1
echo -n "Verilator:     "; docker exec vibeic-eda verilator --version 2>&1 | head -1
echo -n "Icarus:        "; docker exec vibeic-eda iverilog -V 2>&1 | head -1
echo -n "KLayout:       "; docker exec vibeic-eda klayout -v 2>&1 | head -1
echo -n "Magic:         "; docker exec vibeic-eda magic --version 2>&1 | head -1
echo -n "Netgen:        "; docker exec vibeic-eda netgen --version 2>&1 | head -1
echo -n "ngspice:       "; docker exec vibeic-eda ngspice --version 2>&1 | head -1
echo -n "cocotb:        "; docker exec vibeic-eda pip3 show cocotb 2>&1 | grep Version
echo -n "SymbiYosys:    "; docker exec vibeic-eda sby --help 2>&1 | head -1

echo ""
echo "=== Verifying PDKs ==="
docker exec vibeic-eda ls /foss/pdks/gf180mcuD/ > /dev/null 2>&1 && echo "GF180MCU: OK" || echo "GF180MCU: MISSING"
docker exec vibeic-eda ls /foss/pdks/sky130A/ > /dev/null 2>&1 && echo "SKY130:   OK" || echo "SKY130:   MISSING"

echo ""
echo "=== Verifying MCP Server ==="
node "$VIBEIC_DESIGNS/mcp-eda/src/index.js" --help 2>&1 | head -1 || echo "MCP Server: OK (stdio mode, no --help)"

echo ""
echo "=== Verifying vibe-ic-d ==="
cd "$VIBEIC_DESIGNS"/vibe-ic-marketplace/plugins/vibe-ic-d && python3 -m pytest tests/ --tb=no -q 2>&1 | tail -3

echo ""
echo "=== All checks complete ==="
```

### End-to-End Quick Test (Optional)

To run a minimal synthesis through the MCP pipeline, ask Claude Code:

```
Synthesize a 4-bit counter for GF180MCU using eda_synth.
```

Claude will:
1. Generate Verilog RTL for a 4-bit counter
2. Call `eda_lint` to check quality
3. Call `eda_synth` to synthesize with Yosys
4. Report cell count, area, and timing

---

## Architecture Diagram

```
+---------------------------------------------------+
|                 Claude Code CLI                    |
|            (with vibe-ic-d plugin)                 |
|                                                    |
|  User: "Design a 4-bit counter IC for GF180"      |
+---------------------+-----------------------------+
                      |
                      | MCP Protocol (stdio)
                      v
+---------------------------------------------------+
|           MCP EDA Server (Node.js)                 |
|                                                    |
|  eda_lint    | eda_synth   | eda_simulate          |
|  eda_formal  | eda_pnr     | eda_sta               |
|  eda_gds     | eda_drc     | eda_lvs               |
|  eda_spice   | eda_equiv   | eda_ir_drop           |
|  eda_dft     | eda_cocotb  | eda_extraction        |
|  eda_sta_mcorner | eda_rtl_audit                   |
+---------------------+-----------------------------+
                      |
                      | docker exec vibeic-eda ...
                      v
+---------------------------------------------------+
|       IIC-OSIC-Tools Docker Container              |
|                                                    |
|  Yosys  | OpenROAD | OpenSTA | KLayout | Magic    |
|  Verilator | iverilog | ngspice | cocotb           |
|  SymbiYosys | Netgen | Fault | GTKWave | Xschem   |
|                                                    |
|  +-----------------------------------------------+|
|  | Built-in PDKs                                  ||
|  |   GF180MCU (/foss/pdks/gf180mcuD/)            ||
|  |   SKY130   (/foss/pdks/sky130A/)              ||
|  +-----------------------------------------------+|
+---------------------------------------------------+

+---------------------------------------------------+
|          Host-Only Tools (optional)                |
|                                                    |
|  Quartus Lite (eda_fpga_compile, eda_fpga_program) |
|  Vivado       (for Xilinx FPGAs)                   |
|  Custom PDK libraries                              |
+---------------------------------------------------+
```

### Data Flow

```
RTL (.v/.sv) --> eda_lint --> eda_synth --> netlist (.v)
                                              |
                              eda_formal <----+----> eda_simulate
                                              |
                                        eda_pnr --> DEF (.def)
                                              |
                              eda_sta <-------+----> eda_ir_drop
                                              |
                                        eda_gds --> GDSII (.gds)
                                              |
                      eda_drc_klayout <-------+----> eda_lvs
                                              |
                                  Tapeout-ready GDS
```

---

## Troubleshooting

These are real issues we encountered during development and their
proven fixes.

### 1. OpenSTA CUDD Dependency

**Symptom:** Building OpenSTA from source fails with missing CUDD headers.

**Fix:** Install CUDD separately before building OpenSTA:

```bash
git clone https://github.com/ivmai/cudd.git
cd cudd
./configure --prefix=/usr/local
make -j$(nproc)
sudo make install
```

Then rebuild OpenSTA with `-DCUDD_DIR=/usr/local`.

**Note:** Not needed when using the Docker image (pre-built).

### 2. OpenROAD Requires SWIG >= 4.3

**Symptom:** OpenROAD cmake fails because Ubuntu apt only provides
SWIG 4.2.

**Fix:** Build SWIG 4.3 from source:

```bash
wget https://github.com/swig/swig/archive/refs/tags/v4.3.0.tar.gz
tar xzf v4.3.0.tar.gz
cd swig-4.3.0
./autogen.sh
./configure --prefix=/usr/local
make -j$(nproc)
sudo make install
```

**Note:** Not needed when using the Docker image (pre-built).

### 3. Yosys `zero_` Net Issue with OpenROAD

**Symptom:** After `hilomap` in Yosys, internal `zero_` nets remain
in the netlist. OpenROAD TritonRoute refuses to route them.

**Fix:** Three-part solution:

```tcl
# In Yosys script:
synth -top <module> -flatten    ;# flatten first
hilomap -hicell <TIE_HI> -locell <TIE_LO>

# If zero_ nets still appear, in OpenROAD TCL:
foreach net [get_nets zero_*] {
    $net setSpecial
}
```

### 4. KLayout DEF Import Requires LEF + GDS First

**Symptom:** KLayout generates GDS from DEF but all cells appear as
empty boxes (no geometry).

**Fix:** Read cell GDS and LEF **before** the DEF:

```python
# In KLayout Python script:
layout = pya.Layout()
layout.read(cell_gds_path)      # Read cell GDS first
# Then read DEF with LEF context
# KLayout merges cell geometries from the GDS
```

### 5. OpenROAD Site Name Mismatch

**Symptom:** OpenROAD `initialize_floorplan` fails with "no rows found"
or "unknown site."

**Fix:** Each PDK uses a different site name. Check yours:

```bash
grep "^SITE " /path/to/cell.lef
```

Common values:
- GF180MCU: `GF018hv5v_mcu_sc7`
- SKY130: `unithd`

### 6. Missing Track Definitions in Tech LEF

**Symptom:** OpenROAD fails with "no routing tracks defined" after
floorplan initialization.

**Fix:** Add `make_tracks` commands in your OpenROAD TCL, using values
from the LEF PITCH and DIRECTION:

```tcl
make_tracks Metal1 -x_offset 0.0 -x_pitch 0.56 -y_offset 0.0 -y_pitch 0.56
make_tracks Metal2 -x_offset 0.0 -x_pitch 0.56 -y_offset 0.0 -y_pitch 0.56
# ... etc. for each metal layer
```

### 7. Docker `--skip` Flag for Headless Operation

**Symptom:** IIC-OSIC-Tools container starts a full desktop UI (noVNC),
consuming resources unnecessarily.

**Fix:** When running one-shot commands, use `--skip` to bypass the UI:

```bash
docker run --rm hpretl/iic-osic-tools:latest --skip yosys --version
```

For persistent containers used by the MCP server, the default startup
is fine (the MCP server uses `docker exec` to run commands).

### 8. FPGA Tristate Inference Failure

**Symptom:** For single-wire protocols (1-Wire, Lightning AID, etc.),
Quartus fails to infer tristate buffers or the bidirectional bus does
not work on hardware.

**Fix:** The `inout` port **must** be at the FPGA top-level module.
Wrapping it in a sub-module breaks Quartus tristate inference:

```verilog
// WRONG: inout buried in sub-module
module top(output data_out);
    sub_module u1(.bus(internal_wire));  // Quartus cannot infer tristate
endmodule

// CORRECT: inout at top level
module top(inout data_bus);
    assign data_bus = oe ? tx_data : 1'bz;  // Quartus infers tristate
endmodule
```

### 9. KLayout QT_QPA_PLATFORM for Headless Environments

**Symptom:** KLayout crashes with "could not connect to display" in
Docker or SSH sessions.

**Fix:** Set the environment variable before running KLayout:

```bash
export QT_QPA_PLATFORM=offscreen
klayout -b -r my_script.py
```

The MCP EDA Server sets this automatically for `eda_gds` and
`eda_drc_klayout` tools.

### 10. SymbiYosys Solver: Use Yices, Not Z3

**Symptom:** `eda_formal` fails with "solver not found" when using z3.

**Fix:** The IIC-OSIC-Tools container includes Yices but not Z3. Always
configure SymbiYosys `.sby` files with:

```
[engines]
smtbmc yices
```

The MCP `eda_formal` tool does this automatically.

---

## Tapeout Paths

Once your design passes all signoff checks (DRC, LVS, STA, IR-drop),
you can fabricate a real chip:

| Service | PDK | Cost | Timeline |
|---------|-----|------|----------|
| [Efabless chipIgnite](https://efabless.com/chipignite) | GF180MCU | ~$10K USD | 8-10 weeks |
| [Google Open MPW](https://efabless.com/open_shuttle_program) | SKY130 | Free (apply) | Varies |
| [Tiny Tapeout](https://tinytapeout.com/) | SKY130 | $100-300 | Shared area |

---

## Quick Reference

### Start Everything

```bash
# 1. Start Docker container
docker start vibeic-eda || docker run -d --name vibeic-eda \
  -v "$VIBEIC_DESIGNS:$VIBEIC_DESIGNS:rw" \
  -v "$VIBEIC_DESIGNS:/foss/designs:rw" \
  vibeic-eda:0.3.16 --skip sleep infinity   # or: hpretl/iic-osic-tools:latest (stock)

# 2. Launch Claude Code with MCP
claude
```

### Stop Everything

```bash
docker stop vibeic-eda
```

### Reset Container

```bash
docker rm -f vibeic-eda
docker run -d --name vibeic-eda \
  -v "$VIBEIC_DESIGNS:$VIBEIC_DESIGNS:rw" \
  -v "$VIBEIC_DESIGNS:/foss/designs:rw" \
  vibeic-eda:0.3.16 --skip sleep infinity   # or: hpretl/iic-osic-tools:latest (stock)
```

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2026-04-19 | v1.0 | Initial comprehensive guide |

---

*This guide was developed from real production experience running the
full RTL-to-GDS-to-FPGA pipeline for the an example AID bus IC (~2.7K cells,
GF180MCU 180nm) and SC16IS750 UART/I2C bridge (1,132 cells). Every
troubleshooting entry reflects an actual issue encountered and resolved
during development.*
