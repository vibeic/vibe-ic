# Phase 1: Design Document Stack — Vibe-IC 的核心架構

**日期**：2026-04-15
**來源**：IC-A 真實晶片設計文件逆向分析
**目的**：定義從 prompt 到可製造晶片所需的完整文件層次

---

## 核心洞見

> **Datasheet 只佔完整設計資訊的 20-30%。**
> 剩餘 70-80% 是 vendor 內部設計文件，這些文件包含了讓 RTL 正確實作的所有關鍵決策。
>
> **如果 Phase 1 只產生 datasheet，Phase 2/3 的 RTL 就只能猜測其餘 70-80%。**
> BENCH-A vs IC-A 的 23% 功能覆蓋率就是證據。

### Vibe-IC 的解法

```
使用者 prompt
    ↓
Phase 1: AI 對話 → 產出完整 Design Document Stack（8 份文件）
    ↓
Phase 2: Design Documents → RTL → Verification → Synthesis
    ↓
Phase 3: Physical Design → Sign-off → GDS
```

---

## Design Document Stack（8 層）

根據 IC-A 真實設計文件分析，一顆完整 IC 需要以下 8 類設計文件：

```
┌─────────────────────────────────────────────────┐
│  L1  Product Datasheet                          │ ← 對外公開
│       (腳位、電氣特性、功能概述)                    │
├─────────────────────────────────────────────────┤
│  L2  Functional Requirements Spec (FRS)         │ ← 內部設計決策
│       (完整功能需求、行為描述)                      │
├─────────────────────────────────────────────────┤
│  L3  Command Protocol Spec                      │ ← 通訊協議細節
│       (指令集、payload、response、CRC、timing)     │
├─────────────────────────────────────────────────┤
│  L4  Memory Map / Register Spec                 │ ← 記憶體架構
│       (OTP/RAM/Register 地址、位元欄位、lock)       │
├─────────────────────────────────────────────────┤
│  L5  Analog-Digital Interface Spec              │ ← 類比數位邊界
│       (pad 功能、控制邏輯、trim code)              │
├─────────────────────────────────────────────────┤
│  L6  Control Logic Spec                         │ ← 內部控制行為
│       (CC 控制、power sequence、discharge)        │
├─────────────────────────────────────────────────┤
│  L7  Test & Debug Spec                          │ ← 量產測試
│       (Test Mode、Engineer Mode、ATE 流程)        │
├─────────────────────────────────────────────────┤
│  L8  Timing & Waveform Spec                     │ ← 時序驗證
│       (bit timing、response timing、波形序列)      │
└─────────────────────────────────────────────────┘
```

---

## 各層詳細定義

### L1: Product Datasheet（產品規格書）

**對應 IC-A 文件**：`IC-A_Short_Datasheet_0v06.pdf`
**現有 skill**：`datasheet-gen`（已存在）
**內容**：
- 產品概述、應用場景
- 腳位定義（pin name, type, description）
- 電氣特性（VDD, I/O levels, ESD）
- 封裝資訊
- 功能方塊圖
- 簡要命令列表

**覆蓋 BENCH-A 差距**：0%（datasheet 本來就有，不是瓶頸）

---

### L2: Functional Requirements Specification (FRS)（功能需求規格）

**對應 IC-A 文件**：`MDV-A1101-FRS.doc`（2.7MB）
**需要新 skill**：`frs-gen`
**內容**：
- 完整功能需求（每個功能的輸入/輸出/行為/邊界條件）
- 狀態機行為描述（文字版，非 RTL）
- 時脈架構決策（為什麼需要 5 級分頻？功耗考量？）
- Reset 策略（幾種 reset 來源？上電序列？）
- 錯誤處理策略（CRC 失敗怎麼辦？timeout 怎麼辦？）
- 功耗策略（何時關閉 oscillator？低功耗模式？）

**覆蓋 BENCH-A 差距**：
- 時脈架構（5 域 vs 1 域）→ FRS 會定義「需要多時脈域以降低功耗」
- Reset 序列（3-source vs 1-source）→ FRS 會定義「需要 POR + disconnect + OTP-load reset」
- 功耗策略 → FRS 會定義「disconnect 後關閉 oscillator」

