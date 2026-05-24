# Vibe-IC 34 步驟流程 — Input/Output + 驗證方法 + 說服 IC 專家

> **來源**：`vibe-ic-marketplace/plugins/vibe-ic-core/flow/phase2_phase3.yaml`（832 行 canonical 定義）+ `flow_compliance_check.py` 強制執行器
>
> **適用版本**：v0.119.1（752 deterministic tests，77 structural-RTL gates，209 programs，46 MCP tools）

---

## 1. 完整 34 步驟 I/O 對照表

> **慣例**：「Input」= 上游 step 產出 + 該 step 必須讀的 spec 檔；「Output」= `required_outputs` YAML 欄位 + gate 產出的 `reports/gates/*.json`

### Stage 1 — RTL 生成 + 驗證（Step 1-6）

| #  | 步驟                                                         | Input                                            | Output                                                                                                                                                                                                                       |
| -- | ------------------------------------------------------------ | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1  | **Spec-to-RTL**                                              | L1-L9 JSON（`generated_docs/L*.json`）+ `input/docs/*` | `rtl/*.sv`、`rtl/*.v`                                                                                                                                                                                                        |
| 2  | **Lint**（hygiene + Quartus-unsafe + bug-claim schema + 8 generic 任 IC lint） | rtl/ + L3/L8/L11 specs                          | `reports/lint/{rtl_hygiene,rom_init}.json` + `reports/gates/{int_vs_ext_timing,threshold_contiguity,rsp_otp,spec_response_delay,nba_addr_race,periodic_timer,memory_read_pipeline,fpga_input_polluter}.json` |
| 3  | **CDC / RDC**                                                | rtl/ + clock spec                                | `reports/cdc/*.json`、`reports/rdc/*.json`                                                                                                                                                                                    |
| 4  | **Simulation**（testbench + L10/L12 coverage + Verilator）    | rtl/ + tb/ + L10 test cases                      | `reports/sim/*.json`、coverage report、waveform                                                                                                                                                                               |
| 5  | **Formal**（assertions proved + bit-level full-stack tb）    | rtl/ + SVA assertions                            | `reports/formal/*.json`、proof trace                                                                                                                                                                                          |
| 6  | **FPGA early prototype + verification report audit**         | rtl/ + `*.qsf` + cocotb tb                       | `out.sof`、`reports/fpga/*.json`、`reports/verification_audit.json`                                                                                                                                                            |

### Stage 2 — Synthesis + DFT（Step 7-13）

| #  | 步驟                                              | Input                       | Output                                              |
| -- | ------------------------------------------------- | --------------------------- | --------------------------------------------------- |
| 7  | **Constraint setup（SDC + PVT matrix）**          | rtl/ + L8 timing            | `constraints/*.sdc`、`pvt_matrix.yaml`              |
| 8  | **SDC validation**                                | SDC + netlist               | `reports/sta/sdc_check.json`                        |
| 9  | **Synthesis (Yosys → mapped netlist)**            | rtl/ + `.lib` + SDC         | `synth/netlist.v`                                   |
| 10 | **Pre-layout STA (multi-corner SS/TT/FF)**        | netlist + SDC + lib         | `reports/sta/{ss,tt,ff}.json`                       |
| 11 | **DFT insertion (scan chain + ATPG)**             | mapped netlist              | `dft/scan_netlist.v`、`atpg/patterns.stil`          |
| 12 | **Post-DFT optimization**                         | scan_netlist                | `dft/post_dft_netlist.v`                            |
| 13 | **Equivalence check (RTL ≡ post-DFT)**            | rtl/ + post_dft_netlist     | `reports/equiv/*.json`                              |

### Stage Analog —（A1-A8，並行 Stage 1-2）

| #  | 步驟                                  | Input                                    | Output                                          |
| -- | ------------------------------------- | ---------------------------------------- | ----------------------------------------------- |
| A1 | **Analog Spec Extraction**            | L5 ADI spec + `analog/analog_block_list.json` | `analog/spec_extracted.json`                    |
| A2 | **Topology Selection**                | A1 spec                                  | `analog/topology.json`                          |
| A3 | **Netlist Generation**                | A2 topology + PDK                        | `analog/netlist.spice`                          |
| A4 | **Corner Sweep (PVT)**                | netlist + corners                        | `analog/pvt_sweep.json`                         |
| A5 | **Layout (Magic / KLayout)**          | A3 netlist + tech file                   | `analog/layout.gds`                             |
| A6 | **Post-Layout Resimulation**          | layout + extracted spice                 | `analog/postlayout_sim.json`                    |
| A7 | **Hardmacro Generation**              | layout + lib                             | `analog/macro/{*.lef, *.lib, *.gds, *.v}`       |
| A8 | **Co-Simulation / HW Verification**   | A7 macro + FPGA stimulus + scope         | `analog/cosim_compare.json`、scope captures     |

