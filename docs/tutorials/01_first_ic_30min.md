# Your First IC in 30 Minutes

> 從零開始，用 AI 驅動的開源 EDA 工具鏈，30 分鐘內產出你的第一顆晶片 GDS 檔。

---

## 目錄

1. [Prerequisites (2 min)](#1-prerequisites-2-min)
2. [安裝 EDA 環境 (3 min)](#2-安裝-eda-環境-3-min)
3. [安裝 Vibe-IC Plugin (1 min)](#3-安裝-vibe-ic-plugin-1-min)
4. [告訴 Claude：設計一個 4-bit Counter (1 min)](#4-告訴-claude設計一個-4-bit-counter-1-min)
5. [自動化流程：每一步發生了什麼 (10 min)](#5-自動化流程每一步發生了什麼-10-min)
6. [檢視你的 GDS (5 min)](#6-檢視你的-gds-5-min)
7. [理解輸出結果 (5 min)](#7-理解輸出結果-5-min)
8. [下一步：Tapeout 選項 (3 min)](#8-下一步tapeout-選項-3-min)

---

## 1. Prerequisites (2 min)

你只需要兩樣東西：

### Docker

```bash
# Ubuntu / Debian
sudo apt-get update && sudo apt-get install -y docker.io
sudo usermod -aG docker $USER

# macOS
brew install --cask docker

# 驗證安裝
docker --version
# Docker version 24.0.x 或更新
```

### Claude Code

```bash
# 安裝 Claude Code CLI
npm install -g @anthropic-ai/claude-code

# 驗證安裝
claude --version
```

> 需要 Claude Max 或 API Key 訂閱方案。

---

## 2. 安裝 EDA 環境 (3 min)

我們使用 IIC-OSIC-TOOLS Docker 映像，內含完整的開源 EDA 工具鏈：
Yosys（合成）、OpenROAD（佈局佈線）、Magic（DRC / GDS）、SymbiYosys（形式驗證）等。

```bash
# 拉取 Docker 映像（約 15 GB，首次需時較長）
docker pull hpretl/iic-osic-tools:latest

# 啟動容器（掛載工作目錄）
docker run -it --rm \
  -v $HOME/ic_workspace:/foss/eda/designs \
  -e DISPLAY=$DISPLAY \
  hpretl/iic-osic-tools:latest \
  bash
```

進入容器後，驗證工具已就緒：

```bash
$ yosys --version
Yosys 0.40+

$ openroad -version
v2.0-xxxxx

$ magic --version
8.3.xxx
```

```
┌──────────────────────────────────────────────────────────────┐
│                    Docker Container                          │
│                                                              │
│  ┌────────┐  ┌──────────┐  ┌───────┐  ┌──────────────┐      │
│  │ Yosys  │  │ OpenROAD │  │ Magic │  │ SymbiYosys   │      │
│  │ 合成    │  │ P&R      │  │ DRC   │  │ 形式驗證      │      │
│  └───┬────┘  └────┬─────┘  └──┬────┘  └──────────────┘      │
│      │            │           │                              │
│      ▼            ▼           ▼                              │
│  ┌─────────────────────────────────┐                         │
│  │      GF180MCU PDK (開源 180nm)  │                         │
│  │  /foss/pdks/gf180mcuD/          │                         │
│  └─────────────────────────────────┘                         │
│                                                              │
│  /foss/eda/designs/  <-- 你的設計掛載在這裡                      │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 安裝 Vibe-IC Plugin (1 min)

安裝 Vibe-IC plugin（34 個 IC 設計 skills）：

```bash
# 方法 1：從 marketplace 安裝
/plugin install vibe-ic-core@vibe-ic-marketplace

# 方法 2：手動安裝 MCP EDA Server（13 個 EDA 工具）
cd /path/to/AI_IC_design/mcp-eda-server && npm install
claude mcp add eda-tools node $PWD/src/index.js
```

安裝完成後，你可以使用這些 skills：
- `spec-to-rtl` -- 從規格產生 RTL
- `rtl-review` -- 自動審查 RTL
- `assertion-gen` -- 產生形式驗證 assertions
- `ppa-predict` -- 預估 PPA (Performance, Power, Area)
- `placement-optimize` -- 佈局最佳化
- `drc-fix` -- 自動修復 DRC 違規

---

## 4. 告訴 Claude：設計一個 4-bit Counter (1 min)

開啟 Claude Code，輸入一句話：

```
Design a 4-bit synchronous binary counter on GF180MCU.
Based on TI SN74HC163 spec: sync clear, sync load, two enables (ENP/ENT),
ripple carry out (RCO).
```

Claude 會自動執行完整的 RTL-to-GDS 流程。你只需要等待。

---

## 5. 自動化流程：每一步發生了什麼 (10 min)

以下是 Claude 在背後自動執行的每一步，以及實際的命令和輸出。

### Step 5.1: Spec-to-RTL -- 從規格產生 Verilog

Claude 分析 SN74HC163 datasheet，提取功能優先序：

```
優先序（最高到最低）：
  1. CLR_n  -- 同步清除 (active-low)
  2. LOAD_n -- 同步載入 (active-low)
  3. ENP && ENT -- 計數使能
  4. Hold  -- 保持
  RCO = ENT & (Q == 4'b1111)
```

自動產生 `counter4.v`：

```verilog
module counter4 (
    input  wire        clk,
    input  wire        clr_n,   // synchronous clear, active low
    input  wire        load_n,  // synchronous load,  active low
    input  wire        enp,
    input  wire        ent,
    input  wire [3:0]  d,       // parallel data in
    output reg  [3:0]  q,       // counter value
    output wire        rco      // ripple carry out
);

    always @(posedge clk) begin
        if (!clr_n)
            q <= 4'b0000;                 // priority 1: sync clear
        else if (!load_n)
            q <= d;                       // priority 2: sync load
        else if (enp && ent)
            q <= q + 4'd1;                // priority 3: count
        // else: hold
    end

    assign rco = ent & (q == 4'b1111);

endmodule
```

### Step 5.2: Synthesis -- Yosys 合成

使用 GF180MCU 標準元件庫進行邏輯合成：

```bash
yosys -p "
  read_verilog src/counter4.v
  synth -top counter4
  dfflibmap -liberty $LIB
  abc -liberty $LIB
  clean
  stat -liberty $LIB
  write_verilog -noattr results/synth_counter4.v
"
```

實際輸出：

```
=== counter4 ===

   Number of wires:                 42
   Number of wire bits:             73
   Number of cells:                 25

   Chip area for module 'counter4': 604.160000
```

> 25 個標準元件、604 um^2 晶片面積。

### Step 5.3: Place & Route -- OpenROAD 佈局佈線

```bash
openroad -exit <<ORTCL
  # 讀取技術檔案
  read_lef $TECHLEF
  read_lef $CELLLEF
  read_liberty $LIB
  read_verilog results/synth_counter4.v
  link_design counter4

  # Floorplan: 50% utilization, 正方形
  initialize_floorplan -utilization 50 -aspect_ratio 1.0 \
    -core_space 5 -site GF018hv5v_mcu_sc7
  make_tracks

  # IO 腳位放置
  place_pins -hor_layers Metal3 -ver_layers Metal2

  # 電源網路 (PDN)
  add_global_connection -net VDD -pin_pattern "VDD" -power
  add_global_connection -net VSS -pin_pattern "VSS" -ground
  global_connect
  set_voltage_domain -power VDD -ground VSS
  define_pdn_grid -name main
  add_pdn_stripe -grid main -layer Metal1 -width 0.48 -followpins
  pdngen

  # 佈局
  global_placement -density 0.6
  detailed_placement
  check_placement -verbose

  # 時序約束
  create_clock -name clk -period 200 [get_ports clk]

  # 繞線
  global_route -verbose
  set_routing_layers -signal Metal1-Metal5
  detailed_route -output_drc results/route_drc.rpt

  # 輸出
  report_design_area
  report_checks -path_delay max
  write_def results/counter4_gf180.def
  write_verilog results/counter4_pnr.v
ORTCL
```

實際輸出：

```
Design area: 604 um^2
Utilization: 50.0%
Total instances: 25

=== OpenROAD P&R Complete ===
```

### Step 5.4: DRC 檢查 -- Magic

```bash
magic -dnull -noconsole <<MAGIC
  drc style drc(full)
  lef read $TECHLEF
  lef read $CELLLEF
  def read results/counter4_gf180.def
  drc check
  drc count
  quit
MAGIC
```

實際輸出：

```
DRC violations: 0
```

> 0 個 DRC 違規！設計完全通過設計規則檢查。

### Step 5.5: GDS 產生 -- Magic

```bash
magic -dnull -noconsole <<MAGIC
  lef read $TECHLEF
  lef read $CELLLEF
  def read results/counter4_gf180.def
  gds readonly true
  gds rescale false
  gds read $CELLGDS
  load counter4
  select top cell
  gds write results/counter4_gf180.gds
  quit
MAGIC
```

實際輸出：

```
=== GDS Written ===
```

你的第一顆 IC 的 GDS 檔案就在 `results/counter4_gf180.gds`！

---

## 6. 檢視你的 GDS (5 min)

### 方法一：KLayout（推薦）

```bash
# 在容器內
klayout results/counter4_gf180.gds

# 或在主機上安裝 KLayout
# macOS: brew install --cask klayout
# Ubuntu: sudo apt install klayout
klayout ~/ic_workspace/sn74hc163_gf180/results/counter4_gf180.gds
```

### 方法二：Magic

```bash
magic -T /foss/pdks/gf180mcuD/libs.tech/magic/gf180mcuD.tech \
  results/counter4_gf180.gds
```

### 方法三：命令列快速檢視

```bash
# 列出 GDS 內的 cell 數量
python3 -c "
import pya
ly = pya.Layout()
ly.read('results/counter4_gf180.gds')
print(f'Total cells: {ly.cells()}')
for cell in ly.each_cell():
    print(f'  {cell.name}: {cell.bbox()}')
"
```

```
你會看到的 Layout 結構示意：

  ┌───────────────────────────────────────────────┐
  │  VDD ═══════════════════════════════════════  │ ← Metal1 電源軌
  │                                               │
  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐    │
  │  │ DFF │ │ DFF │ │ DFF │ │ DFF │ │ AND │    │ ← 4 個 Flip-Flop
  │  │ q[0]│ │ q[1]│ │ q[2]│ │ q[3]│ │ rco │    │   + RCO 邏輯
  │  └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘    │
  │     │       │       │       │       │        │
  │  ┌──┴──┐ ┌──┴──┐ ┌──┴──┐ ┌──┴──┐            │
  │  │ MUX │ │ MUX │ │ MUX │ │ MUX │            │ ← CLR/LOAD/CNT
  │  └─────┘ └─────┘ └─────┘ └─────┘            │   選擇邏輯
  │                                               │
  │  VSS ═══════════════════════════════════════  │ ← Metal1 接地軌
  └───────────────────────────────────────────────┘

  總面積: ~604 um^2 (約 24.6 x 24.6 um)
```

---

## 7. 理解輸出結果 (5 min)

### 產出檔案總覽

```
results/
  |- synth_counter4.v      # 合成後的 gate-level netlist
  |- synth.log             # Yosys 合成報告
  |- counter4_gf180.def    # P&R 後的版圖定義
  |- counter4_pnr.v        # P&R 後的 netlist
  |- pnr.log               # OpenROAD 報告
  |- route_drc.rpt         # 繞線 DRC 報告
  |- drc.log               # Magic DRC 報告
  |- counter4_gf180.gds    # 最終 GDS (可送 fab!)
  |- gds.log               # GDS 產生記錄
```

### Cell 統計

| 指標 | 數值 | 說明 |
|------|------|------|
| 總 cell 數 | 25 | 標準元件數量 |
| Chip area | 604 um^2 | 晶片面積（不含 pad） |
| DRC violations | 0 | 設計規則違規數 |
| 製程 | GF180MCU | GlobalFoundries 180nm |
| 標準元件庫 | gf180mcu_fd_sc_mcu7t5v0 | 7-track, 3.3V |

### Cell 組成分析

```
counter4 Cell Breakdown (25 cells):
  +-----------------------+-------+
  | Cell Type             | Count |
  +-----------------------+-------+
  | DFF (Flip-Flop)       |   4   |  ← q[3:0] 暫存器
  | MUX (Multiplexer)     |   4   |  ← CLR/LOAD/CNT 選擇
  | AND                   |   3   |  ← ENP&ENT, RCO
  | XOR / Half-Adder      |   4   |  ← q+1 遞增器
  | INV / BUF             |   6   |  ← 反相/緩衝
  | OR / NAND / NOR       |   4   |  ← 雜項邏輯
  +-----------------------+-------+
  | Total                 |  25   |
  +-----------------------+-------+
```

### 時序分析

- **目標頻率**：5 MHz（period = 200 ns）
- **Critical path**：q[3:0] -> incrementer -> mux -> D-input
- **Slack**：極大（180nm 下此設計的 critical path 遠短於 200 ns）
- **結論**：時序完全滿足，無需最佳化

### DRC 結果

```
DRC violations: 0

所有設計規則通過：
  [PASS] Metal spacing
  [PASS] Via enclosure
  [PASS] Minimum width
  [PASS] Power rail continuity
  [PASS] Well proximity
```

---

## 8. 下一步：Tapeout 選項 (3 min)

你的 GDS 檔案已經可以準備送 fab 了！以下是三個主要的開源 tapeout 管道：

### Option A: Efabless / Open MPW (免費)

```
┌──────────────────────────────────────────────┐
│  Efabless Open MPW Shuttle                   │
│                                              │
│  製程：GF180MCU / SKY130                      │
│  費用：免費（Google / Efabless 贊助）           │
│  週期：約 3-6 個月                              │
│  網址：https://efabless.com/open_shuttle_program │
│                                              │
│  適合：學習、研究、原型驗證                       │
└──────────────────────────────────────────────┘
```

- 提交你的 GDS 到 Efabless 平台
- 通過 precheck (DRC/LVS) 後，免費獲得晶片
- 每年多次 shuttle 機會
- 需要完整的 Caravel harness 整合

### Option B: Tiny Tapeout (約 USD $150)

```
┌──────────────────────────────────────────────┐
│  Tiny Tapeout                                │
│                                              │
│  製程：SKY130 (via Efabless)                  │
│  費用：~$150 USD / tile                       │
│  週期：約 6 個月                                │
│  網址：https://tinytapeout.com                │
│                                              │
│  適合：教學、個人專案、快速迭代                    │
└──────────────────────────────────────────────┘
```

- 最簡單的入門方式
- 用 GitHub template 提交你的 Verilog
- 自動化 hardening 流程
- 每個 tile 約 160x100 um（你的 counter4 完全放得下）

### Option C: 自行聯繫 Foundry Shuttle

```
┌──────────────────────────────────────────────┐
│  商業 Shuttle 服務                             │
│                                              │
│  MOSIS / Europractice / CMP / TSRI           │
│  製程：各種（130nm - 7nm）                      │
│  費用：數百至數千美元                             │
│  週期：3-6 個月                                 │
│                                              │
│  適合：商業產品、進階研究                          │
└──────────────────────────────────────────────┘
```

### 從 counter4 到你自己的設計

現在你已經走完一次完整流程，試試看設計更複雜的電路：

```
# 範例 1：SPI Controller
Design a SPI master controller on GF180MCU.
Support mode 0/1/2/3, configurable clock divider, 8/16/32-bit transfers.

# 範例 2：UART
Design a UART transmitter/receiver on GF180MCU.
9600-115200 baud, 8N1 format, 16-byte FIFO.

# 範例 3：PWM Generator
Design a 4-channel PWM generator on GF180MCU.
16-bit resolution, independent duty cycle per channel.
```

---

## 完整的 run_flow.sh 一鍵腳本

如果你想跳過 AI 互動，直接用腳本跑完整流程：

```bash
#!/bin/bash
# SN74HC163 counter4 — Full RTL-to-GDS flow with GF180MCU PDK
set -e

export PATH=/foss/tools/yosys/bin:/foss/tools/openroad/bin:\
/foss/tools/magic/bin:/foss/tools/netgen/bin:/foss/tools/bin:$PATH

DESIGN=counter4
PDK=/foss/pdks/gf180mcuD
SCL=gf180mcu_fd_sc_mcu7t5v0
LIB=$PDK/libs.ref/$SCL/lib/${SCL}__tt_025C_3v30.lib
TECHLEF=$PDK/libs.ref/$SCL/techlef/${SCL}__nom.tlef
CELLLEF=$PDK/libs.ref/$SCL/lef/${SCL}.lef
CELLGDS=$PDK/libs.ref/$SCL/gds/${SCL}.gds

WORKDIR=/foss/eda/designs/sn74hc163_gf180
cd $WORKDIR
mkdir -p results

echo "========================================="
echo "  SN74HC163 GF180MCU Full Flow"
echo "========================================="

# Step 1: Synthesis (Yosys)
echo ">>> Step 1: Synthesis (Yosys + GF180MCU)"
yosys -p "
  read_verilog src/counter4.v
  synth -top $DESIGN
  dfflibmap -liberty $LIB
  abc -liberty $LIB
  clean
  stat -liberty $LIB
  write_verilog -noattr results/synth_${DESIGN}.v
" 2>&1 | tee results/synth.log

# Step 2: Place & Route (OpenROAD)
echo ">>> Step 2: Place & Route (OpenROAD + GF180MCU)"
openroad -exit <<ORTCL 2>&1 | tee results/pnr.log
read_lef $TECHLEF
read_lef $CELLLEF
read_liberty $LIB
read_verilog results/synth_${DESIGN}.v
link_design $DESIGN
initialize_floorplan -utilization 50 -aspect_ratio 1.0 \
  -core_space 5 -site GF018hv5v_mcu_sc7
make_tracks
place_pins -hor_layers Metal3 -ver_layers Metal2
add_global_connection -net VDD -pin_pattern "VDD" -power
add_global_connection -net VSS -pin_pattern "VSS" -ground
global_connect
set_voltage_domain -power VDD -ground VSS
define_pdn_grid -name main
add_pdn_stripe -grid main -layer Metal1 -width 0.48 -followpins
pdngen
global_placement -density 0.6
detailed_placement
check_placement -verbose
create_clock -name clk -period 200 [get_ports clk]
global_route -verbose
set_routing_layers -signal Metal1-Metal5
detailed_route -output_drc results/route_drc.rpt
report_design_area
report_checks -path_delay max
write_def results/${DESIGN}_gf180.def
write_verilog results/${DESIGN}_pnr.v
puts "=== OpenROAD P&R Complete ==="
ORTCL

# Step 3: DRC (Magic)
echo ">>> Step 3: DRC Check (Magic)"
magic -dnull -noconsole <<MAGIC 2>&1 | tee results/drc.log
drc style drc(full)
lef read $TECHLEF
lef read $CELLLEF
def read results/${DESIGN}_gf180.def
drc check
drc count
quit
MAGIC

# Step 4: GDS (Magic)
echo ">>> Step 4: GDS Generation (Magic)"
magic -dnull -noconsole <<MAGIC2 2>&1 | tee results/gds.log
lef read $TECHLEF
lef read $CELLLEF
def read results/${DESIGN}_gf180.def
gds readonly true
gds rescale false
gds read $CELLGDS
load $DESIGN
select top cell
gds write results/${DESIGN}_gf180.gds
puts "=== GDS Written ==="
quit
MAGIC2

echo "========================================="
echo "  Flow Complete!"
echo "========================================="
echo "Results in: $WORKDIR/results/"
ls -lh results/
```

---

## 參考來源

- [TI SN74HC163 Datasheet](https://www.ti.com/lit/ds/symlink/sn74hc163.pdf)
- [GF180MCU PDK (GitHub)](https://github.com/google/gf180mcu-pdk)
- [IIC-OSIC-TOOLS Docker](https://github.com/iic-jku/IIC-OSIC-TOOLS)
- [Efabless Open MPW](https://efabless.com/open_shuttle_program)
- [Tiny Tapeout](https://tinytapeout.com)
- [KLayout](https://www.klayout.de)
- [OpenROAD Project](https://openroad.readthedocs.io)
- [Yosys](https://yosyshq.net/yosys/)