**AI 對話範例**：
```
User: 我要設計一顆 AID bus slave IC，需要低功耗
AI: 了解。為了低功耗，我建議：
    1. 主時脈 5MHz，但內部用分頻鏈（2.5M/1.25M/625K/312.5K）
    2. Protocol 處理用 2.5MHz（降低 dynamic power）
    3. Wake/disconnect 用 625K/312.5K（最低功耗）
    4. Disconnect 後關閉 oscillator
    這樣合理嗎？
User: 合理，disconnect threshold 要多長？
AI: 建議 70-80µs（48 counts @625KHz），太短會誤觸發...
```

---

### L3: Command Protocol Specification（指令協議規格）

**對應 IC-A 文件**：
- `CMD整理 .xlsx`（指令集整理）
- `RX_EVENT.txt`（RX 事件處理流程）
- `70指令控制說明.txt`（個別指令詳細說明）
- `la_protocal/fpga.csv`（真實波形佐證）

**需要新 skill**：`cmd-protocol-gen`
**內容**：
- 完整指令表（command code, payload bytes, response code, response bytes）
- 每個指令的詳細行為（Set State 的每個 bit 代表什麼？）
- CRC 演算法細節（polynomial, init value, residual check）
- 協議狀態機（Break → Command → Data → CRC → Response）
- RX 驗證流程（收到封包後的 9 步驗證順序）
- 錯誤處理（CRC fail、長度錯誤、未知指令）
- VID/PID 驗證（哪些指令需要？）

**覆蓋 BENCH-A 差距**：
- 5 個缺失指令 → 協議規格會完整列出 13 個指令
- CRC init 值 → 協議規格會明確定義 init=0xFF
- Response 長度差異 → 協議規格會精確定義每個 response 的 byte 數
- RX 驗證流程 → 目前完全缺失的 RX_CHK 邏輯

**AI 對話範例**：
```
User: AID protocol 的 CRC 要用什麼？
AI: AID 1.0 使用 CRC-8，但有兩種常見實作：
    1. Polynomial 0x31, init 0x00（MAXIM/Dallas）
    2. Polynomial 0x31, init 0xFF（shift register, bit-serial）
    Apple Lightning 原始規格用的是 init=0xFF 的 bit-serial 版本。
    你要用哪一個？
User: init=0xFF，跟原始規格相容
AI: 好。那 CRC 計算方式是 bit-serial（每 bit 一次 shift），
    不是 byte-parallel。這會影響工作時脈選擇...
```

---

### L4: Memory Map / Register Specification（記憶體暨暫存器規格）

**對應 IC-A 文件**：
- `IC-A_OTP_Table.xlsx`（OTP 完整地址表）
- `digital_interface.xlsx`（暫存器欄位定義）

**需要新 skill**：`regmap-gen`
**內容**：
- OTP/NVM 記憶體 Map（每個地址的用途、reset 值、lock 狀態）
- 暫存器空間定義（間接暫存器、status register、control register）
- Bit field 定義（每個 bit 的名稱、R/W、reset value、功能）
- Lock 機制（哪些區域可 lock？lock 後的行為？）
- OTP 燒錄流程（program timing、verify、VPP 要求）
- Auto-load 序列（上電時從 OTP 載入到 register 的順序）

**覆蓋 BENCH-A 差距**：
- OTP 大小 47B→128B → regmap 會定義完整 128 byte 空間
- Register space 缺失 → regmap 會定義 0x80-0x9F 間接暫存器
- Lock 機制簡化 → regmap 會定義多區域 lock + AL flag
- Auto-load 缺失 → regmap 會定義上電載入序列
- Trim code 缺失 → regmap 會定義 BG_TRIM, OSC_TRIM, IBIAS_SET

**AI 對話範例**：
```
User: OTP 需要存什麼？
AI: 根據 AID 1.0 協議，至少需要：
    - ID (6B) + IMSN (20B) + ASN (20B) = 46B 最小
    但真實 IC 通常還需要：
    - Trim codes: BG_TRIM(1B), OSC_TRIM(1B), IBIAS(1B) = 3B
    - Lock bits: 至少 3B（ID/IMSN/ASN 各自 lock）
    - Extended data: Mount Assembly(20B), Factory Hash(14B), Lock Bits(3B)
    建議 128B OTP。要不要也加 register space？
User: register space 是什麼？
AI: 間接暫存器，用 OTP address 的高位元存取，但不是真的燒 OTP。
    用途：runtime status（PH/PT/SV/PF/AL/PA/TEST）+ program timing counter。
    IC-A 用 0x80-0x9F 這個地址範圍...
```

