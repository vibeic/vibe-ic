# Phase 1: AI 對話設計 — 使用者體驗

**核心原則**：使用者是產品設計師，不是晶片工程師。
**目標**：用日常語言引導使用者做出設計決策，AI 負責翻譯成技術規格。
**關鍵機制**：每個技術決策都可追溯到使用者的哪句話，專家可單獨修改任何一個決策。
**架構**：雙 Agent 流程 — PM Agent（對使用者）→ IC Expert Agent（技術審查）。

---

## 設計原則

1. **零術語** — 不說 CRC、OTP、CC、trim、FSM、CDC、MOS
2. **講取捨** — 每個選擇都有代價，讓使用者根據「自己的產品」決定
3. **不追求完美** — 幫使用者選「夠用」的方案，不是「最好」的方案
4. **情境導向** — 「你的產品是充電線？還是智慧感測器？」不同產品不同建議
5. **AI 做翻譯** — 使用者說「我要省電」，AI 自動決定用多時脈域架構

---

## 完整對話流程示範

### 開場：理解產品

```
AI: 嗨！我是 Vibe-IC，我可以幫你從零開始設計一顆晶片。
    先聊聊你的產品吧 — 你想做什麼東西？

User: 我想做一條 Lightning 充電線，裡面需要一顆認證晶片。

AI: 了解！充電線認證晶片，我幫你整理一下需要確認的幾件事。
    大概會問你 6-7 個問題，每個問題我會說明取捨，你來選就好。
    準備好了嗎？
```

### 第 1 題：相容性（→ 背後決定 L3 CRC init, protocol version）

```
AI: 第一個問題：你的充電線需要跟哪些裝置相容？

    A) 只要能充電就好（成本最低，但有些裝置可能不認）
    B) 要跟市面上大部分充電器相容（建議選這個，多數客戶的選擇）
    C) 要跟原廠設備完全相容（成本最高，但保證不會有相容問題）

User: B，跟大部分充電器相容。

AI: 好的。我會採用業界標準的通訊格式，確保你的線能被大部分充電器認出來。
```

> **AI 內部動作**：選 B → CRC init=0xFF（Apple 標準）、AID 1.0 protocol、13 commands full set

### 第 2 題：功能範圍（→ 背後決定 L3 command set, L4 memory size）

```
AI: 第二個問題：你的充電線需要哪些功能？

    A) 基本款：充電 + 裝置識別
       （最簡單，晶片面積最小，成本最低）
    
    B) 標準款：充電 + 識別 + 序號追蹤
       （可以追蹤每條線的生產資訊，售後服務比較方便）
    
    C) 進階款：充電 + 識別 + 序號 + 工廠診斷 + 防偽
       （完整功能，適合品牌廠商，成本較高）

User: B 吧，我們需要追蹤序號。

AI: 好的。標準款包含裝置識別和序號追蹤功能。
    晶片裡會保留一塊永久記憶區來存放這些資訊，
    出廠時寫入一次就不能改了，這樣可以防止被竄改。
```

> **AI 內部動作**：選 B → 8 core commands (0x70-0xE2) + ID/IMSN/ASN in OTP, 64B OTP, skip extended commands (0xE4-0xEC)

### 第 3 題：省電需求（→ 背後決定 L2 clock architecture, L6 disconnect behavior）

```
AI: 第三個問題：省電對你的產品重要嗎？

    A) 不太重要，反正是接電源的（晶片設計比較簡單）
    B) 有點重要，希望待機時不要太耗電（多數充電線的選擇）
    C) 非常重要，我的產品是電池供電的（需要更複雜的省電設計）

User: B，接電源但希望待機時省電。

AI: 了解。我會讓晶片在沒有通訊的時候自動進入省電模式，
    只在需要回應的時候才全速運作。
    大概可以降低 60% 的待機耗電。
```

> **AI 內部動作**：選 B → 多時脈域（5M/2.5M/625K/312.5K）、disconnect 後關閉 oscillator、protocol 用 2.5MHz

### 第 4 題：充電控制（→ 背後決定 L6 CC control, L5 pad control）

```
AI: 第四個問題：你的線需要控制充電流程嗎？

    A) 不需要，只是傳輸資料用的（沒有充電功能）
    B) 基本充電控制（晶片幫忙管理充電器跟手機之間的握手）
    C) 進階充電控制 + 過電壓保護（適合快充線，安全性更高）

User: B，基本充電控制就好。

AI: 好的。晶片會在裝置插入時自動建立充電通道，
    拔出時自動斷開，中間有個 0.7 秒的緩衝期避免誤判。
    
    不過要注意：如果未來想升級成快充線，
    可能需要重新設計這部分。現在先做基本款 OK 嗎？

User: OK，先基本款。
```

> **AI 內部動作**：選 B → CC_EN control（74 cmd 後開啟）、700ms timeout、RD_ENB 控制、無 OVP/OCP

### 第 5 題：出廠資料（→ 背後決定 L4 OTP memory map, L4 lock mechanism）

```
AI: 第五個問題：出廠時需要寫入哪些資料？

    A) 只寫一個裝置編號（6 個字元，最簡單）
    B) 裝置編號 + 產品序號（26 個字元，可追蹤每條線）
    C) 裝置編號 + 產品序號 + 配件序號 + 工廠代碼
       （46+ 個字元，完整生產履歷）

    寫入後都不能修改，這是為了防偽設計。

User: B，要有產品序號。

AI: 好。寫入空間我會預留稍微大一點（64 個字元），
    這樣萬一未來需要多存一些資訊也不用重新設計晶片。
    多預留的成本差異很小，大概每顆多 0.1 美分。

User: 可以。
```

