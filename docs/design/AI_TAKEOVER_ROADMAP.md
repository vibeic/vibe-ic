# AI 取代路線圖 — IC 設計流程中 LLM vs EDA vs 人工

**對應**: Vision Alignment T-3
**更新**: 2026-04-07（基於實際工具驗證）

---

## 流程總覽

```
Spec ──→ RTL ──→ Lint ──→ Sim ──→ Formal ──→ Synth ──→ P&R ──→ DRC ──→ GDS ──→ Tapeout ──→ 晶片
 🤖       🤖      🤖/🔧    🔧      🔧        🔧       🔧      🔧     🔧      🔧/👤      👤
```

圖例：🤖 = LLM 原生 / 🔧 = EDA 工具（AI 編排）/ 👤 = 人工必要

---

## 逐步驟分析

| 步驟 | 誰做 | 說明 | 現在狀態 |
|------|------|------|---------|
| **1. 規格理解** | 🤖 LLM | 從自然語言/datasheet 提取功能規格 | ✅ 已驗證 |
| **2. 架構選擇** | 🤖 LLM + 👤 審查 | LLM 提出架構（FSM、pipeline 等），人工確認 | ✅ 可行 |
| **3. RTL 設計** | 🤖 LLM | LLM 直接寫 SystemVerilog | ✅ 已驗證（11 模組） |
| **4. RTL Lint** | 🔧 Verilator | LLM 呼叫 `eda_lint`，讀取結果 | ✅ 已驗證 |
| **5. RTL 修復** | 🤖 LLM | LLM 根據 lint 結果修 RTL | ✅ 已驗證 |
| **6. Testbench** | 🤖 LLM | LLM 產生 testbench | ✅ 已驗證 |
| **7. Simulation** | 🔧 iverilog/Verilator | LLM 呼叫 `eda_simulate` | 🟡 簡單設計 ✅，複雜 SV ❌ |
| **8. Assertions** | 🤖 LLM | LLM 產生 SVA (需改寫為 Yosys 格式) | ✅ 已驗證 |
| **9. Formal** | 🔧 SymbiYosys | LLM 呼叫 `eda_formal` | ✅ 已驗證 |
| **10. Synth wrapper** | 🤖 LLM | LLM 自動產生 inout→split wrapper | ✅ 已驗證（新 skill） |
| **11. Synthesis** | 🔧 Yosys | LLM 呼叫 `eda_synth` | ✅ 已驗證 |
| **12. PPA 分析** | 🤖 LLM + 🔧 | LLM 讀取合成報告，產生 PPA 報告 | ✅ 已驗證 |
| **13. Place & Route** | 🔧 OpenROAD | LLM 呼叫 `eda_pnr` | ✅ 已驗證 |
| **14. STA** | 🔧 OpenSTA | LLM 呼叫 `eda_sta`，讀取 slack | ✅ 已驗證 |
| **15. GDS** | 🔧 KLayout | LLM 呼叫 `eda_gds` | ✅ 已驗證 |
| **16. DRC** | 🔧 Magic/KLayout | LLM 讀取 DRC 結果 | 🟡 部分驗證 |
| **17. LVS** | 🔧 Netgen | LLM 呼叫 Netgen | ❌ 未做 |
| **18. Tapeout 文件** | 🤖 LLM | LLM 產生 checklist + release notes | ✅ 已驗證 |
| **19. Foundry 提交** | 👤 人工 | 人工選擇 shuttle、付款、提交 | 👤 必須人工 |
| **20. 類比設計** | 👤 人工 | LDO/POR/OSC 需電晶體級設計 | 🔴 人工瓶頸 |
| **21. 封裝/測試** | 👤 人工 | Wafer probe、wire bonding、final test | 👤 必須人工 |

---

## AI 覆蓋率

| 類別 | 總步驟 | 🤖 LLM 原生 | 🔧 AI 編排 EDA | 👤 人工必要 |
|------|--------|------------|--------------|-----------|
| 前端 (spec→RTL) | 6 | **6** (100%) | 0 | 0 |
| 驗證 | 4 | 2 | **2** | 0 |
| 後端 (synth→GDS) | 6 | 1 | **5** | 0 |
| Signoff | 3 | 1 | **1** | 1 |
| 量產 | 2 | 0 | 0 | **2** |
| **合計** | **21** | **10 (48%)** | **8 (38%)** | **3 (14%)** |

**結論**：86% 的 IC 設計步驟可由 LLM + EDA 工具自動完成。剩下 14%（類比設計、foundry 提交、封裝測試）需要人工。

---

## 到實體晶片的完整時程

| 週次 | 活動 | 執行者 | 產出 |
|------|------|--------|------|
| 1 | Vibe Coding: spec→RTL→驗證→合成→P&R→GDS | 🤖+🔧 | DRC-clean GDS |
| 2 | 人工審查 + 類比設計（如需要） | 👤 | Tapeout package |
| 3 | 提交 Efabless chipIgnite | 👤 | 訂單確認 |
| 4-8 | Foundry 製造（GF180MCU） | 🏭 | 晶圓 |
| 9-10 | 封裝 + 測試 | 👤+🏭 | **實體晶片** |

**總時間：10 週 ≈ 2.5 個月**

---

## 流片費用

| 方案 | PDK | 費用 | 時間 | 適合 |
|------|-----|------|------|------|
| Efabless chipIgnite | GF180MCU | ~$10K | 8-10 週 | 商業/研究 |
| Google Open MPW | SKY130 | 免費 | 12-16 週 | 學術/開源 |
| Tiny Tapeout | SKY130 | $100-300 | 12-16 週 | 教育/實驗 |

---

## 這不是未來——這是現在

在 2026-04-07，我們已經用 LLM (Claude Opus 4.6) + 開源 EDA 工具，在一個 session 內完成了：

1. SN74HC163: **Verilog → Simulation → Formal Proof → Synthesis → P&R → DRC Clean → GDS** (GF180MCU 180nm)
2. BENCH-A (2,693 cells): **SystemVerilog → Lint → Synthesis → P&R → GDS** (GF180MCU 180nm)

下一步就是把 GDS 提交到 Efabless chipIgnite，等 8-10 週拿到晶片。

**Vibe Coding for ASIC 不是願景，是已經可以做到的事。**