---

### L5: Analog-Digital Interface Specification（類比數位介面規格）

**對應 IC-A 文件**：
- `digital_interface.xlsx`（所有 analog-digital 邊界信號）
- `類比確認.docx`（類比區塊確認）

**需要新 skill**：`adi-spec-gen`（Analog-Digital Interface）
**內容**：
- 每個 pad 的數位控制信號列表（OE, DO, DI, PU, PD）
- ID_BUS pad 控制（open-drain, pull-down, HV detect）
- CC pad 控制（CC_EN, RD_ENB, CC_18 monitor）
- Oscillator 控制（OSC_ENB, trim input）
- Power 保護信號（OVP, OCP, UVLO）
- Bias/Reference（BG_TRIM, IBIAS_SET）
- Synth wrapper 需求（哪些信號需要 split i/o/oe）

**覆蓋 BENCH-A 差距**：
- PAD_CTRL 模組完全缺失 → ADI spec 會定義所有 pad 控制邏輯
- CC 相關信號缺失 → ADI spec 會定義 CC_EN/RD_ENB/CC_18
- OVP/OCP 保護缺失 → ADI spec 會定義保護信號介面
- Synth wrapper 不完整 → ADI spec 會定義所有 bidirectional 信號

---

### L6: Control Logic Specification（控制邏輯規格）

**對應 IC-A 文件**：
- `CC控制.txt`（CC 控制邏輯完整說明）
- `CC_Reset測試結果.txt`（CC Reset 行為 11 點詳細說明）
- `70指令控制說明.txt`（MOS switch 控制邏輯）
- `波形圖.xlsx`（power sequence 波形）

**需要新 skill**：`control-logic-gen`
**內容**：
- CC 控制邏輯（CC_EN 何時開/關、RD_ENB 何時開/關）
- CC Reset 行為（700ms timeout、與 70 指令的交互、11 條規則）
- Power sequence（上電→OTP load→reset release→ready）
- Disconnect 行為（OUT1 discharge、OUT2 status、oscillator shutdown）
- OUT1/OUT2 控制邏輯（PH 控制、discharge latch、ANA_DLY_EN）
- PT switch 控制（何時開、何時關、與 wake 的交互）

**覆蓋 BENCH-A 差距**：
- CC 控制 0% → control-logic spec 會完整定義
- Disconnect 後的複雜行為 → 會定義 OSC shutdown + CC reset + 700ms timer
- OUT1/OUT2 的 discharge 邏輯 → 會定義 analog latch 行為
- PT switch 與 MAC 的交互 → 會定義 real_pt_switch_on/off

**AI 對話範例**：
```
User: CC control 要怎麼設計？
AI: 根據 AID 協議，CC 控制有三個關鍵行為：
    1. CC_EN 預設 0（CC_IN 和 CC_OUT 斷開）
    2. 收到 0x74 ID command 後 CC_EN=1（連通）
    3. ID_BUS 回到 LOW 觸發 disconnect 後 CC_EN 回到 0
    
    另外還需要 CC_Reset 機制：
    - ID_BUS 由 HIGH→LOW 且 MPD_CAP 有電時觸發
    - 將 RD_ENB 設為 1（斷開 RD5K）
    - 持續 700ms 或直到電容耗盡
    - 期間 70 指令無法覆蓋此狀態
    
    這 11 條規則都要在 control logic spec 中明確寫出...
```

---

### L7: Test & Debug Specification（測試除錯規格）

**對應 IC-A 文件**：
- `TestMode說明.txt`（Test Mode 進入方式，4 個版本）
- `EngineerMode.txt`（Engineer Mode 完整流程）
- `test mode.pdf`

**需要新 skill**：`test-debug-gen`
**內容**：
- Test Mode（量產 ATE 測試）
  - 進入方式（ID_BUS 7V + CC pattern + data confirmation）
  - 外部 clock 替代內部 oscillator
  - ATE clock output（CC_18 → ate_clk5m）
  - 退出方式（斷電）
  - 與 74 指令的交互（收到 74 後鎖定 Test Mode 進入）