> **AI 內部動作**：選 B+buffer → 64B OTP（ID 6B + IMSN 20B + ASN 20B + lock 1B + reserved 17B）、3-region lock

### 第 6 題：量產校準（→ 背後決定 L4 trim registers, L7 engineer mode）

```
AI: 第六個問題：你的晶片需要出廠時個別校準嗎？

    這個選擇的取捨比較明顯：
    
    A) 不需要校準
       ✅ 工廠流程簡單，每顆測試時間短，成本低
       ❌ 晶片之間會有一些個體差異（大約 ±10%）
       → 適合：對精度要求不高的產品（充電線、簡單配件）
    
    B) 需要個別校準
       ✅ 每顆晶片都被調校過，個體差異 <±1%
       ❌ 工廠需要多一道校準步驟，每顆多花 0.5-1 秒
       → 適合：對精度要求高的產品（感測器、量測設備）

User: A，我是做充電線的，不需要那麼精確。

AI: 了解。不加校準功能，晶片設計會簡單一些，
    也能降低你的工廠測試成本。
```

> **AI 內部動作**：選 A → 不加 BG_TRIM/OSC_TRIM/IBIAS trim registers、不加 Engineer Mode (0x7C/0x7E)、簡化 OTP register space

### 第 7 題：量產測試（→ 背後決定 L7 test mode, L7 DFT）

```
AI: 最後一個問題：量產時怎麼測試晶片？

    A) 基本功能測試就好
       （測完大概需要 0.5 秒/顆，測試機台成本較低）
    
    B) 完整電性測試
       （測完大概需要 2 秒/顆，但能確保每顆品質一致）
    
    通常第一次量產建議選 B，等良率穩定後可以切換到 A 來降低成本。

User: B，我們第一次做，品質先顧好。

AI: 好建議！我會在晶片裡加入一個特殊測試通道，
    讓工廠測試機台可以快速檢查所有功能。
    正常使用時這個通道是鎖住的，不會影響產品。
```

> **AI 內部動作**：選 B → 加 Test Mode（7V trigger + pattern）、加 scan chain DFT、加 0xEC test command

### 總結確認

```
AI: 太好了！我幫你整理一下你的設計決策：

    📦 產品：Lightning 充電線認證晶片
    
    ✅ 相容性：業界標準格式（大部分充電器可用）
    ✅ 功能：充電 + 識別 + 序號追蹤
    ✅ 省電：待機自動省電（降低 60% 待機耗電）
    ✅ 充電控制：基本款（自動握手 + 自動斷開）
    ✅ 出廠資料：裝置編號 + 產品序號（64 字元空間）
    ✅ 校準：不需要（充電線不需要高精度）
    ✅ 測試：完整測試（確保品質）
    
    有沒有哪一項想修改的？
    確認後我就會開始產生完整的設計文件，
    然後自動幫你走完從設計到晶片的流程。

User: 沒有，開始吧！

AI: 收到！正在產生 8 份設計文件...
    這些文件定義了你的晶片的所有細節，
    之後就會自動進入電路設計和佈局階段。
    
    [L1 產品規格書 ✅]
    [L2 功能需求書 ✅]
    [L3 通訊協議書 ✅]
    [L4 記憶體規劃書 ✅]
    [L5 介面規格書 ✅]
    [L6 控制邏輯書 ✅]
    [L7 測試規劃書 ✅]
    [L8 時序規格書 ✅]
    
    全部完成！接下來進入電路設計階段（Phase 2）...
```

---

## 對話原則：取捨說明模板

每個問題都用這個結構：

```
AI: [用日常語言描述選擇]
    
    A) [選項名稱]
       ✅ [好處，用使用者在乎的語言]
       ❌ [代價，用使用者在乎的語言]
       → 適合：[什麼產品/情境適合]
    
    B) [選項名稱]
       ✅ [好處]
       ❌ [代價]
       → 適合：[什麼產品/情境適合]
```

---

## 術語翻譯對照表

AI 內部用技術術語做決策，但對使用者永遠用日常語言：

| 技術術語 | 使用者聽到的說法 |
|---------|----------------|
| CRC-8, init value | 「通訊格式」「相容性設定」 |
| OTP (One-Time Programmable) | 「永久記憶區」「出廠寫入一次就不能改的空間」 |
| CC control (Charge Control) | 「充電管理」「充電通道的開關」 |
| Trim register | 「出廠校準」「個別調校」 |
| Clock domain / CDC | 「省電模式」「不同速度的工作節奏」 |
| Oscillator | 「內部時鐘」 |
| Disconnect detection | 「拔出偵測」「自動斷開」 |
| FSM (state machine) | 不需要跟使用者提 |
| Test Mode | 「工廠測試通道」 |
| Engineer Mode | 「工程校準模式」 |
| DFT / Scan chain | 「品質檢查功能」 |
| Power-on reset | 「開機初始化」 |
| Lock bits | 「防竄改保護」 |
| Synth wrapper | 不需要跟使用者提 |
| MOS switch | 「電子開關」 |
| Open-drain | 不需要跟使用者提 |
| Pull-up / Pull-down | 不需要跟使用者提 |
| OVP / OCP / UVLO | 「過壓保護」「過電流保護」「低電壓保護」 |
| Bandgap reference | 不需要跟使用者提 |
| IBIAS | 不需要跟使用者提 |
| Break / IBT | 不需要跟使用者提 |
| VID / PID | 「裝置編號」「產品編號」 |
| MSN / ASN | 「產品序號」「配件序號」 |
| Wake pulse | 「喚醒信號」 |
| Register space | 「運行時暫存空間」→ 但其實不需要跟使用者提 |

