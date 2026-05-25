# AI Native IC Design Plugin — 依 Design Flow 順序整理

本文件將 `ai-native-ic-design` plugin 內的 12 個 skills，按照典型的 IC 設計流程（Spec → RTL → Verification → Synthesis/PPA → Analog → Physical Design → Signoff → Post-Silicon）排序整理，方便對照各階段可呼叫的工具。

所有 skill 描述內容均取自本機 plugin 安裝路徑 `/sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/`，未自行增補或臆測。

---

## 階段 0｜流程總覽與編排 (Flow Orchestration)

跨越整個 RTL-to-GDSII 流程的總指揮，適合在進入任何單一階段前先規劃。

1. **flow-orchestrate** — 編排完整 RTL-to-GDSII 流程，跨多個 EDA 工具（synthesis、floorplan、placement、CTS、routing、signoff）。使用時機：「run the flow」「set up a build」「orchestrate synth + P&R」「agentic flow」或需要跨工具邊界的端到端自動化。
   - [flow-orchestrate/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/flow-orchestrate/SKILL.md)

---

## 階段 1｜Spec → RTL（規格到設計）

從自然語言規格產生可綜合 (synthesizable) 的 HDL。

2. **spec-to-rtl** — 將自然語言硬體規格翻譯為 Verilog / SystemVerilog / VHDL。使用時機：「generate RTL for...」「write Verilog that...」「turn this spec into hardware」，或提供 functional description、I/O 定義、protocol spec 時。
   - [spec-to-rtl/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/spec-to-rtl/SKILL.md)

---

## 階段 2｜RTL Review & Repair（RTL 品質與修復）

RTL 撰寫完成後的 lint、coding-style、synthesis hazard 檢查與自動修復。

3. **rtl-review** — 稽核 RTL，檢查 lint violations、synthesis hazards、coding-style 合規性與可讀性。使用時機：「review this Verilog」「check my RTL」「lint this module」「is this code synthesizable」。
   - [rtl-review/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/rtl-review/SKILL.md)

4. **rtl-repair** — 自動修復 RTL 中的 lint violations、synthesis errors、simulation mismatches。使用時機：「fix this Verilog」「repair the RTL」「resolve these lint errors」「my synthesis is failing」，或提供工具的錯誤 log 時。
   - [rtl-repair/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/rtl-repair/SKILL.md)

---

## 階段 3｜Verification（驗證）

包含動態模擬的 testbench 與靜態形式驗證的 assertion 生成。

5. **testbench-gen** — 為 RTL 模組產生 SystemVerilog 或 UVM testbench，包含 stimulus、checkers 與 coverage。使用時機：「write a testbench」「verify this module」「create a UVM env」「generate stimulus for」。
   - [testbench-gen/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/testbench-gen/SKILL.md)

6. **assertion-gen** — 從規格或 RTL 產生 SystemVerilog Assertions (SVA)。使用時機：「write assertions for this」「generate SVA」「add formal properties」「create checkers」，或需要 formal verification 的 safety / liveness properties。
   - [assertion-gen/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/assertion-gen/SKILL.md)

---

## 階段 4｜Pre-Synthesis PPA 預估

在花時間跑完整 synthesis 前的早期 sanity check。

7. **ppa-predict** — 在實際跑 synthesis 前預測 RTL 模組的 Power、Performance、Area。使用時機：「estimate PPA」「how big will this be」「what's the area of this module」「will this meet timing」。
   - [ppa-predict/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/ppa-predict/SKILL.md)

---

## 階段 5｜Analog Design（類比設計支線）

數位 flow 之外的類比電路 sizing 支援。

8. **analog-sizing** — 為類比電路拓樸調整電晶體尺寸，以滿足 gain、bandwidth、noise、power 等規格。使用時機：「size this amplifier」「analog sizing」「op-amp design」「bias point」「find W/L」，或使用者提供 schematic 與 spec table 時。
   - [analog-sizing/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/analog-sizing/SKILL.md)

---

## 階段 6｜Physical Design（實體設計）

Floorplan、placement、congestion 與 timing 優化。