- Engineer Mode（工程調試）
  - 進入方式（連續兩個 0x74：payload 27 43 → A5 89）
  - 0x7C 頻率調整（AA BB CC DD 參數，±20%/±10%/±3%/±1%）
  - 0x7E soft reset（trim register 保留）
  - 無視 OTP LockBit
  - Trim → verify wake pulse → E0 寫入 OTP 流程
- DFT 需求（scan chain, BIST, boundary scan）

**覆蓋 BENCH-A 差距**：
- Test Mode 完全缺失 → test-debug spec 會定義完整 ATE 流程
- Engineer Mode 完全缺失 → 會定義 trim/calibration 流程
- 0x7C/0x7E 指令缺失 → 會定義這兩個 Engineer Mode 專用指令

---

### L8: Timing & Waveform Specification（時序波形規格）

**對應 IC-A 文件**：
- `fpga_timing/Timing.txt` + 12 個日期版本的 timing 文件
- `20230103-3.txt`（timing 參數 + response timing）
- `波形圖.xlsx`（信號序列波形）

**需要新 skill**：`timing-waveform-gen`
**內容**：
- Bit timing 參數（H1 min/max, H0 min/max, Break min/max）
- Response timing（每個 command 的 response latency，cycles 為單位）
- Inter-Byte Timing（IBT min/max）
- Wake pulse timing（width, period）
- Disconnect timing（threshold, grace period）
- Power sequence waveform（上電→CC detect→cable insert→charge）
- CC Reset waveform（trigger→700ms hold→release）
- 各信號的時序關係圖

**覆蓋 BENCH-A 差距**：
- Bit timing 常數不同 → timing spec 會精確定義（基於 2.5MHz 而非 5MHz）
- Response timing 缺驗證數據 → timing spec 會定義 expected 值
- Wake timing 不同 → timing spec 會定義 312.5KHz-based pulse

---

## 文件層次 vs BENCH-A 差距對應

| BENCH-A 差距 | 根因：缺少哪層文件？ |
|------------|-------------------|
| CRC init 0x00 vs 0xFF | **L3** Command Protocol |
| 工作時脈 5MHz vs 2.5MHz | **L2** FRS（時脈架構決策）|
| 5 個擴展指令缺失 | **L3** Command Protocol |
| CC 控制缺失 | **L6** Control Logic |
| OTP 47B vs 128B | **L4** Memory Map |
| Register space 缺失 | **L4** Memory Map |
| Test Mode 缺失 | **L7** Test & Debug |
| Engineer Mode 缺失 | **L7** Test & Debug |
| Trim/校準缺失 | **L4** Memory Map + **L5** ADI |
| PAD_CTRL 缺失 | **L5** ADI |
| Reset 序列簡化 | **L2** FRS |
| Disconnect 後 OSC 關閉 | **L6** Control Logic |
| RX_CHK 驗證缺失 | **L3** Command Protocol |
| Collision detection 缺失 | **L3** Command Protocol |
| Response 長度差異 | **L3** Command Protocol |
| 多時脈域缺失 | **L2** FRS |

**如果 Phase 1 產出了完整的 L1-L8 文件，這 16 個差距全部可以在 RTL 生成前就解決。**

---

## Phase 1 Workflow（使用者體驗）

