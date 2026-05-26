# spm — 56-step cross-check 矩陣（我們生成 vs 上游 open-source）

> **Pillar 6 / Step 18（Design-for-ECO）**：新增 flow Step 18「Spare-cell + ECO-prep
> insertion」——在 placement 後、CTS 前，置入分布式、tie-off、`dont_touch`/`keep` 保護的
> 7 顆 spare std cell（inv/nand2/nor2/mux2/aoi/dff，密度 0.0232）。`spare_cell_coverage_check`
> = PASS、`spare_cell_preservation_check` = intact（inserted 7 / survived 7 / removed 0 /
> keep-attr 完整）。REF（`spm_e2e`）**完全沒有 spare / dont_touch** → 本步 OURS
> **BETTER-THAN-REF**（提供 REF 缺少的 metal-only-ECO readiness），且帶 spare 後 DRC/LVS/多角 STA
> sign-off 仍成立。原 Step 18..40 全部 +1 重新編號為 19..41。

> 誠實聲明：spm sign-off 目前只完成「端點」cross-check（功能等價 vs golden+上游RTL、多角STA、DRC、LVS device-match）。
> 以下列出全部 56 步的「逐步輸出 cross-check」方法與狀態。**重點**：因為我們刻意用了**不同微架構**（carry-save vs 上游），
> GDS/netlist 無法做「像素級/結構級相同」比對；正確的 cross-check 是「兩邊各自 DRC/LVS/STA 通過 + 功能等價」（端點已驗）。

