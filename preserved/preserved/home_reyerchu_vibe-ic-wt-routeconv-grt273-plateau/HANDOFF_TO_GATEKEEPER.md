# HANDOFF_TO_GATEKEEPER — 繞線收斂（clock-NDR 揭露 + plateau 停止 + 繞線前壅塞揭露）

## 座標
- **Worktree**：`/home/reyerchu/vibe-ic-wt-routeconv-grt273-plateau`（私有；路徑含任務代號 `routeconv-grt273-plateau`，非共用 `~/vibe-ic-repo`）
- **Branch**：`fix/route-converge-grt273-plateau`
- **Commits**（2 個，按序）：
  | sha | 內容 |
  |-----|------|
  | `f97d6a13` | CASE A 揭露 + GRT-0116 進 ladder + ladder 錨定 + plateau 判定/live abort |
  | `e01949bb` | **誠實性修正**：移除虛構的 plateau fixture、收斂 CASE B 宣稱範圍；新增 CASE B-2 繞線前壅塞揭露 |
- **Base**：`0d2c63d3`
- **未 push**（依指令，一律由 gatekeeper 落地）
- **版本**：**故意未指派**。請於 land 當下重新指派 monotonic 版本 —— rebase 會靜默吃掉預先寫入的版本 bump。本 branch 未觸碰任何 VERSION 檔或版本常數。

> ⚠️ **給 reviewer 的重點**：第二個 commit 推翻了第一個 commit 的一項核心宣稱。第一版聲稱 plateau 判定「對真實 edge_llm 軌跡正確觸發」，**這是錯的**，且它是靠一組虛構的 fixture 成立的。詳見下方「誠實性修正」。如果只看一段，看那段。

---

## 兩案的根因（分開判定：真正的繞線牆 vs 流程設定錯誤）

### (a) ibex × sky130A ＝ **流程設定錯誤**（不是繞線牆）
三個獨立的流程缺陷疊在一起，燒掉 8036 秒、無 GDS：

1. **GRT-0116 買不到任何救援（主因）**。`_route_feedback_loosen` 舊守衛要求 `route_completed`，但 GRT-0116 是在產生任何 DEF **之前**中止的——OpenROAD 發出最大聲的壅塞訊號，卻是唯一**完全跳過** loosen ladder 的訊號。
2. **ladder 錨錯 util**。ladder 頭階硬寫 `_AUTO_DIE_TARGET_UTIL`(0.25)，但 ibex 採 ORFS `CORE_UTILIZATION=50`→die 實際建在 **0.5**。第一步放寬被算成 0.25→0.18（1.18x），實際需要 0.5→0.25（**1.41x**），錯而無人可見。
3. **交易無人記帳**。時脈 NDR 被拿掉換壅塞，然後**還是失敗**——時脈品質白花，而 step 只吐一句裸 `rc=1 log_tail=<2000 字>`。

這三項都在流程內可修，**已修**。注意：這**不**等於宣稱 ibex 一定繞得通——只宣稱流程原本連試都沒試對。

### (b) edge_llm_matmul_accel ＝ **真正的繞線牆**（流程的罪是沉默，不是設定錯誤）
- **util 36.1%，但 weighted routing congestion 1.15–1.17**。全域使用率低、**局部**需求卻超過容量——來源是 FF 建模的 SRAM（行為級 `sram_sp` 合成成正反器陣列）＋256 個 `mac_pe` 的高接腳密度。**放大 die / 降 util 治不了局部接腳密度**，所以這不是 die 幾何設定錯誤。
- **我查證並排除了 PDK 錯配假說**：本機 `campaign_v1544/v1550` 的 edge_llm 目錄是 `*_nangate45`，一度看似「宣告 sky130A 卻跑 nangate45」。但實際那次 23.5h 的 run 記錄在 `benchmark-data/ic/edge_llm_matmul_accel/phase3/PHASE3_MILESTONE.md`，明載 `--pdk sky130A` / `sky130_fd_sc_hd`。**PDK 沒有錯配**；本機那兩個 nangate45 目錄是不同的 campaign。假說為**負**。
- **流程的真實缺陷**：那個壅塞讀數 **在 CTS 之前、在 23.5 小時之前就已經量到了**，而且 OpenROAD 自己講得很白：
  ```
  [INFO GPL-0047] Routability iteration weighted routing congestion: 1.1581
  [INFO GPL-0089] Routability finished. Reverting to minimal observed
                  routing congestion, could not reach target.
  ```
  流程一個字都沒說，直接走過 CTS 進細繞，花一天重新發現同一件事。milestone 文件自己稱之為 "the early congestion signal"。

---

