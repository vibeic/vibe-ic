# Vibe-IC 安裝 + 觸發

> Companion to [`33_step_flow_overview.md`](./33_step_flow_overview.md).
> 那篇講「設計流程是什麼」；這篇講「怎麼裝、怎麼開動」。

## 安裝（兩條件 + 三步驟）

### 先決條件

| 項目 | 版本 | 檢查 |
|---|---|---|
| Linux | Ubuntu 22.04 / 24.04 推薦 | `lsb_release -a` |
| Docker | 20.10+ | `docker --version` |
| Node.js | 18+ | `node --version` |
| Python | 3.10+ | `python3 --version` |
| Claude Code CLI | 最新 | `claude --version` |
| 磁碟 | ≥ 25 GB（IIC-OSIC docker image ~22 GB） | `df -h` |

加 docker 群組：
```bash
sudo usermod -aG docker $USER && newgrp docker
docker ps   # 必須跑得起來，否則 mcp-eda 全部 silent fail
            # （v2.4.1+ 會回 actionable hint，不再吞錯誤）
```

---

### Step 1 — 取 repo

```bash
git clone https://github.com/reyerchu/AI_IC_design.git
cd AI_IC_design
```

### Step 2 — 安裝 plugin（兩個都要）

```bash
# Skills + agents
claude plugin install vibe-ic-marketplace/plugins/vibe-ic-core

# Deterministic 程式 + compliance gate（必裝，不然 33-step strict gate 跑不起來）
claude plugin install vibe-ic-marketplace/plugins/vibe-ic-d
```

備用（手動 copy）：
```bash
mkdir -p .claude/plugins
cp -r vibe-ic-marketplace/plugins/vibe-ic-core .claude/plugins/
cp -r vibe-ic-marketplace/plugins/vibe-ic-d    .claude/plugins/
```

### Step 3 — 啟 EDA Docker + MCP server

```bash
# IIC-OSIC-Tools（Yosys / OpenROAD / KLayout / Magic / Netgen / Verilator / Fault ATPG…）
docker pull hpretl/iic-osic-tools:latest
docker run -d --name iic-eda -v $HOME:$HOME hpretl/iic-osic-tools:latest sleep infinity

# MCP EDA server（v2.5.3 — 24 EDA + 6 device = 30 tools）
cd mcp-eda-server
npm install
claude mcp add eda node $(pwd)/src/index.js -e EDA_CONTAINER=iic-eda
```

驗證：
```bash
bash mcp-eda-server/test_manifest.sh                 # 應 20/20 PASS
bash mcp-eda-server/test/test_devices_registry.sh    # 應 39/39 PASS
```

完整版（含 Quartus + custom PDK）見 [`mcp-eda-server/INSTALL_GUIDE.md`](../../mcp-eda-server/INSTALL_GUIDE.md)。

---

## 觸發 — 五種方式

### 1. 從 prompt 直接設計新 IC（Phase 1 對話入口）

```
claude
> /phase1
# 或更直白：
> 我想做一顆 X，請帶我走完規格收集
```

PM Agent 跟你對話 → IC Expert Agent 整理 → 產 `generated_docs/L*.json` +
`human_docs/L*.md`。

### 2. 既有 vendor docs 出發（Phase 2a）

把 PDF / xlsx / OTP / PDK 放進 `<project>/input/`，然後：

```
> /flow-orchestrate
```

它會逐步喊 Phase 2a 的 17 skill 把 docs → L1-L13 → 進 Phase 2b/3。

### 3. 跑完整 33-step Phase 2+3（Path B 主要入口）

```
> /flow-orchestrate
```

這是**任何下游 EDA 工作的唯一合法入口**。它會：

1. 列出 33-step 計畫（先看 plan 才做）
2. 每步呼叫對應 skill / MCP 工具
3. 每 stage 結束跑 `stage{1,2,3,4}_compliance.py`
4. 全部跑完跑 `flow_compliance_check --strict` 4/4

### 4. 單一 skill 觸發（不走完整 28 步）