> A7 LEF 直接匯入 Step 14 floorplan，做混合訊號整合。

### Stage 3 — Physical Design + Sign-off（Step 14-29）

| #  | 步驟                                         | Input                                  | Output                                          |
| -- | -------------------------------------------- | -------------------------------------- | ----------------------------------------------- |
| 14 | **Floorplan + PDN**                          | netlist + LEF（含 A7 hardmacro）        | `pnr/floorplan.def`                             |
| 15 | **Clock planning**                           | floorplan + SDC                        | `pnr/clock_def.def`                             |
| 16 | **Placement (global + detailed)**            | clock_def                              | `pnr/placed.def`                                |
| 17 | **CTS**                                      | placed.def                             | `pnr/cts.def`、clock tree report                |
| 18 | **Post-CTS hold fixing**                     | cts.def + STA                          | `pnr/post_cts.def`                              |
| 19 | **Routing (global + detailed)**              | post_cts                               | `pnr/routed.def`                                |
| 20 | **Parasitic Extraction (RC → SPEF)**         | routed.def + tech                      | `pnr/extract.spef`                              |
| 21 | **Post-route STA (MMMC sign-off)**           | netlist + SPEF + SDC × corners         | `reports/sta/signoff_*.json`                    |
| 22 | **IR Drop (static + dynamic)**               | routed + power vector                  | `reports/ir_drop.json`                          |
| 23 | **EM check (electromigration)**              | routed + current density               | `reports/em.json`                               |
| 24 | **Antenna check**                            | routed                                 | `reports/antenna.json`                          |
| 25 | **Signal Integrity (XT/Noise/Glitch)**       | SPEF + STA                             | `reports/si.json`                               |
| 26 | **Post-Layout GLS (SDF)**                    | post-route netlist + SDF + tb          | `reports/post_sim.json`                         |
| 27 | **Post-Layout SPICE Verification**           | critical paths + spice + analog        | `reports/spice_correlation.json`                |
| 28 | **Physical Verification (DRC + LVS + ERC + Density)** | layout + tech                  | `reports/{drc,lvs,erc,density}.json`            |
| 29 | **ECO loop**                                 | DRC/STA failures                       | `pnr/eco/*.def`、`reports/eco_summary.json`     |

### Stage 4 — Output + Validation（Step 30-34）

| #  | 步驟                                           | Input                       | Output                                                       |
| -- | ---------------------------------------------- | --------------------------- | ------------------------------------------------------------ |
| 30 | **Power analysis (pre/post-layout)**           | netlist + activity vectors  | `reports/power.json`                                         |
| 31 | **Metal Fill (density fill)**                  | routed.def                  | `pnr/filled.def`                                             |
| 32 | **Tapeout checklist**                          | 所有上游 reports             | `reports/tapeout_checklist.json`（4/4 sign-off 項目）        |
| 33 | **GDSII output**（gated by Step 28 完全 clean） | filled.def + tech           | `chip.gds`                                                   |
| 34 | **FPGA final sign-off (recompile + on-board test)** | rtl + .qsf + bench       | `final.sof`、`reports/onboard/*.json`、scope/camera 證據     |

---

## 2. PASS 之後，我們怎麼驗證？— 6 層證據鏈

`flow_compliance_check.py --strict` 跑出 `Overall: PASS` **只是必要條件**。實際 tapeout 前的驗證金字塔（由內到外）：

| 層     | 驗證方式                                                                                                                | 工具 / 證據                                                                                                                       |
| ------ | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **L1 — 自我審計** | 跑 `flow_compliance_check.py --strict`，每 step 必須 PASS（不能是 WAIVED）                                        | 752/752 deterministic test，77 structural-RTL gates                                                                              |
| **L2 — Oracle 字節對比** | 把 known-good `.sof`（前一版） burn 進 FPGA，host-tester 抓所有 byte stream → 與新版逐 byte 比對          | `mcp__eda-tools__eda_oracle_bytewise_dump`                                                                                      |
| **L3 — Hardware-in-the-loop** | DE10-Lite + EXAMPLE_TESTER host-tester + 示波器 + 相機抓 LED → camera_capture diff 對照 reference        | `device_camera_led_diff`、`device_scope_capture`、`eda_pass_reference_scope_diff`                                               |
| **L4 — Fresh-agent reproducibility** | 砍掉所有 oracle / memory / 過往 conversation，把同一份 L1-L9 spec 餵給乾淨的 Claude session，產出的 RTL 必須 byte-identical（或 functionally identical） | `tools/benchmark/run_benchmark.sh`，第 1 個 benchmark = benchmark_a |
| **L5 — False-alert 回歸** | 把 v0.119.1 全部 77 gates 跑過 v099 known-good baseline → **零** finding                                      | `pytest -q` + `flow_compliance_check.py 1st_benchmark_benchmark_a/phase2+3_v099 --strict`                                            |
| **L6 — Foundry sign-off** | DRC/LVS/PERC 在真實 PDK 上 clean、density 達標、antenna OK、tapeout_checklist 4/4                            | `eda_drc_klayout`、`eda_lvs`、Step 28 + Step 32                                                                                |