9. **placement-optimize** — 建議 macro 與 standard-cell placement 改善方案，降低 wirelength、congestion 與 timing violations。使用時機：「optimize placement」「fix congestion」「macro placement」「floorplan help」，或提供 P&R 的 congestion / timing report 時。
   - [placement-optimize/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/placement-optimize/SKILL.md)

---

## 階段 7｜Signoff / DRC（簽核）

Layout 完成後的 Design Rule Check 修復。

10. **drc-fix** — 診斷並修復 layout / GDS 的 DRC violations。使用時機：「fix DRC」「DRC clean」「resolve spacing errors」「my layout fails DRC」，或提供 Calibre、Klayout、Magic 的 DRC report 時。
    - [drc-fix/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/drc-fix/SKILL.md)

---

## 階段 8｜Late-Stage ECO（晚期工程變更）

P&R 已完成後才發現的 bug，需要最小擾動地修補。

11. **eco-plan** — 規劃 Engineering Change Order (ECO)：對已完成 place-and-route 的 netlist 做晚期變更而最小化擾動。使用時機：「need an ECO」「late-stage fix」「spin without re-place-and-route」「metal-only fix」，或 P&R 後才發現 bug。
    - [eco-plan/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/eco-plan/SKILL.md)

---

## 階段 9｜Post-Silicon（量產後分析）

晶片回片後的測試資料分析與良率診斷。

12. **yield-diagnostic** — 分析矽測試 / wafer 資料以診斷 yield 問題、辨識系統性失效、並提出 layout 或製程修正建議。使用時機：「yield is low」「diagnose failing dies」「wafer map shows」「bin analysis」，或提供 ATE / wafer-sort 資料時。
    - [yield-diagnostic/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/yield-diagnostic/SKILL.md)

---

## Flow 對照總表

| 階段 | Skill | 輸入 | 輸出 |
|---|---|---|---|
| 0. Orchestration | flow-orchestrate | 設計 repo + 需求 | 跨工具 build pipeline |
| 1. Spec → RTL | spec-to-rtl | 自然語言 spec | Verilog / SV / VHDL |
| 2a. RTL Review | rtl-review | HDL 檔案 | Lint / style 報告 |
| 2b. RTL Repair | rtl-repair | HDL + error log | 修復後 HDL |
| 3a. Testbench | testbench-gen | RTL 模組 | SV / UVM testbench |
| 3b. Assertions | assertion-gen | Spec / RTL | SVA properties |
| 4. PPA Predict | ppa-predict | RTL | 早期 PPA 估算 |
| 5. Analog | analog-sizing | Schematic + specs | W/L、bias point |
| 6. Placement | placement-optimize | P&R report | Floorplan / placement 建議 |
| 7. DRC Signoff | drc-fix | Layout / GDS + DRC report | DRC clean layout |
| 8. ECO | eco-plan | Post-P&R netlist + bug | 最小擾動 ECO 方案 |
| 9. Yield | yield-diagnostic | ATE / wafer 資料 | 失效分析與修正建議 |

---

## 資料來源 (References)

本文件所列 12 個 skill 名稱、描述、觸發時機，均取自以下本機 plugin 路徑實際存在的 SKILL.md 檔案（已於 2026-04-05 經 `ls` 驗證路徑正確），未自行新增或推論：

- [flow-orchestrate/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/flow-orchestrate/SKILL.md)
- [spec-to-rtl/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/spec-to-rtl/SKILL.md)
- [rtl-review/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/rtl-review/SKILL.md)
- [rtl-repair/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/rtl-repair/SKILL.md)
- [testbench-gen/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/testbench-gen/SKILL.md)
- [assertion-gen/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/assertion-gen/SKILL.md)
- [ppa-predict/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/ppa-predict/SKILL.md)
- [analog-sizing/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/analog-sizing/SKILL.md)
- [placement-optimize/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/placement-optimize/SKILL.md)
- [drc-fix/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/drc-fix/SKILL.md)
- [eco-plan/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/eco-plan/SKILL.md)
- [yield-diagnostic/SKILL.md](computer:///sessions/relaxed-optimistic-clarke/mnt/.remote-plugins/plugin_01MoxH9NkPFg5h2xiSb7SnEF/skills/yield-diagnostic/SKILL.md)
