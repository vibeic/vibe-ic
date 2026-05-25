# Vibe-IC Database Selection Analysis

**Date**: 2026-04-07

---

## 需求分析

### 現在要存什麼

| 資料類型 | 筆數 | 大小 | 查詢模式 |
|----------|------|------|---------|
| IC 參數 (factual metadata) | 36 → 10,000+ | 小 (~1KB/IC) | Filter + search |
| IC pins | ~300 → 100,000+ | 小 | Join with IC |
| IP manifests | 6 → 500+ | 小 (~2KB/IP) | Filter by PDK/interface |
| Design results (manifest) | 20 → 1,000+ | 小 | Latest per design |
| Datasheet URLs | 36 → 10,000+ | 小 | Lookup |

### 未來要存什麼

| 資料類型 | 筆數 | 大小 | 查詢模式 |
|----------|------|------|---------|
| Vector embeddings (semantic search) | 10,000+ | 大 (~1KB/vector × 768 dim) | ANN (近似最近鄰) |
| User designs | 100+ | 中 (GDS paths, configs) | CRUD |
| Design run history | 10,000+ | 中 (logs, metrics) | Time-series |
| IP dependency graph | 500+ | 小 | Graph traversal |
| User accounts (if SaaS) | 100+ | 小 | Auth |

### 關鍵需求

1. **語義搜尋 (Vector Search)** — 用戶說「I2C 溫度感測器」→ 找到 LM75, TMP102 等
2. **結構化查詢** — 過濾 VDD 3.3V + I2C + SOT-23 的 IC
3. **JSON 儲存** — IP manifest, design config 是 JSON/YAML
4. **可嵌入 / 可獨立** — 開源用戶可以本地跑，SaaS 版本可以雲端
5. **與現有基礎設施相容** — 伺服器群已有 PostgreSQL

---

## 選項比較

### Option A: SQLite（現況）

| 優點 | 缺點 |
|------|------|
| 零設定，檔案即資料庫 | 無 vector search |
| Git 可 commit | 單用戶，無並行寫入 |
| 開源用戶零門檻 | 無 JSON 原生操作（有限支援） |
| 完美適合 CLI 工具 | 不適合 SaaS |

**適合**：開源分發版（用戶本地跑）

### Option B: PostgreSQL + pgvector

| 優點 | 缺點 |
|------|------|
| **你的伺服器已經有 4 個 PostgreSQL** | 需要設定 |
| **pgvector** 擴充直接支援 vector search | 比 SQLite 重 |
| JSONB 原生支援 | 開源用戶需要裝 PostgreSQL |
| 全文搜尋 (tsvector) 內建 | — |
| 多用戶並行、ACID | — |
| PostGIS 可做地理查詢（未來） | — |
| 業界標準，生態成熟 | — |

**適合**：自架 SaaS + 進階功能

### Option C: MySQL

| 優點 | 缺點 |
|------|------|
| <host> 已有 MySQL | **無原生 vector search** |
| 簡單 | JSONB 支援不如 PostgreSQL |
| — | 你的其他服務都用 PostgreSQL |

**不推薦**：功能不足且與現有架構不一致

### Option D: 專用 Vector DB（Milvus / ChromaDB / Pinecone）

| 優點 | 缺點 |
|------|------|
| Vector search 效能最好 | 多一個服務要維護 |
| ChromaDB 可嵌入（像 SQLite） | 不適合結構化查詢 |
| — | 需要同時維護兩個 DB |

**適合**：只有在 pgvector 效能不夠時才考慮

### Option E: PostgreSQL + pgvector + SQLite（混合架構）

| 層 | 用途 | DB |
|----|------|-----|
| 開源分發 | 用戶本地的 IC 參數搜尋 | SQLite（檔案，git 可 commit） |
| 自架服務 | 完整 IC KB + vector search + 用戶管理 | PostgreSQL + pgvector |
| MCP tool | 查詢介面 | 自動偵測：有 PostgreSQL 用它，沒有用 SQLite |

