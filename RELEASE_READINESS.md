# vibe-ic Plugin — Release Readiness（發布基礎條件 / Definition of Done）

> **一句話定義**：在一台**全新平台**上，裝好 EDA open-source Docker + vibe-ic plugin 後，
> Claude Opus 4.8 立即成為 **IC Expert Agent**——它非常清楚 plugin 的**能力範疇、所有入口路徑、
> 預期結果**，能從**兩種輸入**自動跑完 **Phase 1 → 2 → 3**，且在 Local 端重現的 benchmark 分數
> 與我們驗證過的一致。

狀態圖例：✅ 已具備　🟡 部分／打包待補（能力已在，缺文件或一鍵化）　🔴 待補

---

## 1. 基礎運行環境與安裝

| # | 可驗收條件 | 狀態 | 依據 / 缺口 |
|---|---|---|---|
| 1a | vibe-ic 是 plugin，可直接掛到 Claude 使用 | ✅ | `vibe-ic-marketplace/.claude-plugin/marketplace.json` + `plugins/vibe-ic/.claude-plugin/plugin.json`（v1.3.29） |
| 1b | 安裝前提：先安裝 EDA open-source 工具的 Docker（IIC-OSIC-TOOLS） | 🟡 | 依賴已存在（`mcp-eda/` 工具跑在 IIC-OSIC-TOOLS 容器）；**缺**：頂層一頁前置安裝說明（現只在 `mcp-eda/INSTALL_GUIDE.md`） |
| 1c | 裝完 Docker 再裝 plugin，MCP **自動**把兩者接起來（Docker 工具經 MCP 被 plugin 調用） | 🟡 | `.mcp.json` + `mcp-eda/src/index.js`（工具在容器內執行）；**待驗**：全新機器 zero-config 自動接上、健康檢查（`mcp_server_health_check`） |

**發布條件 1**：一條龍安裝路徑（裝 Docker → 裝 plugin → `eda_doctor` 綠燈）在乾淨機器上實測通過。

---

## 2. 基本驗證與執行流程

| # | 可驗收條件 | 狀態 | 依據 / 缺口 |
|---|---|---|---|
| 2a | 全新平台下載安裝後即可用，**並能重現 benchmark 分數** | 🟡 | 分數已產出並上線（見 §4）；**缺**：一鍵 clean-platform reproduce 腳本 + 實測 |
| 2b-i | 輸入方式一：提供一個 **input folder** → 自動跑 Phase 1→3 | ✅ | `programs/vibe_ic_one_shot_runner.py <project>`（`--pdk sky130A` 等） |
| 2b-ii | 輸入方式二：與 Claude（IC expert）**對話**，累積對話內容作輸入 → 跑完 Phase 1→3 | ✅ | ic-expert-agent 對話 → 統一 DOC→JSON track → 進 Phase 1 |

**發布條件 2**：兩種輸入各有一個 end-to-end 範例，從輸入到 Phase 3 產物一鍵可跑。

---

## 3. IC Expert Agent 定位

| # | 可驗收條件 | 狀態 | 依據 |
|---|---|---|---|
| 3a | plugin 啟動即讓 Claude 變成 IC Expert Agent | ✅ | binding identity（每回合 system-reminder 注入）；embody `agents/ic_expert_db/` + `agents/lessons/` + `skills/` |
| 3b | 透過對話得到詳細 Spec，並**自動補足**設計所需資訊 | ✅ | expert-DB（**86 classes / 98 lessons**）+ program-vs-AI 收斂 + sufficiency gate |
| 3c | 另一路徑：從 **Design Documents 直接匯入** | ✅ | Phase 1 DOC → L1–L23 JSON |

**發布條件 3**：expert-DB + lessons 打包在 plugin 內、consistency gate 綠燈（已 PASS），對話與匯入兩路徑皆可觸發補全。

---

## 4. Benchmark 驗證（Local 端）

| # | 可驗收條件 | 狀態 | 依據 / 缺口 |
|---|---|---|---|
| 4a | 支援 **VE-v2 / VE-Human / RTLLM / CVDP** | ✅ | `benchmark/BENCHMARK_REGISTRY.json`：verilogeval-v2(C)、verilogeval-human(C)、rtllm(B)、cvdp-open(C/D, RUNNABLE) |
| 4b | Local 分數 = 我們驗證分數（Opus 4.8 一輪高分） | 🟡 | **最難的保證**。已驗證基準：RTLLM 排除 defect+tool-gap **43/43=100%**（全 blind-proven）、VE-v2 & VE-Human **153/156**、cvdp-open single-shot **210/302**。**缺**：clean-run 一致性實測 + 容差/隨機性說明 |
| 4c | Debug 題（CVDP 類）路徑已配置：一般走 Phase 1；debug 走「RTL 產生後」的收斂路徑，且 plugin **自動判定** | ✅ | dual-track：正常 Phase 1 入口；`rtl_gen=null` → WAIVE `spec-to-rtl` → runner gates 收斂 |