### 原則：如果一個技術決策不影響使用者的產品體驗，AI 就自己決定，不要問。

**自動決定（不問使用者）：**
- CRC polynomial（一定是 0x31）
- Reset 架構（根據省電選擇自動決定）
- Clock divider chain（根據省電選擇自動決定）
- RX/TX bit timing（根據相容性自動決定）
- PAD control logic（根據充電控制選擇自動決定）
- OTP lock mechanism（根據安全需求自動決定）
- Synth wrapper design（自動決定）
- Response packet format（根據相容性自動決定）

**需要問使用者（影響產品/成本/體驗）：**
- 相容性等級（影響能不能用）
- 功能範圍（影響成本和複雜度）
- 省電需求（影響電池壽命或發熱）
- 充電控制（影響安全性）
- 出廠資料（影響售後和追蹤）
- 校準需求（影響精度和工廠成本）
- 測試等級（影響良率和品質）

---

## 不同產品情境的預設方案

### 情境 A：充電線（成本敏感）
```
相容性: B（業界標準）  功能: B（ID+序號）  省電: B（待機省電）
充電: B（基本）        出廠: B（ID+序號）    校準: A（不需要）
測試: B（完整）
→ 預估：8 commands, 64B OTP, 無 trim, 有 Test Mode
```

### 情境 B：智慧感測器（精度重要）
```
相容性: C（完全相容）  功能: C（完整）      省電: C（電池供電）
充電: A（不需要）      出廠: C（完整履歷）    校準: B（需要）
測試: B（完整）
→ 預估：13 commands, 128B OTP, 有 trim, 有 Engineer Mode + Test Mode
```

### 情境 C：簡單配件（極簡）
```
相容性: A（基本）     功能: A（只充電）     省電: A（不重要）
充電: B（基本）       出廠: A（只有 ID）     校準: A（不需要）
測試: A（基本）
→ 預估：4 commands, 16B OTP, 無 trim, 無 Test Mode
```

---

## Decision Trace 機制 — 讓專家能介入修改

### 問題

使用者說「跟大部分充電器相容」→ AI 決定 CRC init=0xFF。
但如果專家審查後認為目標市場其實需要 init=0x00 呢？

**不能要求使用者重新跑整個對話。**
**專家應該能只改這一個決策，其他不動。**

### 解法：Decision Trace Log

每份設計文件的每個技術參數，都記錄三件事：
1. **使用者原話**：他說了什麼
2. **AI 推理**：AI 為什麼選這個值
3. **技術參數**：最終的技術決策

```json
{
  "decision_trace": [
    {
      "id": "D001",
      "user_said": "跟大部分充電器相容",
      "question_id": "Q1",
      "ai_reasoning": "「大部分相容」= 業界標準 AID 1.0，CRC 需與 Apple 標準一致",
      "technical_decisions": [
        {"param": "crc_polynomial", "value": "0x31", "document": "L3"},
        {"param": "crc_init", "value": "0xFF", "document": "L3"},
        {"param": "crc_method", "value": "bit_serial", "document": "L3"},
        {"param": "protocol_version", "value": "AID_1.0", "document": "L3"},
        {"param": "command_set", "value": "full_13", "document": "L3"}
      ]
    },
    {
      "id": "D002",
      "user_said": "充電 + 識別 + 序號追蹤",
      "question_id": "Q2",
      "ai_reasoning": "序號追蹤需要 IMSN+ASN 儲存，至少 46 bytes OTP",
      "technical_decisions": [
        {"param": "otp_size", "value": "64", "document": "L4"},
        {"param": "otp_regions", "value": ["ID:6B", "IMSN:20B", "ASN:20B", "lock:1B", "reserved:17B"], "document": "L4"},
        {"param": "commands_included", "value": ["0x74","0x70","0x72","0x76","0x78","0x7A","0xE0","0xE2"], "document": "L3"}
      ]
    },
    {
      "id": "D003",
      "user_said": "希望待機時不要太耗電",
      "question_id": "Q3",
      "ai_reasoning": "待機省電需要多時脈域 + disconnect 後關閉 oscillator",
      "technical_decisions": [
        {"param": "clock_domains", "value": 4, "document": "L2"},
        {"param": "clock_frequencies", "value": ["5MHz","2.5MHz","625KHz","312.5KHz"], "document": "L2"},
        {"param": "protocol_clock", "value": "2.5MHz", "document": "L2"},
        {"param": "disconnect_osc_shutdown", "value": true, "document": "L6"},
        {"param": "disconnect_threshold_us", "value": 76.4, "document": "L8"}
      ]
    },
    {
      "id": "D004",
      "user_said": "基本充電控制就好",
      "question_id": "Q4",
      "ai_reasoning": "基本充電控制 = CC_EN + RD_ENB + 700ms timeout，不含 OVP/OCP",
      "technical_decisions": [
        {"param": "cc_control", "value": true, "document": "L6"},
        {"param": "cc_en_trigger", "value": "after_0x74_id_cmd", "document": "L6"},
        {"param": "cc_reset_timeout_ms", "value": 700, "document": "L6"},
        {"param": "rd_enb_control", "value": "via_0x70_bit3", "document": "L6"},
        {"param": "ovp_ocp", "value": false, "document": "L5"}
      ]
    },
    {
      "id": "D005",
      "user_said": "裝置編號 + 產品序號",
      "question_id": "Q5",
      "ai_reasoning": "ID(6B)+IMSN(20B)+ASN(20B)=46B 最小，預留到 64B",
      "technical_decisions": [
        {"param": "otp_total_bytes", "value": 64, "document": "L4"},
        {"param": "otp_id_bytes", "value": 6, "document": "L4"},
        {"param": "otp_imsn_bytes", "value": 20, "document": "L4"},
        {"param": "otp_asn_bytes", "value": 20, "document": "L4"},
        {"param": "otp_lock_mechanism", "value": "3_region_2bit_each", "document": "L4"}
      ]
    },
    {
      "id": "D006",
      "user_said": "不需要校準，我是做充電線的",
      "question_id": "Q6",
      "ai_reasoning": "充電線不需要高精度，省略 trim 可簡化設計和工廠流程",
      "technical_decisions": [
        {"param": "bg_trim", "value": false, "document": "L4"},
        {"param": "osc_trim", "value": false, "document": "L4"},
        {"param": "ibias_trim", "value": false, "document": "L4"},
        {"param": "engineer_mode", "value": false, "document": "L7"},
        {"param": "cmd_0x7C_trim", "value": false, "document": "L3"},
        {"param": "cmd_0x7E_soft_reset", "value": false, "document": "L3"}
      ]
    },
    {
      "id": "D007",
      "user_said": "完整測試，我們第一次做，品質先顧好",
      "question_id": "Q7",
      "ai_reasoning": "首次量產用完整測試確保良率，包含 Test Mode + DFT",
      "technical_decisions": [
        {"param": "test_mode", "value": true, "document": "L7"},
        {"param": "test_mode_entry", "value": "7V_trigger_cc_pattern", "document": "L7"},
        {"param": "test_cmd_0xEC", "value": true, "document": "L3"},
        {"param": "dft_scan_chain", "value": true, "document": "L7"},
        {"param": "external_clock_mode", "value": true, "document": "L7"}
      ]
    }
  ],
  "auto_decisions": [
    {
      "id": "A001",
      "param": "crc_polynomial",
      "value": "0x31",
      "reason": "AID 1.0 協議規定，無選擇空間",
      "document": "L3"
    },
    {
      "id": "A002",
      "param": "reset_sources",
      "value": ["POR", "disconnect", "otp_load"],
      "reason": "由 D003 省電選擇自動推導：多時脈域需要 multi-source reset",
      "derived_from": "D003",
      "document": "L2"
    },
    {
      "id": "A003",
      "param": "rx_synchronizer_stages",
      "value": 3,
      "reason": "多時脈域架構需要 3-stage 同步器防止 metastability",
      "derived_from": "D003",
      "document": "L5"
    }
  ]
}
```

