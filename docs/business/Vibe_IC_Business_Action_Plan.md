# Vibe IC 商業模式行動分析

**日期**：2026-04-07 | **專案**：AI-Native IC Design

---

## 1. 商業模式概述

你提出的 Vibe IC 模式可以歸納為以下結構：

| 層次 | 策略 | 目的 |
|------|------|------|
| **開源前端** | Plugins/Skills + EDA MCP 全部 open source | 建立開發者生態、降低進入門檻 |
| **Open PDK 合作** | 與 foundries 談合作取得可公開的 PDK | 讓用戶可以直接跑 flow 到 GDS |
| **自動化 EDA MCP** | 減少人為 checkpoints，全流程自動化 | 核心技術護城河 |
| **設計服務** | 幫客戶完善設計（同步完善 MCP） | 近期營收來源 |
| **製造接單** | 以量談價（集合多家需求統一流片） | 中期營收來源 |

這個模式跟 [Efabless/chipIgnite](https://chipfoundry.io/) 的 shuttle 模式有相似之處，但你的差異化在於：**AI-Native 的自動化設計能力**是前端入口，而非只是一個 tapeout 平台。

---

## 2. 你的判斷完全正確：需要 IC 文件資料庫

你提到的場景非常關鍵：

> 用戶用自然語言描述想要的 IC 功能 → 系統在 Database 裡找到類似的已有 IC → 基於這些文件產生完整 Data Sheet → 作為 Vibe IC flow 的 input

這其實是 **RAG（Retrieval-Augmented Generation）在 IC 設計領域的核心應用**。目前業界已有的 IC 文件資源包括：

### 2.1 可收集的公開資料來源

| 資料類型 | 來源 | 說明 |
|----------|------|------|
| **Datasheets** | [Octopart](https://octopart.com/)、[Datasheet Archive](https://www.datasheetarchive.com/)、[DigChip](https://www.digchip.com/) | 數億份元件 datasheet，可透過 API 或爬蟲取得 |
| **Application Notes** | TI、NXP、ADI、Microchip 等官網 | 各大半導體公司公開的應用文件 |
| **Specs / Standards** | IEEE、JEDEC、AMBA（ARM）、USB-IF | 介面協議規格（部分需付費） |
| **Open Source IC Designs** | [Efabless](https://efabless.com/)、[OpenCores](https://opencores.org/)、GitHub | 已驗證的開源設計，含 RTL + testbench |
| **PDK 文件** | [SKY130 PDK](https://github.com/google/skywater-pdk)、[GF180MCU PDK](https://github.com/google/gf180mcu-pdk)、[IHP SG13G2](https://github.com/IHP-GmbH/IHP-Open-PDK) | 製程規格、design rules、Liberty timing |
| **開源元件資料庫** | [JITX Open Components DB](https://github.com/JITx-Inc/open-components-database)、[Antmicro HW Component DB](https://antmicro.com/blog/2023/10/antmicro-hardware-component-database/) | 結構化元件資訊，含 footprint 與參數 |

### 2.2 專有但可洽談的資料

部分半導體公司會提供 **Design Partner Program**，可能可以取得更完整的設計參考資料。例如 TI 的 [TI Reference Designs](https://www.ti.com/reference-designs/index.html) 就有數千份可公開的參考設計。

---

## 3. 資料庫的架構與整理方式

你問的「是不是也需要做一些整理，讓 search 和 mapping 比較快找出來」——答案是**絕對需要**。原始 PDF 丟進去毫無意義，必須做結構化的知識工程。

### 3.1 建議的資料庫架構

建議採用 **向量資料庫（Vector DB）+ 結構化 Metadata** 的混合架構：

```
┌─────────────────────────────────────────────────┐
│              IC Knowledge Base                   │
├─────────────────────────────────────────────────┤
│  Layer 1: 結構化 Metadata（PostgreSQL / SQLite） │
│  ─ IC 名稱、製造商、製程節點、封裝              │
│  ─ 功能分類（taxonomy）                         │
│  ─ 關鍵參數（電壓、頻率、功耗、腳位數）        │
│  ─ 介面類型（I2C, SPI, UART, USB, etc.）        │
│  ─ 應用領域（automotive, consumer, industrial）  │
├─────────────────────────────────────────────────┤
│  Layer 2: 向量嵌入（ChromaDB / Pinecone / Milvus）│
│  ─ Datasheet 全文的語義嵌入                      │
│  ─ Pin description 嵌入                          │
│  ─ Functional block diagram 描述嵌入             │
│  ─ Timing diagram 參數嵌入                       │
├─────────────────────────────────────────────────┤
│  Layer 3: 原始文件（S3 / MinIO）                 │
│  ─ PDF 原檔                                      │
│  ─ 提取後的結構化 JSON                           │
│  ─ 電路圖 / Block diagram 圖片                   │
└─────────────────────────────────────────────────┘
```

### 3.2 IC 功能分類體系（Taxonomy）

為了讓 search 有效，建議建立一套 IC 功能分類體系，例如：

```
IC Taxonomy
├── Digital Logic
│   ├── Counters (如 SN74HC163)
│   ├── Shift Registers
│   ├── Multiplexers
│   └── Bus Interfaces (如 BENCH-A)
├── Microcontrollers
│   ├── 8-bit MCU
│   ├── 32-bit MCU (ARM Cortex-M)
│   └── RISC-V MCU
├── Analog / Mixed-Signal
│   ├── ADC / DAC
│   ├── Op-Amps
│   ├── Voltage Regulators (LDO, DC-DC)
│   └── PLL / Clock
├── Interface ICs
│   ├── UART / I2C / SPI Bridges
│   ├── USB Controllers
│   ├── Ethernet PHY
│   └── CAN / LIN (Automotive)
├── Power Management
│   ├── PMIC
│   ├── Battery Charger
│   └── Motor Driver
└── Memory
    ├── SRAM / DRAM
    ├── Flash
    └── EEPROM
```

### 3.3 搜尋與匹配策略

當用戶說「我想做一顆 I2C 轉 UART 的橋接晶片，3.3V 供電」時，系統應該能：

1. **關鍵字匹配**：從 Metadata 找出「Interface → UART/I2C Bridge」類別的所有 IC
2. **語義搜尋**：用向量相似度找出 datasheet 描述中最接近用戶需求的 IC
3. **參數過濾**：篩選供電電壓 3.3V 的結果
4. **排序輸出**：依相關性排序，取前 N 份作為參考

這就是 [Google Cloud RAG Engine](https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/vector-db-choices) 或 [Semiconductor Component RAG](https://glama.ai/mcp/servers/@chakradharkalle03-arch/MCP2) 這類方案在做的事。

---

## 4. 除了 EDA MCP 和 Database 之外，還需要做的事

### 4.1 Datasheet 生成引擎（最關鍵的缺口）

你描述的核心流程是：**自然語言 → 找到參考 IC → 生成完整 Datasheet → 跑 Vibe IC flow**。

目前你的 flow 是從「已有 Datasheet」開始（如 BENCH-A 是基於 vendor datasheet），但如果要服務「不知道 datasheet 該長什麼樣」的用戶，你需要一個 **Datasheet Generator**：

- 輸入：用戶的自然語言需求 + DB 中找到的參考 IC
- 輸出：符合業界規格的完整 Datasheet（含 pin table、functional description、timing parameters、absolute maximum ratings、application circuit）
- 這個 generator 本身就可以是一個 AI skill / plugin

### 4.2 PDK 覆蓋範圍擴充

目前你有 3 個 open PDK（GF180MCU、SKY130、IHP SG13G2），但商業上可能不夠：

| PDK | 節點 | 現況 | 建議行動 |
|-----|------|------|----------|
| [GF180MCU](https://github.com/google/gf180mcu-pdk) | 180nm | ✅ 已整合 | 持續維護 |
| [SKY130](https://github.com/google/skywater-pdk) | 130nm | ✅ 已安裝 | 需整合到 MCP flow |
| [IHP SG13G2](https://github.com/IHP-GmbH/IHP-Open-PDK) | 130nm BiCMOS | ✅ 已安裝 | 需整合到 MCP flow，特別適合 RF/類比 |
| TSMC / Samsung | 28nm 以下 | ❌ 無法 open source | 需洽談 design partner program，提供 NDA 版本的 MCP 整合 |

根據 [CHIPS Alliance](https://opensource.googleblog.com/2023/11/open-source-pdks-joining-linux-foundation-chips-alliance.html) 的發展，open PDK 生態正在 Linux Foundation 下持續擴展，這是你可以積極參與的方向。

### 4.3 競爭者分析與差異化

目前 AI-Native IC Design 領域的主要競爭者：

| 公司 | 募資 | 定位 | 你的差異 |
|------|------|------|----------|
| [Cognichip](https://www.cognichip.ai/) | $93M（含 2026/04 的 $60M） | Physics-informed AI model，降低設計成本 75% | 他們走商業 EDA 替代路線；你走 open source + 製造服務 |
| [ChipAgents](https://chipagents.ai/) | $74M Series A（2026/02） | Agentic AI for debugging & verification | 他們專注 verification；你做全流程 spec-to-GDS |
| [Siemens EDA](https://www.designnews.com/design-software/siemens-unveils-eda-ai-system-for-semiconductor-pcb-design-at-dac-2025) | 大企業 | AI 加強既有 EDA 工具 | 他們是 AI4EDA；你是 AI-Native（本質不同） |

你的獨特定位：**唯一做 open source + 全流程 AI-Native + 製造接單的一站式平台**。這是一個 Cognichip 和 ChipAgents 都沒有涵蓋的市場空間。

### 4.4 使用者社群與開發者生態

Open source 策略要成功，社群是關鍵：

- **文件與教學**：需要從 SN74HC163 demo 擴展成完整的 tutorial 系列（demo IC 為 chip-agnostic 範例）
- **Plugin marketplace**：讓第三方也能貢獻 skills（你的 plugin 架構已具備這個基礎）
- **Showcase**：收集和展示用 Vibe IC 設計出來的晶片案例
- **Discord / Forum**：建立開發者交流社群

### 4.5 製造供應鏈管理

「以量談價」需要建立穩定的供應鏈關係：

- 與 [Efabless/chipIgnite](https://chipfoundry.io/faqs) 建立批量折扣合作（目前單一 shuttle $14,950/project）
- 洽談 foundry 直接合作（GF、SkyWater），取得比 shuttle 更好的價格
- 建立封裝測試（OSAT）合作夥伴關係
- 需要有 **design review 流程**，確保送出去的 GDS 品質可靠，避免 wafer 報廢

### 4.6 商業化法律準備

- 開源授權選擇（Apache 2.0 最適合 IC 設計生態，與既有 PDK 授權一致）
- 設計責任釐清（用 AI 生成的 IC 設計，如果有功能缺陷，責任歸屬需要明確條款）
- NDA 管理（部分 PDK 和客戶設計需要保密）

---

## 5. IP 整合策略 — 另一個關鍵拼圖

### 5.1 為什麼需要 IP 整合

IC 設計不可能全部從零開始。現代 SoC 通常是 70-80% 的 IP 重用 + 20-30% 的客製邏輯。根據 [Research Nester 的報告](https://www.researchnester.com/reports/semiconductor-intellectual-property-ip-market/4206)，全球半導體 IP 市場在 2025 年達到約 $79.7 億美元，預計 2030 年成長到 $135.4 億美元（CAGR 11.1%）。其中 **Soft IP（RTL 形式）佔 55.9%**，是最大的 IP 類型。

對 Vibe IC 來說，IP 整合解決兩個問題：(1) 用戶不需要重新設計已經存在的功能模組（如 UART、I2C、SPI controller），可以直接拿現成 IP 嵌入；(2) 我們自己設計的 IC 模組也能反過來變成 IP 給別人用，開啟新的營收管道。

### 5.2 IP 的兩種形式與串接方式

| IP 類型 | 提供格式 | 特性 | 串接方式 |
|---------|---------|------|----------|
| **Soft IP** | RTL（Verilog / VHDL） | 可攜帶、跨製程、可修改 | 直接併入 RTL 設計 → 一起跑 synthesis → P&R → GDS |
| **Hard IP** | GDS + LEF + Liberty (.lib) | 綁定特定製程、效能可預測 | GDS 直接嵌入 floorplan，LEF 定義 pin 位置，Liberty 提供 timing 給 STA |

**Soft IP 串接**：最直接。IP 以 RTL 模組形式加入 top-level design，跟自己寫的 RTL 一起走完整個 EDA flow。這是目前 Vibe IC 最容易支援的形式，因為我們的 MCP flow（eda_synth → eda_pnr → eda_gds）已經可以處理多模組設計。

**Hard IP 串接**：需要在 floorplan 階段預留位置。具體步驟如下：

1. Hard IP 提供者交付：GDS（layout）、LEF（抽象 layout，含 pin 位置和 blockage）、Liberty .lib（timing/power model）、Verilog model（for simulation）
2. 在 OpenROAD 的 `eda_pnr` 階段，將 Hard IP 作為 macro 放入 floorplan
3. STA（`eda_sta`）用 Hard IP 的 Liberty 做 timing 分析
4. 最終 GDS merge：用 KLayout 將 Hard IP GDS 與自己的 GDS 合併

**Hard IP 與製程的綁定**：每個 Hard IP 的 GDS 都是針對特定 PDK 製作的。例如一個 GF180MCU 的 SRAM Hard IP 不能用在 SKY130 上。這意味著我們的 IP Database 需要按 PDK 分類索引。

### 5.3 IP 標準化規格 — 讓 MCP 能自動找到並整合 IP

為了讓 AI Agent 能自動搜尋和整合 IP，建議定義一套 **IP Manifest 標準**：

```yaml
# ip-manifest.yaml — Vibe IC IP 標準描述格式
name: "uart_controller"
version: "1.2.0"
type: "soft"  # soft | hard
license: "Apache-2.0"  # 授權類型
provider: "deFintek"  # 來源

# 功能描述（供語義搜尋）
description: "Full-duplex UART controller with configurable baud rate, 8N1/8E1/8O1, FIFO depth 16"
category: "Interface/UART"  # 對應 IC Taxonomy
keywords: ["uart", "serial", "rs232", "fifo"]

# 技術規格
specs:
  clock_freq_max: "100MHz"
  supply_voltage: "1.8V-3.3V"
  interface: ["APB", "Wishbone"]
  gate_count_estimate: 2500

# 檔案清單
files:
  rtl: ["src/uart_tx.v", "src/uart_rx.v", "src/uart_top.v"]
  testbench: ["tb/uart_tb.sv"]
  docs: ["docs/uart_datasheet.pdf"]
  # Hard IP 額外需要：
  # gds: "layout/uart_gf180.gds"
  # lef: "layout/uart_gf180.lef"
  # liberty: "timing/uart_gf180_tt.lib"

# 製程相容性
compatible_pdks:
  - name: "GF180MCU"
    node: "180nm"
    verified: true
  - name: "SKY130"
    node: "130nm"
    verified: false  # RTL 可用，但未做 PPA 驗證

# 介面定義（讓 AI Agent 自動接線）
ports:
  - name: "clk"
    direction: "input"
    width: 1
    description: "System clock"
  - name: "rst_n"
    direction: "input"
    width: 1
    description: "Active-low reset"
  - name: "tx"
    direction: "output"
    width: 1
    description: "UART transmit data"
  - name: "rx"
    direction: "input"
    width: 1
    description: "UART receive data"
  - name: "apb"
    direction: "slave"
    type: "APB"
    description: "APB slave interface for register access"

# 驗證狀態
verification:
  simulation: "pass"
  formal: "pass"
  synthesis: "pass"
  silicon_proven: false
```

有了這個標準格式，MCP 的 AI Agent 就能做到：

1. **自動搜尋**：用戶說「我需要一個 UART」→ 從 IP Database 查詢 `category: Interface/UART` 的所有 IP
2. **自動匹配**：根據用戶的 PDK 選擇和介面需求，篩選相容的 IP
3. **自動整合**：讀取 `ports` 定義，自動產生 top-level 接線（wire/interconnect）
4. **自動驗證**：檢查 IP 的 verification status，提示用戶哪些需要額外驗證

### 5.4 IP 來源與收集策略

| 來源 | IP 類型 | 數量 | 授權 | 說明 |
|------|---------|------|------|------|
| [OpenCores](https://opencores.org/) / [FOSSi Foundation](https://www.fossi-foundation.org/) | Soft IP | 數百個 | LGPL / BSD / Apache | 歷史最久的開源 IP 社群，含 UART、SPI、I2C、RISC-V 等 |
| [LibreCores](https://www.librecores.org/) | Soft IP | 數十個 | 多種 | FOSSi Foundation 維護的 IP 目錄 |
| GitHub RISC-V 生態 | Soft IP | 50+ CPU cores | BSD / Apache | [CHIPS Alliance](https://chipsalliance.org/) 等組織下的 RISC-V 實作 |
| Efabless Caravel 生態 | Soft + Hard | 600+ 設計 | Apache | [Efabless](https://efabless.com/) 歷屆 shuttle 提交的設計 |
| 自己開發的 IC | Soft + Hard | 持續增長 | 自訂 | BENCH-A、SN74HC163 等模組可直接轉為 IP |

### 5.5 IP 商業模式 — 從消費者到供應者

這是你提到的非常關鍵的一點。IP 不只是成本項，也可以是營收項：

**階段一：IP 消費者（現在）**

- 使用開源 IP（免費）加速設計
- 購買商業 IP（如需要高品質 analog IP）

**階段二：IP 生產者（中期）**

- 每一個透過 Vibe IC 完成的設計，其中的通用模組都可以提取出來成為可重用 IP
- 例如 BENCH-A 裡的 `crc8_engine`、`aid_protocol` 模組，經過驗證和文件化後就是可授權的 Soft IP
- 透過 silicon-proven（流片驗證過）的標記，提高 IP 的價值和可信度

**階段三：IP Marketplace（長期）**

| 營收模式 | 說明 | 業界參考 |
|----------|------|----------|
| **授權費（License Fee）** | 一次性授權使用 | ARM 對 CPU core 的授權模式 |
| **權利金（Royalty）** | 每顆晶片按比例收費 | ARM 的 per-chip royalty |
| **訂閱制** | 月/年費存取 IP 庫 | [Synopsys DesignWare](https://www.synopsys.com/designware-ip.html) 的模式 |
| **Freemium** | 基礎 IP 免費，進階版（silicon-proven, 含 support）收費 | 開源 + 商業雙授權 |

根據 [GlobeNewsWire 的市場報告](https://www.globenewswire.com/news-release/2026/03/02/3247502/28124/en/Semiconductor-Intellectual-Property-Research-Report-2026-2035-A-13-54-Billion-Market-by-2030-with-Arm-Synopsys-Cadence-Design-Systems-CEVA-Imagination-Technologies-Leading.html)，半導體 IP 市場由 ARM（處理器 IP）、Synopsys（介面/analog IP）、Cadence（verification IP）主導，但在 **開源 IP + AI-Native 整合**這個交叉領域，目前沒有主導者，這是 Vibe IC 可以卡位的空間。

### 5.6 IP Database 的結構需求

IP Database 需要跟 Section 3 的 IC 文件資料庫整合，但增加 IP 特有的欄位：

| 欄位 | 說明 | 用途 |
|------|------|------|
| **IP Type** | Soft / Hard / Firmware | 決定串接方式 |
| **PDK Compatibility** | 相容的製程清單 | 過濾不相容的 IP |
| **Bus Interface** | APB / AXI / Wishbone / custom | 自動 interconnect 生成 |
| **Verification Level** | RTL-only / Sim-passed / Formal-proved / Silicon-proven | 品質排序 |
| **License** | Apache / BSD / LGPL / Commercial | 合規性檢查 |
| **Port Map** | 完整 I/O 定義 | AI Agent 自動接線 |
| **Dependencies** | 依賴的其他 IP | 自動拉取相依 IP |

---

## 6. 建議的優先行動排序（更新版）

| 優先級 | 行動項目 | 預計時程 | 理由 |
|--------|----------|----------|------|
| **P0** | 完善 EDA MCP 自動化（減少 checkpoints） | 進行中 | 核心產品能力 |
| **P0** | 建立 IC 文件資料庫（Datasheet/AppNote/Spec） | 4-8 週 | Vibe IC 入口的關鍵 |
| **P1** | 開發 Datasheet Generator skill | 4-6 週 | 從「自然語言 → 完整 Datasheet」的橋樑 |
| **P1** | 整合 SKY130 和 IHP SG13G2 到 MCP flow | 2-4 週 | 擴大 PDK 覆蓋 |
| **P1** | 定義 IP Manifest 標準 + 收集開源 IP | 4-6 週 | IP 重用是加速設計的核心，也為 IP Marketplace 打基礎 |
| **P2** | 建立 IC Taxonomy + 向量資料庫 | 4-6 週 | 讓 search/mapping 有效率 |
| **P2** | 開發 IP 自動整合 skill（自動搜尋、匹配、接線） | 6-8 週 | 讓 AI Agent 能自動在 flow 中嵌入 IP |
| **P2** | 社群建設（文件、教學、forum） | 持續 | open source 成功的必要條件 |
| **P2** | 將已有設計（BENCH-A 模組）IP 化 | 2-4 週 | 產出第一批自有 IP，驗證 IP 流程 |
| **P3** | 與 foundries 洽談量產合作 | 8-12 週 | 中期營收所需 |
| **P3** | 建立 IP Marketplace / 授權機制 | 12-16 週 | 長期營收管道 |
| **P3** | 設計責任條款與法律準備（含 IP 授權） | 4-8 週 | 商業化必要 |

---

## 7. 總結

IC 文件資料庫和 IP 整合是 Vibe IC 平台的兩根支柱：

**文件資料庫**解決「用戶不知道要什麼」的問題——透過 RAG 找到參考 IC，自動生成 Datasheet 作為 flow 的 input。

**IP 整合**解決「不需要全部從零做起」的問題——讓用戶直接嵌入現成的 Soft/Hard IP，大幅縮短設計時間。而且每一個完成的設計都能反過來變成 IP，形成正向飛輪。

長期來看，**IP Marketplace** 是一個非常有潛力的營收管道。半導體 IP 市場在 2025 年已達 $79.7 億美元，而「開源 IP + AI-Native 自動整合」這個交叉點目前沒有主導者。如果 Vibe IC 能在這裡建立標準（IP Manifest）和生態（IP 庫 + 自動整合工具），就有機會成為這個新興市場的 platform player。

---

*Generated by Claude Opus 4.6 | AI-Native IC Design Project | 2026-04-07*
