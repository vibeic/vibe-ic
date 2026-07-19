---
layer: L9
ic: edge_llm_accel
status: final
written_at: 2026-07-18
sources:
  - L1 tapeout targets
  - pdk_registry.json `nangate45` entry(能力邊界)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — 僅描述物理約束目標"
  r2_blackbox: "PASS — 引用 PDK registry 與 SDC 目標"
  r3_multiple_correct: "PASS — floorplan / placement / CTS 策略自由"
---

# L9 — Constraints / Floorplan

## 9.1 SDC

```sdc
set_units -time ns
create_clock [get_ports clk] -name core_clock -period 10.0
```

| 項目 | 值 |
|---|---|
| 主時脈 | `clk`,**10 ns(100 MHz)** |
| I/O delay | input/output delay = clock period 之 20%(2 ns)預設;實作可 override 並於 declaration.json 註記 |
| Corner | **typical**(NangateOpenCellLibrary_typical.lib)。Nangate45 平台僅隨附 typical corner liberty — 單 corner STA,誠實聲明,不假造 multi-corner 簽核 |
| False path / multi-cycle | 無預設;實作若加須於 L7 證明 |

## 9.2 Floorplan

| 項目 | 值 |
|---|---|
| Die size | **2400 × 2400 µm(5.76 mm²)**(1.4M cells + 20 巨集之可繞線裕度;L1) |
| Core utilization | 隨 die 固定後由工具推得(目標 ~50–55%);**不得**為湊 util 而縮 die 犧牲可繞線性 |
| 巨集擺放 | 20 × fakeram45_2048x39(各 206.91×219.80 µm,合計 ~0.91 mm²);位置/朝向由 macro placer 自選,建議 halo ≥ 5 µm |
| Pin placement | 工具自選(無 pad ring;macro-level) |

## 9.3 PDN / Routing

| 項目 | 值 |
|---|---|
| 電源 | `VDD` / `VSS`(NangateOpenCellLibrary 標準) |
| PDN | 平台預設 strategy(follow-pin rails + 上層 straps);巨集電源環/straps 由工具 |
| Routing layers | 平台預設(metal1 – metal10) |
| 平行度 | PnR/route 使用主機全部 CPU cores(deterministic 結果不受 threads 影響之工具步驟) |

## 9.4 簽核 (Signoff) 目標 — tape-out simulation 範圍

| Gate | 標準 |
|---|---|
| STA @ 100 MHz(typical) | **WNS ≥ 0、TNS = 0** |
| Detailed route | **DRC violations = 0** |
| Antenna | **violations = 0**(必要時 diode 修復) |
| GDS | merged GDSII 成功輸出(std cells 實體、SRAM abstract outline) |
| KLayout DRC | FreePDK45.lydrc(educational deck)報告產出;**非** foundry 簽核 |
| LVS | Nangate45 **無 LVS deck**(`lvs_deck=null`)→ 誠實 waive;結構性 CDL 檢查為選項 |
| IR-drop | 不要求(abstract SRAM 無功耗模型之完整性;PDN 連通性檢查即可) |

## 9.5 已知工具邊界(整合須知)

- **Module port 禁用 `signed` 宣告**(L3;OpenROAD Verilog reader 限制)。
- Tie-high/low 用 `LOGIC1_X1`/`LOGIC0_X1`。
- 2000×2000 µm(4 mm²,~77% util)經驗上 **不可繞線**;die 須 ≥ 2400×2400。

## 9.6 不在 L9 約束的事

- ❌ Cell placement 座標、CTS topology、buffer 策略、routing layer 分配