## 動的檔案
| 檔案 | 性質 |
|------|------|
| `programs/_watchdog.py` | +91：第三種 kill `RC_ABORTED` + `supervise/run_supervised` 的 `abort_probe` 鉤子（opt-in） |
| `programs/phase3_one_shot_runner.py` | CASE A 揭露、GRT-0116 結構化 finding、ladder 錨定、plateau 判定 + live probe；**本次再加** CASE B-2 繞線前壅塞揭露 |
| `programs/tests/test_gap_e2e_die_util_routing_feedback.py` | 既有 retry-budget 不變量改以不等式表達（錨定後 ladder 可多一階） |
| `programs/tests/test_route_plateau_and_ndr_disclosure.py` | 50 測試（16 個 `test_negctl_*`）；**本次修正虛構 fixture** 並新增 B-2 測試 |

---

## ✅ 誠實性修正（本次；推翻第一版的宣稱）

**發現**：第一版的 CASE B 頭號負控測試 `test_negctl_plateau_predicate_fires_on_the_real_matmul_wall` 建立在一組**虛構軌跡**上：
```python
MATMUL_PLATEAU = [409554, 220310, 150221, 116677, 13421, 13208, 13150, 13102, 13094]
```
唯一的真實記錄（`PHASE3_MILESTONE.md`）寫的是
`409,554 → 332,073 → 312,639 → 129,304 → ~116,677`，然後 `plateauing ≈13 K/iter`。

把上面 9 個數字逐一拿去比對來源文件：**7 個在文件裡根本不存在**（220,310 / 150,221 / 13,421 / 13,208 / 13,150 / 13,102 / 13,094）。

**誤讀在哪**：文件的「≈13 K/iter」是**最後一輪的改善量**（129,304 − 116,677 = **12,627**），不是殘留違規數。第一版把它讀成「違規停在 13K」，於是編出一條平坦尾巴。

**後果（實測，非推論）**：
```
真實記錄軌跡 [409554,332073,312639,129304,116677]  → _drt_plateau_verdict = None（繼續繞）
虛構 fixture                                        → FIRES (rel_gain 0.0244)
```
也就是說——**第一版的 CASE B 修復，在真實證據上不會停下 CASE B**。它綠燈只因為 fixture 是照著它自己的判準編的。

**而且這無法用更聰明的判準補救**（我試過並否定了）。用「近 N 輪改善率外推剩餘輪數」對真實語料做分離度檢查：
| window | 真實**收斂**軌跡的最大投影 | 真實**牆**（edge_llm）的投影 |
|--------|--------------------------|---------------------------|
| 1 | 20.53 | 4.29 – 16.09 |
| 2 | 5.12 | 1.19 – 6.45 |
| 3 | 0.55 | 1.38 – 1.63 |

**大幅重疊**。在 iter 4 那個時點，edge_llm 每輪仍砍掉約 11% 的違規，數學上與一條正常收斂的路線**無法區分**。沒有任何誠實的判準能對它開火而不屠殺真實收斂路線。

**處置**：
1. `MATMUL_RECORDED` = 真實記錄的 5 個樣本；`SYNTHETIC_FLAT_TAIL` = 明確標示為**手寫、非任何 log** 的平坦尾巴，只用來單元測試判準本身。
2. 新增 `test_recorded_matmul_prefix_is_not_yet_a_plateau`：對真實軌跡的**每一個前綴**斷言判定為 `None`——把「我們不宣稱它會在 iter 4 停下 edge_llm」寫成可執行的界線。
3. 新增 **provenance guard** `test_matmul_recorded_matches_the_milestone_record`：plateau fixture 的每個數字必須能在 checked-in 的 milestone 文件裡逐字找到。**這就是原本會抓到造假的那道閘**（實測：舊 fixture 9 個數字有 7 個過不了）。
4. 模組 docstring 改寫，明說 B-1 的**宣稱範圍**：它涵蓋的是**平坦尾巴**；23.5h 的尾段從未被記錄下來，因此無法宣稱它會在何時觸發。

**B-1（plateau 停止）保留**——機制本身是對的、負控是真的、對 10 條真實收斂軌跡的每個前綴都不誤觸。只是宣稱縮回證據能撐的範圍。

---

## 新增：CASE B-2 — 繞線前壅塞揭露（這才是對 (b) 能被證據支撐的改善）
既然沒有誠實的判準能在 iter 4 停下 edge_llm，那能真正省下那 23.5 小時的，是**把流程早就握有的訊號講出來**。

- `_gpl_congestion_trajectory` / `_gpl_routability_gave_up` / `_placement_congestion_disclosure` / `_placement_congestion_detail`（純函式、只認 OpenROAD GPL log 文法、無 PDK 無設計字面）。
- 在**每一個** pnr 結局（含 PASS）附加到 verdict detail 與 `extras`，並持久化到 `reports/route_congestion_trades.json`（schema 升 `/2`，`placement_congestion` 兩個方向都正面陳述，檔案不存在不必解讀）。
- **`_place_detail` 與 `_ndr_detail` 刻意分開兩個變數**：GRT-0116 分支用「`_ndr_detail` 非空」當旗標接上「而且還不夠：規則讓了、路還是沒繞通」。若把兩者相加，一個**沒掉任何 NDR** 的 run 會被流程宣稱掉了 NDR。已加 `test_placement_detail_never_claims_a_clock_ndr_trade` 守住。
- **§4.05：只揭露、不改 verdict TIER**。唯一的門檻 1.0 是 **demand/capacity 的物理 unity 點**，不是為了讓語料分開而擬合的數字——而且語料**本來就不分開**（見下表 aes）。已加 `test_placement_over_capacity_threshold_is_physical_unity` 釘住。