### 專家審查流程

```
Phase 1 完成
    ↓
產出 Design Documents v1 + Decision Trace Log
    ↓
專家收到審查請求（可以是內部工程師或外部顧問）
    ↓
專家對每個 Decision 有三個選擇：
    [✅ 同意]  [🔧 直接修改]  [💬 追問使用者]
```

#### 路徑 A：專家直接修改（不需要打擾使用者）

適用情境：使用者的意圖很清楚，但 AI 的技術翻譯有誤。

```
┌─────────────────────────────────────────────────────────┐
│  D006: 校準                                              │
│  使用者說：「不需要校準，我是做充電線的」                    │
│  AI 決定：不加 trim registers                              │
│                                                          │
│  專家點 [🔧 直接修改]：                                    │
│                                                          │
│  修改內容：osc_trim = true                                │
│  修改原因：「充電線雖然不需要高精度，                       │
│    但 OSC trim 建議保留，否則量產批次間                     │
│    頻率差異可能導致通訊失敗率偏高。                         │
│    只加 OSC trim，不加 BG/IBIAS trim。」                  │
│                                                          │
│  → AI 自動連帶更新：                                      │
│    - L4 OTP 加 OSC_TRIM 欄位 (1 byte)                    │
│    - L7 加簡化版 Engineer Mode                            │
│                                                          │
│  Trace 記錄：                                             │
│  D006 v1: user="不需要校準" → osc_trim=false              │
│  D006 v2: expert="OSC trim 保留防通訊失敗" → osc_trim=true│
└─────────────────────────────────────────────────────────┘
```

#### 路徑 B：專家追問使用者（使用者的回答不夠具體）

適用情境：使用者說的話太模糊，專家無法判斷正確的技術方向，
需要更多產品背景資訊才能做出好的決策。

```
┌─────────────────────────────────────────────────────────┐
│  D001: 相容性                                            │
│  使用者說：「跟大部分充電器相容」                            │
│  AI 決定：CRC init = 0xFF (Apple 標準)                    │
│                                                          │
│  專家點 [💬 追問使用者]：                                  │
│                                                          │
│  專家看到使用者原話太模糊：「大部分充電器」是哪些？           │
│  專家寫追問（AI 自動翻譯成使用者能懂的語言）：              │
│                                                          │
│  ┌───────────────────────────────────────────────┐       │
│  │ 專家輸入（技術語言）：                          │       │
│  │ 「需要確認目標市場。如果是大陸白牌市場，          │       │
│  │  很多充電器用的是非標準 CRC init=0x00。           │       │
│  │  如果是歐美品牌市場，需要 init=0xFF。」           │       │
│  └───────────────────────────────────────────────┘       │
│              ↓ AI 翻譯                                    │
│  ┌───────────────────────────────────────────────┐       │
│  │ 使用者收到的追問（日常語言）：                    │       │
│  │                                                │       │
│  │ 你好！關於相容性，我們的工程師想多了解一下：       │       │
│  │                                                │       │
│  │ 你的充電線主要賣去哪個市場？                     │       │
│  │                                                │       │
│  │ A) 主要賣大陸市場                               │       │
│  │    （大陸很多充電器用的通訊格式跟國際版稍有不同，  │       │
│  │     選這個可以確保在大陸市場的相容性最高）          │       │
│  │                                                │       │
│  │ B) 主要賣歐美日市場                              │       │
│  │    （國際市場的充電器都用統一的標準格式）           │       │
│  │                                                │       │
│  │ C) 兩邊都賣                                     │       │
│  │    （需要同時支援兩種格式，晶片會稍微複雜一點）    │       │
│  └───────────────────────────────────────────────┘       │
│                                                          │
│  使用者回覆：「B，主要賣歐美。」                           │
│                                                          │
│  → AI 確認：CRC init = 0xFF 維持不變                      │
│  → 但 Decision Trace 更豐富了：                            │
│                                                          │
│  Trace 記錄：                                             │
│  D001 v1: user="大部分相容" → CRC init=0xFF               │
│  D001 v2: expert asked="目標市場?" →                      │
│           user replied="主要賣歐美" →                      │
│           confirmed: CRC init=0xFF (with stronger basis)  │
└─────────────────────────────────────────────────────────┘
```