```
Step 1: 使用者輸入 prompt
   "我要設計一顆 AID 1.0 bus slave IC，用在 Lightning cable 裡，
    需要 OTP 存 ID/MSN/ASN，支援充電控制，能量產測試"

Step 2: AI 產出 L1 Datasheet（draft）
   → 使用者 review、修改腳位/封裝/電壣

Step 3: AI 對話產出 L2 FRS
   → "時脈要幾個域？" → "低功耗需要分頻鏈"
   → "Reset 需要幾種？" → "POR + disconnect + OTP-load"
   → "功耗策略？" → "disconnect 後關 oscillator"

Step 4: AI 對話產出 L3 Command Protocol
   → "CRC 用什麼 init 值？" → "0xFF，與 Apple 規格相容"
   → "要支援幾個指令？" → "13 個（0x70-0xEC）"
   → "每個指令的 response 格式？" → 逐一定義

Step 5: AI 對話產出 L4 Memory Map
   → "OTP 需要多大？" → "128 bytes"
   → "需要 register space 嗎？" → "是，runtime status"
   → "哪些 trim code？" → "BG, OSC, IBIAS, timing"

Step 6: AI 對話產出 L5 ADI Spec
   → "哪些 pad 需要 analog 控制？" → "ID_BUS, CC, OUT1, OUT2"
   → "保護電路？" → "OVP, OCP, UVLO"

Step 7: AI 對話產出 L6 Control Logic
   → "CC 什麼時候開？" → "收到 0x74 後"
   → "CC Reset 行為？" → "700ms timeout，11 條規則"

Step 8: AI 對話產出 L7 Test & Debug
   → "量產怎麼測？" → "Test Mode: 7V trigger + CC pattern"
   → "工程調試？" → "Engineer Mode: 連續 0x74 特定 payload"

Step 9: AI 對話產出 L8 Timing
   → "bit timing 基準？" → "2.5MHz = 400ns/clk"
   → "response latency？" → "~90 cycles per command"

Step 10: 完整 Design Document Stack → Phase 2/3
   → spec-to-rtl 讀取 L2-L8 → 生成完整 RTL
   → 33-step flow → GDS
```

---

## 新增 Skill 清單

| Skill | 輸入 | 輸出 | 對應文件層 |
|-------|------|------|----------|
| `datasheet-gen` | prompt | L1 Datasheet | L1（已存在）|
| `frs-gen` | L1 + 對話 | L2 FRS | L2（**新增**）|
| `cmd-protocol-gen` | L1 + L2 + 對話 | L3 Command Protocol | L3（**新增**）|
| `regmap-gen` | L2 + L3 + 對話 | L4 Memory Map | L4（**新增**）|
| `adi-spec-gen` | L1 + L2 + 對話 | L5 ADI Spec | L5（**新增**）|
| `control-logic-gen` | L2 + L3 + L4 + 對話 | L6 Control Logic | L6（**新增**）|
| `test-debug-gen` | L2 + L4 + 對話 | L7 Test & Debug | L7（**新增**）|
| `timing-waveform-gen` | L2 + L3 + 對話 | L8 Timing & Waveform | L8（**新增**）|

**現有 skill**：1 個（datasheet-gen）
**需要新增**：7 個
**總計 Phase 1 skills**：8 個

---

## Design Document Stack 的輸出格式

每份文件輸出為 **結構化 JSON + 人類可讀 Markdown**：

```json
{
  "document_type": "L3_COMMAND_PROTOCOL",
  "version": "1.0",
  "ic_name": "IC-A",
  "commands": [
    {
      "code": "0x74",
      "name": "ID Command",
      "direction": "host_to_device",
      "payload_bytes": 2,
      "response_code": "0x75",
      "response_bytes": 8,
      "crc": {"polynomial": "0x31", "init": "0xFF", "check": "residual_zero"},
      "behavior": {
        "first_time": "set have_received_id_cmd, enable CC_EN, trigger wake",
        "subsequent": "respond with ID only, no wake",
        "engineer_mode_entry": "payload 27 43 → A5 89 sequence"
      }
    }
  ]
}
```

**這個 JSON 格式可以直接被 Phase 2 的 `spec-to-rtl` 讀取，不需要 AI 再次解釋文件。**

---

## 與現有系統的關係

### 現有 spec.json
目前的 `spec.json` 只包含 L1 層級的資訊（clock, reset, pins, PDK）。
Design Document Stack 擴展了 spec.json 為 8 層結構。

### 現有 33-step flow
33-step flow 是 Phase 2/3，它的輸入從「spec.json + RTL」變成「Design Document Stack + RTL」。
RTL 的品質直接取決於 Document Stack 的完整度。

### 功能覆蓋率預測

| Phase 1 輸出 | 預期 RTL 功能覆蓋率 |
|-------------|-------------------|
| 只有 L1 Datasheet | ~23%（BENCH-A 現狀）|
| L1 + L2 FRS | ~40% |
| L1-L3（含 Protocol） | ~55% |
| L1-L4（含 Memory Map） | ~65% |
| L1-L6（含 Control Logic） | ~80% |
| L1-L8（完整 Stack） | **~95%** |

---

*Generated by Vibe-IC Phase 1 Architecture Analysis — 2026-04-15*
*Evidence: IC-A real chip design documents (93 files, ~100MB)*
