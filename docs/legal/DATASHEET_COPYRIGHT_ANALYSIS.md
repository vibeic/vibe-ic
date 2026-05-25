# Datasheet 著作權與法律風險分析

**Date**: 2026-04-07
**Status**: 商業化前必須諮詢 IP 律師
**Disclaimer**: 以下基於公開判例和法律分析整理，非法律意見

---

## 核心結論

**收集 datasheet 有風險，但可透過架構設計大幅降低。**

安全路線：**提取事實參數（不受著作權保護）+ 連結原始來源（不儲存原文）+ AI 生成新文件（transformative use）**

---

## 三層風險分析

### 1. Datasheet 著作權

- Datasheet 本身受著作權保護（TI ToS 明確聲明）
- TI 曾對 Datasheet Archive 發 DMCA takedown（2021）
- **但**：純事實性資料（電壓、pin 定義、timing 數值）不受著作權保護
- 法律依據：[Feist v. Rural (1991)](https://www.casemine.com/commentary/us/feist-v.-rural:-establishing-the-originality-requirement-for-copyrighting-directories/view) — facts are not copyrightable

### 2. AI 訓練 / RAG 的 Fair Use

| 判例 | 年份 | 結果 | 與我們的關係 |
|------|------|------|------------|
| Bartz v. Anthropic | 2025/06 | AI 訓練是 fair use（transformative） | 有利 — 但需合法取得資料 |
| Kadrey v. Meta | 2025/06 | AI 訓練是 fair use | 有利 |
| Thomson Reuters v. ROSS | 2025/02 | 不是 fair use（建立競爭產品） | **風險** — 如果我們直接輸出原文 |

**關鍵區別**：生成新的 datasheet（transformative）vs 輸出原文（替代原始來源）

### 3. RAG 特有風險

- 2025/02：14 家新聞出版商控告 Cohere 的 RAG 系統
- 2025/04：歐盟法院受理第一個 RAG 著作權案
- RAG 風險 > 純訓練：可能**直接檢索並呈現**原始內容
- 歐盟 Database Directive：即使資料不受著作權保護，大量提取資料庫仍可能違法

---

## 安全架構設計

### Layer 1: Metadata（✅ 安全）

只儲存結構化技術參數（事實，不受著作權保護）：

```json
{
  "ic_name": "LM75",
  "manufacturer": "TI",
  "vdd_min": 2.7, "vdd_max": 5.5,
  "interface": "I2C",
  "resolution_bits": 9,
  "accuracy_celsius": 2.0,
  "package": "SOT-23-5"
}
```

### Layer 2: 連結（✅ 安全）

不儲存 PDF 原文，只存原廠 URL：

```json
{
  "datasheet_url": "https://www.ti.com/lit/ds/symlink/lm75b.pdf",
  "source": "ti.com",
  "accessed": "2026-04-07"
}
```

如同 Octopart 的做法 — 導向原始來源。

### Layer 3: AI 生成（✅ 最安全）

基於多份參考 IC 的參數**生成全新 datasheet**：
- 不複製任何一份 datasheet 的文字
- 結合多個來源的事實性參數
- 產出客製化的新文件
- 這是 transformative use，法律風險最低

### ❌ 不要做

- 不要直接 host datasheet PDF 供用戶下載
- 不要把整段 datasheet 文字存入向量 DB 做 RAG 檢索
- 不要在輸出中直接引用大段原文
- 不要爬取有 robots.txt 禁止的網站

---

## 資料來源分級

| 等級 | 來源 | 風險 | 處理方式 |
|------|------|------|---------|
| 🟢 A | Open PDK 文件（Apache 2.0） | 零 | 直接使用 |
| 🟢 A | OpenCores/Efabless IP 文件 | 零 | 直接使用，遵守授權 |
| 🟡 B | 原廠公開 datasheet 的事實參數 | 低 | 提取參數，不存原文 |
| 🟡 B | Application Notes 的電路圖/參數 | 低 | 提取參數，連結原文 |
| 🔴 C | 整份 PDF 原文 | 高 | 不儲存，只存 URL |
| 🔴 C | 需 NDA 的 PDK/設計文件 | 高 | 需正式授權 |

---

## 商業化前必做的法律準備

1. **諮詢 IP 律師**（熟悉 AI + 著作權交叉領域）
2. **建立資料來源分級制度**（A/B/C 三級）
3. **準備 DMCA 應對流程**（收到 takedown 能快速移除）
4. **Terms of Service 明確揭露**：AI 生成的 datasheet 是參考文件，非官方規格
5. **歐盟合規**：EU AI Act + Database Directive（如在歐盟營運）
6. **考慮加入 CHIPS Alliance**：推動半導體資料開放共享標準
7. **洽談 Data Partnership**：與 TI、NXP 等大廠談正式再利用授權

---

## 對 IC Knowledge Base 架構的影響

原本計畫的三層架構需要調整：

```
原本計畫:
  Layer 1: Metadata (SQLite)        ← ✅ 保留
  Layer 2: Vector Embeddings        ← ⚠️ 只嵌入自有/開源文件
  Layer 3: Raw Documents (S3)       ← ❌ 不儲存原廠 PDF

調整後:
  Layer 1: Metadata (SQLite)        ← ✅ 事實參數（不受著作權保護）
  Layer 2: Vector Embeddings        ← ✅ 只嵌入 Level A 來源
  Layer 3: URL Index                ← ✅ 連結到原始來源
  Layer 4: AI-Generated Datasheets  ← ✅ 我們自己生成的文件
```

---

## References

- [TI Terms of Use](https://www.ti.com/legal/terms-conditions/terms-of-use.html)
- [Feist v. Rural (1991)](https://www.casemine.com/commentary/us/feist-v.-rural:-establishing-the-originality-requirement-for-copyrighting-directories/view)
- [2025 AI Copyright Decisions — IPWatchdog](https://ipwatchdog.com/2025/12/23/copyright-ai-collide-three-key-decisions-ai-training-copyrighted-content-2025/)
- [AI Fair Use — Crowell & Moring](https://www.crowell.com/en/insights/client-alerts/ai-companies-prevail-in-path-breaking-decisions-on-fair-use)
- [RAG Copyright Risk — 36Kr](https://eu.36kr.com/en/p/3422429684387205)
- [EU Database Directive](https://en.wikipedia.org/wiki/Database_right)