#### 路徑 B 的另一個結果：使用者的回答改變了決策

```
┌─────────────────────────────────────────────────────────┐
│  同上場景，但使用者回覆不同：                               │
│                                                          │
│  使用者回覆：「A，主要賣大陸。」                            │
│                                                          │
│  → AI 重新推導：目標大陸市場 → CRC init = 0x00             │
│  → 連鎖影響分析：                                         │
│    - L3 Protocol: CRC init 0xFF → 0x00                   │
│    - L3 Protocol: CRC method bit_serial → byte_parallel  │
│    - L8 Timing: response timing 微調                     │
│                                                          │
│  Trace 記錄：                                             │
│  D001 v1: user="大部分相容" → CRC init=0xFF               │
│  D001 v2: expert asked="目標市場?" →                      │
│           user replied="主要賣大陸" →                      │
│           changed: CRC init=0x00, method=byte_parallel    │
│           reason: 大陸白牌市場標準不同                      │
└─────────────────────────────────────────────────────────┘
```

### 專家審查的完整流程圖

```
            Design Documents v1
                    │
                    ▼
        ┌─── Expert Review ───┐
        │                     │
   每個 Decision:              │
        │                     │
   ┌────┴────┐                │
   │         │                │
 [✅同意]  需要改？             │
           │                  │
      ┌────┴────┐             │
      │         │             │
  [🔧直接改]  [💬追問]         │
      │         │             │
      │    AI 翻譯成            │
      │    日常語言問題          │
      │         │             │
      │    使用者回答            │
      │         │             │
      │    AI 重新推導           │
      │    技術決策             │
      │         │             │
      └────┬────┘             │
           │                  │
     更新 Decision             │
     + 連鎖影響分析             │
           │                  │
           ▼                  │
        ┌──┴──┐               │
        │     │               │
     有影響  無影響             │
        │     │               │
   更新其他    │               │
   Documents  │               │
        │     │               │
        └──┬──┘               │
           │                  │
           ▼                  │
    Design Documents v2 ◄─────┘
    (全部 Decision reviewed)
```

### 文件版本管理

```
v1 — AI 根據使用者對話自動產生
     decision_trace.json 記錄所有決策來源
     
v2 — 專家審查後修改
     兩種修改方式：
     a) 專家直接改（標註：誰改的、改了什麼、為什麼）
     b) 專家追問使用者 → 使用者補充回答 → AI 重新推導
     兩種都記錄在 trace 裡，自動連鎖更新受影響的文件
     
v3 — ECO（工程變更）
     量產後發現問題，需要修改設計
     一樣追溯到哪個 decision 需要改
```

### Decision Trace JSON — 支援追問記錄

```json
{
  "id": "D001",
  "question_id": "Q1",
  "history": [
    {
      "version": "v1",
      "timestamp": "2026-04-15T10:00:00Z",
      "type": "user_answer",
      "user_said": "跟大部分充電器相容",
      "ai_reasoning": "大部分相容 = AID 1.0 + Apple CRC 標準",
      "decisions": {"crc_init": "0xFF", "protocol": "AID_1.0"}
    },
    {
      "version": "v2",
      "timestamp": "2026-04-16T14:30:00Z",
      "type": "expert_askback",
      "expert_name": "王工程師",
      "expert_question_technical": "需要確認目標市場，大陸白牌用 CRC init=0x00",
      "ai_translated_question": "你的充電線主要賣去哪個市場？A)大陸 B)歐美日 C)兩邊都賣",
      "user_replied": "主要賣歐美",
      "ai_re_derived": "歐美市場 = Apple 標準 = CRC init=0xFF（維持不變）",
      "decisions": {"crc_init": "0xFF"},
      "changed": false,
      "confidence": "high (user confirmed specific market)"
    }
  ]
}
```

另一個追問改變決策的例子：

```json
{
  "id": "D004",
  "question_id": "Q4",
  "history": [
    {
      "version": "v1",
      "type": "user_answer",
      "user_said": "基本充電控制就好",
      "decisions": {"ovp": false, "ocp": false}
    },
    {
      "version": "v2",
      "type": "expert_askback",
      "expert_name": "李工程師",
      "expert_question_technical": "無 OVP/OCP 在快充場景有安全風險，需確認是否支援快充",
      "ai_translated_question": "再確認一下：你的充電線會用在快充嗎？快充電壓比較高(9V/12V)，如果會的話建議加一個安全保護功能，成本大約多 2 美分/顆，但可以避免過壓損壞手機的風險。",
      "user_replied": "會用快充，那加保護好了",
      "ai_re_derived": "快充 + 安全保護 → 需要 OVP",
      "decisions": {"ovp": true, "ocp": false},
      "changed": true,
      "cascade_updates": ["L5: 加 OVP pad 控制", "L6: 加 OVP 觸發邏輯", "L1: 更新 pin list"]
    }
  ]
}
```