**發布條件 4**：至少一個 benchmark 在乾淨機器一鍵跑出的分數落在驗證值容差內；4 個 benchmark 的預期分數表隨附。

**已驗證分數（本 session, plugin v1.3.27–29, iverilog）**：

| Benchmark | Shape | Blind 分數 | 排除 defect/floor |
|---|---|---|---|
| VerilogEval-v2 | C | 153/156 | 100% |
| VerilogEval-Human | C | 153/156 | 100% |
| RTLLM v2.0 | B | 43/50 | **43/43 = 100%** |
| cvdp-open (302 nonagentic) | C/D | 210/302 (single-shot) | — |

---

## 5. Guide Map 與流程控制

| # | 可驗收條件 | 狀態 | 依據 |
|---|---|---|---|
| 5a | 清楚的 Guide Map：**~50+ 步、3 Phase** | ✅ | `flow/phase1_phase2_phase3.yaml`（`total_steps=44` + `analog_steps=9` ≈ **53 步**，3 phase）；`flow_compliance_check.py` 強制（無 exit 0 不算 PASS） |
| 5b | **多入口**：一般 Phase 1；debug 從 Phase 2 中段（有 RTL 後）進入 | ✅（🟡 文件） | 存在於 flow；**建議**：把「入口決策表」抽成一頁 |
| 5c | 掌握所有**收斂 loop**（含 Analog loop、ADI 接口 loop） | ✅ | `adi-spec-gen`(L5_ADI_SPEC)、`analog-sizing-loop`、Analog Corner Sweep(PVT)、eco_loop 皆在 flow |

**發布條件 5**：一頁「入口決策表 + 收斂 loop 清單」文件化，AI 與使用者一眼看懂何時走哪個入口、有哪些 loop。

---

## 🎯 總結（發布的必要條件）

> 使用者在 **Claude Opus 4.8** 上啟用 plugin 時，AI 就是 IC Expert Agent，且**非常清楚三件事**：

1. **能力範疇（capability scope）**：Phase 1–3 全流程 + Analog/Mixed + 4 大 benchmark + expert-DB/skills 的覆蓋範圍。
2. **所有入口路徑（entry paths）**：Phase 1 前門（folder / 對話 / 文件匯入）、debug 中段入口（RTL 後收斂）、benchmark dispatch 入口。
3. **預期結果（expected results）**：每個 Phase 的產物、每個 benchmark 的預期分數，能自我核對。

---

## 🚦 最小可發布集合（Release Gate）

**已具備（核心能力）**：plugin 安裝、IC Expert identity、雙輸入、53 步 3-Phase Guide Map、4 benchmark registry、debug dual-track、Analog/ADI loops、benchmark 分數已產出上線。

**發布前必補的 3 個缺口（皆為「打包 / 可重現性」，非「能力」）**：

1. **🟡 一鍵 clean-platform 驗證腳本**（1c/2a/4b）— **腳本已建：`tools/release/verify_clean_platform.sh`**
   4 階段：host 工具 preflight → plugin 結構 → plugin 自檢（flow map / DB consistency / chip-agnostic / MCP import）
   → benchmark 重現（re-score committed samples，斷言＝驗證值：RTLLM 44/50、VE-v2 153/156、VE-Human 153/156）。
   本機實測 **18 PASS / 0 FAIL → READY**。**仍待補**：(i) 真正全新機器實跑；(ii) live Benchmark-Agent 一輪 blind 重現路徑（需 live agent，非 shell 可涵蓋，腳本已註明）。
2. **🟡 頂層 INSTALL / README（single source of truth）**（1b/1c/2b）
   Docker 前置 + MCP 自動接線 + 兩種輸入用法，收斂成一份入口文件。
3. **🟡 一頁「入口決策表 + 收斂 loop 清單 + 預期結果表」**（5b/5c/總結）
   讓 AI 與使用者一眼掌握能力範疇、入口、預期產物/分數。

> 三個缺口都**不是能力缺失**，而是**上線打包**：能力已驗證、已上線 origin/main；剩下的是讓一個
> 陌生使用者在乾淨環境「零摩擦重現」。