---

## 推薦：PostgreSQL + pgvector（主力）+ SQLite（分發用）

### 理由

1. **你已經有 PostgreSQL** — <host> (port 5432) 已跑 Fund CRM + Doc，加一個 DB 零成本
2. **pgvector 完美解決語義搜尋** — 不需要額外的 ChromaDB/Milvus
3. **JSONB 存 IP manifest** — `SELECT * FROM ips WHERE manifest->>'interface' = 'I2C'`
4. **全文搜尋內建** — `WHERE to_tsvector(description) @@ to_tsquery('temperature & sensor')`
5. **SQLite 作為離線分發格式** — 開源用戶 `git clone` 就有本地 DB，不需要裝 PostgreSQL
6. **Migration path 清楚** — SQLite → PostgreSQL 的 schema 幾乎一樣

### 架構

```
開源用戶（本地）              Vibe-IC 服務（<host>）
┌──────────────┐             ┌─────────────────────────┐
│ SQLite        │             │ PostgreSQL + pgvector    │
│ ic_knowledge.db│            │ ┌─────────────────────┐ │
│ (36 ICs)      │  ← sync →  │ │ ic_knowledge DB     │ │
│ 只讀          │             │ │ 10,000+ ICs         │ │
└──────────────┘             │ │ + vector embeddings  │ │
                              │ │ + user designs       │ │
                              │ │ + IP library         │ │
                              │ └─────────────────────┘ │
                              └─────────────────────────┘
```

### 實作步驟

| Step | Task | Timeline |
|------|------|----------|
| 1 | 在 <host> 建立 `vibe_ic` PostgreSQL database | 30 min |
| 2 | 安裝 pgvector 擴充 | 10 min |
| 3 | 移植現有 SQLite schema 到 PostgreSQL | 1 hour |
| 4 | 匯入 36 ICs + 31 JSON params | 30 min |
| 5 | 加入 vector embedding 欄位（用 OpenAI/local embedding） | 2 hours |
| 6 | MCP tool `eda_ic_search` 支援雙 backend | 2 hours |
| 7 | 保留 SQLite 作為離線 export | 30 min |

### PostgreSQL Schema（擴充 pgvector）

```sql
-- 在現有 schema 基礎上加入 vector search
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE ics ADD COLUMN embedding vector(768);  -- for semantic search
ALTER TABLE ics ADD COLUMN manifest JSONB;         -- for IP manifest storage

-- 向量搜尋索引
CREATE INDEX ON ics USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- 全文搜尋索引
ALTER TABLE ics ADD COLUMN search_vector tsvector;
UPDATE ics SET search_vector = to_tsvector('english', coalesce(name,'') || ' ' || coalesce(description,''));
CREATE INDEX ON ics USING gin(search_vector);

-- 混合搜尋（結構化 + 語義 + 全文）
-- 用戶說「3.3V I2C temperature sensor」→ 
-- 1. 全文搜尋: search_vector @@ to_tsquery('temperature & sensor')
-- 2. 參數過濾: vdd_typ = 3.3 AND interface = 'I2C'  
-- 3. 語義排序: ORDER BY embedding <=> query_embedding
```

---

## 結論

| 場景 | 用什麼 |
|------|--------|
| 開源用戶本地 | SQLite（現有 ic_knowledge.db） |
| Vibe-IC 服務端 | **PostgreSQL + pgvector**（on <host>:5432） |
| 語義搜尋 | pgvector（不需要額外的 ChromaDB） |
| IP manifests | PostgreSQL JSONB |
| 全文搜尋 | PostgreSQL tsvector |
| MCP tool | 自動偵測 backend（SQLite fallback） |

**不用 MySQL**（功能不足）。**不用獨立 vector DB**（pgvector 夠用）。**不用換掉 SQLite**（保留作為離線格式）。