### 連鎖更新規則

當專家修改一個 decision 時，AI 自動檢查：

```
修改 D006: osc_trim = false → true
    ↓
影響分析：
  L4 Memory Map:
    → 需要新增 OTP address for OSC_TRIM_CODE[5:0]
    → OTP size 可能需要增加
  L3 Command Protocol:
    → 需要新增或修改 trim 相關命令？
    → 若加 Engineer Mode → 需要 0x7C command
  L7 Test & Debug:
    → 工廠需要新增 trim 校準步驟
    → Engineer Mode entry sequence 需定義
  L8 Timing:
    → trim 校準的 timing 需求
  L2 FRS:
    → 功能需求增加校準項目
    
AI 列出所有影響，專家確認後一次性更新所有文件。
```

### 完整追溯鏈

```
使用者說「不需要校準」
    ↓ D006
AI 決定: osc_trim = false
    ↓ v1
專家改: osc_trim = true（理由：批次頻率差異風險）
    ↓ v2
自動更新: L4 加 OSC_TRIM, L7 加簡化 Engineer Mode
    ↓
Phase 2: spec-to-rtl 讀取 v2 文件 → RTL 包含 OSC trim logic
    ↓
Phase 3: 33-step flow → GDS
    ↓
量產後 ECO: 發現 trim range 不夠 → 回溯到 D006 → 修改 v3
```

**每一個技術參數都能追溯回「使用者說了什麼」或「專家為什麼改」。**
**這就是 Vibe-IC 的可追溯性保證。**

---

## Phase 1 Multi-Agent 架構

### 完整流程

```
使用者
  │
  │ 日常語言對話
  ▼
┌──────────────────────────────────────┐
│  Agent 1: PM (Product Manager)       │
│                                      │
│  角色：產品經理                        │
│  語言：日常用語，零術語                 │
│  能力：理解產品需求，引導取捨決策        │
│  輸出：Design Documents v1            │
│       + Decision Trace Log           │
└──────────────┬───────────────────────┘
               │
               │ v1 文件 + trace
               ▼
┌──────────────────────────────────────┐
│  Agent 2: IC Expert                  │
│  (+Human Expert 初期協助)             │
│                                      │
│  角色：晶片設計專家                    │
│  語言：技術語言（內部）                │
│  能力：                               │
│    ✓ 檢查完整性（有沒有漏掉的項目？）   │
│    ✓ 檢查可行性（技術上做不做得到？）    │
│    ✓ 檢查衝突（A 和 B 會不會矛盾？）   │
│    ✓ 檢查必要性（少了什麼會導致失敗？）  │
│    ✓ 補充隱含需求（使用者沒想到但必須有） │
│                                      │
│  兩種動作：                            │
│    🔧 直接修正（使用者意圖清楚時）       │
│    💬 追問使用者（需要更多資訊時）       │
│        ↓                              │
│    追問經 PM Agent 翻譯成日常語言       │
│    使用者回答後 AI 重新推導              │
│                                      │
│  輸出：Design Documents v2 (final)    │
│       + Updated Decision Trace       │
└──────────────┬───────────────────────┘
               │
               │ v2 文件
               ▼
        Phase 2/3: RTL → GDS
```

### Agent 1: PM Agent — 做什麼

PM Agent 負責第一輪對話，目標是把使用者的產品需求轉換成 v1 設計文件。

**PM Agent 的規則：**
- 永遠用日常語言，不用任何技術術語
- 用取捨框架引導選擇（✅好處 / ❌代價 / →適合什麼產品）
- 幫使用者做 7 個主要決策（相容性、功能、省電、充電、資料、校準、測試）
- 對於不影響使用者的純技術決策，AI 自己決定不問
- 記錄每個決策的完整 trace（使用者說了什麼 → AI 推導了什麼）

**PM Agent 不做的事：**
- 不做技術可行性判斷（那是 IC Expert 的工作）
- 不做跨決策衝突檢查（那是 IC Expert 的工作）
- 不補充使用者沒提到的隱含需求（那是 IC Expert 的工作）

### Agent 2: IC Expert Agent — 做什麼

IC Expert 拿到 v1 文件後，用專業知識做深度審查。

**IC Expert 的審查清單：**

```
1. 完整性檢查
   □ 8 層文件每一層都有內容嗎？
   □ 有沒有遺漏的功能區塊？
   □ 每個指令的 request/response 格式完整嗎？
   □ Memory map 有沒有地址衝突或空洞？

2. 可行性檢查
   □ 這個時脈架構在目標製程下可行嗎？
   □ OTP 大小在目標 foundry 有對應的 IP 嗎？
   □ 功耗估算合理嗎？
   □ 面積估算在目標封裝放得下嗎？

3. 衝突檢查
   □ 省電模式跟即時回應需求有沒有矛盾？
   □ CC 控制時序跟 disconnect 偵測會不會打架？
   □ Test mode 跟正常模式有沒有共用資源衝突？
   □ Lock 機制跟 Engineer mode 的行為一致嗎？

4. 必要性檢查
   □ 使用者選了「不需要校準」，但目標製程的頻率散佈大不大？
   □ 使用者選了「基本充電」，但有沒有安全相關的保護是必須加的？
   □ 有沒有法規/認證要求是使用者沒想到的？

5. 隱含需求補充
   □ 上電序列需要定義（使用者不會想到）
   □ ESD 保護策略（使用者不會想到）
   □ 晶片內部的 power domain 劃分（使用者不會想到）
   □ Reset 去抖動和同步（使用者不會想到）
```

