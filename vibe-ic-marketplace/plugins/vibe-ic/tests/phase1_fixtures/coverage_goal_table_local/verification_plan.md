

| 測試類別 | 判定 | 範圍 |
|---|---|---|
| Random message functional equivalence vs NIST golden | **100% PASS (binary)** | ≥ 1000 random message lengths(0-2KB),每個對 reference Python hashlib.sha256 比對 |
| 邊角 — message length | 100% PASS | 1 byte / 55 bytes(single-block boundary)/ 56 bytes / 64 bytes / 119 bytes / 120 bytes / 1024 bytes |
| 邊角 — protocol | 100% PASS | INIT during BUSY / NEXT without prior INIT / read DIGEST during BUSY / write BLOCK during BUSY |
| Mode switch | 100% PASS | INIT SHA-256 → INIT SHA-224 → INIT SHA-256 順序測試 |