| Step | 名稱 | 狀態 | 產物(上游/我們) | cross-check 方法 |
|---|---|---|---|---|
| D1 | Phase 1 Doc Extraction (17 skills + dialogue e | ⬜ 可做未做 | 上游有/我們有 | L-doc 欄位/語意 diff：我們 vs 上游（同一份 spec 抽出） |
| 1 | Spec-to-RTL | ✅ DONE | 上游有/我們有 | 功能等價 LEC + co-sim：我們RTL vs 上游RTL |
| 2 | 🔁 Lint (RTL + Quartus-unsafe patterns + RTL-bu | ⬜ 可做未做 | 上游有/我們無 | lint clean 對齊（兩邊都應 clean） |
| 3 | 🔁 CDC / RDC check | ⬜ 可做未做 | 上游有/我們無 | CDC/RDC 報告對齊（單時脈→兩邊 trivially clean） |
| 4 | 🔁 Simulation (testbench-based + L10/L12 covera | ✅ DONE | 上游有/我們有 | 對共用 golden 向量模擬（spec/NIST golden） |
| 5 | 🔁 Formal verification (assertions proved + bit | ⚠️ 缺/兩邊都沒跑 | 上游有/我們無 | formal assertions-proved 對齊 |
| 6 | FPGA early prototype + verification report aud | — N/A | — | FPGA early proto（ASIC 流程，選用） |
| 7 | Constraint setup (SDC + PVT matrix) | ⬜ 可做未做 | 上游有/我們有 | SDC diff：時脈週期/IO delay（皆源自 L9） |
| 8 | 🔁 SDC validation | ⬜ 可做未做 | — | SDC validation 對齊 |
| 9 | Synthesis (Yosys → mapped netlist) | ⬜ 可做未做 | 上游有/我們有 | synth netlist：cell數/面積比 + LEC 我們≡上游 |
| 10 | 🔁 Pre-layout STA (multi-corner) | ⚠️ 缺/兩邊都沒跑 | — | pre-layout 多角 STA slack 比對 |
| 11 | DFT insertion (scan chain + ATPG) | ⚠️ 缺/兩邊都沒跑 | 上游有/我們無 | DFT scan-chain 覆蓋率比對 |
| 12 | Post-DFT optimization (resynth / buffering) | ⚠️ 缺/兩邊都沒跑 | — | post-DFT netlist 比對 |
| 13 | 🔁 Equivalence check (RTL ≡ post-DFT netlist) | ⚠️ 缺/兩邊都沒跑 | — | LEC：RTL≡post-DFT netlist |
| A1 | Analog Spec Extraction | — N/A | — | 類比步驟（spm 純數位） |
| A2 | Analog Topology Selection | — N/A | — | 類比步驟（spm 純數位） |
| A3 | Analog Netlist Generation | — N/A | — | 類比步驟（spm 純數位） |
| A4 | Analog Corner Sweep (PVT) | — N/A | — | 類比步驟（spm 純數位） |
| A5 | Analog Layout | — N/A | — | 類比步驟（spm 純數位） |
| A7 | 🔁 Post-Layout Resimulation | — N/A | — | 類比步驟（spm 純數位） |
| A8 | Hardmacro Generation (LEF + Liberty + GDS + Ve | — N/A | — | 類比步驟（spm 純數位） |
| A9 | 🔁 Co-Simulation / HW Verification | — N/A | — | 類比步驟（spm 純數位） |
| 14 | 🔁 pre-PnR Yosys gate (phase2/stage2/synth scri | ⬜ 可做未做 | — | pre-PnR Yosys gate 對齊 |
| 15 | Floorplan + PDN | ⬜ 可做未做 | 上游有/我們有 | floorplan/PDN：die 面積 + utilization 比對 |
| 16 | Clock planning | ⬜ 可做未做 | — | clock planning 對齊 |
| 17 | Placement (global + detailed) | ⬜ 可做未做 | 上游有/我們有 | placed DEF：placement density/legality 比對 |
| 18 | Spare-cell + ECO-prep insertion (Design-for-ECO) | ✅ DONE (BETTER-THAN-REF) | 我們有/上游無 | spare 覆蓋率 PASS(d=0.0232,分布+tie-off) + preservation removed:0；REF 0 spare/0 dont_touch |
| 19 | CTS (Clock Tree Synthesis) | ⬜ 可做未做 | 上游有/我們有 | CTS：clock-tree 深度/skew 比對 |
| 20 | 🔁 Post-CTS hold fixing | ✅ DONE | — | post-CTS hold-fix：hold slack 比對 |
| 21 | Routing (global + detailed) | ⬜ 可做未做 | 上游有/我們有 | routed DEF：route-clean + component/net 比對 |
| 22 | Parasitic Extraction (RC → SPEF) | ⚠️ 缺/兩邊都沒跑 | 上游有/我們無 | SPEF 寄生比對（RC budget） |
| 23 | 🔁 Post-route STA (multi-corner multi-mode sign | ✅ DONE | 上游有/我們有 | post-route 多角 STA slack 比對 SS/TT/FF |
| 24 | 🔁 IR Drop (static + dynamic) | ⚠️ 缺/兩邊都沒跑 | — | IR drop（static+dynamic）比對 |
| 25 | 🔁 EM check (electromigration lifetime) | ⚠️ 缺/兩邊都沒跑 | — | EM electromigration 比對 |
| 26 | 🔁 Antenna check (gate-oxide protection) | ⚠️ 缺/兩邊都沒跑 | — | antenna check 比對 |
| 27 | 🔁 Signal Integrity (Crosstalk / Noise / Glitch | ⚠️ 缺/兩邊都沒跑 | — | Signal Integrity / crosstalk 比對 |
| 28 | Post-Layout Gate-Level Simulation (Post-Sim +  | ⬜ 可做未做 | 上游有/我們有 | post-layout gate-sim + SDF vs golden |
| 29 | Post-Layout SPICE Verification (critical-path  | ⚠️ 缺/兩邊都沒跑 | — | post-layout SPICE 關鍵路徑相關性 |
| 30 | 🔁 Physical Verification (DRC + LVS + ERC + Den | ✅ DONE | 上游有/我們有 | PV：DRC clean 對齊 + LVS clean 對齊 |
| 31 | 🔁 ECO (Engineering Change Order — repair loop) | — N/A | — | ECO 修復迴圈（PV 失敗才需要） |
| 32 | Power analysis (pre/post-layout) | ⚠️ 缺/兩邊都沒跑 | — | power analysis 比對 |
| 33 | Metal Fill (density fill insertion) | ⚠️ 缺/兩邊都沒跑 | — | metal fill density 比對 |
| 34 | Tapeout checklist (final sign-off confirmation | ⚠️ 缺/兩邊都沒跑 | — | tapeout checklist 對齊 |
| 35 | GDSII output (only if PV fully clean) | ✅ DONE | 上游有/我們有 | GDSII：不同微架構→無法像素比；cross-check=兩邊各自 DRC/LVS-clean + 功能等價 |
| 37 | FPGA final sign-off (recompile + on-board test | — N/A | — | FPGA final sign-off（ASIC 流程） |
| A6 | Analog Physical Verification (per-block DRC +  | — N/A | — | 類比步驟（spm 純數位） |
| M1 | Mixed-Signal Top-Level Integration (A+D GDS me | — N/A | — | 混合訊號步驟（spm 純數位） |
| M2 | Mixed-Signal Power Domain + Level Shifter / Is | — N/A | — | 混合訊號步驟（spm 純數位） |
| M3 | Mixed-Signal Verification (AMS co-sim + RNM +  | — N/A | — | 混合訊號步驟（spm 純數位） |
| M4 | Mixed-Signal Sign-Off (top-level PV + final ve | — N/A | — | 混合訊號步驟（spm 純數位） |
| 36 | Foundry Handoff (mask spec + WAT plan + scribe | ⚠️ 缺/兩邊都沒跑 | — | foundry handoff（mask/WAT/scribe）對齊 |
| 38 | Fabrication (foundry mask-set + wafer fab — ex | — N/A | — | Fabrication（外部 foundry，無實體晶圓） |
| 39 | Wafer Sort / Probe Test (ATE + probe card) | — N/A | — | Wafer sort / probe（需 ATE） |
| 40 | Packaging (assembly: wirebond / FC-CSP / WLCSP | — N/A | — | Packaging |
| 41 | Final Test (ATE: functional + parametric + bur | — N/A | — | Final test（ATE） |
| P0 | Structural-RTL pre-flight (77 chip-AGNOSTIC st | ⬜ 可做未做 | — | 77 個結構RTL chip-agnostic checker（跑我們的、比 clean） |

## 統計
- ✅ 已完成 cross-check（端點）：7 步 — Step 1(RTL等價)、4(sim golden)、**18(Design-for-ECO, BETTER-THAN-REF)**、20(hold)、23(post-route STA)、30(DRC/LVS)、35(GDS端點)
- ⬜ 可做但尚未做：14 步（上游+我們大多都有產物，差跑比對腳本）
- ⚠️ 缺口（DFT/SPEF/IR/EM/antenna/SI/SPICE/fill 等，多數上游也沒跑）：15 步
- — N/A（類比 A*/M*、製造 38-41、FPGA：spm 純數位/無實體晶圓）：20 步
- 合計：56 步（原 55 步 + 新增 Step 18 Design-for-ECO）