**IC Expert 發現問題時的處理方式：**

| 問題類型 | 動作 | 範例 |
|:---------|:-----|:-----|
| AI 翻譯錯誤 | 🔧 直接修正 | PM 把「省電」翻譯成 2 時脈域，Expert 改成 4 時脈域 |
| 技術衝突 | 🔧 直接修正 | disconnect timeout 跟 CC reset 時序衝突，Expert 調整 |
| 隱含必要項 | 🔧 直接補充 | 使用者沒提 ESD，但一定需要，直接加 |
| 使用者意圖不明 | 💬 追問使用者 | 「大部分充電器」具體是哪個市場？ |
| 取捨需使用者決定 | 💬 追問使用者 | 快充要不要加過壓保護？成本多 2 美分 |

### IC Expert 需要更多使用者資訊時的流程

**IC Expert 永遠不直接跟使用者對話。**
Expert 把技術需求告訴 PM，PM 負責設計使用者能理解的問題。
兩個 Agent 先互相溝通，確認問題「技術上問到位」又「使用者聽得懂」，然後 PM 才去問。

```
IC Expert 發現問題
    │
    │ 技術需求（Agent 間內部對話）
    ▼
┌─────────────────────────────────────────────────┐
│  Expert → PM 的內部對話（使用者看不到）            │
│                                                  │
│  Expert: 「D004 有安全風險。OVP 在 9V/12V 快充    │
│    場景是必要項。使用者選了基本充電，但我需要知道   │
│    他的線是否用於快充。                            │
│    如果是快充，OVP 不是選配，是安全必須。           │
│    另外我還需要知道最大充電電壓是多少，              │
│    才能決定 OVP threshold 要設在哪。」              │
│                                                  │
│  PM: 「了解。但使用者不知道什麼是 OVP，            │
│    也不一定知道自己的充電電壓。                     │
│    我這樣問好不好：                                │
│    『你的充電線會搭配什麼樣的充電器？               │
│     A) 一般 5V 充電器                              │
│     B) 快充充電器（像 iPhone 快充那種）              │
│     C) 不確定，客戶可能各種都有 』                  │
│    這樣可以嗎？」                                  │
│                                                  │
│  Expert: 「差一點。B 和 C 我需要區分 9V 跟 12V。   │
│    能不能把 B 拆成：                                │
│    B1) 9V 快充（iPhone/Android 常見的）             │
│    B2) 12V 以上快充（筆電充電器等級的）              │
│    這影響 OVP 的保護等級和成本。」                   │
│                                                  │
│  PM: 「好，但選項太多使用者會猶豫。                  │
│    我簡化成：                                      │
│    A) 一般充電（5V）                               │
│    B) 手機快充（通常 9V，像 iPhone 快充）            │
│    C) 高功率充電（筆電等級，12V 以上）               │
│    D) 不確定                                       │
│    然後我加一句：如果選 B 或 C，會加一個              │
│    安全保護功能，成本差別我也說清楚。                 │
│    這樣技術資訊夠嗎？」                              │
│                                                  │
│  Expert: 「夠了。B→OVP 9V, C→OVP 12V,             │
│    D→保守用 OVP 12V。成本差異：                     │
│    A 不加 OVP = 省 1 美分                           │
│    B 加 9V OVP = +1 美分                            │
│    C 加 12V OVP = +2 美分                           │
│    你可以把成本寫進選項裡。」                        │
│                                                  │
│  PM: 「完美，我去問了。」                           │
└─────────────────┬───────────────────────────────┘
                  │
                  │ PM 帶著精心設計的問題去問使用者
                  ▼
┌─────────────────────────────────────────────────┐
│  PM → 使用者的對話                                 │
│                                                  │
│  PM: 「再確認一個問題：                             │
│    你的充電線會搭配什麼樣的充電器？                  │
│                                                  │
│    A) 一般充電（5V）                               │
│       → 不需要額外保護，成本不變                    │
│                                                  │
│    B) 手機快充（像 iPhone 快充那種，通常 9V）        │
│       → 建議加安全保護，成本約多 1 美分/顆           │
│       → 防止電壓異常時損壞手機                      │
│                                                  │
│    C) 高功率充電（筆電充電器等級，12V 以上）          │
│       → 需要更強的安全保護，成本約多 2 美分/顆        │
│                                                  │
│    D) 不確定，客戶可能各種充電器都有                  │
│       → 會用最高規格的保護（+2 美分），比較保險      │
│                                                  │
│    這個安全保護功能可以防止充電器電壓不穩定時         │
│    傷到手機，快充場景蠻建議加的。」                  │
│                                                  │
│  User: 「B，我們主要做手機快充線。」                 │
└─────────────────┬───────────────────────────────┘
                  │
                  │ PM 帶答案回去給 Expert
                  ▼
┌─────────────────────────────────────────────────┐
│  PM → Expert 的內部對話                            │
│                                                  │
│  PM: 「使用者選了 B，手機快充 9V。」                │
│                                                  │
│  Expert: 「好。更新 D004：                         │
│    ovp = true, ovp_threshold = 9V                │
│    連鎖更新：                                     │
│    L5 加 OVP pad + threshold setting              │
│    L6 加 OVP trigger → shutdown logic             │
│    L1 pin list 加 OVP sense pin                   │
│    L8 加 OVP response timing                      │
│    決策確認，這題結案。」                           │
└─────────────────────────────────────────────────┘
```