**重點**：`PASS` 不能取代 silicon。silicon 之前的最高保證是 **L1+L2+L3+L4 同時通過**（這是 vibe-ic 的「engineering tapeout-ready」門檻）。

---

## 3. 怎麼讓 IC 專家相信我們？— 5 個說服元素

IC 專家不會看 `Overall: PASS` 就點頭——他們要看**證據包**。準備這 5 樣：

### (1) 完整 Evidence Pack（壓縮成單一 zip 給 reviewer）

```
project/
├── reports/                  ← 所有 step 的 JSON output（machine-readable）
│   ├── lint/                 ← hygiene + 8 generic any-IC lints
│   ├── gates/                ← 77 structural-RTL gates 的 verdict
│   ├── sta/{ss,tt,ff}.json   ← 3-corner timing
│   ├── {drc,lvs,erc}.json    ← PV signoff
│   └── tapeout_checklist.json
├── pnr/{floorplan,routed,filled}.def
├── chip.gds                  ← 最終產出
├── waveforms/                ← Step 4/26 sim
├── scope_captures/           ← Step 34 真機
└── flow_compliance_audit.txt ← Overall: PASS + per-step verdict
```

### (2) Bug-class Catalogue（讓專家看「我們攔到什麼」）

- **v0118-noris case study**：`FRAME_END_GAP=4000 ticks` 半雙工 latency window 超標 → LL-4 gate 抓到
- **v0.116 benchmark_a case study**：fresh-agent oracle 缺失 → spec-to-rtl 多攔 7 條規則
- 每條規則都附：bug origin commit + 修補 gate + 對應 test 檔

### (3) Gate-coverage Matrix

77 structural-RTL gates × 已知 bug class 的 mapping 表。展示「不是隨便寫 gate 騙覆蓋率」，而是每條 gate 對應一個歷史 bug。可從 `BACKLOG-v6/v7/v10/v11.md` 抽出。

### (4) Fresh-agent Reproducibility Demo

**這是殺手級展示**。在專家面前：

1. 砍掉一個 worktree 的 memory
2. 開新 Claude session 只讀 `1st_benchmark_benchmark_a/phase1_v049_*/human_docs/`
3. 跑 `/spec-to-rtl` → `/flow_compliance_check --strict`
4. 對照 v099 reference SOF → bytewise PASS

→ 證明「不是 prompt-engineered 一次性結果，而是 deterministic pipeline」

### (5) Open-source 全部 deterministic gates

專家可以自己 audit `vibe-ic-marketplace/plugins/vibe-ic-d/programs/*.py`（209 個程式 + 692 tests）。這比任何 marketing slide 都有說服力——「我們敢公開全部規則」。

> 配套指令：`mcp_server_health_check`（liveness probe）+ `eda_phase23_completion_audit`（同樣的 self-audit 但給外部 reviewer 跑）。

---

## 附錄 — 唯一 Acceptance Criterion（再次強調）

任何 agent 宣稱「Phase 2+3 完成」之前，**必須**自行執行：

```bash
python3 vibe-ic-marketplace/plugins/vibe-ic-d/programs/flow_compliance_check.py <project_dir> --strict
```

輸出必須是下列三種 verdict 之一：

- **`Overall: PASS`** — 每個 canonical step 都實際執行並驗證通過。production tapeout-ready。
- **`Overall: PASS_WITH_WAIVERS`** — 結構性完成，但有 N 個 step 用 `waivers.json` deferred（**NOT** pass）。可宣稱「engineering Phase 2+3 complete」但**不可說「all 34 steps PASS」**——必須說「executed PASS = X/(34-N)，deferred = N pending foundry sign-off」。每個 waiver 必須附 evidence + ticket id + `review_required: true`，foundry tapeout 時人類必須在商業 deck 上跑通才放行。
- **`Overall: FAIL`** — 不完成，繼續做。

**個別 gate PASS（如 tapeout_signoff_check 4/4 / BACKLOG-v6 P0 9/9 / BACKLOG-v7 P0 5/5）NOT 等於 Phase 2+3 完成**——它們是必要而非充分條件。任何 agent 跳過這個 self-audit 就 claim PASS 屬於 process violation。waiver ≠ PASS：waiver 是 **DEFERRED open work**，不可在敘述中混為「都過了」。