---

## Gate 結果（全部本機、8HD-9）

### 負控（硬性要求：修復前 FAIL、修復後 PASS）
| 基線 | 結果 |
|------|------|
| **對 main `0d2c63d3`**（整包） | **16 個 `test_negctl_*` 全 FAIL**（48 failed / 2 passed） |
| **對 `f97d6a13`**（只驗本次 B-2 新增） | **8 個 B-2 測試全 FAIL** |
| 修復後 | 該檔 **50 passed** |

### 無下游回歸
- route/watchdog/die-util/phase3/pnr/reference-flow + chip-agnostic & leak 守衛（23 個檔）：**416 passed, 1 skipped**
- 完整套件（`./run_tests.sh`，programs/tests + 60 個 skill tests）：**18,579 passed, 508 skipped, 2 xfailed, 11 failed**（38m54s）
  - 那 **11 個 failed 全是既有問題，已證明**：在**未動過的 `0d2c63d3` 獨立 worktree** 重跑同樣 6 個檔案 → **同樣 11 個、同樣名稱**失敗（`11 failed, 85 passed`）。全屬 yosys / LEC / formal / cvdp 等外部 EDA 工具相依測試，與 phase3 繞線路徑無交集。基線 worktree 驗證後已移除。
- 新程式碼的 chip-AGNOSTIC 檢查：可執行碼中**無**任何設計字面（`ibex`/`edge_llm`/`sky130`/`nangate`…只出現在註解的出處說明）

### 真實 cell 驗證（未截斷的生產 campaign log，8HD-9 本機）
用 runner 自己的 parser 直接讀**全檔**真實 log（10 條互異軌跡）：

| 真實 run | 繞線結果 | 繞線前揭露 |
|----------|---------|-----------|
| sha256 ×5（v1520/1544/1566/1528/sn2025） | CONVERGED | **靜默**（達標且 <1.0，不製造雜訊） |
| sha256 (ssval) | CONVERGED | final 1.0066，over_cap |
| **ibex** v1560 | **GRT-0116 FAIL** | final **1.3255**，over_cap，**gave_up** |
| ibex v1550 | 無乾淨繞線 | final 1.3445，over_cap，gave_up |
| **opentitan_aes** v1560 | **CONVERGED** | final **1.0805**，over_cap，**gave_up** ← **仍須 PASS** |

- ibex 的 NDR 揭露：`nets=[clknet_0_clk_regs, clk_regs]`，CTS 時脈網 1 條 ＝ 任務描述的症狀，現已結構化。
- opentitan_aes ＝ 先前完全無人知曉的**靜默綠燈**案：掉了 2 條時脈網的 NDR、置放階段超過容量且放棄達標，然後**繞通了**。它同時是「揭露不得當預測器」的活證據。
- **CASE B 的證據界線**：edge_llm 那次 23.5h run 的 log 不在本機（`192.168.1.114:~/campaign_v1574` 從 8HD-9 無 SSH 金鑰，`Permission denied`）。可得的唯一記錄是 checked-in 的 `PHASE3_MILESTONE.md`。B-2 的判定邏輯已在**上述真實 sky130A log** 上驗證；edge_llm 本身的 1.15–1.17 是**引用該文件**，非我方計算。

---

## 誠實性附註（遵守任務約束）
- **未改任何 RTL** → synth netlist 重用洞（只檢查 PDK、不檢查 RTL）與本修復無關，無需證明重新合成。
- **未動任何 synth 旋鈕** → loosen 改的是 die 幾何，且以**繞線後**軌跡判定，非 pre-PnR 面積換延遲。
- **「改善」的宣稱都用 acceptance gate 實讀的下游報告驗證**：`StepResult.detail` / `extras` + `reports/route_congestion_trades.json`，非修復自算的數字。本次最大的一項工作，正是**撤掉**一個用自算數字驗證自己的宣稱。
- plateau abort 的誠實界線：只證明 router「被停的當下正在原地打轉」，**不**宣稱設計不可繞；半成品 DEF 被隔離不出貨，省下的 CPU 以「省下」而非「收斂改善」回報。
- 繞線前揭露的誠實界線：明說「routes have converged from here and have also failed from here」，且 detail 文字不含任何 verdict 字眼（有測試釘住）。

## 建議 gatekeeper 落地時
1. 指派 monotonic 版本（本 branch 刻意 version-less）。
2. rebase onto 現行 `origin/main` 後**重跑** required checks（語意衝突偵測）。
3. 兩個 commit 可squash；若 squash，請保留 commit message 中「虛構 fixture 已移除 + provenance guard」的敘述——那是這次最該被記住的一條。