### 為什麼兩個 Agent 要先互相討論？

**只有 Expert 問 → 問題太技術：**
> 「你需要 OVP 嗎？threshold 要 9V 還是 12V？」
> → 使用者：「什麼是 OVP？什麼是 threshold？」

**只有 PM 問 → 問題太模糊：**
> 「你需要安全保護嗎？」
> → 使用者：「需要吧？」
> → Expert 拿到答案後：「...可是我還是不知道 threshold 要設多少」

**兩個 Agent 合作 → 問題剛好：**
> 「你的線搭配什麼充電器？A)一般5V B)手機快充9V C)筆電12V D)不確定」
> → 使用者：「B」
> → Expert 直接對應：OVP threshold = 9V ✅

**PM 確保使用者聽得懂，Expert 確保技術資訊收得到。**

### Agent 間溝通的規則

```
1. Expert 發起請求時必須說明：
   - 我需要知道什麼（技術需求）
   - 為什麼需要（影響哪個設計決策）
   - 每個可能答案對應什麼技術選擇
   - 有沒有成本/效能差異可以給使用者參考

2. PM 設計問題時的原則：
   - 選項不超過 4 個（太多使用者選不了）
   - 每個選項附帶使用者在乎的影響（成本、效能、安全）
   - 如果有「建議選項」就標出來
   - 用使用者熟悉的東西類比（「像 iPhone 快充那種」）

3. PM 對問題沒把握時可以反問 Expert：
   - 「這樣問夠嗎？」
   - 「我少問了什麼？」
   - 「使用者如果選 D 你要怎麼處理？」

4. 來回次數沒有限制，但目標是：
   - 1 次 Agent 間對話 = 1 個完美的使用者問題
   - 不要問使用者兩次同一件事
   - 使用者的每次回答都要能直接對應技術決策
```

### Human Expert 培訓 AI Expert 的機制

```
早期（v0.1 — v0.5）：

    IC Expert Agent 做初步審查
         │
         ▼
    Human Expert 看 Agent 的審查結果
         │
    ┌────┴────┐
    │         │
  Agent 漏了   Agent 做對了
    │         │
    │    Human 確認 ✅
    │    （AI 學到：這類判斷是對的）
    │
  Human 補充修正
    │
  記錄到 Knowledge Base：
  「場景 X + 條件 Y → 必須檢查 Z」
  「使用者說 A 但其實隱含 B」
  「製程 P 的限制是 Q，影響 R」
    │
  AI Expert 下次遇到類似場景
  自動執行這個檢查
```

```
中期（v0.5 — v1.0）：

    IC Expert Agent 做完整審查
    + 主動套用 Knowledge Base 的規則
         │
         ▼
    Human Expert 只做抽查
    （每 5 個案子抽 1 個）
         │
    ┌────┴────┐
    │         │
  沒問題      有遺漏
    │         │
  Human 簽核   Human 補充
  AI 信心 +1   + 更新 Knowledge Base
```

```
成熟期（v1.0+）：

    IC Expert Agent 獨立審查
    Human Expert 只在以下情況介入：
    - 全新的 IC 類別（從沒做過的）
    - AI 信心度低於閾值的決策
    - 使用者指定要人工審查
```

### Knowledge Base 結構

IC Expert 的知識庫隨時間累積：

```json
{
  "rules": [
    {
      "id": "R001",
      "source": "Human Expert 王工程師, 2026-04-16",
      "trigger": "使用者選了「不需要校準」且製程 >= 180nm",
      "action": "建議保留 OSC trim，180nm 製程 RC 頻率散佈大",
      "severity": "warning",
      "times_applied": 12,
      "times_confirmed": 11,
      "confidence": 0.92
    },
    {
      "id": "R002",
      "source": "Human Expert 李工程師, 2026-04-20",
      "trigger": "產品用於快充(>5V) 且沒有 OVP",
      "action": "必須追問使用者加 OVP，這是安全項不是選配",
      "severity": "critical",
      "times_applied": 8,
      "times_confirmed": 8,
      "confidence": 1.0
    },
    {
      "id": "R003",
      "source": "IC-A 案例學習, 2026-04-15",
      "trigger": "AID 1.0 protocol 且目標市場含大陸",
      "action": "追問使用者確認 CRC init，大陸白牌市場可能用 0x00",
      "severity": "info",
      "times_applied": 3,
      "times_confirmed": 2,
      "confidence": 0.67
    }
  ]
}
```

### 兩個 Agent 的角色對比

| | PM Agent | IC Expert Agent |
|:---|:---|:---|
| **對話對象** | 使用者 | 使用者（透過翻譯）+ Human Expert |
| **語言** | 日常用語 | 技術語言（內部）→ 日常語言（對外）|
| **目標** | 理解需求，引導選擇 | 驗證可行性，補齊缺口 |
| **決策風格** | 「你想要什麼？」 | 「這樣做行不行？少了什麼？」|
| **知識來源** | 產品常識 + 取捨框架 | Knowledge Base + Human Expert 指導 |
| **輸出** | v1 文件 + trace | v2 文件 + updated trace |
| **成長方式** | 固定（UX 優化） | 持續學習（Knowledge Base 擴充）|

---

*Generated by Vibe-IC UX Design — 2026-04-15*
*Principle: 使用者不需要懂晶片，只需要懂自己的產品*
*Principle: 專家能修改任何決策，不需要重來*
*Principle: AI Expert 從 Human Expert 學習，逐漸獨立*