```
> /rtl-review            # 審 RTL
> /testbench-gen         # 寫 tb
> /drc-fix               # 修 DRC violation
> /tapeout-checklist     # 看是否可流片
> /synth-doctor          # synth fail 救援
> /sta-review            # 看時序 report
```

71 個 skill 都可這樣個別叫，不會強制觸發整條 flow。

### 5. 程式化 / CI 用法（不開 Claude）

```bash
# Compliance 矩陣
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/flow_compliance_check.py \
  --project <output_dir> --strict --json reports/flow_compliance.json
# 期望: verdict=PASS, 28/28

# 單一 deterministic gate
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/practical_notes_specificity_check.py --json
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/fpga_wrapper_input_polluter_check.py \
  --rtl rtl/ --json reports/gates/fpga_input_polluter.json

# 環境健康檢查（v2.5.0+）
# 在 Claude 裡：
> /eda_doctor            # 探 docker / container / 9 tool binary / PDK 可讀性
```

---

## 黃金規則

> **任何觸發下游 EDA（synth / PnR / GDS / sign-off）的 prompt，agent 第一步必須叫
> `flow-orchestrate`。** 不准 agent 自己 `docker exec` 跳過 MCP，也不准它從 prompt
> 直接喊 Quartus / Yosys / OpenROAD。
>
> 詳見 [`vibe-ic-marketplace/AGENT_USAGE_GUIDE.md`](../../vibe-ic-marketplace/AGENT_USAGE_GUIDE.md)。

---

## 常見裝完不動的排查

| 症狀 | 原因 | 解 |
|---|---|---|
| `eda_lint` 一律回 PASS | docker socket 沒 access | `sudo usermod -aG docker $USER && newgrp docker`；v2.4.1+ 已會回 hint，舊版會 silent PASS |
| `flow-orchestrate` 找不到 skill | plugin 沒 install | `ls .claude/plugins/` 看是否有 vibe-ic-core / vibe-ic-d 目錄 |
| `flow_compliance_check.py` 報錯 | vibe-ic-d 沒裝 | 補裝 `claude plugin install vibe-ic-marketplace/plugins/vibe-ic-d` |
| `eda_rtl_audit` 找不到 programs_dir | 路徑硬編 | v2.5.2+ 會自動偵測；舊版設 `VIBE_IC_PROGRAMS_DIR` 環境變數 |
| MCP 工具列表沒 `eda_*` | mcp 沒 add | `claude mcp list`；沒看到就 `claude mcp add eda node $(pwd)/mcp-eda-server/src/index.js -e EDA_CONTAINER=iic-eda` |
| `device_*` 工具消失 | docker 容器叫別的名字 | `EDA_CONTAINER=<your-container-name>` |
| USB device tools（tester / scope）沒看到 | udev rule 沒 install | `sudo cp mcp-eda-server/src/devices/{tester,scope}/*/udev/*.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger` |

---

## 升級 / 維護

```bash
# 拉新版 plugin + mcp-eda
cd AI_IC_design
git pull origin main

# 重啟 mcp server（reconnect 才會看到新 tool schema）
# 在 Claude 裡：
> /mcp                   # 看 server 狀態
# 或重新 add：
claude mcp remove eda
claude mcp add eda node $(pwd)/mcp-eda-server/src/index.js -e EDA_CONTAINER=iic-eda
```

升級後第一次跑 `/eda_doctor` 確認 9 個 tool binary 都還在。

---

## Reference

- 流程設計（33 步 + 3 phase）：[`33_step_flow_overview.md`](./33_step_flow_overview.md)
- Plugin marketplace 入口：`vibe-ic-marketplace/.claude-plugin/marketplace.json`
- Agent 使用準則：`vibe-ic-marketplace/AGENT_USAGE_GUIDE.md`
- MCP server 細節：`mcp-eda-server/INSTALL_GUIDE.md` + `mcp-eda-server/README.md`
- 全域伺服器架構：`~/CLAUDE.md`
